"""Proveedor falso, en memoria, para tests (sin HTTP).

get_payment_provider() instancia un FakePaymentProvider nuevo en cada llamada
(igual que haría con el proveedor real, que no guarda estado local). Para que
un test pueda `queue_payment(...)` sobre una instancia y luego el código bajo
prueba haga `fetch_payment(...)` sobre otra, el estado de "pagos encolados" se
guarda en el cache de Django en vez de en `self`. El cache ya se limpia antes
y después de cada test (ver `_clear_throttle_cache` en conftest.py), así que
distintos tests no se contaminan entre sí aunque reutilicen el mismo
provider_payment_id.
"""
from decimal import Decimal

from django.core.cache import cache

from .base import (BackUrls, CheckoutItem, CheckoutSession, OAuthTokens,
                   PaymentProvider, PaymentStatus, ProviderPayment, WebhookEnvelope)

_CACHE_KEY = 'fake_payment_provider:payments'
_PREFS_CACHE_KEY = 'fake_payment_provider:preferences'
_REVOKES_CACHE_KEY = 'fake_payment_provider:revokes'


class FakePaymentProvider(PaymentProvider):
    name = 'fake'

    @property
    def _payments(self):
        return cache.get(_CACHE_KEY) or {}

    @property
    def created_preferences(self):
        # En cache: la instancia se descarta por llamada, así el test lee tras el checkout.
        return cache.get(_PREFS_CACHE_KEY) or []

    @property
    def revoked_calls(self):
        # Mismo motivo que `created_preferences`: `disconnect_account` construye su propio
        # provider con get_payment_provider() y lo tira, así que registrar en `self` sería
        # invisible para el test. Lista de dicts {access_token, provider_user_id} en el
        # orden en que se llamó a `revoke`.
        return cache.get(_REVOKES_CACHE_KEY) or []

    # --- helpers de test ---
    def queue_payment(self, *, external_reference, status, amount,
                      currency='CLP', collector_id='fake-collector',
                      provider_payment_id='fake-pay'):
        payments = self._payments
        payments[external_reference] = dict(
            provider_payment_id=provider_payment_id, status=status, amount=Decimal(amount),
            currency=currency, external_reference=external_reference, collector_id=collector_id,
        )
        cache.set(_CACHE_KEY, payments, timeout=None)

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

    def revoke(self, *, access_token, provider_user_id):
        # Registra la llamada (no simula fallos): los tests que necesitan un error
        # monkeypatchean este método. El valor del `access_token` recibido se guarda a
        # propósito: es la única forma de probar CON CUÁL token se revocó, que después del
        # fix del orden ya no sale de la fila (para entonces está vacía) sino del snapshot
        # en memoria que tomó `disconnect_account`, y que puede ser un token REFRESCADO si
        # el guardado estaba vencido. Para probar el ORDEN —vaciado local antes de la
        # revocación— no sirve este registro: hay que leer la fila desde la BD dentro de un
        # `revoke` monkeypatcheado.
        calls = self.revoked_calls
        calls.append({'access_token': access_token, 'provider_user_id': provider_user_id})
        cache.set(_REVOKES_CACHE_KEY, calls, timeout=None)

    def create_checkout(self, *, access_token, external_reference, items, payer_email,
                        back_urls, notification_url, expires_at):
        pref_id = f'pref-{external_reference}'
        prefs = self.created_preferences
        prefs.append(dict(
            external_reference=external_reference,
            notification_url=notification_url,
            back_urls=(dict(success=back_urls.success, pending=back_urls.pending,
                            failure=back_urls.failure) if back_urls else None),
        ))
        cache.set(_PREFS_CACHE_KEY, prefs, timeout=None)
        return CheckoutSession(redirect_url=f'https://fake.mp/checkout/{pref_id}',
                               provider_preference_id=pref_id)

    def fetch_payment(self, *, access_token, provider_payment_id):
        # Busca por el último payment encolado (los tests encolan por external_reference).
        for data in self._payments.values():
            if data['provider_payment_id'] == provider_payment_id:
                # El payload "raw" debe ser JSON-safe, igual que el `resp.json()` del
                # proveedor real (que nunca trae Decimal): no reusar `data` tal cual.
                raw = {**data, 'status': data['status'].value, 'amount': str(data['amount'])}
                return ProviderPayment(status_detail='accredited', raw=raw, **{
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
