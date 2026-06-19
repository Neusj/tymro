# TYMRO E2E — flujo de estudiante (Playwright)

Suite E2E que valida **de extremo a extremo** el flujo del alumno en TYMRO contra QA
(`qa.tymroapp.com`), pegándole al backend real (sin mocks).

## Qué cubre

| # | Flujo | Archivo |
|---|---|---|
| 1 | Login (válido + credenciales inválidas) | `tests/00-auth.setup.js`, `tests/01-login.spec.js` |
| 2 | Ver clases disponibles + filtros (disciplina, profesor, estado, fecha) | `tests/02-clases-filtros.spec.js` |
| 3 | Reservar una clase (éxito + aparece en "Mis reservas" + descuenta saldo) | `tests/03-reservar.spec.js` |
| 4 | Cancelar una clase (devolución de saldo) | `tests/04-cancelar-saldo.spec.js` |
| 5 | Recurrencia: inscribir, pausar, reactivar, quitar | `tests/05-recurrencia.spec.js` |
| 6 | QR check-in real (token vivo de gym_admin, sin cámara) | `tests/06-qr-checkin.spec.js` |
| 7 | Balance del plan (activo, saldo, vigencia) | `tests/07-balance.spec.js` |
| 8 | Aislamiento multitenancy (no acceder a otra org) — nivel API | `tests/08-multitenancy.api.spec.js` |
| 9 | Rechazos: cupo lleno, solape, sin plan, saldo insuficiente, matrícula impaga | `tests/09-rechazos.spec.js` |

## Requisitos

1. **Node 18+** (probado con 24).
2. **QA accesible** en `qa.tymroapp.com` (front + `/api`).
3. **Backend levantado en Docker local** y con la imagen **reconstruida** para incluir
   la extensión del seed (`seed_demo_data --org`). Si cambiaste `seed_demo_data.py`:
   ```bash
   docker compose up -d --build backend
   ```
   > ⚠️ El backend usa imagen horneada (no monta el código). Sin rebuild, el comando
   > de seed con `--org` no existe en el contenedor.

## Setup

```bash
cd e2e
npm install
npx playwright install chromium
cp .env.example .env      # y completa los valores
```

`.env` (ver `.env.example`):

| Variable | Para qué |
|---|---|
| `QA_BASE_URL` / `QA_API_URL` | URLs del front y la API de QA |
| `QA_USER` / `QA_PASSWORD` | alumno feliz (es **username**, no email) |
| `QA_GYM_ADMIN_USER` / `QA_GYM_ADMIN_PASSWORD` | genera el token QR vivo |
| `QA_ORG_SLUG` | org a seedear/probar (`r2b-qa`) |
| `QA_SEED_CMD` | comando que repuebla QA antes de la suite |
| `QA_SKIP_SEED=1` | (opcional) desactiva el auto-seed si seedeas a mano |
| `QA_FOREIGN_CLASS_ID` / `QA_FOREIGN_ORG_ID` | (opcional) override del recurso foráneo |

## Correr

```bash
npm test                       # toda la suite
npx playwright test 03-reservar # un archivo
npm run report                 # abre el reporte HTML (carpeta reportes/)
```

- **Reporte HTML**: `reportes/index.html`.
- **Ante fallos**: screenshot + video + trace quedan en `test-results/`
  (`npx playwright show-trace <ruta>/trace.zip`).

## Cómo funciona

- **`global-setup.js`**: ejecuta `QA_SEED_CMD` (repuebla QA), captura los IDs de los
  fixtures que imprime el seed (línea `TYMRO_E2E_FIXTURES=...`) en `.fixtures.json`, y
  toma el token de gym_admin.
- **Proyecto `setup`** (`00-auth.setup.js`): hace el login válido del alumno UNA vez y
  guarda la sesión (`storageState.student.json`) que reutiliza el resto.
- **Proyecto `chromium`**: corre los specs reusando esa sesión. **Serial (`workers:1`)**
  porque comparten el saldo del mismo alumno.
- **QR sin cámara**: el gym_admin pide el QR vigente por API (`/attendance-qr/current/`)
  y el alumno navega a `/attendance/check-in?token=…` (lo que haría su teléfono).

## Comportamientos del backend que la suite asume (hallazgos de QA)

- **Login rota el token** en cada inicio de sesión: por eso el alumno se loguea una
  sola vez (en el setup). Un segundo login mataría la sesión compartida.
- **Throttle de `/login` = 5/min**: la suite minimiza logins y reintenta ante 429.
- **Multitenancy**: pedir `/classes/?organization_id=<otra>` **no** da 403; el backend
  ignora el parámetro y filtra por la org del token. El aislamiento se verifica con el
  **404** del detalle de un recurso ajeno + que el listado nunca trae datos de otra org.
- **Recurrencia pausada**: `/my-recurring-enrollments/` filtra `is_active=true`, así que
  al pausar, la recurrencia **desaparece** de "Mis recurrencias" y el botón "Reactivar"
  de esa pantalla queda inalcanzable por UI. La reactivación se ejerce por API en el test
  (la capacidad existe en el backend). **Vale la pena revisar este UX antes de producción.**

## Datos de prueba

Los crea el seed (`backend/core/management/commands/seed_demo_data.py`, extendido):
org `r2b-qa`, alumno con plan activo y saldo, 3 clases futuras, una clase en ventana de
QR, una serie con plantilla, clases para cupo-lleno/solape, alumnos en estados de rechazo
y una organización foránea para el test de aislamiento.
