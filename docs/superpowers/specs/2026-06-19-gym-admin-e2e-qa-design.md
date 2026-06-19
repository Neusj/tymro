# Spec — QA E2E completo del perfil gym_admin (navegador + backend real)

**Fecha:** 2026-06-19
**Rama:** `feature/gym-admin-e2e` (merge a `deploy/railway-prod` solo al 100% verde)
**Contexto:** Marcha blanca de R2B Fight Club HOY. Objetivo: validar TODAS las funciones de gym_admin sin fallos, con Playwright contra backend real, y corregir los bugs que bloquean el happy-path.

## Entorno (hallazgos confirmados)

- El stack que sirve `https://qa.tymroapp.com` es **Docker local** (`tymro-backend-1`, `tymro-frontend-1`, `tymro-cloudflared-1`); el túnel Cloudflare expone el backend local. Cambiar código backend + rebuild del contenedor + re-seed se ve en qa sin desplegar a un host externo.
- `seed_demo_data` es **destructivo** (`GymClass.objects.filter(organization=org).delete()`) y usa **usernames globales fijos** (`gymadmin`, `teacher1`, `student1`); `username` es único global. Sembrar otro org con el seed actual reasignaría esos usuarios → rompería `r2b-qa`.
- `r2b-qa` se nombra "R2B Fight Club QA" (seed L40): ES la data de R2B. **No tocar.**
- Rama actual al iniciar: `deploy/railway-prod` (auto-deploy a Railway). Por eso se trabaja en `feature/`.

## Decisiones bloqueadas (aprobadas por el usuario)

1. **Entorno:** org E2E dedicado `e2e-gym`, reusando el backend local. `r2b-qa` intacto.
2. **"Por reserva":** `per_plan_price` + `active_enrollments` (motor ya testeado; cobra por inscrito activo aunque falte; no cobra si cancela en deadline porque se borra el `ConsumptionLog`; deduplica). `revenue_share` queda legacy, no se promueve en UI.
3. **Alcance:** P0 + P1 + P2 **hoy**, sin diferir. Si algo falla, se arregla hoy.
4. **Git:** rama `feature/gym-admin-e2e`; merge a `deploy/railway-prod` al estar 100% verde.
5. **Rebuild backend:** rebuild del contenedor live ahora (~1-2 min de caída de qa.tymroapp.com aceptada). Los bugfixes quedan vivos para R2B (son mejoras netas).
6. **Cálculo de pagos:** validación **API-driven dentro de Playwright** (sembrar escenario vía API con token gym_admin, asertar monto exacto). No solo UI, no solo pytest.

## A. Bugfixes backend (P0)

### A1 — Serializer acepta `per_enrolled`, `per_hour`, `monthly_fixed`
`TeacherPaymentRuleSerializer.validate` (`backend/core/serializers.py:1377-1405`) hoy solo maneja `fixed_per_class`, `per_student`, `revenue_share`, `per_plan_price`; el `else` lanza `{'payment_type': 'Tipo de pago invalido.'}` para los otros 3, que SÍ son choices válidos (`models.py:498-505`) y los soporta el motor (`services/teacher_payments.py`). Fix: agregar ramas `elif` para los 3 (validan `amount ≥ 0`, fuerzan `calculation_base=None`), alineadas con `TeacherPaymentRule.clean()`.

### A2 — `PersonViewSet` seguro (multitenancy)
`PersonViewSet` (`backend/core/views.py:1448`) no declara permission class (default IsAuthenticated), no override de `perform_*`, y `PersonSerializer` (`serializers.py:254`) expone `organization`/`branch` escribibles → escritura cross-tenant. Fix (patrón estándar del repo):
- `permission_classes = [IsSuperAdminOrGymAdmin]`.
- `perform_create`/`perform_update`: fuerzan `organization=user.organization` para org-admin.
- `perform_destroy`: valida `instance.organization_id == user.organization_id`.
- `organization`/`branch` read-only para no-superadmin en el serializer (ignorar payload).

### A3 — Dropdown de reglas de pago (frontend)
`TeacherPaymentRulesPage.jsx` y `client.js`:
- El modo "% del precio del plan" muestra un selector de **base** con 2 opciones claras: **Por asistencia** (`per_plan_price_base=present_attendees`) y **Por reserva** (`=active_enrollments`).
- `client.js` envía `per_plan_price_base` en create/update.
- Los 5 tipos restantes (fijo, por presente, por inscrito, por hora, mensual) quedan operativos tras A1.
- Tabla/badges muestran el tipo y la base correctamente.

## B. Seed extendido (P0 — habilita el resto)

`backend/core/management/commands/seed_demo_data.py`:
- **Usernames con sufijo por org** cuando el org no es el canónico (`gymadmin_e2e`, `teacher_fijo_e2e`, `teacher_asis_e2e`, `teacher_res_e2e`, `s_a_e2e`, …). Garantiza que `e2e-gym` no reasigne usuarios de `r2b-qa`.
- Org `e2e-gym` ("TYMRO E2E Gym"), con su gym_admin, sucursales, disciplinas, tipos.
- **Fixtures deterministas de cálculo de pago:**
  - Plan A: `total_classes=4`, `price=40000` (→ $10.000/clase).
  - Plan B: `total_classes=8`, `price=40000` (→ $5.000/clase).
  - Plan ILIMITADO: `unlimited_classes=true` (→ $0/clase).
  - Alumnos con esos planes (StudentPlan + ConsumptionLog en las clases sembradas).
  - Profe FIJO con regla `fixed_per_class amount=5000`.
  - Profe ASISTENCIA con regla `per_plan_price present_attendees amount=40`.
  - Profe RESERVA con regla `per_plan_price active_enrollments amount=60`.
  - ≥2 disciplinas con reglas distintas (para el caso multi-disciplina).
  - Clases COMPLETED con mezcla de presentes/ausentes/cancelados-in-deadline.
- Ampliar la línea machine-readable `TYMRO_E2E_FIXTURES=` con ids/usernames/planes que consumen los specs de gym_admin (org_slug, gymAdmin user, plan ids, teacher ids, class ids por escenario).

## C. Harness E2E gym_admin (P0)

- `e2e/tests/20-gym-admin-auth.setup.js` → `storageState.gym.json`: login UI del gym_admin e2e (creds desde env), reintento ante throttle (5/min), `waitForURL(/\/gym-admin\/dashboard/)`, assert heading "Gym Admin · Dashboard".
- **Rotación de token:** el backend rota el token en cada login. Resolución: el token de API de gym_admin se lee del `storageState.gym.json` (helper `gymAdminTokenFromStorage` en `fixtures/data.js`); se elimina `captureGymAdminToken` de `global-setup.js` para que el login UI no invalide un token capturado antes. Los specs de QR / provisión usan el token del storage.
- `fixtures/data.js`: `creds.gymAdmin` desde `QA_GYM_ADMIN_E2E_USER/PASSWORD`; helpers de token/usuario desde storage.
- `playwright.config.js`: el project `setup` ya matchea `*-auth.setup.js` por regex; los specs gym_admin declaran `test.use({ storageState: 'storageState.gym.json' })`.

## D. Specs E2E gym_admin (P1 — ~25-30 specs, ~17 archivos)

| Archivo | Casos | Asserts clave |
|---|---|---|
| 21-gym-admin-auth | 2 | login ok→dashboard; inválido→error |
| 22-gym-admin-dashboard | 3 | 4 KPIs reales, scopeados a org, navegación de StatCards |
| 23-gym-admin-students | 5 | CRUD, asignar plan, ver saldos, quitar membresía (sin consumo) |
| 24-gym-admin-plans | 4 | CRUD mensual + ilimitado, precios, ver membresías |
| 25-gym-admin-disciplines-classtypes | 3 | CRUD + duplicado case-insensitive → 400 |
| 26-gym-admin-branches | 3 | CRUD + nombre duplicado → error UI |
| 27-gym-admin-classes | 5 | crear puntual; crear serie→generación; generar rango; cancelar/cerrar/suspender (bulk+individual) |
| 28-gym-admin-holidays | 2 | CRUD; festivo activo bloquea generación |
| 29-gym-admin-qr | 3 | QR rotante visible; pantalla recepción; regenerar código permanente |
| 30-gym-admin-teachers | 2 | CRUD de teachers |
| 31-gym-admin-payment-rules | 4 | crear AMBAS opciones (asistencia/reserva), %s 10/20/40/60, asignar profes |
| 32-gym-admin-payment-calc.api | 7-8 | **ver casos de cálculo abajo** |
| 33-gym-admin-payments-summary | 3 | resumen por período, marcar pagado, export CSV/XLSX |
| 34-gym-admin-import | 3 | catálogo→plantilla→validar→confirmar (disciplinas/sucursales); FK inexistente→rechazo |
| 35-gym-admin-trial-followup | 2 | editar config; negativos (asunto/cuerpo vacío, delay negativo) |
| 36-gym-admin-multitenancy.api | 2 | recurso de otra org → 404; sin leak en listados |
| 37-gym-admin-validations | 5 | plan dup/precio neg/clases neg→400; sucursal dup; clase capacidad/horario inválido→400; profe email dup→400 |

### Casos de cálculo (32-gym-admin-payment-calc.api) — montos exactos
- **FIJO:** profe FIJO, clase con 10 alumnos → **$5.000** (independiente de #alumnos).
- **POR ASISTENCIA 40%:** clase con Alumno1(PlanA $10k/clase, presente) + Alumno2(PlanB $5k/clase, presente) + Alumno3(ilimitado) → (10000+5000+0)×0.4 = **$6.000**.
- **Asistencia, Alumno1 falta:** Alumno1 ausente → solo Alumno2 → 5000×0.4 = **$2.000**.
- **Ilimitado siempre $0:** alumno ilimitado nunca aporta.
- **POR RESERVA 60%:** mismos alumnos inscritos activos (aunque falten) → (10000+5000)×0.6 = **$9.000**.
- **Reserva, cancelación in-deadline:** Alumno2 cancela dentro del deadline (se borra ConsumptionLog, enrollment no activo) → solo Alumno1 → 10000×0.6 = **$6.000**.
- **Multi-disciplina:** profe con regla por disciplina distinta → cada clase aplica su regla (matching `_match_rule_for_class`).
- **Período completo:** suma de todas las clases del mes del profe = total del resumen.

## E. Gaps pytest backend (P2)

- `test_teacher_payment_calc_modes.py`: `fixed_per_class` (monto fijo, #alumnos no importa); `per_plan_price` present/active a 10/20/40/60%; ilimitado=$0; ausente excluido en present; reserva cuenta inscrito aunque falte; matching por disciplina/sucursal/tipo; agregación de período multi-clase.
- `test_teacher_payment_rule_serializer.py`: acepta `per_enrolled`/`per_hour`/`monthly_fixed`; rechaza tipo inválido; `per_plan_price` exige base.
- `test_people_multitenant.py`: usuario de org A no puede crear/editar Person de org B.

## F. Reporte HTML + README (P2)

- Reporter HTML de Playwright a `e2e/reportes/` (ya configurado) + screenshot por flujo a `e2e/reportes/screenshots/` (captura al cierre de cada spec).
- README `e2e/README.md`: cómo correr solo gym_admin (`npx playwright test --grep @gym-admin` o project dedicado), variables de entorno nuevas, lista de casos críticos de cálculo.
- Sin credenciales hardcodeadas: todo por env (`e2e/.env`, `.env.example`).

## Env vars nuevas (en `e2e/.env` y `.env.example`)

- `QA_E2E_ORG_SLUG=e2e-gym`
- `QA_GYM_ADMIN_E2E_USER=gymadmin_e2e`
- `QA_GYM_ADMIN_E2E_PASSWORD=gymadmin123`
- `QA_SEED_CMD` para el org e2e: `docker compose exec -T backend python manage.py seed_demo_data --org=e2e-gym`
- (Las suites de estudiante/profesor también se repuntan al org e2e para no tocar r2b-qa.)

## Orden de implementación

1. Rama `feature/gym-admin-e2e` (hecho) + escribir/commit spec.
2. Bugfixes backend A1, A2 + gaps pytest (E) → `pytest` verde local.
3. Feature dropdown A3.
4. Seed extendido (B) con usernames por org + fixtures de cálculo.
5. **Rebuild `tymro-backend-1`** + seed `e2e-gym`.
6. Harness C (auth setup, storageState, token desde storage).
7. Specs P1 (D), iterando hasta verde.
8. Reporte + README (F).
9. Suite completa verde (estudiante + profesor + gym_admin) → generar reporte HTML.
10. (Tras aprobación) merge a `deploy/railway-prod`.

## Riesgos / mitigaciones

- **Rebuild del backend live:** ~1-2 min downtime de qa.tymroapp.com. Mitigación: rebuild único, rápido; los cambios son mejoras.
- **Throttle login 5/min:** reusar storageState y tokens; no re-login por test.
- **Colisión de usernames:** resuelto con sufijo por org en el seed.
- **Email real (SMTP Gmail):** evitar disparar reset/verify reales en E2E; trial-followup solo valida config + negativos (no entrega).
- **Migración:** A2/A3 no cambian modelos (sin migración). El seed no cambia esquema. Si algún ajuste de modelo surgiera, se genera migración.

## Criterio de aceptación

- 3 bugs corregidos (commits) y verificados.
- pytest backend verde con los gaps rellenados.
- E2E gym_admin 25-30 specs verdes contra backend real.
- Suites existentes verdes contra el org e2e: 39 estudiante + 21 profesor + 25+ gym_admin = 85+.
- Reporte HTML con screenshots por flujo.
- Sin credenciales hardcodeadas.
