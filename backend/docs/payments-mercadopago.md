# Pagos con MercadoPago — configuración y sandbox

Guía operativa para poner en marcha el cobro online (alumno → gym) con MercadoPago
Checkout Pro. Cada organización conecta **su propia** cuenta de MercadoPago vía OAuth;
TYMRO usa **una sola app** en MercadoPago (un `client_id`/`client_secret` para todas las
orgs) y **nunca toca el dinero** (pass-through puro, sin split/comisión).

Código relevante: `backend/core/services/payments.py` (orquestación),
`backend/core/services/providers/` (abstracción `PaymentProvider` + implementación
`mercadopago.py` + `fake.py` para tests), `backend/core/views_payments.py` (endpoints),
`backend/core/fields.py` (cifrado de tokens).

## 1. Variables de entorno

Todas se leen en `backend/tymro/settings.py` vía `os.getenv`:

| Variable | Default | Descripción |
|---|---|---|
| `PAYMENTS_PROVIDER` | `mercadopago` | Nombre del proveedor activo (registry `get_payment_provider`). |
| `PAYMENTS_ENCRYPTION_KEY` | *(vacío)* | Clave Fernet para cifrar `access_token`/`refresh_token` en reposo. Soporta **rotación**: varias claves separadas por coma (la primera cifra, todas descifran vía `MultiFernet`). |
| `PAYMENTS_APEX_BASE_URL` | `http://localhost:8000` | Base pública del **apex** (sin subdominio) usada para armar el callback OAuth y la `notification_url` del webhook. |
| `MP_CLIENT_ID` | *(vacío)* | Client ID de la app MercadoPago de TYMRO. |
| `MP_CLIENT_SECRET` | *(vacío)* | Client secret de esa app. |
| `MP_WEBHOOK_SECRET` | *(vacío)* | Secret de firma de webhooks de la app (uno solo, global — no es por organización). |
| `MP_OAUTH_REDIRECT_URI` | `{PAYMENTS_APEX_BASE_URL}/api/payments/oauth/callback/` | Redirect URI que se envía a MP en el flujo OAuth. Debe coincidir **exactamente** con el registrado en la app MP. |

Generar `PAYMENTS_ENCRYPTION_KEY`:

```bash
cd backend
python -c "from core.fields import generate_encryption_key; print(generate_encryption_key())"
```

**Fail-fast en producción:** si `DEBUG=False` y falta cualquiera de
`PAYMENTS_ENCRYPTION_KEY`, `MP_CLIENT_ID`, `MP_CLIENT_SECRET` o `MP_WEBHOOK_SECRET`, el
proceso Django **no arranca** (`ImproperlyConfigured` en `settings.py`). En desarrollo
(`DEBUG=True`) no es obligatorio, pero sin `PAYMENTS_ENCRYPTION_KEY` cualquier operación
sobre `PaymentAccount` falla al leer/escribir los tokens cifrados.

## 2. Configuración en el panel de MercadoPago

En la app de MercadoPago que usa TYMRO (una sola, propiedad de la plataforma):

1. **Redirect URI (OAuth):** registrar exactamente una:
   `{PAYMENTS_APEX_BASE_URL}/api/payments/oauth/callback/`
   (ej. `https://tymroapp.com/api/payments/oauth/callback/`). El tenant no viaja en la
   URL ni en el host: viaja en el parámetro `state`, firmado con `django.core.signing`
   (TTL de 10 minutos, salt `payments-oauth`).
2. **URL de Webhooks:** configurar
   `{PAYMENTS_APEX_BASE_URL}/api/payments/webhook/`
   (ej. `https://tymroapp.com/api/payments/webhook/`).
3. Copiar el **signature secret** que MP genera para esa configuración de Webhooks a
   `MP_WEBHOOK_SECRET`.

Tanto el callback como el webhook llegan al **apex, sin subdominio** (MP no puede
resolver el tenant por host). El middleware de multitenancy (`OrganizationMiddleware`)
tiene ambas rutas en su allowlist (`backend/core/middleware.py`), así que no exigen
subdominio para resolver.

## 3. Endpoints

| Método | Ruta | Quién | Qué hace |
|---|---|---|---|
| `POST` | `/api/payments/connect/` | `gym_admin` / `superadmin` (de la org del usuario) | Genera la `authorization_url` de MP para iniciar el OAuth. |
| `GET` | `/api/payments/oauth/callback/` | `AllowAny` (apex) | Recibe `code`+`state` de MP, valida el `state`, intercambia el código y guarda/actualiza el `PaymentAccount` de la org. Redirige al frontend a `/ajustes/pagos?connected=1|0`. |
| `GET` | `/api/payments/account/` | `gym_admin` / `superadmin` | Estado de la conexión de pagos de la org (`connected`/`disconnected`, `is_sandbox`, `token_expires_at`, etc.). |
| `POST` | `/api/payments/checkout/` | Alumno (`student`) | Crea una `PaymentTransaction` y una preference de Checkout Pro. Body: **exactamente uno** de `{"plan_id": <id>}` o `{"target_student_plan_id": <id>}`. Responde `{transaction_id, redirect_url}`. |
| `GET` | `/api/payments/transactions/<uuid>/status/` | Dueño de la transacción (mismo `user` + `organization`) | Estado informativo (`status`, `status_detail`, `amount`, `currency`) para el polling del frontend tras volver del `back_url`. |
| `POST` | `/api/payments/webhook/?tx=<uuid>` | `AllowAny` (apex, firma obligatoria) | Recibe la notificación de MP, verifica firma, y dispara la activación/renovación idempotente. |

Todos los endpoints con datos de tenant filtran por `organization_id` del usuario
autenticado; el callback y el webhook resuelven la organización por `state` y por la
transacción (`?tx=`), nunca por el host.

## 4. Flujo de cobro

1. El alumno elige un plan (o tiene una matrícula pendiente) y el frontend llama
   `POST /api/payments/checkout/`.
2. `create_checkout` valida que la organización tenga un `PaymentAccount` conectado,
   calcula el monto (CLP, redondeado a entero) y crea la preference de MercadoPago
   usando el **access token del gym** (no el de TYMRO). La `notification_url` de la
   preference incluye `?tx=<id de la transacción>`.
3. El frontend redirige al alumno a la URL de Checkout Pro (`init_point`). MP hospeda el
   formulario de pago completo — TYMRO nunca ve datos de tarjeta.
4. Tras pagar, ocurren dos cosas en paralelo:
   - **Asíncrono y autoritativo:** MP llama al webhook (`POST /api/payments/webhook/?tx=...`).
     El backend verifica la firma HMAC (`x-signature`), consulta el **estado canónico del
     pago** a la API de MP (nunca confía en el body del webhook como fuente de verdad), y
     aplica `apply_provider_payment` de forma idempotente: activa/renueva el `StudentPlan`
     (si era compra/renovación de plan) o marca `enrollment_fee_paid_at` (si era solo
     matrícula sobre un plan existente).
   - **Síncrono e informativo:** MP redirige al alumno a un `back_url` de
     `{FRONTEND_URL}/pagos/resultado?tx=<id>`. El frontend hace polling a
     `GET /api/payments/transactions/<id>/status/` solo para **mostrar** el estado; ese
     endpoint **no activa nada**.
5. **La activación ocurre exclusivamente por el webhook (o por el reconcile de la
   sección 5).** El `back_url` es manipulable por el cliente (puede cerrar la pestaña o
   nunca volver), así que no es una ruta de activación confiable.
6. Idempotencia: `PaymentTransaction.processed_at` es el guard de "ya activado, no
   repetir"; además hay un `UniqueConstraint(provider, provider_payment_id)` a nivel DB
   y `select_for_update()` para serializar webhooks concurrentes del mismo pago.
7. **Fuera de alcance del piloto:** un mismo checkout cubre **un solo propósito** — o
   bien un `plan_id` (alta/renovación de plan), o bien un `target_student_plan_id`
   (matrícula pendiente sobre un `StudentPlan` ya existente). Cobrar plan + matrícula en
   una sola transacción es un ítem de fase 2; hoy el servicio rechaza la llamada si se
   envían ambos o ninguno.

## 5. Sandbox / pruebas sin dinero real

MercadoPago permite probar el flujo completo con usuarios de prueba, sin cuentas reales:

1. **Crear usuarios de prueba** (sitio `MLC`, Chile): uno que hará de **vendedor**
   (representa al gym) y otro que hará de **comprador** (representa al alumno). Ver el
   checklist de la sección 6 para confirmar el endpoint vigente de creación.
2. **Conectar el vendedor de prueba por OAuth:** iniciar sesión con las credenciales del
   usuario de prueba vendedor y completar `POST /api/payments/connect/` → autorización →
   callback, igual que con una cuenta real. Esto deja un `PaymentAccount` normal
   (`status=connected`) para la organización de prueba.
   - **Nota:** el modelo `PaymentAccount` tiene un campo `is_sandbox`, pero hoy **no se
     setea automáticamente** en ningún punto del código (ni en `connect_callback` ni en
     ningún otro lugar) — queda en `False` por default. Si se quiere distinguir cuentas
     de prueba de reales en el panel/reportes, hay que setearlo a mano (por Django
     admin/shell) o implementarlo como mejora futura; hoy es solo un flag de esquema.
3. **Pagar con tarjetas de prueba:** MP fuerza el resultado del pago según el **nombre
   del titular** de la tarjeta de prueba usada en el checkout:
   - `APRO` → aprobado
   - `OTHE` / `CONT` → pendiente
   - `FUND`, `SECU`, `EXPI`, `FORM` → distintos motivos de rechazo
   Confirmar el catálogo vigente de tarjetas de prueba y nombres mágicos en la doc de MP
   (cambia con el tiempo).
4. **Exponer el webhook en local:** reutilizar el Cloudflare Tunnel del repo
   (`docker-compose.yml`, servicio `cloudflared`, variable `CLOUDFLARE_TUNNEL_TOKEN`) para
   que MP pueda alcanzar `https://<dominio del túnel>/api/payments/webhook/` desde
   internet. El túnel apunta al frontend Nginx, que ya proxya `/api/` al backend. Mientras
   se prueba, `PAYMENTS_APEX_BASE_URL` (y por lo tanto `MP_OAUTH_REDIRECT_URI` /
   `notification_url`) debe apuntar a esa URL pública del túnel, no a `localhost`.
   Alternativa sin túnel: usar el botón "Simular notificación" del panel de MP para un
   pago ya creado.

## 6. Tareas programadas (cron)

| Comando | Frecuencia sugerida | Qué hace |
|---|---|---|
| `python manage.py reconcile_payments --minutes 5` | Cada ~5 minutos | Backstop de webhooks perdidos. Toma `PaymentTransaction` en `pending`/`in_process` sin `processed_at`, creadas hace más de `--minutes`, y reintenta el procesamiento idempotente contra el estado canónico de MP. |
| `python manage.py refresh_payment_tokens` | Diario | Refresca proactivamente los `PaymentAccount` conectados cuyo `token_expires_at` esté por vencer (además del refresh perezoso que ya ocurre antes de cada uso del token). |

**Limitación importante de `reconcile_payments`:** el comando **solo** reconsidera
transacciones que ya tienen `provider_payment_id` (es decir, que ya recibieron al menos
un webhook válido con ese dato, aunque no hayan llegado a `approved`). Una transacción
para la que MP **nunca** envió ningún webhook (o cuyo primer webhook fue rechazado por
firma inválida) se queda sin `provider_payment_id` y **no** es recogida por el reconcile.
Para ese caso extremo no hay hoy un backstop automático; requiere revisión manual (Django
admin / consulta directa a la API de MP por `external_reference`).

## 7. Checklist — verificar contra la documentación vigente de MercadoPago

El código de `backend/core/services/providers/mercadopago.py` deja explícitos varios
puntos que dependen de la doc de MP en el momento de operar (puede cambiar sin aviso):

- [ ] **Formato exacto del manifest de `x-signature`** (`ts=...,v1=...`) y el string que
  se firma (`id:<data.id>;request-id:<x-request-id>;ts:<ts>;`). Confirmar que MP no haya
  cambiado el orden/nombres de los campos.
- [ ] **Shape del body del webhook**: si actualmente incluye `external_reference` o solo
  `data.id` (hoy el código resuelve la transacción por el query param `?tx=` de la
  `notification_url`, no por el body).
- [ ] **TTL reales** de `access_token`/`refresh_token` del OAuth y si **PKCE** es
  obligatorio en el flujo de autorización (Chile / `auth.mercadopago.cl`).
- [ ] **Endpoint de creación de test users** (`/users/test_user` u otro vigente) y el
  **catálogo actual de tarjetas de prueba** / nombres mágicos de titular.

## 8. Fuera de alcance (explícitamente, no implementado)

- **Marketplace / comisión de plataforma:** no hay split de pagos. El dinero va 100% a
  la cuenta MP del gym; TYMRO nunca lo toca. La interfaz `PaymentProvider` deja el hueco
  para agregarlo en el futuro, pero hoy no existe ningún cálculo ni campo de comisión.
- **Checkout combinado plan + matrícula en una sola transacción:** ver punto 7 de la
  sección 4 — el piloto cobra un solo propósito por transacción.
- **Otros proveedores de pago:** la abstracción `PaymentProvider` está pensada para
  soportarlos, pero solo existe la implementación de MercadoPago (más `fake.py` para
  tests).
- **Refunds, contracargos, cancelaciones desde la UI, suscripciones/auto-renovación,
  cola tipo Celery:** ninguno de estos está implementado; el procesamiento del webhook es
  síncrono dentro del request.
