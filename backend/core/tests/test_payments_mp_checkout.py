from decimal import Decimal

import responses

from core.services.providers.base import (BackUrls, CheckoutItem, PaymentStatus)
from core.services.providers.mercadopago import MercadoPagoProvider


def _p():
    return MercadoPagoProvider(client_id='APP', client_secret='S', webhook_secret='W')


@responses.activate
def test_create_checkout_posts_preference_and_returns_init_point():
    responses.add(responses.POST, MercadoPagoProvider.PREFERENCE_URL, json={
        'id': 'PREF-1', 'init_point': 'https://mp/checkout/PREF-1',
        'sandbox_init_point': 'https://sandbox.mp/checkout/PREF-1',
    }, status=201)
    session = _p().create_checkout(
        access_token='GYMTOKEN', external_reference='tx-uuid',
        items=[CheckoutItem(title='Plan Mensual', quantity=1, unit_price=Decimal('30000'))],
        payer_email='alumno@x.cl',
        back_urls=BackUrls(success='https://s', pending='https://p', failure='https://f'),
        notification_url='https://app.tymroapp.com/api/payments/webhook/?tx=tx-uuid',
        expires_at=None,
    )
    assert session.provider_preference_id == 'PREF-1'
    assert session.redirect_url == 'https://mp/checkout/PREF-1'
    sent = responses.calls[0].request
    assert sent.headers['Authorization'] == 'Bearer GYMTOKEN'
    import json
    body = json.loads(sent.body)
    assert body['external_reference'] == 'tx-uuid'
    assert body['items'][0]['currency_id'] == 'CLP'
    assert body['items'][0]['unit_price'] == 30000
    assert body['notification_url'].endswith('tx=tx-uuid')


@responses.activate
def test_fetch_payment_normalizes_status():
    responses.add(responses.GET, MercadoPagoProvider.PAYMENT_URL.format(id='PAY9'), json={
        'id': 'PAY9', 'status': 'approved', 'status_detail': 'accredited',
        'transaction_amount': 30000, 'currency_id': 'CLP',
        'external_reference': 'tx-uuid', 'collector_id': 987654,
    }, status=200)
    payment = _p().fetch_payment(access_token='GYMTOKEN', provider_payment_id='PAY9')
    assert payment.status == PaymentStatus.APPROVED
    assert payment.amount == Decimal('30000')
    assert payment.currency == 'CLP'
    assert payment.external_reference == 'tx-uuid'
    assert payment.collector_id == '987654'


@responses.activate
def test_fetch_payment_maps_rejected():
    responses.add(responses.GET, MercadoPagoProvider.PAYMENT_URL.format(id='P'), json={
        'id': 'P', 'status': 'rejected', 'status_detail': 'cc_rejected',
        'transaction_amount': 100, 'currency_id': 'CLP', 'external_reference': 'e', 'collector_id': 1,
    }, status=200)
    assert _p().fetch_payment(access_token='T', provider_payment_id='P').status == PaymentStatus.REJECTED
