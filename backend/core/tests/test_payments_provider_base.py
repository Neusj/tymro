from decimal import Decimal

import pytest

from core.services.providers import get_payment_provider
from core.services.providers.base import PaymentProvider, PaymentStatus
from core.services.providers.fake import FakePaymentProvider


def test_factory_returns_fake_when_configured(settings):
    settings.PAYMENTS_PROVIDER = 'fake'
    provider = get_payment_provider()
    assert isinstance(provider, FakePaymentProvider)
    assert isinstance(provider, PaymentProvider)
    assert provider.name == 'fake'


def test_factory_unknown_name_raises():
    with pytest.raises(ValueError):
        get_payment_provider('nope')


def test_fake_exchange_and_checkout_and_fetch():
    p = FakePaymentProvider()
    tokens = p.exchange_code(code='c', redirect_uri='http://x/cb')
    assert tokens.access_token and tokens.refresh_token and tokens.provider_user_id

    session = p.create_checkout(
        access_token='t', external_reference='ext-1',
        items=[], payer_email='a@b.cl',
        back_urls=None, notification_url='http://x/wh', expires_at=None,
    )
    assert session.redirect_url and session.provider_preference_id

    p.queue_payment(external_reference='ext-1', status=PaymentStatus.APPROVED,
                    amount=Decimal('10000'), provider_payment_id='pay-1')
    payment = p.fetch_payment(access_token='t', provider_payment_id='pay-1')
    assert payment.status == PaymentStatus.APPROVED
    assert payment.external_reference == 'ext-1'
    assert payment.amount == Decimal('10000')
