# Suite E2E Profesor (Playwright) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: usar superpowers:subagent-driven-development o superpowers:executing-plans para ejecutar tarea por tarea. Los pasos usan checkbox (`- [ ]`).

**Goal:** Suite Playwright que valida los 9 flujos críticos del perfil Profesor contra QA (qa.tymroapp.com), al mismo nivel de solidez que la suite de estudiante.

**Architecture:** Reusa el harness existente en `e2e/`. Se agrega (1) una sesión de profesor (setup project → `storageState.teacher.json`), (2) un helper de aprovisionamiento de datos vía API de gym_admin (clases/alumnos/planes/reglas desechables), y (3) specs `1X-teacher-*.spec.js`. Patrón idéntico al de alumno: acción por UI + verificación por API, role-based locators, `apiContext`/`tokenFromStorage`, self-cleaning, serial global (workers:1).

**Tech Stack:** Playwright (ESM, JS), @playwright/test, dotenv. Backend Django/DRF (Token auth). Sin data-testid en el front (selectores por rol/texto en español).

## Global Constraints (copiados del harness real)

- Correr SIEMPRE desde `e2e/` con `npm test` (no hay package.json en la raíz). baseURL = `QA_BASE_URL` (default `https://qa.tymroapp.com`).
- Serial obligatorio: `fullyParallel:false`, `workers:1`. NO usar `test.step` ni `describe.serial` (la serialización es global). Locale `es-CL`, tz `America/Santiago`.
- El backend **ROTA el token en cada login** y `/login` tiene **throttle 5/min**. Cada usuario se loguea **una sola vez** (UI en su setup) → su `storageState`. Para API reusar el token guardado (`tokenFromStorage`), nunca re-loguear.
- Endpoints API sin slash inicial y con slash final (`classes/${id}/`), resueltos dentro de `/api/` por `apiContext`. Siempre `await ctx.dispose()`.
- Login es por **username** (no email): profesor = `teacher1` / `teacher123` (lo crea el seed).
- Multitenancy se valida a nivel API como **404 en el detalle** (no 403) + **no-leak en el listado**.
- El control de acceso del front es **cosmético**: toda restricción real la valida el backend.

---

## ⚠️ HALLAZGOS CRÍTICOS (verificados en código — responder "¿hay que arreglar algo YA?")

**H1 — El botón "Suspender clase" NO suspende: hace `complete_early` (cierre irreversible) y NO manda email.**
`TeacherClassesPage.jsx:421-428` → `closeClass(row,'complete_early')` → `classesApi.completeEarly` → `POST /classes/{id}/complete-early/` → `status=COMPLETED_EARLY`, `is_active=false`, consolida asistencia y dispara pago. El endpoint real `suspend` (`views.py:1966`, `status=SUSPENDED` + email `_notify_suspension`) **no tiene ningún botón en la UI del profesor**. Consecuencia: el flujo 5 (suspender + email) y el flujo 7 (complete-early) son **el MISMO botón**, y "Suspender" cierra la clase de forma **irreversible** (no es una pausa reactivable). Riesgo demo: el cliente clickea "Suspender" esperando pausar y cierra la clase para siempre. **Recomendación: renombrar el botón a "Cerrar clase (anticipado)" o cablearlo al endpoint `suspend` real antes de la demo.**

**H2 — Cancelar una clase NO devuelve el saldo a los alumnos.**
La acción `cancel` (`views.py:1920-1940`) solo cambia `status=CANCELLED`; **nunca** llama a `cancel_enrollment_with_refund`. Las inscripciones quedan `active` sobre una clase cancelada y su `ConsumptionLog` NO se revierte → el alumno pierde la clase consumida. El refund (`reservations.py:186`) solo ocurre al cancelar **cada inscripción individual** (ahí sí, porque `should_refund_consumption` devuelve True si la clase está CANCELLED). Consecuencia: el flujo 6 ("devolución de saldo al cancelar") **no se cumple** a nivel de clase. **Recomendación: que la acción `cancel` itere las inscripciones activas y haga refund, o documentarlo como limitación. El test lo dejará explícito.**

**H3 — "Mis pagos" sale vacío con el seed actual y no hay plan ilimitado.**
El seed NO crea `TeacherPaymentRule`/`TeacherPaymentRecord` ni ningún plan `unlimited_classes=True`. Por eso el flujo 8 (pagos) y la validación de pago $0 con plan ilimitado **necesitan datos aprovisionados** (vía API de gym_admin) — no es un bug, es estado de datos. Se resuelve sin tocar el seed ni rebuildear el backend.

---

## RESPUESTAS A LAS 4 PREGUNTAS DEL PLAN

### 1) Env vars nuevas
Agregar a `e2e/.env` y `e2e/.env.example` (siguiendo la convención `QA_*`):
```
QA_TEACHER_USER=teacher1
QA_TEACHER_PASSWORD=teacher123
```
(El seed ya crea `teacher1`/`teacher123` y `teacher2`/`teacher123`. Login por username.) No se requiere otra var: gym_admin (`QA_GYM_ADMIN_USER/PASSWORD`) y la org foránea (`QA_FOREIGN_*`) ya existen y se reusan para aprovisionar y para multitenancy.

### 2) Preparación de datos — **NO se extiende el seed** (evita rebuild del backend la noche previa)
- **Sesión profesor:** un setup spec loguea `teacher1` por UI una vez → `storageState.teacher.json`.
- **Datos read-only (clases/roster/historial):** se usan los que el seed YA crea para `teacher1` (clases futuras SCHEDULED, completadas, en curso, con alumnos inscritos).
- **Datos mutables/irreversibles y de pagos:** un helper `fixtures/teacherProvision.js` los crea **vía API de gym_admin** en tiempo de test (idempotente, por nombre/username determinista):
  - clases desechables futuras asignadas a `teacher1` (para asistencia/inscribir/quitar/cerrar/cancelar/suspender),
  - alumnos desechables con plan **ilimitado** (para inscribir sin tocar el saldo del seed y para el test $0),
  - una `TeacherPaymentRule` (`per_plan_price` o `revenue_share`) asignada a `teacher1` (para que "Mis pagos" tenga datos y para el $0).
- **Idempotencia:** las clases desechables las borra el seed en la próxima corrida (global-setup wipea `GymClass` de la org). Alumnos/planes/reglas se crean con get-or-create por nombre para no acumular en re-runs.

### 3) Flujos que NO se pueden probar (o solo parcialmente)
- **Suspender real + email a alumnos (flujo 5):** la UI no llega al endpoint `suspend` (ver H1). Se prueba el `suspend` **solo por API** (status→SUSPENDED). El **contenido del email NO es verificable** en E2E (SMTP `fail_silently`, sin buzón accesible en QA).
- **Devolución de saldo al cancelar (flujo 6):** se prueba el comportamiento **real** (status→CANCELLED) y se **asserta/documenta** que el saldo NO se restituye automáticamente (H2). No se forzará un assert "verde" falso.
- **Clase en estado `in_progress` a demanda:** no hay API para forzarlo (es por reloj). No es necesario: asistencia/cerrar/cancelar/suspender funcionan sobre una clase `scheduled` futura, que sí se puede aprovisionar.
- **Marcar como pagado (pending→paid):** no existe en la UI del profesor (solo admin). Fuera de alcance del perfil profesor.
- **Ejecución desde este entorno:** la suite necesita `docker compose exec backend ... seed_demo_data` (global-setup) y red a qa.tymroapp.com. Si este sandbox no alcanza Docker/QA, la corrida la harás tú; te entrego comandos exactos y, si puedo, la ejecuto y reporto.

### 4) Timeline estimado
- Scaffolding (env, teacher setup, helpers de token + provisión): ~45–60 min.
- Specs 11–13 (login, clases/filtros/KPIs, asistencia, inscripciones): ~60–75 min.
- Specs 14–16 (cierre/cancelación, suspend API, pagos+CSV): ~60 min.
- Specs 17–18 ($0 ilimitado, multitenancy): ~30 min.
- Corrida contra QA + estabilización de selectores + reporte: ~45–60 min.
- **Total: ~4–5 h** de trabajo. Si hay que recortar para mañana: **Fase 1 (must-pass)** = setup + 11 + 12 + 14 + 16 + 18; **Fase 2** = 13, 15, 17.

---

## File Structure

- Create: `e2e/tests/00b-teacher-auth.setup.js` — login UI de teacher1 (1 vez) → `storageState.teacher.json` + assert landing (flujo 1 positivo).
- Modify: `e2e/.env`, `e2e/.env.example` — agregar `QA_TEACHER_USER`/`QA_TEACHER_PASSWORD`.
- Modify: `e2e/fixtures/data.js` — `creds.teacher`, `tokenFromStorage(path)` genérico (+ `teacherTokenFromStorage()`).
- Create: `e2e/fixtures/teacherProvision.js` — provisión idempotente vía gym_admin (clases/alumnos/planes/reglas desechables) + helpers de limpieza.
- Create: `e2e/tests/10-teacher-login.spec.js` — login negativo + guard de ruta (UI).
- Create: `e2e/tests/11-teacher-clases.spec.js` — próximas + filtros + KPIs + historial (UI, seed).
- Create: `e2e/tests/12-teacher-asistencia.spec.js` — roster + present/absent/late + guardar + verificación API (UI, desechable).
- Create: `e2e/tests/13-teacher-inscripciones.spec.js` — inscribir/quitar + rechazo "ya inscrito" (UI + API, desechable).
- Create: `e2e/tests/14-teacher-cierre.spec.js` — "Suspender clase"=complete_early + "Cancelar clase" + chequeo de saldo (UI, desechable; valida H1/H2).
- Create: `e2e/tests/15-teacher-suspend.api.spec.js` — suspend real + reactivate (API, desechable).
- Create: `e2e/tests/16-teacher-pagos.spec.js` — resumen/desglose/payout + export CSV (UI + API).
- Create: `e2e/tests/17-teacher-pago-ilimitado.api.spec.js` — pago $0 con plan ilimitado (API; limitación conocida).
- Create: `e2e/tests/18-teacher-multitenancy.api.spec.js` — 404 detalle + no-leak listado (API).

> Nota config: el setup project usa `testMatch: /auth\.setup\.js/`. El archivo `00b-teacher-auth.setup.js` contiene la subcadena `auth.setup.js`, así que es recogido por el setup project **sin tocar `playwright.config.js`**. Las specs de profesor declaran `test.use({ storageState: 'storageState.teacher.json' })` y corren bajo el project `chromium` con sesión de profesor (igual que `01-login` hace override de storageState). **Verificar el match del regex al implementar** (Task 2, paso de verificación).

---

## Tareas

### Task 1: Env vars + creds.teacher + token helper genérico

**Files:** Modify `e2e/.env`, `e2e/.env.example`, `e2e/fixtures/data.js`

- [ ] **Step 1:** Agregar a `e2e/.env` y `.env.example`:
```
QA_TEACHER_USER=teacher1
QA_TEACHER_PASSWORD=teacher123
```
- [ ] **Step 2:** En `data.js`, extender `creds` y generalizar el lector de token:
```js
export const creds = {
  student: { username: process.env.QA_USER || 'student1', password: process.env.QA_PASSWORD || 'student123' },
  gymAdmin: { username: process.env.QA_GYM_ADMIN_USER || 'gymadmin', password: process.env.QA_GYM_ADMIN_PASSWORD || 'gymadmin123' },
  teacher: { username: process.env.QA_TEACHER_USER || 'teacher1', password: process.env.QA_TEACHER_PASSWORD || 'teacher123' },
}

import { readFileSync } from 'node:fs'
export function tokenFromStorage(path) {
  const state = JSON.parse(readFileSync(path, 'utf8'))
  return state.origins?.[0]?.localStorage?.find((kv) => kv.name === 'tymro_token')?.value
}
export function teacherTokenFromStorage() { return tokenFromStorage('storageState.teacher.json') }
// studentTokenFromStorage() se mantiene; opcionalmente reescribir como tokenFromStorage('storageState.student.json')
```
- [ ] **Step 3 (verificación):** `node -e "import('./fixtures/data.js').then(m=>console.log(m.creds.teacher))"` desde `e2e/` → imprime `{ username:'teacher1', ... }`.

### Task 2: Setup de sesión del profesor (flujo 1 positivo)

**Files:** Create `e2e/tests/00b-teacher-auth.setup.js`

- [ ] **Step 1:** Replicar `00-auth.setup.js` pero para teacher, con assert de landing en `/teacher/classes/upcoming` y manejo de throttle (loop 4 intentos, `setup.setTimeout(120_000)`):
```js
import { test as setup, expect } from '@playwright/test'
import { creds } from '../fixtures/data.js'
const STORAGE = 'storageState.teacher.json'
setup('autenticación profesor (una sola vez)', async ({ page }) => {
  setup.setTimeout(120_000)
  for (let i = 0; i < 4; i++) {
    await page.goto('/login')
    await page.getByLabel('Usuario').fill(creds.teacher.username)
    await page.getByLabel('Contraseña').fill(creds.teacher.password)
    await page.getByRole('button', { name: 'Entrar' }).click()
    const throttled = page.getByText(/regulada|throttled/i)
    if (await throttled.isVisible().catch(() => false)) {
      const secs = Number((await throttled.textContent())?.match(/(\d+)\s*second/)?.[1] || 15)
      await page.waitForTimeout((secs + 1) * 1000); continue
    }
    break
  }
  await expect(page).toHaveURL(/\/teacher\/classes\/upcoming/)  // flujo 1: login válido lleva al profesor a sus clases
  await page.context().storageState({ path: STORAGE })
})
```
- [ ] **Step 2 (verificación del regex):** `npx playwright test --list 2>&1 | grep -i teacher-auth` → debe listar el setup bajo el project `setup`. Si NO aparece, agregar a `playwright.config.js` un `testMatch` explícito o renombrar el archivo.
- [ ] **Step 3:** Confirmar credenciales/landing exactos del componente Login (label "Usuario"/"Contraseña", botón "Entrar") leyendo `LoginPage.jsx` antes de fijar selectores.

### Task 3: Helper de aprovisionamiento (gym_admin API)

**Files:** Create `e2e/fixtures/teacherProvision.js`

- [ ] **Step 1:** Implementar funciones que reciben el token de gym_admin (`fx.tokens.gymAdmin`) y devuelven ids; idempotentes por nombre/username. Resolver FKs por GET (branches/class-types/disciplines/users) y el id de teacher1 por `GET users/?...`:
  - `getRefs(ctx)` → `{ teacherId, branchId, classTypeId, disciplineId }`.
  - `ensureUnlimitedPlan(ctx)` → crea/recupera Plan `E2E Ilimitado` con `unlimited_classes:true`.
  - `ensureStudents(ctx, n)` → crea/recupera `e2e_tprof_studN`, asigna el plan ilimitado.
  - `createFutureClass(ctx, {name, startOffsetMin})` → `POST classes/` (status default scheduled; start futuro). Devuelve `{id, name}`.
  - `enrollActive(ctx, classId, studentId)` → `POST enrollments/ {gym_class, student, status:'active'}`.
  - `ensureRule(ctx, {payment_type, amount})` + `assignRule(ctx, ruleId, [teacherId])`.
  - `cancelEnrollment(ctx, enrollmentId)` / `deleteClassIfPossible` para limpieza.
- [ ] **Step 2 (verificación):** un mini-script o el `beforeAll` de la primera spec que use el helper imprime los ids creados y responde 200/201.

> Payloads exactos (de los serializers): `classes/` requiere `{name, branch, teacher, class_type, discipline, start_datetime, end_datetime, capacity>0}`; `plans/` `{name, plan_type:'monthly', total_classes, duration_days, price, unlimited_classes:true}`; `plans/assign/` `{user, plan, start_date}`; `teacher-payment-rules/` `{payment_type, amount}` + `PUT teacher-payment-rules/{id}/assignments/ {teacher_ids:[...]}`. La org se fuerza sola (gym_admin).

### Task 4: Spec 11 — Ver mis clases + filtros + KPIs + historial (UI)

**Files:** Create `e2e/tests/11-teacher-clases.spec.js` (`test.use({ storageState: 'storageState.teacher.json' })`, `test.describe('11. Clases del profesor', ...)`)

- [ ] Próximas: `page.goto('/teacher/classes/upcoming')`; `expect(getByRole('heading',{name:'Teacher · Próximas clases'})).toBeVisible()`; KPI `getByText('Total clases')` visible; tabla con al menos 1 clase de teacher1.
- [ ] Filtro Estado: abrir FilterDropdown `getByRole('button',{name:/Estado:/})` → opción `'Programada'`; verificar filas. Filtro Disciplina análogo. (Viewport ≥1280 para tener `<table>`.)
- [ ] Historial: `page.goto('/teacher/classes/history')`; heading `'Teacher · Clases realizadas'`; KPIs `'Total asistentes'`/`'Ocupacion promedio'`; al menos una clase completada del seed.
- [ ] Verificación API opcional: `apiContext(teacherTokenFromStorage()).get('classes/?status=scheduled')` → todas con `teacher` = teacher1.

### Task 5: Spec 12 — Tomar asistencia (UI, clase desechable)

**Files:** Create `e2e/tests/12-teacher-asistencia.spec.js`

- [ ] `beforeAll`: provisionar clase futura + 2 alumnos ilimitados inscritos (helper, con token gym_admin de `fx.tokens.gymAdmin`).
- [ ] UI: `goto('/teacher/classes/upcoming')`; localizar la fila por nombre; abrir gear `getByRole('button',{name:'Abrir acciones'})` → `'Tomar asistencia'`.
- [ ] En el dialog `getByRole('dialog',{name:/Asistencia/})`: por cada alumno, scopear `.locator('label').filter({hasText: nombre}).getByRole('button',{name:'Presente'|'Ausente'|'Tarde'})`. Marcar present/absent/late en alumnos distintos.
- [ ] `Promise.all([page.waitForResponse(r=>r.url().includes('/attendance/')&&r.request().method()==='POST'), getByRole('button',{name:'Guardar asistencia'}).click()])`; `expect(resp.ok()).toBeTruthy()`.
- [ ] Verificación API: `GET classes/{id}/` (teacher token) → `attendances` con los status marcados.
- [ ] Limpieza: cancelar la clase desechable (o dejar que el seed la wipee).

### Task 6: Spec 13 — Inscribir / quitar + rechazo "ya inscrito"

**Files:** Create `e2e/tests/13-teacher-inscripciones.spec.js`

- [ ] `beforeAll`: clase futura desechable + 1 alumno ilimitado NO inscrito.
- [ ] Inscribir (UI): gear → `'Inscribir alumnos'`; en dialog `getByRole('dialog',{name:/Inscribir alumnos/})` buscar por `getByPlaceholder('Nombre, username o email')`, marcar checkbox del alumno (scopear por `<label>`), `getByRole('button',{name:'Inscribir seleccionados'})`. Verificar por API que la inscripción quedó `active`.
- [ ] Quitar (UI): gear → `'Ver inscritos'`; marcar y `'Quitar seleccionados'`; verificar API inscripción `cancelled`.
- [ ] Rechazo doble inscripción (API): con teacher token, `POST enrollments/ {gym_class, student, status:'active'}` dos veces → 2ª responde **400** con mensaje `'El alumno ya tiene una reserva para esta clase.'` (code `duplicate_enrollment`). Documentar que el front deshabilita el checkbox para alumnos sin saldo (window.alert 'Alumno sin clases disponibles' → registrar `page.on('dialog')`).

### Task 7: Spec 14 — "Suspender clase" (=complete_early) y "Cancelar clase" (UI; valida H1/H2)

**Files:** Create `e2e/tests/14-teacher-cierre.spec.js`

- [ ] `beforeAll`: 2 clases futuras desechables (una para "suspender", otra para "cancelar"), cada una con 1 alumno con plan **de saldo** (no ilimitado) para poder observar el saldo. Registrar saldo inicial vía `GET plans/my-plan/` con token del alumno (apiLogin del alumno desechable o gym_admin que lo consulte).
- [ ] **page.on('dialog')** registrado ANTES de actuar (los dos flujos usan `window.prompt`): `page.on('dialog', d => d.accept('Motivo E2E'))`.
- [ ] "Suspender clase": gear → `'Suspender clase'`; tras éxito, `GET classes/{id}/` → `status === 'completed_early'` (NO `suspended`). **Comentario en el test documentando H1** (el botón mal rotulado hace complete_early irreversible y no manda email).
- [ ] "Cancelar clase": gear → `'Cancelar clase'`; `GET classes/{id}/` → `status === 'cancelled'`. Luego `GET plans/my-plan/` del alumno → **assertar el comportamiento REAL**: `classes_used` NO disminuye (H2). El test documenta como **limitación conocida / bug a reportar**: cancelar clase no restituye saldo automáticamente.

### Task 8: Spec 15 — Suspend real + reactivate (API)

**Files:** Create `e2e/tests/15-teacher-suspend.api.spec.js`

- [ ] `beforeAll`: clase futura desechable de teacher1.
- [ ] Con **teacher token**: `POST classes/{id}/suspend/ {suspend_reason:'E2E'}` → 200; `GET classes/{id}/` → `status==='suspended'`, `is_active===false`. (Email: solo se constata que el endpoint responde 200; contenido no verificable.)
- [ ] `POST classes/{id}/reactivate/` → 200; `status` vuelve a `scheduled`/`in_progress` según reloj. Limpieza: cancelar la clase.
- [ ] Negativo: profesor sobre clase ajena (de teacher2 o foránea) → 404/403 (ver multitenancy).

### Task 9: Spec 16 — Mis pagos: resumen/desglose/payout + export CSV

**Files:** Create `e2e/tests/16-teacher-pagos.spec.js`

- [ ] `beforeAll`: `ensureRule(per_plan_price o fixed_per_class)` + `assignRule(teacher1)`; clase desechable futura con 2 alumnos; marcar asistencia present (API); `POST complete-early/` para que se genere `TeacherPaymentRecord`.
- [ ] UI: `goto('/teacher/payments')`; setear `getByLabel('Período')` al mes actual (`'2026-06'`); `expect(getByText(/Total del período/)).toBeVisible()`; verificar `'Sueldo base'`/`'Por clase'`/`'Total'` y el pill de `PayoutStatus` (`getByText('Pendiente',{exact:true})`).
- [ ] Export CSV: esperar a que el botón cargue; `const [dl]=await Promise.all([page.waitForEvent('download'), getByRole('button',{name:'CSV'}).click()])`; `expect(dl.suggestedFilename()).toBe('mis_pagos_2026-06.csv')`.
- [ ] Verificación de contenido (API): `page.request.get('/api/teacher-payments/summary/export/?date_from=2026-06-01&date_to=2026-06-30&fmt=csv')` con sesión de profesor → 200 y body con la clase del período.

### Task 10: Spec 17 — Pago $0 con plan ilimitado (API; limitación conocida)

**Files:** Create `e2e/tests/17-teacher-pago-ilimitado.api.spec.js`

- [ ] `beforeAll`: regla `per_plan_price` (o `revenue_share`) asignada a teacher1; clase desechable; inscribir un alumno **ilimitado**; marcar present (API); `complete-early`.
- [ ] Assert: en `GET teacher-payments/summary/` (teacher token) o en el `TeacherPaymentRecord`, la contribución de ese alumno = **$0** (los planes ilimitados se excluyen de la base — `teacher_payments.py:66`). Comentario: **limitación conocida, no bug**.

### Task 11: Spec 18 — Multitenancy (API)

**Files:** Create `e2e/tests/18-teacher-multitenancy.api.spec.js`

- [ ] Con teacher token: `GET classes/${fx.foreign.class_id}/` → **404** (`expect(...,'clase foránea debe dar 404').toBe(404)`).
- [ ] `GET classes/?organization_id=${fx.foreign.org_id}` → 200 y la lista **no** contiene la clase foránea (idiom `Array.isArray(data)?data:data.results||[]`).
- [ ] Acción de profesor sobre clase ajena: `POST classes/${fx.foreign.class_id}/attendance/` o `/suspend/` → 404/403. Documentar el código observado.

### Task 12: Correr contra QA + estabilizar + reporte

- [ ] `cd e2e && npm test -- 1*-teacher* 00b-teacher-auth.setup.js` (o `npm test` completo). Si global-setup no puede correr el seed en este entorno, usar `QA_SKIP_SEED=1` con `.fixtures.json` existente.
- [ ] Para cada fallo: clasificar en (a) selector frágil → ajustar, (b) comportamiento real distinto al esperado → documentar (H1/H2) o reportar bug. NO forzar verdes falsos.
- [ ] Entregar reporte: verde por flujo + lista de limitaciones conocidas (H1/H2/H3) + bugs nuevos si aparecen.

---

## Self-Review (cobertura vs flujos pedidos)
1. Login ✓ (Task 2 positivo + Task spec 10 negativo). 2. Ver clases/filtros/KPIs ✓ (Task 4). 3. Asistencia present/absent/late ✓ (Task 5). 4. Inscribir/quitar ✓ (Task 6). 5. Suspender+email → **parcial/flag H1** (UI=complete_early; suspend real solo API en Task 8; email no verificable). 6. Cancelar+devolución → **flag H2** (status sí; refund no, documentado, Task 7). 7. Complete-early ✓ (es el botón "Suspender", Task 7). 8. Pagos+CSV ✓ (Task 9). 9. Multitenancy ✓ (Task 11). Validaciones críticas: ya-inscrito ✓ (Task 6), doble inscripción ✓ (Task 6), cerrar sin asistencia completa ✓ (complete-early consolida ausentes, Task 7/9), pago ilimitado $0 ✓ (Task 10).

> Pendiente menor: spec `10-teacher-login.spec.js` (login negativo + guard de ruta) — añadir como Task 4-bis si se desea cubrir el caso negativo de credenciales.
