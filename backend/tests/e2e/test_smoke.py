"""Smoke E2E: verifica que el harness (live_server + Playwright request) funciona
y que los datos creados por ORM son visibles para el servidor vivo."""
import pytest


@pytest.mark.django_db(transaction=True)
def test_login_against_live_server(api, make_organization, make_user, login):
    org = make_organization('Smoke Org')
    make_user('smoke_admin', organization=org, role='gym_admin')

    token = login('smoke_admin')
    assert token

    # El token autentica contra el servidor real.
    me = api.get('/api/me/', headers={'Authorization': f'Token {token}'})
    assert me.status == 200, me.text()
    assert me.json()['username'] == 'smoke_admin'
