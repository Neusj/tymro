import pytest

from core.models import Plan
from core.services import payments


@pytest.fixture(autouse=True)
def _fake(settings):
    settings.PAYMENTS_PROVIDER = 'fake'
    settings.PAYMENTS_ENCRYPTION_KEY = __import__(
        'core.fields', fromlist=['generate_encryption_key']).generate_encryption_key()
    settings.PAYMENTS_APEX_BASE_URL = 'https://app.tymroapp.com'


@pytest.fixture
def connected_org(make_organization):
    org = make_organization()
    payments.connect_callback(code='C', state=payments._sign_state(org.id))
    return org


def test_checkout_endpoint_returns_redirect_url(api_client, connected_org, make_user):
    org = connected_org
    student = make_user('stu', organization=org, role='student')
    plan = Plan.objects.create(organization=org, name='M', plan_type='monthly', total_classes=1,
                               unlimited_classes=False, duration_days=30, price=1000.0)
    api_client.force_authenticate(user=student)
    resp = api_client.post('/api/payments/checkout/', {'plan_id': plan.id}, format='json')
    assert resp.status_code == 200
    assert 'redirect_url' in resp.data and 'transaction_id' in resp.data


def test_checkout_requires_student(api_client, connected_org, make_user):
    org = connected_org
    admin = make_user('a', organization=org, role='gym_admin')
    plan = Plan.objects.create(organization=org, name='M', plan_type='monthly', total_classes=1,
                               unlimited_classes=False, duration_days=30, price=1000.0)
    api_client.force_authenticate(user=admin)
    resp = api_client.post('/api/payments/checkout/', {'plan_id': plan.id}, format='json')
    assert resp.status_code == 403


def test_status_endpoint_scoped_to_owner(api_client, connected_org, make_user):
    org = connected_org
    student = make_user('stu2', organization=org, role='student')
    plan = Plan.objects.create(organization=org, name='M', plan_type='monthly', total_classes=1,
                               unlimited_classes=False, duration_days=30, price=1000.0)
    tx, _ = payments.create_checkout(organization=org, user=student, plan=plan)
    other = make_user('stu3', organization=org, role='student')
    api_client.force_authenticate(user=other)
    assert api_client.get(f'/api/payments/transactions/{tx.id}/status/').status_code == 404
    api_client.force_authenticate(user=student)
    resp = api_client.get(f'/api/payments/transactions/{tx.id}/status/')
    assert resp.status_code == 200
    assert resp.data['status'] == 'pending'
