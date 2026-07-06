from django.conf import settings

from .base import PaymentProvider, PaymentProviderError, PaymentStatus  # re-export
from .fake import FakePaymentProvider


def get_payment_provider(name: str | None = None) -> PaymentProvider:
    name = name or getattr(settings, 'PAYMENTS_PROVIDER', 'mercadopago')
    if name == 'mercadopago':
        from .mercadopago import MercadoPagoProvider
        return MercadoPagoProvider(
            client_id=settings.MP_CLIENT_ID,
            client_secret=settings.MP_CLIENT_SECRET,
            webhook_secret=settings.MP_WEBHOOK_SECRET,
        )
    if name == 'fake':
        return FakePaymentProvider()
    raise ValueError(f'Proveedor de pago desconocido: {name}')
