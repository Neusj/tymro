from django.db import transaction
from django.utils import timezone

from ..models import ConsumptionLog, Enrollment, GymClass, StudentPlan


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
    target_date = on_date or timezone.localdate()
    return (
        StudentPlan.objects.filter(
            user=student,
            is_active=True,
            start_date__lte=target_date,
            end_date__gte=target_date,
        )
        .order_by('-start_date', '-id')
        .first()
    )


def validate_student_plan_for_reservation(student, on_date=None):
    student_plan = get_active_student_plan(student, on_date=on_date)
    if not student_plan:
        raise ReservationRuleError('No tienes clases disponibles o plan activo', code='plan_unavailable')
    if not student_plan.unlimited_classes and student_plan.classes_used >= student_plan.total_classes:
        raise ReservationRuleError('No tienes clases disponibles o plan activo', code='plan_unavailable')
    return student_plan


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

    _, created = ConsumptionLog.objects.get_or_create(
        user=enrollment.student,
        class_instance=enrollment.gym_class,
        student_plan=student_plan,
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


def _validate_reservation_rules(*, student, gym_class, existing=None, require_plan=True):
    if student.organization_id != gym_class.organization_id:
        raise ReservationRuleError('No puedes inscribir alumnos de otra organización.', code='wrong_organization')
    if gym_class.status == GymClass.Status.CANCELLED:
        raise ReservationRuleError('No puedes reservar una clase cancelada.', code='class_cancelled')
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

    overlapping_enrollments = Enrollment.objects.filter(
        student=student,
        status='active',
        gym_class__status__in=[GymClass.Status.SCHEDULED, GymClass.Status.IN_PROGRESS],
        gym_class__start_datetime__lt=gym_class.end_datetime,
        gym_class__end_datetime__gt=gym_class.start_datetime,
    )
    if existing:
        overlapping_enrollments = overlapping_enrollments.exclude(id=existing.id)
    if overlapping_enrollments.exists():
        raise ReservationRuleError('El alumno ya tiene otra clase reservada o confirmada en ese horario.', code='student_conflict')

    return validate_student_plan_for_reservation(student) if require_plan else None


@transaction.atomic
def reserve_student_in_class(*, student, gym_class, recurring_enrollment=None, require_plan=True):
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
        existing.save(update_fields=['status', 'recurring_enrollment', 'updated_at'])
        enrollment = existing
    else:
        enrollment = Enrollment.objects.create(
            gym_class=gym_class,
            student=student,
            recurring_enrollment=recurring_enrollment,
            status='active',
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
