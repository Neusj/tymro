"""Gestión de `is_active` y `public_registration_enabled` de una organización.

Cubre la regla de seguridad clave: solo el superadmin puede cambiar `is_active`
(y el registro público) por el serializer de organización; un gym_admin NO puede
desactivar su propia org por esta vía. Además: las orgs nacen SIEMPRE activas y
con registro público habilitado, aunque el payload de create intente lo contrario.
"""
import pytest

from core.models import Organization

pytestmark = pytest.mark.django_db

ORG_URL = '/api/organizations/'


def _detail(org):
    return f'{ORG_URL}{org.id}/'


# --- Superadmin SÍ puede gestionar ambos flags ----------------------------------

def test_superadmin_can_toggle_flags_on_update(api_client, make_organization, make_user):
    org = make_organization(name='Org A')
    assert org.is_active is True
    assert org.public_registration_enabled is True

    superadmin = make_user('root', organization=None, role='superadmin')
    api_client.force_authenticate(user=superadmin)

    resp = api_client.patch(
        _detail(org),
        {'is_active': False, 'public_registration_enabled': False},
        format='json',
    )
    assert resp.status_code == 200

    org.refresh_from_db()
    assert org.is_active is False
    assert org.public_registration_enabled is False


# --- SEGURIDAD: gym_admin NO puede cambiar is_active por el serializer -----------

def test_gym_admin_cannot_change_is_active(api_client, make_organization, make_user):
    org = make_organization(name='Org A')
    admin = make_user('admin_a', organization=org, role='gym_admin')

    api_client.force_authenticate(user=admin)
    resp = api_client.patch(_detail(org), {'is_active': False}, format='json')

    # perform_update rechaza a cualquiera que no sea superadmin.
    assert resp.status_code == 403
    org.refresh_from_db()
    assert org.is_active is True


def test_gym_admin_cannot_disable_own_org_via_serializer(api_client, make_organization, make_user):
    """Ni siquiera mezclando is_active con un PATCH 'inocente' de branding."""
    org = make_organization(name='Org A')
    admin = make_user('admin_a', organization=org, role='gym_admin')

    api_client.force_authenticate(user=admin)
    resp = api_client.patch(
        _detail(org),
        {'primary_color': '#000000', 'is_active': False},
        format='json',
    )
    assert resp.status_code == 403
    org.refresh_from_db()
    assert org.is_active is True
    assert org.primary_color != '#000000'


# --- Las orgs nacen SIEMPRE en True (create ignora ambos flags) ------------------

def test_create_ignores_flags_and_org_is_born_enabled(api_client, make_user):
    superadmin = make_user('root', organization=None, role='superadmin')
    api_client.force_authenticate(user=superadmin)

    resp = api_client.post(
        ORG_URL,
        {
            'name': 'Nueva Org',
            'slug': 'nueva-org',
            # Intento explícito de nacer rota: debe ser ignorado.
            'is_active': False,
            'public_registration_enabled': False,
        },
        format='json',
    )
    assert resp.status_code == 201

    org = Organization.objects.get(slug='nueva-org')
    assert org.is_active is True
    assert org.public_registration_enabled is True
