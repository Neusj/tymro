"""Abstracción de proveedor de pago. El dominio solo conoce esto, nunca MercadoPago."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Mapping


class PaymentStatus(str, Enum):
    PENDING = 'pending'
    IN_PROCESS = 'in_process'
    APPROVED = 'approved'
    REJECTED = 'rejected'
    CANCELLED = 'cancelled'
    REFUNDED = 'refunded'


class PaymentProviderError(Exception):
    """Error al comunicarse con el proveedor de pago."""


@dataclass
class OAuthTokens:
    access_token: str
    refresh_token: str
    expires_in: int
    provider_user_id: str
    public_key: str | None = None
    scope: str | None = None


@dataclass
class CheckoutItem:
    title: str
    quantity: int
    unit_price: Decimal


@dataclass
class BackUrls:
    success: str
    pending: str
    failure: str


@dataclass
class CheckoutSession:
    redirect_url: str
    provider_preference_id: str


@dataclass
class ProviderPayment:
    provider_payment_id: str
    status: PaymentStatus
    status_detail: str | None
    amount: Decimal
    currency: str
    external_reference: str | None
    collector_id: str | None
    raw: dict = field(default_factory=dict)


@dataclass
class WebhookEnvelope:
    type: str
    action: str | None
    provider_payment_id: str | None


class PaymentProvider(ABC):
    name: str = 'base'

    @abstractmethod
    def get_authorization_url(self, *, state: str, redirect_uri: str) -> str: ...

    @abstractmethod
    def exchange_code(self, *, code: str, redirect_uri: str) -> OAuthTokens: ...

    @abstractmethod
    def refresh_tokens(self, *, refresh_token: str) -> OAuthTokens: ...

    @abstractmethod
    def create_checkout(self, *, access_token: str, external_reference: str,
                        items: list[CheckoutItem], payer_email: str | None,
                        back_urls: BackUrls | None, notification_url: str,
                        expires_at) -> CheckoutSession: ...

    @abstractmethod
    def fetch_payment(self, *, access_token: str, provider_payment_id: str) -> ProviderPayment: ...

    @abstractmethod
    def verify_webhook(self, *, headers: Mapping[str, str], raw_body: bytes) -> bool: ...

    @abstractmethod
    def parse_webhook(self, *, headers: Mapping[str, str], raw_body: bytes) -> WebhookEnvelope: ...
