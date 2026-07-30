"""`StudentPlan.objects.valid_on(on_date)` — mitad temporal del predicado único (7.2).

El bloque `is_active=True + start_date__lte + end_date__gte` estaba escrito tres veces en
el backend (reservas, roster, "mis membresías") y las tres copias divergían en el origen
de la organización y en el criterio de desempate. Acá vive una sola vez, como queryset,
para que los lectores lo encadenen sobre su propio scope.

`on_date` es OBLIGATORIO a propósito: el default implícito a "hoy" es lo que permite que
una reserva para una clase futura se valide contra la vigencia de hoy. Cerrar eso es #9;
lo que hace este diseño es obligar al llamador a declarar la fecha.
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from core.models import Plan, StudentPlan

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()


def _plan(org, total_classes=10, unlimited=False):
    return Plan.objects.create(
        organization=org, name=f'Plan {total_classes}', plan_type='pack',
        total_classes=total_classes, unlimited_classes=unlimited,
        duration_days=30, price=30000,
    )


def _membership(student, plan, *, start_offset=-1, end_offset=30, is_active=True):
    return StudentPlan.objects.create(
        user=student, plan=plan, organization_id=plan.organization_id,
        start_date=TODAY + timedelta(days=start_offset),
        end_date=TODAY + timedelta(days=end_offset),
        total_classes=plan.total_classes, unlimited_classes=plan.unlimited_classes,
        classes_used=0, final_price=30000, is_active=is_active,
    )


@pytest.fixture
def student_with_plan(make_organization, make_user):
    org = make_organization()
    student = make_user('stu-validon', organization=org, role='student')
    return org, student, _plan(org)


def test_valid_on_includes_membership_inside_its_window(student_with_plan):
    _, student, plan = student_with_plan
    membership = _membership(student, plan)
    assert list(StudentPlan.objects.valid_on(TODAY)) == [membership]


def test_valid_on_excludes_membership_that_starts_tomorrow(student_with_plan):
    """El borde que NINGÚN test del repo cubría: `start_date__lte`.

    El importador deriva `is_active` mirando solo `end_date >= hoy`, así que una membresía
    con fecha de inicio futura se guarda con el flag en True. Si el predicado no chequeara
    `start_date`, esa membresía habilitaría reservas antes de empezar.
    """
    _, student, plan = student_with_plan
    _membership(student, plan, start_offset=1, end_offset=30)
    assert list(StudentPlan.objects.valid_on(TODAY)) == []


def test_valid_on_includes_membership_on_its_exact_start_date(student_with_plan):
    _, student, plan = student_with_plan
    membership = _membership(student, plan, start_offset=0)
    assert list(StudentPlan.objects.valid_on(TODAY)) == [membership]


def test_valid_on_includes_membership_on_its_exact_end_date(student_with_plan):
    """`end_date` es inclusivo: el último día el plan todavía sirve."""
    _, student, plan = student_with_plan
    membership = _membership(student, plan, start_offset=-30, end_offset=0)
    assert list(StudentPlan.objects.valid_on(TODAY)) == [membership]


def test_valid_on_excludes_membership_that_ended_yesterday(student_with_plan):
    _, student, plan = student_with_plan
    _membership(student, plan, start_offset=-30, end_offset=-1)
    assert list(StudentPlan.objects.valid_on(TODAY)) == []


def test_valid_on_excludes_inactive_membership_inside_its_window(student_with_plan):
    _, student, plan = student_with_plan
    _membership(student, plan, is_active=False)
    assert list(StudentPlan.objects.valid_on(TODAY)) == []


def test_valid_on_evaluates_against_the_date_it_receives_not_today(student_with_plan):
    """La fecha es un parámetro, no "hoy": una membresía ya vencida seguía vigente ayer."""
    _, student, plan = student_with_plan
    membership = _membership(student, plan, start_offset=-30, end_offset=-1)
    assert list(StudentPlan.objects.valid_on(TODAY - timedelta(days=1))) == [membership]


def test_valid_on_requires_the_date_argument():
    """Sin default: el llamador tiene que declarar contra qué fecha evalúa (ver #9)."""
    with pytest.raises(TypeError):
        StudentPlan.objects.valid_on()


def test_valid_on_is_chainable_after_filter(student_with_plan, make_user):
    """Los lectores lo encadenan sobre su propio scope (usuario, organización)."""
    org, student, plan = student_with_plan
    mine = _membership(student, plan)
    other = make_user('otro-validon', organization=org, role='student')
    _membership(other, plan)
    assert list(StudentPlan.objects.filter(user=student).valid_on(TODAY)) == [mine]


def test_valid_on_is_chainable_before_filter(student_with_plan, make_user):
    org, student, plan = student_with_plan
    mine = _membership(student, plan)
    other = make_user('otro2-validon', organization=org, role='student')
    _membership(other, plan)
    assert list(StudentPlan.objects.valid_on(TODAY).filter(user=student)) == [mine]


def test_related_manager_keeps_seeing_every_membership(student_with_plan):
    """`plan.student_plans` NO puede filtrar nada.

    La guarda de borrado en cascada (`_cascade_blocker`, views.py) cuenta membresías por
    el related manager, que usa `_default_manager`. Si el manager custom hiciera override
    de `get_queryset()`, esa cuenta se volvería silenciosamente parcial y la guarda
    dejaría pasar el borrado de un plan con membresías vencidas colgando.
    """
    _, student, plan = student_with_plan
    _membership(student, plan, is_active=False, start_offset=-60, end_offset=-30)
    _membership(student, plan, start_offset=1, end_offset=40)
    assert plan.student_plans.count() == 2
    assert StudentPlan.objects.count() == 2
