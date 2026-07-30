from collections import defaultdict

from django.db import transaction
from django.db.models import F, Value
from django.db.models.functions import Greatest
from django.utils import timezone

from ..models import ConsumptionLog, Enrollment, GymClass, StudentPlan
from .plans import (
    REASON_ENROLLMENT_FEE_UNPAID,
    REASON_PLAN_UNAVAILABLE,
    describe_student_plan,
)


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


def validate_student_plan_for_reservation(student, on_date=None):
    """La membresía con la que el alumno puede reservar, o `ReservationRuleError`.

    El saldo y la matrícula ya no se evalúan acá: los resuelve `describe_student_plan`, que
    es la misma fuente que usan el roster y el serializer. Antes eran las dos únicas mitades
    del predicado que existían en un solo lugar —este—, y por eso el roster podía ofrecer
    clases que la reserva después rechazaba.

    Los mensajes y los `code` no cambian: `reason_code` reproduce los mismos valores que esta
    función ya devolvía (`plan_unavailable` / `enrollment_fee_unpaid`), que el frontend maneja.
    """
    target_date = on_date or timezone.localdate()
    student_plan = get_active_student_plan(student, on_date=target_date)
    state = describe_student_plan(student_plan, target_date)
    if state.is_usable:
        return student_plan
    if state.reason_code == REASON_ENROLLMENT_FEE_UNPAID:
        raise ReservationRuleError(
            'Debes pagar la matrícula de tu plan antes de reservar.',
            code=REASON_ENROLLMENT_FEE_UNPAID,
        )
    raise ReservationRuleError(
        'No tienes clases disponibles o plan activo', code=REASON_PLAN_UNAVAILABLE
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
    consumption_log = (
        ConsumptionLog.objects.select_related('student_plan')
        .filter(user=enrollment.student, class_instance=enrollment.gym_class)
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

    student_plan.classes_used += 1
    student_plan.save(update_fields=['classes_used', 'updated_at'])
    return True


def rollback_consumption_for_enrollment(enrollment, student_plan=None):
    if enrollment.status != 'active':
        return False
    resolved_plan = student_plan or get_enrollment_student_plan(enrollment)
    if not resolved_plan:
        return False
    if not should_refund_consumption(enrollment):
        return False

    consumption_log = ConsumptionLog.objects.filter(
        user=enrollment.student,
        class_instance=enrollment.gym_class,
        student_plan=resolved_plan,
    ).first()
    if not consumption_log:
        return False

    consumption_log.delete()
    if resolved_plan.classes_used > 0:
        resolved_plan.classes_used -= 1
        resolved_plan.save(update_fields=['classes_used', 'updated_at'])
    return True


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
def revert_consumption_for_class(gym_class):
    """Devuelve al saldo de cada alumno los consumos de esta clase y borra sus logs.

    Se usa ANTES de eliminar una clase: `ConsumptionLog.class_instance` es CASCADE, así
    que el borrado se llevaría los logs sin tocar `StudentPlan.classes_used` y dejaría
    clases consumidas fantasma.
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
    """
    return _revert_consumption_logs(
        ConsumptionLog.objects.filter(
            user_id=enrollment.student_id,
            class_instance_id=enrollment.gym_class_id,
        )
    )


def _validate_reservation_rules(*, student, gym_class, existing=None, require_plan=True):
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

    student_plan = validate_student_plan_for_reservation(student)
    validate_plan_branch_for_class(student_plan, gym_class)
    return student_plan


@transaction.atomic
def reserve_student_in_class(*, student, gym_class, recurring_enrollment=None, require_plan=True, is_trial=False):
    existing = Enrollment.objects.filter(gym_class=gym_class, student=student).first()
    student_plan = _validate_reservation_rules(
        student=student,
        gym_class=gym_class,
        existing=existing,
        require_plan=require_plan,
    )

    if existing:
        existing.status = 'active'
        existing.recurring_enrollment = recurring_enrollment or existing.recurring_enrollment
        update_fields = ['status', 'recurring_enrollment', 'updated_at']
        if is_trial and not existing.is_trial:
            existing.is_trial = True
            update_fields.append('is_trial')
        existing.save(update_fields=update_fields)
        enrollment = existing
    else:
        enrollment = Enrollment.objects.create(
            gym_class=gym_class,
            student=student,
            recurring_enrollment=recurring_enrollment,
            status='active',
            is_trial=is_trial,
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
