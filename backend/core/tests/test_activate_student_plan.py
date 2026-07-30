from datetime import date, timedelta

import pytest

from core.models import Plan, StudentPlan
from core.services.plans import activate_student_plan


@pytest.fixture
def plan(db, make_organization):
    org = make_organization()
    return org, Plan.objects.create(organization=org, name='Mensual', plan_type='monthly',
                                    total_classes=12, unlimited_classes=False, duration_days=30,
                                    price=30000.0, discount_percentage=0)


def test_activate_creates_active_plan_and_derives_fields(plan, make_user):
    org, p = plan
    student = make_user('stu', organization=org, role='student')
    sp = activate_student_plan(student=student, plan=p, start_date=date(2026, 7, 1))
    assert sp.is_active is True
    assert sp.total_classes == 12
    assert sp.unlimited_classes is False
    assert sp.end_date == date(2026, 7, 1) + timedelta(days=29)   # duration-1
    assert sp.final_price == 30000.0


def test_activate_applies_discount(plan, make_user):
    org, p = plan
    student = make_user('stu2', organization=org, role='student')
    sp = activate_student_plan(student=student, plan=p, start_date=date(2026, 7, 1),
                               discount_percentage=50)
    assert sp.final_price == 15000.0
    assert sp.discount_percentage == 50


def test_activate_keeps_the_previous_membership_active(plan, make_user):
    """Invierte el comportamiento anterior. `activate_student_plan` desactivaba las
    membresías vigentes del alumno antes de crear la nueva, y eso era un bug: un alumno
    puede tener varios planes contratados a la vez (dos disciplinas), así que contratar
    uno nuevo no puede apagarle los que está usando."""
    org, p = plan
    student = make_user('stu3', organization=org, role='student')
    first = activate_student_plan(student=student, plan=p, start_date=date(2026, 6, 1))
    second = activate_student_plan(student=student, plan=p, start_date=date(2026, 7, 1))
    first.refresh_from_db()
    assert first.is_active is True
    assert second.is_active is True
    assert StudentPlan.objects.filter(user=student, is_active=True).count() == 2
