import logging
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from core.models import PaymentAccount, PaymentTransaction
from core.services import payments
from core.services.providers.base import (PaymentProviderError, RevocationNotSupported,
                                          RevocationUnverified)
from core.services.providers.fake import FakePaymentProvider


@pytest.fixture(autouse=True)
def _fake(settings):
    settings.PAYMENTS_PROVIDER = 'fake'
    settings.PAYMENTS_ENCRYPTION_KEY = __import__(
        'core.fields', fromlist=['generate_encryption_key']).generate_encryption_key()


def _connect(org):
    """Conecta la cuenta de la org vía el flujo real (update_or_create con tokens)."""
    return payments.connect_callback(code='C', state=payments._sign_state(org.id))


def test_disconnect_requires_gym_admin_or_superadmin(api_client, make_organization, make_user):
    org = make_organization()
    _connect(org)
    student = make_user('s', organization=org, role='student')
    api_client.force_authenticate(user=student)
    resp = api_client.post('/api/payments/disconnect/')
    assert resp.status_code == 403
    # La cuenta sigue intacta: un rol sin permiso no puede tocarla.
    account = PaymentAccount.objects.get(organization=org)
    assert account.status == PaymentAccount.STATUS_CONNECTED


def test_disconnect_empties_tokens_and_sets_status(api_client, make_organization, make_user):
    org = make_organization()
    _connect(org)
    admin = make_user('a', organization=org, role='gym_admin')
    api_client.force_authenticate(user=admin)

    resp = api_client.post('/api/payments/disconnect/')

    assert resp.status_code == 200
    assert resp.data['status'] == 'disconnected'
    account = PaymentAccount.objects.get(organization=org)
    assert account.status == PaymentAccount.STATUS_DISCONNECTED
    assert account.access_token in (None, '')
    assert account.refresh_token in (None, '')
    # No se borra la fila: se conserva para el histórico y la reconexión.
    assert PaymentAccount.objects.filter(organization=org).count() == 1


def test_disconnect_does_not_touch_other_org(api_client, make_organization, make_user):
    # Aislamiento cross-tenant: el gym_admin solo desconecta la cuenta de SU org.
    # El endpoint nunca recibe un id de cuenta: se scopea por request.user.organization_id.
    # Autenticamos a propósito como admin de la SEGUNDA org (pk mayor): si la view olvidara
    # el filtro por organización y resolviera con .first() (pk menor), desconectaría org_a y
    # este test fallaría. Así discrimina scoping-correcto de una implementación sin filtro.
    org_a = make_organization()
    org_b = make_organization()
    _connect(org_a)
    _connect(org_b)
    admin_b = make_user('bb', organization=org_b, role='gym_admin')
    api_client.force_authenticate(user=admin_b)

    resp = api_client.post('/api/payments/disconnect/')

    assert resp.status_code == 200
    # Solo la cuenta del actor (org_b) queda desconectada.
    assert PaymentAccount.objects.get(organization=org_b).status == PaymentAccount.STATUS_DISCONNECTED
    # La cuenta de la otra org (org_a, pk menor) queda intacta.
    account_a = PaymentAccount.objects.get(organization=org_a)
    assert account_a.status == PaymentAccount.STATUS_CONNECTED
    assert account_a.access_token not in (None, '')


def test_reconnect_after_disconnect_sets_connected(api_client, make_organization, make_user):
    org = make_organization()
    _connect(org)
    admin = make_user('a', organization=org, role='gym_admin')
    api_client.force_authenticate(user=admin)
    resp = api_client.post('/api/payments/disconnect/')
    assert resp.status_code == 200
    assert PaymentAccount.objects.get(organization=org).status == PaymentAccount.STATUS_DISCONNECTED

    # Reconexión posterior vía el update_or_create existente del callback OAuth.
    account = _connect(org)

    assert account.status == PaymentAccount.STATUS_CONNECTED
    assert account.access_token not in (None, '')
    assert account.refresh_token not in (None, '')
    assert PaymentAccount.objects.filter(organization=org).count() == 1


def test_webhook_notification_on_disconnected_account_is_ignored(make_organization, make_user):
    # Regresión: si un alumno paga y el gym desconecta antes de que llegue el webhook,
    # process_payment_notification NO debe intentar refrescar el token de una cuenta
    # desconectada (con MP real eso da 400 → PaymentProviderError → HTTP 500 y bucle de
    # reintentos). Debe abortar limpio (return None) sin tocar la cuenta ni la transacción.
    org = make_organization()
    _connect(org)
    student = make_user('st', organization=org, role='student')
    tx = PaymentTransaction.objects.create(
        organization=org, user=student, provider='fake',
        amount=Decimal('10000'), status='pending')

    payments.disconnect_account(PaymentAccount.objects.get(organization=org))

    result = payments.process_payment_notification(tx_id=str(tx.id), provider_payment_id='PAY-1')

    assert result is None
    tx.refresh_from_db()
    assert tx.processed_at is None
    assert tx.status == 'pending'
    # La cuenta NO se reconectó por un intento de refresh oculto.
    account = PaymentAccount.objects.get(organization=org)
    assert account.status == PaymentAccount.STATUS_DISCONNECTED
    assert account.access_token in (None, '')


def test_disconnect_without_account_is_idempotent(api_client, make_organization, make_user):
    # Sin cuenta conectada, desconectar no falla: responde estado desconectado.
    org = make_organization()
    admin = make_user('a', organization=org, role='gym_admin')
    api_client.force_authenticate(user=admin)
    resp = api_client.post('/api/payments/disconnect/')
    assert resp.status_code == 200
    assert resp.data['status'] == 'disconnected'


# --- Revocación en el proveedor (P3.3) ---------------------------------------------------
#
# Antes, desconectar solo vaciaba los tokens LOCALES: el token real seguía vivo del lado del
# proveedor hasta caducar (hasta 180 días) bajo nuestro app_id. Ahora `disconnect_account`
# intenta revocarlo de verdad, pero el intento es BEST-EFFORT: lo que estos tests fijan es
# que la revocación se intente con los datos correctos y, sobre todo, que NADA de lo que
# pase en ese intento impida el vaciado local.
#
# ORDEN (fix de seguridad posterior a P3.3): primero se VACÍA LA FILA, después se revoca.
# El orden inverso —revocar y después vaciar— tenía una ventana real: `_TIMEOUT` de requests
# son 15 s por separado para connect y read (~30 s) contra el `--timeout 30` de los workers
# sync de gunicorn, así que un proveedor que acepta la conexión y no responde hace que el
# arbiter mate al worker con una SEÑAL —no una excepción— y el vaciado local nunca corra:
# fila `connected` con el token guardado, y encima quizás ya muerto del otro lado.

def _assert_locally_wiped(org):
    account = PaymentAccount.objects.get(organization=org)
    assert account.status == PaymentAccount.STATUS_DISCONNECTED
    assert account.access_token in (None, '')
    assert account.refresh_token in (None, '')
    assert account.token_expires_at is None
    return account


def test_disconnect_revokes_at_provider_with_the_stored_token(make_organization):
    org = make_organization()
    account = _connect(org)
    token_before = account.access_token
    user_id_before = account.provider_user_id
    assert token_before   # el flujo real dejó un token: si no, el test no probaría nada

    payments.disconnect_account(account)

    # El provider se descarta por llamada, así que la evidencia vive en el cache (ver fake.py).
    # El token que llega al proveedor NO se lee de la fila (para entonces está vacía) sino del
    # snapshot en memoria que `disconnect_account` tomó antes de vaciarla.
    assert FakePaymentProvider().revoked_calls == [
        {'access_token': token_before, 'provider_user_id': user_id_before}]
    _assert_locally_wiped(org)


def test_disconnect_wipes_locally_BEFORE_calling_revoke(monkeypatch, make_organization):
    """El corazón del fix de orden: cuando corre `revoke`, la fila YA está vacía en la BD.

    No alcanza con mirar el estado final (el orden viejo también terminaba vaciado): hay que
    observar la fila DESDE ADENTRO de la revocación. Por eso el stub la relee de la base —no
    usa la instancia en memoria, que podría estar mutada sin `save()`— y guarda lo que vio.
    Con el orden viejo este test falla: vería `connected` y el token guardado, que es
    exactamente el estado en el que quedaba la fila si gunicorn mataba al worker acá.
    """
    org = make_organization()
    account = _connect(org)
    pk = account.pk
    seen = {}

    def _spy(self, *, access_token, provider_user_id):
        row = PaymentAccount.objects.get(pk=pk)
        seen.update(status=row.status, access_token=row.access_token,
                    refresh_token=row.refresh_token, token_expires_at=row.token_expires_at)

    monkeypatch.setattr(FakePaymentProvider, 'revoke', _spy)

    payments.disconnect_account(account)

    assert seen, 'el stub de revoke no corrió: el test no probaría nada'
    assert seen['status'] == PaymentAccount.STATUS_DISCONNECTED
    assert seen['access_token'] in (None, '')
    assert seen['refresh_token'] in (None, '')
    assert seen['token_expires_at'] is None


@pytest.mark.parametrize('exc', [
    PaymentProviderError('MP revoke error 500: boom'),   # fallo de red/API del proveedor
    RevocationNotSupported('este proveedor no revoca'),  # limitación estructural
    RevocationUnverified('MP revoke no confirmado (401)'),  # 401: resultado desconocido
    TypeError('bug del proveedor'),                      # bug inesperado → fail-safe
], ids=['provider_error', 'not_supported', 'unverified', 'unexpected_bug'])
def test_disconnect_completes_even_if_revoke_fails(monkeypatch, make_organization, exc):
    org = make_organization()
    account = _connect(org)
    token = account.access_token

    called = []

    def _boom(self, *, access_token, provider_user_id):
        called.append(access_token)
        raise exc

    monkeypatch.setattr(FakePaymentProvider, 'revoke', _boom)

    # No escapa NINGUNA excepción: el llamador (la view) responde 200 igual que siempre.
    payments.disconnect_account(account)

    assert called == [token]   # el stub CORRIÓ (si no, el test pasaría sin probar nada)
    _assert_locally_wiped(org)


def test_disconnect_never_logs_the_access_token(monkeypatch, caplog, make_organization):
    org = make_organization()
    account = _connect(org)
    token = account.access_token

    def _boom(self, *, access_token, provider_user_id):
        # Mensaje SIN el token: el contrato es que el proveedor nunca lo pone en la excepción.
        raise PaymentProviderError('MP revoke error 500: {"message":"internal"}')

    monkeypatch.setattr(FakePaymentProvider, 'revoke', _boom)

    with caplog.at_level(logging.WARNING, logger='core.services.payments'):
        payments.disconnect_account(account)

    assert 'Revocación en el proveedor falló' in caplog.text
    # El token es un secreto cifrado en reposo: filtrarlo al log lo deja en texto plano.
    assert token not in caplog.text
    assert str(account.pk) in caplog.text          # sí se loguea con qué fila reconciliar
    _assert_locally_wiped(org)


def test_disconnect_logs_unverified_revocation_as_not_confirmed(monkeypatch, caplog,
                                                                make_organization):
    """Un 401 del proveedor se reporta como NO CONFIRMADO, nunca como éxito.

    Es el caso operativamente peor: la fila ya se vació, así que no queda ningún token con
    el que reintentar, y la autorización puede seguir viva en MP. La única salida es que un
    humano la quite desde el panel, y el log tiene que decirlo con qué fila mirar. Antes de
    este fix el 401 se tragaba como éxito y no se logueaba NADA.
    """
    org = make_organization()
    account = _connect(org)
    token = account.access_token

    def _unverified(self, *, access_token, provider_user_id):
        raise RevocationUnverified('MP revoke no confirmado (401): no se pudo autenticar')

    monkeypatch.setattr(FakePaymentProvider, 'revoke', _unverified)

    with caplog.at_level(logging.WARNING, logger='core.services.payments'):
        payments.disconnect_account(account)

    assert 'NO CONFIRMADA' in caplog.text
    assert 'reconciliar a mano' in caplog.text
    # Distinto del warning de "falló": son dos situaciones distintas y el operador tiene que
    # poder separarlas (una es "no anduvo", la otra es "no sabemos si anduvo").
    assert 'Revocación en el proveedor falló' not in caplog.text
    assert token not in caplog.text
    assert str(account.pk) in caplog.text
    assert str(account.organization_id) in caplog.text
    _assert_locally_wiped(org)


# --- Con qué token se revoca (fix: el guardado puede estar VENCIDO) -----------------------
#
# Los access_token de MP duran hasta 180 días y solo se renuevan cuando alguien cobra. Un
# gimnasio que conectó y nunca vendió llega a la desconexión con el token de la fila VENCIDO
# → 401 → revocación no confirmada → autorización viva en MP. Por eso se refresca primero.
#
# El refresh se hace a mano y NO con `get_valid_access_token`: esa función ESCRIBE en la
# fila (guarda tokens y pone status=CONNECTED), así que después del vaciado resucitaría la
# cuenta a `connected`, y antes del vaciado reintroduciría la llamada de red previa que el
# fix de orden elimina.

def _record_refreshes(monkeypatch):
    """Espía `refresh_tokens` del fake conservando su comportamiento (devuelve fake-access-2)."""
    seen = []
    original = FakePaymentProvider.refresh_tokens

    def _spy(self, *, refresh_token):
        seen.append(refresh_token)
        return original(self, refresh_token=refresh_token)

    monkeypatch.setattr(FakePaymentProvider, 'refresh_tokens', _spy)
    return seen


def test_disconnect_refreshes_an_expired_token_before_revoking(monkeypatch, make_organization):
    org = make_organization()
    account = _connect(org)
    stale_token = account.access_token
    refresh_before = account.refresh_token
    # Token vencido ayer: el escenario del gym que conectó y nunca cobró.
    account.token_expires_at = timezone.now() - timedelta(days=1)
    account.save(update_fields=['token_expires_at'])

    refreshes = _record_refreshes(monkeypatch)

    payments.disconnect_account(account)

    assert refreshes == [refresh_before]
    calls = FakePaymentProvider().revoked_calls
    # Se revoca con el token NUEVO, no con el vencido de la fila.
    assert [c['access_token'] for c in calls] == ['fake-access-2']
    assert stale_token not in [c['access_token'] for c in calls]
    # Y la fila NO se resucitó: el token refrescado vivió solo en memoria. Si esto se hubiera
    # hecho con `get_valid_access_token`, acá habría una cuenta `connected` con tokens nuevos
    # — desconectarse habría terminado reconectando al gimnasio.
    _assert_locally_wiped(org)


def test_disconnect_without_any_usable_token_says_so_instead_of_skipping_in_silence(
        monkeypatch, caplog, make_organization):
    """Sin token utilizable NO se revoca, pero queda dicho en el log.

    La trampa que cierra: se llega acá con `access_token` vacío pero `refresh_token` presente
    —así que pasa la guarda de "no hay nada que revocar"— y encima el refresh falla, con lo
    cual no queda ningún token con el que autenticar el DELETE. Sin este `else` el camino
    salía sin revocar y SIN LOGUEAR: log limpio, autorización posiblemente viva en MP. Es
    exactamente la clase de no-op silencioso que el resto de esta pieza existe para eliminar.
    """
    org = make_organization()
    account = _connect(org)
    # Fila en estado mixto: sin access_token pero con refresh_token.
    account.access_token = None
    account.save(update_fields=['access_token'])

    def _refresh_boom(self, *, refresh_token):
        raise PaymentProviderError('MP caído')

    monkeypatch.setattr(FakePaymentProvider, 'refresh_tokens', _refresh_boom)

    with caplog.at_level(logging.WARNING):
        payments.disconnect_account(account)

    assert FakePaymentProvider().revoked_calls == []      # no había con qué revocar
    assert 'No quedó ningún token con el que revocar' in caplog.text
    assert str(account.pk) in caplog.text                 # con qué fila reconciliar
    # Y el vaciado local, intacto: es lo único que el producto garantiza.
    _assert_locally_wiped(org)


def test_disconnect_does_not_refresh_a_live_token(monkeypatch, make_organization):
    # Token vigente (el flujo real deja 180 días): refrescar sería una llamada de red al
    # pedo —y una rotación de credenciales innecesaria— en el camino normal.
    org = make_organization()
    account = _connect(org)
    live_token = account.access_token
    refreshes = _record_refreshes(monkeypatch)

    payments.disconnect_account(account)

    assert refreshes == []
    assert [c['access_token'] for c in FakePaymentProvider().revoked_calls] == [live_token]
    _assert_locally_wiped(org)


def test_disconnect_falls_back_to_the_raw_token_when_refresh_fails(monkeypatch,
                                                                   make_organization):
    # Si el refresh falla (5xx, timeout) igual se intenta con el token crudo: puede seguir
    # vivo, y un intento con un token quizás bueno es mejor que no intentar. Si tampoco
    # sirve, el 401 se reportará como no confirmado — nunca como éxito.
    org = make_organization()
    account = _connect(org)
    stale_token = account.access_token
    account.token_expires_at = timezone.now() - timedelta(days=1)
    account.save(update_fields=['token_expires_at'])

    def _boom(self, *, refresh_token):
        raise PaymentProviderError('MP token error 500: boom')

    monkeypatch.setattr(FakePaymentProvider, 'refresh_tokens', _boom)

    payments.disconnect_account(account)

    assert [c['access_token'] for c in FakePaymentProvider().revoked_calls] == [stale_token]
    _assert_locally_wiped(org)


def test_disconnect_without_token_does_not_call_revoke(make_organization):
    org = make_organization()
    account = _connect(org)
    payments.disconnect_account(account)
    assert len(FakePaymentProvider().revoked_calls) == 1

    # Segunda desconexión sobre la cuenta ya desconectada (sin tokens): no hay nada que
    # revocar, así que no se toca la red — un 401 esperable solo sería ruido — y no revienta.
    payments.disconnect_account(account)

    assert len(FakePaymentProvider().revoked_calls) == 1
    _assert_locally_wiped(org)


def test_disconnect_without_provider_user_id_skips_revoke_and_says_so(caplog, make_organization):
    """Sin `provider_user_id` no se intenta revocar, y el log lo DICE.

    La trampa que cierra: la URL de revocación interpola el id (`/users/{id}/applications/`),
    así que vacío da `/users//applications/...` → 404 → y la regla "404 = ya estaba revocado"
    lo contaría como ÉXITO. Sería un no-op silencioso con el token vivo y el log limpio.
    `provider_user_id` puede quedar vacío de verdad: `exchange_code` lo llena con
    `str(data.get('user_id', ''))`.
    """
    org = make_organization()
    account = _connect(org)
    account.provider_user_id = ''
    account.save(update_fields=['provider_user_id'])

    with caplog.at_level(logging.WARNING):
        payments.disconnect_account(account)

    assert FakePaymentProvider().revoked_calls == []      # no se tocó la red
    assert 'sin provider_user_id' in caplog.text
    assert str(account.pk) in caplog.text
    # El vaciado local pasa IGUAL: es lo único que el producto garantiza.
    _assert_locally_wiped(org)


def test_disconnect_endpoint_revokes_and_stays_scoped(api_client, make_organization, make_user):
    # Nivel endpoint: la revocación viaja por la view real, y sigue tocando SOLO la cuenta
    # de la organización del actor (el token revocado es el de org_b, nunca el de org_a).
    org_a = make_organization()
    org_b = make_organization()
    _connect(org_a)
    account_b = _connect(org_b)
    token_b = account_b.access_token
    admin_b = make_user('bb', organization=org_b, role='gym_admin')
    api_client.force_authenticate(user=admin_b)

    resp = api_client.post('/api/payments/disconnect/')

    assert resp.status_code == 200
    assert [c['access_token'] for c in FakePaymentProvider().revoked_calls] == [token_b]
    assert PaymentAccount.objects.get(organization=org_a).status == PaymentAccount.STATUS_CONNECTED


def test_disconnect_forbidden_role_does_not_revoke(api_client, make_organization, make_user):
    # Espejo del 403 de arriba, del lado de la revocación: un rol sin permiso no puede
    # provocar la llamada al proveedor (sería un efecto irreversible sin autorización).
    org = make_organization()
    _connect(org)
    student = make_user('s', organization=org, role='student')
    api_client.force_authenticate(user=student)

    resp = api_client.post('/api/payments/disconnect/')

    assert resp.status_code == 403
    assert FakePaymentProvider().revoked_calls == []
