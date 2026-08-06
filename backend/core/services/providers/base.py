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


class RevocationNotSupported(PaymentProviderError):
    """El proveedor no tiene forma de revocar la autorización desde nuestro lado.

    SUBCLASE de PaymentProviderError a propósito: el idioma del módulo es que el caller
    atrapa el error genérico del proveedor, y un caller que ya lo atrapa debe seguir
    cubriendo este caso sin enumerar excepciones nuevas. Se distingue del error genérico
    solo para el log y los tests: "este proveedor NO PUEDE revocar" es una limitación
    ESTRUCTURAL y permanente (no existe API), no un fallo transitorio que valga la pena
    reintentar más tarde ni alertar como incidente.
    """


class RevocationUnverified(PaymentProviderError):
    """La revocación NO pudo CONFIRMARSE: no se logró autenticar contra el proveedor.

    El caso típico es un 401 al pedir la revocación. Es un resultado DESCONOCIDO, no un
    éxito: "no pude autenticar con este token" NO prueba que la autorización vendedor↔app
    haya muerto. Puede seguir en pie bajo nuestro ``app_id`` con un ``refresh_token`` vivo
    capaz de emitir access_tokens nuevos — exactamente el residuo que la revocación existe
    para eliminar. Y como la limpieza local ya borró los tokens guardados, esa fue además
    la ÚLTIMA oportunidad de revocar sin intervención manual: hay que reconciliar a mano
    desde el panel del proveedor.

    HISTORIA: hasta este fix el 401 se contaba como ÉXITO ("el token ya está muerto, el
    objetivo está cumplido"). Era una conclusión inválida — confunde "el token no sirve
    para autenticar" (que un token simplemente CADUCADO también produce) con "la
    autorización ya no existe" — y encima silenciosa: dejaba un log limpio sobre una
    desconexión incompleta.

    SUBCLASE de PaymentProviderError por el mismo motivo que ``RevocationNotSupported``:
    un caller que ya atrapa el error genérico sigue cubierto. Se distingue para que el
    caller pueda loguearlo como "no confirmado" y no como "falló".
    """


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
    def revoke(self, *, access_token: str, provider_user_id: str) -> None:
        """Invalida EN EL PROVEEDOR los tokens de esta cuenta (fin de la autorización).

        CONTRATO:
        - Devuelve ``None`` SOLO con EVIDENCIA de que la autorización ya no existe del
          lado del proveedor. Eso incluye "no había nada que revocar" (el proveedor
          responde explícitamente que esa autorización no existe, p.ej. un 404): lo que
          importa es el ESTADO resultante, no haber sido quien lo produjo.
        - Levanta ``RevocationUnverified`` cuando no se pudo AUTENTICAR y por lo tanto el
          resultado es desconocido (p.ej. 401). Ojo: eso NO es evidencia de revocación —
          un token meramente caducado da el mismo 401 mientras la autorización sigue viva.
        - Levanta ``RevocationNotSupported`` si el proveedor no expone revocación.
        - Levanta ``PaymentProviderError`` ante fallo de red o error de la API.

        EL CALLER DEBE SER A PRUEBA DE FALLOS: la limpieza local (marcar la cuenta
        desconectada y vaciar los tokens guardados) NO puede depender de que esto
        funcione. Un proveedor caído —o un bug en esta llamada— nunca puede dejar la fila
        en ``connected`` con un token vivo guardado; ese sería el peor de los dos mundos.
        Por eso el caller hace la limpieza local ANTES de llamar acá y le pasa los valores
        que leyó en variables locales (ver ``disconnect_account``).

        El ``access_token`` es un SECRETO: va únicamente en el header de autorización de
        la request. Nunca en la URL, ni en un log, ni en el mensaje de una excepción.
        """

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
