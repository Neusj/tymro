from decimal import Decimal

import pytest

from core.models import PaymentAccount, PaymentTransaction
from core.services import payments


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
