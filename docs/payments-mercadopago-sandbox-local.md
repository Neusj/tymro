# Probar pagos MercadoPago en local contra el SANDBOX (end-to-end por navegador)

Guía exacta para ejercitar los **tres** flujos de la UI de pagos —conectar cuenta (OAuth real),
comprar plan (Checkout Pro real) y recibir el webhook— usando el **sandbox de MercadoPago**
(tu cuenta personal + usuarios de prueba), **sin `FakePaymentProvider` ni shell**.

`PAYMENTS_PROVIDER=mercadopago`. El dinero es ficticio (usuarios de prueba); no se cobra nada real.

> Complementa `backend/docs/payments-mercadopago.md` (§1–2, §5). Aquí está el paso a paso operativo.

---

## 0. Resumen de por qué se necesita un túnel

MercadoPago tiene que **alcanzar tu backend desde internet** en dos momentos:

1. **OAuth callback** — al conectar, MP redirige el navegador a `redirect_uri`
   (`…/api/payments/oauth/callback/`). Debe ser una URL **https pública** registrada en la app.
2. **Webhook** — tras el pago, MP hace `POST …/api/payments/webhook/?tx=<id>` a la
   `notification_url`. También debe ser pública.

`localhost` no sirve para ninguno de los dos. Se usa el **Cloudflare Tunnel** (ya está en el repo)
para exponer el entorno local con una URL https pública. Esa URL es tu **apex**:
`PAYMENTS_APEX_BASE_URL` y `FRONTEND_URL` apuntan a ella.

---

## 1. Crear la app en MercadoPago y obtener credenciales

1. Entra a **[Mercado Pago Developers → Tus integraciones](https://www.mercadopago.cl/developers/panel/app)**
   con tu cuenta personal (país **Chile**, site `MLC`).
2. **Crear aplicación**. Elige el producto **Pagos online / Checkout Pro** y, cuando pregunte por el
   modelo de integración, marca que **integrarás cuentas de terceros / marketplace** (esto habilita
   el flujo **OAuth**, imprescindible: cada gym conecta *su* cuenta, no la tuya).
3. En la app, ve a **Credenciales de producción**. Copia:
   - **Client ID** → `MP_CLIENT_ID`
   - **Client Secret** → `MP_CLIENT_SECRET`

   > OAuth no funciona con las credenciales de "prueba"; usa las de **producción** de la app. El
   > "sandbox" acá se logra con **usuarios de prueba** (paso 5), no con credenciales de test.

---

## 2. Configurar Redirect URI + Webhook (con la URL del túnel del paso 3)

En la misma app de MercadoPago. **Estas URLs deben coincidir EXACTO con las de tu entorno**
(incluida la barra final `/`). Usa la URL pública del túnel que levantarás en el paso 3
(ej. `https://tymro-sandbox.trycloudflare.com`):

1. **Redirect URIs (OAuth):** agrega exactamente:
   `https://<TU-TÚNEL>/api/payments/oauth/callback/`
2. **Webhooks / Notificaciones:** configura la URL:
   `https://<TU-TÚNEL>/api/payments/webhook/`
   - Selecciona el evento **Pagos** (`payment`).
   - MP genera una **clave secreta / firma** para esa configuración → cópiala a `MP_WEBHOOK_SECRET`.

> El `?tx=<id>` de la `notification_url` lo agrega el backend al crear cada preference; **no** lo
> pongas en el panel. Registra solo `…/api/payments/webhook/`.

---

## 3. Levantar el túnel (elige UNA opción)

### Opción A — `npm run dev` + `runserver` + quick tunnel (recomendada para desarrollar UI)

Tres terminales:

```bash
# Terminal 1 — backend (con el .env del paso 4 cargado)
cd backend
python manage.py migrate
python manage.py runserver 0.0.0.0:8000

# Terminal 2 — frontend (Vite; proxya /api y /media al backend :8000)
cd frontend
npm run dev            # http://localhost:5173

# Terminal 3 — túnel público hacia Vite (:5173). Vite ya proxya /api → backend.
cloudflared tunnel --url http://localhost:5173
# → imprime algo como: https://tymro-sandbox.trycloudflare.com
```

- El dev server de Vite ya acepta hosts `*.trycloudflare.com` (`vite.config.js`), y proxya `/api`
  al backend preservando el `Host` (`xfwd`).
- **Haz TODO el test entrando por la URL del túnel** (`https://<TU-TÚNEL>`), no por `localhost`,
  para que los redirects de MP (callback y `back_url`) caigan en el mismo origen y MP acepte las
  URLs https.

### Opción B — docker-compose (túnel con nombre que ya tienes)

```bash
# .env con las variables del paso 4 + CLOUDFLARE_TUNNEL_TOKEN
docker compose up --build
```
El servicio `cloudflared` publica tu dominio (configurado en el panel de Cloudflare, apuntando al
frontend Nginx, que sirve la SPA y proxya `/api/` al backend). Usa ese dominio como `<TU-TÚNEL>`.

---

## 4. Variables de entorno exactas (backend)

`PAYMENTS_PROVIDER=mercadopago`. Genera primero la clave de cifrado de tokens:

```bash
cd backend
python -c "from core.fields import generate_encryption_key; print(generate_encryption_key())"
```

`.env` (o variables del compose). Reemplaza `<TU-TÚNEL>` por el host del paso 3:

```bash
DJANGO_DEBUG=True
PAYMENTS_PROVIDER=mercadopago

# App MercadoPago (paso 1)
MP_CLIENT_ID=<client id de producción de la app>
MP_CLIENT_SECRET=<client secret de la app>
MP_WEBHOOK_SECRET=<clave secreta de firma del webhook, paso 2>

# Cifrado de tokens en reposo (Fernet, generada arriba)
PAYMENTS_ENCRYPTION_KEY=<clave fernet>

# Apex público (el túnel). De acá se derivan el redirect_uri y la notification_url.
PAYMENTS_APEX_BASE_URL=https://<TU-TÚNEL>
FRONTEND_URL=https://<TU-TÚNEL>

# Que el backend acepte el host del túnel
ALLOWED_HOSTS=localhost,127.0.0.1,.trycloudflare.com,<TU-TÚNEL>
CSRF_TRUSTED_ORIGINS=https://<TU-TÚNEL>,http://localhost:5173
```

- `MP_OAUTH_REDIRECT_URI` **no** hace falta setearla: por defecto es
  `${PAYMENTS_APEX_BASE_URL}/api/payments/oauth/callback/`. Debe coincidir EXACTO con la registrada
  en la app (paso 2). Si las difieres, MP responde `redirect_uri mismatch`.
- Con `DJANGO_DEBUG=True` no aplica el *fail-fast* de producción, pero **igual necesitas** las 4
  variables MP + `PAYMENTS_ENCRYPTION_KEY` reales para que el cobro funcione.
- **`FRONTEND_URL` apunta al túnel** a propósito: el callback OAuth redirige a
  `${FRONTEND_URL}/ajustes/pagos?connected=1` y los `back_urls` del checkout a
  `${FRONTEND_URL}/pagos/resultado?tx=…`. Entrando por el túnel, esos redirects caen en tu SPA.

---

## 5. Crear los usuarios de prueba (vendedor + comprador)

En **Tus integraciones → [tu app] → Cuentas de prueba → Crear cuenta de prueba** (site Chile):

1. **Vendedor** — hará de *gimnasio* que cobra. (Si pide un monto ficticio, cualquier valor sirve.)
2. **Comprador** — hará de *alumno* que paga.

Cada uno entrega **usuario + contraseña** autogenerados (y un código de 6 dígitos por si pide
verificación por email al iniciar sesión). Guárdalos.

> Nota: `PaymentAccount.is_sandbox` **no** se setea solo (queda `False`). Si quieres que la UI
> muestre el badge "Modo prueba", ponlo a mano por Django admin/shell tras conectar. No afecta el flujo.

---

## 6. Flujo end-to-end por navegador

Todo entrando por `https://<TU-TÚNEL>`.

### 6.1 GYM_ADMIN — conectar la cuenta (OAuth real)
1. Inicia sesión en TYMRO como **gym_admin** de la organización de prueba.
2. Sidebar → **Configuraciones → Pagos (MercadoPago)** (ruta `/ajustes/pagos`).
3. Clic en **"Conectar con MercadoPago"** → te redirige a MercadoPago.
4. En MP, **inicia sesión con el usuario de prueba VENDEDOR** y autoriza la app.
5. MP vuelve a `…/ajustes/pagos?connected=1` → la pantalla muestra **"Cuenta conectada"**,
   la cuenta cobradora (`provider_user_id`) y la fecha.
   - Si ves `connected=0&error=state` → el `state` expiró (>10 min): reintenta.
   - Si ves `error=exchange` → falló el intercambio de código (revisa client_id/secret y redirect_uri).

### 6.2 ALUMNO — comprar un plan (Checkout Pro real)
1. Cierra sesión y entra como **alumno** de la misma organización.
2. Sidebar → **Mis planes → Comprar plan** (ruta `/student/plans/comprar`).
   - Recuerda: el plan debe ser **público, activo y no trial/giftcard** para aparecer.
3. Clic en **"Pagar"** en un plan → te redirige a **Checkout Pro** de MercadoPago.
4. Paga con una **tarjeta de prueba** (ver paso 7). Usa el titular **`APRO`** para aprobar.
   - Puedes pagar como invitado o iniciar sesión con el **usuario COMPRADOR** de prueba.
5. MP redirige a `…/pagos/resultado?tx=<id>`. La pantalla:
   - Hace *polling* al estado y muestra **aprobado / pendiente / rechazado**.
   - Aclara que **la activación la confirma el webhook**, no esa pantalla.

### 6.3 Confirmar que el plan quedó activo (webhook)
El webhook (`POST …/api/payments/webhook/?tx=…`) activa el `StudentPlan`. Verifica:
- Como **alumno**: **Mis planes → Vigentes** (`/student/plans`) → aparece el plan activo.
- Como **gym_admin**: **Planes → [plan] → Ver membresías** (`/gym-admin/plans/:id/memberships`) →
  el alumno aparece con estado **activo**.
- Como **profesor**: en el roster de la clase, el alumno figura con clases disponibles.
- Si tarda: es normal (el webhook es asíncrono). El botón **Actualizar** de la pantalla de resultado
  reconsulta. El cron `reconcile_payments` es el backstop (opcional en local).

### 6.4 Pagar matrícula (opcional)
Si un `StudentPlan` del alumno tiene matrícula pendiente, en **Mis planes → Vigentes** aparece el
botón **"Pagar matrícula · $…"** (columna Matrícula) → mismo Checkout Pro → misma pantalla de resultado.

---

## 7. Tarjetas de prueba y resultado forzado por el titular

MP fuerza el resultado del pago según el **nombre del titular** de la tarjeta de prueba:

| Titular | Resultado |
|---|---|
| `APRO` | Aprobado |
| `OTHE` | Rechazado (motivo genérico) |
| `CONT` | Pendiente |
| `FUND` / `SECU` / `EXPI` / `FORM` | Distintos rechazos |

Usa las tarjetas de prueba vigentes del catálogo de MP (número, CVV y fecha de prueba). El catálogo
puede cambiar: **confírmalo en la doc de MP** ([tarjetas de prueba](https://www.mercadopago.cl/developers/es/docs/checkout-pro/integration-test/test-purchases)).

---

## 8. Troubleshooting

| Síntoma | Causa probable / arreglo |
|---|---|
| `redirect_uri mismatch` al conectar | La Redirect URI de la app (paso 2) no coincide EXACTO con `${PAYMENTS_APEX_BASE_URL}/api/payments/oauth/callback/` (revisa https, host y barra final). |
| Vuelve con `error=exchange` | `MP_CLIENT_ID`/`MP_CLIENT_SECRET` incorrectos, o la app no tiene OAuth/marketplace habilitado. |
| El webhook no activa el plan | (a) `MP_WEBHOOK_SECRET` no coincide → el backend responde 401 y loguea "firma inválida"; (b) la URL de webhook en MP no apunta al túnel; (c) el túnel se cayó. Revisa logs del backend. |
| `DisallowedHost` en el backend | Agrega el host del túnel a `ALLOWED_HOSTS`. |
| La SPA no carga tras el redirect | Entraste por `localhost` en vez del túnel, o `FRONTEND_URL` no apunta al túnel. |
| Error al leer/guardar la cuenta | Falta `PAYMENTS_ENCRYPTION_KEY` (los tokens se guardan cifrados). |

**Gotchas conocidos** (heredados del backend, no de la UI):
- **Multitenancy por subdominio:** el login resuelve la org por subdominio. En un quick tunnel (host
  único) usa una org alcanzable por el apex. Los endpoints de pago **no** dependen del host (resuelven
  la org por el usuario autenticado / `state` firmado / `tx`), así que el cobro funciona igual.
- **Token de ~6 h:** MP entrega access tokens cortos; el backend refresca de forma perezosa antes de
  cada uso (rota el refresh_token). Es esperable ver refresh frecuente.
- `is_sandbox` no se auto-setea (ver paso 5).
