"""Proveedor falso, en memoria, para tests (sin HTTP)."""
from decimal import Decimal

from .base import (BackUrls, CheckoutItem, CheckoutSession, OAuthTokens,
                   PaymentProvider, PaymentStatus, ProviderPayment, WebhookEnvelope)


class FakePaymentProvider(PaymentProvider):
    name = 'fake'

    def __init__(self):
        self._payments = {}   # external_reference -> dict
        self.created_preferences = []

    # --- helpers de test ---
    def queue_payment(self, *, external_reference, status, amount,
                      currency='CLP', collector_id='fake-collector',
                      provider_payment_id='fake-pay'):
        self._payments[external_reference] = dict(
            provider_payment_id=provider_payment_id, status=status, amount=Decimal(amount),
            currency=currency, external_reference=external_reference, collector_id=collector_id,
        )

    # --- interfaz ---
    def get_authorization_url(self, *, state, redirect_uri):
        return f'https://fake.mp/authorize?state={state}&redirect_uri={redirect_uri}'

    def exchange_code(self, *, code, redirect_uri):
        return OAuthTokens(access_token='fake-access', refresh_token='fake-refresh',
                           expires_in=15552000, provider_user_id='fake-collector',
                           public_key='fake-pk', scope='read write offline_access')

    def refresh_tokens(self, *, refresh_token):
        return OAuthTokens(access_token='fake-access-2', refresh_token='fake-refresh-2',
                           expires_in=15552000, provider_user_id='fake-collector',
                           public_key='fake-pk', scope='read write offline_access')

    def create_checkout(self, *, access_token, external_reference, items, payer_email,
                        back_urls, notification_url, expires_at):
        pref_id = f'pref-{external_reference}'
        self.created_preferences.append(dict(external_reference=external_reference,
                                             notification_url=notification_url))
        return CheckoutSession(redirect_url=f'https://fake.mp/checkout/{pref_id}',
                               provider_preference_id=pref_id)

    def fetch_payment(self, *, access_token, provider_payment_id):
        # Busca por el último payment encolado (los tests encolan por external_reference).
        for data in self._payments.values():
            if data['provider_payment_id'] == provider_payment_id:
                return ProviderPayment(status_detail='accredited', raw=dict(data), **{
                    k: data[k] for k in ('provider_payment_id', 'status', 'amount',
                                         'currency', 'external_reference', 'collector_id')})
        raise KeyError(provider_payment_id)

    def verify_webhook(self, *, headers, raw_body):
        return True

    def parse_webhook(self, *, headers, raw_body):
        import json
        body = json.loads(raw_body or b'{}')
        data = body.get('data') or {}
        return WebhookEnvelope(type=body.get('type', 'payment'),
                               action=body.get('action'),
                               provider_payment_id=str(data.get('id')) if data.get('id') else None)
