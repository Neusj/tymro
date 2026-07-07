"""Self-service: el propio usuario completa/actualiza su RUT vía PATCH /api/me/.

Decisión de producto (PASO 0): el registro público NO exige RUT; en cambio la app
alerta al usuario para que complete sus datos (responsabilidad del cliente). Este
endpoint es el que hace accionable esa alerta. Está acotado a rut/phone del PROPIO
usuario: nunca puede escalar rol, cambiar organización ni is_active.
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


def test_anonymous_cannot_patch_me(api_client):
    resp = api_client.patch('/api/me/', {'rut': RUT}, format='json')
    assert resp.status_code in (401, 403)


def test_student_sets_own_rut_normalized(api_client, student):
    assert student.rut is None
    api_client.force_authenticate(student)
    resp = api_client.patch('/api/me/', {'rut': '12.345.678-5'}, format='json')
    assert resp.status_code == 200, resp.data
    student.refresh_from_db()
    assert student.rut == RUT


def test_student_invalid_rut_returns_400(api_client, student):
    api_client.force_authenticate(student)
    resp = api_client.patch('/api/me/', {'rut': '12345678-9'}, format='json')
    assert resp.status_code == 400
    assert 'rut' in resp.data
    student.refresh_from_db()
    assert student.rut is None


def test_student_can_update_own_phone(api_client, student):
    api_client.force_authenticate(student)
    resp = api_client.patch('/api/me/', {'phone': '+56 9 9999 0000'}, format='json')
    assert resp.status_code == 200, resp.data
    student.refresh_from_db()
    assert student.phone == '+56 9 9999 0000'


def test_rut_taken_by_other_in_same_org_returns_400(api_client, student, make_user, org_a):
    make_user('otro', organization=org_a, role='student', email='otro@a.local', rut=RUT)
    api_client.force_authenticate(student)
    resp = api_client.patch('/api/me/', {'rut': RUT}, format='json')
    assert resp.status_code == 400
    assert 'rut' in resp.data


def test_me_cannot_escalate_role_or_toggle_active(api_client, student):
    api_client.force_authenticate(student)
    resp = api_client.patch(
        '/api/me/',
        {'rut': RUT, 'role': 'superadmin', 'is_active': False, 'is_active_member': False},
        format='json',
    )
    assert resp.status_code == 200, resp.data
    student.refresh_from_db()
    assert student.role == 'student'          # no escaló
    assert student.is_active is True          # no se desactivó
    assert student.rut == RUT                 # sí guardó el rut
