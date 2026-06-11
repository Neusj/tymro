# CLAUDE.md — Backend (TYMRO)

SaaS multi-organización para gestión de gimnasios. **Django 5.0.6 + DRF 3.15.1**, Python 3.13. MVP en desarrollo.

## Comandos

```bash
cd backend
pip install -r requirements.txt
python manage.py makemigrations
python manage.py migrate
python manage.py runserver        # http://127.0.0.1:8000
```

- API bajo `/api/`, admin en `/admin/`.
- No hay scripts de `test` ni `lint` configurados.
- Con Docker: `docker-compose.yml` levanta backend (8000) + frontend + cloudflared.

## Arquitectura

- `tymro/` — config del proyecto (`settings.py`, `urls.py`).
- `accounts/` — `CustomUser` (`AUTH_USER_MODEL = 'accounts.CustomUser'`).
- `core/` — dominio del negocio:
  - `models.py` — todos los modelos.
  - `views.py` — ViewSets y APIViews (~2.300 líneas).
  - `serializers.py`, `urls.py` (router DRF), `permissions.py`.
  - `services/` — **lógica de negocio**: `reservations.py`, `recurrence.py`, `teacher_payments.py`, `class_dashboard.py`.

## Reglas clave

1. **Multi-tenant: SIEMPRE filtrar por `organization_id`.** Todo `get_queryset` filtra por organización y las escrituras validan pertenencia. Cualquier endpoint nuevo debe respetar esto.
2. **Lógica de negocio va en `core/services/`, no en las views.** Reservas, recurrencia y cálculo de pagos viven ahí.
3. **Usar el modelo `Plan`, NO `MembershipPlan`.** `MembershipPlanViewSet` opera sobre `Plan`.
4. **Estado de clases:** `GymClass.refresh_status_from_schedule()` recalcula según la hora; `_sync_class_statuses()` se llama en listados y dispara el cálculo de pagos al completar. No setear `status` a mano sin considerar este flujo.
5. **Reservas** consumen/devuelven clases del plan vía `ConsumptionLog` (ver `services/reservations.py`): validan plan activo, capacidad, solapes y organización.
6. **QR de asistencia:** tokens firmados con `django.core.signing`, TTL corto (10s); sesiones de pantalla con TTL 8h. Mantener este diseño anti-reutilización.

## Auth y permisos

- `TokenAuthentication` + `SessionAuthentication`. Login (`POST /api/login/`) devuelve token.
- Permiso por defecto: `IsAuthenticated` (salvo endpoints `AllowAny` como `/health/` y `/login/`).
- Permisos custom en `permissions.py`: `IsSuperAdmin`, `IsSuperAdminOrGymAdmin`.
- 6 roles (`CustomUser.Role`): `superadmin` (plataforma), `gym_admin`, `manager`, `monitor`, `teacher`, `student` (organización). Acceso por rol vía helpers `_is_superadmin/_is_gym_admin/_is_manager/_is_monitor/_is_teacher/_is_student`.
- **`accounts/roles.py` es la ÚNICA fuente de verdad** de qué rol puede asignar/gestionar quién (`PLATFORM_ROLES`, `ORG_ROLES`, `assignable_roles`, `can_assign`, `is_org_admin`). La misma matriz gobierna crear usuarios y editar/borrar instancias. No duplicar esa lógica en views/serializers.
- Locale: `es-cl`, `America/Santiago`, `USE_TZ=True`.

## Variables de entorno (nombres)

`SECRET_KEY`, `DJANGO_DEBUG`/`DEBUG`, `ALLOWED_HOSTS`, `DATABASE_URL` (o `POSTGRES_DB/USER/PASSWORD/HOST/PORT`), `SQLITE_DB_NAME`, `CORS_ALLOW_ALL_ORIGINS`, `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS`, `BACKEND_PORT`, `STUDENT_CANCEL_DEADLINE_HOURS`, `STUDENT_RECURRING_CHANGE_DEADLINE_HOURS`.

- DB: SQLite en dev, PostgreSQL en producción.

## ⚠️ Advertencias (estado actual del repo)

- **Duplicidad de modelos de plan:** coexisten `Plan` y `MembershipPlan`. La API usa `Plan`; `MembershipPlan` parece heredado. Confirmar antes de tocar planes.
- **Sin tests ni linter** configurados.
- **Sin paginación DRF** explícita (no hay `DEFAULT_PAGINATION_CLASS`); el frontend tolera listas y respuestas paginadas.
- **`AUTH_PASSWORD_VALIDATORS = []`** — validadores deshabilitados (a reforzar en producción).
- `STUDENT_CANCEL_DEADLINE_HOURS` y `STUDENT_RECURRING_CHANGE_DEADLINE_HOURS` no están en `.env.example` y usan default `0`.