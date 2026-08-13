"""RUT en el API de usuarios (CustomUserSerializer vía UserViewSet).

Corte 'por presencia' aprobado en PASO 0:
- create (POST): RUT opcional; si viene, se guarda canónico.
- update (PATCH): si el rut viene en el payload se valida/normaliza; si NO viene,
  el rut existente queda intacto (así el toggle de is_active y otros PATCH
  parciales de sistema no se rompen sobre usuarios con rut NULL).
- No se puede blanquear el rut al editar ('' o null => 400).
- Unicidad POR organización (mismo rut en dos orgs OK; duplicado en la misma 400).
"""
import pytest
from django.contrib.auth import get_user_model

User = get_user_model()
pytestmark = pytest.mark.django_db

PASSWORD = 'Passw0rd2026'
RUT = '12345678-5'
RUT_2 = '20347878-K'


@pytest.fixture
def org_a(make_organization):
    return make_organization('A')


@pytest.fixture
def org_b(make_organization):
    return make_organization('B')


@pytest.fixture
def admin_a(make_user, org_a):
    return make_user('admin_a', organization=org_a, role='gym_admin', email='admin@a.local')


@pytest.fixture
def admin_b(make_user, org_b):
    return make_user('admin_b', organization=org_b, role='gym_admin', email='admin@b.local')


# --- create -----------------------------------------------------------------

def test_create_without_rut_is_allowed(api_client, admin_a):
    api_client.force_authenticate(admin_a)
    resp = api_client.post(
        '/api/users/',
        {'email': 'nuevo@a.local', 'role': 'student', 'password': PASSWORD},
        format='json',
    )
    assert resp.status_code == 201, resp.data
    assert resp.data['rut'] is None
    assert User.objects.get(email='nuevo@a.local').rut is None


def test_create_with_valid_rut_stores_canonical(api_client, admin_a):
    api_client.force_authenticate(admin_a)
    resp = api_client.post(
        '/api/users/',
        {'email': 'nuevo@a.local', 'role': 'student', 'password': PASSWORD,
         'rut': '12.345.678-5'},
        format='json',
    )
    assert resp.status_code == 201, resp.data
    assert resp.data['rut'] == RUT
    assert User.objects.get(email='nuevo@a.local').rut == RUT


def test_create_normalizes_lowercase_k_and_dots(api_client, admin_a):
    api_client.force_authenticate(admin_a)
    resp = api_client.post(
        '/api/users/',
        {'email': 'k@a.local', 'role': 'student', 'password': PASSWORD,
         'rut': '20.347.878-k'},
        format='json',
    )
    assert resp.status_code == 201, resp.data
    assert resp.data['rut'] == '20347878-K'


def test_create_with_invalid_dv_returns_400(api_client, admin_a):
    api_client.force_authenticate(admin_a)
    resp = api_client.post(
        '/api/users/',
        {'email': 'bad@a.local', 'role': 'student', 'password': PASSWORD,
         'rut': '12345678-9'},
        format='json',
    )
    assert resp.status_code == 400
    assert 'rut' in resp.data


def test_create_dup_rut_same_org_returns_400(api_client, admin_a):
    api_client.force_authenticate(admin_a)
    api_client.post(
        '/api/users/',
        {'email': 'one@a.local', 'role': 'student', 'password': PASSWORD, 'rut': RUT},
        format='json',
    )
    resp = api_client.post(
        '/api/users/',
        {'email': 'two@a.local', 'role': 'student', 'password': PASSWORD, 'rut': '12.345.678-5'},
        format='json',
    )
    assert resp.status_code == 400
    assert 'rut' in resp.data


def test_same_rut_in_two_orgs_is_allowed(api_client, admin_a, admin_b):
    api_client.force_authenticate(admin_a)
    r_a = api_client.post(
        '/api/users/',
        {'email': 'x@a.local', 'role': 'student', 'password': PASSWORD, 'rut': RUT},
        format='json',
    )
    assert r_a.status_code == 201, r_a.data

    api_client.force_authenticate(admin_b)
    r_b = api_client.post(
        '/api/users/',
        {'email': 'x@b.local', 'role': 'student', 'password': PASSWORD, 'rut': RUT},
        format='json',
    )
    assert r_b.status_code == 201, r_b.data


def test_rut_is_exposed_on_retrieve(api_client, admin_a, make_user, org_a):
    student = make_user('stu', organization=org_a, role='student', email='stu@a.local', rut=RUT)
    api_client.force_authenticate(admin_a)
    resp = api_client.get(f'/api/users/{student.id}/')
    assert resp.status_code == 200
    assert resp.data['rut'] == RUT


# --- update (corte por presencia) -------------------------------------------

def test_edit_form_updates_rut(api_client, admin_a, make_user, org_a):
    student = make_user('stu', organization=org_a, role='student', email='stu@a.local', rut=RUT)
    api_client.force_authenticate(admin_a)
    resp = api_client.patch(
        f'/api/users/{student.id}/',
        {'rut': '20.347.878-K'},
        format='json',
    )
    assert resp.status_code == 200, resp.data
    student.refresh_from_db()
    assert student.rut == '20347878-K'


def test_edit_form_with_invalid_rut_returns_400(api_client, admin_a, make_user, org_a):
    student = make_user('stu', organization=org_a, role='student', email='stu@a.local', rut=RUT)
    api_client.force_authenticate(admin_a)
    resp = api_client.patch(
        f'/api/users/{student.id}/',
        {'rut': '12345678-9'},
        format='json',
    )
    assert resp.status_code == 400
    assert 'rut' in resp.data


def test_cannot_blank_rut_on_edit(api_client, admin_a, make_user, org_a):
    student = make_user('stu', organization=org_a, role='student', email='stu@a.local', rut=RUT)
    api_client.force_authenticate(admin_a)
    for blank in ('', None):
        resp = api_client.patch(
            f'/api/users/{student.id}/',
            {'rut': blank},
            format='json',
        )
        assert resp.status_code == 400, (blank, resp.data)
    student.refresh_from_db()
    assert student.rut == RUT


def test_partial_patch_without_rut_leaves_null_rut_untouched(api_client, admin_a, make_user, org_a):
    """EL CORTE: toggle de is_active sobre un usuario con rut NULL no debe fallar
    ni exigir RUT (el rut no viene en el payload => intacto)."""
    student = make_user('stu', organization=org_a, role='student', email='stu@a.local')  # rut NULL
    assert student.rut is None
    api_client.force_authenticate(admin_a)
    resp = api_client.patch(
        f'/api/users/{student.id}/',
        {'is_active': False},
        format='json',
    )
    assert resp.status_code == 200, resp.data
    student.refresh_from_db()
    assert student.rut is None
    assert student.is_active is False


def test_partial_patch_without_rut_keeps_existing_rut(api_client, admin_a, make_user, org_a):
    student = make_user('stu', organization=org_a, role='student', email='stu@a.local', rut=RUT)
    api_client.force_authenticate(admin_a)
    resp = api_client.patch(
        f'/api/users/{student.id}/',
        {'is_active': False},
        format='json',
    )
    assert resp.status_code == 200, resp.data
    student.refresh_from_db()
    assert student.rut == RUT
