"""Feature 1: modalidad de pago a profesor 'per_plan_price'.

El profesor cobra un % del 'precio por clase' (final_price / total_classes) de
los planes de los alumnos. La base de alumnos es configurable por regla:
- active_enrollments: todos los inscritos activos (asistan o no).
- present_attendees: solo los marcados presentes.
Los planes ilimitados se excluyen (igual que revenue_share).
"""
from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone

from core.models import (
    Attendance,
    Branch,
    ConsumptionLog,
    Enrollment,
    GymClass,
    Plan,
    StudentPlan,
    TeacherPaymentRule,
)
from core.services.teacher_payments import calculate_teacher_payment

pytestmark = pytest.mark.django_db

PPP = TeacherPaymentRule.PaymentType.PER_PLAN_PRICE
ACTIVE = TeacherPaymentRule.PerPlanPriceBase.ACTIVE_ENROLLMENTS
PRESENT = TeacherPaymentRule.PerPlanPriceBase.PRESENT_ATTENDEES


@pytest.fixture
def setup(make_organization, make_user):
    org = make_organization()
    teacher = make_user('teach', organization=org, role='teacher', first_name='Ana')
    s1 = make_user('s1', organization=org, role='student')
    s2 = make_user('s2', organization=org, role='student')
    branch = Branch.objects.create(organization=org, name='Sede')
    return {'org': org, 'teacher': teacher, 's1': s1, 's2': s2, 'branch': branch}


def _completed_class(org, branch, teacher):
    start = timezone.now() - timedelta(hours=2)
    return GymClass.objects.create(
        organization=org, branch=branch, teacher=teacher, name='Clase',
        start_datetime=start, end_datetime=start + timedelta(hours=1),
        status=GymClass.Status.COMPLETED,
    )


def _give_plan(org, user, total, price, unlimited=False):
    today = timezone.localdate()
    plan = Plan.objects.create(
        organization=org, name=f'Plan-{user.username}-{total}', plan_type='pack',
        total_classes=total, unlimited_classes=unlimited, duration_days=30, price=price,
    )
    return StudentPlan.objects.create(
        user=user, plan=plan, start_date=today, end_date=today + timedelta(days=30),
        organization_id=plan.organization_id,
        total_classes=total, unlimited_classes=unlimited, classes_used=0, final_price=price,
    )


def _enroll(gym_class, student, student_plan=None, present=False):
    Enrollment.objects.create(gym_class=gym_class, student=student, status='active')
    if student_plan:
        ConsumptionLog.objects.create(user=student, student_plan=student_plan, class_instance=gym_class)
    if present:
        Attendance.objects.create(gym_class=gym_class, student=student, status=Attendance.Status.PRESENT)


def _rule(org, teacher, base, amount=20):
    rule = TeacherPaymentRule.objects.create(
        organization=org, payment_type=PPP, amount=amount, per_plan_price_base=base, is_active=True,
    )
    rule.teachers.add(teacher)
    return rule


def test_active_enrollments_sums_per_class_value(setup):
    org, branch, teacher = setup['org'], setup['branch'], setup['teacher']
    gym_class = _completed_class(org, branch, teacher)
    _enroll(gym_class, setup['s1'], _give_plan(org, setup['s1'], 4, 15000))   # 15000/4 = 3750
    _enroll(gym_class, setup['s2'], _give_plan(org, setup['s2'], 24, 4000))   # 4000/24 = 166.67
    _rule(org, teacher, ACTIVE, amount=20)

    record, created = calculate_teacher_payment(gym_class)
    assert created is True
    assert record.total_students == 2          # ambos inscritos
    # (3750 + 166.6667) * 0.20 = 783.33
    assert record.total_amount == 783.33


def test_single_plan_matches_spec_example(setup):
    org, branch, teacher = setup['org'], setup['branch'], setup['teacher']
    gym_class = _completed_class(org, branch, teacher)
    _enroll(gym_class, setup['s1'], _give_plan(org, setup['s1'], 4, 15000))
    _rule(org, teacher, ACTIVE, amount=20)

    record, _ = calculate_teacher_payment(gym_class)
    assert record.total_amount == 750.0        # 3750 * 0.20


def test_present_attendees_excludes_absent(setup):
    org, branch, teacher = setup['org'], setup['branch'], setup['teacher']
    gym_class = _completed_class(org, branch, teacher)
    _enroll(gym_class, setup['s1'], _give_plan(org, setup['s1'], 4, 15000), present=True)   # presente
    _enroll(gym_class, setup['s2'], _give_plan(org, setup['s2'], 24, 4000), present=False)  # ausente
    _rule(org, teacher, PRESENT, amount=20)

    record, _ = calculate_teacher_payment(gym_class)
    assert record.total_students == 1          # solo el presente
    assert record.total_amount == 750.0        # 3750 * 0.20 (el ausente no aporta)


def test_unlimited_plan_excluded_from_base(setup):
    org, branch, teacher = setup['org'], setup['branch'], setup['teacher']
    gym_class = _completed_class(org, branch, teacher)
    _enroll(gym_class, setup['s1'], _give_plan(org, setup['s1'], 4, 15000))                 # limitado
    _enroll(gym_class, setup['s2'], _give_plan(org, setup['s2'], 0, 60000, unlimited=True))  # ilimitado
    _rule(org, teacher, ACTIVE, amount=20)

    record, _ = calculate_teacher_payment(gym_class)
    assert record.total_students == 2          # ambos inscritos
    assert record.total_amount == 750.0        # solo el limitado aporta: 3750 * 0.20


def test_amount_out_of_range_is_invalid(setup):
    org, teacher = setup['org'], setup['teacher']
    rule = TeacherPaymentRule(
        organization=org, payment_type=PPP, amount=150, per_plan_price_base=ACTIVE,
    )
    with pytest.raises(DjangoValidationError) as exc:
        rule.full_clean()
    assert 'amount' in exc.value.message_dict


def test_calculation_base_rejected_for_per_plan_price(setup):
    org, teacher = setup['org'], setup['teacher']
    rule = TeacherPaymentRule(
        organization=org, payment_type=PPP, amount=20, per_plan_price_base=ACTIVE,
        calculation_base=TeacherPaymentRule.CalculationBase.ATTENDANCE,
    )
    with pytest.raises(DjangoValidationError) as exc:
        rule.full_clean()
    assert 'calculation_base' in exc.value.message_dict
