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


def test_oauth_callback_redirects_to_org_subdomain(api_client, make_organization, settings):
    # Tras procesar el callback (que llega al apex), el backend redirige al SUBDOMINIO
    # del gym para que el gym_admin vuelva con su sesión intacta (no al apex).
    settings.FRONTEND_URL = 'https://tymroapp.com'
    org = make_organization()   # subdomain = 'org-N'
    state = payments._sign_state(org.id)
    resp = api_client.get('/api/payments/oauth/callback/', {'code': 'C', 'state': state})
    assert resp.status_code == 302
    assert resp['Location'] == f'https://{org.subdomain}.tymroapp.com/ajustes/pagos?connected=1'


def test_oauth_callback_invalid_state_redirects_to_apex(api_client, settings):
    # Sin org resoluble (state inválido), no hay subdominio al cual volver: cae al apex.
    settings.FRONTEND_URL = 'https://tymroapp.com'
    resp = api_client.get('/api/payments/oauth/callback/', {'code': 'C', 'state': 'bogus'})
    assert resp.status_code == 302
    assert resp['Location'] == 'https://tymroapp.com/ajustes/pagos?connected=0&error=state'


def test_frontend_base_for_organization_prepends_subdomain(settings):
    settings.FRONTEND_URL = 'https://tymroapp.com'

    class _Org:
        subdomain = 'acme'

    assert payments.frontend_base_for_organization(_Org()) == 'https://acme.tymroapp.com'


def test_frontend_base_for_organization_preserves_scheme_and_port(settings):
    settings.FRONTEND_URL = 'http://localhost:5173'

    class _Org:
        subdomain = 'acme'

    assert payments.frontend_base_for_organization(_Org()) == 'http://acme.localhost:5173'


def test_frontend_base_for_organization_without_subdomain_falls_back_to_apex(settings):
    settings.FRONTEND_URL = 'https://tymroapp.com'

    class _Org:
        subdomain = ''

    assert payments.frontend_base_for_organization(_Org()) == 'https://tymroapp.com'


def test_account_view_scoped_to_org(api_client, make_organization, make_user):
    org = make_organization()
    payments.connect_callback(code='C', state=payments._sign_state(org.id))
    admin = make_user('a', organization=org, role='gym_admin')
    api_client.force_authenticate(user=admin)
    resp = api_client.get('/api/payments/account/')
    assert resp.status_code == 200
    assert resp.data['status'] == 'connected'
    assert resp.data['provider'] == 'fake'   # = settings.PAYMENTS_PROVIDER en el entorno de test
