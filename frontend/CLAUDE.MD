# CLAUDE.md — Frontend (TYMRO)

SPA para gestión de gimnasios. **React 18.3.1 + Vite 5.4.8 + TailwindCSS 3.4.13**, axios 1.7.7. MVP en desarrollo.

## Comandos

```bash
cd frontend                 # ⚠️ la carpeta real es frontend/ (ver advertencias)
npm install
npm run dev                 # vite, http://localhost:5173
npm run build               # producción
npm run preview             # previsualizar build
npm run test                # vitest run (suite unitaria, jsdom)
npm run test:watch          # vitest en modo watch
```

- **Tests con vitest** (`vitest.config.js`, setup en `src/test/setup.js`); los archivos son `src/**/*.test.{js,jsx}`. No hay linter configurado.
- `vitest.config.js` fija `TZ=America/Santiago`: la app muestra fechas del backend (`DateField`, sin hora) y el bug de interpretarlas como UTC solo se manifiesta al oeste de Greenwich. Sin la zona fijada, los tests de fecha pasarían estando rotos.

## Arquitectura

- `main.jsx` — entrada: `BrowserRouter` → `AuthProvider` → `App` (con `React.StrictMode`).
- `App.jsx` — definición de todas las rutas.
- `api/client.js` — cliente axios centralizado y todos los endpoints.
- `auth/AuthContext.jsx` — estado global de autenticación.
- `routes/ProtectedRoute.jsx` — protección de rutas por rol.
- `utils/` — `roles.js` (`defaultRouteByRole`), `format.js` (`clp`, `formatDate`, `todayLocalISO`, `firstApiError`), `rut.js`, `apiErrors.js`.
- `layouts/` + `components/layout/` — `AppLayout`, `Sidebar`, etc.
- `components/` — UI reutilizable (~20: `DataTable`, `FormModal`, `ConfirmDialog`, `BulkActionModal`, `StatCard`, etc.).
- `pages/` — páginas por rol (~30).

## Reglas clave

1. **Toda llamada a la API pasa por `api/client.js`.** Usar los módulos existentes (`authApi`, `usersApi`, `classesApi`, `enrollmentsApi`, `attendanceQrApi`, etc.). No crear instancias de axios sueltas.
2. **`baseURL = VITE_API_URL || VITE_API_BASE_URL || '/api'`.** En Docker/producción se usa `VITE_API_URL=/api` tras Nginx + túnel Cloudflare.
3. **Token:** `setAuthToken()` agrega `Authorization: Token <token>`; se llama en login y al rehidratar sesión. Persistencia en `localStorage` con claves `tymro_token` y `tymro_user`.
4. **Estado global SOLO para auth**, vía `AuthContext` (`token`, `user`, `loading`, `isAuthenticated`, `login/logout/refreshMe`). No hay Redux/Zustand; el resto es estado local (`useState`/`useEffect`) + helpers por página.
5. **Rutas protegidas con `<ProtectedRoute allowedRoles={[...]}>`.** Tras login, `defaultRouteByRole` (en `utils/roles.js`) redirige según rol.
6. **Respuestas de API:** usar `normalizeListResponse()` (tolera lista o paginada). Archivos/imágenes con `toFormData()`; URLs de media con `resolveMediaUrl()`.

## Rutas por rol

- **Públicas:** `/login`, `/attendance/screen`, `/attendance/check-in` (student).
- **Superadmin** `/superadmin/...`: organizations, users, plans, teacher-payments.
- **Gym Admin** `/gym-admin/...`: dashboard, users, branches, classes, attendance-qr, class-templates, class-types, disciplines, holidays, plans, teacher-payments.
- **Teacher** `/teacher/...`: dashboard, classes (upcoming/history), payments.
- **Student** `/student/...`: dashboard, plans, classes (available/reservations/recurring/history).

## Variables de entorno (nombres)

`VITE_API_URL` (fallback `VITE_API_BASE_URL`), `FRONTEND_PORT`.

## ⚠️ Advertencias (estado actual del repo)

- **Inconsistencia de carpeta:** el `README.md` raíz menciona `front/` y usa comandos `cd front`, pero la carpeta real es **`frontend/`**. Los comandos del README no coinciden.
- **Sin linter** configurado (sí hay tests: `npm run test`).
- **El estado de una membresía no se deriva en el cliente.** El backend manda `validity_status` + `validity_status_label` + `expiry_alert_level` + `expiry_alert_message` (y en el roster, los mismos con prefijo `plan_`); la UI solo pinta. `PlanAlertBadge` traduce el nivel a color y nada más. Reintroducir un mapeo estado→texto en el frontend recrea la divergencia que 7.3 cerró.
- El frontend ya tolera respuestas en lista o paginadas (el backend no tiene paginación DRF por defecto).