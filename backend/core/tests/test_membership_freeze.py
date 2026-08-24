from datetime import time, timedelta

import pytest
from django.utils import timezone

from core.models import (
    Branch,
    ClassTemplate,
    ConsumptionLog,
    Enrollment,
    GymClass,
    Plan,
    RecurringEnrollment,
    StudentPlan,
    StudentPlanChangeLog,
    StudentPlanFreeze,
)
from core.services.membership_freezes import (
    MembershipFreezeError,
    complete_due_membership_freezes,
    complete_membership_freeze,
    create_membership_freeze,
)
from core.serializers import StudentPlanSerializer
from core.services.plans import PlanStatus, describe_student_plan
from core.services.recurrence import create_enrollments_for_recurring_subscription
from core.services.reservations import ReservationRuleError, reserve_student_in_class

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()


@pytest.fixture
def setup(make_organization, make_user):
    org = make_organization()
    admin = make_user('freeze-admin', organization=org, role='gym_admin')
    teacher = make_user('freeze-teacher', organization=org, role='teacher')
    student = make_user('freeze-student', organization=org, role='student')
    branch = Branch.objects.create(organization=org, name='Sede')
    plan = Plan.objects.create(
        organization=org,
        name='Pack freeze',
        plan_type='pack',
        total_classes=10,
        duration_days=30,
        price=30000,
    )
    membership = StudentPlan.objects.create(
        user=student,
        plan=plan,
        organization=org,
        branch=branch,
        start_date=TODAY - timedelta(days=1),
        end_date=TODAY + timedelta(days=30),
        total_classes=10,
        classes_used=0,
        final_price=30000,
        is_active=True,
    )
    return {
        'org': org,
        'admin': admin,
        'teacher': teacher,
        'student': student,
        'branch': branch,
        'plan': plan,
        'membership': membership,
    }


def _future_class(setup, days=1, template=None):
    start = timezone.now() + timedelta(days=days)
    return GymClass.objects.create(
        organization=setup['org'],
        branch=setup['branch'],
        teacher=setup['teacher'],
        class_template=template,
        name='Clase freeze',
        start_datetime=start,
        end_datetime=start + timedelta(hours=1),
        capacity=10,
        status=GymClass.Status.SCHEDULED,
    )


def _freeze(membership, admin, *, start=TODAY, days=10):
    return create_membership_freeze(
        membership=membership,
        start_date=start,
        planned_end_date=start + timedelta(days=days),
        reason='Lesion',
        actor=admin,
    )


def test_normal_freeze_blocks_use_then_auto_completion_extends_membership(setup):
    membership = setup['membership']
    freeze = _freeze(membership, setup['admin'], days=10)
    membership.refresh_from_db()

    state_during = describe_student_plan(membership, TODAY)
    assert state_during.status == PlanStatus.FROZEN
    assert state_during.is_usable is False

    with pytest.raises(ReservationRuleError) as exc_info:
        reserve_student_in_class(
            student=setup['student'],
            gym_class=_future_class(setup, days=1),
            student_plan_id=membership.id,
        )
    assert exc_info.value.code == 'chosen_plan_unavailable'
    membership.refresh_from_db()
    assert membership.classes_used == 0
    assert not ConsumptionLog.objects.filter(student_plan=membership).exists()

    completed = complete_due_membership_freezes(today=TODAY + timedelta(days=10))
    assert completed == 1
    membership.refresh_from_db()
    freeze.refresh_from_db()
    assert freeze.status == StudentPlanFreeze.Status.COMPLETED
    assert freeze.actual_end_date == TODAY + timedelta(days=10)
    assert freeze.extension_days == 10
    assert membership.end_date == TODAY + timedelta(days=40)
    assert describe_student_plan(membership, TODAY + timedelta(days=10)).status == PlanStatus.ACTIVE


def test_freeze_interval_start_is_inclusive_and_end_is_exclusive(setup):
    membership = setup['membership']
    _freeze(membership, setup['admin'], days=1)
    membership.refresh_from_db()

    assert describe_student_plan(membership, TODAY).status == PlanStatus.FROZEN
    assert describe_student_plan(membership, TODAY + timedelta(days=1)).status == PlanStatus.ACTIVE


def test_frozen_membership_stays_in_valid_on_until_freeze_end_even_after_original_expiry(setup):
    membership = setup['membership']
    membership.end_date = TODAY + timedelta(days=2)
    membership.save(update_fields=['end_date', 'updated_at'])
    _freeze(membership, setup['admin'], days=10)

    target = TODAY + timedelta(days=5)
    assert StudentPlan.objects.valid_on(target).filter(id=membership.id).exists()
    membership.refresh_from_db()
    assert describe_student_plan(membership, target).status == PlanStatus.FROZEN


def test_early_unfreeze_extends_only_real_frozen_days(setup):
    membership = setup['membership']
    membership.end_date = TODAY + timedelta(days=60)
    membership.save(update_fields=['end_date', 'updated_at'])
    freeze = StudentPlanFreeze.objects.create(
        student_plan=membership,
        organization=setup['org'],
        start_date=TODAY - timedelta(days=12),
        planned_end_date=TODAY + timedelta(days=18),
        reason='Viaje',
        created_by=setup['admin'],
    )

    result = complete_membership_freeze(
        freeze=freeze,
        actual_end_date=TODAY,
        actor=setup['admin'],
        reason='Volvio antes',
    )

    membership.refresh_from_db()
    freeze.refresh_from_db()
    assert result.extension_days == 12
    assert freeze.extension_days == 12
    assert freeze.actual_end_date == TODAY
    assert membership.end_date == TODAY + timedelta(days=72)


def test_unfreeze_future_freeze_closes_without_extension(setup):
    membership = setup['membership']
    original_end_date = membership.end_date
    freeze = _freeze(membership, setup['admin'], start=TODAY + timedelta(days=5), days=10)

    result = complete_membership_freeze(
        freeze=freeze,
        actual_end_date=TODAY,
        actor=setup['admin'],
        reason='Liberacion anticipada.',
    )

    membership.refresh_from_db()
    freeze.refresh_from_db()
    assert result.extension_days == 0
    assert freeze.status == StudentPlanFreeze.Status.COMPLETED
    assert freeze.actual_end_date == TODAY + timedelta(days=5)
    assert membership.end_date == original_end_date


def test_freeze_api_permissions(api_client, setup):
    url = f"/api/plans/{setup['plan'].id}/memberships/{setup['membership'].id}/freeze/"
    payload = {
        'start_date': TODAY.isoformat(),
        'planned_end_date': (TODAY + timedelta(days=5)).isoformat(),
        'reason': 'Reposo',
    }

    api_client.force_authenticate(setup['admin'])
    admin_response = api_client.post(url, payload, format='json')
    assert admin_response.status_code == 200, admin_response.content

    other_membership = StudentPlan.objects.create(
        user=setup['student'],
        plan=setup['plan'],
        organization=setup['org'],
        branch=setup['branch'],
        start_date=TODAY - timedelta(days=1),
        end_date=TODAY + timedelta(days=30),
        total_classes=10,
        final_price=30000,
        is_active=True,
    )
    other_url = f"/api/plans/{setup['plan'].id}/memberships/{other_membership.id}/freeze/"

    api_client.force_authenticate(setup['student'])
    student_response = api_client.post(other_url, payload, format='json')
    assert student_response.status_code == 403

    api_client.force_authenticate(setup['teacher'])
    teacher_response = api_client.post(other_url, payload, format='json')
    assert teacher_response.status_code == 403


def test_serializer_exposes_open_freeze_before_start_date(setup):
    membership = setup['membership']
    _freeze(membership, setup['admin'], start=TODAY + timedelta(days=3), days=7)
    membership.refresh_from_db()

    data = StudentPlanSerializer(membership).data

    assert describe_student_plan(membership, TODAY).status == PlanStatus.ACTIVE
    assert data['validity_status'] == PlanStatus.ACTIVE
    assert data['validity_status_label'] == 'Vigente'
    assert data['active_freeze']['start_date'] == (TODAY + timedelta(days=3)).isoformat()


def test_freeze_rejects_inactive_memberships_and_second_active_freeze(setup):
    membership = setup['membership']
    _freeze(membership, setup['admin'], days=5)

    with pytest.raises(MembershipFreezeError) as duplicate:
        _freeze(membership, setup['admin'], days=2)
    assert duplicate.value.code == 'active_freeze_exists'

    expired = StudentPlan.objects.create(
        user=setup['student'],
        plan=setup['plan'],
        organization=setup['org'],
        start_date=TODAY - timedelta(days=30),
        end_date=TODAY - timedelta(days=1),
        total_classes=10,
        final_price=30000,
        is_active=True,
    )
    expired_freeze = _freeze(expired, setup['admin'], days=5)
    assert expired_freeze.status == StudentPlanFreeze.Status.ACTIVE

    inactive = StudentPlan.objects.create(
        user=setup['student'],
        plan=setup['plan'],
        organization=setup['org'],
        start_date=TODAY - timedelta(days=1),
        end_date=TODAY + timedelta(days=30),
        total_classes=10,
        final_price=30000,
        is_active=False,
    )
    with pytest.raises(MembershipFreezeError) as inactive_error:
        _freeze(inactive, setup['admin'], days=5)
    assert inactive_error.value.code == 'membership_not_freezable'

    with pytest.raises(MembershipFreezeError) as invalid_period:
        create_membership_freeze(
            membership=inactive,
            start_date=TODAY,
            planned_end_date=TODAY,
            reason='Periodo invalido',
            actor=setup['admin'],
        )
    assert invalid_period.value.code == 'invalid_freeze_period'


def test_future_reservations_inside_freeze_are_cancelled_and_refunded(setup):
    membership = setup['membership']
    inside = _future_class(setup, days=2)
    outside = _future_class(setup, days=20)
    enrollment_inside = reserve_student_in_class(
        student=setup['student'],
        gym_class=inside,
        student_plan_id=membership.id,
    )
    enrollment_outside = reserve_student_in_class(
        student=setup['student'],
        gym_class=outside,
        student_plan_id=membership.id,
    )
    membership.refresh_from_db()
    assert membership.classes_used == 2

    freeze = _freeze(membership, setup['admin'], days=10)

    membership.refresh_from_db()
    enrollment_inside.refresh_from_db()
    enrollment_outside.refresh_from_db()
    assert freeze.cancelled_future_enrollments == 1
    assert enrollment_inside.status == 'cancelled'
    assert enrollment_outside.status == 'active'
    assert membership.classes_used == 1
    assert not ConsumptionLog.objects.filter(class_instance=inside, student_plan=membership).exists()
    assert ConsumptionLog.objects.filter(class_instance=outside, student_plan=membership).exists()


def test_recurring_materialization_with_frozen_membership_is_skipped(setup):
    membership = setup['membership']
    template = ClassTemplate.objects.create(
        organization=setup['org'],
        branch=setup['branch'],
        teacher=setup['teacher'],
        name='Serie freeze',
        weekday=0,
        start_time=time(10, 0),
        end_time=time(11, 0),
        capacity=10,
        start_date=TODAY - timedelta(days=30),
    )
    recurring = RecurringEnrollment.objects.create(
        student=setup['student'],
        class_template=template,
        start_date=TODAY - timedelta(days=1),
        student_plan=membership,
    )
    gym_class = _future_class(setup, days=2, template=template)
    _freeze(membership, setup['admin'], days=10)

    summary = create_enrollments_for_recurring_subscription(recurring, class_instances=[gym_class])

    assert summary['created_count'] == 0
    assert summary['skipped'] == [{'class_id': gym_class.id, 'reason': 'plan_unavailable'}]
    assert not Enrollment.objects.filter(gym_class=gym_class, student=setup['student']).exists()


def test_freeze_and_unfreeze_are_recorded_in_existing_change_log(setup):
    membership = setup['membership']
    freeze = _freeze(membership, setup['admin'], days=4)
    complete_membership_freeze(
        freeze=freeze,
        actual_end_date=TODAY + timedelta(days=2),
        actor=setup['admin'],
        reason='Alta medica',
    )

    fields = list(
        StudentPlanChangeLog.objects
        .filter(student_plan=membership)
        .order_by('created_at', 'id')
        .values_list('field', flat=True)
    )
    assert 'membership_freeze_started' in fields
    assert 'membership_freeze_completed' in fields
