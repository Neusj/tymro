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
| `POST` | `/api/payments/disconnect/` | `gym_admin` / `superadmin` (de la org del usuario) | Desconecta la cuenta: marca `disconnected` y vacía los tokens guardados **primero** (garantizado, sin depender de la red) y **después** intenta revocar el token en el proveedor (best-effort). Body opcional `{"branch_id": <id>}` (sin él, la cuenta principal). Ver **sección 9**. |
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
   **Excepción, desde P3.4:** ese guard ya no descarta TODO aviso posterior. Un
   `refunded`/`charged_back` sigue entrando y se registra en la fila (`refunded_at`,
   `refunded_amount`, y `status` pasa a `refunded`), con los mismos chequeos de integridad
   que el cobro (collector y `external_reference`) y con su propia idempotencia por
   `refunded_at`. Antes era un no-op absoluto: el gimnasio devolvía la plata y la fila
   seguía diciendo `approved`, así que cualquier reporte de ingresos la contaba entera.
   La **membresía activada NO se desactiva** (decisión de producto pendiente, ver el TODO
   en `payments._stamp_refund`); lo que queda cerrado es que la plata devuelta existe en la
   base y la reportería la resta.
7. **El dinero cobrado tiene su propio marcador: `collected_at`.** Se estampa cuando el
   proveedor confirma el cobro y no se limpia nunca. No es `processed_at` (que además
   exige que la activación de la membresía haya funcionado) ni `status` (que la devolución
   pisa). Es la columna por la que la reportería suma el ingreso bruto.
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
- [ ] **Revocación (sección 9):** confirmar en sandbox, con un vendedor de prueba, que
  `DELETE api.mercadolibre.com/users/{user_id}/applications/{app_id}` responde 200 con el
  token emitido por **nuestra app de MP** y que después ese `access_token`/`refresh_token`
  quedan efectivamente inválidos (un `POST /oauth/token` de refresh debe fallar). Es el
  único punto del código que depende de un endpoint que MP no documenta para este flujo.

## 8. Fuera de alcance (explícitamente, no implementado)

- **Marketplace / comisión de plataforma:** no hay split de pagos. El dinero va 100% a
  la cuenta MP del gym; TYMRO nunca lo toca. La interfaz `PaymentProvider` deja el hueco
  para agregarlo en el futuro, pero hoy no existe ningún cálculo ni campo de comisión.
- **Checkout combinado plan + matrícula en una sola transacción:** ver punto 7 de la
  sección 4 — el piloto cobra un solo propósito por transacción.
- **Otros proveedores de pago:** la abstracción `PaymentProvider` está pensada para
  soportarlos, pero solo existe la implementación de MercadoPago (más `fake.py` para
  tests).
- **Refunds y contracargos:** se **REGISTRAN** desde P3.4 (`refunded_at`/`refunded_amount`
  sobre la `PaymentTransaction`, ver punto 6 de la sección 4) para que la reportería reste
  la plata devuelta. Lo que sigue fuera de alcance es la **reversión del efecto**: la
  membresía activada por ese cobro no se desactiva, y no hay forma de originar una
  devolución desde nuestra UI (solo se recibe el aviso de MP). Tampoco se distinguen
  devoluciones **parciales**: la abstracción de proveedor colapsa `refunded` y
  `charged_back` en un solo estado y MP informa el monto original, así que se registra
  siempre el total.
- **Una devolución avisada y perdida no tiene backstop.** `reconcile_payments` solo levanta
  transacciones en `pending`/`in_process` **sin** `processed_at`, y una devolución llega
  siempre sobre una fila ya cobrada y procesada, así que queda fuera de ese filtro. Si MP
  reintenta el webhook (lo hace) el registro entra; si se pierde definitivamente, el ingreso
  queda inflado y hay que corregirlo a mano. Ensanchar el reconcile para re-consultar cobros
  recientes es la solución, y no está hecha: implicaría pollear todo lo aprobado del período.
- **Devoluciones con la cuenta ya desconectada:** el aviso se pierde.
  `process_payment_notification` aborta limpio cuando la `PaymentAccount` del cobro no está
  `connected` (sin token no se puede consultar el estado canónico a MP), así que un
  reembolso avisado DESPUÉS de que el gimnasio desconectó su cuenta no se registra y el
  ingreso queda inflado. Es la misma limitación que ya tenía la activación.
- **Cancelaciones desde la UI, suscripciones/auto-renovación, cola tipo Celery:** ninguno
  de estos está implementado; el procesamiento del webhook es síncrono dentro del request.

## 9. Desconexión de una cuenta y revocación del token

`POST /api/payments/disconnect/` → `payments.disconnect_account()`
(`backend/core/services/payments.py`). Hace **dos cosas, en este orden**:

1. **Limpieza local (garantizada, y va PRIMERO).** Se copia a variables locales lo necesario
   para revocar (tokens, expiración, `provider_user_id`, proveedor) y acto seguido se
   escribe la fila: `status = disconnected` y `access_token`, `refresh_token`,
   `token_expires_at` a `NULL`. **La fila se conserva** (histórico + reconexión por el
   `update_or_create` del callback OAuth). Esto ocurre **siempre**: no está dentro de ningún
   `try` y no toca la red.

   **INVARIANTE:** al volver de `disconnect_account` la fila está `disconnected` con los
   tres campos de token en `NULL`, pase lo que pase con la red — incluso si el worker muere
   durante la revocación.

2. **Revocación en el proveedor (best-effort), ya con la fila vacía.** Con el token del
   snapshot en memoria:

   ```
   DELETE https://api.mercadolibre.com/users/{user_id}/applications/{app_id}
   Authorization: Bearer {access_token del vendedor}
   ```

   donde `user_id` es `PaymentAccount.provider_user_id` (el id del vendedor en MP) y
   `app_id` es `MP_CLIENT_ID`. Invalida el `access_token` **y** el `refresh_token`.
   - **Con qué token se revoca:** si el `token_expires_at` del snapshot está vencido o por
     vencer (mismo `REFRESH_MARGIN` que `get_valid_access_token`) y hay `refresh_token`, se
     hace **primero** un `refresh_tokens` y se revoca con el access_token **nuevo**. Los
     access_token de MP duran hasta 180 días y solo se renuevan al cobrar, así que un
     gimnasio que conectó y **nunca vendió** llega con el token de la fila vencido y la
     revocación daría `401`. Ese token refrescado **vive solo en memoria: NO se guarda en la
     fila.** Por eso **no** se reusa `get_valid_access_token` —esa función escribe y pone
     `status=CONNECTED`, o sea que resucitaría la cuenta que se acaba de desconectar—; el
     criterio de expiración está duplicado a propósito en `_revocation_access_token`.
     Si el refresh falla se intenta igual con el access_token crudo.
   - **`404` cuenta como "ya revocado"**: es evidencia de que esa autorización ya no existe
     (la quitaron desde el panel de MP, o una desconexión anterior la eliminó).
   - **`401` NO es éxito.** Levanta `RevocationUnverified` y se loguea como **revocación NO
     CONFIRMADA**, con la instrucción de reconciliar a mano en el panel de MercadoPago. Un
     `401` solo prueba "no pude autenticar", que es también lo que responde un token
     simplemente caducado mientras la autorización sigue **viva** bajo nuestro `app_id` con
     su `refresh_token` — justo el residuo que esta revocación existe para eliminar. Y como
     la limpieza local ya borró los tokens, esa fue la última chance automática.
     *(Antes de este fix el `401` se contaba como éxito y no se logueaba nada.)*
   - Si el snapshot **no tiene** tokens (cuenta ya desconectada) no se hace ninguna llamada
     de red: no hay nada que revocar.
   - **Cualquier fallo se loguea como `warning` y se ignora** (`logger` de
     `core.services.payments`, con `account`/`organization`/`branch`/`provider` — **nunca**
     el token). Hay **dos warnings distintos**: "Revocación en el proveedor **falló**"
     (no anduvo) y "Revocación en el proveedor **NO CONFIRMADA**" (no sabemos si anduvo).
     Se atrapa `Exception` a propósito, no solo `PaymentProviderError`: un bug en esa
     llamada no puede convertir una desconexión en un 500 para el gimnasio.

**Por qué la limpieza local va primero** (el orden original de P3.3 era el inverso): el
argumento para revocar antes —"después del vaciado no habría con qué autenticar"— es
**falso**, porque el token ya está en una variable local. Y el orden inverso tenía una falla
real: el `_TIMEOUT` de `requests` son 15 s que aplican **por separado** a connect y a read
(~30 s en el peor caso), mientras gunicorn corre con workers **sync** y `--timeout` 30 s
(ver `entrypoint.sh`). Si el proveedor acepta la conexión y no responde, el arbiter mata al
worker con una **señal**, no con una excepción: el `except Exception` no la cubre y el
vaciado local **nunca corría**. La fila quedaba `connected` con el token guardado y el panel
diciendo "Conectada", cuando además la request pudo llegar a ML y matar el token allá — el
peor de los dos mundos. Con el orden actual lo único que se pierde si el worker muere es el
intento de revocación, que ya era best-effort.

**Lo que el producto garantiza es el punto 1**, no el 2. La razón: **MercadoPago no publica
un endpoint de revocación** para el flujo OAuth de *split payments* — su doc de "Gestión de
Access Token" solo documenta `POST /oauth/token` (crear y refrescar), aunque sí describe la
semántica ("al revocar la autorización entre el vendedor y la aplicación se eliminan todos
los tokens y permisos temporales asociados"). El endpoint que usamos está documentado por
**Mercado Libre**, que comparte con MP el sistema de identidad y de aplicaciones (el
`client_id` de MP es el `app_id` de ML; el `user_id` del vendedor es el mismo en ambos). Es
lo único real que existe, pero **puede cambiar o dejar de responder sin aviso**: tratarlo
como *best-effort* y no asumir que el token remoto murió.

**Sin el punto 2** (comportamiento anterior a P3.3) el token del gimnasio seguía **vivo del
lado de MercadoPago hasta caducar solo —hasta 180 días— bajo el `app_id` de TYMRO**, aunque
el gimnasio viera "desconectado" en la app. Hoy se intenta matarlo de verdad; si el intento
falla o no se confirma, queda el `warning` en el log con el `account` afectado para
reconciliar a mano desde el panel de MP.

Detalle de implementación: la revocación se pide al proveedor **que emitió el token**
(`get_payment_provider(account.provider)`), no al `PAYMENTS_PROVIDER` global — mismo criterio
que `get_valid_access_token`. La interfaz es `PaymentProvider.revoke(access_token=,
provider_user_id=)` y su contrato vive en el docstring de `PaymentProvider.revoke`
(`services/providers/base.py`). Devolver `None` significa **hay evidencia** de que la
autorización ya no existe; las excepciones, todas subclases de `PaymentProviderError` para
que un caller que ya lo atrapa siga cubierto, son:

| Excepción | Significa | Cómo lo loguea `disconnect_account` |
|---|---|---|
| `RevocationUnverified` | no se pudo autenticar (401): resultado **desconocido** | "NO CONFIRMADA" + reconciliar a mano |
| `RevocationNotSupported` | el proveedor **no tiene** API de revocación | "falló" (limitación estructural) |
| `PaymentProviderError` | fallo de red o error de la API (5xx, etc.) | "falló" |
