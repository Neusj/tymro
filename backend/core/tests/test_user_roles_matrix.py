"""Matriz actor×target del rediseño de roles (Ronda 1).

La fuente de verdad es accounts/roles.py; estos tests fijan el contrato HTTP
de /api/users/. Cubre creación (matriz completa 6×6), barrera de plataforma,
flags is_staff/is_superuser, organización forzada, edición/borrado (la misma
matriz gobierna gestionar instancias existentes) y visibilidad.

Notas de contrato:
- Denegaciones en create/update llegan como 400 (serializer, defensa en
  profundidad) o 403 (viewset); en destroy siempre 403.
- Instancias fuera del queryset del actor (otra org, superadmins) -> 404.
- Cambio de comportamiento aceptado: gym_admin SÍ puede crear/editar/borrar
  otros gym_admin de su organización.
"""
import pytest
from django.contrib.auth import get_user_model

User = get_user_model()

pytestmark = pytest.mark.django_db

ALL_ROLES = ['superadmin', 'gym_admin', 'manager', 'monitor', 'teacher', 'student']

# RUT válido (Módulo 11) para algunas altas: estos tests de permisos pueden
# incluirlo para aislar lo que prueban (rol/organización), no la validación del RUT.
VALID_RUT = '12345678-5'

# Espejo de accounts/roles.py: si la matriz central cambia, estos tests deben
# cambiar conscientemente (fijan el contrato, no lo derivan).
ASSIGNABLE = {
    'superadmin': {'superadmin', 'gym_admin', 'manager', 'monitor', 'teacher', 'student'},
    'gym_admin': {'gym_admin', 'manager', 'monitor', 'teacher', 'student'},
    'manager': {'teacher', 'student'},
    'monitor': set(),
    'teacher': set(),
    'student': set(),
}

DENIED_STATUSES = (400, 403)


@pytest.fixture
def org(make_organization):
    return make_organization()


@pytest.fixture
def other_org(make_organization):
    return make_organization()


def _make_actor(make_user, org, role, username=None):
    return make_user(
        username or f'actor_{role}',
        organization=None if role == 'superadmin' else org,
        role=role,
    )


def _auth_as(api_client, make_user, org, role):
    actor = _make_actor(make_user, org, role)
    api_client.force_authenticate(user=actor)
    return actor


# ---------------------------------------------------------------------------
# 1. Matriz de creación completa (6 actores × 6 targets)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('actor_role', ALL_ROLES)
@pytest.mark.parametrize('target_role', ALL_ROLES)
def test_create_matrix(api_client, make_user, org, actor_role, target_role):
    _auth_as(api_client, make_user, org, actor_role)
    email = f'new_{actor_role}_{target_role}@test.local'
    payload = {'email': email, 'role': target_role, 'password': 'Passw0rd2026'}
    if target_role != 'superadmin':
        payload['organization'] = org.id
        payload['rut'] = VALID_RUT

    response = api_client.post('/api/users/', payload, format='json')

    if target_role in ASSIGNABLE[actor_role]:
        assert response.status_code == 201, response.data
        created = User.objects.get(email__iexact=email)
        assert created.role == target_role
    else:
        assert response.status_code in DENIED_STATUSES, response.data
        assert not User.objects.filter(email__iexact=email).exists()


# ---------------------------------------------------------------------------
# 2. Barrera de plataforma: ningún rol de organización asigna superadmin
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('actor_role', ['gym_admin', 'manager', 'monitor', 'teacher', 'student'])
def test_org_roles_cannot_create_superadmin_even_in_payload(api_client, make_user, org, actor_role):
    _auth_as(api_client, make_user, org, actor_role)
    payload = {'email': 'sneaky_admin@test.local', 'role': 'superadmin', 'password': 'Passw0rd2026'}

    response = api_client.post('/api/users/', payload, format='json')

    assert response.status_code in DENIED_STATUSES
    assert not User.objects.filter(email__iexact='sneaky_admin@test.local').exists()
    assert not User.objects.filter(is_staff=True).exists()


# ---------------------------------------------------------------------------
# 3. Flags is_staff / is_superuser
# ---------------------------------------------------------------------------

def test_superadmin_creates_superadmin_with_staff_flags_and_no_org(api_client, make_user, org):
    _auth_as(api_client, make_user, org, 'superadmin')
    payload = {
        'email': 'new_platform_admin@test.local',
        'role': 'superadmin',
        'password': 'Passw0rd2026',
        'organization': org.id,  # debe ser ignorada/forzada a None
    }

    response = api_client.post('/api/users/', payload, format='json')

    assert response.status_code == 201, response.data
    created = User.objects.get(email__iexact='new_platform_admin@test.local')
    assert created.is_staff is True
    assert created.is_superuser is True
    assert created.organization_id is None


def test_superadmin_creates_gym_admin_without_staff_flags(api_client, make_user, org):
    _auth_as(api_client, make_user, org, 'superadmin')
    payload = {
        'email': 'new_gym_admin@test.local',
        'role': 'gym_admin',
        'password': 'Passw0rd2026',
        'organization': org.id,
        'rut': VALID_RUT,
    }

    response = api_client.post('/api/users/', payload, format='json')

    assert response.status_code == 201, response.data
    created = User.objects.get(email__iexact='new_gym_admin@test.local')
    assert created.is_staff is False
    assert created.is_superuser is False
    assert created.organization_id == org.id


# ---------------------------------------------------------------------------
# 4. Organización forzada para gym_admin y manager
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('actor_role', ['gym_admin', 'manager'])
def test_org_admin_cannot_create_in_other_org(api_client, make_user, org, other_org, actor_role):
    _auth_as(api_client, make_user, org, actor_role)
    payload = {
        'email': 'cross_org_teacher@test.local',
        'role': 'teacher',
        'password': 'Passw0rd2026',
        'organization': other_org.id,
        'rut': VALID_RUT,
    }

    response = api_client.post('/api/users/', payload, format='json')

    assert response.status_code == 403
    assert not User.objects.filter(email__iexact='cross_org_teacher@test.local').exists()


@pytest.mark.parametrize('actor_role', ['gym_admin', 'manager'])
def test_org_admin_creates_without_org_in_payload_gets_own_org(api_client, make_user, org, actor_role):
    _auth_as(api_client, make_user, org, actor_role)
    email = f'auto_org_student_{actor_role}@test.local'
    payload = {'email': email, 'role': 'student', 'password': 'Passw0rd2026', 'rut': VALID_RUT}

    response = api_client.post('/api/users/', payload, format='json')

    assert response.status_code == 201, response.data
    created = User.objects.get(email__iexact=email)
    assert created.organization_id == org.id


# ---------------------------------------------------------------------------
# 5. Edición: la misma matriz gobierna instancias existentes
# ---------------------------------------------------------------------------

def test_gym_admin_can_edit_other_gym_admin_same_org(api_client, make_user, org):
    """Cambio de comportamiento aceptado en Ronda 1 (antes denegado)."""
    _auth_as(api_client, make_user, org, 'gym_admin')
    peer = make_user('peer_gym_admin', organization=org, role='gym_admin')

    response = api_client.patch(f'/api/users/{peer.id}/', {'first_name': 'Editado'}, format='json')

    assert response.status_code == 200, response.data
    peer.refresh_from_db()
    assert peer.first_name == 'Editado'


def test_gym_admin_cannot_reach_superadmin_instances(api_client, make_user, org):
    _auth_as(api_client, make_user, org, 'gym_admin')
    platform_admin = make_user('platform_admin', organization=None, role='superadmin')

    response = api_client.patch(f'/api/users/{platform_admin.id}/', {'first_name': 'X'}, format='json')

    # Fuera del queryset del gym_admin (org=None) -> 404.
    assert response.status_code == 404


@pytest.mark.parametrize('target_role,allowed', [
    ('teacher', True),
    ('student', True),
    ('monitor', False),
    ('manager', False),
    ('gym_admin', False),
])
def test_manager_edit_matrix(api_client, make_user, org, target_role, allowed):
    _auth_as(api_client, make_user, org, 'manager')
    target = make_user(f'target_{target_role}', organization=org, role=target_role)

    response = api_client.patch(f'/api/users/{target.id}/', {'first_name': 'Editado'}, format='json')

    if allowed:
        assert response.status_code == 200, response.data
    else:
        # Visible en el queryset del manager (misma org) pero gestión denegada.
        assert response.status_code in DENIED_STATUSES


def test_manager_cannot_promote_teacher_to_manager(api_client, make_user, org):
    """La gestión de la instancia está permitida, pero la asignación del rol no."""
    _auth_as(api_client, make_user, org, 'manager')
    teacher = make_user('promotable_teacher', organization=org, role='teacher')

    response = api_client.patch(f'/api/users/{teacher.id}/', {'role': 'manager'}, format='json')

    assert response.status_code in DENIED_STATUSES
    teacher.refresh_from_db()
    assert teacher.role == 'teacher'


@pytest.mark.parametrize('actor_role', ['monitor', 'teacher', 'student'])
def test_non_managing_roles_cannot_edit_even_themselves(api_client, make_user, org, actor_role):
    actor = _auth_as(api_client, make_user, org, actor_role)

    response = api_client.patch(f'/api/users/{actor.id}/', {'first_name': 'Yo'}, format='json')

    assert response.status_code in DENIED_STATUSES


# ---------------------------------------------------------------------------
# 6. Borrado
# ---------------------------------------------------------------------------

def test_gym_admin_can_delete_peer_gym_admin(api_client, make_user, org):
    _auth_as(api_client, make_user, org, 'gym_admin')
    peer = make_user('deletable_gym_admin', organization=org, role='gym_admin')

    response = api_client.delete(f'/api/users/{peer.id}/')

    assert response.status_code == 204
    assert not User.objects.filter(id=peer.id).exists()


def test_manager_can_delete_teacher(api_client, make_user, org):
    _auth_as(api_client, make_user, org, 'manager')
    teacher = make_user('deletable_teacher', organization=org, role='teacher')

    response = api_client.delete(f'/api/users/{teacher.id}/')

    assert response.status_code == 204
    assert not User.objects.filter(id=teacher.id).exists()


@pytest.mark.parametrize('target_role', ['gym_admin', 'manager', 'monitor'])
def test_manager_cannot_delete_unmanageable_roles(api_client, make_user, org, target_role):
    _auth_as(api_client, make_user, org, 'manager')
    target = make_user(f'undeletable_{target_role}', organization=org, role=target_role)

    response = api_client.delete(f'/api/users/{target.id}/')

    assert response.status_code == 403
    assert User.objects.filter(id=target.id).exists()


def test_gym_admin_cannot_delete_cross_org_user(api_client, make_user, org, other_org):
    _auth_as(api_client, make_user, org, 'gym_admin')
    outsider = make_user('outsider_teacher', organization=other_org, role='teacher')

    response = api_client.delete(f'/api/users/{outsider.id}/')

    assert response.status_code == 404
    assert User.objects.filter(id=outsider.id).exists()


# ---------------------------------------------------------------------------
# 7. Visibilidad
# ---------------------------------------------------------------------------

def _listed_ids(payload):
    items = payload['results'] if isinstance(payload, dict) and 'results' in payload else payload
    return {item['id'] for item in items}


def test_manager_lists_only_own_org_users(api_client, make_user, org, other_org):
    actor = _auth_as(api_client, make_user, org, 'manager')
    own_teacher = make_user('own_teacher', organization=org, role='teacher')
    foreign_teacher = make_user('foreign_teacher', organization=other_org, role='teacher')

    response = api_client.get('/api/users/')

    assert response.status_code == 200
    ids = _listed_ids(response.data)
    assert {actor.id, own_teacher.id} <= ids
    assert foreign_teacher.id not in ids


def test_monitor_lists_own_org_users_readonly(api_client, make_user, org, other_org):
    """Monitor es un visor de solo lectura de su organización: lista los usuarios
    de su org (no los de otra). La denegación de escritura se cubre en
    test_non_managing_roles_cannot_edit_even_themselves y la matriz de borrado."""
    actor = _auth_as(api_client, make_user, org, 'monitor')
    own_teacher = make_user('own_teacher', organization=org, role='teacher')
    foreign_teacher = make_user('foreign_teacher', organization=other_org, role='teacher')

    response = api_client.get('/api/users/')

    assert response.status_code == 200
    ids = _listed_ids(response.data)
    assert {actor.id, own_teacher.id} <= ids
    assert foreign_teacher.id not in ids


def test_monitor_can_retrieve_own_org_users_but_not_cross_org(api_client, make_user, org, other_org):
    actor = _auth_as(api_client, make_user, org, 'monitor')
    own = make_user('some_teacher', organization=org, role='teacher')
    outsider = make_user('outsider_teacher', organization=other_org, role='teacher')

    assert api_client.get(f'/api/users/{actor.id}/').status_code == 200
    assert api_client.get(f'/api/users/{own.id}/').status_code == 200
    assert api_client.get(f'/api/users/{outsider.id}/').status_code == 404
