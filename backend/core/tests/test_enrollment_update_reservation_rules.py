"""Reactivar una inscripción por PATCH debe pasar por las reglas de reserva.

`EnrollmentViewSet.perform_update` hacía `serializer.save()` a secas. El serializer
valida organización, cupo, solape y duplicados, pero NO plan activo, NI matrícula
impaga, NI la exclusividad de sucursal, y no crea `ConsumptionLog`. Combinado con la
creación en `status='cancelled'`, daba un bypass de dos llamadas:

    POST /api/enrollments/ {"status": "cancelled"}  -> 201
    PATCH /api/enrollments/{id}/ {"status": "active"} -> 200, sin consumir el plan

Eso anula la exclusividad por sucursal y además regala clases sin descontarlas.
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from core.models import Branch, ConsumptionLog, Enrollment, GymClass, Plan, StudentPlan

pytestmark = pytest.mark.django_db

PASSWORD = 'Passw0rd2026'


def _login(api_client, username):
    from django.contrib.auth import get_user_model
    user = get_user_model().objects.get(username=username)
    host = {'HTTP_HOST': f'{user.organization.subdomain}.localhost'} if user.organization_id else {}
    token = api_client.post(
        '/api/login/', {'email': user.email, 'password': PASSWORD}, format='json', **host
    ).json()['token']
    api_client.credentials(HTTP_AUTHORIZATION=f'Token {token}')


@pytest.fixture
def setup(make_organization, make_user):
    org = make_organization()
    make_user('admin', organization=org, role='gym_admin')
    teacher = make_user('teach', organization=org, role='teacher')
    student = make_user('alu', organization=org, role='student', email='alu@gym.cl')
    centro = Branch.objects.create(organization=org, name='Sede Centro')
    barrio = Branch.objects.create(organization=org, name='Sede Barrio')
    return {
        'org': org, 'teacher': teacher, 'student': student,
        'centro': centro, 'barrio': barrio,
    }


def _class(setup, branch, days=1):
    start = timezone.now() + timedelta(days=days)
    return GymClass.objects.create(
        organization=setup['org'], branch=branch, teacher=setup['teacher'],
        name=f'Clase {branch.name}', start_datetime=start,
        end_datetime=start + timedelta(hours=1), capacity=10,
        status=GymClass.Status.SCHEDULED,
    )


def _student_plan(setup, branch=None):
    today = timezone.localdate()
    plan = Plan.objects.create(
        organization=setup['org'], branch=branch, name='Pack 10', plan_type='pack',
        total_classes=10, duration_days=30, price=30000,
    )
    return StudentPlan.objects.create(
        user=setup['student'], plan=plan, branch=branch,
        start_date=today - timedelta(days=1), end_date=today + timedelta(days=30),
        total_classes=10, classes_used=0, final_price=30000,
    )


def _cancelled_enrollment(api_client, setup, gym_class):
    resp = api_client.post('/api/enrollments/', {
        'gym_class': gym_class.id, 'student': setup['student'].id, 'status': 'cancelled',
    }, format='json')
    assert resp.status_code == 201, resp.content
    return resp.json()['id']


def test_patch_to_active_respects_exclusive_plan_branch(api_client, setup):
    """El bypass de dos llamadas no puede saltarse la exclusividad de sucursal."""
    _student_plan(setup, branch=setup['centro'])
    gym_class = _class(setup, setup['barrio'])
    _login(api_client, 'admin')
    enrollment_id = _cancelled_enrollment(api_client, setup, gym_class)

    resp = api_client.patch(
        f'/api/enrollments/{enrollment_id}/', {'status': 'active'}, format='json',
    )

    assert resp.status_code == 400, resp.content
    assert Enrollment.objects.get(id=enrollment_id).status == 'cancelled'


def test_patch_to_active_consumes_the_plan(api_client, setup):
    """Reactivar tiene que descontar la clase, igual que reservar."""
    student_plan = _student_plan(setup, branch=None)
    gym_class = _class(setup, setup['centro'])
    _login(api_client, 'admin')
    enrollment_id = _cancelled_enrollment(api_client, setup, gym_class)

    resp = api_client.patch(
        f'/api/enrollments/{enrollment_id}/', {'status': 'active'}, format='json',
    )

    assert resp.status_code == 200, resp.content
    student_plan.refresh_from_db()
    assert student_plan.classes_used == 1, 'reactivar debe consumir una clase del plan'
    assert ConsumptionLog.objects.filter(
        class_instance=gym_class, user=setup['student'],
    ).exists()


def test_patch_to_active_requires_an_active_plan(api_client, setup):
    """Sin plan vigente no se puede reactivar: es una reserva como cualquier otra."""
    gym_class = _class(setup, setup['centro'])
    _login(api_client, 'admin')
    enrollment_id = _cancelled_enrollment(api_client, setup, gym_class)

    resp = api_client.patch(
        f'/api/enrollments/{enrollment_id}/', {'status': 'active'}, format='json',
    )

    assert resp.status_code == 400, resp.content
    assert Enrollment.objects.get(id=enrollment_id).status == 'cancelled'


def test_manager_cannot_bypass_plan_rules_either(api_client, setup, make_user):
    """`manager` llega a este endpoint por `roles.is_org_admin` aunque tenga prohibido
    hasta leer planes; no puede ser la vía para regalar clases."""
    _student_plan(setup, branch=setup['centro'])
    gym_class = _class(setup, setup['barrio'])
    make_user('gerente', organization=setup['org'], role='manager')
    _login(api_client, 'gerente')
    enrollment_id = _cancelled_enrollment(api_client, setup, gym_class)

    resp = api_client.patch(
        f'/api/enrollments/{enrollment_id}/', {'status': 'active'}, format='json',
    )

    assert resp.status_code == 400, resp.content
    assert Enrollment.objects.get(id=enrollment_id).status == 'cancelled'


def test_patch_that_does_not_touch_status_still_works(api_client, setup):
    """Regresión: editar una inscripción sin cambiar el estado no debe romperse."""
    _student_plan(setup, branch=None)
    gym_class = _class(setup, setup['centro'])
    _login(api_client, 'admin')
    resp = api_client.post('/api/enrollments/', {
        'gym_class': gym_class.id, 'student': setup['student'].id,
    }, format='json')
    assert resp.status_code == 201, resp.content
    enrollment_id = resp.json()['id']

    resp = api_client.patch(
        f'/api/enrollments/{enrollment_id}/', {'status': 'active'}, format='json',
    )

    assert resp.status_code == 200, resp.content


def test_patch_to_cancelled_refunds_the_consumption(api_client, setup):
    """El reverso: pasar a 'cancelled' por PATCH debe devolver el saldo, como hace la
    acción `cancel`. Si no, el alumno queda cobrado y sin inscripción."""
    student_plan = _student_plan(setup, branch=None)
    gym_class = _class(setup, setup['centro'])
    _login(api_client, 'admin')
    resp = api_client.post('/api/enrollments/', {
        'gym_class': gym_class.id, 'student': setup['student'].id,
    }, format='json')
    enrollment_id = resp.json()['id']
    student_plan.refresh_from_db()
    assert student_plan.classes_used == 1

    resp = api_client.patch(
        f'/api/enrollments/{enrollment_id}/', {'status': 'cancelled'}, format='json',
    )

    assert resp.status_code == 200, resp.content
    student_plan.refresh_from_db()
    assert student_plan.classes_used == 0, 'cancelar por PATCH debe devolver el saldo'
