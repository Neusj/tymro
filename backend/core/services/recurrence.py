from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone

from ..models import ClassTemplate, GymClass, Holiday, RecurringEnrollment
from .reservations import (
    ReservationRuleError,
    reserve_student_in_class,
    revert_consumption_for_class,
)


def _delete_class_refunding_consumption(gym_class):
    """Borra una instancia devolviendo antes su consumo al saldo del alumno.

    `ConsumptionLog.class_instance` es CASCADE: borrar la clase a secas se lleva los
    consumos sin decrementar `StudentPlan.classes_used`. Las guardas de este módulo
    miran `Enrollment`, no `ConsumptionLog`, así que una clase sin inscripciones activas
    pero con un consumo huérfano (lo deja `DELETE /api/enrollments/`) pasaba el filtro y
    se borraba dejando saldo fantasma.
    """
    revert_consumption_for_class(gym_class)
    gym_class.delete()


TERMINAL_STATUSES = {
    GymClass.Status.CANCELLED,
    GymClass.Status.COMPLETED,
    GymClass.Status.COMPLETED_EARLY,
}


def _combine_local_datetime(value_date, value_time):
    naive = datetime.combine(value_date, value_time)
    current_tz = timezone.get_current_timezone()
    return timezone.make_aware(naive, current_tz) if timezone.is_naive(naive) else timezone.localtime(naive, current_tz)


def _as_date(value):
    if value is None:
        return None
    if hasattr(value, 'year') and hasattr(value, 'month') and hasattr(value, 'day') and not isinstance(value, str):
        return value
    if isinstance(value, str):
        return datetime.strptime(value, '%Y-%m-%d').date()
    raise ValueError('Invalid date value')


def _iter_template_dates(template, from_date, until_date):
    if until_date < from_date:
        return
    days_until_target = (template.weekday - from_date.weekday()) % 7
    current = from_date + timedelta(days=days_until_target)
    while current <= until_date:
        yield current
        current += timedelta(days=7)


def is_holiday(value_date, organization=None, branch=None):
    holiday_query = Holiday.objects.filter(date=value_date, is_active=True)
    holiday_query = holiday_query.filter(
        Holiday.scope_q_global()
        | Holiday.scope_q_organization(organization_id=getattr(organization, 'id', organization))
        | Holiday.scope_q_branch(branch_id=getattr(branch, 'id', branch))
    )
    return holiday_query.exists()


def _create_enrollment_if_possible(*, recurring_enrollment, gym_class):
    try:
        reserve_student_in_class(
            student=recurring_enrollment.student,
            gym_class=gym_class,
            recurring_enrollment=recurring_enrollment,
            require_plan=True,
        )
    except ReservationRuleError as exc:
        return False, exc.code
    return True, None


@transaction.atomic
def create_enrollments_for_recurring_subscription(recurring_enrollment, class_instances=None, from_date=None, until_date=None):
    if not recurring_enrollment.is_active:
        return {'created_count': 0, 'skipped': [{'reason': 'inactive_recurring_enrollment'}]}

    template = recurring_enrollment.class_template
    effective_from = from_date or recurring_enrollment.start_date
    effective_from = max(effective_from, recurring_enrollment.start_date, template.start_date)

    effective_until = until_date
    if recurring_enrollment.end_date:
        effective_until = min(effective_until, recurring_enrollment.end_date) if effective_until else recurring_enrollment.end_date
    if template.end_date:
        effective_until = min(effective_until, template.end_date) if effective_until else template.end_date

    queryset = class_instances
    if queryset is None:
        queryset = GymClass.objects.filter(class_template=template)
        queryset = queryset.filter(start_datetime__date__gte=effective_from)
        if effective_until:
            queryset = queryset.filter(start_datetime__date__lte=effective_until)

    summary = {'created_count': 0, 'skipped': []}
    for gym_class in queryset:
        class_date = timezone.localtime(gym_class.start_datetime).date()
        if class_date < recurring_enrollment.start_date:
            summary['skipped'].append({'class_id': gym_class.id, 'reason': 'before_subscription_start'})
            continue
        if recurring_enrollment.end_date and class_date > recurring_enrollment.end_date:
            summary['skipped'].append({'class_id': gym_class.id, 'reason': 'after_subscription_end'})
            continue
        created, reason = _create_enrollment_if_possible(recurring_enrollment=recurring_enrollment, gym_class=gym_class)
        if created:
            summary['created_count'] += 1
        else:
            summary['skipped'].append({'class_id': gym_class.id, 'reason': reason})

    return summary


def sync_recurring_enrollments_for_generated_instances(template, class_instances):
    recurring_items = RecurringEnrollment.objects.filter(class_template=template, is_active=True).select_related('student')
    for recurring_enrollment in recurring_items:
        create_enrollments_for_recurring_subscription(
            recurring_enrollment=recurring_enrollment,
            class_instances=class_instances,
        )


@transaction.atomic
def generate_instances_for_template_range(template, from_date=None, until_date=None, created_by=None, skip_holidays=True):
    parsed_from = _as_date(from_date) if from_date is not None else None
    parsed_until = _as_date(until_date) if until_date is not None else None

    effective_from = max(template.start_date, parsed_from or timezone.localdate())
    effective_until = parsed_until or template.end_date or (effective_from + timedelta(days=365))
    if template.end_date:
        effective_until = min(effective_until, template.end_date)

    summary = {'created_count': 0, 'created_ids': [], 'skipped': []}
    if not template.is_active:
        summary['skipped'].append({'reason': 'inactive_template'})
        return summary
    if effective_until < effective_from:
        return summary

    for occurrence_date in _iter_template_dates(template, effective_from, effective_until):
        if skip_holidays and is_holiday(occurrence_date, organization=template.organization_id, branch=template.branch_id):
            summary['skipped'].append({'date': occurrence_date.isoformat(), 'reason': 'holiday'})
            continue

        if GymClass.objects.filter(class_template=template, start_datetime__date=occurrence_date).exists():
            summary['skipped'].append({'date': occurrence_date.isoformat(), 'reason': 'duplicate_instance'})
            continue

        start_datetime = _combine_local_datetime(occurrence_date, template.start_time)
        end_datetime = _combine_local_datetime(occurrence_date, template.end_time)

        if GymClass.objects.filter(
            teacher=template.teacher,
            start_datetime__lt=end_datetime,
            end_datetime__gt=start_datetime,
        ).exclude(status=GymClass.Status.CANCELLED).exists():
            summary['skipped'].append({'date': occurrence_date.isoformat(), 'reason': 'teacher_conflict'})
            continue

        gym_class = GymClass.objects.create(
            organization=template.organization,
            class_template=template,
            branch=template.branch,
            teacher=template.teacher,
            class_type=template.class_type,
            discipline=template.discipline,
            name=template.name or (template.class_type.name if template.class_type else f'Clase {template.get_weekday_display()}'),
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            capacity=template.capacity,
            is_trial_eligible=template.is_trial_eligible,
            status=GymClass.Status.SCHEDULED,
            created_by=created_by or template.created_by,
            is_active=True,
        )
        summary['created_count'] += 1
        summary['created_ids'].append(gym_class.id)

    if summary['created_ids']:
        instances = list(GymClass.objects.filter(id__in=summary['created_ids']).order_by('start_datetime'))
        sync_recurring_enrollments_for_generated_instances(template=template, class_instances=instances)

    return summary


@transaction.atomic
def apply_template_updates_to_future_instances(template, now=None):
    now = now or timezone.now()
    future_instances = GymClass.objects.filter(
        class_template=template,
        start_datetime__gt=now,
    ).exclude(status__in=TERMINAL_STATUSES)

    summary = {'updated_count': 0, 'protected_count': 0, 'protected_ids': []}
    for gym_class in future_instances:
        has_active_enrollments = gym_class.enrollments.filter(status='active').exists()
        if has_active_enrollments:
            summary['protected_count'] += 1
            summary['protected_ids'].append(gym_class.id)
            continue

        class_date = timezone.localtime(gym_class.start_datetime).date()
        if class_date < template.start_date:
            _delete_class_refunding_consumption(gym_class)
            continue
        if template.end_date and class_date > template.end_date:
            _delete_class_refunding_consumption(gym_class)
            continue
        if class_date.weekday() != template.weekday:
            _delete_class_refunding_consumption(gym_class)
            continue
        if is_holiday(class_date, organization=template.organization_id, branch=template.branch_id):
            _delete_class_refunding_consumption(gym_class)
            continue

        gym_class.name = template.name or gym_class.name
        gym_class.branch = template.branch
        gym_class.teacher = template.teacher
        gym_class.class_type = template.class_type
        gym_class.discipline = template.discipline
        gym_class.capacity = template.capacity
        gym_class.is_trial_eligible = template.is_trial_eligible
        gym_class.start_datetime = _combine_local_datetime(class_date, template.start_time)
        gym_class.end_datetime = _combine_local_datetime(class_date, template.end_time)

        teacher_conflict = GymClass.objects.filter(
            teacher=template.teacher,
            start_datetime__lt=gym_class.end_datetime,
            end_datetime__gt=gym_class.start_datetime,
        ).exclude(status=GymClass.Status.CANCELLED).exclude(id=gym_class.id)
        if teacher_conflict.exists():
            summary['protected_count'] += 1
            summary['protected_ids'].append(gym_class.id)
            continue

        gym_class.save(
            update_fields=[
                'name',
                'branch',
                'teacher',
                'class_type',
                'discipline',
                'capacity',
                'is_trial_eligible',
                'start_datetime',
                'end_datetime',
                'updated_at',
            ]
        )
        summary['updated_count'] += 1

    regeneration = generate_instances_for_template_range(
        template=template,
        from_date=max(timezone.localdate(), template.start_date),
        until_date=template.end_date,
        created_by=template.created_by,
    )
    summary['regeneration'] = regeneration
    return summary


def can_delete_template(template):
    instances = GymClass.objects.filter(class_template=template)
    if RecurringEnrollment.objects.filter(class_template=template).exists():
        return False, 'La serie tiene recurrencias de alumnos asociadas.'
    if instances.filter(enrollments__isnull=False).exists():
        return False, 'La serie tiene clases con alumnos inscritos o historial de reservas.'
    if instances.filter(attendances__isnull=False).exists():
        return False, 'La serie tiene asistencia registrada.'
    if instances.filter(status__in=[GymClass.Status.COMPLETED, GymClass.Status.COMPLETED_EARLY]).exists():
        return False, 'La serie tiene historial consolidado.'
    return True, None


@transaction.atomic
def delete_template_safely(template):
    can_delete, reason = can_delete_template(template)
    if not can_delete:
        return {'deleted': False, 'reason': reason}

    # Instancia por instancia y no un `.delete()` en bloque: cada una tiene que devolver
    # su consumo antes de que la cascada se lleve el ConsumptionLog. `can_delete_template`
    # mira Enrollment, así que un consumo huérfano llega hasta acá.
    for gym_class in GymClass.objects.filter(class_template=template):
        _delete_class_refunding_consumption(gym_class)
    template.delete()
    return {'deleted': True}


@transaction.atomic
def cancel_future_instances_for_template(template, actor=None, comment='Cancelacion masiva de serie'):
    now = timezone.now()
    queryset = GymClass.objects.filter(
        class_template=template,
        start_datetime__gt=now,
        status__in=[GymClass.Status.SCHEDULED, GymClass.Status.IN_PROGRESS],
    )
    updated_count = queryset.update(
        status=GymClass.Status.CANCELLED,
        is_active=False,
        closure_comment=comment,
        closed_by=actor if actor else None,
        closed_at=now,
    )
    return {'updated_count': updated_count}


@transaction.atomic
def activate_template(template):
    if template.is_active:
        return {'updated': False, 'reason': 'already_active'}
    template.is_active = True
    template.save(update_fields=['is_active', 'updated_at'])
    return {'updated': True}


@transaction.atomic
def reactivate_future_cancelled_instances_for_template(template):
    now = timezone.now()
    cancelled_instances = GymClass.objects.filter(
        class_template=template,
        status=GymClass.Status.CANCELLED,
        start_datetime__gt=now,
    )

    summary = {'reactivated_count': 0, 'skipped': []}
    for gym_class in cancelled_instances:
        if gym_class.attendances.exists():
            summary['skipped'].append({'id': gym_class.id, 'reason': 'has_attendance'})
            continue
        if gym_class.closed_at and gym_class.closed_at <= now:
            summary['skipped'].append({'id': gym_class.id, 'reason': 'already_closed_in_past'})
            continue
        if template.end_date and timezone.localtime(gym_class.start_datetime).date() > template.end_date:
            summary['skipped'].append({'id': gym_class.id, 'reason': 'outside_template_range'})
            continue
        if is_holiday(
            timezone.localtime(gym_class.start_datetime).date(),
            organization=template.organization_id,
            branch=template.branch_id,
        ):
            summary['skipped'].append({'id': gym_class.id, 'reason': 'holiday'})
            continue
        if GymClass.objects.filter(
            teacher=template.teacher,
            start_datetime__lt=gym_class.end_datetime,
            end_datetime__gt=gym_class.start_datetime,
        ).exclude(status=GymClass.Status.CANCELLED).exclude(id=gym_class.id).exists():
            summary['skipped'].append({'id': gym_class.id, 'reason': 'teacher_conflict'})
            continue

        gym_class.status = GymClass.Status.SCHEDULED
        gym_class.is_active = True
        gym_class.closed_at = None
        gym_class.closed_by = None
        gym_class.closure_comment = ''
        gym_class.save(update_fields=['status', 'is_active', 'closed_at', 'closed_by', 'closure_comment', 'updated_at'])
        summary['reactivated_count'] += 1

    return summary
