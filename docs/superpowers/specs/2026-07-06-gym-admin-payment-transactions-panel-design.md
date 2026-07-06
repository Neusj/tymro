# Panel de transacciones de pagos para gym_admin — Diseño

**Fecha:** 2026-07-06
**Estado:** aprobado (diseño)

## Objetivo

Dar al `gym_admin` una pantalla donde vea las `PaymentTransaction` **de su propia
organización**, sin tener que consultar la base de datos. Solo lectura, paginado,
ordenado por fecha descendente, aislado por organización.

## Contexto (auditoría del estado actual)

- **Modelo `PaymentTransaction`** (`core/models.py:905`) ya contiene todo lo necesario:
  `organization` (FK, clave multitenant), `user` (alumno pagador), `plan` (FK nullable),
  `amount`/`plan_amount`/`enrollment_fee_amount`/`currency`, `status`
  (`pending/in_process/approved/rejected/cancelled/refunded`), `status_detail`,
  `student_plan` (StudentPlan **activado** por la tx, `related_name='origin_transactions'`),
  `target_student_plan` (matrícula pendiente), `created_at`/`processed_at`
  (hereda de `TimestampedModel`). `Meta.ordering = ['-created_at']`. Índices en
  `(organization, status)` y `(user, status)`.
- **Serializers:** solo existe `PaymentTransactionStatusSerializer` (`id, status,
  status_detail, amount, currency`), pensado para el polling del alumno. Insuficiente
  para el panel admin.
- **Endpoints de pago** (`views_payments.py`): connect / oauth callback / account /
  checkout / `transactions/<uuid>/status/` (solo el alumno dueño) / webhook.
  **No existe ningún listado de transacciones para el gym_admin** — ese es el hueco.
- **Multitenancy:** manual por vista. Patrón `superadmin→all / org-user→filter(organization_id=...)
  / else→.none()`. `PaymentTransaction` tiene `organization` FK directo.
- **Paginación:** no hay `DEFAULT_PAGINATION_CLASS`. El frontend pagina en cliente con
  `DataTable`; `normalizeListResponse` tolera lista o `{results}`.
- **Permisos:** existe `FinancialResourcePermission`, pero deja leer a monitor — **no** se
  usa aquí (ver Acceso).
- **Frontend de tests:** vitest + testing-library ya configurados (`npm run test`), pese a
  que `frontend/CLAUDE.md` diga lo contrario.

## Decisiones (confirmadas con el usuario)

1. **Ubicación UI:** página propia (no una pestaña dentro de la página de conexión MP).
2. **Paginación:** server-side con DRF `PageNumberPagination`.
3. **Acceso:** **solo `gym_admin`**, y solo ve su propia organización. Todos los demás
   roles —incluido **superadmin**— reciben **403**. Motivo explícito del usuario: el
   superadmin no debe ver las transacciones de todos los gimnasios. No hay parámetro
   `?organization_id`.
4. **Filtros:** por `status` y por rango de fechas, y cada fila incluye **más datos del
   alumno** (nombre, email, teléfono).

## Backend

### Endpoint

`GET /api/payments/transactions/` — `ListAPIView` (solo `GET`), en `core/views_payments.py`,
bajo el namespace `/payments/` existente. No colisiona con
`/payments/transactions/<uuid:pk>/status/` (ese lleva `pk`).

Ruta en `core/urls.py`:
```python
path('payments/transactions/', PaymentTransactionListView.as_view(),
     name='payments-transactions-list'),
```
El orden respecto a la ruta `<uuid:pk>/status/` es indiferente (son paths distintos),
pero se ubica junto a ella por claridad.

### Acceso y aislamiento (`get_queryset`)

```
if _is_gym_admin(user) and user.organization_id:
    queryset.filter(organization_id=user.organization_id)
else:
    raise PermissionDenied  # 403 para superadmin/manager/monitor/teacher/student
```

Un chequeo explícito de rol (estilo `views_payments`, no `FinancialResourcePermission`).
`select_related('user', 'plan', 'student_plan')` para evitar N+1.
Orden por `-created_at` (y `-id` como desempate estable para la paginación).

### Serializer — `PaymentTransactionAdminSerializer` (read-only)

| Campo | Origen |
|---|---|
| `id`, `created_at`, `processed_at` | modelo |
| `status`, `status_detail` | modelo |
| `amount`, `plan_amount`, `enrollment_fee_amount`, `currency` | modelo |
| `student_name` | `first_name last_name`, fallback `username` |
| `student_email` | `user.email` |
| `student_phone` | `user.phone` |
| `plan_name` | `plan.name` (o `null`) |
| `concept` | `"Plan: {nombre}"` si hay `plan`; `"Matrícula"` si hay `target_student_plan`; si no, `"—"` |
| `activated_student_plan` | `bool(student_plan_id)` → **si activó StudentPlan** |
| `student_plan` | id del StudentPlan activado (trazabilidad) |

`read_only_fields = fields`.

### Paginación

Clase local aplicada **solo a esta vista** (no se toca la config global):
```python
class PaymentTransactionPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = 'page_size'
    max_page_size = 100
```
Respuesta `{count, next, previous, results:[...]}`.

### Filtros (query params)

- `?status=<valor>` — validado contra `PaymentTransaction.STATUS_CHOICES`; inválido → **400**.
- `?date_from=YYYY-MM-DD`, `?date_to=YYYY-MM-DD` — sobre `created_at__date` (gte / lte).
  Formato inválido → **400** (mismo patrón que `TeacherPaymentRecordViewSet`).

### Tests backend (pytest) — foco en aislamiento multitenant

1. **Aislamiento:** tx en org A y org B; gym_admin de A ve **solo** las de A (`count`).
2. gym_admin de B no ve ninguna tx de A.
3. Orden `-created_at` descendente.
4. Paginación: `page_size`, `page=2`, `count` correcto.
5. Filtro por `status`; `status` inválido → 400.
6. Filtro por `date_from`/`date_to`.
7. Roles: manager, monitor, teacher, student, **superadmin** → **403**.
8. Sin autenticación → 401.
9. Serializer: incluye `student_name`/`student_email`/`student_phone`, `plan_name`,
   `concept`, y `activated_student_plan` correcto (tx que activó StudentPlan = `true`;
   tx pending = `false`).

## Frontend

### API client

`paymentsApi.listTransactions({ page, pageSize, status, dateFrom, dateTo })` en
`frontend/src/api/client.js`. Devuelve `{ results, count, next, previous }` (sin
`normalizeListResponse`: aquí sí necesitamos `count` para la paginación server-side).

### Página y ruta

- `frontend/src/pages/GymAdminPaymentsTransactionsPage.jsx`.
- Ruta `/gym-admin/pagos/transacciones` en `App.jsx`, envuelta en
  `<ProtectedRoute allowedRoles={['gym_admin']}>`.
- Item nuevo en el Sidebar del gym_admin ("Transacciones").

### Tabla y UX

- Como la paginación es server-side, **no** se usa `DataTable` (pagina en cliente y
  duplicaría). Se arma una tabla con los primitivos de estilo existentes + el componente
  `TablePagination` cableado a los params del servidor.
- Columnas: fecha, alumno (nombre + email/teléfono), concepto/plan, monto, estado (badge),
  activó plan (sí/no).
- Filtro de estado con `FilterDropdown`; dos inputs de fecha (`date_from`/`date_to`).
- Badges de estado: `approved`→verde, `rejected`/`cancelled`→rojo, `pending`/`in_process`→ámbar,
  `refunded`→neutro.
- Formato `es-CL` para fecha y monto. Estados de carga / vacío / error.

### Tests frontend (vitest + testing-library)

- Render de filas con datos del alumno y badge de estado.
- Cambio de página llama a la API con el `page` correcto.
- Filtro de estado dispara refetch con el `status` correcto.
- Estado vacío ("sin transacciones").

## Fuera de alcance (YAGNI)

Exportar CSV, ver `raw_provider_payload`, reembolsos o cualquier acción de escritura,
gráficos/dashboards. Estrictamente listado de solo lectura.
