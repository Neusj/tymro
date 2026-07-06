"""Implementación concreta de PaymentProvider para MercadoPago (Checkout Pro + OAuth).

Aísla TODO el detalle de MercadoPago (endpoints, formatos, firma). El resto del
sistema no importa este módulo directamente: usa get_payment_provider().

VERIFICAR CONTRA LA DOC VIGENTE DE MP AL IMPLEMENTAR/PROBAR:
- Endpoint exacto de autorización (auth.mercadopago.cl) y si PKCE es obligatorio.
- TTL real de expires_in (se usa el valor devuelto, no se hardcodea).
- Formato del header x-signature y del manifest (ver Task 12).
"""
from decimal import Decimal
from urllib.parse import urlencode

import requests

from .base import (OAuthTokens, PaymentProvider, PaymentProviderError)

_TIMEOUT = 15


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

    # --- Cobro (Task 9) y Webhook (Task 12): stubs por ahora ---
    def create_checkout(self, **kwargs):
        raise NotImplementedError('create_checkout: ver Task 9')

    def fetch_payment(self, **kwargs):
        raise NotImplementedError('fetch_payment: ver Task 9')

    def verify_webhook(self, **kwargs):
        raise NotImplementedError('verify_webhook: ver Task 12')

    def parse_webhook(self, **kwargs):
        raise NotImplementedError('parse_webhook: ver Task 12')
