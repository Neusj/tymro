"""Feature 3: matrícula (enrollment fee) por StudentPlan.

La matrícula es individual del alumno (no global del plan): 0 = sin matrícula.
Si es > 0 y no está pagada, bloquea las reservas. El vencimiento por defecto es
un año desde la creación del StudentPlan.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from core.models import Branch, GymClass, Plan, StudentPlan
from core.serializers import StudentPlanSerializer
from core.services.reservations import ReservationRuleError, reserve_student_in_class

pytestmark = pytest.mark.django_db


@pytest.fixture
def setup(make_organization, make_user):
    org = make_organization()
    teacher = make_user('teach', organization=org, role='teacher')
    student = make_user('alu', organization=org, role='student', email='alu@gym.cl')
    branch = Branch.objects.create(organization=org, name='Sede')
    return {'org': org, 'teacher': teacher, 'student': student, 'branch': branch}


def _plan_with_fee(org, user, fee, paid=False, due_at=None):
    today = timezone.localdate()
    plan = Plan.objects.create(
        organization=org, name='Plan', plan_type='pack',
        total_classes=8, duration_days=30, price=40000,
    )
    sp = StudentPlan(
        user=user, plan=plan, start_date=today, end_date=today + timedelta(days=30),
        total_classes=8, classes_used=0, final_price=40000, enrollment_fee=fee,
    )
    if paid:
        sp.enrollment_fee_paid_at = timezone.now()
    sp.save()
    if due_at is not None:
        sp.enrollment_fee_due_at = due_at
        sp.save(update_fields=['enrollment_fee_due_at'])
    return sp


def _future_class(org, branch, teacher):
    start = timezone.now() + timedelta(days=1)
    return GymClass.objects.create(
        organization=org, branch=branch, teacher=teacher, name='Clase',
        start_datetime=start, end_datetime=start + timedelta(hours=1),
        capacity=10, status=GymClass.Status.SCHEDULED,
    )


def test_due_at_autocomputed_one_year(setup):
    sp = _plan_with_fee(setup['org'], setup['student'], Decimal('50000'))
    assert sp.enrollment_fee_due_at == (sp.created_at + timedelta(days=365)).date()


def test_no_fee_leaves_due_at_null(setup):
    sp = _plan_with_fee(setup['org'], setup['student'], Decimal('0'))
    assert sp.enrollment_fee_due_at is None


def test_reservation_blocked_when_fee_unpaid(setup):
    _plan_with_fee(setup['org'], setup['student'], Decimal('50000'))
    gym_class = _future_class(setup['org'], setup['branch'], setup['teacher'])
    with pytest.raises(ReservationRuleError) as exc:
        reserve_student_in_class(student=setup['student'], gym_class=gym_class)
    assert exc.value.code == 'enrollment_fee_unpaid'


def test_reservation_allowed_when_fee_paid(setup):
    _plan_with_fee(setup['org'], setup['student'], Decimal('50000'), paid=True)
    gym_class = _future_class(setup['org'], setup['branch'], setup['teacher'])
    enrollment = reserve_student_in_class(student=setup['student'], gym_class=gym_class)
    assert enrollment.status == 'active'


def test_reservation_allowed_when_no_fee(setup):
    _plan_with_fee(setup['org'], setup['student'], Decimal('0'))
    gym_class = _future_class(setup['org'], setup['branch'], setup['teacher'])
    enrollment = reserve_student_in_class(student=setup['student'], gym_class=gym_class)
    assert enrollment.status == 'active'


def test_fee_status_waived_when_no_fee(setup):
    sp = _plan_with_fee(setup['org'], setup['student'], Decimal('0'))
    assert StudentPlanSerializer(sp).data['enrollment_fee_status']['status'] == 'waived'


def test_fee_status_pending_when_unpaid_and_not_overdue(setup):
    sp = _plan_with_fee(setup['org'], setup['student'], Decimal('50000'))
    assert StudentPlanSerializer(sp).data['enrollment_fee_status']['status'] == 'pending'


def test_fee_status_paid(setup):
    sp = _plan_with_fee(setup['org'], setup['student'], Decimal('50000'), paid=True)
    assert StudentPlanSerializer(sp).data['enrollment_fee_status']['status'] == 'paid'


def test_fee_status_overdue(setup):
    yesterday = timezone.localdate() - timedelta(days=1)
    sp = _plan_with_fee(setup['org'], setup['student'], Decimal('50000'), due_at=yesterday)
    assert StudentPlanSerializer(sp).data['enrollment_fee_status']['status'] == 'overdue'
