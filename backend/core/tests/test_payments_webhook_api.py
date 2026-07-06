import hashlib
import hmac
import json
from decimal import Decimal

import pytest

from core.models import Plan, PaymentTransaction, StudentPlan, WebhookEvent
from core.services import payments
from core.services.providers.base import PaymentStatus


@pytest.fixture(autouse=True)
def _fake(settings):
    # Firma real la valida el provider MP; para el webhook API usamos el provider MP
    # solo para firma/parseo, pero el fetch lo hace el fake vía process_notification.
    settings.PAYMENTS_PROVIDER = 'fake'
    settings.MP_WEBHOOK_SECRET = 'WH'
    settings.PAYMENTS_ENCRYPTION_KEY = __import__(
        'core.fields', fromlist=['generate_encryption_key']).generate_encryption_key()
    settings.PAYMENTS_APEX_BASE_URL = 'https://app.tymroapp.com'


def _signed(body_dict, secret='WH', request_id='req-1', ts='1720000000'):
    body = json.dumps(body_dict).encode()
    data_id = str(body_dict.get('data', {}).get('id', ''))
    manifest = f'id:{data_id};request-id:{request_id};ts:{ts};'
    v1 = hmac.new(secret.encode(), manifest.encode(), hashlib.sha256).hexdigest()
    return body, {'HTTP_X_SIGNATURE': f'ts={ts},v1={v1}', 'HTTP_X_REQUEST_ID': request_id}


@pytest.fixture
def approved_tx(make_organization, make_user):
    org = make_organization()
    payments.connect_callback(code='C', state=payments._sign_state(org.id))
    student = make_user('stu', organization=org, role='student')
    plan = Plan.objects.create(organization=org, name='M', plan_type='monthly', total_classes=12,
                               unlimited_classes=False, duration_days=30, price=30000.0)
    tx, _ = payments.create_checkout(organization=org, user=student, plan=plan)
    from core.services.providers import get_payment_provider
    get_payment_provider().queue_payment(external_reference=str(tx.id),
                                         status=PaymentStatus.APPROVED, amount=Decimal('30000'),
                                         provider_payment_id='PAY1')
    return org, student, tx


def test_webhook_invalid_signature_401(api_client, settings):
    settings.PAYMENTS_PROVIDER = 'mercadopago'
    body, headers = _signed({'type': 'payment', 'data': {'id': '1'}}, secret='WRONG')
    resp = api_client.post('/api/payments/webhook/?tx=abc', data=body,
                           content_type='application/json', **headers)
    assert resp.status_code == 401


@pytest.mark.django_db
def test_invalid_signature_records_no_webhook_event(api_client, settings):
    settings.PAYMENTS_PROVIDER = 'mercadopago'
    body, headers = _signed({'type': 'payment', 'data': {'id': '1'}}, secret='WRONG')
    resp = api_client.post('/api/payments/webhook/?tx=abc', data=body,
                           content_type='application/json', **headers)
    assert resp.status_code == 401
    assert WebhookEvent.objects.count() == 0


@pytest.mark.django_db
def test_malformed_tx_returns_200(api_client, settings):
    settings.PAYMENTS_PROVIDER = 'mercadopago'
    body, headers = _signed({'type': 'payment', 'data': {'id': 'PAY1'}})
    resp = api_client.post('/api/payments/webhook/?tx=not-a-uuid', data=body,
                           content_type='application/json', **headers)
    assert resp.status_code == 200


def test_webhook_valid_signature_calls_processor(api_client, approved_tx, settings, monkeypatch):
    settings.PAYMENTS_PROVIDER = 'mercadopago'   # firma/parseo reales
    org, student, tx = approved_tx
    calls = {}
    def _fake_process(*, tx_id, provider_payment_id):
        calls['tx_id'] = tx_id
        calls['pid'] = provider_payment_id
        return None
    monkeypatch.setattr('core.views_payments.payments.process_payment_notification', _fake_process)
    body, headers = _signed({'type': 'payment', 'data': {'id': 'PAY1'}})
    resp = api_client.post(f'/api/payments/webhook/?tx={tx.id}', data=body,
                           content_type='application/json', **headers)
    assert resp.status_code == 200
    assert calls == {'tx_id': str(tx.id), 'pid': 'PAY1'}
