from dataclasses import dataclass
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from core.models import Enrollment, StudentPlan, StudentPlanChangeLog, StudentPlanFreeze
from core.services.reservations import cancel_enrollment_with_refund


class MembershipFreezeError(Exception):
    def __init__(self, message, code='membership_freeze_invalid'):
        super().__init__(message)
        self.message = message
        self.code = code


@dataclass
class FreezeCompletionResult:
    freeze: StudentPlanFreeze
    extension_days: int


def freeze_duration_days(start_date, end_date):
    """Intervalo semiabierto: congelada desde start_date, activa otra vez en end_date."""
    return max((end_date - start_date).days, 0)


def freeze_applies_on(freeze, on_date):
    return (
        freeze.status == StudentPlanFreeze.Status.ACTIVE
        and freeze.start_date <= on_date < freeze.planned_end_date
    )


def active_freeze_for_date(student_plan, on_date):
    freezes = getattr(student_plan, '_prefetched_objects_cache', {}).get('freezes')
    if freezes is None:
        freezes = student_plan.freezes.filter(status=StudentPlanFreeze.Status.ACTIVE)
    for freeze in freezes:
        if freeze_applies_on(freeze, on_date):
            return freeze
    return None


def _audit_value(value):
    if value is None:
        return ''
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    return str(value)


def _record_change(*, membership, actor, field, old_value='', new_value='', reason=''):
    StudentPlanChangeLog.objects.create(
        student_plan=membership,
        organization=membership.organization,
        changed_by=actor if getattr(actor, 'is_authenticated', False) else None,
        field=field,
        old_value=_audit_value(old_value),
        new_value=_audit_value(new_value),
        reason=reason,
    )


def _validate_freezable_membership(membership, start_date):
    if not membership.is_active:
        raise MembershipFreezeError(
            'Solo se puede congelar una membresía activa.',
            code='membership_not_freezable',
        )


def _cancel_future_enrollments_in_freeze(freeze):
    queryset = (
        Enrollment.objects
        .select_related('gym_class', 'student')
        .filter(
            student_plan=freeze.student_plan,
            status='active',
            gym_class__start_datetime__gt=timezone.now(),
            gym_class__start_datetime__date__gte=freeze.start_date,
            gym_class__start_datetime__date__lt=freeze.planned_end_date,
        )
        .order_by('gym_class__start_datetime', 'id')
    )
    cancelled = 0
    for enrollment in queryset:
        cancel_enrollment_with_refund(enrollment, block_recurring_resync=True)
        cancelled += 1
    return cancelled


@transaction.atomic
def create_membership_freeze(*, membership, start_date, planned_end_date, reason, actor):
    today = timezone.localdate()
    if start_date < today:
        raise MembershipFreezeError(
            'La fecha de inicio no puede estar en el pasado.',
            code='freeze_start_in_past',
        )
    if planned_end_date <= start_date:
        raise MembershipFreezeError(
            'La fecha de término debe ser posterior al inicio.',
            code='invalid_freeze_period',
        )

    membership = (
        StudentPlan.objects
        .select_for_update()
        .select_related('plan', 'user')
        .prefetch_related('origin_transactions', 'manual_payments', 'freezes')
        .get(pk=membership.pk)
    )
    if membership.freezes.filter(status=StudentPlanFreeze.Status.ACTIVE).exists():
        raise MembershipFreezeError(
            'La membresía ya tiene un congelamiento abierto.',
            code='active_freeze_exists',
        )
    _validate_freezable_membership(membership, start_date)

    try:
        freeze = StudentPlanFreeze.objects.create(
            student_plan=membership,
            organization=membership.organization,
            start_date=start_date,
            planned_end_date=planned_end_date,
            reason=reason,
            status=StudentPlanFreeze.Status.ACTIVE,
            created_by=actor if getattr(actor, 'is_authenticated', False) else None,
        )
    except IntegrityError as exc:
        raise MembershipFreezeError(
            'La membresía ya tiene un congelamiento abierto.',
            code='active_freeze_exists',
        ) from exc

    cancelled = _cancel_future_enrollments_in_freeze(freeze)
    if cancelled:
        freeze.cancelled_future_enrollments = cancelled
        freeze.save(update_fields=['cancelled_future_enrollments', 'updated_at'])

    planned_days = freeze_duration_days(start_date, planned_end_date)
    _record_change(
        membership=membership,
        actor=actor,
        field='membership_freeze_started',
        old_value='',
        new_value=(
            f'{start_date.isoformat()} a {planned_end_date.isoformat()} '
            f'({planned_days} días, término exclusivo)'
        ),
        reason=reason,
    )
    if cancelled:
        _record_change(
            membership=membership,
            actor=actor,
            field='freeze_future_reservations_cancelled',
            old_value='0',
            new_value=str(cancelled),
            reason='Reservas futuras dentro del congelamiento canceladas con devolución de saldo.',
        )
    return freeze


@transaction.atomic
def complete_membership_freeze(*, freeze, actual_end_date, actor=None, reason='', automatic=False):
    freeze = (
        StudentPlanFreeze.objects
        .select_for_update()
        .select_related('student_plan', 'student_plan__plan', 'student_plan__user')
        .get(pk=freeze.pk)
    )
    if freeze.status != StudentPlanFreeze.Status.ACTIVE:
        raise MembershipFreezeError(
            'El congelamiento ya está cerrado.',
            code='freeze_already_completed',
        )
    if actual_end_date < freeze.start_date:
        actual_end_date = freeze.start_date
    if actual_end_date > freeze.planned_end_date:
        actual_end_date = freeze.planned_end_date

    membership = (
        StudentPlan.objects
        .select_for_update()
        .get(pk=freeze.student_plan_id)
    )
    old_end_date = membership.end_date
    extension_days = freeze_duration_days(freeze.start_date, actual_end_date)
    membership.end_date = membership.end_date + timedelta(days=extension_days)
    membership.save(update_fields=['end_date', 'updated_at'])

    freeze.status = StudentPlanFreeze.Status.COMPLETED
    freeze.actual_end_date = actual_end_date
    freeze.extension_days = extension_days
    freeze.ended_by = actor if getattr(actor, 'is_authenticated', False) else None
    freeze.ended_at = timezone.now()
    freeze.save(update_fields=[
        'status',
        'actual_end_date',
        'extension_days',
        'ended_by',
        'ended_at',
        'updated_at',
    ])

    audit_reason = reason or (
        'Descongelamiento automático al llegar la fecha de término.'
        if automatic else
        'Descongelamiento anticipado.'
    )
    _record_change(
        membership=membership,
        actor=actor,
        field='membership_freeze_completed',
        old_value=old_end_date,
        new_value=membership.end_date,
        reason=(
            f'{audit_reason} Congelada realmente por {extension_days} días '
            f'({freeze.start_date.isoformat()} a {actual_end_date.isoformat()}, término exclusivo).'
        ),
    )
    return FreezeCompletionResult(freeze=freeze, extension_days=extension_days)


def complete_due_membership_freezes(*, today=None, org_id=None, dry_run=False):
    today = today or timezone.localdate()
    queryset = (
        StudentPlanFreeze.objects
        .filter(status=StudentPlanFreeze.Status.ACTIVE, planned_end_date__lte=today)
        .select_related('student_plan', 'student_plan__organization')
        .order_by('planned_end_date', 'id')
    )
    if org_id is not None:
        queryset = queryset.filter(organization_id=org_id)

    completed = 0
    for freeze in queryset:
        if dry_run:
            completed += 1
            continue
        complete_membership_freeze(
            freeze=freeze,
            actual_end_date=freeze.planned_end_date,
            actor=None,
            automatic=True,
        )
        completed += 1
    return completed
