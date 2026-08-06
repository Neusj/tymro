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
                   PaymentProviderError, PaymentStatus, ProviderPayment,
                   RevocationUnverified)

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
    # Revocación de la autorización vendedor↔app. OJO: host de Mercado LIBRE, no de
    # MercadoPago — no es un error de tipeo, ver el bloque de `revoke()`.
    REVOKE_URL = 'https://api.mercadolibre.com/users/{user_id}/applications/{app_id}'

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
        if 'access_token' not in data or 'refresh_token' not in data:
            raise PaymentProviderError(f'MP token response sin access_token/refresh_token: {data}')
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

    # --- Revocación de la autorización (P3.3) ---
    #
    # QUÉ DICE LA DOC, verificado: MercadoPago describe la SEMÁNTICA que necesitamos —"al
    # revocar una autorización entre el vendedor y la aplicación se eliminan todos los
    # tokens y permisos temporales asociados"— pero NO publica ningún endpoint de
    # revocación llamable por el integrador: de OAuth solo documenta `POST /oauth/token`
    # (crear y refrescar). Sin revocación, el token del gimnasio sigue VIVO en MP hasta que
    # caduca solo (hasta 180 días) aunque el gimnasio ya se haya "desconectado".
    #
    # El único endpoint programático documentado vive en el host de Mercado LIBRE, que
    # comparte con MercadoPago el sistema de identidad y de aplicaciones (el `client_id` de
    # MP es el `app_id` de ML, y el `user_id` del vendedor es el mismo en ambos):
    #
    #     DELETE https://api.mercadolibre.com/users/{user_id}/applications/{app_id}
    #     Authorization: Bearer {access_token DEL VENDEDOR}
    #     → {"user_id": "...", "app_id": "...", "msg": "Autorización eliminada"}
    #
    # Invalida el `access_token` Y el `refresh_token` de una sola vez.
    #
    # Por eso esto es explícitamente BEST-EFFORT: lo documenta ML, no MP para el flujo
    # OAuth de split payments, así que puede cambiar o dejar de responder sin aviso. Se usa
    # porque es lo único real que existe, pero NUNCA debe bloquear ni romper la desconexión
    # local (ver `disconnect_account` en services/payments.py, que atrapa todo y sigue).
    #
    # ALTERNATIVA DESCARTADA: inventar un `api.mercadopago.com/oauth/revoke`. No existe:
    # daría 404 en todas las cuentas y —peor— con el criterio de "404 = ya revocado" de
    # abajo convertiría la revocación en un no-op silencioso que parece funcionar.
    def revoke(self, *, access_token, provider_user_id):
        url = self.REVOKE_URL.format(user_id=provider_user_id, app_id=self.client_id)
        try:
            resp = requests.delete(url, timeout=_TIMEOUT,
                                   headers={'Authorization': f'Bearer {access_token}',
                                            'Accept': 'application/json'})
        except requests.RequestException as exc:
            raise PaymentProviderError(f'MP revoke falló: {exc}') from exc
        # 404 es ÉXITO: MP/ML dice que esa autorización ya no existe (el gimnasio la quitó
        # desde su panel, o una desconexión anterior ya la eliminó). Es EVIDENCIA sobre el
        # estado de la autorización, que es justo lo que queremos garantizar.
        if resp.status_code == 404:
            return None
        # 401 NO es éxito, aunque lo parezca. Solo prueba "no pude autenticar con ESTE
        # token", que es también lo que responde un token simplemente CADUCADO: los
        # access_token de MP viven hasta 180 días y solo se refrescan cuando alguien cobra,
        # así que un gimnasio que conectó y nunca vendió llega acá con el token vencido y
        # la autorización PERFECTAMENTE VIVA. Contarlo como éxito dejaba la autorización en
        # pie bajo nuestro `app_id` —con su refresh_token capaz de emitir tokens nuevos—
        # con un log limpio diciendo que todo salió bien: el residuo exacto que esta
        # revocación existe para eliminar. Se levanta una excepción DISTINGUIBLE para que
        # el caller la loguee como "no confirmada" (hay que reconciliar a mano) y no como
        # "falló" ni como "listo". El body NO se incluye: puede traer eco del token.
        if resp.status_code == 401:
            raise RevocationUnverified(
                'MP revoke no confirmado (401): no se pudo autenticar, la autorización '
                'puede seguir viva del lado del proveedor')
        if resp.status_code >= 400:
            # `resp.text` es seguro de incluir: es la respuesta de MP, no un secreto
            # nuestro. El `access_token` NO se incluye jamás — va solo en el header.
            raise PaymentProviderError(f'MP revoke error {resp.status_code}: {resp.text}')
        return None

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
        if not self.webhook_secret:
            return False
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
        if not isinstance(body, dict):
            body = {}
        data = body.get('data')
        if not isinstance(data, dict):
            data = {}
        pid = data.get('id')
        return WebhookEnvelope(type=body.get('type', ''), action=body.get('action'),
                               provider_payment_id=str(pid) if pid is not None else None)
