import pytest

pytestmark = pytest.mark.django_db

CHECK_SUBDOMAIN_URL = '/api/public/organizations/check-subdomain/'


def test_public_subdomain_check_returns_only_existence(api_client, make_organization):
    org = make_organization(name='Cross Santiago')

    ok = api_client.get(CHECK_SUBDOMAIN_URL, {'subdomain': org.subdomain})
    assert ok.status_code == 200
    assert ok.json() == {'exists': True}

    missing = api_client.get(CHECK_SUBDOMAIN_URL, {'subdomain': 'no-existe'})
    assert missing.status_code == 200
    assert missing.json() == {'exists': False}


def test_public_subdomain_check_requires_active_org(api_client, make_organization):
    org = make_organization(name='Cross Santiago')
    org.is_active = False
    org.save(update_fields=['is_active'])

    resp = api_client.get(CHECK_SUBDOMAIN_URL, {'subdomain': org.subdomain})

    assert resp.status_code == 200
    assert resp.json() == {'exists': False}


def test_public_subdomain_check_hides_invalid_input(api_client):
    resp = api_client.get(CHECK_SUBDOMAIN_URL, {'subdomain': '../api'})

    assert resp.status_code == 200
    assert resp.json() == {'exists': False}
