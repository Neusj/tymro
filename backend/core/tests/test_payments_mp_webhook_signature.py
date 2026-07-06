import hashlib
import hmac
import json

from core.services.providers.mercadopago import MercadoPagoProvider


def _sig_headers(secret, data_id, request_id, ts):
    manifest = f'id:{data_id};request-id:{request_id};ts:{ts};'
    v1 = hmac.new(secret.encode(), manifest.encode(), hashlib.sha256).hexdigest()
    return {'x-signature': f'ts={ts},v1={v1}', 'x-request-id': request_id}


def test_verify_webhook_accepts_valid_signature():
    p = MercadoPagoProvider(client_id='A', client_secret='S', webhook_secret='WHSECRET')
    body = json.dumps({'type': 'payment', 'data': {'id': '123'}}).encode()
    headers = _sig_headers('WHSECRET', '123', 'req-1', '1720000000')
    assert p.verify_webhook(headers=headers, raw_body=body) is True


def test_verify_webhook_rejects_tampered_signature():
    p = MercadoPagoProvider(client_id='A', client_secret='S', webhook_secret='WHSECRET')
    body = json.dumps({'type': 'payment', 'data': {'id': '123'}}).encode()
    headers = _sig_headers('OTHER', '123', 'req-1', '1720000000')   # secret equivocado
    assert p.verify_webhook(headers=headers, raw_body=body) is False


def test_parse_webhook_extracts_payment_id():
    p = MercadoPagoProvider(client_id='A', client_secret='S', webhook_secret='W')
    body = json.dumps({'type': 'payment', 'action': 'payment.updated',
                       'data': {'id': '999'}}).encode()
    env = p.parse_webhook(headers={}, raw_body=body)
    assert env.type == 'payment'
    assert env.action == 'payment.updated'
    assert env.provider_payment_id == '999'
