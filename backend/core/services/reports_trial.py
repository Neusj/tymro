"""Reporte de CONVERSIÓN DE LA CLASE DE PRUEBA (P3.4 · parte 2, pieza 2).

De los que usaron la clase de prueba gratis en el período, cuántos terminaron comprando un
plan. Publica el conteo bruto de las dos puntas (probaron / compraron) y la tasa, más la serie
temporal para el gráfico.

⚠️ POR QUÉ NO SE USA `CustomUser.has_used_trial` COMO FUENTE
============================================================
`has_used_trial` es un **BooleanField SIN FECHA** (`accounts/models.py`). No se puede anclar
"usaron la prueba EN EL PERÍODO" en un flag que no dice cuándo, y forzarlo produciría el peor
reporte posible: uno que cuenta a todos los que alguna vez probaron dentro de cualquier período
que se le pida.

La fecha sale de la RESERVA: `Enrollment.is_trial` (models.py), que setea
`reserve_student_in_class(..., is_trial=True)` desde el ÚNICO camino que existe hoy,
`PublicTrialBookView` (views.py) — el mismo camino que, en la misma transacción, prende
`has_used_trial`. O sea: el flag y la reserva nacen juntos, y la reserva es la única de las dos
que tiene fecha, sede y clase.

TODAS LAS DEFINICIONES DE ESTE MÓDULO, EXPLÍCITAS
=================================================

**1. "USÓ LA PRUEBA" = TUVO UNA RESERVA DE PRUEBA VIVA EN UNA CLASE QUE SE DICTÓ Y YA EMPEZÓ.**
Tres condiciones, y cada una descarta un caso que haría mentir a la tasa:

* `Enrollment.is_trial=True` y `status='active'`. La reserva CANCELADA no se usó: el alumno
  agendó y no fue (y el derecho a la prueba no se le devuelve — lo verifica
  `test_public_registration`). Se cuentan aparte en `totals.cancelled_trials` para que la
  diferencia entre "agendaron" y "probaron" no sea un hueco mudo.
* La clase se DICTÓ: se reusa `reports_occupancy.DICTATED_Q`, la fuente única de ese predicado
  (`scheduled`/`in_progress` vivas + `completed`/`completed_early`; nunca `cancelled` ni
  `suspended`). Una prueba agendada en una clase que el gimnasio CANCELÓ no es una prueba
  desperdiciada por el prospecto: nunca existió. Contarla en el denominador castigaría al
  gimnasio por cancelar bien, exactamente el razonamiento de ese `Q`.
* La clase YA EMPEZÓ (`start_datetime <= ahora`). Una prueba agendada para el jueves que viene
  todavía no se usó; si el período incluye fechas futuras entraría al denominador sin ninguna
  posibilidad de haber convertido, hundiendo la tasa. Van aparte en `totals.pending_trials`.

**2. LA FECHA DEL TRIAL ES LA DE LA CLASE (`gym_class.start_datetime`), NO EL `created_at` DE
LA RESERVA.** El reporte dice "usaron la clase de prueba en el período", y la prueba ocurre
cuando ocurre la CLASE: agendar el 30 de enero para una clase del 2 de febrero es una prueba de
FEBRERO. Con `created_at` la prueba caería en un bucket en el que todavía no había pasado nada,
y un mes cerrado podría contener pruebas que se tomaron el mes siguiente. Es también el ancla
que ya usa el rail de seguimiento (`send_trial_followups` dispara por
`gym_class.end_datetime`). Se convierte con `timezone.localtime(...).date()`, la misma zona con
la que Postgres resuelve el filtro `start_datetime__date__gte/lte`, así que el filtro y el
bucket hablan del mismo día (mismo criterio que `reports_occupancy`).

**3. "PROBARON" SE CUENTA EN ALUMNOS ÚNICOS, NO EN RESERVAS.** El KPI es "cuántas personas
probaron". `has_used_trial` hace que en la práctica haya una sola reserva de prueba por alumno,
pero el reporte no lo asume: si aparecieran dos (fila legacy, alta directa por el admin de
Django, la e2e), el alumno cuenta UNA vez y su ancla temporal es la PRIMERA —la más generosa,
porque abre antes la ventana de conversión—.

**4. "ASISTIÓ" SE PUBLICA APARTE Y NO ES EL DENOMINADOR DE LA TASA PRINCIPAL.**
Se puede saber quién ASISTIÓ (`Attendance` con `present`/`late`, la misma definición que
`send_trial_followups.ATTENDED_STATUSES`, importada de ahí para no tener dos), pero NO puede
ser el universo de la tasa: `GymClass.consolidate_attendance` marca `absent` a todo el que no
tenga fila al cerrar la clase, así que en un gimnasio que no pasa lista por QR ni a mano
**todos quedan `absent`** y `attended` sería 0 — una tasa con denominador 0 en un gimnasio que
sí hizo pruebas. Por eso el denominador publicado es la RESERVA VIVA en una clase dictada (lo
que la base permite afirmar siempre: el gimnasio le guardó el lugar y el lugar no se liberó), y
la asistencia viaja como segundo par de números (`attended`, `converted_attended`,
`attended_conversion_rate`) para el gimnasio que sí la registra. La coincidencia se hace por el
par (clase, alumno) y no solo por alumno: haber asistido a OTRA clase del período no es haber
asistido a la propia prueba.

**5. "MEMBRESÍA DE PAGO" ES LA REGLA DE `plans._payment_status`, NO `final_price > 0`.**
Misma semántica, expresada como queryset por volumen (fila por fila serían dos consultas por
membresía). En orden:

* **FREE gana**: `final_price` con un 0 EXPLÍCITO no es una compra (beca, giftcard, cortesía) y
  queda fuera. Se escribe en POSITIVO —`final_price IS NULL OR final_price > 0`— y no como
  `exclude(final_price__lte=0)`: la columna es NULLABLE y `NOT (x <= 0)` en SQL descarta los
  NULL, que acá significan "no se registró el precio" y NO "se decidió no cobrar" (la
  distinción que `_payment_status` fija a propósito).
* **PAID** si hay una `PaymentTransaction` APROBADA de la MISMA organización colgada de la
  membresía **con `plan_amount > 0`**, o un `ManualPayment` de la MISMA organización sobre esa
  membresía. El `plan_amount > 0` NO es cosmético y es la ambigüedad que 8.2 resolvió a
  propósito: `apply_provider_payment` también cuelga la tx cuando el cobro pagó solo la
  MATRÍCULA (`plan_amount == 0`), y pagar la matrícula no compra el plan. Sin ese filtro, un
  prospecto con un plan asignado a mano —impago— que pagó su matrícula en línea aparecería
  como convertido.
* **UNPAID** el resto: no es conversión.

El filtro por `organization_id` en las DOS ramas no es redundante: esas FK son propias y nada
obliga a que la contraparte sea del tenant que vendió la membresía (el agujero multitenant
recurrente del proyecto).

**6. UNA COMPRA DEVUELTA NO CUENTA COMO CONVERSIÓN, PERO SE PUBLICA.**
Cuando el proveedor avisa un reembolso o un contracargo, `_stamp_refund` (services/payments.py)
pisa `status` a `refunded`, así que la membresía deja de cumplir la regla PAID y el alumno sale
del numerador — sin escribir una línea de lógica de devoluciones acá. Se elige eso y no lo
contrario porque la definición de "pagada" tiene que ser UNA sola en todo el backend: si este
reporte contara como convertida una membresía que `_payment_status` declara `unpaid`, habría dos
verdades sobre la misma fila.

La contrapartida es real y por eso se declara: **la tasa de un período CERRADO puede BAJAR más
adelante** si una compra de ese período se devuelve (lo contrario de lo que hace
`reports_revenue`, que congela el bruto en `collected_at` justamente para que no pase). La baja
nunca es muda: `totals.refunded_conversions` cuenta los prospectos que compraron y a los que se
les devolvió la plata, detectados por `collected_at IS NOT NULL AND refunded_at IS NOT NULL`
(`collected_at` se estampa una vez y NUNCA se limpia, tampoco al devolver).

**7. HAY VENTANA DE CONVERSIÓN (`CONVERSION_WINDOW_DAYS`).** La compra tiene que empezar dentro
de `fecha del trial + CONVERSION_WINDOW_DAYS`. Sin tope, un trial de enero que compra en
diciembre mejoraría el enero ya informado once meses después: el número de un período cerrado
no puede cambiar hacia atrás (mismo principio que `reports_revenue` con `collected_at`, y que
la gracia de `reports_retention`). Comprar ocho meses después es otra venta, no la conversión de
esa prueba. `totals.pending_window` cuenta los trials cuyo veredicto TODAVÍA puede cambiar
(ventana abierta hoy), así que un "no convirtió" recién nacido no se lee como definitivo.

**8. "POSTERIOR AL TRIAL" SE MIDE CON `StudentPlan.start_date`, NO CON `created_at`.**
`start_date >= fecha del trial`. Es la fecha de negocio que TODOS los escritores llenan con
sentido (`activate_student_plan` la pone en hoy para la compra en línea, el admin la elige al
asignar, el importador la trae del CSV), y hace entrar el caso clásico —probó y se inscribió el
mismo día en el mostrador—. `created_at` sería peor: para todo el histórico cargado por
importador vale el instante del import, así que declararía "conversión" una membresía anterior
al trial por años.

⚠️ EL CRUCE TRIAL → COMPRA ES DONDE ES FÁCIL CRUZAR ORGANIZACIONES
==================================================================
El alumno es la clave del join y el alumno es LO ÚNICO que no está anclado al tenant
(`Enrollment.student` y `StudentPlan.user` son CASCADE sobre el USUARIO, no sobre la
organización; un alumno movido de organización deja datos viejos alcanzables desde el tenant
nuevo). Por eso **ninguno de los dos lados se scopea por `student.organization_id`**, y cada uno
llega a `scope.organization_id` por su propio camino:

* la reserva de prueba, por `gym_class.organization_id` (la org de la CLASE);
* la membresía, por `StudentPlan.organization` (la org que VENDIÓ), jamás por `user.organization`;
* y los cobros que la declaran pagada, por su propio `organization_id`.

⚠️ FILTRO POR SUCURSAL: SOLO DEL LADO DEL TRIAL
==============================================
`GymClass.branch` es NOT NULL, así que del lado de la prueba la sede es un hecho duro y filtrar
por ella no pierde nada. Del lado de la COMPRA, `StudentPlan.branch` es NULLABLE y NULL
significa **"el plan es global"** (los dos escritores lo derivan de `plan.branch`; ver
`reports_retention` y el comentario del campo en `models.py`): si se exigiera que la compra
fuera de la misma sede, el prospecto que probó en Sede Centro y compró un plan GLOBAL contaría
como NO convertido, y la tasa por sede sería una mentira en el gimnasio que solo vende planes
globales.

Por eso el filtro de sede define el UNIVERSO (qué pruebas se miran) y la compra es solo un
PREDICADO sobre ese mismo conjunto de alumnos, scopeado por organización. Numerador y
denominador viven en el mismo universo por construcción: el numerador es un subconjunto del
conjunto que el filtro seleccionó, nunca una segunda consulta que pueda recortarlo.

LÍMITES CONOCIDOS
=================
* **Quien tenga `has_used_trial=True` sin reserva de prueba es INVISIBLE para la tasa.** Hoy no
  hay camino de API que produzca esa combinación (el flag y la reserva se escriben en la misma
  transacción de `PublicTrialBookView`), pero sí la producen el admin de Django y —sobre todo—
  el **borrado de una clase**: `Enrollment.gym_class` es CASCADE, así que borrar la `GymClass`
  se lleva la reserva de prueba y deja el flag prendido. Esas personas NO entran en la tasa (no
  hay fecha para ubicarlas en un período) y se publican en el bloque aparte
  `unbacked_trial_flags`, que es un diagnóstico de datos y NO un número de negocio.
  Ese conteo es lo único de este módulo anclado en `user.organization_id` —el flag vive en el
  usuario y no tiene otra ancla—, así que **sobrecuenta** a los alumnos que usaron su prueba en
  OTRA organización antes de mudarse a esta. Va declarado en el payload.
* **La poda de la ventana rodante NO borra clases con inscripciones**
  (`rolling_window._prune_past_empty_classes` exige `enrollments__isnull=True`), así que una
  clase con una prueba adentro sobrevive y este reporte no necesita el rastro de
  `ClassOccupancySnapshot`. Si esa condición de la poda cambiara, las pruebas históricas
  empezarían a desaparecer en silencio.
* **Una compra con `start_date` retroactivo (el admin la fecha antes del trial) no cuenta como
  conversión.** Es la consecuencia de la decisión 8 y no hay columna que permita distinguir
  "venta vieja" de "venta nueva mal fechada".
* **Un prospecto que ya era alumno pagador antes de probar** no infla la tasa por sus
  membresías viejas (se exige `start_date >= fecha del trial`), pero sí cuenta como convertido
  si renovó después del trial dentro de la ventana. La base no permite distinguir una renovación
  de una primera compra sin volver a preguntar por el linaje, que es otro reporte
  (`reports_retention`).
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

# FUENTE ÚNICA de "asistió = estuvo físicamente en la clase". Se importa del comando de
# seguimiento de trials en vez de copiarse: es la MISMA pregunta que decide a quién se le manda
# el correo post-prueba, y dos listas separadas podrían divergir (el reporte diría que asistió
# gente que nunca recibió el correo, o al revés). Importar un módulo de `management/commands`
# desde un servicio es inusual y deliberado: ahí vive el set desde Feature 2 y moverlo obligaría
# a tocar un rail que ya corre en producción sin ninguna necesidad funcional.
from ..management.commands.send_trial_followups import ATTENDED_STATUSES
from ..models import (Attendance, Enrollment, GymClass, ManualPayment, PaymentTransaction,
                      StudentPlan)
# `rate_pct` y `points_delta` viven en `reports_base` y NO acá: el reporte de retención
# (`reports_retention`) usa exactamente las mismas dos funciones, y una copia por módulo es la
# forma en que dos mitades de la misma feature divergen sin que nada lo detecte.
from .reports_base import bucket_key, bucket_keys, pct_delta, points_delta, rate_pct
from .reports_occupancy import DICTATED_Q

# Días después de la prueba en que una compra todavía se atribuye a esa prueba. Ver la decisión
# 7 del docstring. Global de módulo (no default de parámetro) para que un test lo pueda mover
# con monkeypatch sin fabricar meses de historia, igual que `reports_revenue_detail.MAX_ROWS`.
CONVERSION_WINDOW_DAYS = 60


# --------------------------------------------------------------------------------------
# Lado TRIAL. Todo cuelga de la clase, que es lo único anclado al tenant y a la sede.
# --------------------------------------------------------------------------------------

def _trial_classes(*, organization_id, branch, date_from, date_to):
    """Clases DICTADAS del rango que podrían tener una prueba adentro.

    Se usa como SUBCONSULTA (`gym_class__in=...`) y no como lista de ids: el rango puede ser de
    731 días (`MAX_PERIOD_DAYS`) y un `IN` con miles de enteros viaja peor que un subselect que
    Postgres resuelve con el mismo índice.

    `DICTATED_Q` viene de `reports_occupancy`, la fuente única del predicado "esta clase se
    dictó" (ver el docstring de ese módulo: `is_active` NO se puede exigir parejo porque todo
    cierre terminal lo apaga, así que un filtro ingenuo vaciaría cualquier período pasado).
    NO se filtra por `is_trial_eligible`: la elegibilidad de HOY puede haber cambiado después
    de la prueba, y lo que importa es que la reserva quedó marcada `is_trial`.
    """
    queryset = GymClass.objects.filter(
        DICTATED_Q,
        organization_id=organization_id,
        # Fecha LOCAL sobre un `DateTimeField`: Postgres convierte a `America/Santiago`
        # (`USE_TZ=True`), la misma zona con la que después se calcula el bucket.
        start_datetime__date__gte=date_from,
        start_datetime__date__lte=date_to,
    )
    if branch is not None:
        # `GymClass.branch` es NOT NULL: acá el filtro por sede no deja nada afuera y no tiene
        # la ambigüedad de `StudentPlan.branch` (ver el encabezado del módulo). `branch` ya
        # vino verificada como de esta organización (`views_reports._scoped_id`).
        queryset = queryset.filter(branch=branch)
    return queryset


def _trial_students(classes, *, now):
    """`({student_id: (fecha local de su PRIMERA prueba, {ids de clase})}, canceladas, pendientes)`.

    Tres lecturas del mismo universo de clases, cada una con su propio recorte:

    * las reservas VIVAS en clases que ya empezaron → el universo del reporte;
    * las CANCELADAS → informativas (agendaron y no probaron);
    * las vivas en clases que todavía NO empezaron → informativas (probarán).

    Las tres cuentan ALUMNOS ÚNICOS (decisión 3). El ancla de cada alumno es su prueba más
    temprana en el período.
    """
    held = classes.filter(start_datetime__lte=now)
    rows = (
        Enrollment.objects
        .filter(is_trial=True, status='active', gym_class__in=held)
        # `.order_by()` descarta el `Meta.ordering = ['created_at']` de Enrollment: el mínimo
        # por alumno se resuelve abajo y el ORDER BY solo costaría un sort.
        .values('student_id', 'gym_class_id', 'gym_class__start_datetime')
        .order_by()
    )

    students = {}
    for row in rows:
        # Misma conversión de zona que `reports_occupancy._live_rows`: el bucket sale del día
        # LOCAL de la clase, no del día UTC.
        trial_date = timezone.localtime(row['gym_class__start_datetime']).date()
        current = students.get(row['student_id'])
        if current is None:
            students[row['student_id']] = (trial_date, {row['gym_class_id']})
        else:
            # `min`: la prueba más temprana manda (decisión 3). El set de clases guarda TODAS
            # las del alumno para que la coincidencia de asistencia sea por par (clase, alumno).
            current[1].add(row['gym_class_id'])
            students[row['student_id']] = (min(current[0], trial_date), current[1])

    cancelled = (
        Enrollment.objects
        .filter(is_trial=True, status='cancelled', gym_class__in=held)
        .values('student_id').distinct().count()
    )
    pending = (
        Enrollment.objects
        .filter(is_trial=True, status='active',
                gym_class__in=classes.filter(start_datetime__gt=now))
        .values('student_id').distinct().count()
    )
    return students, cancelled, pending


def _attended_pairs(students):
    """`{(gym_class_id, student_id)}` de las pruebas con asistencia PRESENTE/TARDE.

    La coincidencia es por PAR y no por alumno: haber asistido a otra clase del período no es
    haber asistido a la propia prueba (decisión 4). La consulta acota por los dos lados —los
    alumnos con prueba y sus clases de prueba— así que devuelve un superconjunto pequeño del
    que se filtran los pares exactos en memoria; el volumen es de una prueba por alumno, no de
    todas las asistencias del período (que en dos años son decenas de miles).
    """
    if not students:
        return set()
    class_ids = set()
    for _trial_date, ids in students.values():
        class_ids |= ids
    rows = Attendance.objects.filter(
        gym_class_id__in=class_ids,
        student_id__in=students.keys(),
        status__in=ATTENDED_STATUSES,
    ).values_list('gym_class_id', 'student_id')
    return set(rows)


# --------------------------------------------------------------------------------------
# Lado COMPRA. La regla de "pagada" es la de `plans._payment_status`, expresada como
# subconsultas `Exists` para que no haya una consulta por membresía.
# --------------------------------------------------------------------------------------

def _paid_membership_rows(*, organization_id, student_ids, earliest_trial, latest_deadline):
    """Membresías candidatas a ser la conversión, ya etiquetadas como pagada / devuelta.

    ⚠️ Se usan `Exists` y NO un `filter(Q(origin_transactions__...) | Q(manual_payments__...))`.
    Un OR entre dos relaciones inversas produce un producto cartesiano de JOINs: la misma
    membresía volvería repetida una vez por cobro y cualquier conteo quedaría inflado (el
    `.distinct()` que lo tapa es justo el parche que esconde el problema). Con `Exists` la fila
    aparece una sola vez y cada subconsulta se evalúa por su cuenta.

    Las tres subconsultas intersectan `organization_id` con la organización del scope: esas FK
    son propias y nada obliga a que el cobro sea del tenant que vendió la membresía (decisión
    5).
    """
    approved_transaction = PaymentTransaction.objects.filter(
        student_plan_id=OuterRef('pk'),
        organization_id=organization_id,
        status=PaymentTransaction.STATUS_APPROVED,
        # Pagar solo la MATRÍCULA no compra el plan: la ambigüedad que 8.2 cerró.
        plan_amount__gt=0,
    )
    manual_payment = ManualPayment.objects.filter(
        student_plan_id=OuterRef('pk'),
        organization_id=organization_id,
    )
    # Cobro que ENTRÓ y volvió. `status` ya fue pisado a `refunded` (por eso no cumple la regla
    # PAID), pero `collected_at` no se limpia nunca: es la única forma de saber que esa venta
    # existió. Ver la decisión 6.
    refunded_transaction = PaymentTransaction.objects.filter(
        student_plan_id=OuterRef('pk'),
        organization_id=organization_id,
        collected_at__isnull=False,
        refunded_at__isnull=False,
        plan_amount__gt=0,
    )

    queryset = (
        StudentPlan.objects
        .filter(
            # La org que VENDIÓ, jamás `user.organization`.
            organization_id=organization_id,
            user_id__in=student_ids,
            # Ventana de conversión, acotada al lote completo; el par exacto (trial, compra) lo
            # resuelve `_conversion_kind`.
            start_date__gte=earliest_trial,
            start_date__lte=latest_deadline,
        )
        # FREE gana sobre todo, escrito en POSITIVO para no perder los NULL (decisión 5).
        .filter(Q(final_price__isnull=True) | Q(final_price__gt=0))
        .annotate(
            has_approved_transaction=Exists(approved_transaction),
            has_manual_payment=Exists(manual_payment),
            has_refunded_transaction=Exists(refunded_transaction),
        )
        .values('user_id', 'start_date', 'has_approved_transaction', 'has_manual_payment',
                'has_refunded_transaction')
        # Descarta el `Meta.ordering = ['-start_date']`: se indexa por alumno en memoria.
        .order_by()
    )
    index = {}
    for row in queryset:
        index.setdefault(row['user_id'], []).append(row)
    return index


#: Resultado del predicado de conversión. Internos: al cable van los contadores.
_CONVERTED = 'converted'
_REFUNDED = 'refunded'


def _conversion_kind(trial_date, memberships, window_days):
    """`_CONVERTED`, `_REFUNDED` o ``None`` para UN alumno.

    `_CONVERTED` gana: si compró dos veces y una se devolvió, el alumno convirtió. Un solo
    lugar donde vive el predicado, y lo usan el período actual y el de comparación —si cada uno
    lo escribiera aparte, el delta compararía dos definiciones de conversión en vez de dos
    períodos (la lección de `reports_revenue._method_data`)—.
    """
    deadline = trial_date + timedelta(days=window_days)
    refunded = False
    for row in memberships:
        # `start_date >= fecha del trial` (decisión 8) y dentro de la ventana (decisión 7).
        if row['start_date'] < trial_date or row['start_date'] > deadline:
            continue
        if row['has_approved_transaction'] or row['has_manual_payment']:
            return _CONVERTED
        if row['has_refunded_transaction']:
            refunded = True
    return _REFUNDED if refunded else None


# --------------------------------------------------------------------------------------
# Agregación. Un solo recorrido por alumno alimenta los totales y la serie.
# --------------------------------------------------------------------------------------

def _empty_group():
    return {
        'trials': 0,
        'attended': 0,
        'converted': 0,
        'converted_attended': 0,
        'refunded_conversions': 0,
        'pending_window': 0,
    }


def _accumulate(group, *, attended, kind, pending):
    group['trials'] += 1
    if attended:
        group['attended'] += 1
    if kind == _CONVERTED:
        group['converted'] += 1
        if attended:
            group['converted_attended'] += 1
    elif kind == _REFUNDED:
        group['refunded_conversions'] += 1
    if pending:
        group['pending_window'] += 1


def _group_payload(group):
    """Números publicados de un grupo (total o bucket), con sus dos tasas.

    Las tasas se derivan de los enteros ya contados y publicados, así que la división que el
    front muestra cuadra exactamente con los dos números de al lado (mismo criterio que
    `reports_revenue._totals`).
    """
    trials = group['trials']
    attended = group['attended']
    return {
        'trials': trials,
        'converted': group['converted'],
        # La tasa PRINCIPAL: sobre las pruebas TOMADAS, no sobre las asistidas (decisión 4).
        'conversion_rate': rate_pct(group['converted'], trials),
        # ⊆ trials: con asistencia registrada. En un gimnasio que no pasa lista esto es 0 y la
        # tasa de arriba sigue siendo válida.
        'attended': attended,
        'converted_attended': group['converted_attended'],
        'attended_conversion_rate': rate_pct(group['converted_attended'], attended),
        # Compraron y se les devolvió la plata: NO están en `converted` (decisión 6). Se
        # publica para que una baja retroactiva de la tasa tenga una explicación a la vista.
        'refunded_conversions': group['refunded_conversions'],
        # ⊆ (trials - converted): la ventana de conversión sigue abierta hoy, así que su
        # veredicto todavía puede cambiar (decisión 7).
        'pending_window': group['pending_window'],
    }


def _tally(*, organization_id, branch, date_from, date_to, window_days, now, today):
    """`(payload de totales, filas por alumno)` de un rango cualquiera.

    Lo llaman el período del reporte y el de comparación: las dos lecturas usan el MISMO
    universo y el MISMO predicado de conversión.
    """
    classes = _trial_classes(organization_id=organization_id, branch=branch,
                             date_from=date_from, date_to=date_to)
    students, cancelled, pending_trials = _trial_students(classes, now=now)

    totals = _empty_group()
    rows = []
    if students:
        attended_pairs = _attended_pairs(students)
        trial_dates = [trial_date for trial_date, _ids in students.values()]
        memberships = _paid_membership_rows(
            organization_id=organization_id,
            student_ids=list(students.keys()),
            earliest_trial=min(trial_dates),
            latest_deadline=max(trial_dates) + timedelta(days=window_days),
        )
        for student_id, (trial_date, class_ids) in students.items():
            attended = any((class_id, student_id) in attended_pairs for class_id in class_ids)
            kind = _conversion_kind(trial_date, memberships.get(student_id, ()), window_days)
            # Solo tiene sentido marcar "pendiente" a quien NO convirtió: una conversión ya es
            # un hecho cerrado.
            pending = kind != _CONVERTED and (trial_date + timedelta(days=window_days)) >= today
            _accumulate(totals, attended=attended, kind=kind, pending=pending)
            rows.append((trial_date, attended, kind, pending))

    payload = _group_payload(totals)
    # Los dos informativos van SOLO en los totales (no en la serie): explican la diferencia
    # entre "agendaron" y "probaron", y una serie con seis líneas no se lee.
    payload['cancelled_trials'] = cancelled
    payload['pending_trials'] = pending_trials
    return payload, rows


def _unbacked_trial_flags(organization_id):
    """Alumnos con `has_used_trial=True` y SIN ninguna reserva de prueba en esta organización.

    Es un DIAGNÓSTICO DE DATOS, no un número de negocio: esta gente no puede entrar en la tasa
    porque el flag no tiene fecha con la que ubicarla en un período (ver el encabezado del
    módulo). Se publica para que "faltan alumnos" sea un número visible en vez de una sospecha.

    ⚠️ Es lo ÚNICO de este módulo anclado en `user.organization_id`, y no hay alternativa: el
    flag vive en el usuario y no tiene otra ancla. La consecuencia es que SOBRECUENTA a quien
    usó su prueba en otra organización antes de mudarse a esta (el flag viaja con la persona).
    Va declarado en el payload; jamás en la tasa.

    `~Exists(...)` y no `exclude(...)`: la subconsulta se scopea por `gym_class__organization_id`
    (la org de la CLASE, nunca la del alumno) y con `exclude` sobre una relación inversa Django
    arma un `NOT IN` sobre un subselect cuyo NULL es traicionero.
    """
    User = get_user_model()
    has_trial_reservation = Enrollment.objects.filter(
        student_id=OuterRef('pk'),
        is_trial=True,
        gym_class__organization_id=organization_id,
    )
    students = User.objects.filter(
        organization_id=organization_id,
        has_used_trial=True,
        role=User.Role.STUDENT,
    ).filter(~Exists(has_trial_reservation))
    return students.count()


def build_trial_conversion_report(scope):
    """Conversión de la clase de prueba en el período de `scope`.

    Sin filtros propios más allá del `scope` (período + sucursal): las dos lecturas posibles
    del universo —reserva viva en clase dictada, y asistencia confirmada— se publican LAS DOS
    en `totals`, así que no hace falta un parámetro que cambie el significado de la tasa
    principal según cómo venga el request (ver la decisión 4).

    Todo sale filtrado por `scope.organization_id`, que es la organización DEL ACTOR, y cada
    lado del cruce trial → compra llega ahí por su propio camino (ver el encabezado del
    módulo). La organización no es un parámetro de este reporte.
    """
    window_days = CONVERSION_WINDOW_DAYS
    now = timezone.now()
    # "Hoy" es el día del gimnasio (`America/Santiago`) y no el día UTC del servidor: con
    # `date.today()` la ventana de conversión se correría un día durante las últimas horas de
    # cada jornada. Mismo criterio que `views_reports._report_scope`.
    today = timezone.localdate()

    totals, rows = _tally(
        organization_id=scope.organization_id, branch=scope.branch,
        date_from=scope.date_from, date_to=scope.date_to,
        window_days=window_days, now=now, today=today,
    )

    # El período anterior se calcula con LA MISMA función y el MISMO predicado: comparar contra
    # otra definición mediría la diferencia entre las dos consultas y no el movimiento del
    # negocio.
    previous_scope = scope.previous()
    previous_totals, _previous_rows = _tally(
        organization_id=previous_scope.organization_id, branch=previous_scope.branch,
        date_from=previous_scope.date_from, date_to=previous_scope.date_to,
        window_days=window_days, now=now, today=today,
    )

    # La serie nace COMPLETA y en cero: un bucket sin pruebas es un dato (nadie probó), no una
    # ausencia de dato. Ver `reports_base.bucket_keys`.
    series = {key: _empty_group() for key in bucket_keys(scope)}
    for trial_date, attended, kind, pending in rows:
        # Indexado directo y no `setdefault`: la clave SIEMPRE está porque el filtro de la
        # consulta (`start_datetime__date` entre las dos fechas del scope, resuelto por
        # Postgres en la zona del proyecto) y esta conversión (`timezone.localtime`, misma
        # zona) hablan del mismo día. Un KeyError acá sería un desalineamiento real de huso y
        # tiene que verse, no rellenarse con un bucket fuera de rango.
        _accumulate(series[bucket_key(trial_date, scope.granularity)],
                    attended=attended, kind=kind, pending=pending)

    return {
        'period': scope.period_payload(),
        'filters': scope.filters_payload(
            # El parámetro de negocio del cálculo viaja en la respuesta: el mismo payload
            # leído dentro de seis meses tiene que poder explicar sus propios números.
            conversion_window_days=window_days,
        ),
        'totals': totals,
        'previous': {
            'period': previous_scope.period_payload(),
            'totals': previous_totals,
        },
        'comparison': {
            # PUNTOS PORCENTUALES, no variación porcentual de un porcentaje (ver
            # `reports_base.points_delta`).
            'conversion_rate_delta_pp': points_delta(
                totals['conversion_rate'], previous_totals['conversion_rate']),
            'trials_delta': totals['trials'] - previous_totals['trials'],
            # Acá el % sí significa lo que parece (conteos, no tasas): se reusa el helper de
            # `reports_base`, que devuelve `None` si el período anterior fue 0.
            'trials_delta_pct': pct_delta(totals['trials'], previous_totals['trials']),
            'converted_delta': totals['converted'] - previous_totals['converted'],
            'converted_delta_pct': pct_delta(totals['converted'],
                                             previous_totals['converted']),
        },
        # Diagnóstico de datos, FUERA de la tasa y fuera del período. Ver
        # `_unbacked_trial_flags`.
        'unbacked_trial_flags': {
            'students': _unbacked_trial_flags(scope.organization_id),
            # Declarado explícitamente para que nadie lo lea como un número del período o de
            # la sede: no depende de ninguno de los dos.
            'scope': 'organization',
            'excluded_from_rate': True,
        },
        'series': [
            dict(_group_payload(series[key]), bucket=key)
            # Se recorre `bucket_keys` y no el dict: el orden del payload es el del período, no
            # el de inserción de las filas que llegaron.
            for key in bucket_keys(scope)
        ],
    }


def trial_conversion_export_spec(data):
    """`{'header', 'rows', 'total_row'}` para `reports_base.export_response`.

    Se exporta la SERIE, que en este reporte es el único corte tabular que existe (no hay una
    dimensión tipo "por plan" o "por disciplina": el hecho es una persona y una fecha). El
    export sale de `data`, o sea del MISMO payload que devolvió el JSON, así que la planilla no
    puede divergir de lo que el administrador está mirando.

    Las tasas no calculables (bucket sin pruebas, o sin asistencia registrada) salen como celda
    VACÍA y no como 0: un 0 % de conversión en un día sin pruebas es una afirmación falsa
    escrita en un archivo que después alguien promedia. La fila TOTAL trae además las dos
    columnas informativas que la serie no publica —canceladas y pendientes de tomar—, porque en
    el archivo son la única forma de explicar por qué "probaron" es menor que "agendaron".
    """
    header = ['Período', 'Probaron', 'Convirtieron', 'Tasa conversión %', 'Asistieron',
              'Convirtieron (asistieron)', 'Tasa conversión asistentes %',
              'Compras devueltas', 'Veredicto pendiente']

    def _cells(item):
        return [
            item['trials'], item['converted'],
            '' if item['conversion_rate'] is None else item['conversion_rate'],
            item['attended'], item['converted_attended'],
            ('' if item['attended_conversion_rate'] is None
             else item['attended_conversion_rate']),
            item['refunded_conversions'], item['pending_window'],
        ]

    rows = [[point['bucket']] + _cells(point) for point in data['series']]
    totals = data['totals']
    rows.append([
        f'— Reservas de prueba canceladas: {totals["cancelled_trials"]} · '
        f'pruebas agendadas aún no tomadas: {totals["pending_trials"]}. '
        f'Ninguna de las dos entra en "Probaron". —',
        '', '', '', '', '', '', '', '',
    ])
    total_row = ['TOTAL'] + _cells(totals)
    return {'header': header, 'rows': rows, 'total_row': total_row}
