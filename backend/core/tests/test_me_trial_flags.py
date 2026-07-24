"""Contrato de /api/me/: expone email_verified y has_used_trial (SOLO LECTURA).

El banner de "clase de prueba gratis" del frontend decide su visibilidad con estos
dos flags. Ambos existen en el modelo (CustomUser) pero deben viajar en la respuesta
de /me para que un alumno logueado o importado pueda evaluarlos.

Son de SOLO LECTURA: CustomUserSerializer también sirve al alta/edición de usuarios
del admin (/api/users/), así que un gym_admin NO puede marcar has_used_trial ni
email_verified a mano (sería negar la clase de prueba o saltarse la verificación
de correo). El estado real de ambos lo mueve solo el backend (verificación / reserva).
"""
import pytest
from django.contrib.auth import get_user_model

User = get_user_model()
pytestmark = pytest.mark.django_db

RUT = '12345678-5'


@pytest.fixture
def org_a(make_organization):
    return make_organization('A')


@pytest.fixture
def student(make_user, org_a):
    return make_user('stu', organization=org_a, role='student', email='stu@a.local')


@pytest.fixture
def admin_a(make_user, org_a):
    return make_user('admin_a', organization=org_a, role='gym_admin', email='admin@a.local')


def test_me_exposes_flags_verified_no_trial(api_client, student):
    student.email_verified = True
    student.has_used_trial = False
    student.save(update_fields=['email_verified', 'has_used_trial'])
    api_client.force_authenticate(student)

    resp = api_client.get('/api/me/')

    assert resp.status_code == 200, resp.data
    assert resp.data['email_verified'] is True
    assert resp.data['has_used_trial'] is False


def test_me_exposes_flags_unverified_with_trial(api_client, student):
    student.email_verified = False
    student.has_used_trial = True
    student.save(update_fields=['email_verified', 'has_used_trial'])
    api_client.force_authenticate(student)

    resp = api_client.get('/api/me/')

    assert resp.status_code == 200, resp.data
    assert resp.data['email_verified'] is False
    assert resp.data['has_used_trial'] is True


def test_admin_cannot_write_trial_flags(api_client, admin_a, make_user, org_a):
    """read_only: aunque los flags ahora viajan en el serializer compartido con
    /api/users/, un admin no puede escribirlos (defensa contra negar la prueba o
    falsear la verificación de correo)."""
    target = make_user(
        'target', organization=org_a, role='student', email='target@a.local', rut=RUT,
        email_verified=False, has_used_trial=False,
    )
    api_client.force_authenticate(admin_a)

    resp = api_client.patch(
        f'/api/users/{target.id}/',
        {'email_verified': True, 'has_used_trial': True},
        format='json',
    )

    assert resp.status_code == 200, resp.data
    target.refresh_from_db()
    assert target.email_verified is False   # ignorado (read-only)
    assert target.has_used_trial is False   # ignorado (read-only)


def test_admin_cannot_set_trial_flags_on_create(api_client, admin_a):
    """read_only también en el ALTA (POST /api/users/): los flags del payload se
    ignoran y el usuario nace con el estado real por defecto (ambos False)."""
    api_client.force_authenticate(admin_a)

    resp = api_client.post(
        '/api/users/',
        {
            'email': 'nuevo@a.local', 'role': 'student', 'password': 'Passw0rd2026',
            'rut': RUT, 'email_verified': True, 'has_used_trial': True,
        },
        format='json',
    )

    assert resp.status_code == 201, resp.data
    created = User.objects.get(email='nuevo@a.local')
    assert created.email_verified is False   # ignorado (read-only)
    assert created.has_used_trial is False   # ignorado (read-only)
