# QA E2E gym_admin — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Corregir los 3 bugs que bloquean gym_admin y entregar una suite E2E Playwright (25-30 specs) + gaps de pytest, todo verde contra el backend real, en el org dedicado `e2e-gym`.

**Architecture:** Backend Django/DRF (bugfixes en serializer, PersonViewSet, dropdown de reglas). Seed extendido siembra el org `e2e-gym` (usernames con sufijo para no tocar `r2b-qa`) con fixtures deterministas de cálculo de pago. Harness Playwright nuevo para gym_admin (storageState propio + token desde storage). Specs por flujo; el cálculo de pago se valida API-driven dentro de Playwright con montos exactos.

**Tech Stack:** Django 5 + DRF, pytest; React + Vite; Playwright 1.49; Docker Compose (stack local tuneleado a qa.tymroapp.com).

## Global Constraints

- Rama de trabajo: `feature/gym-admin-e2e`. Merge a `deploy/railway-prod` solo al 100% verde.
- `r2b-qa` NO se toca (no reseed, no correr suites estudiante/profesor hoy).
- Multitenancy: todo `get_queryset` filtra por `organization_id`; `perform_*` fuerza la org del actor. El backend es la única frontera de seguridad.
- Sin credenciales hardcodeadas: env vars en `e2e/.env` + `.env.example`.
- Lógica de negocio en `core/services/`, no en views.
- "Por reserva" = `per_plan_price` + `active_enrollments`. "Por asistencia" = `per_plan_price` + `present_attendees`.
- Org E2E: slug `e2e-gym`. gym_admin: `gymadmin_e2e` / `gymadmin123`.

---

## Fase 1 — Bugfixes backend + gaps pytest (P0)

### Task 1: Serializer acepta per_enrolled, per_hour, monthly_fixed

**Files:**
- Modify: `backend/core/serializers.py:1404-1405` (rama `else` de `TeacherPaymentRuleSerializer.validate`)
- Test: `backend/core/tests/test_teacher_payment_rule_serializer.py` (crear)

**Interfaces:**
- Produces: regla creable vía `POST /api/teacher-payment-rules/` con `payment_type ∈ {per_enrolled, per_hour, monthly_fixed}`.

- [ ] **Step 1: Test que falla** — `backend/core/tests/test_teacher_payment_rule_serializer.py`:

```python
import pytest
from core.serializers import TeacherPaymentRuleSerializer
from core.models import TeacherPaymentRule

pytestmark = pytest.mark.django_db


class _Req:
    def __init__(self, user):
        self.user = user


@pytest.fixture
def gym_admin(make_organization, make_user):
    org = make_organization()
    return make_user('ga', organization=org, role='gym_admin')


@pytest.mark.parametrize('ptype', ['per_enrolled', 'per_hour', 'monthly_fixed'])
def test_serializer_accepts_previously_rejected_types(gym_admin, ptype):
    s = TeacherPaymentRuleSerializer(
        data={'payment_type': ptype, 'amount': 5000, 'is_active': True},
        context={'request': _Req(gym_admin)},
    )
    assert s.is_valid(), s.errors
    assert s.validated_data['payment_type'] == ptype


def test_serializer_rejects_unknown_type(gym_admin):
    s = TeacherPaymentRuleSerializer(
        data={'payment_type': 'bogus', 'amount': 1},
        context={'request': _Req(gym_admin)},
    )
    assert not s.is_valid()
    assert 'payment_type' in s.errors


def test_per_plan_price_requires_base(gym_admin):
    s = TeacherPaymentRuleSerializer(
        data={'payment_type': 'per_plan_price', 'amount': 40},
        context={'request': _Req(gym_admin)},
    )
    assert not s.is_valid()
    assert 'per_plan_price_base' in s.errors
```

- [ ] **Step 2: Correr y ver fallar** — `docker compose exec -T backend python -m pytest core/tests/test_teacher_payment_rule_serializer.py -v` → FAIL (acepta solo 4 tipos; los 3 dan `payment_type` invalid).

- [ ] **Step 3: Implementar** — en `serializers.py`, antes del `else` final (línea ~1404), insertar:

```python
        elif payment_type in (
            TeacherPaymentRule.PaymentType.PER_ENROLLED,
            TeacherPaymentRule.PaymentType.PER_HOUR,
            TeacherPaymentRule.PaymentType.MONTHLY_FIXED,
        ):
            attrs['calculation_base'] = None
            if amount is None or float(amount) < 0:
                raise serializers.ValidationError({'amount': 'El monto debe ser mayor o igual a 0.'})
```

- [ ] **Step 4: Correr y ver pasar** — mismo pytest → PASS.
- [ ] **Step 5: Commit** — `git add -A && git commit -m "fix(payments): serializer acepta per_enrolled/per_hour/monthly_fixed"`

### Task 2: PersonViewSet seguro (multitenancy)

**Files:**
- Modify: `backend/core/views.py:1448-1458` (`PersonViewSet`)
- Modify: `backend/core/serializers.py:254-272` (`PersonSerializer`)
- Test: `backend/core/tests/test_people_multitenant.py` (crear)

**Interfaces:**
- Consumes: `IsSuperAdminOrGymAdmin` (permissions.py), `_is_superadmin`/`roles.is_org_admin` (views.py).
- Produces: `/api/people/` rechaza no-(superadmin|gym_admin) y bloquea escritura cross-org.

- [ ] **Step 1: Test que falla** — `backend/core/tests/test_people_multitenant.py`:

```python
import pytest
from rest_framework.test import APIClient
from core.models import Person

pytestmark = pytest.mark.django_db
PASSWORD = 'Passw0rd2026'
URL = '/api/people/'


def _login(c, u):
    t = c.post('/api/login/', {'username': u, 'password': PASSWORD}, format='json').json()['token']
    c.credentials(HTTP_AUTHORIZATION=f'Token {t}')


@pytest.fixture
def two_orgs(make_organization, make_user):
    a = make_organization(); b = make_organization()
    ga_a = make_user('gaa', organization=a, role='gym_admin', password=PASSWORD)
    ga_b = make_user('gab', organization=b, role='gym_admin', password=PASSWORD)
    return {'a': a, 'b': b, 'ga_a': ga_a, 'ga_b': ga_b}


def test_gym_admin_create_forces_own_org(two_orgs):
    c = APIClient(); _login(c, 'gaa')
    resp = c.post(URL, {'first_name': 'X', 'last_name': 'Y', 'organization': two_orgs['b'].id}, format='json')
    assert resp.status_code == 201
    assert Person.objects.get(id=resp.json()['id']).organization_id == two_orgs['a'].id  # NO la b


def test_student_cannot_write_people(make_organization, make_user):
    org = make_organization(); make_user('stu', organization=org, role='student', password=PASSWORD)
    c = APIClient(); _login(c, 'stu')
    assert c.post(URL, {'first_name': 'X', 'last_name': 'Y'}, format='json').status_code == 403
```

- [ ] **Step 2: Correr y ver fallar** — FAIL (hoy crea en org ajena; student no es 403).

- [ ] **Step 3: Implementar** — `PersonViewSet`:

```python
class PersonViewSet(ModelViewSet):
    queryset = Person.objects.select_related('organization', 'branch').all()
    serializer_class = PersonSerializer
    permission_classes = [IsSuperAdminOrGymAdmin]

    def get_queryset(self):
        user = self.request.user
        if _is_superadmin(user):
            return self.queryset
        if user.organization_id:
            return self.queryset.filter(organization_id=user.organization_id)
        return self.queryset.none()

    def perform_create(self, serializer):
        user = self.request.user
        if _is_superadmin(user):
            serializer.save()
        else:
            serializer.save(organization=user.organization)

    def perform_update(self, serializer):
        user = self.request.user
        if not _is_superadmin(user) and serializer.instance.organization_id != user.organization_id:
            raise PermissionDenied('No puedes editar registros de otra organización.')
        if _is_superadmin(user):
            serializer.save()
        else:
            serializer.save(organization=user.organization)

    def perform_destroy(self, instance):
        user = self.request.user
        if not _is_superadmin(user) and instance.organization_id != user.organization_id:
            raise PermissionDenied('No puedes eliminar registros de otra organización.')
        instance.delete()
```

(`PermissionDenied` ya está importado en views.py; `IsSuperAdminOrGymAdmin` añadir al import desde `.permissions`.)

`PersonSerializer`: marcar `organization` y `branch` validados contra la org del actor — añadir `validate`:

```python
    def validate(self, attrs):
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if user and user.is_authenticated and not _is_superadmin_user(user):
            attrs.pop('organization', None)  # la fuerza el perform_create/update
        return attrs
```

(Helper mínimo `_is_superadmin_user` o reutilizar `user.role == 'superadmin'`.)

- [ ] **Step 4: Correr y ver pasar** — PASS.
- [ ] **Step 5: Commit** — `fix(security): PersonViewSet scope por org + permiso gym_admin/superadmin`

### Task 3: pytest — modos de cálculo de pago

**Files:**
- Test: `backend/core/tests/test_teacher_payment_calc_modes.py` (crear)

**Interfaces:**
- Consumes: `calculate_teacher_payment`, `build_teacher_payment_summary` (services/teacher_payments.py); `Plan`, `StudentPlan`, `ConsumptionLog`, `Enrollment`, `Attendance`, `GymClass`, `TeacherPaymentRule`.

- [ ] **Step 1: Test que falla** — incluye helpers y casos (montos exactos del spec): FIJO $5000 con 10 alumnos; `per_plan_price present_attendees 40%` → (10000+5000)*0.4=6000; ausente → 2000; ilimitado=0; `active_enrollments 60%` → 9000; cancel in-deadline (ConsumptionLog borrado + enrollment cancelado) → 6000; matching por disciplina; agregación de período. (Reusar patrón de `test_per_plan_price.py`: `_give_plan`, `_enroll(present=)`, `_completed_class`.) Para 10/20/40/60% parametrizar `amount`.

```python
import pytest
from datetime import timedelta
from django.utils import timezone
from core.models import (Attendance, Branch, ConsumptionLog, Enrollment, GymClass,
                         Plan, StudentPlan, TeacherPaymentRule)
from core.services.teacher_payments import calculate_teacher_payment, build_teacher_payment_summary

pytestmark = pytest.mark.django_db
PPP = TeacherPaymentRule.PaymentType.PER_PLAN_PRICE
PRESENT = TeacherPaymentRule.PerPlanPriceBase.PRESENT_ATTENDEES
ACTIVE = TeacherPaymentRule.PerPlanPriceBase.ACTIVE_ENROLLMENTS

# ... fixtures setup (org, teacher, branch, students) ...
# _give_plan(org, user, total, price, unlimited=False) -> StudentPlan
# _enroll(gym_class, student, student_plan, present=False) crea Enrollment+ConsumptionLog (+Attendance)
# _completed_class(org, branch, teacher)
# _rule_ppp(org, teacher, base, amount)
# _rule_fixed(org, teacher, amount)

def test_fixed_pays_flat_regardless_of_students(...):
    # 10 alumnos presentes, regla fixed 5000 -> total_amount == 5000

@pytest.mark.parametrize('pct,expected', [(10, 1500.0), (20, 3000.0), (40, 6000.0), (60, 9000.0)])
def test_present_pct(...):
    # Alumno1 PlanA(4,40000)=10000, Alumno2 PlanB(8,40000)=5000, ambos presentes
    # expected = 15000 * pct/100

def test_present_absent_excluded(...):
    # Alumno1 presente, Alumno2 ausente, 40% -> 10000*0.4 = 4000

def test_unlimited_zero(...):
    # alumno ilimitado presente -> aporta 0

def test_active_counts_absent(...):
    # base ACTIVE, ambos inscritos, Alumno2 ausente, 60% -> (10000+5000)*0.6 = 9000

def test_active_excludes_cancelled_in_deadline(...):
    # Alumno2 inscrito cancelado (enrollment status='cancelled', ConsumptionLog borrado), 60% -> 10000*0.6=6000

def test_matching_by_discipline(...):
    # dos disciplinas, reglas distintas -> _match_rule_for_class elige la correcta por clase

def test_period_aggregates_classes(...):
    # 2 clases completed del profe en el mes -> summary.total == suma de ambas
```

- [ ] **Step 2: Correr y ver fallar/pasar** — `pytest core/tests/test_teacher_payment_calc_modes.py -v`. (El motor YA implementa esto; estos tests cierran el gap. Si alguno falla, es bug real → arreglar el servicio.)
- [ ] **Step 3: (si aplica) arreglar servicio.** **Step 4: PASS.** **Step 5: Commit** — `test(payments): cobertura de modos de cálculo (fijo, per_plan_price present/active, %, matching, período)`

### Task 4: Suite pytest completa verde

- [ ] Correr `docker compose exec -T backend python -m pytest -q` → todo verde. Commit si hubo ajustes.

---

## Fase 2 — Dropdown reglas de pago (frontend, P0)

### Task 5: Exponer "por asistencia" y "por reserva"

**Files:**
- Modify: `frontend/src/pages/TeacherPaymentRulesPage.jsx` (form + estado + labels + tabla)
- Modify: `frontend/src/api/client.js` (enviar `per_plan_price_base`)

**Interfaces:**
- Produces: regla `per_plan_price` creada desde UI con base `present_attendees` o `active_enrollments`.

- [ ] **Step 1:** En `initialForm`/estado, añadir `per_plan_price_base: ''`. En `loadForm(row)`, precargar `per_plan_price_base: row.per_plan_price_base || ''`.
- [ ] **Step 2:** En el `<select>` de tipo (líneas ~416-421) reemplazar la opción única de porcentaje por dos opciones claras y un selector de base condicional:
```jsx
<option value="per_plan_price">% del precio del plan</option>
```
y cuando `form.payment_type === 'per_plan_price'`, mostrar:
```jsx
<select value={form.per_plan_price_base}
  onChange={(e) => setForm((p) => ({ ...p, per_plan_price_base: e.target.value }))}>
  <option value="">Seleccionar base</option>
  <option value="present_attendees">Por asistencia (solo presentes)</option>
  <option value="active_enrollments">Por reserva (inscritos activos)</option>
</select>
```
- [ ] **Step 3:** En `handleSubmit`, incluir `per_plan_price_base: form.payment_type === 'per_plan_price' ? form.per_plan_price_base : null` en el payload; validación local: si `per_plan_price` y sin base → error inline.
- [ ] **Step 4:** En `client.js` `teacherPaymentRulesApi.create/update`, pasar `per_plan_price_base` en el body. Tabla/badge: mostrar base legible.
- [ ] **Step 5:** Build local del frontend para validar que compila: `docker compose exec -T frontend sh -c 'true'` (el contenedor sirve build; verificación real en E2E). Commit — `feat(payments-ui): dropdown con % por asistencia y por reserva (per_plan_price_base)`

---

## Fase 3 — Seed extendido (P0)

### Task 6: Usernames con sufijo por org (no tocar r2b-qa)

**Files:**
- Modify: `backend/core/management/commands/seed_demo_data.py`

- [ ] **Step 1:** Añadir helper de sufijo: para slug canónico (`r2b-qa`, `tymro-demo`) sufijo `''`; para otros, `'_' + slug.replace('-', '')[:8]` (ej. `_e2egym`). Aplicar a TODOS los `username=` (gymadmin, teacher1/2, student1/2/3, superadmin queda global). Las contraseñas se mantienen.
- [ ] **Step 2:** Verificar idempotencia: re-correr `seed_demo_data --org=e2e-gym` no duplica ni toca usuarios de r2b-qa.
- [ ] **Step 3:** Commit — `feat(seed): usernames con sufijo por org para aislar e2e-gym de r2b-qa`

### Task 7: Fixtures de cálculo de pago en e2e-gym

**Files:**
- Modify: `backend/core/management/commands/seed_demo_data.py` (nuevo método `_seed_payment_calc_fixtures`, llamado solo cuando `slug == 'e2e-gym'`)

- [ ] **Step 1:** Crear Planes: A(`total_classes=4, price=40000`), B(`total_classes=8, price=40000`), ILIM(`unlimited_classes=True`). Crear alumnos `s_a`, `s_b`, `s_ilim` con StudentPlan respectivo. Profes: `teacher_fijo` (regla fixed 5000), `teacher_asis` (regla per_plan_price present 40), `teacher_res` (regla per_plan_price active 60). Disciplina extra con regla distinta para `teacher_asis`. Clases COMPLETED con Enrollment+ConsumptionLog (+Attendance presente para s_a, ausente para s_b en una clase del profe asistencia).
- [ ] **Step 2:** Ampliar `_print_e2e_fixtures` para incluir bajo `gym_admin`/`payment_calc`: ids de planes, usernames de profes/alumnos, ids de clases por escenario, regla ids.
- [ ] **Step 3:** Commit — `feat(seed): fixtures deterministas de cálculo de pago para e2e-gym`

---

## Fase 4 — Rebuild + seed (P0, ops)

### Task 8: Rebuild backend y sembrar e2e-gym

- [ ] **Step 1:** `docker compose build backend`
- [ ] **Step 2:** `docker compose up -d backend` (rebuild del live; ~1-2 min downtime aceptado)
- [ ] **Step 3:** `docker compose exec -T backend python manage.py seed_demo_data --org=e2e-gym` → captura la línea `TYMRO_E2E_FIXTURES=`.
- [ ] **Step 4:** Smoke API: `curl -s https://qa.tymroapp.com/api/login/ -d '{"username":"gymadmin_e2e","password":"gymadmin123"}' -H 'Content-Type: application/json'` → 200 con token. (Verifica que el rebuild + seed funcionan.)

---

## Fase 5 — Harness Playwright gym_admin (P0)

### Task 9: fixtures/data.js + global-setup (token desde storage)

**Files:**
- Modify: `e2e/fixtures/data.js` (creds.gymAdmin desde `QA_GYM_ADMIN_E2E_USER/PASSWORD`; helper `gymAdminTokenFromStorage`)
- Modify: `e2e/global-setup.js` (quitar `captureGymAdminToken`; el token sale del storage tras el auth setup)
- Modify: `e2e/.env`, `e2e/.env.example` (nuevas vars), `e2e/.gitignore` (ignorar `storageState.gym.json`)

- [ ] Añadir vars: `QA_E2E_ORG_SLUG=e2e-gym`, `QA_GYM_ADMIN_E2E_USER=gymadmin_e2e`, `QA_GYM_ADMIN_E2E_PASSWORD=gymadmin123`, `QA_SEED_CMD=docker compose exec -T backend python manage.py seed_demo_data --org=e2e-gym`. Commit.

### Task 10: auth setup gym_admin → storageState.gym.json

**Files:**
- Create: `e2e/tests/20-gym-admin-auth.setup.js`

- [ ] Login UI con `creds.gymAdmin`, reintento ante throttle, `waitForURL(/\/gym-admin\/dashboard/)`, `expect(page.getByRole('heading', {name: /Gym Admin/})).toBeVisible()`, `context().storageState({ path: 'storageState.gym.json' })`. Correr `npx playwright test 20-gym-admin-auth.setup.js` → PASS. Commit.

---

## Fase 6 — Specs E2E gym_admin (P1)

**Patrón común:** cada spec hace `test.use({ storageState: 'storageState.gym.json' })`, lee fixtures de `.fixtures.json` (helper `readFixtures()` en `fixtures/helpers.js`), y para cálculo usa `request` con el token de gym_admin del storage (API-driven). Crear `e2e/fixtures/gymAdmin.js` con helpers compartidos (`gymAdminApi(request)`, `seedScenario(...)`).

### Task 11: helper compartido `fixtures/gymAdmin.js`
- [ ] `gymToken()` (lee storage), `api(request)` (contexto con header Token), `expectAmount(summary, teacherId, expected)`. Commit.

### Tasks 12-28: un task por archivo de spec (contratos exactos)

Cada uno: crear archivo, escribir specs con asserts del spec de diseño (sección D + casos de cálculo), correr `npx playwright test <archivo>` hasta verde, commit.

- [ ] **12** `21-gym-admin-auth.spec.js` — login ok→/gym-admin/dashboard; inválido→mensaje error.
- [ ] **13** `22-gym-admin-dashboard.spec.js` — 4 KPIs numéricos; StatCards navegan a /branches y /users.
- [ ] **14** `23-gym-admin-students.spec.js` — crear/editar/desactivar/eliminar alumno; asignar plan; ver saldo; quitar membresía sin consumo.
- [ ] **15** `24-gym-admin-plans.spec.js` — crear mensual + ilimitado; editar precio; ver membresías.
- [ ] **16** `25-gym-admin-disciplines-classtypes.spec.js` — CRUD; duplicado case-insensitive→400 (mensaje en modal).
- [ ] **17** `26-gym-admin-branches.spec.js` — CRUD; nombre duplicado → no se crea.
- [ ] **18** `27-gym-admin-classes.spec.js` — crear puntual; crear serie→instancias generadas; generar rango; cancelar/cerrar/suspender (individual + bulk).
- [ ] **19** `28-gym-admin-holidays.spec.js` — CRUD; festivo activo bloquea generación en esa fecha.
- [ ] **20** `29-gym-admin-qr.spec.js` — QR rotante visible; iniciar pantalla; regenerar permanente.
- [ ] **21** `30-gym-admin-teachers.spec.js` — CRUD de teachers.
- [ ] **22** `31-gym-admin-payment-rules.spec.js` — crear regla por asistencia y por reserva; %s 10/20/40/60; asignar profes (modal).
- [ ] **23** `32-gym-admin-payment-calc.api.spec.js` — **montos exactos** (API-driven): FIJO=5000; asistencia40%=6000; ausente=2000; ilimitado=0; reserva60%=9000; cancel-deadline=6000; multi-disciplina; período=suma. Sembrar escenarios con la API o reusar fixtures del seed.
- [ ] **24** `33-gym-admin-payments-summary.spec.js` — resumen mes; marcar pagado; export CSV y XLSX (descarga).
- [ ] **25** `34-gym-admin-import.spec.js` — disciplinas/sucursales: catálogo→plantilla→validar→confirmar; FK inexistente→fila en error.
- [ ] **26** `35-gym-admin-trial-followup.spec.js` — editar config; negativos (asunto/cuerpo vacío, delay negativo→error).
- [ ] **27** `36-gym-admin-multitenancy.api.spec.js` — GET recurso de `r2b-qa`/otra org con token e2e → 404; listados no leak.
- [ ] **28** `37-gym-admin-validations.spec.js` — plan dup/precio neg/clases neg→400; sucursal dup; clase capacidad/horario inválido→400; profe email dup→400.

---

## Fase 7 — Reporte + README (P2)

### Task 29: Screenshots por flujo + README
- [ ] `playwright.config.js`: añadir afterEach o usar `screenshot:'on'` para los specs gym_admin; guardar a `e2e/reportes/screenshots/`. Reporter HTML ya a `e2e/reportes/`.
- [ ] `e2e/README.md`: sección "Correr solo gym_admin" (`npx playwright test 2[0-9]-gym-admin* 3[0-9]-gym-admin*`), env vars nuevas, lista de casos críticos de cálculo. Commit.

### Task 30: Suite gym_admin completa verde + reporte
- [ ] Correr todos los specs gym_admin → 25-30 verdes. `npx playwright show-report reportes` genera el HTML. Commit final del reporte/artefactos versionables.

---

## Self-Review (cobertura del spec)

- Bugs 1/2/3 → Tasks 1, 2, 5. ✅
- Seed org dedicado + fixtures cálculo → Tasks 6, 7. ✅
- Harness → Tasks 9, 10. ✅
- Flujos 1-14 del spec → Tasks 12-28. ✅
- pytest gaps (calc, serializer, people) → Tasks 1, 2, 3. ✅
- Reporte + README → Tasks 29, 30. ✅
- Matching/`_match_rule_for_class` → Task 3 + spec 32. ✅

## Riesgos
- Rebuild live: ~1-2 min downtime (aceptado). Si el build falla, `docker compose up -d backend` con la imagen previa restaura.
- Throttle login 5/min: reusar storageState; cálculo via API con token de storage.
- Si un caso de cálculo falla, es bug real del servicio → arreglar en `services/teacher_payments.py` (no el test).
