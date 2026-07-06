from datetime import timedelta

import pytest
from django.utils import timezone

from core.models import PaymentAccount
from core.services import payments


@pytest.fixture(autouse=True)
def _fake_provider(settings):
    settings.PAYMENTS_PROVIDER = 'fake'
    settings.PAYMENTS_ENCRYPTION_KEY = __import__(
        'core.fields', fromlist=['generate_encryption_key']).generate_encryption_key()


def test_build_connect_url_contains_signed_state(make_organization):
    org = make_organization()
    url = payments.build_connect_url(organization=org)
    assert 'state=' in url and 'redirect_uri=' in url


def test_connect_callback_creates_account(make_organization):
    org = make_organization()
    state = payments._sign_state(org.id)          # helper interno para el test
    acc = payments.connect_callback(code='CODE', state=state)
    assert acc.organization_id == org.id
    assert acc.provider == 'fake'
    assert acc.access_token == 'fake-access'       # descifrado
    assert acc.status == PaymentAccount.STATUS_CONNECTED
    assert acc.provider_user_id == 'fake-collector'
    assert acc.token_expires_at is not None


def test_connect_callback_is_idempotent_upsert(make_organization):
    org = make_organization()
    state = payments._sign_state(org.id)
    a1 = payments.connect_callback(code='C', state=state)
    a2 = payments.connect_callback(code='C', state=payments._sign_state(org.id))
    assert a1.pk == a2.pk                           # misma cuenta (upsert por org+provider)
    assert PaymentAccount.objects.filter(organization=org).count() == 1


def test_connect_callback_bad_state_raises(make_organization):
    with pytest.raises(payments.InvalidState):
        payments.connect_callback(code='C', state='garbage')


def test_get_valid_access_token_refreshes_when_expiring(make_organization):
    org = make_organization()
    acc = payments.connect_callback(code='C', state=payments._sign_state(org.id))
    acc.token_expires_at = timezone.now() - timedelta(hours=1)   # vencido
    acc.save(update_fields=['token_expires_at'])
    token = payments.get_valid_access_token(account=acc)
    acc.refresh_from_db()
    assert token == 'fake-access-2'                 # vino del refresh
    assert acc.refresh_token == 'fake-refresh-2'
