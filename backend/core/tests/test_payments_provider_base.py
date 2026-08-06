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


def test_fake_revoke_is_visible_from_another_instance():
    # `revoke` se registra en el cache, no en `self`, porque el código de producción
    # (`disconnect_account`) construye su propio provider con get_payment_provider() y lo
    # descarta: si el registro viviera en la instancia, ningún test podría verlo.
    FakePaymentProvider().revoke(access_token='AT', provider_user_id='SELLER-1')

    assert FakePaymentProvider().revoked_calls == [
        {'access_token': 'AT', 'provider_user_id': 'SELLER-1'}]


def test_revocation_not_supported_is_a_provider_error():
    # Subclase a propósito: un caller que ya atrapa PaymentProviderError sigue cubierto.
    from core.services.providers.base import PaymentProviderError, RevocationNotSupported
    assert issubclass(RevocationNotSupported, PaymentProviderError)


def test_revocation_unverified_is_a_distinguishable_provider_error():
    # Mismo criterio: subclase para que el caller genérico siga cubierto, pero clase PROPIA
    # para que `disconnect_account` pueda loguear "no confirmada" (hay que reconciliar a
    # mano en el panel de MP) en vez de "falló" — y, sobre todo, para que deje de contarse
    # como éxito, que es lo que hacía el 401 antes de este fix.
    from core.services.providers.base import (PaymentProviderError, RevocationNotSupported,
                                              RevocationUnverified)
    assert issubclass(RevocationUnverified, PaymentProviderError)
    assert not issubclass(RevocationUnverified, RevocationNotSupported)
    assert not issubclass(RevocationNotSupported, RevocationUnverified)
