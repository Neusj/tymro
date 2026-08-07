"""Config de ventana de materialización y poda de series recurrentes (Task 1 de rolling-window).

Solo cubre los campos `class_generation_window_days` y `class_pruning_grace_days`
en sí (existencia, default, exposición por API, escritura vía PATCH). El consumo
real de estos valores — decidir cuántos días hacia adelante se generan clases de
una serie recurrente, y cuántos días de colchón hay antes de podar una clase
terminada vacía — es una tarea aparte (no cubierta acá).

Sigue el mismo molde que `trial_validity_days`: mismo tipo de campo, mismo
permiso de escritura (solo superadmin puede editar la organización, ver
`test_organization_admin.py`).
"""
import pytest
from django.core.exceptions import ValidationError

from core.models import Organization

pytestmark = pytest.mark.django_db

ORG_URL = '/api/organizations/'


def _detail(org):
    return f'{ORG_URL}{org.id}/'


def test_field_exists_with_default_21(make_organization):
    org = make_organization()
    assert org.class_generation_window_days == 21


def test_field_is_exposed_in_organization_response(api_client, make_organization, make_user):
    org = make_organization()
    admin = make_user('admin_a', organization=org, role='gym_admin')

    api_client.force_authenticate(user=admin)
    resp = api_client.get(_detail(org))

    assert resp.status_code == 200
    assert resp.json()['class_generation_window_days'] == 21


def test_superadmin_can_update_field_via_patch(api_client, make_organization, make_user):
    org = make_organization()
    superadmin = make_user('root', organization=None, role='superadmin')

    api_client.force_authenticate(user=superadmin)
    resp = api_client.patch(
        _detail(org),
        {'class_generation_window_days': 45},
        format='json',
    )

    assert resp.status_code == 200
    assert resp.json()['class_generation_window_days'] == 45
    org.refresh_from_db()
    assert org.class_generation_window_days == 45


def test_superadmin_can_set_max_allowed_value_366(api_client, make_organization, make_user):
    org = make_organization()
    superadmin = make_user('root', organization=None, role='superadmin')

    api_client.force_authenticate(user=superadmin)
    resp = api_client.patch(
        _detail(org),
        {'class_generation_window_days': 366},
        format='json',
    )

    assert resp.status_code == 200
    org.refresh_from_db()
    assert org.class_generation_window_days == 366


def test_value_above_366_is_rejected(api_client, make_organization, make_user):
    """Cota superior evita el OverflowError de `timedelta` con valores absurdos
    (ver `materialization_window_cap` en core/services/recurrence.py): sin tope,
    DRF acepta hasta 2147483647 y la materialización de esa org rompe con 500."""
    org = make_organization()
    superadmin = make_user('root', organization=None, role='superadmin')

    api_client.force_authenticate(user=superadmin)
    resp = api_client.patch(
        _detail(org),
        {'class_generation_window_days': 5_000_000},
        format='json',
    )

    assert resp.status_code == 400
    org.refresh_from_db()
    assert org.class_generation_window_days == 21


def test_gym_admin_cannot_update_field_via_patch(api_client, make_organization, make_user):
    """Mismo permiso que trial_validity_days: solo superadmin edita la organización."""
    org = make_organization()
    admin = make_user('admin_a', organization=org, role='gym_admin')

    api_client.force_authenticate(user=admin)
    resp = api_client.patch(
        _detail(org),
        {'class_generation_window_days': 45},
        format='json',
    )

    assert resp.status_code == 403
    org.refresh_from_db()
    assert org.class_generation_window_days == 21


def test_pruning_grace_field_exists_with_default_7(make_organization):
    org = make_organization()
    assert org.class_pruning_grace_days == 7


def test_pruning_grace_field_is_exposed_in_organization_response(api_client, make_organization, make_user):
    org = make_organization()
    admin = make_user('admin_a', organization=org, role='gym_admin')

    api_client.force_authenticate(user=admin)
    resp = api_client.get(_detail(org))

    assert resp.status_code == 200
    assert resp.json()['class_pruning_grace_days'] == 7


def test_superadmin_can_update_pruning_grace_field_via_patch(api_client, make_organization, make_user):
    org = make_organization()
    superadmin = make_user('root', organization=None, role='superadmin')

    api_client.force_authenticate(user=superadmin)
    resp = api_client.patch(
        _detail(org),
        {'class_pruning_grace_days': 14},
        format='json',
    )

    assert resp.status_code == 200
    assert resp.json()['class_pruning_grace_days'] == 14
    org.refresh_from_db()
    assert org.class_pruning_grace_days == 14


def test_superadmin_can_set_pruning_grace_to_0(api_client, make_organization, make_user):
    """0 = sin colchón (podar apenas termina la clase) es un valor válido."""
    org = make_organization()
    superadmin = make_user('root', organization=None, role='superadmin')

    api_client.force_authenticate(user=superadmin)
    resp = api_client.patch(
        _detail(org),
        {'class_pruning_grace_days': 0},
        format='json',
    )

    assert resp.status_code == 200
    org.refresh_from_db()
    assert org.class_pruning_grace_days == 0


def test_superadmin_can_set_pruning_grace_max_allowed_value_90(api_client, make_organization, make_user):
    org = make_organization()
    superadmin = make_user('root', organization=None, role='superadmin')

    api_client.force_authenticate(user=superadmin)
    resp = api_client.patch(
        _detail(org),
        {'class_pruning_grace_days': 90},
        format='json',
    )

    assert resp.status_code == 200
    org.refresh_from_db()
    assert org.class_pruning_grace_days == 90


def test_pruning_grace_value_above_90_is_rejected(api_client, make_organization, make_user):
    org = make_organization()
    superadmin = make_user('root', organization=None, role='superadmin')

    api_client.force_authenticate(user=superadmin)
    resp = api_client.patch(
        _detail(org),
        {'class_pruning_grace_days': 91},
        format='json',
    )

    assert resp.status_code == 400
    org.refresh_from_db()
    assert org.class_pruning_grace_days == 7


def test_gym_admin_cannot_update_pruning_grace_field_via_patch(api_client, make_organization, make_user):
    """Mismo permiso que class_generation_window_days: solo superadmin edita la organización."""
    org = make_organization()
    admin = make_user('admin_a', organization=org, role='gym_admin')

    api_client.force_authenticate(user=admin)
    resp = api_client.patch(
        _detail(org),
        {'class_pruning_grace_days': 14},
        format='json',
    )

    assert resp.status_code == 403
    org.refresh_from_db()
    assert org.class_pruning_grace_days == 7


def test_max_reservation_window_field_exists_with_default_21(make_organization):
    org = make_organization()
    assert org.max_reservation_window_days == 21


@pytest.mark.parametrize('value', [1, 366])
def test_max_reservation_window_model_accepts_bounds(make_organization, value):
    org = make_organization()
    org.max_reservation_window_days = value

    org.full_clean()


@pytest.mark.parametrize('value', [0, 367])
def test_max_reservation_window_model_rejects_out_of_bounds(make_organization, value):
    org = make_organization()
    org.max_reservation_window_days = value

    with pytest.raises(ValidationError) as excinfo:
        org.full_clean()

    assert 'max_reservation_window_days' in excinfo.value.message_dict


def test_max_reservation_window_field_is_exposed_in_organization_response(api_client, make_organization, make_user):
    org = make_organization()
    admin = make_user('admin_a', organization=org, role='gym_admin')

    api_client.force_authenticate(user=admin)
    resp = api_client.get(_detail(org))

    assert resp.status_code == 200
    assert resp.json()['max_reservation_window_days'] == 21


def test_superadmin_can_update_max_reservation_window_field_via_patch(api_client, make_organization, make_user):
    org = make_organization()
    superadmin = make_user('root', organization=None, role='superadmin')

    api_client.force_authenticate(user=superadmin)
    resp = api_client.patch(
        _detail(org),
        {'max_reservation_window_days': 45},
        format='json',
    )

    assert resp.status_code == 200
    assert resp.json()['max_reservation_window_days'] == 45
    org.refresh_from_db()
    assert org.max_reservation_window_days == 45


@pytest.mark.parametrize('value', [0, 367])
def test_max_reservation_window_invalid_values_are_rejected_via_patch(
    api_client, make_organization, make_user, value
):
    org = make_organization()
    superadmin = make_user('root', organization=None, role='superadmin')

    api_client.force_authenticate(user=superadmin)
    resp = api_client.patch(
        _detail(org),
        {'max_reservation_window_days': value},
        format='json',
    )

    assert resp.status_code == 400
    org.refresh_from_db()
    assert org.max_reservation_window_days == 21


def test_max_reservation_window_travels_in_login_and_me_with_existing_windows(
    api_client, make_organization, make_user
):
    org = make_organization()
    org.trial_validity_days = 9
    org.class_generation_window_days = 28
    org.max_reservation_window_days = 35
    org.class_pruning_grace_days = 6
    org.save(
        update_fields=[
            'trial_validity_days',
            'class_generation_window_days',
            'max_reservation_window_days',
            'class_pruning_grace_days',
        ]
    )
    student = make_user('student_a', organization=org, role='student', password='Passw0rd2026')
    host = {'HTTP_HOST': f'{org.subdomain}.localhost'}

    login_resp = api_client.post(
        '/api/login/',
        {'email': student.email, 'password': 'Passw0rd2026'},
        format='json',
        **host,
    )

    assert login_resp.status_code == 200
    login_org = login_resp.json()['user']['organization_detail']
    assert login_org['trial_validity_days'] == 9
    assert login_org['class_generation_window_days'] == 28
    assert login_org['max_reservation_window_days'] == 35
    assert login_org['class_pruning_grace_days'] == 6

    api_client.credentials(HTTP_AUTHORIZATION=f"Token {login_resp.json()['token']}")
    me_resp = api_client.get('/api/me/', **host)

    assert me_resp.status_code == 200
    me_org = me_resp.json()['organization_detail']
    assert me_org['trial_validity_days'] == 9
    assert me_org['class_generation_window_days'] == 28
    assert me_org['max_reservation_window_days'] == 35
    assert me_org['class_pruning_grace_days'] == 6
