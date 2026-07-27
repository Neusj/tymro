"""Regresión de multitenancy: crear inscripciones exige autorización SIEMPRE.

`EnrollmentViewSet.perform_create` tenía un atajo al principio —si el `status` pedido
no era 'active', hacía `serializer.save()` y volvía— que ocurría ANTES de todas las
ramas por rol y de su `PermissionDenied`. El único filtro que quedaba era
`EnrollmentSerializer.validate`, cuyo check de organización estaba condicionado a
`roles.is_org_admin(user)`, así que monitor y teacher no lo activaban: un
`POST /api/enrollments/ {"status": "cancelled"}` con una clase y un alumno de OTRA
organización creaba la fila en el tenant ajeno (verificado: HTTP 201).
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from core.models import Branch, Enrollment, GymClass

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
def victim(make_organization, make_user):
    """Una organización ajena, completa y con una clase futura."""
    org = make_organization(name='Org Victima')
    teacher = make_user('profeB', organization=org, role='teacher')
    student = make_user('aluB', organization=org, role='student', email='alub@victima.cl')
    branch = Branch.objects.create(organization=org, name='Sede B')
    start = timezone.now() + timedelta(days=1)
    gym_class = GymClass.objects.create(
        organization=org, branch=branch, teacher=teacher, name='Clase B',
        start_datetime=start, end_datetime=start + timedelta(hours=1), capacity=10,
    )
    return {'org': org, 'teacher': teacher, 'student': student, 'gym_class': gym_class}


@pytest.mark.parametrize('status_value', ['cancelled', 'active'])
@pytest.mark.parametrize('intruder_role', ['monitor', 'teacher', 'gym_admin', 'manager', 'student'])
def test_cross_org_enrollment_create_is_rejected(
    api_client, victim, make_organization, make_user, intruder_role, status_value,
):
    """Ningún rol de otra organización puede crear una inscripción en la org víctima,
    con cualquier `status`. El atajo por `status != 'active'` era la vía abierta."""
    attacker_org = make_organization(name='Org Atacante')
    make_user('intruso', organization=attacker_org, role=intruder_role)
    _login(api_client, 'intruso')

    resp = api_client.post('/api/enrollments/', {
        'gym_class': victim['gym_class'].id,
        'student': victim['student'].id,
        'status': status_value,
    }, format='json')

    assert resp.status_code in (400, 403, 404), resp.content
    assert not Enrollment.objects.filter(gym_class=victim['gym_class']).exists(), (
        f'{intruder_role} con status={status_value} escribió en otra organización'
    )


def test_monitor_cannot_create_enrollment_even_in_own_org(api_client, victim, make_user):
    """`monitor` no está en la matriz de escritura de inscripciones; el atajo por
    status tampoco puede ser su puerta de entrada dentro de su propia organización."""
    make_user('monitor1', organization=victim['org'], role='monitor')
    _login(api_client, 'monitor1')

    resp = api_client.post('/api/enrollments/', {
        'gym_class': victim['gym_class'].id,
        'student': victim['student'].id,
        'status': 'cancelled',
    }, format='json')

    assert resp.status_code in (400, 403), resp.content
    assert not Enrollment.objects.filter(gym_class=victim['gym_class']).exists()


def test_teacher_cannot_create_enrollment_in_someone_elses_class(api_client, victim, make_user):
    """Un profesor de la MISMA org que no dicta la clase tampoco entra por el atajo."""
    make_user('otroprofe', organization=victim['org'], role='teacher')
    _login(api_client, 'otroprofe')

    resp = api_client.post('/api/enrollments/', {
        'gym_class': victim['gym_class'].id,
        'student': victim['student'].id,
        'status': 'cancelled',
    }, format='json')

    assert resp.status_code in (400, 403), resp.content
    assert not Enrollment.objects.filter(gym_class=victim['gym_class']).exists()


# --- Los caminos legítimos deben seguir funcionando -----------------------------


def test_gym_admin_can_still_create_cancelled_enrollment_in_own_org(api_client, victim, make_user):
    make_user('adminB', organization=victim['org'], role='gym_admin')
    _login(api_client, 'adminB')

    resp = api_client.post('/api/enrollments/', {
        'gym_class': victim['gym_class'].id,
        'student': victim['student'].id,
        'status': 'cancelled',
    }, format='json')

    assert resp.status_code == 201, resp.content


def test_class_teacher_can_still_create_cancelled_enrollment(api_client, victim):
    _login(api_client, 'profeB')

    resp = api_client.post('/api/enrollments/', {
        'gym_class': victim['gym_class'].id,
        'student': victim['student'].id,
        'status': 'cancelled',
    }, format='json')

    assert resp.status_code == 201, resp.content
