import pytest
from django.urls import reverse   # si las rutas tienen name; si no, usar paths literales

from core.models import PaymentAccount
from core.services import payments


@pytest.fixture(autouse=True)
def _fake(settings):
    settings.PAYMENTS_PROVIDER = 'fake'
    settings.PAYMENTS_ENCRYPTION_KEY = __import__(
        'core.fields', fromlist=['generate_encryption_key']).generate_encryption_key()


def test_connect_requires_gym_admin(api_client, make_organization, make_user):
    org = make_organization()
    student = make_user('s', organization=org, role='student')
    api_client.force_authenticate(user=student)
    resp = api_client.post('/api/payments/connect/')
    assert resp.status_code == 403


def test_connect_returns_authorization_url(api_client, make_organization, make_user):
    org = make_organization()
    admin = make_user('a', organization=org, role='gym_admin')
    api_client.force_authenticate(user=admin)
    resp = api_client.post('/api/payments/connect/')
    assert resp.status_code == 200
    assert 'authorization_url' in resp.data
    assert 'state=' in resp.data['authorization_url']


def test_oauth_callback_creates_account_and_redirects(api_client, make_organization):
    org = make_organization()
    state = payments._sign_state(org.id)
    resp = api_client.get('/api/payments/oauth/callback/', {'code': 'C', 'state': state})
    assert resp.status_code in (302, 200)
    assert PaymentAccount.objects.filter(organization=org).exists()


def test_account_view_scoped_to_org(api_client, make_organization, make_user):
    org = make_organization()
    payments.connect_callback(code='C', state=payments._sign_state(org.id))
    admin = make_user('a', organization=org, role='gym_admin')
    api_client.force_authenticate(user=admin)
    resp = api_client.get('/api/payments/account/')
    assert resp.status_code == 200
    assert resp.data['status'] == 'connected'
    assert resp.data['provider'] == 'fake'   # = settings.PAYMENTS_PROVIDER en el entorno de test
