# Pagos alumno→gym con MercadoPago — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** El alumno paga/renueva su plan (y paga su matrícula pendiente) online con MercadoPago; el pago aprobado activa/renueva su `StudentPlan` de forma idempotente. El dinero va directo a la cuenta MercadoPago de cada gym (OAuth por organización); TYMRO nunca toca fondos.

**Architecture:** Una abstracción `PaymentProvider` (ABC + DTOs) aísla MercadoPago del dominio. La lógica vive en `core/services/` (convención del repo); MercadoPago habla HTTP solo dentro de `core/services/providers/mercadopago.py`. Se agregan dos modelos (`PaymentAccount`, `PaymentTransaction`) + una bitácora opcional (`WebhookEvent`), todos con `organization_id` para aislamiento multitenant. Checkout Pro (redirect). El webhook es la ÚNICA vía de activación, idempotente por `processed_at` + `select_for_update` + unique constraint. Un command de reconciliación cierra los huecos si un webhook se pierde.

**Tech Stack:** Django 5.0.6, DRF 3.15.1, Python 3.13, PostgreSQL (prod) / SQLite (dev), `requests` (HTTP a MP), `cryptography`/Fernet (cifrado de tokens en reposo), pytest + `responses` (mock HTTP en tests).

## Global Constraints

- **Multitenant: SIEMPRE filtrar por `organization_id`.** No hay red central; cada queryset filtra por `request.user.organization_id` y cada `perform_*` fuerza la organización del actor. El webhook y el callback OAuth resuelven la org por dato firmado/propio (`state` / `?tx=`), NUNCA por el Host. (Regla #1 de `backend/CLAUDE.md`.)
- **El backend es la única frontera de seguridad.** Toda restricción de rol tiene su check en el backend (permission class o `_is_*` → 403/404).
- **Lógica de negocio en `core/services/`**, no en las views.
- **Usar el modelo `Plan`, NO `MembershipPlan`.**
- **Moneda:** CLP, sin decimales. `Plan.price` es `FloatField` (deuda existente): convertir a `Decimal` y redondear a **entero CLP** en la frontera. NO modificar `Plan.price`.
- **Locale/TZ:** `es-cl`, `America/Santiago`, `USE_TZ=True`. Fechas de negocio con `timezone.localdate()`, timestamps con `timezone.now()`.
- **Secrets solo por env var** (`os.getenv`, patrón del repo). Si falta un secret requerido en prod (`DEBUG=False`), la app **falla al arrancar** (mismo criterio que `SECRET_KEY`).
- **Nunca `Math.random`/hora en migraciones ni en firmas.** `state` y tokens firmados con `django.core.signing` (patrón del repo para QR).
- Tests con `pytest` (`cd backend && python -m pytest`), config en `pytest.ini` (settings `tymro.settings_test`, testpaths `core/tests`). Fixtures globales en `backend/conftest.py`: `api_client`, `make_organization`, `make_user`.

## Refinamientos respecto al documento de diseño (decisiones de implementación)

1. **Un propósito por transacción en el piloto.** Cada `PaymentTransaction` cubre **plan** _o_ **matrícula**, no ambos en una sola preference (el `Plan` no tiene `enrollment_fee`; la matrícula vive por-`StudentPlan`, así que un checkout combinado "plan nuevo + su matrícula" no tiene monto de matrícula conocido al momento de comprar). El modelo guarda `plan_amount` y `enrollment_fee_amount` por separado para habilitar el combinado en fase 2. Flujos del piloto:
   - `plan_id` → cobra `Plan.price` (compra/renovación).
   - `target_student_plan_id` → cobra la matrícula pendiente de un `StudentPlan` existente (`enrollment_fee > 0` y no pagada).
2. **`notification_url` lleva `?tx=<transaction_id>`.** MP conserva los query params de la `notification_url` que fijamos en la preference. El webhook lee `tx` para resolver la org (y su access_token) **antes** de consultar el pago a MP, resolviendo el problema "no sé de qué org es este pago". Se cruza `external_reference == tx.id` y `collector_id == cuenta del gym` como defensa.
3. **`activate_student_plan(...)`** se extrae a `core/services/plans.py` y lo reusan tanto la acción `assign` (admin, manual) como el webhook (automático). Una sola fuente de verdad para "activar plan".

---

## File Structure

**Nuevos:**
- `backend/core/fields.py` — `EncryptedTextField` (cifrado Fernet en reposo).
- `backend/core/services/providers/__init__.py` — `get_payment_provider(name)` (factory).
- `backend/core/services/providers/base.py` — `PaymentProvider` (ABC), DTOs, enum `PaymentStatus`, `PaymentProviderError`.
- `backend/core/services/providers/mercadopago.py` — implementación concreta MercadoPago.
- `backend/core/services/providers/fake.py` — `FakePaymentProvider` (tests).
- `backend/core/services/plans.py` — `activate_student_plan(...)`.
- `backend/core/services/payments.py` — orquestación: `create_checkout`, `connect_url`, `connect_callback`, `get_valid_access_token`, `process_payment_notification`, `reconcile_transaction`.
- `backend/core/views_payments.py` — APIViews: connect, callback, account, checkout, status, webhook (split justificado: `views.py` ya tiene ~2800 líneas).
- `backend/core/management/commands/reconcile_payments.py`
- `backend/core/management/commands/refresh_payment_tokens.py`
- `backend/core/tests/test_payments_*.py` — suites por tarea.

**Modificados:**
- `backend/requirements.txt` (+`requests`, +`cryptography`), `backend/requirements-dev.txt` (+`responses`).
- `backend/tymro/settings.py` (vars de pagos + fail-fast).
- `backend/core/models.py` (+`PaymentAccount`, +`PaymentTransaction`, +`WebhookEvent`).
- `backend/core/migrations/0025_payments.py` (generada).
- `backend/core/views.py` (refactor de `assign` para usar `activate_student_plan`).
- `backend/core/serializers.py` (+serializers de request de pagos).
- `backend/core/urls.py` (+rutas de pagos).
- `backend/core/middleware.py` (+prefijos de pagos al allowlist, defensivo).

---

## Task 1: Dependencias y settings de pagos

**Files:**
- Modify: `backend/requirements.txt`
- Modify: `backend/requirements-dev.txt`
- Modify: `backend/tymro/settings.py`
- Test: `backend/core/tests/test_payments_settings.py`

**Interfaces:**
- Produces: settings `PAYMENTS_PROVIDER`, `PAYMENTS_ENCRYPTION_KEY`, `PAYMENTS_APEX_BASE_URL`, `MP_CLIENT_ID`, `MP_CLIENT_SECRET`, `MP_WEBHOOK_SECRET`, `MP_OAUTH_REDIRECT_URI`. Constante `PAYMENTS_REQUIRED_IN_PROD` (lista de settings que no pueden faltar en prod).

- [ ] **Step 1: Añadir dependencias**

En `backend/requirements.txt` agregar (una por línea, respetando el estilo sin versiones pinneadas del archivo, o pinneando si el resto lo está — seguir lo existente):

```
requests
cryptography
```

En `backend/requirements-dev.txt` agregar:

```
responses
```

- [ ] **Step 2: Instalar**

Run: `cd backend && pip install -r requirements.txt -r requirements-dev.txt`
Expected: instala `requests`, `cryptography`, `responses` sin errores.

- [ ] **Step 3: Escribir el test de settings**

Crear `backend/core/tests/test_payments_settings.py`:

```python
from django.conf import settings


def test_payment_settings_exist_with_defaults():
    assert hasattr(settings, 'PAYMENTS_PROVIDER')
    assert settings.PAYMENTS_PROVIDER == 'mercadopago'
    # En test/dev no se exige el resto, pero los atributos deben existir (default '').
    for name in ('PAYMENTS_ENCRYPTION_KEY', 'MP_CLIENT_ID', 'MP_CLIENT_SECRET',
                 'MP_WEBHOOK_SECRET', 'MP_OAUTH_REDIRECT_URI', 'PAYMENTS_APEX_BASE_URL'):
        assert hasattr(settings, name)
```

- [ ] **Step 4: Correr el test (debe fallar)**

Run: `cd backend && python -m pytest core/tests/test_payments_settings.py -v`
Expected: FAIL (AttributeError: settings sin `PAYMENTS_PROVIDER`).

- [ ] **Step 5: Añadir settings**

En `backend/tymro/settings.py`, cerca del resto de config de entorno, agregar:

```python
# --- Pagos (MercadoPago) ---
PAYMENTS_PROVIDER = os.getenv('PAYMENTS_PROVIDER', 'mercadopago')
PAYMENTS_ENCRYPTION_KEY = os.getenv('PAYMENTS_ENCRYPTION_KEY', '')
# Base pública en el APEX (sin subdominio) para callback OAuth y webhook.
PAYMENTS_APEX_BASE_URL = os.getenv('PAYMENTS_APEX_BASE_URL', 'http://localhost:8000')
MP_CLIENT_ID = os.getenv('MP_CLIENT_ID', '')
MP_CLIENT_SECRET = os.getenv('MP_CLIENT_SECRET', '')
MP_WEBHOOK_SECRET = os.getenv('MP_WEBHOOK_SECRET', '')
MP_OAUTH_REDIRECT_URI = os.getenv(
    'MP_OAUTH_REDIRECT_URI',
    f'{PAYMENTS_APEX_BASE_URL}/api/payments/oauth/callback/',
)
```

Y en el bloque de hardening de producción (donde hoy se valida `SECRET_KEY` con `DEBUG=False`), agregar el fail-fast:

```python
if not DEBUG:
    _missing_payment = [
        name for name in (
            'PAYMENTS_ENCRYPTION_KEY', 'MP_CLIENT_ID', 'MP_CLIENT_SECRET', 'MP_WEBHOOK_SECRET',
        )
        if not globals().get(name)
    ]
    if _missing_payment:
        raise ImproperlyConfigured(
            f'Faltan variables de entorno de pagos en producción: {", ".join(_missing_payment)}'
        )
```

(Asegurar el import `from django.core.exceptions import ImproperlyConfigured` si no está ya presente.)

- [ ] **Step 6: Correr el test (debe pasar)**

Run: `cd backend && python -m pytest core/tests/test_payments_settings.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/requirements.txt backend/requirements-dev.txt backend/tymro/settings.py backend/core/tests/test_payments_settings.py
git commit -m "feat(payments): dependencias y settings de MercadoPago con fail-fast en prod"
```

---

## Task 2: Campo cifrado en reposo (`EncryptedTextField`)

**Files:**
- Create: `backend/core/fields.py`
- Test: `backend/core/tests/test_payments_fields.py`

**Interfaces:**
- Produces: `EncryptedTextField` (subclase de `models.TextField`) que cifra en `get_prep_value` y descifra en `from_db_value`, usando `settings.PAYMENTS_ENCRYPTION_KEY` (soporta rotación con múltiples claves separadas por coma vía `MultiFernet`). Helper `generate_encryption_key() -> str`.

- [ ] **Step 1: Escribir el test**

Crear `backend/core/tests/test_payments_fields.py`:

```python
import pytest
from django.db import connection

from core.fields import EncryptedTextField, generate_encryption_key


@pytest.fixture
def enc_key(settings):
    key = generate_encryption_key()
    settings.PAYMENTS_ENCRYPTION_KEY = key
    return key


def test_generate_key_is_usable():
    key = generate_encryption_key()
    assert isinstance(key, str) and len(key) > 0


def test_roundtrip_encrypt_decrypt(enc_key):
    field = EncryptedTextField()
    stored = field.get_prep_value('super-secret-token')
    assert stored != 'super-secret-token'          # cifrado en DB
    back = field.from_db_value(stored, None, connection)
    assert back == 'super-secret-token'            # descifrado al leer


def test_none_passes_through(enc_key):
    field = EncryptedTextField()
    assert field.get_prep_value(None) is None
    assert field.from_db_value(None, None, connection) is None


def test_supports_key_rotation(settings):
    old = generate_encryption_key()
    new = generate_encryption_key()
    settings.PAYMENTS_ENCRYPTION_KEY = old
    stored = EncryptedTextField().get_prep_value('x')
    # Rotamos: nueva clave primero, vieja como secundaria.
    settings.PAYMENTS_ENCRYPTION_KEY = f'{new},{old}'
    assert EncryptedTextField().from_db_value(stored, None, connection) == 'x'
```

- [ ] **Step 2: Correr el test (debe fallar)**

Run: `cd backend && python -m pytest core/tests/test_payments_fields.py -v`
Expected: FAIL (ModuleNotFoundError: `core.fields`).

- [ ] **Step 3: Implementar el campo**

Crear `backend/core/fields.py`:

```python
"""Campo de modelo cifrado en reposo con Fernet (para tokens OAuth de pagos).

La clave viene de settings.PAYMENTS_ENCRYPTION_KEY. Soporta rotación: varias
claves separadas por coma; la primera cifra, todas descifran (MultiFernet).
"""
from cryptography.fernet import Fernet, MultiFernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import models


def generate_encryption_key() -> str:
    return Fernet.generate_key().decode()


def _fernet() -> MultiFernet:
    raw = (settings.PAYMENTS_ENCRYPTION_KEY or '').strip()
    if not raw:
        raise ImproperlyConfigured('PAYMENTS_ENCRYPTION_KEY no configurada.')
    keys = [Fernet(k.strip().encode()) for k in raw.split(',') if k.strip()]
    if not keys:
        raise ImproperlyConfigured('PAYMENTS_ENCRYPTION_KEY vacía o inválida.')
    return MultiFernet(keys)


class EncryptedTextField(models.TextField):
    """TextField cuyo valor se cifra antes de guardarse y se descifra al leerse."""

    def get_prep_value(self, value):
        if value is None:
            return None
        token = _fernet().encrypt(str(value).encode())
        return token.decode()

    def from_db_value(self, value, expression, connection):
        if value is None:
            return None
        return _fernet().decrypt(value.encode()).decode()
```

- [ ] **Step 4: Correr el test (debe pasar)**

Run: `cd backend && python -m pytest core/tests/test_payments_fields.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/core/fields.py backend/core/tests/test_payments_fields.py
git commit -m "feat(payments): EncryptedTextField (Fernet) con rotación de clave"
```

---

## Task 3: Abstracción de proveedor (base + fake + factory)

**Files:**
- Create: `backend/core/services/providers/__init__.py`
- Create: `backend/core/services/providers/base.py`
- Create: `backend/core/services/providers/fake.py`
- Test: `backend/core/tests/test_payments_provider_base.py`

**Interfaces:**
- Produces:
  - `PaymentStatus` (str Enum): `PENDING, IN_PROCESS, APPROVED, REJECTED, CANCELLED, REFUNDED`.
  - DTOs (dataclasses): `OAuthTokens(access_token, refresh_token, expires_in:int, provider_user_id:str, public_key:str|None, scope:str|None)`; `CheckoutItem(title:str, quantity:int, unit_price:Decimal)`; `BackUrls(success:str, pending:str, failure:str)`; `CheckoutSession(redirect_url:str, provider_preference_id:str)`; `ProviderPayment(provider_payment_id:str, status:PaymentStatus, status_detail:str|None, amount:Decimal, currency:str, external_reference:str|None, collector_id:str|None, raw:dict)`; `WebhookEnvelope(type:str, action:str|None, provider_payment_id:str|None)`.
  - `PaymentProviderError(Exception)`.
  - `PaymentProvider` (ABC) con: `get_authorization_url(*, state, redirect_uri) -> str`; `exchange_code(*, code, redirect_uri) -> OAuthTokens`; `refresh_tokens(*, refresh_token) -> OAuthTokens`; `create_checkout(*, access_token, external_reference, items, payer_email, back_urls, notification_url, expires_at) -> CheckoutSession`; `fetch_payment(*, access_token, provider_payment_id) -> ProviderPayment`; `verify_webhook(*, headers, raw_body) -> bool`; `parse_webhook(*, headers, raw_body) -> WebhookEnvelope`. Atributo `name: str`.
  - `FakePaymentProvider(PaymentProvider)` con estado en memoria y helpers para tests: `queue_payment(external_reference, status, amount, currency='CLP', collector_id='fake-collector')`.
  - `get_payment_provider(name=None) -> PaymentProvider` (lee `settings.PAYMENTS_PROVIDER` si `name` es None; soporta `'fake'`).

- [ ] **Step 1: Escribir el test**

Crear `backend/core/tests/test_payments_provider_base.py`:

```python
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
```

- [ ] **Step 2: Correr el test (debe fallar)**

Run: `cd backend && python -m pytest core/tests/test_payments_provider_base.py -v`
Expected: FAIL (ModuleNotFoundError `core.services.providers`).

- [ ] **Step 3: Implementar `base.py`**

Crear `backend/core/services/providers/base.py`:

```python
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
```

- [ ] **Step 4: Implementar `fake.py`**

Crear `backend/core/services/providers/fake.py`:

```python
"""Proveedor falso, en memoria, para tests (sin HTTP)."""
from decimal import Decimal

from .base import (BackUrls, CheckoutItem, CheckoutSession, OAuthTokens,
                   PaymentProvider, PaymentStatus, ProviderPayment, WebhookEnvelope)


class FakePaymentProvider(PaymentProvider):
    name = 'fake'

    def __init__(self):
        self._payments = {}   # external_reference -> dict
        self.created_preferences = []

    # --- helpers de test ---
    def queue_payment(self, *, external_reference, status, amount,
                      currency='CLP', collector_id='fake-collector',
                      provider_payment_id='fake-pay'):
        self._payments[external_reference] = dict(
            provider_payment_id=provider_payment_id, status=status, amount=Decimal(amount),
            currency=currency, external_reference=external_reference, collector_id=collector_id,
        )

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

    def create_checkout(self, *, access_token, external_reference, items, payer_email,
                        back_urls, notification_url, expires_at):
        pref_id = f'pref-{external_reference}'
        self.created_preferences.append(dict(external_reference=external_reference,
                                             notification_url=notification_url))
        return CheckoutSession(redirect_url=f'https://fake.mp/checkout/{pref_id}',
                               provider_preference_id=pref_id)

    def fetch_payment(self, *, access_token, provider_payment_id):
        # Busca por el último payment encolado (los tests encolan por external_reference).
        for data in self._payments.values():
            if data['provider_payment_id'] == provider_payment_id:
                return ProviderPayment(status_detail='accredited', raw=dict(data), **{
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
```

- [ ] **Step 5: Implementar el factory `__init__.py`**

Crear `backend/core/services/providers/__init__.py`:

```python
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
```

(El import de `MercadoPagoProvider` es perezoso para que este módulo no falle antes de la Task 5.)

- [ ] **Step 6: Correr el test (debe pasar)**

Run: `cd backend && python -m pytest core/tests/test_payments_provider_base.py -v`
Expected: PASS (4 tests). (`test_factory_unknown_name_raises` no toca mercadopago.)

- [ ] **Step 7: Commit**

```bash
git add backend/core/services/providers/ backend/core/tests/test_payments_provider_base.py
git commit -m "feat(payments): abstracción PaymentProvider + DTOs + FakePaymentProvider + factory"
```

---

## Task 4: Modelos `PaymentAccount`, `PaymentTransaction`, `WebhookEvent` + migración

**Files:**
- Modify: `backend/core/models.py` (append al final)
- Create: `backend/core/migrations/0025_payments.py` (generada por `makemigrations`)
- Test: `backend/core/tests/test_payments_models.py`

**Interfaces:**
- Consumes: `EncryptedTextField` (Task 2), `Organization`/`Plan`/`StudentPlan` existentes, `PaymentStatus` (Task 3, para las choices).
- Produces:
  - `PaymentAccount(organization, provider, provider_user_id, access_token[enc], refresh_token[enc], public_key, scope, token_expires_at, status, is_sandbox, connected_at)`; `unique_together (organization, provider)`; `STATUS_CONNECTED='connected'`, `STATUS_DISCONNECTED='disconnected'`.
  - `PaymentTransaction(id:UUID pk, organization, user, provider, provider_preference_id, provider_payment_id, status, status_detail, currency, plan, plan_amount, enrollment_fee_amount, amount, target_student_plan, student_plan, processed_at, metadata:JSON, raw_provider_payload:JSON)`; unique constraint condicional en `(provider, provider_payment_id)`; índices `(organization, status)`, `(user, status)`.
  - `WebhookEvent(provider, provider_payment_id, transaction, raw_body, headers:JSON, processed_ok:bool, note)`.

- [ ] **Step 1: Escribir el test**

Crear `backend/core/tests/test_payments_models.py`:

```python
import uuid
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction as db_tx

from core.models import PaymentAccount, PaymentTransaction


@pytest.fixture
def enc_key(settings):
    from core.fields import generate_encryption_key
    settings.PAYMENTS_ENCRYPTION_KEY = generate_encryption_key()


def test_payment_account_tokens_encrypted_at_rest(db, enc_key, make_organization):
    org = make_organization()
    acc = PaymentAccount.objects.create(
        organization=org, provider='mercadopago', provider_user_id='u1',
        access_token='AT', refresh_token='RT', status=PaymentAccount.STATUS_CONNECTED,
    )
    acc.refresh_from_db()
    assert acc.access_token == 'AT'          # se descifra al leer
    from django.db import connection
    with connection.cursor() as cur:
        cur.execute('SELECT access_token FROM core_paymentaccount WHERE id=%s', [acc.id])
        raw = cur.fetchone()[0]
    assert raw != 'AT'                        # cifrado en DB


def test_payment_account_unique_per_org_provider(db, enc_key, make_organization):
    org = make_organization()
    PaymentAccount.objects.create(organization=org, provider='mercadopago',
                                  provider_user_id='u1', access_token='a', refresh_token='b')
    with pytest.raises(IntegrityError):
        PaymentAccount.objects.create(organization=org, provider='mercadopago',
                                      provider_user_id='u2', access_token='c', refresh_token='d')


def test_transaction_uuid_pk_and_defaults(db, make_organization, make_user):
    org = make_organization()
    student = make_user('stu', organization=org, role='student')
    tx = PaymentTransaction.objects.create(
        organization=org, user=student, provider='mercadopago',
        amount=Decimal('10000'), plan_amount=Decimal('10000'), enrollment_fee_amount=Decimal('0'),
    )
    assert isinstance(tx.id, uuid.UUID)
    assert tx.status == 'pending'
    assert tx.currency == 'CLP'
    assert tx.processed_at is None


def test_unique_provider_payment_id(db, make_organization, make_user):
    org = make_organization()
    student = make_user('stu2', organization=org, role='student')
    common = dict(organization=org, user=student, provider='mercadopago',
                  amount=Decimal('1'), plan_amount=Decimal('1'), enrollment_fee_amount=Decimal('0'))
    PaymentTransaction.objects.create(provider_payment_id='PAY1', **common)
    with pytest.raises(IntegrityError):
        with db_tx.atomic():
            PaymentTransaction.objects.create(provider_payment_id='PAY1', **common)
    # Múltiples NULL sí se permiten (constraint condicional):
    with db_tx.atomic():
        PaymentTransaction.objects.create(provider_payment_id=None, **common)
        PaymentTransaction.objects.create(provider_payment_id=None, **common)
```

- [ ] **Step 2: Correr el test (debe fallar)**

Run: `cd backend && python -m pytest core/tests/test_payments_models.py -v`
Expected: FAIL (ImportError: `PaymentAccount`).

- [ ] **Step 3: Añadir modelos**

En `backend/core/models.py` (al final; asegurar imports `import uuid` y `from .fields import EncryptedTextField` arriba; `Q` desde `django.db.models`):

```python
class PaymentAccount(TimestampedModel):
    STATUS_CONNECTED = 'connected'
    STATUS_DISCONNECTED = 'disconnected'
    STATUS_CHOICES = [(STATUS_CONNECTED, 'Conectada'), (STATUS_DISCONNECTED, 'Desconectada')]

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='payment_accounts')
    provider = models.CharField(max_length=30, default='mercadopago')
    provider_user_id = models.CharField(max_length=64)
    access_token = EncryptedTextField()
    refresh_token = EncryptedTextField()
    public_key = models.CharField(max_length=255, null=True, blank=True)
    scope = models.CharField(max_length=255, null=True, blank=True)
    token_expires_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_CONNECTED)
    is_sandbox = models.BooleanField(default=False)
    connected_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [('organization', 'provider')]

    def __str__(self):
        return f'{self.organization} · {self.provider} ({self.status})'


class PaymentTransaction(TimestampedModel):
    STATUS_CHOICES = [(s.value, s.value) for s in __import__('core.services.providers.base',
                      fromlist=['PaymentStatus']).PaymentStatus]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='payment_transactions')
    user = models.ForeignKey('accounts.CustomUser', on_delete=models.CASCADE, related_name='payment_transactions')
    provider = models.CharField(max_length=30, default='mercadopago')
    provider_preference_id = models.CharField(max_length=64, null=True, blank=True)
    provider_payment_id = models.CharField(max_length=64, null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    status_detail = models.CharField(max_length=120, null=True, blank=True)
    currency = models.CharField(max_length=3, default='CLP')
    plan = models.ForeignKey(Plan, on_delete=models.SET_NULL, null=True, blank=True,
                             related_name='payment_transactions')
    plan_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    enrollment_fee_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    target_student_plan = models.ForeignKey(StudentPlan, on_delete=models.SET_NULL, null=True, blank=True,
                                            related_name='enrollment_fee_transactions')
    student_plan = models.ForeignKey(StudentPlan, on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name='origin_transactions')
    processed_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    raw_provider_payload = models.JSONField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['provider', 'provider_payment_id'],
                condition=Q(provider_payment_id__isnull=False),
                name='uniq_provider_payment',
            ),
        ]
        indexes = [
            models.Index(fields=['organization', 'status']),
            models.Index(fields=['user', 'status']),
        ]

    def __str__(self):
        return f'{self.id} · {self.status} · {self.amount} {self.currency}'


class WebhookEvent(TimestampedModel):
    provider = models.CharField(max_length=30, default='mercadopago')
    provider_payment_id = models.CharField(max_length=64, null=True, blank=True)
    transaction = models.ForeignKey(PaymentTransaction, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='webhook_events')
    raw_body = models.TextField()
    headers = models.JSONField(default=dict, blank=True)
    processed_ok = models.BooleanField(default=False)
    note = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
```

> Nota de estilo: la expresión `__import__(...)` para `STATUS_CHOICES` evita un import circular models↔providers. Si prefieres, reemplázala por una lista literal `[('pending','pending'), ('in_process','in_process'), ('approved','approved'), ('rejected','rejected'), ('cancelled','cancelled'), ('refunded','refunded')]` — más simple y sin magia. **Recomendado: la lista literal.**

- [ ] **Step 4: Generar la migración**

Run: `cd backend && python manage.py makemigrations core`
Expected: crea `core/migrations/0025_payments.py` con `PaymentAccount`, `PaymentTransaction`, `WebhookEvent`. Revisar que sea puramente aditiva (no altera `StudentPlan`/`Plan`).

- [ ] **Step 5: Correr los tests (deben pasar)**

Run: `cd backend && python -m pytest core/tests/test_payments_models.py -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Verificar que la suite completa sigue verde**

Run: `cd backend && python -m pytest -q`
Expected: PASS (sin regresiones; la migración es aditiva).

- [ ] **Step 7: Commit**

```bash
git add backend/core/models.py backend/core/migrations/0025_payments.py backend/core/tests/test_payments_models.py
git commit -m "feat(payments): modelos PaymentAccount/PaymentTransaction/WebhookEvent + migración"
```

---

## Task 5: MercadoPago provider — OAuth (authorize / exchange / refresh)

**Files:**
- Create: `backend/core/services/providers/mercadopago.py` (parte OAuth; se completa en Tasks 9 y 12)
- Test: `backend/core/tests/test_payments_mp_oauth.py`

**Interfaces:**
- Consumes: `OAuthTokens`, `PaymentProvider`, `PaymentProviderError` (Task 3).
- Produces: `MercadoPagoProvider(client_id, client_secret, webhook_secret)` con `name='mercadopago'` y los 3 métodos OAuth implementados vía `requests`. Endpoints como constantes de clase: `AUTH_URL='https://auth.mercadopago.cl/authorization'`, `TOKEN_URL='https://api.mercadopago.com/oauth/token'`.

- [ ] **Step 1: Escribir el test (mock HTTP con `responses`)**

Crear `backend/core/tests/test_payments_mp_oauth.py`:

```python
import responses

from core.services.providers.mercadopago import MercadoPagoProvider


def _provider():
    return MercadoPagoProvider(client_id='APP123', client_secret='SEC', webhook_secret='WH')


def test_authorization_url_has_required_params():
    url = _provider().get_authorization_url(state='ST', redirect_uri='https://app.tymroapp.com/cb')
    assert url.startswith('https://auth.mercadopago.cl/authorization')
    assert 'client_id=APP123' in url
    assert 'response_type=code' in url
    assert 'state=ST' in url
    assert 'redirect_uri=' in url


@responses.activate
def test_exchange_code_parses_tokens():
    responses.add(responses.POST, MercadoPagoProvider.TOKEN_URL, json={
        'access_token': 'AT', 'refresh_token': 'RT', 'expires_in': 15552000,
        'user_id': 987654, 'public_key': 'PK', 'scope': 'offline_access read write',
    }, status=200)
    tokens = _provider().exchange_code(code='CODE', redirect_uri='https://app.tymroapp.com/cb')
    assert tokens.access_token == 'AT'
    assert tokens.refresh_token == 'RT'
    assert tokens.expires_in == 15552000
    assert tokens.provider_user_id == '987654'
    assert tokens.public_key == 'PK'


@responses.activate
def test_refresh_tokens_parses_tokens():
    responses.add(responses.POST, MercadoPagoProvider.TOKEN_URL, json={
        'access_token': 'AT2', 'refresh_token': 'RT2', 'expires_in': 15552000,
        'user_id': 987654, 'public_key': 'PK',
    }, status=200)
    tokens = _provider().refresh_tokens(refresh_token='RT')
    assert tokens.access_token == 'AT2'
    assert tokens.refresh_token == 'RT2'


@responses.activate
def test_exchange_code_error_raises():
    from core.services.providers.base import PaymentProviderError
    responses.add(responses.POST, MercadoPagoProvider.TOKEN_URL,
                  json={'error': 'invalid_grant'}, status=400)
    import pytest
    with pytest.raises(PaymentProviderError):
        _provider().exchange_code(code='BAD', redirect_uri='https://app.tymroapp.com/cb')
```

- [ ] **Step 2: Correr el test (debe fallar)**

Run: `cd backend && python -m pytest core/tests/test_payments_mp_oauth.py -v`
Expected: FAIL (ModuleNotFoundError `core.services.providers.mercadopago`).

- [ ] **Step 3: Implementar el provider (OAuth)**

Crear `backend/core/services/providers/mercadopago.py`:

```python
"""Implementación concreta de PaymentProvider para MercadoPago (Checkout Pro + OAuth).

Aísla TODO el detalle de MercadoPago (endpoints, formatos, firma). El resto del
sistema no importa este módulo directamente: usa get_payment_provider().

VERIFICAR CONTRA LA DOC VIGENTE DE MP AL IMPLEMENTAR/PROBAR:
- Endpoint exacto de autorización (auth.mercadopago.cl) y si PKCE es obligatorio.
- TTL real de expires_in (se usa el valor devuelto, no se hardcodea).
- Formato del header x-signature y del manifest (ver Task 12).
"""
from decimal import Decimal
from urllib.parse import urlencode

import requests

from .base import (OAuthTokens, PaymentProvider, PaymentProviderError)

_TIMEOUT = 15


class MercadoPagoProvider(PaymentProvider):
    name = 'mercadopago'

    AUTH_URL = 'https://auth.mercadopago.cl/authorization'
    TOKEN_URL = 'https://api.mercadopago.com/oauth/token'
    PREFERENCE_URL = 'https://api.mercadopago.com/checkout/preferences'
    PAYMENT_URL = 'https://api.mercadopago.com/v1/payments/{id}'

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

    # --- Cobro (Task 9) y Webhook (Task 12): stubs por ahora ---
    def create_checkout(self, **kwargs):
        raise NotImplementedError('create_checkout: ver Task 9')

    def fetch_payment(self, **kwargs):
        raise NotImplementedError('fetch_payment: ver Task 9')

    def verify_webhook(self, **kwargs):
        raise NotImplementedError('verify_webhook: ver Task 12')

    def parse_webhook(self, **kwargs):
        raise NotImplementedError('parse_webhook: ver Task 12')
```

- [ ] **Step 4: Correr el test (debe pasar)**

Run: `cd backend && python -m pytest core/tests/test_payments_mp_oauth.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/core/services/providers/mercadopago.py backend/core/tests/test_payments_mp_oauth.py
git commit -m "feat(payments): MercadoPago provider — OAuth (authorize/exchange/refresh)"
```

---

## Task 6: Servicio de conexión OAuth (connect + callback + refresh lazy)

**Files:**
- Create: `backend/core/services/payments.py` (parte de conexión; se amplía en Tasks 10 y 13)
- Test: `backend/core/tests/test_payments_connect_service.py`

**Interfaces:**
- Consumes: `get_payment_provider` (Task 3), `PaymentAccount` (Task 4), `OAuthTokens` (Task 3), `django.core.signing`.
- Produces (en `core/services/payments.py`):
  - `build_connect_url(*, organization) -> str` — firma `state={org_id, nonce}` y devuelve la authorization_url.
  - `STATE_SALT = 'payments-oauth'`, `STATE_MAX_AGE = 600` (10 min).
  - `connect_callback(*, code, state) -> PaymentAccount` — valida `state`, intercambia `code`, upsert `PaymentAccount` (tokens cifrados, `token_expires_at`, `provider_user_id`, `public_key`, `status=connected`, `connected_at=now`). Lanza `InvalidState` si el state no valida.
  - `get_valid_access_token(*, account) -> str` — refresh lazy si `token_expires_at` vencido o dentro de `REFRESH_MARGIN` (24h); persiste tokens nuevos; si el refresh falla, marca `disconnected` y lanza `PaymentProviderError`.
  - Excepción `InvalidState(Exception)`.

- [ ] **Step 1: Escribir el test**

Crear `backend/core/tests/test_payments_connect_service.py`:

```python
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
    assert acc.provider == 'mercadopago'
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
```

- [ ] **Step 2: Correr el test (debe fallar)**

Run: `cd backend && python -m pytest core/tests/test_payments_connect_service.py -v`
Expected: FAIL (ImportError `core.services.payments`).

- [ ] **Step 3: Implementar el servicio (conexión)**

Crear `backend/core/services/payments.py`:

```python
"""Orquestación de dominio de pagos. No sabe de HTTP ni de MercadoPago:
delega en get_payment_provider(). Aísla la lógica de negocio de las views.
"""
from datetime import timedelta

from django.conf import settings
from django.core import signing
from django.utils import timezone

from core.models import PaymentAccount
from .providers import PaymentProviderError, get_payment_provider

STATE_SALT = 'payments-oauth'
STATE_MAX_AGE = 600          # 10 minutos
REFRESH_MARGIN = timedelta(hours=24)


class InvalidState(Exception):
    """El parámetro state del callback OAuth no es válido/expiró."""


def _sign_state(organization_id) -> str:
    # nonce derivado del org_id + timestamp implícito de signing (no usamos Math.random).
    return signing.dumps({'org': organization_id}, salt=STATE_SALT)


def _load_state(state) -> int:
    try:
        data = signing.loads(state, salt=STATE_SALT, max_age=STATE_MAX_AGE)
    except signing.BadSignature as exc:
        raise InvalidState('state inválido o expirado') from exc
    return data['org']


def build_connect_url(*, organization) -> str:
    provider = get_payment_provider()
    state = _sign_state(organization.id)
    return provider.get_authorization_url(state=state, redirect_uri=settings.MP_OAUTH_REDIRECT_URI)


def connect_callback(*, code, state) -> PaymentAccount:
    from core.models import Organization
    org_id = _load_state(state)
    organization = Organization.objects.get(id=org_id)
    provider = get_payment_provider()
    tokens = provider.exchange_code(code=code, redirect_uri=settings.MP_OAUTH_REDIRECT_URI)
    now = timezone.now()
    account, _ = PaymentAccount.objects.update_or_create(
        organization=organization, provider=provider.name,
        defaults=dict(
            provider_user_id=tokens.provider_user_id,
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            public_key=tokens.public_key,
            scope=tokens.scope,
            token_expires_at=now + timedelta(seconds=tokens.expires_in) if tokens.expires_in else None,
            status=PaymentAccount.STATUS_CONNECTED,
            connected_at=now,
        ),
    )
    return account


def get_valid_access_token(*, account) -> str:
    expiring = (account.token_expires_at is None
                or account.token_expires_at <= timezone.now() + REFRESH_MARGIN)
    if not expiring:
        return account.access_token
    provider = get_payment_provider(account.provider)
    try:
        tokens = provider.refresh_tokens(refresh_token=account.refresh_token)
    except PaymentProviderError:
        account.status = PaymentAccount.STATUS_DISCONNECTED
        account.save(update_fields=['status', 'updated_at'])
        raise
    account.access_token = tokens.access_token
    account.refresh_token = tokens.refresh_token
    if tokens.expires_in:
        account.token_expires_at = timezone.now() + timedelta(seconds=tokens.expires_in)
    account.status = PaymentAccount.STATUS_CONNECTED
    account.save(update_fields=['access_token', 'refresh_token', 'token_expires_at',
                                'status', 'updated_at'])
    return account.access_token
```

- [ ] **Step 4: Correr el test (debe pasar)**

Run: `cd backend && python -m pytest core/tests/test_payments_connect_service.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/core/services/payments.py backend/core/tests/test_payments_connect_service.py
git commit -m "feat(payments): servicio OAuth connect/callback + refresh lazy de token"
```

---

## Task 7: Endpoints de conexión (connect / callback / account) + allowlist

**Files:**
- Create: `backend/core/views_payments.py` (connect, callback, account; se amplía en Tasks 11 y 14)
- Modify: `backend/core/serializers.py` (append serializers de pagos)
- Modify: `backend/core/urls.py` (rutas de pagos)
- Modify: `backend/core/middleware.py` (allowlist defensivo)
- Test: `backend/core/tests/test_payments_connect_api.py`

**Interfaces:**
- Consumes: `payments.build_connect_url`, `payments.connect_callback`, `payments.InvalidState` (Task 6); helpers de rol de `core.views` (`_is_gym_admin`, `_is_superadmin`).
- Produces: `PaymentConnectView` (POST `/api/payments/connect/`), `PaymentOAuthCallbackView` (GET `/api/payments/oauth/callback/`, AllowAny), `PaymentAccountView` (GET `/api/payments/account/`). Rutas montadas bajo `/api/payments/`.

- [ ] **Step 1: Escribir el test**

Crear `backend/core/tests/test_payments_connect_api.py`:

```python
import pytest
from django.urls import reverse   # si las rutas tienen name; si no, usar paths literales

from core.models import PaymentAccount
from core.services import payments


@pytest.fixture(autouse=True)
def _fake(settings):
    settings.PAYMENTS_PROVIDER = 'fake'
    settings.PAYMENTS_ENCRYPTION_KEY = __import__(
        'core.fields', fromlist=['generate_encryption_key']).generate_encryption_key()


def test_connect_requires_gym_admin(api_client, make_organization, make_user):
    org = make_organization()
    student = make_user('s', organization=org, role='student')
    api_client.force_authenticate(user=student)
    resp = api_client.post('/api/payments/connect/')
    assert resp.status_code == 403


def test_connect_returns_authorization_url(api_client, make_organization, make_user):
    org = make_organization()
    admin = make_user('a', organization=org, role='gym_admin')
    api_client.force_authenticate(user=admin)
    resp = api_client.post('/api/payments/connect/')
    assert resp.status_code == 200
    assert 'authorization_url' in resp.data
    assert 'state=' in resp.data['authorization_url']


def test_oauth_callback_creates_account_and_redirects(api_client, make_organization):
    org = make_organization()
    state = payments._sign_state(org.id)
    resp = api_client.get('/api/payments/oauth/callback/', {'code': 'C', 'state': state})
    assert resp.status_code in (302, 200)
    assert PaymentAccount.objects.filter(organization=org).exists()


def test_account_view_scoped_to_org(api_client, make_organization, make_user):
    org = make_organization()
    payments.connect_callback(code='C', state=payments._sign_state(org.id))
    admin = make_user('a', organization=org, role='gym_admin')
    api_client.force_authenticate(user=admin)
    resp = api_client.get('/api/payments/account/')
    assert resp.status_code == 200
    assert resp.data['status'] == 'connected'
    assert resp.data['provider'] == 'fake'   # = settings.PAYMENTS_PROVIDER en el entorno de test
```

- [ ] **Step 2: Correr el test (debe fallar)**

Run: `cd backend && python -m pytest core/tests/test_payments_connect_api.py -v`
Expected: FAIL (404, rutas inexistentes).

- [ ] **Step 3: Añadir serializer de salida de cuenta**

En `backend/core/serializers.py` (al final):

```python
class PaymentAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentAccount
        fields = ['provider', 'status', 'provider_user_id', 'is_sandbox',
                  'connected_at', 'token_expires_at']
        read_only_fields = fields
```

(Asegurar `from .models import PaymentAccount` en los imports del serializers.py.)

- [ ] **Step 4: Implementar las views**

Crear `backend/core/views_payments.py`:

```python
"""APIViews de pagos (MercadoPago). Split de views.py por tamaño.
Todas respetan multitenancy: connect/account filtran por request.user.organization;
el callback resuelve la org por el state firmado (nunca por el Host)."""
from django.conf import settings
from django.shortcuts import redirect
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import PaymentAccount
from .serializers import PaymentAccountSerializer
from .services import payments
from .views import _is_gym_admin, _is_superadmin   # helpers de rol existentes


class PaymentConnectView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        if not (_is_superadmin(user) or _is_gym_admin(user)):
            return Response({'detail': 'No tienes permisos para conectar pagos.'},
                            status=status.HTTP_403_FORBIDDEN)
        if user.organization_id is None:
            return Response({'detail': 'Usuario sin organización.'},
                            status=status.HTTP_400_BAD_REQUEST)
        url = payments.build_connect_url(organization=user.organization)
        return Response({'authorization_url': url})


class PaymentOAuthCallbackView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        code = request.GET.get('code')
        state = request.GET.get('state')
        frontend = getattr(settings, 'FRONTEND_URL', '') or settings.PAYMENTS_APEX_BASE_URL
        if not code or not state:
            return redirect(f'{frontend}/ajustes/pagos?connected=0')
        try:
            payments.connect_callback(code=code, state=state)
        except payments.InvalidState:
            return redirect(f'{frontend}/ajustes/pagos?connected=0&error=state')
        except Exception:
            return redirect(f'{frontend}/ajustes/pagos?connected=0&error=exchange')
        return redirect(f'{frontend}/ajustes/pagos?connected=1')


class PaymentAccountView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if not (_is_superadmin(user) or _is_gym_admin(user)):
            return Response({'detail': 'No tienes permisos.'}, status=status.HTTP_403_FORBIDDEN)
        account = PaymentAccount.objects.filter(
            organization_id=user.organization_id, provider=settings.PAYMENTS_PROVIDER).first()
        if account is None:
            return Response({'status': 'disconnected', 'provider': settings.PAYMENTS_PROVIDER})
        return Response(PaymentAccountSerializer(account).data)
```

- [ ] **Step 5: Montar las rutas**

En `backend/core/urls.py`, importar y agregar a `urlpatterns` (además del router DRF existente):

```python
from django.urls import path
from .views_payments import (PaymentAccountView, PaymentConnectView,
                             PaymentOAuthCallbackView)

# ... dentro de urlpatterns (agregar estas rutas):
    path('payments/connect/', PaymentConnectView.as_view(), name='payments-connect'),
    path('payments/oauth/callback/', PaymentOAuthCallbackView.as_view(), name='payments-oauth-callback'),
    path('payments/account/', PaymentAccountView.as_view(), name='payments-account'),
```

(Confirmar el prefijo real: si `core.urls` ya cuelga de `/api/` en `tymro/urls.py`, estas rutas quedan en `/api/payments/...`.)

- [ ] **Step 6: Allowlist defensivo en el middleware**

En `backend/core/middleware.py`, extender `_ALLOWLIST_PREFIXES`:

```python
_ALLOWLIST_PREFIXES = ('/admin', '/static', '/media', '/api/health',
                       '/api/payments/webhook', '/api/payments/oauth/callback')
```

(Defensivo: callback y webhook llegan al apex —donde `request.organization` ya es `None` sin 404—, pero esto los protege si un host tipo túnel se resolviera como subdominio.)

- [ ] **Step 7: Correr el test (debe pasar)**

Run: `cd backend && python -m pytest core/tests/test_payments_connect_api.py -v`
Expected: PASS (4 tests).

- [ ] **Step 8: Commit**

```bash
git add backend/core/views_payments.py backend/core/serializers.py backend/core/urls.py backend/core/middleware.py backend/core/tests/test_payments_connect_api.py
git commit -m "feat(payments): endpoints connect/callback/account + allowlist"
```

---

## Task 8: Extraer `activate_student_plan` y refactorizar `assign`

**Files:**
- Create: `backend/core/services/plans.py`
- Modify: `backend/core/views.py:2775-2789` (acción `assign` usa el servicio)
- Test: `backend/core/tests/test_activate_student_plan.py`

**Interfaces:**
- Consumes: `StudentPlan`, `Plan` (modelos), `django.db.transaction`, `django.utils.timezone`.
- Produces: `activate_student_plan(*, student, plan, start_date, discount_percentage=None) -> StudentPlan` — desactiva el `StudentPlan` activo previo y crea uno nuevo replicando EXACTAMENTE la lógica de `assign` (end_date, total_classes, unlimited_classes, discount, final_price). NO cambia el comportamiento observable de `assign`.

- [ ] **Step 1: Escribir el test**

Crear `backend/core/tests/test_activate_student_plan.py`:

```python
from datetime import date, timedelta

import pytest

from core.models import Plan, StudentPlan
from core.services.plans import activate_student_plan


@pytest.fixture
def plan(db, make_organization):
    org = make_organization()
    return org, Plan.objects.create(organization=org, name='Mensual', plan_type='monthly',
                                    total_classes=12, unlimited_classes=False, duration_days=30,
                                    price=30000.0, discount_percentage=0)


def test_activate_creates_active_plan_and_derives_fields(plan, make_user):
    org, p = plan
    student = make_user('stu', organization=org, role='student')
    sp = activate_student_plan(student=student, plan=p, start_date=date(2026, 7, 1))
    assert sp.is_active is True
    assert sp.total_classes == 12
    assert sp.unlimited_classes is False
    assert sp.end_date == date(2026, 7, 1) + timedelta(days=29)   # duration-1
    assert sp.final_price == 30000.0


def test_activate_applies_discount(plan, make_user):
    org, p = plan
    student = make_user('stu2', organization=org, role='student')
    sp = activate_student_plan(student=student, plan=p, start_date=date(2026, 7, 1),
                               discount_percentage=50)
    assert sp.final_price == 15000.0
    assert sp.discount_percentage == 50


def test_activate_deactivates_previous(plan, make_user):
    org, p = plan
    student = make_user('stu3', organization=org, role='student')
    first = activate_student_plan(student=student, plan=p, start_date=date(2026, 6, 1))
    second = activate_student_plan(student=student, plan=p, start_date=date(2026, 7, 1))
    first.refresh_from_db()
    assert first.is_active is False
    assert second.is_active is True
    assert StudentPlan.objects.filter(user=student, is_active=True).count() == 1
```

- [ ] **Step 2: Correr el test (debe fallar)**

Run: `cd backend && python -m pytest core/tests/test_activate_student_plan.py -v`
Expected: FAIL (ImportError `core.services.plans`).

- [ ] **Step 3: Implementar el servicio**

Crear `backend/core/services/plans.py`:

```python
"""Activación/renovación de StudentPlan. Fuente única de verdad usada por la
acción admin `assign` y por el webhook de pagos."""
from datetime import timedelta

from django.db import transaction

from core.models import StudentPlan


def activate_student_plan(*, student, plan, start_date, discount_percentage=None):
    discount = discount_percentage if discount_percentage is not None else (plan.discount_percentage or 0)
    end_date = start_date + timedelta(days=max(plan.duration_days - 1, 0))
    final_price = max(float(plan.price) * (1 - (discount / 100)), 0)
    with transaction.atomic():
        StudentPlan.objects.filter(user=student, is_active=True).update(is_active=False)
        return StudentPlan.objects.create(
            user=student, plan=plan,
            start_date=start_date, end_date=end_date,
            total_classes=plan.total_classes,
            unlimited_classes=plan.unlimited_classes,
            discount_percentage=discount,
            final_price=final_price,
            is_active=True,
        )
```

- [ ] **Step 4: Refactorizar `assign` para usar el servicio**

En `backend/core/views.py`, dentro de la acción `assign` (~línea 2775), reemplazar el bloque `with transaction.atomic(): ...` por:

```python
        from core.services.plans import activate_student_plan
        assigned = activate_student_plan(
            student=student,
            plan=plan,
            start_date=validated['start_date'],
            discount_percentage=validated['discount_percentage'],
        )
        return Response(StudentPlanSerializer(assigned).data, status=status.HTTP_201_CREATED)
```

(El resto de la acción —checks de permisos y de organización— queda igual.)

- [ ] **Step 5: Correr los tests (nuevos + regresión de assign)**

Run: `cd backend && python -m pytest core/tests/test_activate_student_plan.py core/tests/test_plan_assign_unlimited.py core/tests/test_per_plan_price.py -v`
Expected: PASS (nuevos verdes y los tests existentes de `assign` siguen verdes).

- [ ] **Step 6: Commit**

```bash
git add backend/core/services/plans.py backend/core/views.py backend/core/tests/test_activate_student_plan.py
git commit -m "refactor(plans): extraer activate_student_plan; assign lo reutiliza"
```

---

## Task 9: MercadoPago provider — `create_checkout` + `fetch_payment`

**Files:**
- Modify: `backend/core/services/providers/mercadopago.py` (implementar los dos stubs)
- Test: `backend/core/tests/test_payments_mp_checkout.py`

**Interfaces:**
- Consumes: `CheckoutItem`, `BackUrls`, `CheckoutSession`, `ProviderPayment`, `PaymentStatus`, `PaymentProviderError` (Task 3).
- Produces: `MercadoPagoProvider.create_checkout(...)` (POST preference con Bearer del gym, `currency_id='CLP'`, `external_reference`, `notification_url`, `back_urls`, `auto_return='approved'`, `expiration_date_to`) → `CheckoutSession(redirect_url=init_point, provider_preference_id=id)`; `MercadoPagoProvider.fetch_payment(...)` (GET `/v1/payments/{id}`) → `ProviderPayment` con `status` normalizado. Mapa `_STATUS_MAP` MP→`PaymentStatus`.

- [ ] **Step 1: Escribir el test**

Crear `backend/core/tests/test_payments_mp_checkout.py`:

```python
from decimal import Decimal

import responses

from core.services.providers.base import (BackUrls, CheckoutItem, PaymentStatus)
from core.services.providers.mercadopago import MercadoPagoProvider


def _p():
    return MercadoPagoProvider(client_id='APP', client_secret='S', webhook_secret='W')


@responses.activate
def test_create_checkout_posts_preference_and_returns_init_point():
    responses.add(responses.POST, MercadoPagoProvider.PREFERENCE_URL, json={
        'id': 'PREF-1', 'init_point': 'https://mp/checkout/PREF-1',
        'sandbox_init_point': 'https://sandbox.mp/checkout/PREF-1',
    }, status=201)
    session = _p().create_checkout(
        access_token='GYMTOKEN', external_reference='tx-uuid',
        items=[CheckoutItem(title='Plan Mensual', quantity=1, unit_price=Decimal('30000'))],
        payer_email='alumno@x.cl',
        back_urls=BackUrls(success='https://s', pending='https://p', failure='https://f'),
        notification_url='https://app.tymroapp.com/api/payments/webhook/?tx=tx-uuid',
        expires_at=None,
    )
    assert session.provider_preference_id == 'PREF-1'
    assert session.redirect_url == 'https://mp/checkout/PREF-1'
    sent = responses.calls[0].request
    assert sent.headers['Authorization'] == 'Bearer GYMTOKEN'
    import json
    body = json.loads(sent.body)
    assert body['external_reference'] == 'tx-uuid'
    assert body['items'][0]['currency_id'] == 'CLP'
    assert body['items'][0]['unit_price'] == 30000
    assert body['notification_url'].endswith('tx=tx-uuid')


@responses.activate
def test_fetch_payment_normalizes_status():
    responses.add(responses.GET, MercadoPagoProvider.PAYMENT_URL.format(id='PAY9'), json={
        'id': 'PAY9', 'status': 'approved', 'status_detail': 'accredited',
        'transaction_amount': 30000, 'currency_id': 'CLP',
        'external_reference': 'tx-uuid', 'collector_id': 987654,
    }, status=200)
    payment = _p().fetch_payment(access_token='GYMTOKEN', provider_payment_id='PAY9')
    assert payment.status == PaymentStatus.APPROVED
    assert payment.amount == Decimal('30000')
    assert payment.currency == 'CLP'
    assert payment.external_reference == 'tx-uuid'
    assert payment.collector_id == '987654'


@responses.activate
def test_fetch_payment_maps_rejected():
    responses.add(responses.GET, MercadoPagoProvider.PAYMENT_URL.format(id='P'), json={
        'id': 'P', 'status': 'rejected', 'status_detail': 'cc_rejected',
        'transaction_amount': 100, 'currency_id': 'CLP', 'external_reference': 'e', 'collector_id': 1,
    }, status=200)
    assert _p().fetch_payment(access_token='T', provider_payment_id='P').status == PaymentStatus.REJECTED
```

- [ ] **Step 2: Correr el test (debe fallar)**

Run: `cd backend && python -m pytest core/tests/test_payments_mp_checkout.py -v`
Expected: FAIL (NotImplementedError en `create_checkout`).

- [ ] **Step 3: Implementar los métodos**

En `backend/core/services/providers/mercadopago.py`, agregar el mapa de estados a nivel de módulo e implementar los métodos (reemplazando los stubs de `create_checkout` y `fetch_payment`):

```python
from .base import (BackUrls, CheckoutItem, CheckoutSession, PaymentStatus, ProviderPayment)

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
```

```python
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
```

- [ ] **Step 4: Correr el test (debe pasar)**

Run: `cd backend && python -m pytest core/tests/test_payments_mp_checkout.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/core/services/providers/mercadopago.py backend/core/tests/test_payments_mp_checkout.py
git commit -m "feat(payments): MercadoPago create_checkout + fetch_payment con mapeo de estados"
```

---

## Task 10: Servicio `create_checkout` (orquestación de cobro)

**Files:**
- Modify: `backend/core/services/payments.py` (agregar `create_checkout`)
- Test: `backend/core/tests/test_payments_checkout_service.py`

**Interfaces:**
- Consumes: `get_payment_provider`, `get_valid_access_token` (Task 6), `PaymentAccount`, `PaymentTransaction`, `Plan`, `StudentPlan`, DTOs (`CheckoutItem`, `BackUrls`).
- Produces: `create_checkout(*, organization, user, plan=None, target_student_plan=None) -> tuple[PaymentTransaction, str]` (devuelve la transacción y la `redirect_url`). Reglas: exige exactamente uno de `plan`/`target_student_plan`; valida pertenencia a la org; exige `PaymentAccount` conectada; calcula montos en entero CLP; setea `notification_url = f'{APEX}/api/payments/webhook/?tx={tx.id}'`. Excepciones: `CheckoutError(Exception)`, `NotConnected(CheckoutError)`.

- [ ] **Step 1: Escribir el test**

Crear `backend/core/tests/test_payments_checkout_service.py`:

```python
from decimal import Decimal

import pytest

from core.models import Plan, PaymentTransaction, StudentPlan
from core.services import payments


@pytest.fixture(autouse=True)
def _fake(settings):
    settings.PAYMENTS_PROVIDER = 'fake'
    settings.PAYMENTS_ENCRYPTION_KEY = __import__(
        'core.fields', fromlist=['generate_encryption_key']).generate_encryption_key()
    settings.PAYMENTS_APEX_BASE_URL = 'https://app.tymroapp.com'


@pytest.fixture
def connected_org(make_organization):
    org = make_organization()
    payments.connect_callback(code='C', state=payments._sign_state(org.id))
    return org


def test_checkout_for_plan_creates_pending_transaction(connected_org, make_user):
    org = connected_org
    student = make_user('stu', organization=org, role='student')
    plan = Plan.objects.create(organization=org, name='Mensual', plan_type='monthly',
                               total_classes=12, unlimited_classes=False, duration_days=30,
                               price=30000.0, discount_percentage=0)
    tx, url = payments.create_checkout(organization=org, user=student, plan=plan)
    assert isinstance(tx, PaymentTransaction)
    assert tx.status == 'pending'
    assert tx.plan_amount == Decimal('30000')
    assert tx.enrollment_fee_amount == Decimal('0')
    assert tx.amount == Decimal('30000')
    assert url.startswith('https://fake.mp/checkout/')


def test_checkout_for_enrollment_fee(connected_org, make_user):
    org = connected_org
    student = make_user('stu2', organization=org, role='student')
    plan = Plan.objects.create(organization=org, name='M', plan_type='monthly', total_classes=1,
                               unlimited_classes=False, duration_days=30, price=1000.0)
    sp = StudentPlan.objects.create(user=student, plan=plan, start_date='2026-07-01',
                                    end_date='2026-07-30', total_classes=1,
                                    enrollment_fee=Decimal('20000'))
    tx, url = payments.create_checkout(organization=org, user=student, target_student_plan=sp)
    assert tx.enrollment_fee_amount == Decimal('20000')
    assert tx.plan_amount == Decimal('0')
    assert tx.amount == Decimal('20000')
    assert tx.target_student_plan_id == sp.id


def test_checkout_without_connected_account_raises(make_organization, make_user):
    org = make_organization()   # no conectada
    student = make_user('stu3', organization=org, role='student')
    plan = Plan.objects.create(organization=org, name='M', plan_type='monthly', total_classes=1,
                               unlimited_classes=False, duration_days=30, price=1000.0)
    with pytest.raises(payments.NotConnected):
        payments.create_checkout(organization=org, user=student, plan=plan)


def test_checkout_rejects_plan_from_other_org(connected_org, make_organization, make_user):
    org = connected_org
    other = make_organization()
    student = make_user('stu4', organization=org, role='student')
    foreign_plan = Plan.objects.create(organization=other, name='X', plan_type='monthly',
                                       total_classes=1, unlimited_classes=False,
                                       duration_days=30, price=1000.0)
    with pytest.raises(payments.CheckoutError):
        payments.create_checkout(organization=org, user=student, plan=foreign_plan)
```

- [ ] **Step 2: Correr el test (debe fallar)**

Run: `cd backend && python -m pytest core/tests/test_payments_checkout_service.py -v`
Expected: FAIL (AttributeError `create_checkout`).

- [ ] **Step 3: Implementar `create_checkout`**

En `backend/core/services/payments.py`, agregar imports y la función:

```python
from decimal import Decimal

from core.models import PaymentTransaction
from .providers.base import BackUrls, CheckoutItem


class CheckoutError(Exception):
    """No se puede iniciar el cobro."""


class NotConnected(CheckoutError):
    """La organización no tiene cuenta de pago conectada."""


def _clp(value) -> Decimal:
    return Decimal(int(round(float(value))))


def create_checkout(*, organization, user, plan=None, target_student_plan=None):
    if bool(plan) == bool(target_student_plan):
        raise CheckoutError('Debe indicarse exactamente uno: plan o target_student_plan.')

    account = PaymentAccount.objects.filter(
        organization=organization, provider=settings.PAYMENTS_PROVIDER,
        status=PaymentAccount.STATUS_CONNECTED).first()
    if account is None:
        raise NotConnected('La organización no tiene MercadoPago conectado.')

    plan_amount = Decimal('0')
    enrollment_fee_amount = Decimal('0')
    items = []

    if plan is not None:
        if plan.organization_id != organization.id:
            raise CheckoutError('El plan no pertenece a la organización.')
        discount = plan.discount_percentage or 0
        plan_amount = _clp(max(float(plan.price) * (1 - discount / 100), 0))
        items.append(CheckoutItem(title=f'Plan {plan.name}', quantity=1, unit_price=plan_amount))
    else:
        sp = target_student_plan
        if sp.user_id != user.id or sp.plan.organization_id != organization.id:
            raise CheckoutError('La matrícula no corresponde al alumno/organización.')
        if not (sp.enrollment_fee and sp.enrollment_fee > 0) or sp.enrollment_fee_paid_at is not None:
            raise CheckoutError('No hay matrícula pendiente para este plan.')
        enrollment_fee_amount = _clp(sp.enrollment_fee)
        items.append(CheckoutItem(title='Matrícula', quantity=1, unit_price=enrollment_fee_amount))

    amount = plan_amount + enrollment_fee_amount

    tx = PaymentTransaction.objects.create(
        organization=organization, user=user, provider=account.provider,
        plan=plan, plan_amount=plan_amount, enrollment_fee_amount=enrollment_fee_amount,
        amount=amount, currency='CLP', target_student_plan=target_student_plan,
        metadata={'items': [it.title for it in items]},
    )

    provider = get_payment_provider(account.provider)
    access_token = get_valid_access_token(account=account)
    apex = settings.PAYMENTS_APEX_BASE_URL.rstrip('/')
    frontend = getattr(settings, 'FRONTEND_URL', apex).rstrip('/')
    session = provider.create_checkout(
        access_token=access_token,
        external_reference=str(tx.id),
        items=items,
        payer_email=getattr(user, 'email', None),
        back_urls=BackUrls(success=f'{frontend}/pagos/resultado?tx={tx.id}',
                           pending=f'{frontend}/pagos/resultado?tx={tx.id}',
                           failure=f'{frontend}/pagos/resultado?tx={tx.id}'),
        notification_url=f'{apex}/api/payments/webhook/?tx={tx.id}',
        expires_at=None,
    )
    tx.provider_preference_id = session.provider_preference_id
    tx.save(update_fields=['provider_preference_id', 'updated_at'])
    return tx, session.redirect_url
```

- [ ] **Step 4: Correr el test (debe pasar)**

Run: `cd backend && python -m pytest core/tests/test_payments_checkout_service.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/core/services/payments.py backend/core/tests/test_payments_checkout_service.py
git commit -m "feat(payments): servicio create_checkout (plan o matrícula) idempotente por tx"
```

---

## Task 11: Endpoints de checkout y de estado

**Files:**
- Modify: `backend/core/views_payments.py` (agregar `PaymentCheckoutView`, `PaymentTransactionStatusView`)
- Modify: `backend/core/serializers.py` (serializer de request + de estado)
- Modify: `backend/core/urls.py` (rutas)
- Test: `backend/core/tests/test_payments_checkout_api.py`

**Interfaces:**
- Consumes: `payments.create_checkout`, `payments.CheckoutError`, `payments.NotConnected` (Task 10); `PaymentTransaction`; helpers `_is_student`.
- Produces: `POST /api/payments/checkout/` (body `{plan_id?}` o `{target_student_plan_id?}`, rol student, filtra por org) → `{transaction_id, redirect_url}`; `GET /api/payments/transactions/<uuid:pk>/status/` (dueño de la tx) → `{id, status, status_detail, amount}`.

- [ ] **Step 1: Escribir el test**

Crear `backend/core/tests/test_payments_checkout_api.py`:

```python
import pytest

from core.models import Plan
from core.services import payments


@pytest.fixture(autouse=True)
def _fake(settings):
    settings.PAYMENTS_PROVIDER = 'fake'
    settings.PAYMENTS_ENCRYPTION_KEY = __import__(
        'core.fields', fromlist=['generate_encryption_key']).generate_encryption_key()
    settings.PAYMENTS_APEX_BASE_URL = 'https://app.tymroapp.com'


@pytest.fixture
def connected_org(make_organization):
    org = make_organization()
    payments.connect_callback(code='C', state=payments._sign_state(org.id))
    return org


def test_checkout_endpoint_returns_redirect_url(api_client, connected_org, make_user):
    org = connected_org
    student = make_user('stu', organization=org, role='student')
    plan = Plan.objects.create(organization=org, name='M', plan_type='monthly', total_classes=1,
                               unlimited_classes=False, duration_days=30, price=1000.0)
    api_client.force_authenticate(user=student)
    resp = api_client.post('/api/payments/checkout/', {'plan_id': plan.id}, format='json')
    assert resp.status_code == 200
    assert 'redirect_url' in resp.data and 'transaction_id' in resp.data


def test_checkout_requires_student(api_client, connected_org, make_user):
    org = connected_org
    admin = make_user('a', organization=org, role='gym_admin')
    plan = Plan.objects.create(organization=org, name='M', plan_type='monthly', total_classes=1,
                               unlimited_classes=False, duration_days=30, price=1000.0)
    api_client.force_authenticate(user=admin)
    resp = api_client.post('/api/payments/checkout/', {'plan_id': plan.id}, format='json')
    assert resp.status_code == 403


def test_status_endpoint_scoped_to_owner(api_client, connected_org, make_user):
    org = connected_org
    student = make_user('stu2', organization=org, role='student')
    plan = Plan.objects.create(organization=org, name='M', plan_type='monthly', total_classes=1,
                               unlimited_classes=False, duration_days=30, price=1000.0)
    tx, _ = payments.create_checkout(organization=org, user=student, plan=plan)
    other = make_user('stu3', organization=org, role='student')
    api_client.force_authenticate(user=other)
    assert api_client.get(f'/api/payments/transactions/{tx.id}/status/').status_code == 404
    api_client.force_authenticate(user=student)
    resp = api_client.get(f'/api/payments/transactions/{tx.id}/status/')
    assert resp.status_code == 200
    assert resp.data['status'] == 'pending'
```

- [ ] **Step 2: Correr el test (debe fallar)**

Run: `cd backend && python -m pytest core/tests/test_payments_checkout_api.py -v`
Expected: FAIL (404).

- [ ] **Step 3: Añadir serializers**

En `backend/core/serializers.py` (al final):

```python
class PaymentCheckoutRequestSerializer(serializers.Serializer):
    plan_id = serializers.IntegerField(required=False)
    target_student_plan_id = serializers.IntegerField(required=False)

    def validate(self, attrs):
        if bool(attrs.get('plan_id')) == bool(attrs.get('target_student_plan_id')):
            raise serializers.ValidationError('Indica exactamente uno: plan_id o target_student_plan_id.')
        return attrs


class PaymentTransactionStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentTransaction
        fields = ['id', 'status', 'status_detail', 'amount', 'currency']
        read_only_fields = fields
```

(Asegurar `from .models import PaymentTransaction` en imports.)

- [ ] **Step 4: Añadir las views**

En `backend/core/views_payments.py`:

```python
from django.shortcuts import get_object_or_404

from .models import Plan, PaymentTransaction, StudentPlan
from .serializers import (PaymentCheckoutRequestSerializer,
                          PaymentTransactionStatusSerializer)
from .views import _is_student


class PaymentCheckoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        if not _is_student(user):
            return Response({'detail': 'Solo alumnos pueden pagar.'}, status=status.HTTP_403_FORBIDDEN)
        req = PaymentCheckoutRequestSerializer(data=request.data)
        req.is_valid(raise_exception=True)
        plan = target = None
        if req.validated_data.get('plan_id'):
            plan = get_object_or_404(Plan, id=req.validated_data['plan_id'],
                                     organization_id=user.organization_id)
        else:
            target = get_object_or_404(StudentPlan, id=req.validated_data['target_student_plan_id'],
                                       user=user)
        try:
            tx, url = payments.create_checkout(organization=user.organization, user=user,
                                               plan=plan, target_student_plan=target)
        except payments.NotConnected:
            return Response({'detail': 'El gimnasio no tiene pagos habilitados.'},
                            status=status.HTTP_409_CONFLICT)
        except payments.CheckoutError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'transaction_id': str(tx.id), 'redirect_url': url})


class PaymentTransactionStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        tx = get_object_or_404(PaymentTransaction, id=pk,
                               organization_id=request.user.organization_id, user=request.user)
        return Response(PaymentTransactionStatusSerializer(tx).data)
```

(Agregar `from .services import payments` si no está ya importado en el módulo.)

- [ ] **Step 5: Montar rutas**

En `backend/core/urls.py` agregar:

```python
from .views_payments import PaymentCheckoutView, PaymentTransactionStatusView
# ...
    path('payments/checkout/', PaymentCheckoutView.as_view(), name='payments-checkout'),
    path('payments/transactions/<uuid:pk>/status/', PaymentTransactionStatusView.as_view(),
         name='payments-transaction-status'),
```

- [ ] **Step 6: Correr el test (debe pasar)**

Run: `cd backend && python -m pytest core/tests/test_payments_checkout_api.py -v`
Expected: PASS (3 tests).

- [ ] **Step 7: Commit**

```bash
git add backend/core/views_payments.py backend/core/serializers.py backend/core/urls.py backend/core/tests/test_payments_checkout_api.py
git commit -m "feat(payments): endpoints de checkout y de estado de transacción"
```

---

## Task 12: MercadoPago provider — `verify_webhook` + `parse_webhook`

**Files:**
- Modify: `backend/core/services/providers/mercadopago.py` (implementar los stubs)
- Test: `backend/core/tests/test_payments_mp_webhook_signature.py`

**Interfaces:**
- Consumes: `WebhookEnvelope` (Task 3), `hmac`, `hashlib`.
- Produces: `MercadoPagoProvider.verify_webhook(*, headers, raw_body) -> bool` (HMAC-SHA256 en tiempo constante, manifest con `data.id` + `x-request-id` + `ts`, secret de app); `parse_webhook(*, headers, raw_body) -> WebhookEnvelope` (JSON body → type/action/data.id).

> **VERIFICAR CONTRA DOC VIGENTE DE MP:** el **string exacto** del manifest (orden/nombres) y el nombre exacto de los headers (`x-signature`, `x-request-id`). El manifest usado aquí (`id:{id};request-id:{req};ts:{ts};`) es el documentado históricamente; confirmar antes de ir a prod. El enfoque (HMAC-SHA256 con `MP_WEBHOOK_SECRET`, comparación constante) es estable.

- [ ] **Step 1: Escribir el test**

Crear `backend/core/tests/test_payments_mp_webhook_signature.py`:

```python
import hashlib
import hmac
import json

from core.services.providers.mercadopago import MercadoPagoProvider


def _sig_headers(secret, data_id, request_id, ts):
    manifest = f'id:{data_id};request-id:{request_id};ts:{ts};'
    v1 = hmac.new(secret.encode(), manifest.encode(), hashlib.sha256).hexdigest()
    return {'x-signature': f'ts={ts},v1={v1}', 'x-request-id': request_id}


def test_verify_webhook_accepts_valid_signature():
    p = MercadoPagoProvider(client_id='A', client_secret='S', webhook_secret='WHSECRET')
    body = json.dumps({'type': 'payment', 'data': {'id': '123'}}).encode()
    headers = _sig_headers('WHSECRET', '123', 'req-1', '1720000000')
    assert p.verify_webhook(headers=headers, raw_body=body) is True


def test_verify_webhook_rejects_tampered_signature():
    p = MercadoPagoProvider(client_id='A', client_secret='S', webhook_secret='WHSECRET')
    body = json.dumps({'type': 'payment', 'data': {'id': '123'}}).encode()
    headers = _sig_headers('OTHER', '123', 'req-1', '1720000000')   # secret equivocado
    assert p.verify_webhook(headers=headers, raw_body=body) is False


def test_parse_webhook_extracts_payment_id():
    p = MercadoPagoProvider(client_id='A', client_secret='S', webhook_secret='W')
    body = json.dumps({'type': 'payment', 'action': 'payment.updated',
                       'data': {'id': '999'}}).encode()
    env = p.parse_webhook(headers={}, raw_body=body)
    assert env.type == 'payment'
    assert env.action == 'payment.updated'
    assert env.provider_payment_id == '999'
```

- [ ] **Step 2: Correr el test (debe fallar)**

Run: `cd backend && python -m pytest core/tests/test_payments_mp_webhook_signature.py -v`
Expected: FAIL (NotImplementedError).

- [ ] **Step 3: Implementar los métodos**

En `backend/core/services/providers/mercadopago.py` (agregar imports `import hashlib, hmac, json` arriba y reemplazar los stubs):

```python
    def _parse_x_signature(self, header_value):
        # "ts=1720000000,v1=abc123..."
        parts = {}
        for chunk in (header_value or '').split(','):
            if '=' in chunk:
                k, v = chunk.split('=', 1)
                parts[k.strip()] = v.strip()
        return parts.get('ts'), parts.get('v1')

    def verify_webhook(self, *, headers, raw_body):
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
        data = body.get('data') or {}
        pid = data.get('id')
        return WebhookEnvelope(type=body.get('type', ''), action=body.get('action'),
                               provider_payment_id=str(pid) if pid is not None else None)
```

- [ ] **Step 4: Correr el test (debe pasar)**

Run: `cd backend && python -m pytest core/tests/test_payments_mp_webhook_signature.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/core/services/providers/mercadopago.py backend/core/tests/test_payments_mp_webhook_signature.py
git commit -m "feat(payments): verificación de firma (HMAC) y parseo de webhook MercadoPago"
```

---

## Task 13: Servicio `process_payment_notification` (idempotente) + `reconcile_transaction`

**Files:**
- Modify: `backend/core/services/payments.py` (agregar procesamiento del webhook)
- Test: `backend/core/tests/test_payments_process_webhook.py`

**Interfaces:**
- Consumes: `get_payment_provider`, `get_valid_access_token`, `activate_student_plan` (Task 8), `PaymentTransaction`, `PaymentAccount`, `PaymentStatus`, `django.db.transaction`, `timezone`.
- Produces:
  - `apply_provider_payment(*, tx, payment) -> PaymentTransaction` — núcleo idempotente: `select_for_update` sobre `tx`, no-op si `processed_at` seteado; cross-check `collector_id`/`amount`; en `APPROVED` llama `activate_student_plan` (o marca `enrollment_fee_paid_at`), setea `student_plan`, `provider_payment_id`, `processed_at`.
  - `process_payment_notification(*, tx_id, provider_payment_id) -> PaymentTransaction | None` — resuelve tx+account, obtiene token, `fetch_payment`, delega en `apply_provider_payment`.
  - `reconcile_transaction(*, tx) -> PaymentTransaction` — reusa `apply_provider_payment` para el backstop.

- [ ] **Step 1: Escribir el test**

Crear `backend/core/tests/test_payments_process_webhook.py`:

```python
from decimal import Decimal

import pytest

from core.models import Plan, PaymentTransaction, StudentPlan
from core.services import payments
from core.services.providers.base import PaymentStatus


@pytest.fixture(autouse=True)
def _fake(settings):
    settings.PAYMENTS_PROVIDER = 'fake'
    settings.PAYMENTS_ENCRYPTION_KEY = __import__(
        'core.fields', fromlist=['generate_encryption_key']).generate_encryption_key()
    settings.PAYMENTS_APEX_BASE_URL = 'https://app.tymroapp.com'


@pytest.fixture
def scenario(make_organization, make_user):
    org = make_organization()
    payments.connect_callback(code='C', state=payments._sign_state(org.id))
    student = make_user('stu', organization=org, role='student')
    plan = Plan.objects.create(organization=org, name='Mensual', plan_type='monthly',
                               total_classes=12, unlimited_classes=False, duration_days=30,
                               price=30000.0, discount_percentage=0)
    tx, _ = payments.create_checkout(organization=org, user=student, plan=plan)
    return org, student, plan, tx


def _approve(tx, provider):
    provider.queue_payment(external_reference=str(tx.id), status=PaymentStatus.APPROVED,
                           amount=Decimal('30000'), provider_payment_id='PAY1')


def test_approved_payment_activates_student_plan(scenario):
    org, student, plan, tx = scenario
    from core.services.providers import get_payment_provider
    provider = get_payment_provider()
    _approve(tx, provider)
    result = payments.process_payment_notification(tx_id=str(tx.id), provider_payment_id='PAY1')
    result.refresh_from_db()
    assert result.status == 'approved'
    assert result.processed_at is not None
    assert result.student_plan_id is not None
    assert StudentPlan.objects.filter(user=student, is_active=True).count() == 1


def test_idempotent_double_processing_creates_one_plan(scenario):
    org, student, plan, tx = scenario
    from core.services.providers import get_payment_provider
    provider = get_payment_provider()
    _approve(tx, provider)
    payments.process_payment_notification(tx_id=str(tx.id), provider_payment_id='PAY1')
    first_processed = PaymentTransaction.objects.get(id=tx.id).processed_at
    # Segundo webhook (duplicado) para el mismo pago:
    payments.process_payment_notification(tx_id=str(tx.id), provider_payment_id='PAY1')
    tx.refresh_from_db()
    assert tx.processed_at == first_processed            # no se re-procesó
    assert StudentPlan.objects.filter(user=student, is_active=True).count() == 1   # un solo plan


def test_rejected_payment_does_not_activate(scenario):
    org, student, plan, tx = scenario
    from core.services.providers import get_payment_provider
    provider = get_payment_provider()
    provider.queue_payment(external_reference=str(tx.id), status=PaymentStatus.REJECTED,
                           amount=Decimal('30000'), provider_payment_id='PAYX')
    payments.process_payment_notification(tx_id=str(tx.id), provider_payment_id='PAYX')
    tx.refresh_from_db()
    assert tx.status == 'rejected'
    assert tx.processed_at is None
    assert StudentPlan.objects.filter(user=student, is_active=True).count() == 0


def test_amount_mismatch_is_rejected(scenario):
    org, student, plan, tx = scenario
    from core.services.providers import get_payment_provider
    provider = get_payment_provider()
    provider.queue_payment(external_reference=str(tx.id), status=PaymentStatus.APPROVED,
                           amount=Decimal('1'), provider_payment_id='PAYBAD')   # monto no cuadra
    with pytest.raises(payments.PaymentIntegrityError):
        payments.process_payment_notification(tx_id=str(tx.id), provider_payment_id='PAYBAD')
    tx.refresh_from_db()
    assert tx.processed_at is None


def test_unknown_tx_returns_none(scenario):
    import uuid
    assert payments.process_payment_notification(
        tx_id=str(uuid.uuid4()), provider_payment_id='X') is None


def test_enrollment_fee_payment_marks_paid(make_organization, make_user):
    org = make_organization()
    payments.connect_callback(code='C', state=payments._sign_state(org.id))
    student = make_user('stu5', organization=org, role='student')
    plan = Plan.objects.create(organization=org, name='M', plan_type='monthly', total_classes=1,
                               unlimited_classes=False, duration_days=30, price=1000.0)
    sp = StudentPlan.objects.create(user=student, plan=plan, start_date='2026-07-01',
                                    end_date='2026-07-30', total_classes=1,
                                    enrollment_fee=Decimal('20000'))
    tx, _ = payments.create_checkout(organization=org, user=student, target_student_plan=sp)
    from core.services.providers import get_payment_provider
    provider = get_payment_provider()
    provider.queue_payment(external_reference=str(tx.id), status=PaymentStatus.APPROVED,
                           amount=Decimal('20000'), provider_payment_id='PAYE')
    payments.process_payment_notification(tx_id=str(tx.id), provider_payment_id='PAYE')
    sp.refresh_from_db()
    assert sp.enrollment_fee_paid_at is not None
```

- [ ] **Step 2: Correr el test (debe fallar)**

Run: `cd backend && python -m pytest core/tests/test_payments_process_webhook.py -v`
Expected: FAIL (AttributeError `process_payment_notification`).

- [ ] **Step 3: Implementar el procesamiento**

En `backend/core/services/payments.py`, agregar:

```python
from django.db import transaction as db_transaction

from .providers.base import PaymentStatus


class PaymentIntegrityError(Exception):
    """El pago no cuadra con la transacción (monto/collector) — posible forja."""


def apply_provider_payment(*, tx, payment):
    """Núcleo idempotente. Debe llamarse por webhook y por reconcile."""
    with db_transaction.atomic():
        tx = PaymentTransaction.objects.select_for_update().get(pk=tx.pk)
        if tx.processed_at is not None:
            return tx   # ya activado: no-op

        account = PaymentAccount.objects.filter(
            organization_id=tx.organization_id, provider=tx.provider).first()
        if (payment.collector_id and account and account.provider_user_id
                and str(payment.collector_id) != str(account.provider_user_id)):
            raise PaymentIntegrityError('collector_id no coincide con la cuenta del gym.')
        if payment.external_reference and str(payment.external_reference) != str(tx.id):
            raise PaymentIntegrityError('external_reference no coincide.')

        tx.provider_payment_id = payment.provider_payment_id
        tx.status = payment.status.value
        tx.status_detail = payment.status_detail
        tx.raw_provider_payload = payment.raw

        if payment.status == PaymentStatus.APPROVED:
            if payment.amount != tx.amount:
                raise PaymentIntegrityError(f'monto {payment.amount} != esperado {tx.amount}')
            from django.utils import timezone
            from .plans import activate_student_plan
            if tx.plan_id:
                sp = activate_student_plan(student=tx.user, plan=tx.plan,
                                           start_date=timezone.localdate())
                tx.student_plan = sp
            elif tx.target_student_plan_id:
                sp = tx.target_student_plan
                sp.enrollment_fee_paid_at = timezone.now()
                sp.save(update_fields=['enrollment_fee_paid_at', 'updated_at'])
                tx.student_plan = sp
            tx.processed_at = timezone.now()

        tx.save()
        return tx


def process_payment_notification(*, tx_id, provider_payment_id):
    tx = PaymentTransaction.objects.filter(id=tx_id).select_related(
        'organization', 'user', 'plan', 'target_student_plan').first()
    if tx is None:
        return None
    account = PaymentAccount.objects.filter(
        organization_id=tx.organization_id, provider=tx.provider).first()
    if account is None:
        return None
    provider = get_payment_provider(tx.provider)
    access_token = get_valid_access_token(account=account)
    payment = provider.fetch_payment(access_token=access_token,
                                     provider_payment_id=provider_payment_id)
    return apply_provider_payment(tx=tx, payment=payment)


def reconcile_transaction(*, tx):
    if tx.provider_payment_id:
        return process_payment_notification(tx_id=tx.id,
                                            provider_payment_id=tx.provider_payment_id)
    return tx
```

- [ ] **Step 4: Correr el test (debe pasar)**

Run: `cd backend && python -m pytest core/tests/test_payments_process_webhook.py -v`
Expected: PASS (7 tests). Nota: en SQLite `select_for_update` es no-op pero la serialización de las conexiones de test + el guard `processed_at` garantizan idempotencia; en Postgres (prod) el lock añade la protección concurrente real.

- [ ] **Step 5: Commit**

```bash
git add backend/core/services/payments.py backend/core/tests/test_payments_process_webhook.py
git commit -m "feat(payments): procesamiento idempotente de pago (activa/renueva o marca matrícula)"
```

---

## Task 14: Endpoint webhook

**Files:**
- Modify: `backend/core/views_payments.py` (agregar `PaymentWebhookView`)
- Modify: `backend/core/urls.py` (ruta webhook)
- Test: `backend/core/tests/test_payments_webhook_api.py`

**Interfaces:**
- Consumes: `get_payment_provider` (para `verify_webhook`/`parse_webhook`), `payments.process_payment_notification`, `WebhookEvent` (bitácora).
- Produces: `POST /api/payments/webhook/` (AllowAny, sin auth, CSRF-exento por no usar SessionAuth): valida firma (401 si inválida), registra `WebhookEvent`, resuelve `tx` por `?tx=`, procesa; responde 200 salvo firma inválida.

- [ ] **Step 1: Escribir el test**

Crear `backend/core/tests/test_payments_webhook_api.py`:

```python
import hashlib
import hmac
import json
from decimal import Decimal

import pytest

from core.models import Plan, PaymentTransaction, StudentPlan, WebhookEvent
from core.services import payments
from core.services.providers.base import PaymentStatus


@pytest.fixture(autouse=True)
def _fake(settings):
    # Firma real la valida el provider MP; para el webhook API usamos el provider MP
    # solo para firma/parseo, pero el fetch lo hace el fake vía process_notification.
    settings.PAYMENTS_PROVIDER = 'fake'
    settings.MP_WEBHOOK_SECRET = 'WH'
    settings.PAYMENTS_ENCRYPTION_KEY = __import__(
        'core.fields', fromlist=['generate_encryption_key']).generate_encryption_key()
    settings.PAYMENTS_APEX_BASE_URL = 'https://app.tymroapp.com'


def _signed(body_dict, secret='WH', request_id='req-1', ts='1720000000'):
    body = json.dumps(body_dict).encode()
    data_id = str(body_dict.get('data', {}).get('id', ''))
    manifest = f'id:{data_id};request-id:{request_id};ts:{ts};'
    v1 = hmac.new(secret.encode(), manifest.encode(), hashlib.sha256).hexdigest()
    return body, {'HTTP_X_SIGNATURE': f'ts={ts},v1={v1}', 'HTTP_X_REQUEST_ID': request_id}


@pytest.fixture
def approved_tx(make_organization, make_user):
    org = make_organization()
    payments.connect_callback(code='C', state=payments._sign_state(org.id))
    student = make_user('stu', organization=org, role='student')
    plan = Plan.objects.create(organization=org, name='M', plan_type='monthly', total_classes=12,
                               unlimited_classes=False, duration_days=30, price=30000.0)
    tx, _ = payments.create_checkout(organization=org, user=student, plan=plan)
    from core.services.providers import get_payment_provider
    get_payment_provider().queue_payment(external_reference=str(tx.id),
                                         status=PaymentStatus.APPROVED, amount=Decimal('30000'),
                                         provider_payment_id='PAY1')
    return org, student, tx


def test_webhook_invalid_signature_401(api_client, settings):
    settings.PAYMENTS_PROVIDER = 'mercadopago'
    body, headers = _signed({'type': 'payment', 'data': {'id': '1'}}, secret='WRONG')
    resp = api_client.post('/api/payments/webhook/?tx=abc', data=body,
                           content_type='application/json', **headers)
    assert resp.status_code == 401
```

> **Nota de estrategia de test:** verificar firma exige el provider MP real, pero `fetch_payment` haría HTTP. Por eso el Step 1 solo prueba el rechazo por firma inválida (401). El test de "firma válida" se agrega en el Step 5 monkeypatcheando `core.views_payments.payments.process_payment_notification` con un doble que registre la llamada, para afirmar que la vista lo invoca con el `tx` del query y el `provider_payment_id` del body. El camino de activación real ya está cubierto por la Task 13.

- [ ] **Step 2: Correr el test (debe fallar)**

Run: `cd backend && python -m pytest core/tests/test_payments_webhook_api.py -v`
Expected: FAIL (404 en `/api/payments/webhook/`).

- [ ] **Step 3: Implementar la view**

En `backend/core/views_payments.py`:

```python
from .models import WebhookEvent
from .services.providers import get_payment_provider


class PaymentWebhookView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []   # sin SessionAuth → sin CSRF

    def post(self, request):
        raw_body = request.body
        provider = get_payment_provider()   # settings.PAYMENTS_PROVIDER
        headers = {k[5:].replace('_', '-').lower(): v
                   for k, v in request.META.items() if k.startswith('HTTP_')}
        if not provider.verify_webhook(headers=headers, raw_body=raw_body):
            return Response({'detail': 'firma inválida'}, status=status.HTTP_401_UNAUTHORIZED)

        env = provider.parse_webhook(headers=headers, raw_body=raw_body)
        WebhookEvent.objects.create(
            provider=provider.name, provider_payment_id=env.provider_payment_id,
            raw_body=raw_body.decode('utf-8', 'replace'),
            headers={'x-request-id': headers.get('x-request-id')},
        )
        if env.type != 'payment' or not env.provider_payment_id:
            return Response(status=status.HTTP_200_OK)   # ack, ignorar

        tx_id = request.GET.get('tx')
        if tx_id:
            try:
                payments.process_payment_notification(
                    tx_id=tx_id, provider_payment_id=env.provider_payment_id)
            except payments.PaymentIntegrityError:
                # No re-encolar: es una inconsistencia, no un fallo transitorio.
                return Response(status=status.HTTP_200_OK)
        return Response(status=status.HTTP_200_OK)
```

- [ ] **Step 4: Montar la ruta**

En `backend/core/urls.py`:

```python
from .views_payments import PaymentWebhookView
# ...
    path('payments/webhook/', PaymentWebhookView.as_view(), name='payments-webhook'),
```

- [ ] **Step 5: Ajustar el test de firma válida (monkeypatch)**

Reemplazar el cuerpo de `test_webhook_valid_signature_activates` por:

```python
def test_webhook_valid_signature_calls_processor(api_client, approved_tx, settings, monkeypatch):
    settings.PAYMENTS_PROVIDER = 'mercadopago'   # firma/parseo reales
    org, student, tx = approved_tx
    calls = {}
    def _fake_process(*, tx_id, provider_payment_id):
        calls['tx_id'] = tx_id
        calls['pid'] = provider_payment_id
        return None
    monkeypatch.setattr('core.views_payments.payments.process_payment_notification', _fake_process)
    body, headers = _signed({'type': 'payment', 'data': {'id': 'PAY1'}})
    resp = api_client.post(f'/api/payments/webhook/?tx={tx.id}', data=body,
                           content_type='application/json', **headers)
    assert resp.status_code == 200
    assert calls == {'tx_id': str(tx.id), 'pid': 'PAY1'}
```

- [ ] **Step 6: Correr el test (debe pasar)**

Run: `cd backend && python -m pytest core/tests/test_payments_webhook_api.py -v`
Expected: PASS (2 tests: firma inválida 401 + firma válida invoca el processor).

- [ ] **Step 7: Commit**

```bash
git add backend/core/views_payments.py backend/core/urls.py backend/core/tests/test_payments_webhook_api.py
git commit -m "feat(payments): endpoint webhook con verificación de firma y bitácora"
```

---

## Task 15: Commands de reconciliación y refresh de tokens

**Files:**
- Create: `backend/core/management/commands/reconcile_payments.py`
- Create: `backend/core/management/commands/refresh_payment_tokens.py`
- Test: `backend/core/tests/test_payments_commands.py`

**Interfaces:**
- Consumes: `payments.reconcile_transaction`, `payments.get_valid_access_token`, `PaymentTransaction`, `PaymentAccount`.
- Produces: `python manage.py reconcile_payments [--minutes N]` (procesa tx `pending`/`in_process` con >N min); `python manage.py refresh_payment_tokens` (refresca cuentas próximas a vencer).

- [ ] **Step 1: Escribir el test**

Crear `backend/core/tests/test_payments_commands.py`:

```python
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.utils import timezone

from core.models import Plan, PaymentAccount, PaymentTransaction, StudentPlan
from core.services import payments
from core.services.providers.base import PaymentStatus


@pytest.fixture(autouse=True)
def _fake(settings):
    settings.PAYMENTS_PROVIDER = 'fake'
    settings.PAYMENTS_ENCRYPTION_KEY = __import__(
        'core.fields', fromlist=['generate_encryption_key']).generate_encryption_key()
    settings.PAYMENTS_APEX_BASE_URL = 'https://app.tymroapp.com'


def test_reconcile_activates_pending_with_known_payment(make_organization, make_user):
    org = make_organization()
    payments.connect_callback(code='C', state=payments._sign_state(org.id))
    student = make_user('stu', organization=org, role='student')
    plan = Plan.objects.create(organization=org, name='M', plan_type='monthly', total_classes=12,
                               unlimited_classes=False, duration_days=30, price=30000.0)
    tx, _ = payments.create_checkout(organization=org, user=student, plan=plan)
    tx.provider_payment_id = 'PAY1'      # como si el webhook lo hubiera anotado pero no activó
    tx.save(update_fields=['provider_payment_id'])
    from core.services.providers import get_payment_provider
    get_payment_provider().queue_payment(external_reference=str(tx.id),
                                         status=PaymentStatus.APPROVED, amount=Decimal('30000'),
                                         provider_payment_id='PAY1')
    # Envejecer la transacción:
    PaymentTransaction.objects.filter(id=tx.id).update(
        created_at=timezone.now() - timedelta(minutes=30))

    call_command('reconcile_payments', '--minutes', '5')

    tx.refresh_from_db()
    assert tx.status == 'approved'
    assert StudentPlan.objects.filter(user=student, is_active=True).count() == 1


def test_refresh_tokens_updates_expiring_account(make_organization):
    org = make_organization()
    acc = payments.connect_callback(code='C', state=payments._sign_state(org.id))
    PaymentAccount.objects.filter(id=acc.id).update(
        token_expires_at=timezone.now() + timedelta(hours=1))   # dentro del margen

    call_command('refresh_payment_tokens')

    acc.refresh_from_db()
    assert acc.access_token == 'fake-access-2'   # refrescado
```

- [ ] **Step 2: Correr el test (debe fallar)**

Run: `cd backend && python -m pytest core/tests/test_payments_commands.py -v`
Expected: FAIL (CommandError: comando desconocido `reconcile_payments`).

- [ ] **Step 3: Implementar `reconcile_payments`**

Crear `backend/core/management/commands/reconcile_payments.py`:

```python
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import PaymentTransaction
from core.services import payments


class Command(BaseCommand):
    help = 'Reconciliar transacciones pendientes contra el proveedor de pago (backstop de webhooks).'

    def add_arguments(self, parser):
        parser.add_argument('--minutes', type=int, default=10,
                            help='Antigüedad mínima (min) de la transacción para reconciliar.')

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(minutes=options['minutes'])
        qs = PaymentTransaction.objects.filter(
            status__in=['pending', 'in_process'], processed_at__isnull=True,
            created_at__lte=cutoff, provider_payment_id__isnull=False,
        )
        done = 0
        for tx in qs.iterator():
            try:
                payments.reconcile_transaction(tx=tx)
                done += 1
            except Exception as exc:   # noqa: BLE001 - loguear y continuar con el resto
                self.stderr.write(f'tx {tx.id}: {exc}')
        self.stdout.write(self.style.SUCCESS(f'Reconciliadas {done} transacciones.'))
```

- [ ] **Step 4: Implementar `refresh_payment_tokens`**

Crear `backend/core/management/commands/refresh_payment_tokens.py`:

```python
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import PaymentAccount
from core.services import payments


class Command(BaseCommand):
    help = 'Refrescar proactivamente tokens OAuth de pago próximos a vencer.'

    def handle(self, *args, **options):
        soon = timezone.now() + payments.REFRESH_MARGIN
        qs = PaymentAccount.objects.filter(
            status=PaymentAccount.STATUS_CONNECTED, token_expires_at__lte=soon)
        ok = 0
        for account in qs.iterator():
            try:
                payments.get_valid_access_token(account=account)
                ok += 1
            except Exception as exc:   # noqa: BLE001
                self.stderr.write(f'account {account.id}: {exc}')
        self.stdout.write(self.style.SUCCESS(f'Refrescadas {ok} cuentas.'))
```

- [ ] **Step 5: Correr el test (debe pasar)**

Run: `cd backend && python -m pytest core/tests/test_payments_commands.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Correr TODA la suite (regresión final)**

Run: `cd backend && python -m pytest -q`
Expected: PASS (toda la suite, incluidos los ~40 tests nuevos de pagos y los existentes).

- [ ] **Step 7: Commit**

```bash
git add backend/core/management/commands/reconcile_payments.py backend/core/management/commands/refresh_payment_tokens.py backend/core/tests/test_payments_commands.py
git commit -m "feat(payments): commands reconcile_payments y refresh_payment_tokens"
```

---

## Task 16: Documentación de sandbox / puesta en marcha

**Files:**
- Create: `backend/docs/payments-mercadopago.md`

**Interfaces:** Ninguna (documentación).

- [ ] **Step 1: Escribir la guía**

Crear `backend/docs/payments-mercadopago.md` con:
- Variables de entorno requeridas (`MP_CLIENT_ID`, `MP_CLIENT_SECRET`, `MP_WEBHOOK_SECRET`, `PAYMENTS_ENCRYPTION_KEY` — generar con `python -c "from core.fields import generate_encryption_key; print(generate_encryption_key())"`, `PAYMENTS_APEX_BASE_URL`, `MP_OAUTH_REDIRECT_URI`).
- Registrar en la app MP: el `redirect_uri` (apex `/api/payments/oauth/callback/`) y la URL de Webhooks + copiar el secret a `MP_WEBHOOK_SECRET`.
- Sandbox: crear test users (vendedor+comprador), conectar el vendedor por OAuth (queda `PaymentAccount.is_sandbox=True`), tarjetas de prueba con nombres mágicos (`APRO`/`OTHE`/`CONT`/rechazos), exponer el webhook con el Cloudflare Tunnel del repo.
- Cron sugerido: `reconcile_payments --minutes 5` cada 5 min; `refresh_payment_tokens` diario.
- Checklist "confirmar contra doc MP vigente": formato del manifest de firma, shape del body del webhook, TTL de tokens, endpoint de test users.

- [ ] **Step 2: Commit**

```bash
git add backend/docs/payments-mercadopago.md
git commit -m "docs(payments): guía de configuración y sandbox de MercadoPago"
```

---

## Self-Review (cobertura del spec)

| Requisito del spec | Tarea(s) |
|---|---|
| §2 Abstracción `PaymentProvider` + DTOs + concreto MP | 3, 5, 9, 12 |
| §2 Fake provider para tests | 3 |
| §3 OAuth por org (state firmado, redirect_uri apex) | 6, 7 |
| §3 Tokens cifrados en reposo | 2, 4 |
| §3 Refresh (lazy + proactivo) | 6, 15 |
| §4 Modelos `PaymentAccount`/`PaymentTransaction`/`WebhookEvent` + migración | 4 |
| §4 Constraints anti-duplicado + índices | 4 |
| §4/§5 `activate_student_plan` reusado por assign y webhook | 8, 13 |
| §5 Flujo de checkout (plan + matrícula) | 10, 11 |
| §5 Activación solo por webhook; back_url informativo | 11 (status), 13, 14 |
| §6 Webhook idempotente (firma, select_for_update, processed_at, cross-checks) | 12, 13, 14 |
| §6 Reconciliación backstop | 13, 15 |
| §6 Sin Celery en piloto (síncrono) | 14 |
| §7 Sandbox / test users / tunnel | 16 |
| §7 Tests (fake, idempotencia, firma, multitenancy) | 3,6,7,10,11,13,14 |
| §8 Alcance piloto | Tasks 1-16 |

**Nota de scope:** Este plan es un solo subsistema cohesivo (integración de pagos) con tareas secuenciales por dependencia. Produce software testeable en cada tarea. No requiere descomponerse en planes separados.
