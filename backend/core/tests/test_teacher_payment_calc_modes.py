"""Cobertura de los modos de cálculo de pago a profesor (gap previo).

Cubre, con montos exactos:
- FIJO: monto plano independiente del número de alumnos.
- per_plan_price PRESENT: % del precio-por-clase de los alumnos PRESENTES.
- per_plan_price ACTIVE: % de los INSCRITOS activos (cobra aunque falten).
- plan ILIMITADO no aporta ($0).
- cancelación in-deadline (enrollment cancelado + ConsumptionLog borrado) no aporta.
- matching de regla por disciplina (_match_rule_for_class).
- agregación de período (build_teacher_payment_summary).
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from core.models import (
    Attendance,
    Branch,
    ConsumptionLog,
    Discipline,
    Enrollment,
    GymClass,
    Plan,
    StudentPlan,
    TeacherPaymentRule,
)
from core.services.teacher_payments import build_teacher_payment_summary, calculate_teacher_payment

pytestmark = pytest.mark.django_db

PPP = TeacherPaymentRule.PaymentType.PER_PLAN_PRICE
FIXED = TeacherPaymentRule.PaymentType.FIXED_PER_CLASS
PRESENT = TeacherPaymentRule.PerPlanPriceBase.PRESENT_ATTENDEES
ACTIVE = TeacherPaymentRule.PerPlanPriceBase.ACTIVE_ENROLLMENTS


@pytest.fixture
def setup(make_organization, make_user):
    org = make_organization()
    teacher = make_user('teach', organization=org, role='teacher', first_name='Ana')
    branch = Branch.objects.create(organization=org, name='Sede')
    students = [make_user(f's{i}', organization=org, role='student') for i in range(10)]
    return {'org': org, 'teacher': teacher, 'branch': branch, 'students': students}


def _completed_class(org, branch, teacher, discipline=None):
    start = timezone.now() - timedelta(hours=2)
    return GymClass.objects.create(
        organization=org, branch=branch, teacher=teacher, discipline=discipline,
        name='Clase', start_datetime=start, end_datetime=start + timedelta(hours=1),
        status=GymClass.Status.COMPLETED,
    )


def _give_plan(org, user, total, price, unlimited=False):
    today = timezone.localdate()
    plan = Plan.objects.create(
        organization=org, name=f'Plan-{user.username}-{total}-{price}', plan_type='pack',
        total_classes=total, unlimited_classes=unlimited, duration_days=30, price=price,
    )
    return StudentPlan.objects.create(
        user=user, plan=plan, start_date=today, end_date=today + timedelta(days=30),
        organization_id=plan.organization_id,
        total_classes=total, unlimited_classes=unlimited, classes_used=0, final_price=price,
    )


def _enroll(gym_class, student, student_plan=None, present=False, status='active'):
    enr = Enrollment.objects.create(gym_class=gym_class, student=student, status=status)
    if student_plan is not None:
        ConsumptionLog.objects.create(user=student, student_plan=student_plan, class_instance=gym_class)
    if present:
        Attendance.objects.create(gym_class=gym_class, student=student, status=Attendance.Status.PRESENT)
    return enr


def _rule_ppp(org, teacher, base, amount, discipline=None):
    rule = TeacherPaymentRule.objects.create(
        organization=org, payment_type=PPP, amount=amount, per_plan_price_base=base,
        discipline=discipline, is_active=True,
    )
    rule.teachers.add(teacher)
    return rule


def _rule_fixed(org, teacher, amount, discipline=None):
    rule = TeacherPaymentRule.objects.create(
        organization=org, payment_type=FIXED, amount=amount, discipline=discipline, is_active=True,
    )
    rule.teachers.add(teacher)
    return rule


def test_fixed_pays_flat_regardless_of_students(setup):
    org, branch, teacher, students = setup['org'], setup['branch'], setup['teacher'], setup['students']
    gym_class = _completed_class(org, branch, teacher)
    for s in students[:5]:  # 5 presentes
        _enroll(gym_class, s, present=True)
    _rule_fixed(org, teacher, 5000)

    record, _ = calculate_teacher_payment(gym_class)
    assert record.total_amount == 5000  # plano, no depende de los 5 alumnos


@pytest.mark.parametrize('pct,expected', [(10, 1500.0), (20, 3000.0), (40, 6000.0), (60, 9000.0)])
def test_present_percentage(setup, pct, expected):
    org, branch, teacher, students = setup['org'], setup['branch'], setup['teacher'], setup['students']
    gym_class = _completed_class(org, branch, teacher)
    _enroll(gym_class, students[0], _give_plan(org, students[0], 4, 40000), present=True)  # 10000/clase
    _enroll(gym_class, students[1], _give_plan(org, students[1], 8, 40000), present=True)  # 5000/clase
    _rule_ppp(org, teacher, PRESENT, pct)

    record, _ = calculate_teacher_payment(gym_class)
    assert record.total_amount == expected  # 15000 * pct/100


def test_present_absent_not_paid(setup):
    org, branch, teacher, students = setup['org'], setup['branch'], setup['teacher'], setup['students']
    gym_class = _completed_class(org, branch, teacher)
    _enroll(gym_class, students[0], _give_plan(org, students[0], 4, 40000), present=True)   # 10000
    _enroll(gym_class, students[1], _give_plan(org, students[1], 8, 40000), present=False)  # ausente
    _rule_ppp(org, teacher, PRESENT, 40)

    record, _ = calculate_teacher_payment(gym_class)
    assert record.total_amount == 4000  # solo el presente: 10000 * 0.4


def test_unlimited_plan_contributes_zero(setup):
    org, branch, teacher, students = setup['org'], setup['branch'], setup['teacher'], setup['students']
    gym_class = _completed_class(org, branch, teacher)
    _enroll(gym_class, students[0], _give_plan(org, students[0], 4, 40000), present=True)          # 10000
    _enroll(gym_class, students[2], _give_plan(org, students[2], 0, 99000, unlimited=True), present=True)  # 0
    _rule_ppp(org, teacher, PRESENT, 40)

    record, _ = calculate_teacher_payment(gym_class)
    assert record.total_amount == 4000  # ilimitado no aporta


def test_active_pays_even_if_absent(setup):
    org, branch, teacher, students = setup['org'], setup['branch'], setup['teacher'], setup['students']
    gym_class = _completed_class(org, branch, teacher)
    _enroll(gym_class, students[0], _give_plan(org, students[0], 4, 40000), present=True)   # 10000
    _enroll(gym_class, students[1], _give_plan(org, students[1], 8, 40000), present=False)  # inscrito, ausente
    _rule_ppp(org, teacher, ACTIVE, 60)

    record, _ = calculate_teacher_payment(gym_class)
    assert record.total_amount == 9000  # (10000+5000) * 0.6, ausente igual aporta


def test_active_excludes_cancelled_in_deadline(setup):
    org, branch, teacher, students = setup['org'], setup['branch'], setup['teacher'], setup['students']
    gym_class = _completed_class(org, branch, teacher)
    _enroll(gym_class, students[0], _give_plan(org, students[0], 4, 40000), present=True)  # 10000, activo
    # students[1] cancela en deadline: enrollment cancelado + ConsumptionLog borrado.
    sp = _give_plan(org, students[1], 8, 40000)
    _enroll(gym_class, students[1], sp, status='cancelled')
    ConsumptionLog.objects.filter(class_instance=gym_class, user=students[1]).delete()
    _rule_ppp(org, teacher, ACTIVE, 60)

    record, _ = calculate_teacher_payment(gym_class)
    assert record.total_amount == 6000  # solo el activo: 10000 * 0.6


def test_matching_by_discipline(setup):
    org, branch, teacher, students = setup['org'], setup['branch'], setup['teacher'], setup['students']
    d1 = Discipline.objects.create(organization=org, name='Funcional')
    d2 = Discipline.objects.create(organization=org, name='Yoga')
    _rule_fixed(org, teacher, 5000, discipline=d1)
    _rule_fixed(org, teacher, 7000, discipline=d2)

    c1 = _completed_class(org, branch, teacher, discipline=d1)
    c2 = _completed_class(org, branch, teacher, discipline=d2)
    _enroll(c1, students[0], present=True)
    _enroll(c2, students[1], present=True)

    r1, _ = calculate_teacher_payment(c1)
    r2, _ = calculate_teacher_payment(c2)
    assert r1.total_amount == 5000  # regla de d1
    assert r2.total_amount == 7000  # regla de d2


def test_period_aggregates_all_classes(setup):
    org, branch, teacher, students = setup['org'], setup['branch'], setup['teacher'], setup['students']
    _rule_fixed(org, teacher, 5000)
    now = timezone.now()
    for _ in range(3):
        c = _completed_class(org, branch, teacher)
        _enroll(c, students[0], present=True)
        calculate_teacher_payment(c)

    first = now.replace(day=1).date()
    last = (now.replace(day=28) + timedelta(days=4)).date()
    summary = build_teacher_payment_summary(org.id, first, last, teacher_id=teacher.id)
    row = next(r for r in summary['rows'] if r['teacher_id'] == teacher.id)
    assert row['classes_count'] == 3
    assert row['per_class_total'] == 15000  # 3 clases * 5000
    assert row['total'] == 15000
