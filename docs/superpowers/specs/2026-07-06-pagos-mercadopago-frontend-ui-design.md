# Diseño: UI de pagos MercadoPago en el frontend (React/Vite)

- **Fecha:** 2026-07-06
- **Estado:** Aprobado por el usuario (2026-07-06) — listo para implementar
- **Rama:** `feat/pagos-mercadopago` (sin merge, sin push)
- **Alcance:** SOLO frontend. Consume los endpoints de pago ya existentes en el backend
  (`backend/core/views_payments.py`). **No se toca el backend.** Si algo resultara
  imprescindible en backend, se reporta antes de crearlo.

Complementa (no reemplaza) el diseño de backend
`2026-07-05-pagos-mercadopago-alumno-gym-design.md` y la guía operativa
`backend/docs/payments-mercadopago.md`.

---

## 1. Contexto

El backend de pagos alumno→gym con MercadoPago (Checkout Pro + OAuth por organización)
ya está construido y probado (pytest verde), pero **inerte**: no hay UI que lo dispare.
Este diseño agrega la UI, consistente con el sistema visual de TYMRO (tema oscuro,
tokens `brand-*`, `card-surface`, `DashboardHeader`, `DataTable`, `clp()`, banners inline).

Tres piezas por rol:

1. **GYM_ADMIN — Conectar MercadoPago** (pantalla de ajustes: estado + OAuth).
2. **ALUMNO — Comprar plan** (planes comprables → Checkout Pro → pantalla de resultado)
   **+ pagar matrícula pendiente**.
3. **GYM_ADMIN / PROFESOR — Ver estado**: el `StudentPlan` activado tras el pago se
   refleja en pantallas ya existentes (verificación, sin UI nueva).

## 2. Decisiones (confirmadas con el usuario)

| Tema | Decisión |
|---|---|
| Ítem 3 (ver estado admin/profe) | **Reflejar en pantallas existentes.** Sin backend nuevo, sin dashboard de transacciones. |
| Matrícula (`enrollment_fee`) | **Incluida.** Botón "Pagar matrícula" en "Mis planes" cuando `enrollment_fee_status ∈ {pending, overdue}` → checkout con `target_student_plan_id`. |
| Ubicación compra alumno | **Página dedicada** `/student/plans/comprar` (sidebar → grupo "Mis planes"). |
| Tests | **Vitest + React Testing Library + jsdom.** |
| Presentación planes comprables | **Cards** (no `DataTable`), estilo marketing con CTA por plan. |
| Badge "Pagado online" | **Descartado.** `StudentPlanSerializer` no expone origen de pago; requeriría cambio de backend. Ítem 3 se cubre con la membresía activa apareciendo en las pantallas existentes. |
| Pruebas | **Sandbox real de MercadoPago por navegador** (cuenta personal + usuarios de prueba), NO `FakePaymentProvider` ni shell. `PAYMENTS_PROVIDER=mercadopago`. Ver §9. |

## 3. Endpoints consumidos (contratos, ya existentes)

Todos por la instancia **autenticada** `api` de `api/client.js` (nunca `publicApi`;
todos exigen token).

| Método | Ruta | Rol | Request | Response |
|---|---|---|---|---|
| GET | `/payments/account/` | gym_admin / superadmin | — | `{status:'disconnected', provider}` **o** `{provider, status:'connected', provider_user_id, is_sandbox, connected_at, token_expires_at}` |
| POST | `/payments/connect/` | gym_admin / superadmin | — | `{authorization_url}` |
| POST | `/payments/checkout/` | student | `{plan_id}` **XOR** `{target_student_plan_id}` | `{transaction_id, redirect_url}` |
| GET | `/payments/transactions/{uuid}/status/` | dueño (student) | — | `{id, status, status_detail, amount, currency}` |

- `status` normalizado: `pending | in_process | approved | rejected | cancelled | refunded`.
- Errores relevantes de checkout: **409** `NotConnected` (gym sin MP), **400** `CheckoutError`
  (plan no comprable / matrícula inválida) con `{detail}`, **403** si no es alumno.
- El backend **redirige a rutas fijas del frontend** (hardcodeadas): OAuth callback →
  `{FRONTEND_URL}/ajustes/pagos?connected=1|0[&error=state|exchange]`; back_urls del
  checkout → `{FRONTEND_URL}/pagos/resultado?tx={uuid}`. **La UI debe usar exactamente
  esas rutas.**

## 4. Plumbing compartido

### 4.1 `api/client.js` — módulo `paymentsApi` (nuevo)
```js
export const paymentsApi = {
  getAccount:        async () => (await api.get('/payments/account/')).data,
  connect:           async () => (await api.post('/payments/connect/')).data,
  checkout:          async ({ planId, targetStudentPlanId } = {}) => {
    const payload = {}
    if (planId) payload.plan_id = planId
    if (targetStudentPlanId) payload.target_student_plan_id = targetStudentPlanId
    return (await api.post('/payments/checkout/', payload)).data
  },
  transactionStatus: async (id) => (await api.get(`/payments/transactions/${id}/status/`)).data,
}
```

### 4.2 `utils/format.js` (nuevo)
Extrae los helpers hoy copiados en varias páginas, para reutilizarlos en las páginas nuevas
(no se refactorizan las páginas existentes — fuera de alcance):
- `clp(value)` → `"$12.345"` (es-CL, `Math.round`, sin decimales).
- `firstApiError(detail, fallback)` → desempaqueta `response.data` a string.

### 4.3 Rutas (`App.jsx`)
```
/ajustes/pagos          ProtectedRoute allowedRoles={['gym_admin','superadmin']}  → GymAdminPaymentsSettingsPage
/student/plans/comprar  ProtectedRoute allowedRoles={['student']}                 → StudentBuyPlanPage
/pagos/resultado        ProtectedRoute allowedRoles={['student']}                 → PaymentResultPage
```
Las tres dentro de `<ShellRoute>` (layout autenticado). `/ajustes/pagos` y `/pagos/resultado`
son **top-level** a propósito: coinciden con lo que el backend hardcodea.

### 4.4 Navegación (`components/layout/Sidebar.jsx`)
- gym_admin, grupo **"Configuraciones"** → agregar hijo `{ to: '/ajustes/pagos', label: 'Pagos (MercadoPago)' }`
  (etiqueta distinta de "Pagos Profesores" para no confundir).
- student, grupo **"Mis planes"** → agregar hijo `{ to: '/student/plans/comprar', label: 'Comprar plan' }`.

## 5. GYM_ADMIN — Conectar MercadoPago  (`pages/GymAdminPaymentsSettingsPage.jsx`)

Ruta `/ajustes/pagos`. Estructura estándar: `space-y-6` → `DashboardHeader` → banners → `card-surface`.

**Al montar:**
1. Leer query `?connected=1|0&error=state|exchange` (`useSearchParams`) y mostrar banner:
   - `connected=1` → notice verde "Cuenta de MercadoPago conectada."
   - `connected=0&error=state` → error "El enlace de conexión expiró. Intenta de nuevo."
   - `connected=0&error=exchange` → error "No se pudo completar la conexión con MercadoPago."
   - `connected=0` (sin error) → error genérico.
   Luego limpiar los params (`navigate(pathname, {replace:true})`) para que un refresh no repita el banner.
2. `paymentsApi.getAccount()` → estado de la conexión.

**Render:**
- **Desconectado** (`status:'disconnected'`): card explicativa ("Conecta la cuenta de
  MercadoPago del gimnasio para cobrar planes en línea. El dinero va directo a tu cuenta.")
  + botón **"Conectar con MercadoPago"**.
- **Conectado** (`status:'connected'`): `ValueBadge`/pill verde "Conectado", `provider_user_id`
  (id de la cuenta cobradora), `connected_at` (fecha es-CL), badge "Modo prueba" si `is_sandbox`,
  vencimiento del token (`token_expires_at`) informativo, y botón secundario **"Reconectar"**.

**Acción conectar:** `setConnecting(true)` → `paymentsApi.connect()` →
`window.location.assign(data.authorization_url)`. `catch` → banner de error (usa `firstApiError`).
Estados: `loading` (carga inicial), `connecting` (botón), `error`, `notice`.

## 6. ALUMNO — Comprar plan  (`pages/StudentBuyPlanPage.jsx`)

Ruta `/student/plans/comprar`.
- `getPlans()` → filtrar **client-side** a comprables:
  `p.is_public && p.is_active && !['trial','giftcard'].includes(p.plan_type)`.
  (El backend re-valida en checkout; el filtro es solo de presentación.)
- **Cards** (grid `sm:grid-cols-2 xl:grid-cols-3`, `card-surface p-5`). Cada card:
  - Nombre + badge de tipo (`monthly→Mensual`, `pack→Pack`, `single_class→Clase suelta`).
  - Precio: `final = Math.round(price*(1 - discount/100))`. Mostrar `clp(final)` grande; si
    `discount_percentage>0`, mostrar `clp(price)` tachado + pill `-N%`.
  - Clases: `unlimited_classes ? 'Clases ilimitadas' : \`${total_classes} clases\``.
  - Duración: `\`${duration_days} días\``.
  - Botón **"Pagar"**.
- **Pagar:** `setPayingId(plan.id)` → `paymentsApi.checkout({planId: plan.id})` →
  `window.location.assign(redirect_url)`. `catch`:
  - `409` → "El gimnasio aún no habilitó pagos en línea."
  - `400` → `detail` del backend.
  - otro → genérico.
- Estados: `loading` (skeleton), `error` (banner), `payingId` (botón por card), empty state
  ("No hay planes disponibles para comprar por ahora.").

### 6.1 Pantalla de resultado  (`pages/PaymentResultPage.jsx`)

Ruta `/pagos/resultado?tx={uuid}`.
- Leer `tx` (`useSearchParams`). Si falta → estado de error "No encontramos la referencia del pago."
- `paymentsApi.transactionStatus(tx)` con **polling acotado**: si `status ∈ {pending, in_process}`,
  reintentar cada ~3 s hasta ~8 veces; luego detenerse y ofrecer botón **"Actualizar"**. Cancelar
  el timer al desmontar y al llegar a estado terminal.
- Mapa estado → UI (con `clp(amount)` visible):
  - `approved` → éxito verde: "¡Pago aprobado!" + nota de activación por webhook + link "Ver mis planes" (`/student/plans`).
  - `pending`/`in_process` → ámbar: "Pago en proceso" + "Estamos esperando la confirmación de MercadoPago; puede tardar unos minutos." + botón "Actualizar".
  - `rejected` → rojo: "Pago rechazado" + `status_detail` legible + botón "Volver a intentar" (`/student/plans/comprar`).
  - `cancelled` → "Pago cancelado". `refunded` → "Pago reembolsado".
- **Aclaración fija en todos los estados:** "La activación de tu plan la confirma
  MercadoPago mediante una notificación automática (webhook), no esta pantalla."
- `404` (tx inexistente o de otro usuario) → estado de error claro.

### 6.2 Matrícula pendiente  (modifica `pages/StudentPlansPage.jsx`)

En la tabla de "Mis planes" (`getMyMemberships()`, filas = `StudentPlan` con
`enrollment_fee`, y `enrollment_fee_status` que es un dict `{status, ...}` con
`status ∈ {waived, paid, overdue, pending}`), agregar columna **"Matrícula"**:
- `enrollment_fee_status.status ∈ {pending, overdue}` y `enrollment_fee>0` → monto `clp(enrollment_fee)` + botón
  **"Pagar matrícula"** → `paymentsApi.checkout({targetStudentPlanId: row.id})` →
  `window.location.assign(redirect_url)` (misma pantalla de resultado).
- `paid` → badge "Pagada". `waived` → "—".
- Estado `payingMembershipId` para el botón; errores vía banner de la página.

## 7. GYM_ADMIN / PROFESOR — Ver estado (ítem 3, sin código nuevo)

Tras la confirmación por webhook, el `StudentPlan` activado ya aparece como membresía activa en:
- **Gym Admin → Planes → "Ver membresías"** (`/gym-admin/plans/:id/memberships`,
  `GymAdminPlanMembershipsPage`): muestra `validity_status`, `is_active`, `remaining_classes`,
  `enrollment_fee_status`.
- **Rosters de clase del profesor** (`/api/classes/{id}/enrolled-students/`): `plan_status`,
  `available_classes`.

Deliverable: **verificación** (correr el flujo sandbox y confirmar que la membresía queda
activa en esas pantallas), no UI nueva.

## 8. Estados de carga/error y casos borde

- Cada acción tiene `loading`/estado por-acción + banner de error (patrón nativo:
  `border-brand-red/50 bg-brand-red/10 text-red-200` / notice `emerald`).
- Casos cubiertos: gym sin MP (409), `state` OAuth expirado, plan no comprable (400),
  `tx` ausente/ajeno (404), lista de planes vacía, alumno sin organización, fallo de red.

## 9. Plan de pruebas

### 9.1 Automatizadas — Vitest + React Testing Library + jsdom
- Config: `vitest.config.js` (separado de `vite.config.js` para no arrastrar el plugin PWA),
  `src/test/setup.js` (`@testing-library/jest-dom`), script `"test": "vitest run"`.
- `api/client` se mockea con `vi.mock`; `window.location.assign` se stubbea; router con `MemoryRouter`.
- Suites:
  - `utils/format.test.js`: `clp` (formato es-CL), `firstApiError` (string / `{detail}` / errores de campo).
  - `StudentBuyPlanPage.test.jsx`: filtro excluye trial/giftcard/privados/inactivos; precio con descuento;
    "Pagar" llama checkout y redirige; 409 muestra mensaje amable; loading y empty.
  - `PaymentResultPage.test.jsx`: mapea approved/pending/rejected; nota de webhook presente;
    polling se detiene en estado terminal; `tx` ausente.
  - `GymAdminPaymentsSettingsPage.test.jsx`: desconectado→botón conectar→redirect; conectado
    muestra collector/fecha/sandbox; banners por query param.
- **`npm run build` debe pasar** (se verifica).

### 9.2 Manual end-to-end contra el SANDBOX de MercadoPago (por navegador, sin shell)
`PAYMENTS_PROVIDER=mercadopago`. Se documenta como entregable operativo al terminar la UI
(§ credenciales, redirect_uri/notification_url vía Cloudflare Tunnel, usuarios de prueba
vendedor+comprador, variables de entorno exactas). Base: `backend/docs/payments-mercadopago.md`
§1–2 y §5; se ampliará con el paso a paso exacto.

Wiring local (dos opciones, ambas ya soportadas por el repo):
- **`npm run dev` (Vite :5173, proxya `/api`→:8000) + `runserver` :8000 + quick tunnel**
  `cloudflared tunnel --url http://localhost:5173` (el dev server ya permite `.trycloudflare.com`).
- **docker-compose** (frontend Nginx :5173 + backend :8000 + `cloudflared` con token).

En ambos: `PAYMENTS_APEX_BASE_URL` y `FRONTEND_URL` = URL pública del túnel; registrar en la app
MP el callback `{túnel}/api/payments/oauth/callback/` y el webhook `{túnel}/api/payments/webhook/`.

## 10. Inventario de archivos

**Nuevos:**
- `frontend/src/pages/GymAdminPaymentsSettingsPage.jsx`
- `frontend/src/pages/StudentBuyPlanPage.jsx`
- `frontend/src/pages/PaymentResultPage.jsx`
- `frontend/src/utils/format.js`
- `frontend/vitest.config.js`, `frontend/src/test/setup.js`
- Tests: `frontend/src/utils/format.test.js`, `frontend/src/pages/StudentBuyPlanPage.test.jsx`,
  `frontend/src/pages/PaymentResultPage.test.jsx`, `frontend/src/pages/GymAdminPaymentsSettingsPage.test.jsx`

**Modificados:**
- `frontend/src/api/client.js` (+`paymentsApi`)
- `frontend/src/App.jsx` (+3 rutas)
- `frontend/src/components/layout/Sidebar.jsx` (+2 items de nav)
- `frontend/src/pages/StudentPlansPage.jsx` (columna/acción "Pagar matrícula")
- `frontend/package.json` (devDeps de test + script `test`)

## 11. Fuera de alcance
- Cualquier cambio de backend (incl. badge "Pagado online", endpoint admin de transacciones).
- Combinar plan + matrícula en un mismo checkout (el backend cobra un propósito por transacción).
- Refunds/cancelaciones desde UI, suscripciones, historial de pagos/boletas.
- Refactor de las páginas existentes que duplican `clp`/`firstApiError`.
