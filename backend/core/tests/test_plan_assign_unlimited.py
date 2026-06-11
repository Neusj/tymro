"""Regresión: al asignar un plan, la cantidad de clases y el flag de ilimitado
se DERIVAN del plan y NO son inyectables vía payload.

Garantía central de la feature "clases ilimitadas": un cliente que envíe
``total_classes`` y ``unlimited_classes`` en el body de ``/plans/assign/`` no
debe poder alterar el saldo ni saltarse el tope de clases del alumno; el
StudentPlan resultante refleja SIEMPRE los valores del Plan.
"""
import pytest

from core.models import Plan, StudentPlan

pytestmark = pytest.mark.django_db

ASSIGN_URL = '/api/plans/assign/'


def _make_plan(org, *, total_classes, unlimited_classes):
    return Plan.objects.create(
        organization=org,
        name='Plan test',
        plan_type=Plan.PlanType.MONTHLY,
        total_classes=total_classes,
        unlimited_classes=unlimited_classes,
        duration_days=30,
        price=30000,
    )


def test_assign_ignores_payload_classes_for_finite_plan(api_client, make_organization, make_user):
    """Plan finito (5 clases): aunque el payload pida total_classes=9999 y
    unlimited_classes=True, el StudentPlan queda con los valores del plan."""
    org = make_organization()
    gym_admin = make_user('admin_finite', organization=org, role='gym_admin')
    student = make_user('student_finite', organization=org, role='student')
    plan = _make_plan(org, total_classes=5, unlimited_classes=False)

    api_client.force_authenticate(gym_admin)
    response = api_client.post(
        ASSIGN_URL,
        {
            'user': student.id,
            'plan': plan.id,
            'start_date': '2026-06-11',
            'total_classes': 9999,        # intento de inyección
            'unlimited_classes': True,    # intento de inyección
        },
        format='json',
    )

    assert response.status_code == 201, response.data
    assigned = StudentPlan.objects.get(user=student, is_active=True)
    assert assigned.total_classes == 5
    assert assigned.unlimited_classes is False
    # La respuesta serializada tampoco debe reflejar el payload.
    assert response.data['total_classes'] == 5
    assert response.data['unlimited_classes'] is False


def test_assign_derives_unlimited_from_plan(api_client, make_organization, make_user):
    """Plan ilimitado: aunque el payload pida total_classes=9999 y
    unlimited_classes=False, el StudentPlan queda ilimitado con la cantidad del plan."""
    org = make_organization()
    gym_admin = make_user('admin_unlim', organization=org, role='gym_admin')
    student = make_user('student_unlim', organization=org, role='student')
    plan = _make_plan(org, total_classes=0, unlimited_classes=True)

    api_client.force_authenticate(gym_admin)
    response = api_client.post(
        ASSIGN_URL,
        {
            'user': student.id,
            'plan': plan.id,
            'start_date': '2026-06-11',
            'total_classes': 9999,        # intento de inyección
            'unlimited_classes': False,   # intento de inyección
        },
        format='json',
    )

    assert response.status_code == 201, response.data
    assigned = StudentPlan.objects.get(user=student, is_active=True)
    assert assigned.unlimited_classes is True
    assert assigned.total_classes == 0
    assert response.data['unlimited_classes'] is True
