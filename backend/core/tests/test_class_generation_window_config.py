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
