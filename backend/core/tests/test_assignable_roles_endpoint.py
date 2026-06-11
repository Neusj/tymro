"""Contrato HTTP de GET /api/users/assignable-roles/ (Ronda 2).

Fija values, labels (español) Y orden exactos por rol. La fuente de verdad es
accounts/roles.py (assignable_role_choices); estos dicts son el contrato
esperado, no derivado — si la matriz o los labels cambian, estos tests deben
cambiar conscientemente.
"""
import pytest

pytestmark = pytest.mark.django_db

EXPECTED = {
    'superadmin': [
        {'value': 'superadmin', 'label': 'Superadmin'},
        {'value': 'gym_admin', 'label': 'Gym Admin'},
        {'value': 'manager', 'label': 'Manager'},
        {'value': 'monitor', 'label': 'Monitor'},
        {'value': 'teacher', 'label': 'Profesor'},
        {'value': 'student', 'label': 'Alumno'},
    ],
    'gym_admin': [
        {'value': 'gym_admin', 'label': 'Gym Admin'},
        {'value': 'manager', 'label': 'Manager'},
        {'value': 'monitor', 'label': 'Monitor'},
        {'value': 'teacher', 'label': 'Profesor'},
        {'value': 'student', 'label': 'Alumno'},
    ],
    'manager': [
        {'value': 'teacher', 'label': 'Profesor'},
        {'value': 'student', 'label': 'Alumno'},
    ],
    'monitor': [],
    'teacher': [],
    'student': [],
}


@pytest.mark.parametrize('actor_role', list(EXPECTED))
def test_assignable_roles_by_actor(api_client, make_user, make_organization, actor_role):
    org = make_organization()
    actor = make_user(
        f'actor_{actor_role}',
        organization=None if actor_role == 'superadmin' else org,
        role=actor_role,
    )
    api_client.force_authenticate(user=actor)

    response = api_client.get('/api/users/assignable-roles/')

    assert response.status_code == 200
    assert response.json() == EXPECTED[actor_role]


def test_assignable_roles_anonymous_is_401(api_client):
    assert api_client.get('/api/users/assignable-roles/').status_code == 401
