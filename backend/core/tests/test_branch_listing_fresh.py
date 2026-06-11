"""Regresión: tras crear una sucursal debe aparecer en el listado de inmediato,
sin reiniciar el proceso (bug del queryset cacheado a nivel de clase)."""
import pytest

from core.models import Branch

pytestmark = pytest.mark.django_db

PASSWORD = 'Passw0rd2026'


def _ids(payload):
    items = payload['results'] if isinstance(payload, dict) and 'results' in payload else payload
    return {item['id'] for item in items}


def test_created_branch_appears_in_listing_immediately(api_client, make_organization, make_user):
    org = make_organization(name='Gym Repro')
    make_user('super', role='superadmin', organization=None)

    token = api_client.post(
        '/api/login/', {'username': 'super', 'password': PASSWORD}, format='json'
    ).json()['token']
    api_client.credentials(HTTP_AUTHORIZATION=f'Token {token}')

    # Primer listado: evalúa el queryset (poblaría el _result_cache si se reusa).
    first = api_client.get('/api/branches/')
    assert first.status_code == 200

    # Creamos una sucursal vía API.
    created = api_client.post(
        '/api/branches/',
        {'name': 'Sede Nueva', 'organization': org.id},
        format='json',
    )
    assert created.status_code == 201, created.content
    new_id = created.json()['id']

    # Segundo listado en el mismo proceso: la nueva sucursal DEBE aparecer.
    second = api_client.get('/api/branches/')
    assert second.status_code == 200
    assert new_id in _ids(second.json()), 'La sucursal recién creada no aparece en el listado'
