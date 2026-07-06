"""Implementación concreta de PaymentProvider para MercadoPago (Checkout Pro + OAuth).

Aísla TODO el detalle de MercadoPago (endpoints, formatos, firma). El resto del
sistema no importa este módulo directamente: usa get_payment_provider().

VERIFICAR CONTRA LA DOC VIGENTE DE MP AL IMPLEMENTAR/PROBAR:
- Endpoint exacto de autorización (auth.mercadopago.cl) y si PKCE es obligatorio.
- TTL real de expires_in (se usa el valor devuelto, no se hardcodea).
- Formato del header x-signature y del manifest (ver Task 12).
"""
import hashlib
import hmac
import json
from decimal import Decimal
from urllib.parse import urlencode

import requests

from .base import (BackUrls, CheckoutItem, CheckoutSession, OAuthTokens, PaymentProvider,
                   PaymentProviderError, PaymentStatus, ProviderPayment)

_TIMEOUT = 15

_STATUS_MAP = {
    'approved': PaymentStatus.APPROVED,
    'pending': PaymentStatus.PENDING,
    'in_process': PaymentStatus.IN_PROCESS,
    'authorized': PaymentStatus.IN_PROCESS,
    'rejected': PaymentStatus.REJECTED,
    'cancelled': PaymentStatus.CANCELLED,
    'refunded': PaymentStatus.REFUNDED,
    'charged_back': PaymentStatus.REFUNDED,
}


class MercadoPagoProvider(PaymentProvider):
    name = 'mercadopago'

    AUTH_URL = 'https://auth.mercadopago.cl/authorization'
    TOKEN_URL = 'https://api.mercadopago.com/oauth/token'
    PREFERENCE_URL = 'https://api.mercadopago.com/checkout/preferences'
    PAYMENT_URL = 'https://api.mercadopago.com/v1/payments/{id}'

    def __init__(self, *, client_id, client_secret, webhook_secret):
        self.client_id = client_id
        self.client_secret = client_secret
        self.webhook_secret = webhook_secret

    # --- OAuth ---
    def get_authorization_url(self, *, state, redirect_uri):
        params = {
            'client_id': self.client_id,
            'response_type': 'code',
            'platform_id': 'mp',
            'state': state,
            'redirect_uri': redirect_uri,
        }
        return f'{self.AUTH_URL}?{urlencode(params)}'

    def _post_token(self, payload) -> OAuthTokens:
        try:
            resp = requests.post(self.TOKEN_URL, json=payload, timeout=_TIMEOUT,
                                 headers={'Accept': 'application/json'})
        except requests.RequestException as exc:
            raise PaymentProviderError(f'MP token request falló: {exc}') from exc
        if resp.status_code >= 400:
            raise PaymentProviderError(f'MP token error {resp.status_code}: {resp.text}')
        data = resp.json()
        return OAuthTokens(
            access_token=data['access_token'],
            refresh_token=data['refresh_token'],
            expires_in=int(data.get('expires_in', 0)),
            provider_user_id=str(data.get('user_id', '')),
            public_key=data.get('public_key'),
            scope=data.get('scope'),
        )

    def exchange_code(self, *, code, redirect_uri):
        return self._post_token({
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': redirect_uri,
        })

    def refresh_tokens(self, *, refresh_token):
        return self._post_token({
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'grant_type': 'refresh_token',
            'refresh_token': refresh_token,
        })

    # --- Cobro (Task 9) ---
    def create_checkout(self, *, access_token, external_reference, items, payer_email,
                        back_urls, notification_url, expires_at):
        body = {
            'items': [{
                'title': it.title,
                'quantity': it.quantity,
                'unit_price': int(it.unit_price),   # CLP sin decimales
                'currency_id': 'CLP',
            } for it in items],
            'external_reference': external_reference,
            'notification_url': notification_url,
            'auto_return': 'approved',
        }
        if payer_email:
            body['payer'] = {'email': payer_email}
        if back_urls:
            body['back_urls'] = {'success': back_urls.success, 'pending': back_urls.pending,
                                 'failure': back_urls.failure}
        if expires_at:
            body['expires'] = True
            body['expiration_date_to'] = expires_at.isoformat()
        try:
            resp = requests.post(self.PREFERENCE_URL, json=body, timeout=_TIMEOUT,
                                 headers={'Authorization': f'Bearer {access_token}',
                                          'Accept': 'application/json'})
        except requests.RequestException as exc:
            raise PaymentProviderError(f'MP preference falló: {exc}') from exc
        if resp.status_code >= 400:
            raise PaymentProviderError(f'MP preference error {resp.status_code}: {resp.text}')
        data = resp.json()
        return CheckoutSession(redirect_url=data['init_point'],
                               provider_preference_id=str(data['id']))

    def fetch_payment(self, *, access_token, provider_payment_id):
        try:
            resp = requests.get(self.PAYMENT_URL.format(id=provider_payment_id), timeout=_TIMEOUT,
                                headers={'Authorization': f'Bearer {access_token}',
                                         'Accept': 'application/json'})
        except requests.RequestException as exc:
            raise PaymentProviderError(f'MP fetch_payment falló: {exc}') from exc
        if resp.status_code >= 400:
            raise PaymentProviderError(f'MP fetch_payment error {resp.status_code}: {resp.text}')
        d = resp.json()
        return ProviderPayment(
            provider_payment_id=str(d['id']),
            status=_STATUS_MAP.get(d.get('status'), PaymentStatus.PENDING),
            status_detail=d.get('status_detail'),
            amount=Decimal(str(d.get('transaction_amount', '0'))),
            currency=d.get('currency_id', 'CLP'),
            external_reference=d.get('external_reference'),
            collector_id=str(d['collector_id']) if d.get('collector_id') is not None else None,
            raw=d,
        )

    # --- Webhook (Task 12) ---
    def _parse_x_signature(self, header_value):
        # "ts=1720000000,v1=abc123..."
        parts = {}
        for chunk in (header_value or '').split(','):
            if '=' in chunk:
                k, v = chunk.split('=', 1)
                parts[k.strip()] = v.strip()
        return parts.get('ts'), parts.get('v1')

    def verify_webhook(self, *, headers, raw_body):
        h = {k.lower(): v for k, v in dict(headers).items()}
        ts, v1 = self._parse_x_signature(h.get('x-signature'))
        request_id = h.get('x-request-id', '')
        if not ts or not v1:
            return False
        try:
            data_id = str(json.loads(raw_body or b'{}').get('data', {}).get('id', ''))
        except (ValueError, AttributeError):
            data_id = ''
        manifest = f'id:{data_id};request-id:{request_id};ts:{ts};'
        expected = hmac.new(self.webhook_secret.encode(), manifest.encode(),
                            hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, v1)

    def parse_webhook(self, *, headers, raw_body):
        from .base import WebhookEnvelope
        try:
            body = json.loads(raw_body or b'{}')
        except ValueError:
            body = {}
        data = body.get('data') or {}
        pid = data.get('id')
        return WebhookEnvelope(type=body.get('type', ''), action=body.get('action'),
                               provider_payment_id=str(pid) if pid is not None else None)
