"""Ventana rodante: avance de la materialización + poda de lo que quedó vacío atrás.

Motor del comando `advance_class_windows`, en el molde comando-fino/servicio-gordo que ya
usa `expire_and_notify_plans` → `services/plan_expiry_notifications.py`.

El Prompt 1 le puso un TOPE a la materialización: `materialization_window_cap` no deja
crear nada más allá de `hoy + Organization.class_generation_window_days` (default 21). Ese
tope, solo, congelaría el calendario: una serie sin `end_date` se quedaría sin clases
nuevas en cuanto la ventana se consuma, porque nada vuelve a llamar a la generación después
del alta. Este módulo es la otra mitad —el que EMPUJA la ventana—: corre a diario, vuelve a
pedirle a cada serie viva que materialice (esta vez con un `hoy` más nuevo, o sea un tope
más lejano) y borra las instancias que se quedaron atrás sin ninguna historia.

Tres fases por organización, SIEMPRE en este orden (ver `advance_windows_for_org`):

1. **extender** la ventana de materialización (`_extend_windows`),
2. **consolidar** el estado de lo que ya arrancó (`_sync_statuses` → `sync_class_statuses`),
3. **podar** lo que quedó vacío atrás, con un colchón de gracia (`_prune_past_empty_classes`).

QUÉ DECIDE ESTE MÓDULO Y QUÉ NO
-------------------------------
No decide cuán lejos se materializa (eso es `materialization_window_cap`), ni cómo se
auto-inscribe y se cobra una instancia nueva (eso es
`sync_recurring_enrollments_for_generated_instances` → `reserve_student_in_class`, que
`generate_instances_for_template_range` ya dispara solo), ni cómo se borra una clase sin
dejar saldo fantasma (eso es `_delete_class_refunding_consumption`). Acá solo vive la
ORQUESTACIÓN: a quién llamar, dentro de qué transacción, y qué hacer cuando una pieza
falla. Nada de esto se reimplementa: si el tope o el cobro cambian, cambian en un solo
lugar y este job los hereda.

Lo que sí decide:

1. **La granularidad de la transacción: una por serie y una por clase, ninguna global.**
   `generate_instances_for_template_range` ya es `@transaction.atomic`, así que la serie que
   falla queda intacta —sin instancias a medias ni consumos huérfanos— y las anteriores ya
   están commiteadas. La poda abre su propia `atomic()` por clase por la misma razón: el
   reverso de consumo y el `DELETE` de una clase tienen que ser un solo hecho. Una corrida
   interrumpida a mitad (deploy, OOM del contenedor) deja trabajo PARCIAL pero siempre
   consistente, y la corrida de mañana continúa donde quedó: extender es idempotente
   (`duplicate_instance`) y podar también (lo ya borrado no vuelve a ser candidato).

2. **Un error no puede tumbar la corrida.** El job es multi-tenant y desatendido: sin
   try/except por serie, por clase y por organización, una fila corrupta de un gimnasio
   dejaría a TODOS los demás sin calendario nuevo, en silencio y en cada corrida (el mismo
   razonamiento que la guarda por organización de `run_expiry_notifications`).

3. **La poda es por ESTADO + HISTORIA, no por serie.** Ver `_prune_candidates`: entran las
   pasadas `scheduled` Y las `completed` —el estado no alcanza para saber si la clase se
   dictó, porque el sync cierra solo toda `scheduled` pasada; quien lo sabe son las
   cuatro FK de historia—, entran también las clases sueltas (`class_template=None`), y no
   entra ninguna clase que alguien haya tocado ni ninguna que un humano haya cerrado,
   cancelado o suspendido a mano.

4. **Borrar SIEMPRE por el camino que reembolsa** (`_delete_class_refunding_consumption`),
   nunca `.delete()` directo — aunque el filtro garantice cero consumos. Es defensa: si el
   filtro tuviera un hueco, el reverso devuelve el saldo antes de que la CASCADE de
   `ConsumptionLog.class_instance` se lleve el log y deje `classes_used` inflado.

5. **Cuándo se poda: nunca apenas termina, sino después de un COLCHÓN.** Ver
   `_pruning_cutoff`. La poda mira `end_datetime < now - class_pruning_grace_days` (default
   7): borrar en el barrido de la mañana siguiente no deja margen para el backfill tardío
   —pasar lista el lunes por la clase del viernes— ni para deshacer nada a mano, y el
   borrado es IRREVERSIBLE. El colchón es por organización y `0` es un valor válido (podar
   apenas termina) para quien quiera el comportamiento anterior.

6. **Que el estado esté consolidado ANTES de juzgar.** Ver `_sync_statuses`: el flip a
   `completed` y el `TeacherPaymentRecord` del profe los crea `sync_class_statuses`, que
   hasta ahora solo corría cuando alguien abría el dashboard. Sin esa fase acá, si la clase
   vacía se podaba antes de que un humano entrara a la app, la liquidación de ese dictado
   nunca nacía: el resultado del job dependía del tráfico web. Ahora el job la corre él
   mismo y decide sobre estado consolidado.
"""
import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from ..models import ClassTemplate, GymClass, Organization
from .class_status import sync_class_statuses
from .recurrence import _delete_class_refunding_consumption, generate_instances_for_template_range
from .reports_occupancy import record_occupancy_snapshot

logger = logging.getLogger(__name__)


def _error_line(kind, obj_id, exc):
    """Una línea de error legible por el comando. Se guarda como STRING a propósito: el
    summary lo imprime `advance_class_windows` tal cual, sin conocer estructura."""
    return f'{kind} {obj_id}: {exc.__class__.__name__}: {exc}'


def _extend_windows(org, summary):
    """Pieza 1: le pide a cada serie viva de la org que materialice hasta el tope de HOY.

    Se llama a `generate_instances_for_template_range` con SOLO el template, sin
    `from_date` ni `until_date`: los defaults (hoy → `hoy + ventana de la org`) son
    exactamente el rango que este job quiere, y pasar fechas propias acá sería una segunda
    definición de la ventana compitiendo con `materialization_window_cap`.

    Lo que ya hace esa función y NO se repite acá: skipea duplicados
    (`duplicate_instance`, por eso correr el job dos veces el mismo día es inocuo), skipea
    feriados, y auto-inscribe + cobra las instancias nuevas a las recurrencias vivas de la
    serie. O sea: el consumo del alumno lo dispara esta llamada, de a una ventana por vez,
    en vez del año entero el día del alta.
    """
    templates = (
        ClassTemplate.objects
        .filter(organization=org, is_active=True)
        # `select_related`: la generación lee `template.organization` en cada plantilla para
        # resolver el tope de la ventana.
        .select_related('organization')
        .order_by('id')
    )
    for template in templates:
        summary['templates_processed'] += 1
        try:
            result = generate_instances_for_template_range(template)
        except Exception as exc:  # noqa: BLE001
            logger.exception('rolling window: extension failed org=%s template=%s', org.id, template.id)
            summary['extension_errors'].append(_error_line('plantilla', template.id, exc))
            continue
        summary['instances_created'] += result['created_count']


def _sync_statuses(org, now, summary):
    """Pieza 2: consolida el estado de las clases de la org que YA arrancaron, antes de podar.

    Es el mismo `sync_class_statuses` que corre el request path (dashboard y listados): cierra
    toda `scheduled`/`in_progress` cuyo horario ya pasó, consolida asistencias y —cuando hay
    una regla de pago activa que matchee— crea el `TeacherPaymentRecord` del profe. Se llama
    ACÁ, y no se deja al azar de que alguien abra la app, porque la poda de la fase 3 juzga
    por estado + historia: una clase vacía podada antes del sync se llevaba consigo la
    liquidación del dictado que nunca llegó a nacer.

    El queryset se acota a `start_datetime__lte=now` para no tocar nada futuro: lo que todavía
    no arrancó no tiene estado que consolidar.

    OJO, eso NO significa que esta fase nunca alcance lo que la fase 1 acaba de crear. La
    generación arranca en `max(template.start_date, timezone.localdate())` y NO descarta un
    horario de HOY que ya pasó (`recurrence.generate_instances_for_template_range`), así que un
    cron corriendo tarde en el día puede materializar la clase de hoy y cerrarla en esta misma
    corrida —completed, ausentes consolidados y `TeacherPaymentRecord` si hay regla—. No es una
    regresión: el request path dejaba exactamente ese mismo estado final en el siguiente
    page-load. Y con el cron off-peak (madrugada) no pasa en la práctica, porque a esa hora la
    instancia de hoy todavía cae adelante de `now`.

    La FASE ENTERA va en un try/except: una clase corrupta no puede dejar sin podar al resto
    de la organización. El try/except NO se baja al loop de a una clase a propósito:
    `sync_class_statuses` es compartido con el request path y su semántica (una excepción
    aborta el sync) no se cambia desde acá.
    """
    try:
        candidates = GymClass.objects.filter(
            organization=org,
            status__in=[GymClass.Status.SCHEDULED, GymClass.Status.IN_PROGRESS],
            start_datetime__lte=now,
        )
        sync_class_statuses(candidates)
    except Exception as exc:  # noqa: BLE001
        logger.exception('rolling window: status sync failed org=%s', org.id)
        summary['sync_errors'].append(_error_line('sync', org.id, exc))


def _pruning_cutoff(org, now):
    """Instante límite de la poda: una clase entra recién cuando terminó ANTES de este
    momento, o sea `now - class_pruning_grace_days` (default 7).

    El colchón existe porque el borrado es IRREVERSIBLE y el barrido corre a diario: sin él,
    la clase del viernes desaparecía el sábado a la mañana y ya no se le podía pasar lista el
    lunes ni deshacer nada a mano. Con el colchón hay una ventana real de backfill tardío y de
    reversibilidad operativa; lo que se paga a cambio son unas filas vacías de más en la base
    durante esos días, que es exactamente el trade que este job quiere.

    La organización llega SIEMPRE desde el queryset del propio job, nunca desde input del
    request (orden 8.3, igual que `materialization_window_cap`). El default del MODELO es la
    única fuente de verdad del 7: la rama de fallback es defensa para una org sin el atributo
    cargado, y ojo con `or` acá —un colchón de 0 días es válido y significa "podar apenas
    termina", el comportamiento anterior a este campo—.
    """
    days = getattr(org, 'class_pruning_grace_days', None)
    if days is None:
        days = Organization._meta.get_field('class_pruning_grace_days').default
    return now - timedelta(days=int(days))


def _prune_candidates(org, now):
    """Clases de la org que se pueden borrar sin perder información: TERMINADAS HACE YA UNOS
    DÍAS, sin cerrar a mano, y sin una sola fila de historia colgando. La regla en una línea:
    **la clase pasó, nadie vino, nadie cobró, y ya pasó el plazo para arrepentirse.**

    Es un helper propio (y no un queryset inline) para poder testear el filtro solo: es la
    parte peligrosa de este módulo, porque un hueco acá borra datos reales.

    Por qué cada condición:

    * `status__in=[SCHEDULED, COMPLETED]` — la clase pasó y no dejó rastro de nadie.
      `COMPLETED` entra porque ese estado NO lo pone una persona: `sync_class_statuses`
      (`services/class_status.py`) cierra toda `scheduled` pasada —lo corre la fase 2 de este
      mismo job y también el request path, en cuanto alguien abre el dashboard o un
      listado—, así que al llegar acá las vacías ya son `completed` y el criterio
      viejo (`status=SCHEDULED`) dejaba esta poda INERTE en la práctica. Una `completed` no es
      historia consolidada por sí misma: la historia vive en las cuatro FK inversas de abajo
      —y la plata del profe en `teacher_payment_records`, que ese mismo sync crea vía
      `calculate_teacher_payment` solo cuando hay una regla de pago activa que matchee; sin
      regla no hay fila, y sin fila no hay nada que preservar—.
      `COMPLETED_EARLY`, `CANCELLED` y `SUSPENDED` quedan afuera SIEMPRE: las tres son una
      acción humana explícita (cerrar antes de hora, cancelar, suspender) y borrarlas sería
      borrar la decisión de alguien, no un hueco vacío del calendario.
    * `end_datetime__lt=cutoff` — TERMINÓ HACE AL MENOS N DÍAS (`_pruning_cutoff`), no solo
      empezó. Dos cosas en una condición. Primero, `end_datetime` y no `start_datetime` (la
      letra original de la spec): por `start_datetime` se podaría una clase que arrancó hace
      10 minutos, sigue `scheduled` y todavía no tiene ni un check-in —sería borrar un
      dictado EN CURSO—. Segundo, el `cutoff` en vez de `now`: la clase tiene que llevar
      terminado el colchón de gracia de la org, porque el borrado es irreversible y hay que
      dejar margen para el backfill tardío (ver `_pruning_cutoff`). Podar futuro (con
      cualquiera de las dos columnas) seguiría sin poder pasar: sería borrar el calendario
      que este mismo job acaba de materializar.
    * los cuatro `__isnull=True` sobre las FK inversas (`enrollments`, `attendances`,
      `consumption_logs`, `teacher_payment_records`) — cada uno arma un LEFT OUTER JOIN con
      `IS NULL`, o sea "no existe ninguna fila relacionada". Con `IS NULL` el join aporta a
      lo sumo una fila nula por clase, así que no hay multiplicación de filas ni hace falta
      `.distinct()`. Alcanza con UNA fila en cualquiera de las cuatro tablas para que la
      clase deje de ser candidata: se prefiere una clase vacía de más en la base antes que
      borrar una inscripción, una asistencia, un consumo o un pago a profesor.
      `enrollments` NO se filtra por `status='active'` a propósito: una inscripción
      `cancelled` también es historia (alguien reservó y se bajó). Por la misma razón se
      cuenta por FILA y no por monto: un `TeacherPaymentRecord` de $0 (regla `per_student`
      que matcheó con 0 alumnos —`calculate_teacher_payment` hace `get_or_create` igual—)
      protege la clase, porque la fila ES el rastro de que hubo liquidación de ese dictado.

    Incluye clases SIN `class_template` (las sueltas, creadas a mano): el criterio es estado
    + historia, no pertenencia a una serie. Una clase suelta que nadie usó y ya pasó es
    exactamente igual de inútil que una de serie.
    """
    return GymClass.objects.filter(
        organization=org,
        status__in=[GymClass.Status.SCHEDULED, GymClass.Status.COMPLETED],
        end_datetime__lt=_pruning_cutoff(org, now),
        enrollments__isnull=True,
        attendances__isnull=True,
        consumption_logs__isnull=True,
        teacher_payment_records__isnull=True,
    )


def _prune_past_empty_classes(org, now, summary):
    """Pieza 3: borra las candidatas, de a una, cada una en su propia transacción."""
    # El colchón se calcula UNA vez para toda la corrida de esta org y se reusa en el
    # re-chequeo lockeado de abajo: los dos filtros —el SELECT de candidatas y el lock— tienen
    # que hablar del MISMO instante. `_pruning_cutoff` es puro (misma org + mismo `now` → mismo
    # valor), así que el `_prune_candidates(org, now)` de adentro del loop coincide exacto.
    cutoff = _pruning_cutoff(org, now)
    # Los ids se materializan ANTES del loop: el queryset se re-evaluaría en cada paso y
    # los borrados de este mismo loop lo irían cambiando debajo (mismo criterio que
    # `cancel_future_instances_for_template`). Además deja fijo qué se examinó, que es lo
    # que el re-chequeo de abajo compara contra el estado del momento del borrado.
    candidate_ids = list(_prune_candidates(org, now).order_by('id').values_list('id', flat=True))

    for class_id in candidate_ids:
        try:
            with transaction.atomic():
                # Re-lectura CON lock de fila y re-chequeo del filtro completo dentro de la
                # transacción del borrado: entre el SELECT de arriba y este DELETE puede
                # haber pasado cualquier cosa (otra corrida del job, un admin cerrando la
                # clase, una inscripción). Si dejó de calificar, se saltea en silencio —no
                # es un error, es el resultado correcto—.
                #
                # El lock se toma sobre la fila de `GymClass` pelada y NO sobre
                # `_prune_candidates`: `SELECT ... FOR UPDATE` sobre el lado nulable de un
                # OUTER JOIN es un error en Postgres, y ese queryset es todo outer joins.
                # (En SQLite el `FOR UPDATE` no se emite; ahí la red es el re-chequeo.)
                # Serializa contra otra corrida del job y contra los escritores que tocan la
                # clase; una reserva concurrente no la toma, pero tampoco existe: la clase
                # ya arrancó (y si ya terminó, con más razón) y `reserve_student_in_class`
                # rechaza el pasado (`class_started`).
                locked = GymClass.objects.select_for_update().filter(
                    pk=class_id,
                    organization=org,
                    # Los estados tienen que ser LOS MISMOS que en `_prune_candidates`: si acá
                    # quedara solo `SCHEDULED`, las `completed` pasarían el SELECT de arriba y
                    # este lock las saltearía en silencio (`locked is None`), dejando la poda
                    # inerte sin un solo error en el summary. Mismo razonamiento para el
                    # colchón: `now` acá y `cutoff` allá dejaría este lock MÁS permisivo que el
                    # filtro (borraría dentro de la gracia si algo forzara el candidato), y al
                    # revés lo dejaría inerte. Los dos predicados se mueven JUNTOS siempre.
                    status__in=[GymClass.Status.SCHEDULED, GymClass.Status.COMPLETED],
                    end_datetime__lt=cutoff,
                ).first()
                if locked is None:
                    continue
                if not _prune_candidates(org, now).filter(pk=class_id).exists():
                    continue

                # RASTRO DE OCUPACIÓN (P3.4) — antes del borrado y DENTRO de la misma
                # transacción. Los dos tienen que ser un solo hecho: si el `DELETE` falla, el
                # rastro no puede quedar, porque el reporte contaría como oferta una clase que
                # sigue viva y la sumaría DOS veces (la fila viva más su snapshot).
                #
                # Por qué el rastro vive acá y NO en `_delete_class_refunding_consumption` (el
                # borrado genérico de clases, que también usan el borrado a mano y el de
                # series): esta es la única vía por la que se destruye oferta SIN que ninguna
                # persona lo haya decidido. Es un borrado automático y masivo de clases que
                # nadie tomó —o sea, justo el dato que el reporte de ocupación necesita para no
                # mentir—, y ocurre en un cron desatendido. Cuando un humano borra una clase
                # está tomando una decisión sobre su propio calendario y sabe lo que se lleva;
                # acá no hay nadie mirando. Poner el rastro en el borrado genérico además
                # duplicaría filas de oferta con cada borrado deliberado.
                record_occupancy_snapshot(locked)
                _delete_class_refunding_consumption(locked)
            summary['pruned_count'] += 1
        except Exception as exc:  # noqa: BLE001
            logger.exception('rolling window: prune failed org=%s class=%s', org.id, class_id)
            summary['prune_errors'].append(_error_line('clase', class_id, exc))


def advance_windows_for_org(org, now=None):
    """Extiende la ventana, consolida estados y poda clases vacías pasadas de UNA org.
    Devuelve summary dict.

    ORDEN DE LAS FASES: extender → sync → podar. No es arbitrario.

    * **Extender va primero** porque es lo único que el alumno ve: si el proceso muere a mitad
      (deploy, OOM), lo que sobrevive es el calendario nuevo y no la limpieza, que puede
      esperar a mañana.
    * **El sync va entre las dos** porque la poda juzga por ESTADO + HISTORIA, y el sync es
      justo lo que consolida las dos cosas (flip a `completed`, asistencias, y el
      `TeacherPaymentRecord` del profe cuando hay regla activa). Podar antes de sincronizar
      hacía que el resultado del job dependiera de si alguien había abierto el dashboard: la
      clase vacía se borraba y la liquidación de ese dictado nunca nacía. Después de sincronizar
      la decisión es determinista.
    * **Que el sync vaya DESPUÉS de extender casi nunca le agrega trabajo, y cuando se lo agrega
      está bien.** Lo que la fase 1 crea cae casi siempre adelante de `now`
      (`materialization_window_cap` mira hacia adelante), así que el filtro
      `start_datetime__lte=now` del sync no lo alcanza. La excepción real es el MISMO DÍA: la
      generación arranca en `max(template.start_date, hoy)` y no descarta un horario de hoy que
      ya pasó, así que un cron tarde en el día puede crear la clase de hoy y cerrarla en la
      misma corrida (ver `_sync_statuses`). Es inofensivo —el request path producía ese mismo
      estado en el próximo page-load— y el cron off-peak lo evita. Ponerlo antes de extender no
      cambiaría nada de esto; queda después para que el orden se lea como el pipeline.
    """
    now = now or timezone.now()
    summary = {
        'org_id': org.id,
        'org_name': org.name,
        'templates_processed': 0,   # plantillas examinadas, incluidas las que fallaron
        'instances_created': 0,
        'extension_errors': [],
        'sync_errors': [],
        'pruned_count': 0,
        'prune_errors': [],
    }
    _extend_windows(org, summary)
    _sync_statuses(org, now, summary)
    _prune_past_empty_classes(org, now, summary)
    return summary


def run_advance_class_windows(org_id=None, include_inactive=False):
    """Recorre todas las orgs activas (o solo `org_id`) y agrega summaries. Devuelve dict global.

    SIN transacción global: cada organización queda commiteada aunque la siguiente falle.

    El guard de `is_active` es PAREJO ahora en las dos formas de invocación —barrido
    default y `org_id` puntual—: un gimnasio suspendido no genera (ni cobra) clases nuevas
    por su cuenta, y tampoco lo hace una corrida manual apuntada a su id, salvo que se pida
    explícitamente. El override es el flag `include_inactive`:

    * sin `org_id`: `include_inactive=False` (default) trae solo `is_active=True`, igual
      que siempre; `include_inactive=True` trae TODAS las orgs (`Organization.objects.all()`).
    * con `org_id`: siempre se resuelve con `.get(pk=org_id)` primero, así que un id
      inexistente sigue propagando `Organization.DoesNotExist` (el comando lo convierte en
      `CommandError`) ANTES de mirar `is_active`. Si la org existe pero está inactiva y NO
      se pidió `include_inactive`, no se procesa: se loguea, se registra en
      `skipped_inactive` y la función retorna limpia (exit 0, sin excepción). Con
      `include_inactive=True` la org puntual corre igual que si estuviera activa —es la
      corrida manual de un operador que necesita arreglar el calendario de una org
      suspendida a propósito, sabiendo que eso le descuenta saldo real a sus alumnos—.

    `skipped_inactive` es una lista de `{'org_id': ..., 'org_name': ...}`, una entrada por
    cada organización que se salteó por estar inactiva (vacía cuando no se salteó
    ninguna). Solo se llena por el camino de `org_id` puntual: el barrido default nunca la
    llena, porque ahí las orgs inactivas ni siquiera entran al queryset —no hay nada que
    "saltear", ya vinieron excluidas—.

    `errors` junta TODO lo que salió mal —fallas por plantilla, del sync de estados, por clase
    y por organización— ya formateado como strings con el id de la org adelante, para que el
    comando pueda decidir su código de salida mirando una sola lista.
    """
    result = {
        'orgs_processed': 0,   # orgs que completaron (las que reventaron entran en `errors`)
        'instances_created': 0,
        'pruned_count': 0,
        'errors': [],
        'org_summaries': [],
        'skipped_inactive': [],
    }

    if org_id is not None:
        org = Organization.objects.get(pk=org_id)
        if not org.is_active and not include_inactive:
            logger.warning(
                'rolling window: org %s (%s) inactiva, salteada (include_inactive=False)',
                org.id, org.name,
            )
            result['skipped_inactive'].append({'org_id': org.id, 'org_name': org.name})
            return result
        organizations = [org]
    elif include_inactive:
        organizations = Organization.objects.all().order_by('id')
    else:
        organizations = Organization.objects.filter(is_active=True).order_by('id')

    for org in organizations:
        try:
            org_summary = advance_windows_for_org(org)
        except Exception as exc:  # noqa: BLE001
            # Red de última instancia: las fallas por plantilla y por clase ya se
            # capturaron adentro, así que llegar acá es que reventó el propio recorrido
            # (la base, un queryset). Igual no puede arrastrar a las orgs siguientes.
            logger.exception('rolling window: org run failed org=%s', org.id)
            # 'org' y no 'organización': mismo prefijo que usan los errores de plantilla/
            # clase de abajo (`f'org {id}: ...'`), para que el comando no tenga dos formatos
            # de prefijo distintos según dónde reventó.
            result['errors'].append(_error_line('org', org.id, exc))
            continue

        result['org_summaries'].append(org_summary)
        result['orgs_processed'] += 1
        result['instances_created'] += org_summary['instances_created']
        result['pruned_count'] += org_summary['pruned_count']
        for line in org_summary['extension_errors'] + org_summary['sync_errors'] + org_summary['prune_errors']:
            result['errors'].append(f'org {org_summary["org_id"]}: {line}')

    return result
