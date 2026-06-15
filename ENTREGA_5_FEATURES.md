# Entrega — 5 Features (TYMRO)

Implementación de los 5 features, lista para QA local y deploy en Railway.
Todo el backend nuevo respeta multitenancy (`organization_id`) y la regla "el
backend es la única frontera de seguridad". **268 tests pasan** (230 previos sin
regresión + 38 nuevos). Revisión de seguridad multitenant: sin fugas cross‑tenant.

---

## Qué se implementó (y decisiones vs. el spec original)

### F1 — Modo de pago `per_plan_price`
- Nueva opción en `TeacherPaymentRule.PaymentType` + campo configurable
  `per_plan_price_base` (`active_enrollments` por defecto, o `present_attendees`).
- El profesor cobra **% del "precio por clase"** de cada alumno =
  `final_price / total_classes × %`, excluyendo planes ilimitados (misma política
  que `revenue_share`). El plan de cada alumno se resuelve por el `ConsumptionLog`
  real de esa clase.
- **Decisión (confirmada contigo):** la base de alumnos la elige el manager por
  regla. `active_enrollments` cuenta a todos los inscritos activos; `present_attendees`
  solo a los presentes.
- Validación `0–100%` y rechazo de `calculation_base` para este tipo viven en
  `TeacherPaymentRule.clean()` (admin) y `TeacherPaymentRuleSerializer.validate()` (API).
- Lógica: `core/services/teacher_payments.py` (`_calculate_plan_price_revenue_for_class`).

### F2 — `Enrollment.is_trial` + email de seguimiento
- `Enrollment.is_trial` y `Attendance.trial_followup_sent_at` (ambos read‑only por API).
- La reserva pública (`PublicTrialBookView`) marca `is_trial=True`.
- Modelo configurable por org: `TrialFollowupConfiguration` (activo/inactivo, minutos
  tras fin de clase, asunto y cuerpo con variables) + admin.
- Management command `send_trial_followups`: envía a alumnos que **asistieron**
  (presente/tarde) a una clase de prueba ya terminada, pasado el delay. Idempotente
  (`trial_followup_sent_at` + `select_for_update`) y scopeado por organización.
- **Decisión:** si una org no tiene `TrialFollowupConfiguration` activa, se omite
  (no se envía nada hasta configurarla). Ver "Post‑deploy".

### F3 — Matrícula (enrollment fee) por alumno
- **Cambio respecto al spec (confirmado contigo):** la matrícula vive en
  **`StudentPlan`** (individual), no en `Plan` (global). Campos:
  `enrollment_fee` (Decimal, 0 = sin matrícula), `enrollment_fee_paid_at`,
  `enrollment_fee_due_at` (read‑only por API; no se pueden forjar).
- **Bloqueo de reserva:** si el plan activo tiene `enrollment_fee > 0` y no está
  pagada, `reserve_student_in_class` rechaza con código `enrollment_fee_unpaid`.
- El vencimiento por defecto = creación + 365 días (calculado **después** de
  `super().save()` — se corrigió el bug del spec que leía `created_at` antes del INSERT).
- Se asigna al crear el `StudentPlan` (admin Django o importador, columna "Matrícula").
- `enrollment_fee_status` expuesto en `StudentPlanSerializer` (`waived/pending/paid/overdue`).

### F4 — Estado `SUSPENDED`
- `GymClass.Status.SUSPENDED` + `suspended_at`, `suspend_reason`, `suspended_by`,
  `reactivation_expected_date`.
- Endpoints `POST /api/classes/{id}/suspend/` y `/reactivate/`.
- **Decisión (seguridad):** permiso = `_can_close_or_cancel` (superadmin / org‑admin
  de la misma org / profesor dueño), **no** `IsAuthenticated`. Más estricto que el
  spec, consistente con el resto de acciones de cierre.
- `reactivate` recalcula el estado por horario (SCHEDULED / IN_PROGRESS); rechaza si
  la clase ya terminó.
- El scheduler (`refresh_status_from_schedule`) **no** reanima clases suspendidas.
- Las clases suspendidas **se ocultan al alumno** (listado y `?mine=1`) y **no son
  reservables** (`class_suspended`).
- Email de aviso a inscritos activos al suspender (no bloquea si el email falla).
- No se puede pasar a `suspended` por un PATCH normal: hay que usar la acción.

### F5 — Importador flexible (clases restantes / utilizadas + matrícula)
- Membresías acepta **`Clases utilizadas`** además de `Clases restantes`: indica una
  u otra; si vienen ambas deben sumar el total del plan; rango validado. Planes
  ilimitados ignoran el saldo.
- Columna opcional **`Matrícula`** → setea `StudentPlan.enrollment_fee` (F3).
- **Mejora del motor:** las columnas **opcionales** pueden faltar en el archivo (las
  obligatorias siguen siendo exigidas). Así agregar un campo opcional no rompe las
  plantillas ya distribuidas — verdadero "importador flexible".

### Migración
- Una sola migración aditiva y reversible: `core/migrations/0023_attendance_trial_followup_sent_at_and_more.py`.

---

## QA local (tu computadora)

```bash
cd backend
# (venv ya creado en backend/.venv)

# 1. Aplicar migraciones
.venv/Scripts/python manage.py migrate --settings=tymro.settings_test

# 2. Suite completa (config en pytest.ini -> tymro.settings_test)
.venv/Scripts/python -m pytest -q
#   -> 268 passed

# 3. Suites por feature
.venv/Scripts/python -m pytest core/tests/test_per_plan_price.py \
  core/tests/test_enrollment_fee.py \
  core/tests/test_class_suspension.py \
  core/tests/test_trial_followup.py \
  core/tests/test_importer.py -q

# 4. Probar el comando sin enviar nada
.venv/Scripts/python manage.py send_trial_followups --dry-run --settings=tymro.settings_test

# 5. Importador: descarga la plantilla de "Membresías activas" desde la UI;
#    ahora trae las columnas "Clases utilizadas" y "Matrícula".
```

> Nota: `coverage` no está en `requirements-dev.txt` (solo `pytest`/`pytest-django`),
> por lo que no se midió el % de cobertura. Se agregaron 38 tests que cubren los 5
> features (cálculos de pago, bloqueo de matrícula, suspensión, email de prueba,
> reconciliación de saldo del importador).

---

## Deploy a Railway

1. **Push a la rama de deploy** (Railway redeploya solo):
   ```bash
   git push origin <tu-rama>:deploy/railway-prod
   ```
   El `backend/Dockerfile` corre `python manage.py migrate` al arrancar, así que la
   migración `0023` se aplica automáticamente con las env vars de producción
   (`SECRET_KEY`, `DATABASE_URL`, `DEFAULT_FROM_EMAIL`, `FRONTEND_URL`, `EMAIL_*`).

2. **Scheduled Job para el email de prueba** (no hay Celery/Redis). En Railway,
   crea un *Cron/Scheduled Job* sobre el mismo servicio del backend:
   - Comando: `python manage.py send_trial_followups`
   - Schedule sugerido: `*/5 * * * *` (cada 5 min)

3. **Verifica el envío de correo en prod**: `DEFAULT_FROM_EMAIL` y `EMAIL_*` deben
   estar configurados (el backend usa SMTP cuando `DEBUG=False`).

---

## Post‑deploy

El email de seguimiento solo se envía a las organizaciones con una
`TrialFollowupConfiguration` **activa**. Para habilitarlo:

- **Por organización (recomendado):** créala/edítala en el admin de Django
  (`/admin/` → "Configuración de email de prueba"): activar, minutos de delay,
  asunto y cuerpo. Variables disponibles: `{student_name}`, `{org_name}`,
  `{class_name}`, `{teacher_name}`, `{signup_link}`.

- **Para todas de una vez (defaults):** en `manage.py shell`:
  ```python
  from core.models import Organization, TrialFollowupConfiguration
  for org in Organization.objects.all():
      TrialFollowupConfiguration.objects.get_or_create(organization=org)
  ```
  Crea config por defecto (activa, 30 min, plantilla estándar). Edítalas luego en el admin.

La matrícula (F3) se cobra cuando el `StudentPlan` se crea con `enrollment_fee > 0`
(admin Django o columna "Matrícula" del importador). El alumno no podrá reservar
hasta que un administrador marque `enrollment_fee_paid_at` (admin Django).
