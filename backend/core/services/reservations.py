from collections import defaultdict

from django.db import transaction
from django.db.models import F, Value
from django.db.models.functions import Greatest
from django.utils import timezone

from ..models import ConsumptionLog, Enrollment, GymClass, StudentPlan
from .plans import REASON_PLAN_UNAVAILABLE, describe_student_plan


TERMINAL_CLASS_STATUSES = {
    GymClass.Status.COMPLETED,
    GymClass.Status.CANCELLED,
    GymClass.Status.COMPLETED_EARLY,
}


class ReservationRuleError(Exception):
    def __init__(self, message, code='reservation_invalid'):
        super().__init__(message)
        self.message = message
        self.code = code


def get_active_student_plan(student, on_date=None):
    """Membresía vigente del alumno EN SU ORGANIZACIÓN.

    Filtrar solo por `user` no alcanza: `StudentPlan.user` es CASCADE sobre el usuario, no
    sobre la organización, así que mover a un alumno de la org A a la org B le deja las
    membresías de A vivas y apuntando al plan de A. Sin el filtro, ese alumno reservaba
    clases de la org B consumiendo —y descontando— un plan que la org A le vendió.

    La organización la manda la COLUMNA `StudentPlan.organization` —copia de
    `plan.organization` hecha al vender—, no el join `plan__organization`. No es lo mismo:
    `Plan` no tiene `clean()` y nada revalida las membresías que cuelgan de él, así que
    mover un plan de organización se llevaba con él las ventas históricas y el alumno se
    quedaba sin plan vigente. La columna se queda con el vendedor, que es la semántica
    declarada. De paso saca el join del camino caliente de la reserva.
    """
    # TODO #9: múltiples activas, definir imputación de consumo. Un alumno puede tener
    # varias membresías vigentes a la vez en la misma organización (p. ej. 4 BJJ + 8
    # kickboxing), y este `.first()` devuelve una ARBITRARIA —la de `start_date` más
    # reciente—, así que la reserva puede descontarle la clase al plan equivocado. Definir
    # la regla de imputación (por disciplina del plan, elección del alumno, o la que vence
    # antes) es parte de #9 (reservas); no se resuelve acá.
    target_date = on_date or timezone.localdate()
    return (
        StudentPlan.objects.filter(
            user=student,
            organization_id=student.organization_id,
        )
        .valid_on(target_date)
        .order_by('-start_date', '-id')
        .first()
    )


def resolve_student_plan_for_reservation(student, *, student_plan_id=None, on_date=None):
    """Con QUÉ membresía se descuenta esta reserva (9.1) — cierra el `TODO #9` que dejaba
    `get_active_student_plan` (ver su docstring, líneas 26-46): ese `.first()` sigue siendo
    arbitrario cuando el alumno tiene 2+ membresías vigentes en la misma organización (dos
    disciplinas, p. ej. 4 BJJ + 8 kickboxing). Reemplaza, como paso de resolución DENTRO de
    `_validate_reservation_rules`, al validador anterior (que solo confirmaba una única
    membresía usable sin elegir entre candidatos) — es el único llamador de esta función
    nueva. `get_active_student_plan`,
    `_get_active_student_plan_map`, `my-plan` y el roster son DISPLAY, no CONSUMO: no se tocan y
    siguen con su desempate arbitrario tal cual.

    Hereda el mismo razonamiento multitenant de `get_active_student_plan`: la organización
    del candidato la manda la COLUMNA `StudentPlan.organization` —copia de
    `plan.organization` hecha al vender—, nunca el join `plan__organization` ni
    `user.organization`. Filtrar solo por `user` no alcanza: `StudentPlan.user` es CASCADE
    sobre el usuario, no sobre la organización, así que un alumno movido de tenant
    conservaría vivas las membresías de la organización anterior.

    El queryset de candidatos (`valid_on` + `describe_student_plan(...).is_usable`) es LA
    ÚNICA FUENTE: ni el id elegido ni el conteo consultan ningún `StudentPlan` fuera de él.
    `describe_student_plan` es la fuente única de saldo/ilimitado —la misma que usan el
    roster y el serializer—, así que no se reimplementa el predicado acá.

    `student_plan_id`, si vino, se busca DENTRO de `candidates` y no con un `.get()`
    aparte: un id que exista pero sea de otra organización, esté sin saldo, vencido, o
    directamente no exista son la MISMA `ReservationRuleError`
    (`chosen_plan_unavailable`). Es el mismo anti-oráculo del resto del proyecto —
    distinguir esos casos le regalaría al alumno información sobre membresías que no son
    suyas—, así que las cuatro causas comparten mensaje y code.

    Sin `student_plan_id`, la ambigüedad que `get_active_student_plan` resolvía en
    silencio pasa a ser explícita: 0 candidatos es el error histórico
    (`plan_unavailable`, mismo string y code que ya manejaba el frontend); exactamente 1
    se usa sin preguntar; 2+ exige que el alumno elija (`plan_choice_required`) en vez de
    descontarle a uno arbitrario —"no adivinar" es la decisión de producto de #9—.
    """
    target_date = on_date or timezone.localdate()
    candidates_qs = (
        StudentPlan.objects
        .filter(user=student, organization_id=student.organization_id)
        .valid_on(target_date)
        .order_by('-start_date', '-id')
    )
    candidates = [sp for sp in candidates_qs if describe_student_plan(sp, target_date).is_usable]

    if student_plan_id is not None:
        for candidate in candidates:
            if candidate.id == student_plan_id:
                return candidate
        raise ReservationRuleError(
            'El plan elegido no está disponible.', code='chosen_plan_unavailable'
        )

    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise ReservationRuleError(
            'No tienes clases disponibles o plan activo', code=REASON_PLAN_UNAVAILABLE
        )
    raise ReservationRuleError(
        'Tienes más de un plan vigente. Elige con cuál reservar.', code='plan_choice_required'
    )


def validate_plan_branch_for_class(student_plan, gym_class):
    """Un plan EXCLUSIVO de una sucursal solo cubre las clases de esa sede.

    El alcance lo manda `plan.branch` (NULL = plan global, vale en toda la organización),
    no `student_plan.branch`, que es solo el registro histórico de dónde se activó la
    membresía. Así, cambiar el alcance del plan del catálogo se refleja en las membresías
    vigentes sin tener que migrarlas.

    EXCEPCIÓN CONOCIDA: la clase de prueba reserva con `require_plan=False`, así que no
    pasa por acá y un alumno con plan exclusivo puede agendar su prueba en otra sede. Es
    deliberado —la prueba es gratis, no consume plan y está limitada a una por usuario
    (`has_used_trial`)—, no un hueco de la regla.
    """
    plan = getattr(student_plan, 'plan', None)
    plan_branch_id = getattr(plan, 'branch_id', None)
    if not plan_branch_id:
        return
    if plan_branch_id != gym_class.branch_id:
        raise ReservationRuleError(
            f'Tu plan es exclusivo de {plan.branch.name} y no cubre las clases de esta sucursal.',
            code='plan_branch_mismatch',
        )


def get_enrollment_student_plan(enrollment):
    """De qué `StudentPlan` se descontó esta inscripción, según el `ConsumptionLog` que la
    respalda — usado por el reverso (`rollback_consumption_for_enrollment`) como fallback
    cuando no le pasan el plan explícito.

    Espeja el filtro del backfill de `Enrollment.student_plan`
    (`migrations/0033_enrollment_student_plan.py`): el log tiene que ser de la MISMA
    organización que la clase (`student_plan__organization_id=F('class_instance__organization_id')`),
    no solo matchear `user`/`class_instance`. Logs de antes del fix de scoping multitenant
    pueden apuntar a un `student_plan` de OTRA organización (mismo alumno/clase por
    coincidencia, plan ajeno); sin este filtro este helper le devolvía —y el reverso le
    reembolsaba saldo— a un plan que no es de esta organización. `None` es el mismo
    veredicto que 0033: no hay de dónde imputar de forma defendible, así que no se inventa
    un plan ni se toca uno ajeno.
    """
    consumption_log = (
        ConsumptionLog.objects.select_related('student_plan')
        .filter(
            user=enrollment.student,
            class_instance=enrollment.gym_class,
            student_plan__organization_id=F('class_instance__organization_id'),
        )
        .order_by('-consumed_at', '-id')
        .first()
    )
    return consumption_log.student_plan if consumption_log else None


def should_refund_consumption(enrollment, now=None):
    gym_class = enrollment.gym_class
    if getattr(gym_class, 'status', None) == GymClass.Status.CANCELLED or bool(getattr(gym_class, 'is_cancelled', False)):
        return True

    reference_now = now or timezone.now()
    start_datetime = getattr(gym_class, 'start_datetime', None)
    if not start_datetime:
        return False

    return reference_now < start_datetime


def consume_student_plan_for_enrollment(enrollment, student_plan):
    if enrollment.status != 'active':
        return False

    # `branch` va en defaults y NO en la clave de búsqueda: es un dato derivado de la
    # clase, no parte de la identidad del consumo.
    _, created = ConsumptionLog.objects.get_or_create(
        user=enrollment.student,
        class_instance=enrollment.gym_class,
        student_plan=student_plan,
        defaults={'branch_id': enrollment.gym_class.branch_id},
    )
    if not created:
        return False

    # Simétrico al reverso (`_revert_consumption_logs`): read-modify-write en memoria
    # pierde un +1 si dos reservas concurrentes consumen el MISMO plan (dos alumnos, o el
    # mismo alumno con doble click, contra el plan que `resolve_student_plan_for_reservation`
    # eligió). Se materializa el SELECT del lock (una queryset sin evaluar no dispara nada)
    # y sirve para serializar a los competidores: no-op en SQLite, que igual serializa las
    # escrituras; la garantía real es en Postgres (prod) y la red de fondo es el UPDATE con
    # `F()` de abajo. Requiere estar dentro de una transacción atómica: la aporta el
    # `@transaction.atomic` de `reserve_student_in_class`, único llamador real de esta función.
    list(StudentPlan.objects.filter(pk=student_plan.pk).select_for_update().values_list('pk', flat=True))

    # Incremento en la base y no read-modify-write: si otra reserva concurrente ya sumó
    # su +1 sobre este plan, `F('classes_used')` lo ve y no lo pisa con un snapshot viejo.
    StudentPlan.objects.filter(pk=student_plan.pk).update(
        classes_used=F('classes_used') + 1,
        updated_at=timezone.now(),
    )
    # La instancia en memoria no se actualiza sola con `.update()`: sin este refresh el
    # resto del request (p. ej. el serializer de la respuesta) seguiría viendo el
    # `classes_used` viejo.
    student_plan.refresh_from_db(fields=['classes_used', 'updated_at'])
    return True


def rollback_consumption_for_enrollment(enrollment, student_plan=None):
    """Camino de CANCELAR: exige `status=='active'` y respeta la ventana de reembolso
    (`should_refund_consumption`) — a diferencia de `revert_consumption_for_enrollment`
    (el camino de DELETE), que es incondicional.

    La MECÁNICA del reverso (a qué plan se le devuelve y cómo) ya no vive acá: se
    delega a `revert_consumption` (10.1), el núcleo único. Antes este reverso hacía
    read-modify-write en Python sin lock (`consumption_log.delete();
    resolved_plan.classes_used -= 1; save()`) y, para colmo, nunca leía el FK
    `enrollment.student_plan` — resolvía siempre por `get_enrollment_student_plan`
    (inferencia vía `ConsumptionLog`), aunque el FK ya fuera la fuente canónica desde
    #9. `revert_consumption` reordena esa prioridad (FK primero, helper solo si es
    NULL) y reemplaza el read-modify-write por el mismo lock + idempotencia que ya
    usa `_revert_consumption_logs`.
    """
    if enrollment.status != 'active':
        return False
    if not should_refund_consumption(enrollment):
        return False
    return bool(revert_consumption(enrollment, student_plan=student_plan))


def _revert_consumption_logs(log_queryset):
    """Borra los logs del queryset y devuelve cada consumo al saldo de su plan.

    Es el reverso INCONDICIONAL: no aplica la política de cancelación
    (`should_refund_consumption`, que solo devuelve el saldo si la clase está cancelada
    o aún no empezó). Se usa cuando el registro que respaldaba el consumo desaparece del
    historial, y entonces el consumo tiene que desaparecer con él sin importar la fecha:
    la invariante a sostener es `classes_used == count(ConsumptionLog)`. Un log que
    sobrevive a su respaldo es un consumo huérfano —saldo fantasma— y además ciega las
    guardas de borrado, que miran `Enrollment`.

    Devuelve la cantidad de consumos revertidos.

    Es seguro ante dos reversos concurrentes del MISMO consumo (doble click en
    `DELETE /api/enrollments/{id}/` o en `DELETE /api/classes/{id}/`): el saldo se
    devuelve solo por las filas que este DELETE borró de verdad. `Greatest(..., 0)` no
    alcanza como red —solo tapa el caso `classes_used == 1`—, así que el conteo NO puede
    salir del snapshot del SELECT.
    """
    # Se materializan los ids UNA sola vez y se borra por id: contar y borrar sobre el
    # mismo queryset lo reevaluaría dos veces, y un consumo insertado entre ambas
    # sentencias se borraría sin haber sido contado (saldo fantasma, justo lo que esto
    # viene a evitar). `select_for_update` serializa a los competidores en el SELECT: el
    # perdedor lo reevalúa al liberarse el lock y ya no ve los logs borrados (no-op en
    # SQLite, que igual serializa las escrituras; la red real es el rowcount de abajo).
    rows = list(log_queryset.select_for_update().values_list('id', 'student_plan_id'))
    if not rows:
        return 0

    # Se agrupa por plan porque `ConsumptionLog` no tiene unique constraint sobre
    # (user, class_instance, student_plan): pueden existir dos logs del MISMO plan para
    # la misma clase, y hay que devolver los dos consumos, no uno.
    ids_by_plan = defaultdict(list)
    for log_id, plan_id in rows:
        ids_by_plan[plan_id].append(log_id)

    reverted = 0
    for plan_id, log_ids in ids_by_plan.items():
        # El saldo baja por lo que el DELETE realmente se llevó, no por lo que el SELECT
        # había visto: si otra transacción ya borró estos logs, `consumed` es 0 y no se
        # devuelve un saldo que ya devolvió ella.
        # Del rowcount se toma SOLO el de ConsumptionLog: el total de `delete()` incluiría
        # los objetos cascadeados si algún día algo cuelga del log, y ese número no es
        # cantidad de consumos.
        _, deleted_by_model = ConsumptionLog.objects.filter(id__in=log_ids).delete()
        consumed = deleted_by_model.get(ConsumptionLog._meta.label, 0)
        if not consumed:
            continue
        reverted += consumed
        # Decremento en la base y no read-modify-write: si otra reserva concurrente
        # suma su +1 sobre el mismo plan, no se pierde.
        StudentPlan.objects.filter(id=plan_id).update(
            classes_used=Greatest(F('classes_used') - consumed, Value(0)),
            updated_at=timezone.now(),
        )

    return reverted


@transaction.atomic
def revert_consumption(enrollment, student_plan=None):
    """Núcleo único del reverso de consumo POR INSCRIPCIÓN (10.1).

    Resuelve QUÉ `StudentPlan` respalda esta inscripción con la misma prioridad que
    consolidó #9: el FK `enrollment.student_plan` (T1, registro histórico de la
    imputación) manda; solo cuando es NULL se cae a `get_enrollment_student_plan`, que
    infiere por el `ConsumptionLog` y ya devuelve `None` ante un log cross-org (ver su
    docstring) — no se reintroduce esa inferencia como camino primario. Un
    `student_plan` explícito por parámetro pisa a ambos: es para el llamador que ya lo
    tiene resuelto en memoria y no quiere pagar una resolución redundante; no cambia la
    prioridad FK-primero cuando no lo pasan.

    Sin plan resuelto no hay a quién reembolsar: devuelve `0` sin tocar nada (alumno
    con FK NULL y sin log defendible — trial, reserva sin plan, o log histórico
    cross-org).

    Acota el reverso a los logs de ESTA inscripción (`user`, `class_instance`) Y de ESE
    plan puntual: con el alumno con 2+ planes vigentes, el saldo vuelve al que
    efectivamente la respalda, no a cualquiera. Delega el borrado + decremento a
    `_revert_consumption_logs`, que ya trae el lock (`select_for_update` sobre los
    logs) y la idempotencia ante dos reversos concurrentes del mismo consumo — no se
    duplica ese patrón acá.

    NO es el núcleo de `revert_consumption_for_class` ni de
    `revert_consumption_for_enrollment` (el camino de DELETE): esos dos revierten TODO
    lo que cuelga de la clase o de (alumno, clase) sin importar el plan —incluso logs
    cross-org, por diseño, ver sus docstrings—, así que acotar por plan los rompería.
    Ambos siguen yendo directo a `_revert_consumption_logs`.

    Defensa en profundidad: el camino FK (`enrollment.student_plan`) no vuelve a
    validar organización acá —hoy esa invariante la sostienen todos los escritores del
    FK (la resolución de #9 y el backfill de la migración 0033, ambos org-scopeados)—,
    pero el filtro de abajo (`student_plan__organization_id=F(...)`, el mismo
    predicado que ya usa `get_enrollment_student_plan`) es la misma red por si algún
    escritor futuro rompe esa invariante en silencio: si el plan resuelto no es de la
    organización de la clase, el filtro no matchea ningún log y el reverso devuelve
    `0` — el mismo veredicto que "sin plan defendible", nunca un reembolso cross-org.
    """
    resolved_plan = student_plan or enrollment.student_plan or get_enrollment_student_plan(enrollment)
    if not resolved_plan:
        return 0
    return _revert_consumption_logs(
        ConsumptionLog.objects.filter(
            user_id=enrollment.student_id,
            class_instance_id=enrollment.gym_class_id,
            student_plan=resolved_plan,
            student_plan__organization_id=F('class_instance__organization_id'),
        )
    )


@transaction.atomic
def revert_consumption_for_class(gym_class):
    """Devuelve al saldo de cada alumno los consumos de esta clase y borra sus logs.

    Se usa ANTES de eliminar una clase: `ConsumptionLog.class_instance` es CASCADE, así
    que el borrado se llevaría los logs sin tocar `StudentPlan.classes_used` y dejaría
    clases consumidas fantasma.

    Incondicional y SIN acotar por plan ni por organización (a propósito, igual que
    `revert_consumption_for_enrollment`): borra TODO lo que cuelga de la clase, incluso
    un log cross-org, porque sostener `classes_used == count(ConsumptionLog)` importa
    más que la atribución. No pasa por `revert_consumption` (10.1) —ese resuelve UN
    plan por FK para UNA inscripción— sino directo por `_revert_consumption_logs`, el
    núcleo mecánico que ambos comparten.
    """
    return _revert_consumption_logs(ConsumptionLog.objects.filter(class_instance=gym_class))


@transaction.atomic
def revert_consumption_for_enrollment(enrollment):
    """Devuelve el saldo del consumo de ESTA inscripción y borra su log.

    Se usa ANTES de eliminar una inscripción. `ConsumptionLog` no tiene FK a
    `Enrollment` —cuelga de (user, class_instance, student_plan)—, así que el borrado de
    la inscripción no lo cascadea: el log sobrevive y `classes_used` queda inflado. El
    alumno queda cobrado sin reserva y el log huérfano ciega las guardas de borrado de
    clases y de series, que miran `Enrollment`.

    La identificación por (alumno, clase) es exacta: `Enrollment` es
    `unique_together('gym_class', 'student')`, así que esos logs son de esta inscripción
    y de ninguna otra.

    A diferencia de `rollback_consumption_for_enrollment` —el camino de CANCELAR, que
    mantiene el registro y por eso sí respeta la ventana de reembolso y exige
    status='active'—, acá el reverso es incondicional: ver `_revert_consumption_logs`.

    Tampoco acota por plan (a propósito, igual que `revert_consumption_for_class`): si
    un log histórico cross-org quedó colgado de (alumno, clase), este DELETE también
    se lo lleva y le devuelve su +1 al plan ajeno que lo respaldaba — es la misma
    excepción documentada arriba. No pasa por `revert_consumption` (10.1), que sí
    acota por plan; va directo a `_revert_consumption_logs`.
    """
    return _revert_consumption_logs(
        ConsumptionLog.objects.filter(
            user_id=enrollment.student_id,
            class_instance_id=enrollment.gym_class_id,
        )
    )


def _validate_reservation_rules(*, student, gym_class, existing=None, require_plan=True, student_plan_id=None):
    if student.organization_id != gym_class.organization_id:
        raise ReservationRuleError('No puedes inscribir alumnos de otra organización.', code='wrong_organization')
    if gym_class.status == GymClass.Status.CANCELLED:
        raise ReservationRuleError('No puedes reservar una clase cancelada.', code='class_cancelled')
    if gym_class.status == GymClass.Status.SUSPENDED:
        raise ReservationRuleError('No puedes reservar una clase suspendida.', code='class_suspended')
    if gym_class.start_datetime <= timezone.now():
        raise ReservationRuleError('No puedes reservar clases pasadas o ya iniciadas.', code='class_started')
    if gym_class.status in TERMINAL_CLASS_STATUSES:
        raise ReservationRuleError('No puedes reservar una clase cerrada.', code='class_closed')

    active_duplicate = Enrollment.objects.filter(gym_class=gym_class, student=student, status='active')
    if existing:
        active_duplicate = active_duplicate.exclude(id=existing.id)
    if active_duplicate.exists():
        raise ReservationRuleError('El alumno ya tiene una reserva para esta clase.', code='duplicate_enrollment')

    active_count = gym_class.enrollments.filter(status='active')
    if existing:
        active_count = active_count.exclude(id=existing.id)
    if active_count.count() >= gym_class.capacity:
        raise ReservationRuleError('La clase ya alcanzó su capacidad máxima.', code='class_full')

    # Acotado a la organizacion de la clase: un alumno movido de organizacion conserva
    # sus reservas activas de la anterior, y el solape las encontraba. Bloqueaba una reserva
    # legitima y delataba que en ese horario hay algo en el otro gimnasio.
    overlapping_enrollments = Enrollment.objects.filter(
        student=student,
        status='active',
        gym_class__organization_id=gym_class.organization_id,
        gym_class__status__in=[GymClass.Status.SCHEDULED, GymClass.Status.IN_PROGRESS],
        gym_class__start_datetime__lt=gym_class.end_datetime,
        gym_class__end_datetime__gt=gym_class.start_datetime,
    )
    if existing:
        overlapping_enrollments = overlapping_enrollments.exclude(id=existing.id)
    if overlapping_enrollments.exists():
        raise ReservationRuleError('El alumno ya tiene otra clase reservada o confirmada en ese horario.', code='student_conflict')

    if not require_plan:
        return None

    student_plan = resolve_student_plan_for_reservation(student, student_plan_id=student_plan_id)
    validate_plan_branch_for_class(student_plan, gym_class)
    return student_plan


@transaction.atomic
def reserve_student_in_class(*, student, gym_class, recurring_enrollment=None, require_plan=True, is_trial=False, student_plan_id=None):
    existing = Enrollment.objects.filter(gym_class=gym_class, student=student).first()
    student_plan = _validate_reservation_rules(
        student=student,
        gym_class=gym_class,
        existing=existing,
        require_plan=require_plan,
        student_plan_id=student_plan_id,
    )

    if existing:
        existing.status = 'active'
        existing.recurring_enrollment = recurring_enrollment or existing.recurring_enrollment
        update_fields = ['status', 'recurring_enrollment', 'updated_at']
        if is_trial and not existing.is_trial:
            existing.is_trial = True
            update_fields.append('is_trial')
        # Reactivación (9.1): si esta reserva SÍ pasó por resolución de plan, se registra
        # la imputación igual que en el alta. Si vino None —`require_plan=False` o
        # trial—, se deja el valor previo intacto: no hay membresía nueva que atribuirle,
        # y pisarlo a NULL borraría el registro histórico de una imputación anterior.
        if student_plan is not None:
            existing.student_plan = student_plan
            update_fields.append('student_plan')
        existing.save(update_fields=update_fields)
        enrollment = existing
    else:
        enrollment = Enrollment.objects.create(
            gym_class=gym_class,
            student=student,
            recurring_enrollment=recurring_enrollment,
            status='active',
            is_trial=is_trial,
            student_plan=student_plan,
        )

    if student_plan:
        consume_student_plan_for_enrollment(enrollment, student_plan)
    return enrollment


@transaction.atomic
def cancel_enrollment_with_refund(enrollment):
    rollback_consumption_for_enrollment(enrollment)
    enrollment.status = 'cancelled'
    enrollment.save(update_fields=['status', 'updated_at'])
    return enrollment


@transaction.atomic
def cancel_future_recurring_enrollments(recurring_enrollment):
    now = timezone.now()
    queryset = Enrollment.objects.select_related('gym_class', 'student').filter(
        recurring_enrollment=recurring_enrollment,
        status='active',
        gym_class__start_datetime__gt=now,
        gym_class__status__in=[GymClass.Status.SCHEDULED, GymClass.Status.IN_PROGRESS],
    )
    cancelled_count = 0
    for enrollment in queryset:
        cancel_enrollment_with_refund(enrollment)
        cancelled_count += 1
    return cancelled_count
