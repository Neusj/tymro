"""Regresión: un gym_admin debe poder crear una sucursal SIN enviar `organization`
en el payload (el backend la asigna desde el usuario autenticado).

Bug: el `UniqueTogetherValidator` que DRF auto-genera a partir de
`unique_together = ('organization', 'name')` exige `organization` en el payload al
crear y corre ANTES del `validate()` que la auto-asigna, devolviendo 400 antes de
que el serializer pueda completar la organización."""
import pytest

from core.models import Branch

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


def test_gym_admin_creates_branch_without_organization_in_payload(api_client, make_organization, make_user):
    org = make_organization(name='Gym Admin Org')
    make_user('admin', role='gym_admin', organization=org)
    _login(api_client, 'admin')

    created = api_client.post('/api/branches/', {'name': 'Sede Centro'}, format='json')

    assert created.status_code == 201, created.content
    branch = Branch.objects.get(id=created.json()['id'])
    assert branch.organization_id == org.id


def test_gym_admin_cannot_create_duplicate_branch_name(api_client, make_organization, make_user):
    org = make_organization(name='Gym Dup Org')
    make_user('admin', role='gym_admin', organization=org)
    Branch.objects.create(organization=org, name='Sede Centro')
    _login(api_client, 'admin')

    # Mismo nombre (case-insensitive) en la misma organización debe rechazarse.
    created = api_client.post('/api/branches/', {'name': 'sede centro'}, format='json')

    assert created.status_code == 400, created.content
    assert 'name' in created.json()
