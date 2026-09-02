from calendar import monthrange
from datetime import date, timedelta

from django.utils import timezone


DEFAULT_CYCLE_START_DAY = 1


def normalize_cycle_start_day(value):
    try:
        day = int(value)
    except (TypeError, ValueError):
        raise ValueError('El dia de inicio debe estar entre 1 y 31.')
    if not 1 <= day <= 31:
        raise ValueError('El dia de inicio debe estar entre 1 y 31.')
    return day


def _clamped_month_day(year, month, day):
    return date(year, month, min(day, monthrange(year, month)[1]))


def _next_month(year, month):
    if month == 12:
        return year + 1, 1
    return year, month + 1


def _previous_month(year, month):
    if month == 1:
        return year - 1, 12
    return year, month - 1


def calendar_month_range(year, month):
    start = date(year, month, 1)
    next_year, next_month = _next_month(year, month)
    return start, date(next_year, next_month, 1) - timedelta(days=1)


def is_full_calendar_month(date_from, date_to):
    start, end = calendar_month_range(date_from.year, date_from.month)
    return date_from == start and date_to == end


def cycle_period_for_month(year, month, start_day):
    start_day = normalize_cycle_start_day(start_day)
    start = _clamped_month_day(year, month, start_day)
    next_year, next_month = _next_month(year, month)
    next_start = _clamped_month_day(next_year, next_month, start_day)
    return start, next_start - timedelta(days=1)


def cycle_start_on_or_before(on_date, start_day):
    start_day = normalize_cycle_start_day(start_day)
    this_month_start = _clamped_month_day(on_date.year, on_date.month, start_day)
    if this_month_start <= on_date:
        return this_month_start
    prev_year, prev_month = _previous_month(on_date.year, on_date.month)
    return _clamped_month_day(prev_year, prev_month, start_day)


def cycle_start_on_or_after(on_date, start_day):
    start_day = normalize_cycle_start_day(start_day)
    this_month_start = _clamped_month_day(on_date.year, on_date.month, start_day)
    if this_month_start >= on_date:
        return this_month_start
    next_year, next_month = _next_month(on_date.year, on_date.month)
    return _clamped_month_day(next_year, next_month, start_day)


def next_cycle_start_after_current_cycle(*, active_start_day, new_start_day, on_date=None):
    on_date = on_date or timezone.localdate()
    current_start = cycle_start_on_or_before(on_date, active_start_day)
    next_current_start = cycle_start_on_or_after(current_start + timedelta(days=1), active_start_day)
    current_end = next_current_start - timedelta(days=1)
    return cycle_start_on_or_after(current_end + timedelta(days=1), new_start_day)


def active_cycle_start_day_for_date(teacher, on_date=None):
    on_date = on_date or timezone.localdate()
    effective_from = getattr(teacher, 'teacher_payment_cycle_effective_from', None)
    previous_day = getattr(teacher, 'teacher_payment_cycle_previous_start_day', None)
    configured_day = getattr(teacher, 'teacher_payment_cycle_start_day', DEFAULT_CYCLE_START_DAY) or DEFAULT_CYCLE_START_DAY
    if effective_from and effective_from > on_date:
        return previous_day or DEFAULT_CYCLE_START_DAY
    return configured_day


def cycle_start_day_for_selected_month(teacher, year, month):
    configured_day = getattr(teacher, 'teacher_payment_cycle_start_day', DEFAULT_CYCLE_START_DAY) or DEFAULT_CYCLE_START_DAY
    effective_from = getattr(teacher, 'teacher_payment_cycle_effective_from', None)
    previous_day = getattr(teacher, 'teacher_payment_cycle_previous_start_day', None)
    if not effective_from:
        return configured_day
    candidate_start, _ = cycle_period_for_month(year, month, configured_day)
    if candidate_start < effective_from:
        return previous_day or DEFAULT_CYCLE_START_DAY
    return configured_day


def payment_period_for_teacher(teacher, date_from, date_to):
    if not is_full_calendar_month(date_from, date_to):
        return date_from, date_to
    start_day = cycle_start_day_for_selected_month(teacher, date_from.year, date_from.month)
    return cycle_period_for_month(date_from.year, date_from.month, start_day)


def schedule_teacher_payment_cycle_change(*, teacher, new_start_day, actor=None, on_date=None):
    from accounts.models import TeacherPaymentCycleChange

    on_date = on_date or timezone.localdate()
    new_start_day = normalize_cycle_start_day(new_start_day)
    active_day = active_cycle_start_day_for_date(teacher, on_date)
    if new_start_day == active_day:
        teacher.teacher_payment_cycle_start_day = new_start_day
        teacher.teacher_payment_cycle_previous_start_day = None
        teacher.teacher_payment_cycle_effective_from = None
        teacher.teacher_payment_cycle_updated_at = timezone.now()
        teacher.teacher_payment_cycle_updated_by = actor if getattr(actor, 'is_authenticated', False) else None
        teacher.save(update_fields=[
            'teacher_payment_cycle_start_day',
            'teacher_payment_cycle_previous_start_day',
            'teacher_payment_cycle_effective_from',
            'teacher_payment_cycle_updated_at',
            'teacher_payment_cycle_updated_by',
        ])
        TeacherPaymentCycleChange.objects.filter(
            teacher=teacher,
            status=TeacherPaymentCycleChange.Status.SCHEDULED,
        ).update(status=TeacherPaymentCycleChange.Status.CANCELLED)
        return None

    effective_from = next_cycle_start_after_current_cycle(
        active_start_day=active_day,
        new_start_day=new_start_day,
        on_date=on_date,
    )
    TeacherPaymentCycleChange.objects.filter(
        teacher=teacher,
        status=TeacherPaymentCycleChange.Status.SCHEDULED,
    ).update(status=TeacherPaymentCycleChange.Status.CANCELLED)
    change = TeacherPaymentCycleChange.objects.create(
        teacher=teacher,
        organization_id=teacher.organization_id,
        previous_start_day=active_day,
        new_start_day=new_start_day,
        effective_from=effective_from,
        requested_by=actor if getattr(actor, 'is_authenticated', False) else None,
    )
    teacher.teacher_payment_cycle_start_day = new_start_day
    teacher.teacher_payment_cycle_previous_start_day = active_day
    teacher.teacher_payment_cycle_effective_from = effective_from
    teacher.teacher_payment_cycle_updated_at = timezone.now()
    teacher.teacher_payment_cycle_updated_by = actor if getattr(actor, 'is_authenticated', False) else None
    teacher.save(update_fields=[
        'teacher_payment_cycle_start_day',
        'teacher_payment_cycle_previous_start_day',
        'teacher_payment_cycle_effective_from',
        'teacher_payment_cycle_updated_at',
        'teacher_payment_cycle_updated_by',
    ])
    return change
