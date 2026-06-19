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

---

# Suite gym_admin (org `e2e-gym`)

Valida TODAS las funciones del perfil **gym_admin** contra el backend real, en un org
**dedicado y descartable** (`e2e-gym`). El seed sufija los usernames por org (`_e2egym`),
así que **`r2b-qa` (datos de R2B) nunca se toca**.

## Cómo correr SOLO gym_admin

1. Apunta `e2e/.env` al org `e2e-gym` (ver bloque comentado en `.env.example`):
   ```
   QA_GYM_ADMIN_USER=gymadmin_e2egym
   QA_USER=student1_e2egym
   QA_TEACHER_USER=teacher1_e2egym
   QA_ORG_SLUG=e2e-gym
   QA_SEED_CMD=docker compose exec -T backend python manage.py seed_demo_data --org=e2e-gym
   ```
2. Corre el proyecto aislado (su propio setup + `storageState.gym.json`):
   ```bash
   npx playwright test --project=gym-admin
   ```
   No corre los setups de alumno/profesor (proyectos separados).

## Qué cubre (17 archivos, 34 casos)

| Flujo | Archivo |
|---|---|
| Auth (sesión válida + inválida + redirect) | `21-gym-admin-auth.spec.js` |
| Dashboard (4 KPIs reales, navegación) | `22-gym-admin-dashboard.spec.js` |
| Estudiantes (crear + asignar plan) | `23-gym-admin-students.spec.js` |
| Planes (listado + crear/eliminar) | `24-gym-admin-plans.spec.js` |
| Disciplinas y tipos (CRUD + duplicado) | `25-gym-admin-disciplines-classtypes.spec.js` |
| Sucursales (CRUD + duplicado) | `26-gym-admin-branches.spec.js` |
| Clases (crear puntual) | `27-gym-admin-classes.spec.js` |
| Festivos (crear) | `28-gym-admin-holidays.spec.js` |
| QR de asistencia (QR rotante + regenerar) | `29-gym-admin-qr.spec.js` |
| Profesores (crear usuario teacher) | `30-gym-admin-teachers.spec.js` |
| Reglas de pago (POR ASISTENCIA + POR RESERVA) | `31-gym-admin-payment-rules.spec.js` |
| **Cálculo de pago (montos exactos, API)** | `32-gym-admin-payment-calc.api.spec.js` |
| Resumen de pagos + export CSV/XLSX | `33-gym-admin-payments-summary.spec.js` |
| Importador (catálogo + plantilla) | `34-gym-admin-import.spec.js` |
| Trial-followup (config + negativos) | `35-gym-admin-trial-followup.spec.js` |
| Multitenancy (404 + sin leak, API) | `36-gym-admin-multitenancy.api.spec.js` |
| Validaciones de rechazo (API) | `37-gym-admin-validations.api.spec.js` |

## Casos críticos de cálculo de pago (verificados end-to-end, API real)

Sembrados por el seed con clases COMPLETED + asistencia/planes; el backend calcula al
cerrar y la suite asierta el **monto exacto** del resumen:

| Modalidad | Escenario | Monto |
|---|---|---|
| **FIJO** | `fixed_per_class $5.000`, 3 alumnos presentes | **$5.000** (no depende de #alumnos) |
| **POR ASISTENCIA 40%** | `per_plan_price present_attendees`: PlanA $40k/4=$10k + PlanB $40k/8=$5k + ilimitado=$0, todos presentes | **$6.000** |
| **POR RESERVA 60%** | `per_plan_price active_enrollments`: mismos inscritos, uno ausente (igual cobra) | **$9.000** |

> "POR ASISTENCIA" = `per_plan_price` + `present_attendees` (gatilla por asistencia).
> "POR RESERVA" = `per_plan_price` + `active_enrollments` (cobra por inscrito aunque falte;
> no cobra si cancela dentro del deadline, porque se borra el `ConsumptionLog`).

## Notas

- **El backend rota el token en cada login** → el gym_admin se loguea UNA vez (setup) y los
  specs de API leen el token de `storageState.gym.json`.
- Las acciones de fila viven en un dropdown "Abrir acciones" (helper `openRowAction`) cuando
  hay 3+ acciones; inline si son 2. La `DataTable` renderiza doble (escritorio + móvil): usar
  `.first()` para visibilidad.
