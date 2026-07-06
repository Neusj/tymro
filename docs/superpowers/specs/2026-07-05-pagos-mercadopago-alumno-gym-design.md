# Diseño: Pagos alumno→gym con MercadoPago (Checkout Pro, OAuth por organización)

- **Fecha:** 2026-07-05
- **Estado:** Borrador para revisión
- **Autor:** Diseño asistido (Claude)
- **Alcance de este doc:** SOLO diseño. No hay código de implementación. Nada del repo se modifica salvo este archivo.

---

## 1. Contexto y objetivo

Hoy TYMRO no tiene ningún flujo de cobro online. El precio del plan (`Plan.price`) y la
matrícula (`StudentPlan.enrollment_fee`) se marcan pagados a mano por un admin. Queremos que
el **alumno pague/renuevе su plan online** y que ese pago **active/renueve automáticamente su
`StudentPlan`**.

Restricciones de negocio (dadas):

- **Cada organización conecta SU PROPIA cuenta de MercadoPago** vía OAuth.
- **TYMRO es dueño de UNA sola aplicación** en MercadoPago (un `client_id` / `client_secret`).
- **El dinero va directo al gym; TYMRO nunca toca fondos** → sin split/comisión (pass-through puro).
- Debe quedar detrás de **una abstracción de proveedor de pago**; MercadoPago es la primera
  implementación concreta, para no amarrarse a un solo proveedor.

Decisiones tomadas en el brainstorming (2026-07-05):

| Decisión | Elección | Consecuencia |
|---|---|---|
| Tipo de checkout | **Checkout Pro (redirect)** | MP hospeda el formulario. Creamos una *preference* y redirigimos. **Sin carga PCI**. |
| Alcance del cobro | **Plan + matrícula (`enrollment_fee`)** | Un checkout puede cubrir precio del plan y/o matrícula. |
| Comisión de plataforma | **Nunca / no ahora (pass-through)** | `marketplace_fee = 0`. La interfaz deja el hook, pero no se implementa split. |

### Hechos del código existente que condicionan el diseño

(Referencias verificadas en el repo — `backend/`, apps `core` y `accounts`.)

- **Multitenant por subdominio** (`OrganizationMiddleware`, [middleware.py](../../../backend/core/middleware.py)),
  pero **el aislamiento de datos NO depende del middleware**: cada `get_queryset`/`perform_*`
  filtra manualmente por `request.user.organization_id` (regla #1 de `backend/CLAUDE.md`).
  → **Todo endpoint de pagos DEBE filtrar por `organization_id` explícitamente.**
- **El webhook de MP llegará al apex (sin subdominio).** No puede resolver el tenant por host;
  lo resolverá por `external_reference` (nuestra transacción).
- **`StudentPlan`** ([models.py:478](../../../backend/core/models.py#L478)) es la membresía del
  alumno. Hoy se crea/renueva vía la acción `assign` de `MembershipPlanViewSet`
  ([views.py:2756](../../../backend/core/views.py#L2756)). **Renovar = crear un `StudentPlan`
  nuevo + desactivar el anterior** (`is_active=False`). No tiene estado de pago ni FK a pasarela.
- **`Plan.price` es `FloatField`** ([models.py:466](../../../backend/core/models.py#L466)) y
  **no hay campo de moneda** (CLP implícito; locale `es-cl`, TZ `America/Santiago`).
- **Gate de pago ya reutilizable:** `enrollment_fee_paid_at` + validación en
  [reservations.py:41](../../../backend/core/services/reservations.py#L41) (bloquea reserva si
  `enrollment_fee > 0` y no pagada). Un pago aprobado seteará `enrollment_fee_paid_at`.
- **No existe patrón de cifrado** de campos sensibles en DB → lo introduce este diseño.
- **No existe patrón de mock HTTP** en tests → lo introduce este diseño (fake provider).
- Ya se usa **Cloudflare Tunnel** en el repo (`CLOUDFLARE_TUNNEL_TOKEN`) → reutilizable para
  recibir webhooks en desarrollo.
- Convención del repo: lógica de negocio en `core/services/`, no en views.

---

## 2. Capa de abstracción: `PaymentProvider`

La meta es que el resto del sistema (modelos, views, services de dominio) **nunca** hable de
MercadoPago directamente. Solo conoce una interfaz y unos DTOs normalizados. MercadoPago vive
aislado en `core/services/providers/mercadopago.py`.

### 2.1 Ubicación de archivos (nueva)

```
backend/core/
├── services/
│   ├── payments.py                 # ORQUESTACIÓN de dominio (connect, checkout, procesar webhook)
│   └── providers/
│       ├── __init__.py             # registry: get_payment_provider(name) -> PaymentProvider
│       ├── base.py                 # PaymentProvider (ABC) + DTOs + enum PaymentStatus
│       ├── mercadopago.py          # implementación concreta MercadoPago
│       └── fake.py                 # FakePaymentProvider para tests (sin HTTP)
```

**Separación de responsabilidades:**
- `providers/base.py` + `providers/mercadopago.py` → **el "cómo" de MP** (HTTP, firmas, formatos).
- `services/payments.py` → **el "qué" del negocio** (crear transacción, activar `StudentPlan`,
  idempotencia). No sabe de HTTP ni de MP.
- `views.py` → HTTP de TYMRO (auth, tenant, serialización), delega en `services/payments.py`.

### 2.2 DTOs normalizados (dataclasses, provider-agnósticos)

```python
# providers/base.py  (PSEUDOCÓDIGO de diseño, no implementación)

class PaymentStatus(str, Enum):     # estado NORMALIZADO de TYMRO
    PENDING   = "pending"
    IN_PROCESS = "in_process"
    APPROVED  = "approved"
    REJECTED  = "rejected"
    CANCELLED = "cancelled"
    REFUNDED  = "refunded"

@dataclass
class OAuthTokens:
    access_token: str
    refresh_token: str
    expires_in: int          # segundos
    provider_user_id: str    # id de la cuenta MP del gym (collector)
    public_key: str | None
    scope: str | None

@dataclass
class CheckoutSession:
    redirect_url: str            # init_point (o sandbox_init_point en test)
    provider_preference_id: str  # id de la preference

@dataclass
class ProviderPayment:            # resultado de consultar un pago
    provider_payment_id: str
    status: PaymentStatus
    status_detail: str | None
    amount: Decimal
    currency: str
    external_reference: str       # nuestro PaymentTransaction.id (UUID)
    collector_id: str | None      # id de la cuenta que recibió (para cross-check con el gym)
    raw: dict                      # payload crudo para auditoría

@dataclass
class WebhookEnvelope:
    type: str                     # "payment", "merchant_order", ...
    action: str | None            # "payment.created" / "payment.updated"
    provider_payment_id: str | None
```

### 2.3 La interfaz

```python
class PaymentProvider(ABC):
    name: str  # "mercadopago"

    # --- OAuth / conexión de cuenta ---
    def get_authorization_url(self, *, state: str, redirect_uri: str) -> str: ...
    def exchange_code(self, *, code: str, redirect_uri: str) -> OAuthTokens: ...
    def refresh_tokens(self, *, refresh_token: str) -> OAuthTokens: ...

    # --- Cobro ---
    def create_checkout(
        self, *, access_token: str, external_reference: str,
        items: list[CheckoutItem], payer_email: str | None,
        back_urls: BackUrls, notification_url: str, expires_at: datetime | None,
    ) -> CheckoutSession: ...

    def fetch_payment(self, *, access_token: str, provider_payment_id: str) -> ProviderPayment: ...

    # --- Webhook ---
    def verify_webhook(self, *, headers: Mapping[str, str], raw_body: bytes) -> bool: ...
    def parse_webhook(self, *, headers: Mapping[str, str], raw_body: bytes) -> WebhookEnvelope: ...
```

**Qué queda fuera de la interfaz a propósito (YAGNI):** refunds, cancelaciones, suscripciones,
split/comisión, giftcards. Se agregan como métodos nuevos cuando lleguen (fase 2). Añadir un
proveedor nuevo (Transbank, Fintoc, Stripe) = una clase nueva que implemente esta interfaz +
registrarla; nada del dominio cambia.

**Contrato clave del enum:** cada provider mapea sus estados crudos → `PaymentStatus`. MercadoPago:
`approved→APPROVED`, `pending→PENDING`, `in_process/authorized→IN_PROCESS`,
`rejected→REJECTED`, `cancelled→CANCELLED`, `refunded/charged_back→REFUNDED`.

---

## 3. OAuth por organización (multitenant)

### 3.1 Modelo mental

- **Una** app MercadoPago propiedad de TYMRO → un `MP_CLIENT_ID` / `MP_CLIENT_SECRET`
  (env vars, nunca en DB ni en código).
- **Un** `redirect_uri` global registrado en la app MP:
  `https://app.tymroapp.com/api/payments/oauth/callback` (apex, no subdominio — MP exige URL fija).
- El **tenant se transporta en el parámetro `state`** (firmado), no en el host ni en el path.
- Cada gym que autoriza produce **un `PaymentAccount` por organización** con sus tokens.

> **Verificar contra la doc vigente de MP al implementar:** endpoint exacto de autorización
> (`https://auth.mercadopago.cl/authorization`), soporte/obligatoriedad de PKCE
> (`code_challenge`/`code_verifier`), y los **TTL reales** de `access_token`/`refresh_token`
> (históricamente ~180 días el access; el refresh rota en cada uso). El diseño no depende del
> valor exacto: usamos `expires_in` que devuelve MP.

### 3.2 Flujo connect (gym_admin conecta su cuenta)

```
gym_admin (logueado en <gym>.tymroapp.com)
  │  1. POST /api/payments/connect/           (rol: gym_admin | superadmin, filtra por org)
  ▼
TYMRO backend
  │  genera state = signing.dumps({org_id, nonce}, salt="mp-oauth")  [TTL ~10 min]
  │  arma authorization_url(state, redirect_uri global)
  │  devuelve {authorization_url}
  ▼
Frontend redirige al gym owner a MercadoPago
  │  el dueño del gym inicia sesión EN SU cuenta MP y autoriza la app TYMRO
  ▼
MP redirige a  https://app.tymroapp.com/api/payments/oauth/callback?code=...&state=...
  │  2. GET  /api/payments/oauth/callback     (AllowAny; apex; en allowlist del middleware)
  ▼
TYMRO backend (services/payments.connect_callback)
  │  - signing.loads(state) → valida firma + TTL → obtiene org_id  (rechaza si inválido)
  │  - provider.exchange_code(code, redirect_uri) → OAuthTokens
  │  - upsert PaymentAccount(org) con tokens CIFRADOS + provider_user_id + expires_at
  │  - redirige al gym a  https://<gym>.tymroapp.com/ajustes/pagos?connected=1
  ▼
Cuenta conectada. El gym ya puede recibir cobros.
```

Por qué `state` firmado: el callback llega al apex sin sesión ni subdominio; `state` es la
**única** fuente confiable del tenant. Se firma con `django.core.signing` (patrón ya usado en el
repo para QR de asistencia) e incluye un `nonce` + TTL corto para mitigar replay/CSRF.

### 3.3 Almacenamiento de tokens: cifrado en reposo

No hay patrón previo → se introduce uno mínimo y explícito:

- Dependencia nueva: `cryptography` (Fernet).
- Env var nueva: `PAYMENTS_ENCRYPTION_KEY` (clave Fernet base64, **distinta** de `SECRET_KEY`).
  Rotación soportada con `MultiFernet` (lista de claves; la primera cifra, todas descifran).
- `access_token` y `refresh_token` se guardan como **texto cifrado** en columnas `TextField`.
  Se descifran solo en memoria, justo antes de llamar a MP.
- Implementación sugerida: un `EncryptedTextField` fino (subclase de `TextField` que cifra en
  `get_prep_value` y descifra en `from_db_value`) para que el modelo lo maneje transparentemente.
- `public_key` de MP **no es secreto** → texto plano.

> Si `PAYMENTS_ENCRYPTION_KEY` falta en prod (DEBUG=False), la app debe fallar al arrancar
> (mismo criterio que `SECRET_KEY` hoy en `settings.py`).

### 3.4 Refresh de token

- **Perezoso (lazy):** antes de cada uso del token (crear checkout, consultar pago), si
  `token_expires_at` está vencido o dentro de un margen (p.ej. < 24 h), se llama
  `provider.refresh_tokens(refresh_token)` y se persisten **ambos** tokens nuevos + nuevo
  `expires_at`. MP rota el refresh_token, así que hay que guardar el nuevo.
- **Proactivo (backstop):** management command `refresh_payment_tokens` (cron diario) que
  refresca cuentas con `token_expires_at` próximo a vencer. Evita que una cuenta inactiva mucho
  tiempo pierda la conexión.
- Si el refresh falla (revocado por el gym): marcar `PaymentAccount.status = "disconnected"`,
  notificar al gym_admin y bloquear nuevos checkouts con un error claro.

---

## 4. Modelo de datos nuevo

Dos modelos nuevos en `core/models.py`, ambos con `organization` FK (aislamiento multitenant).

### 4.1 `PaymentAccount` (conexión OAuth del gym)

| Campo | Tipo | Notas |
|---|---|---|
| `organization` | FK Organization | `unique_together (organization, provider)` |
| `provider` | Char(choices) | `"mercadopago"` |
| `provider_user_id` | Char | id de la cuenta MP del gym (collector). Cross-check en webhook. |
| `access_token` | EncryptedText | cifrado en reposo |
| `refresh_token` | EncryptedText | cifrado en reposo |
| `public_key` | Char (null) | no secreto |
| `scope` | Char (null) | |
| `token_expires_at` | DateTime | para refresh lazy/proactivo |
| `status` | Char(choices) | `connected` / `disconnected` |
| `is_sandbox` | Bool | cuenta de prueba vs real |
| `connected_at` | DateTime | |
| `created_at/updated_at` | (TimestampedModel) | |

### 4.2 `PaymentTransaction` (cada intento de cobro del alumno)

| Campo | Tipo | Notas |
|---|---|---|
| `id` | **UUIDField (PK)** | Se usa como `external_reference` en MP → resuelve tenant + idempotencia |
| `organization` | FK Organization | denormalizado; filtrado multitenant y cross-check |
| `user` | FK CustomUser | el alumno |
| `provider` | Char(choices) | `"mercadopago"` |
| `provider_preference_id` | Char (null) | id de la preference |
| `provider_payment_id` | Char (null) | id del pago MP; se llena en el webhook |
| `status` | Char(choices) = `PaymentStatus` | estado NORMALIZado interno |
| `status_detail` | Char (null) | detalle crudo del proveedor |
| `currency` | Char(3) default `"CLP"` | |
| `plan` | FK Plan (null) | plan que se compra/renueva (si aplica) |
| `plan_amount` | Decimal(10,2) | precio del plan cobrado (0 si solo matrícula) |
| `enrollment_fee_amount` | Decimal(10,2) | matrícula cobrada (0 si no aplica) |
| `amount` | Decimal(10,2) | total = plan_amount + enrollment_fee_amount |
| `target_student_plan` | FK StudentPlan (null) | para cobro de matrícula sobre un plan existente |
| `student_plan` | FK StudentPlan (null) | el StudentPlan creado/renovado al aprobar (idempotencia) |
| `processed_at` | DateTime (null) | **marca de activación aplicada** (guard de exactly-once) |
| `metadata` | JSON | snapshot: items, descuento, quién inició, etc. |
| `raw_provider_payload` | JSON (null) | último payload de MP (auditoría) |
| `created_at/updated_at` | (TimestampedModel) | |

**Constraints e índices (clave para 300 pagos en lote):**

- `UniqueConstraint(fields=["provider", "provider_payment_id"], condition=Q(provider_payment_id__isnull=False), name="uniq_provider_payment")`
  → **el mismo pago MP no puede procesarse dos veces**, aunque lleguen webhooks duplicados.
- Índices: `(organization, status)`, `(user, status)`, `provider_preference_id`.

**Sobre la moneda/monto:** `Plan.price` es `Float` (deuda técnica existente). En la **frontera**
convertimos a `Decimal` y redondeamos a **entero CLP** (CLP no usa decimales) para armar el monto
que se manda a MP y se guarda en `amount`. **No** cambiamos `Plan.price` en el piloto.

### 4.3 (Opcional) `WebhookEvent` — bitácora de entrada

Registro append-only de cada notificación recibida (raw body, headers relevantes,
`provider_payment_id`, resultado del procesamiento, timestamp). Sirve para auditoría, depuración y
**replay** manual. No es imprescindible para la corrección (la idempotencia vive en
`PaymentTransaction`), pero se recomienda incluirlo por confiabilidad. Barato.

### 4.4 Migraciones

- Django migrations estándar, una migración nueva en `backend/core/migrations/` siguiendo la
  numeración (`0025_paymentaccount_paymenttransaction.py`).
- Solo **agrega** tablas y (opcional) el `WebhookEvent`. **No toca** `StudentPlan` ni `Plan` →
  migración aditiva, sin riesgo sobre datos existentes.
- Si se adopta el `EncryptedTextField`, las columnas son `TextField` a nivel DB (el cifrado es de
  aplicación); no requiere extensión de Postgres.

### 4.5 Relación con `StudentPlan` (sin romper lo existente)

`PaymentTransaction` es la **capa de cobro**; `StudentPlan` sigue siendo la **capa de membresía**.
El pago aprobado **dispara** la misma operación que hoy hace `assign` (crear `StudentPlan` nuevo +
desactivar el anterior). Se **extrae esa lógica** de la acción `assign` a una función reutilizable
en `services/` (p.ej. `activate_student_plan(...)`) para que la usen tanto el admin (manual) como
el webhook (automático). Así hay **una sola** fuente de verdad para "activar plan".

---

## 5. Flujo de cobro (compra/renovación)

```
Alumno logueado en <gym>.tymroapp.com, elige un Plan público (is_public=True)
  │  1. POST /api/payments/checkout/  { plan_id, include_enrollment_fee? }
  ▼
services/payments.create_checkout(org, user, plan, ...)
  │  - valida: plan pertenece a la org y es público/activo; usuario es alumno de la org
  │  - carga PaymentAccount de la org (status=connected); refresh lazy si hace falta
  │  - calcula montos (plan_amount, enrollment_fee_amount) en Decimal→entero CLP
  │  - crea PaymentTransaction(status=PENDING, id=UUID)   ← external_reference
  │  - provider.create_checkout(access_token=gym, external_reference=tx.id,
  │        items=[...], notification_url=APEX/api/payments/webhook,
  │        back_urls={success,pending,failure}, expires_at=+30min)
  │  - guarda provider_preference_id; devuelve {redirect_url, transaction_id}
  ▼
Frontend redirige al alumno a  redirect_url (checkout.mercadopago.cl / init_point)
  │  el alumno paga (tarjeta, débito, transferencia, etc. — MP hospeda)
  ▼
  ├─(async, autoritativo)→ MP llama WEBHOOK  →  §6  →  activa StudentPlan
  └─(sync, informativo)  → MP redirige a back_url success/pending/failure
                            el front hace polling a GET /api/payments/transactions/{id}/status/
                            (lee estado; NO activa nada por sí mismo)
```

**Puntos de diseño importantes:**

1. **La activación ocurre SOLO por el webhook (o el reconcile de §6.4).** El `back_url` es puramente
   informativo. Razón: el `back_url` es manipulable por el cliente y puede no ejecutarse (cierra la
   pestaña). Tener **una sola** ruta de activación evita doble-activación y estados inconsistentes.
2. **Un checkout puede cubrir plan + matrícula** como dos `items` en la misma preference. Al
   aprobar:
   - Si `plan` está seteado → `activate_student_plan(...)` crea el `StudentPlan` nuevo (copia
     `total_classes`, `duration_days`, etc. del `Plan`, aplica descuento). Si
     `enrollment_fee_amount > 0` → setea `enrollment_fee_paid_at = now` en ese plan nuevo.
   - Si es **solo matrícula** sobre un plan existente (`target_student_plan`) → setea
     `enrollment_fee_paid_at = now` en ese `StudentPlan`.
3. **Renovación** = mismo flujo; `activate_student_plan` desactiva el `StudentPlan` activo previo y
   crea el nuevo (idéntico a `assign` hoy).
4. **Expiración de preference** (`expires_at`): si el alumno no paga, la transacción queda `PENDING`
   y el reconcile la marca `CANCELLED` pasado el tiempo. No ensucia el estado del alumno.

---

## 6. Webhook idempotente y confiable (crítico: 300 alumnos en lote)

### 6.1 Endpoint

- `POST /api/payments/webhook/` — `AllowAny`, en el **apex**, agregado al **allowlist del
  `OrganizationMiddleware`** (junto con `/api/payments/oauth/callback`) para que no exija subdominio.
- Responde **rápido** (MP reintenta si no recibe 2xx dentro de la ventana). Debe devolver 200
  apenas la notificación quede procesada o se descarte de forma segura.

### 6.2 Validación de autenticidad (firma)

MP firma la notificación con un header **`x-signature`** (partes `ts` y `v1`) + `x-request-id`.
Se reconstruye un *manifest* y se calcula **HMAC-SHA256** con el **secret de webhook de la app**
(env var global `MP_WEBHOOK_SECRET`, ya que TYMRO tiene una sola app), y se compara con `v1` en
tiempo constante.

> **Verificar contra la doc vigente de MP al implementar:** el **string exacto** del manifest
> (orden y nombres de los campos `id`, `request-id`, `ts`) y el nombre exacto de los headers. El
> diseño fija el **enfoque** (HMAC-SHA256 con secret de app, comparación constante); el formato
> literal se confirma al implementar. `verify_webhook()` encapsula este detalle en el provider MP.

- Firma inválida → **401**, se registra (posible intento de forja). No se procesa.
- El `MP_WEBHOOK_SECRET` es **de la aplicación** (global), no por-org, porque todas las preferences
  se crean con el `client_id` de TYMRO. (A confirmar en la config de Webhooks del dashboard MP.)

### 6.3 Procesamiento idempotente (evitar doble-activación)

Regla de oro: **el body del webhook NO es confiable como fuente del estado**. Solo trae un
`data.id` (id de pago). Siempre **consultamos el estado canónico** a MP y aplicamos con guardas.

```
POST /api/payments/webhook/
  0. verify_webhook(headers, raw_body)               → si falla: 401
  1. (opcional) persistir WebhookEvent(raw)          → auditoría/replay
  2. env = parse_webhook(...)  ; si env.type != "payment" → 200 (ack, ignorar en piloto)
  3. payment = provider.fetch_payment(access_token=<token de la org>, id=env.provider_payment_id)
        (para elegir la org: primero external_reference→tx→org; ver nota abajo)
  4. tx = PaymentTransaction.objects.get(id=payment.external_reference)   → 200 si no existe
  5. with transaction.atomic():
         tx = PaymentTransaction.objects.select_for_update().get(pk=tx.pk)   # LOCK de fila
         if tx.processed_at is not None:                 # ya activado → no-op
             return 200
         # cross-checks de seguridad:
         assert payment.collector_id == tx.organization.payment_account.provider_user_id
         assert payment.amount == tx.amount and payment.currency == tx.currency
         tx.provider_payment_id = payment.provider_payment_id   # UniqueConstraint anti-duplicado
         tx.status = payment.status
         tx.status_detail = payment.status_detail
         tx.raw_provider_payload = payment.raw
         if payment.status == APPROVED:
             sp = activate_student_plan(tx)               # crea/renueva o marca matrícula
             tx.student_plan = sp
             tx.processed_at = now()
         tx.save()
  6. return 200
```

**Por qué esto es exactly-once bajo carga:**

- **`select_for_update()`** serializa el procesamiento por transacción: si llegan 2 webhooks del
  mismo pago a la vez, uno espera al otro; el segundo ve `processed_at` seteado y sale sin activar.
- **`processed_at`** es el guard idempotente: la activación (crear `StudentPlan`) corre **una sola
  vez** por transacción. Nunca se crean dos `StudentPlan` para el mismo pago.
- **`UniqueConstraint(provider, provider_payment_id)`** es la red de seguridad a nivel DB: si por
  cualquier camino se intentara asociar dos veces el mismo pago, la DB lo rechaza.
- **Consultar el estado canónico** (paso 3) evita actuar sobre payloads viejos/duplicados/fuera de
  orden (MP manda `payment.created` y luego `payment.updated`).
- **Cross-check `collector_id` y `amount`**: rechaza `external_reference` forjados o montos que no
  cuadran → un webhook no puede activar el plan de otra org ni por otro monto.

> **Nota sobre "qué token uso para consultar el pago" (paso 3):** el `fetch_payment` necesita el
> access_token del gym dueño del pago. Resolvemos primero la transacción por `external_reference`
> (que trae la org) y usamos el token de **esa** org; luego cruzamos `collector_id`. Como el body
> firmado por MP (paso 0) ya está validado, `data.id` es confiable; y `external_reference` se
> confirma contra el `collector_id`. Si MP no incluyera `external_reference` en el body del webhook
> (solo `data.id`), se consulta el pago con un barrido corto o se usa el `WebhookEvent`/reconcile;
> a confirmar el shape exacto del body en la doc de MP.

### 6.4 Reconciliación (backstop de confiabilidad)

Los webhooks pueden perderse (caída, deploy, timeout). Management command
`reconcile_payments` (cron cada ~5 min):

- Toma `PaymentTransaction` en `PENDING`/`IN_PROCESS` con cierta antigüedad.
- Consulta su estado real a MP (`fetch_payment` por `provider_payment_id`, o búsqueda por
  `external_reference`).
- Aplica **el mismo** procesamiento idempotente de §6.3 (misma función que el webhook).
- Marca `CANCELLED` las que expiraron sin pago.

Esto convierte el sistema en **eventualmente consistente y auto-sanable**: aunque un webhook falle,
el reconcile activa el plan en la siguiente pasada. Dado el escenario de 300 pagos en lote, se
recomienda incluir el reconcile en el piloto (barato y de alto valor).

### 6.5 ¿Y una cola (Celery)?

El repo **no** tiene Celery/broker. Para el piloto, el procesamiento **síncrono** dentro del
request es aceptable: cada webhook hace 1 llamada saliente a MP + 1 transacción DB corta, y gunicorn
absorbe la ráfaga. La **idempotencia + reconcile** dan la confiabilidad, no la cola. Introducir
Celery es **fase 2** (si el volumen lo pide). Se documenta como decisión explícita para no
sobre-ingenierizar.

---

## 7. Sandbox / pruebas sin cuenta real

MercadoPago permite probar el flujo completo con **usuarios de prueba** (no requiere cuentas reales
ni dinero):

1. **Crear usuarios de prueba** vía API MP (`POST /users/test_user`, `site_id = MLC` para Chile):
   uno **vendedor de prueba** (hace de "gym") y uno **comprador de prueba** (hace de "alumno").
   Devuelven email/clave de acceso.
2. **Conectar el vendedor de prueba por OAuth**: se inicia sesión con el usuario de prueba vendedor
   y se autoriza la app TYMRO → obtenemos **credenciales de prueba** que se guardan en un
   `PaymentAccount` con `is_sandbox=True`, ligado a una **organización de prueba**.
3. **Pagar con tarjetas de prueba**: MP publica tarjetas de test y se fuerza el resultado con el
   **nombre del titular** (`APRO` = aprobado, `OTHE`/`CONT` = pendiente, `FUND/SECU/EXPI/FORM` =
   distintos rechazos). Permite ejercitar approved/pending/rejected sin dinero real.
4. **Recibir webhooks en local**: se reutiliza el **Cloudflare Tunnel** del repo
   (`CLOUDFLARE_TUNNEL_TOKEN`) para exponer el backend y que MP alcance
   `/api/payments/webhook/`. Alternativa: botón "simular notificación" del dashboard MP.
5. **Distinguir test de real**: `PaymentAccount.is_sandbox` + el flag `live_mode` que viene en los
   objetos de MP. En el piloto conviven una **org de prueba** (sandbox) y las orgs reales.

> **Verificar contra la doc vigente:** endpoint exacto de creación de test users y catálogo actual
> de tarjetas/nombres mágicos.

### 7.1 Tests automatizados (pytest)

El repo no tiene mock de HTTP. Estrategia alineada al estilo del repo:

- **`FakePaymentProvider`** (`providers/fake.py`): implementa `PaymentProvider` en memoria
  (devuelve tokens/pagos deterministas, permite simular approved/rejected). El registry
  `get_payment_provider` se parametriza por settings para que los tests inyecten el fake — igual
  que hoy se hace `monkeypatch` de constantes de módulo.
- **Tests de servicio** (`services/payments`): con el fake, cubrir: crear checkout, activar plan al
  aprobar, renovación (desactiva el previo), matrícula, y **la idempotencia** (procesar el mismo
  pago 2×/concurrente → un solo `StudentPlan`, `processed_at` intacto).
- **Tests unitarios del provider MP**: `verify_webhook` con vectores de firma conocidos
  (HMAC calculado a mano) — sin red. Mapeo de estados MP→`PaymentStatus`.
- **(Opcional)** añadir `responses`/`requests-mock` a `requirements-dev.txt` para testear la capa
  HTTP de `mercadopago.py` de forma aislada.
- **Seguridad/multitenancy**: test de que un webhook con `external_reference` de otra org (o
  `collector_id` que no cuadra) **no** activa nada; y que los endpoints `checkout`/`connect`
  filtran por `organization_id` (reutilizar el patrón de `test_multitenant`).

---

## 8. Alcance mínimo del piloto vs fase 2

### Piloto (fase 1) — lo que entra

- [ ] Abstracción `PaymentProvider` + DTOs + `PaymentStatus` (`providers/base.py`).
- [ ] Implementación concreta **MercadoPago** (`providers/mercadopago.py`): OAuth, create_checkout
      (Checkout Pro), fetch_payment, verify/parse webhook.
- [ ] `FakePaymentProvider` + registry parametrizable.
- [ ] Cifrado en reposo (`EncryptedTextField` + `PAYMENTS_ENCRYPTION_KEY`).
- [ ] Modelos `PaymentAccount`, `PaymentTransaction` (+ `WebhookEvent` opcional) + migración aditiva.
- [ ] Flujo OAuth connect: `POST /connect/` + `GET /oauth/callback/` (state firmado, multitenant).
- [ ] Refresh de token: lazy + command `refresh_payment_tokens`.
- [ ] Flujo de cobro: `POST /checkout/` (plan + matrícula) → Checkout Pro → redirect.
- [ ] Webhook idempotente `POST /webhook/` (firma, select_for_update, processed_at, cross-checks).
- [ ] Extraer `activate_student_plan(...)` a `services/` y reusarlo en `assign` y en el webhook.
- [ ] Endpoint de estado `GET /transactions/{id}/status/` para el back_url del front.
- [ ] Command `reconcile_payments` (backstop).
- [ ] Allowlist del middleware para `/api/payments/webhook` y `/api/payments/oauth/callback`.
- [ ] Sandbox con test users + tests (fake provider, idempotencia, firma, multitenancy).

### Fase 2 — lo que queda fuera a propósito

- Comisión/split de plataforma (marketplace_fee) — la interfaz ya deja el hueco.
- Refunds, contracargos y cancelaciones desde UI.
- Otros `plan_type`: giftcard, single_class, packs; cuotas/installments; **suscripciones**
  (preapproval de MP para auto-renovación en vez de renovación manual).
- Otros proveedores (Transbank, Fintoc, Stripe) sobre la misma abstracción.
- Cola/worker (Celery) + panel de reintentos si el volumen lo exige.
- Checkout transparente (Bricks) para pagar sin salir de TYMRO.
- Links de cobro generados por el admin; historial de pagos / boletas / emails de recibo.
- Panel de conciliación y reportes de ingresos para el gym.

---

## 9. Endpoints nuevos (resumen)

| Método | Ruta | Auth | Propósito |
|---|---|---|---|
| POST | `/api/payments/connect/` | gym_admin / superadmin (por org) | Inicia OAuth; devuelve `authorization_url` |
| GET | `/api/payments/oauth/callback/` | AllowAny (apex, allowlist) | Recibe `code`+`state`, guarda `PaymentAccount` |
| GET | `/api/payments/account/` | gym_admin / superadmin (por org) | Estado de conexión de la org |
| POST | `/api/payments/checkout/` | alumno de la org | Crea `PaymentTransaction` + preference; devuelve `redirect_url` |
| GET | `/api/payments/transactions/{id}/status/` | dueño de la tx (por org) | Estado para el back_url (informativo) |
| POST | `/api/payments/webhook/` | AllowAny (apex, allowlist, firma) | Notificaciones de MP; activa el plan |

Todos los endpoints con datos de tenant **filtran por `request.user.organization_id`**; el webhook
y el callback resuelven la org por `external_reference`/`state` respectivamente (nunca por host).

---

## 10. Riesgos y puntos a confirmar

1. **Formato exacto de firma del webhook** (manifest `x-signature`) y **shape del body** (¿incluye
   `external_reference`?) — confirmar contra doc vigente de MP.
2. **TTL reales** de access/refresh token y **obligatoriedad de PKCE** en el OAuth de MP Chile.
3. **`MP_WEBHOOK_SECRET` a nivel app** (uno global) vs por-cuenta — confirmar en dashboard MP.
4. **Endpoint de test users** y catálogo de tarjetas de prueba vigente.
5. **Moneda:** `Plan.price` es `Float` → tratar como `Decimal`/entero CLP en la frontera; deuda
   técnica a no propagar.
6. **Redirect_uri fijo** en apex: requiere que el certificado/routing del apex esté disponible
   (independiente del wildcard de subdominios pendiente para prod).

---

## Apéndice A — Diagrama de componentes

```
                         ┌─────────────────────────────────────────────┐
   Frontend (gym sub)    │                 core/views.py               │
   ─ conectar MP ───────▶│  ConnectView / OAuthCallbackView            │
   ─ comprar plan ──────▶│  CheckoutView / TransactionStatusView       │
                         │  WebhookView (AllowAny)                     │
                         └───────────────┬─────────────────────────────┘
                                         │ delega
                                         ▼
                         ┌─────────────────────────────────────────────┐
                         │        core/services/payments.py            │
                         │  connect_callback() / create_checkout()     │
                         │  process_webhook() / reconcile()            │
                         │  activate_student_plan()  ◀── reusa assign  │
                         └───────┬──────────────────────────┬──────────┘
                                 │ usa                       │ escribe
                                 ▼                           ▼
             ┌───────────────────────────────┐   ┌──────────────────────────┐
             │  providers/  (abstracción)     │   │  models: PaymentAccount, │
             │  base.PaymentProvider (ABC)    │   │  PaymentTransaction,     │
             │  ├─ mercadopago.py (concreto)  │   │  (WebhookEvent), y        │
             │  └─ fake.py (tests)            │   │  StudentPlan (existente) │
             └───────────────┬───────────────┘   └──────────────────────────┘
                             │ HTTP
                             ▼
                    ┌──────────────────┐
                    │   MercadoPago    │  (cuenta del gym vía OAuth; dinero directo al gym)
                    └──────────────────┘
```
