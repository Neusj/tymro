# CLAUDE.md — Backend (TYMRO)

SaaS multi-organización para gestión de gimnasios. **Django 5.0.6 + DRF 3.15.1**, Python 3.13. MVP en desarrollo.

## Comandos

```bash
cd backend
pip install -r requirements.txt
python manage.py makemigrations
python manage.py migrate
python manage.py runserver        # http://127.0.0.1:8000
python -m pytest                  # suite de tests (config en pytest.ini)
```

- API bajo `/api/`, admin en `/admin/`.
- **Tests con `pytest`** (ver `pytest.ini` y `conftest.py`); la suite vive en `core/tests/` e incluye, entre otros, `test_multitenant`, `test_auth`, `test_user_roles_matrix`, `test_role_capabilities`, `test_assignable_roles_endpoint`. No hay linter configurado.
- Con Docker: `docker-compose.yml` levanta backend (8000) + frontend + cloudflared.

## Tests — qué comando correr

La suite son **1302 tests** y en serie tarda **~14 min** contra Postgres. Hay dos modos
rápidos, **ninguno activo por defecto**: `python -m pytest` a secas sigue siendo la suite
completa en serie.

### ⚠️ La suite corre SIEMPRE contra Postgres — SQLite está descartado

**No hay que exportar nada:** `tymro/settings_test.py` ya apunta a `tymro-pg-verify`
(`postgresql://tymro:tymro@127.0.0.1:55432/tymro`) por defecto. **El fallback a SQLite está
deliberadamente cerrado para los tests.**

Por qué: producción es Postgres y hay tests de esta suite cuyo resultado **depende del
motor**. El caso canónico es el tope de `student_plan` en `ManualPaymentCreateSerializer`,
que existe porque un `filter(pk=...)` fuera del rango de bigint **revienta con 500 en
Postgres y en SQLite pasa sin chistar**. Una suite verde en SQLite NO es evidencia de que la
rama esté sana. Además `--testmon` guarda un único mapa test→archivos por máquina, así que
alternar de motor lo ensucia y lo hace subseleccionar en silencio.

`settings_test.py` tiene dos guardas, y **cualquiera de las dos aborta la suite antes de
correr** con un mensaje que empieza en `Postgres no disponible:`:

1. **el motor resuelto no es Postgres** (cayó al fallback de SQLite, o alguien exportó un
   `DATABASE_URL` que no es Postgres);
2. **Postgres está configurado pero no responde** en su host/puerto (el modo de fallo real:
   el contenedor parado). Es un socket con timeout de 3 s, así que en vez de un
   `OperationalError` críptico en medio de la creación de las bases de test —multiplicado por
   worker con `-n auto`— sale una sola línea legible.

Si aparece ese error, levantar el contenedor: `docker start tymro-pg-verify`. Para apuntar a
otro Postgres, exportar `DATABASE_URL` (se respeta; lo único que no se acepta es que no haya
ninguno). El fallback a SQLite de `settings.py` sigue vivo para `runserver` en dev: el que
está cerrado es el de los **tests**.

```bash
cd backend
python -m pytest --testmon    # CICLO NORMAL: solo los tests que toca tu cambio
python -m pytest -n auto      # GATE PRE-DEPLOY: suite completa, 1 proceso por CPU
```

| | `--testmon` | `-n auto` | `python -m pytest` |
|---|---|---|---|
| Qué corre | solo los afectados | los 1302 | los 1302 |
| Tiempo medido | 0,03 s a ~2,5 min | **~3–5 min** | ~14 min |
| Cuándo | mientras iterás sobre un cambio | **antes de mergear/pushear a `deploy/railway-prod`** | debug puntual, CI serial |

### `--testmon` (ciclo de iteración)

- La **primera** corrida es la suite completa instrumentada con cobertura (**~22 min**) y
  construye `.testmondata`. Se paga **una sola vez por máquina**. Después, sin cambios,
  la corrida es de **0 tests en 0,03 s**.
- ⚠️ **Cuánto ahorra depende de QUÉ archivo tocás**, y en este repo la diferencia es brutal.
  Tests que dependen de cada archivo, según el mapa real de testmon:

  | Archivo tocado | Tests que se re-corren |
  |---|---|
  | `core/services/teacher_payments.py` | 47 (3,6 %) |
  | `core/services/plans.py` | 265 (20 %) |
  | `core/serializers.py` | 693 (53 %) |
  | `core/views.py` | 795 (61 %) |
  | `core/models.py` | 1190 (91 %) |
  | `conftest.py` | 1302 (100 %) |

  **testmon rinde en archivos hoja (`core/services/*`), no en `models.py`/`views.py`.**
  Un cambio típico que toca models + views + serializers re-corre >1200 tests: ahí el modo
  rápido no es testmon, es `-n auto`.
- **`--testmon` NO es un gate de entrega.** Selecciona desde el mapa de la corrida anterior;
  si el mapa está frío, desactualizado o venís de otra rama, subselecciona en silencio.
  **Antes de pushear a producción corré `-n auto`, nunca testmon.**
- `.testmondata` está en `.gitignore` (local, se reconstruye solo). Si testmon se porta raro
  —cambio de rama, cambio de motor de BD, seleccionó de menos— borralo y dejá que se rearme.
- **No combinar `--testmon` con `-n auto`:** testmon no soporta xdist (no falla ruidosamente,
  así que el riesgo es una corrida que parece verde sin haber seleccionado bien).

### `-n auto` (suite completa en paralelo)

- Un worker por CPU lógica (12 en la máquina de referencia). `pytest-django` crea **una BD de
  test por worker** (`test_tymro_gw0..gw11`) automáticamente contra `tymro-pg-verify`.
- Verificado: **1302 passed, mismo resultado que en serie, cero fallos y cero flaky** en
  `--dist load` (default) y en `--dist loadscope`. No hace falta `loadscope`.
- Si el Postgres local sufre con 12 BDs simultáneas, bajar a `-n 6`.
- El tiempo oscila (~3–5 min) según carga de la máquina; el serial no baja de ~14 min.

## Arquitectura

- `tymro/` — config del proyecto (`settings.py`, `urls.py`).
- `accounts/` — `CustomUser` (`AUTH_USER_MODEL = 'accounts.CustomUser'`).
- `core/` — dominio del negocio:
  - `models.py` — todos los modelos.
  - `views.py` — ViewSets y APIViews (~2.300 líneas).
  - `serializers.py`, `urls.py` (router DRF), `permissions.py`.
  - `services/` — **lógica de negocio**: `reservations.py`, `recurrence.py`, `teacher_payments.py`, `class_dashboard.py`.

## Reglas clave

1. **Multi-tenant: SIEMPRE filtrar por `organization_id`.** El aislamiento es **manual y sin red central**: no hay manager base ni middleware que resuelva la organización. Cada `get_queryset` filtra por `request.user.organization_id` (patrón `superadmin → all` / `org-user → filter(organization_id=...)` / `else → .none()`; los recursos anidados filtran por la FK padre, p.ej. `class_instance__organization_id`) y cada `perform_create/update/destroy` **fuerza** la organización del actor y rechaza cualquier `organization` del payload. El riesgo #1 es un endpoint que olvide el filtro y filtre datos cross-tenant en silencio. Cualquier endpoint nuevo debe respetar esto.
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
- **El backend es la única frontera de seguridad real.** El control de acceso del frontend React (`ProtectedRoute`, `utils/roles.js`) es **cosmético** (oculta acciones según rol): toda restricción debe tener su check equivalente aquí (permission class o check `_is_*` que devuelva 403/404).
- Locale: `es-cl`, `America/Santiago`, `USE_TZ=True`.

## Variables de entorno (nombres)

`SECRET_KEY`, `DJANGO_DEBUG`/`DEBUG`, `ALLOWED_HOSTS`, `DATABASE_URL` (o `POSTGRES_DB/USER/PASSWORD/HOST/PORT`), `SQLITE_DB_NAME`, `CORS_ALLOW_ALL_ORIGINS`, `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS`, `BACKEND_PORT`, `STUDENT_CANCEL_DEADLINE_HOURS`, `STUDENT_RECURRING_CHANGE_DEADLINE_HOURS`.

- DB: SQLite en dev (`runserver`), PostgreSQL en producción. **Los tests son SIEMPRE
  PostgreSQL** — ver § Tests; `settings_test.py` fuerza `tymro-pg-verify` y falla si no está.

## ⚠️ Advertencias (estado actual del repo)

- **Duplicidad de modelos de plan:** coexisten `Plan` y `MembershipPlan`. La API usa `Plan`; `MembershipPlan` parece heredado. Confirmar antes de tocar planes.
- **Sin linter** configurado. (Sí hay tests: suite `pytest` en `core/tests/` — ver sección Comandos.)
- **Sin paginación DRF** explícita (no hay `DEFAULT_PAGINATION_CLASS`); el frontend tolera listas y respuestas paginadas.
- **`AUTH_PASSWORD_VALIDATORS = []`** — validadores deshabilitados (a reforzar en producción).
- `STUDENT_CANCEL_DEADLINE_HOURS` y `STUDENT_RECURRING_CHANGE_DEADLINE_HOURS` no están en `.env.example` y usan default `0`.