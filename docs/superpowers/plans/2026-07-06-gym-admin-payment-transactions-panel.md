# Panel de transacciones de pagos para gym_admin — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dar al `gym_admin` una pantalla de solo lectura donde vea las `PaymentTransaction` de su propia organización (fecha, alumno, plan/concepto, monto, estado, si activó StudentPlan), paginada en el servidor y ordenada por fecha descendente.

**Architecture:** Un `ListAPIView` nuevo (`GET /api/payments/transactions/`) en `core/views_payments.py` con paginación DRF local, un serializer de solo lectura, y aislamiento multitenant manual (solo gym_admin ve su org; todo lo demás → 403). En el frontend, una página React nueva con tabla + `TablePagination` cableado a la paginación del servidor, más su entrada en el router y el Sidebar.

**Tech Stack:** Django 5.0.6 + DRF 3.15.1 (backend, pytest); React 18 + Vite + Tailwind (frontend, vitest + @testing-library/react).

## Global Constraints

- **Multitenant:** SIEMPRE filtrar por `organization_id`. Acceso a este endpoint: **solo `gym_admin`** de su propia organización; superadmin/manager/monitor/teacher/student → **403**. No hay parámetro `?organization_id`.
- **Solo lectura:** el endpoint solo acepta `GET`. Ninguna mutación.
- **Paginación:** DRF `PageNumberPagination` aplicada SOLO a esta vista (no tocar `DEFAULT_PAGINATION_CLASS`). `page_size=25`, `page_size_query_param='page_size'`, `max_page_size=100`.
- **Orden:** `-created_at`, con `-id` como desempate estable.
- **Toda llamada API del frontend pasa por `frontend/src/api/client.js`** (módulo `paymentsApi`). No crear instancias de axios sueltas.
- **Backend tests:** pytest, `python -m pytest` desde `backend/`. Fixtures en `backend/conftest.py`: `api_client`, `make_organization(name=None)`, `make_user(username, organization=None, role='gym_admin', password='Passw0rd2026', **extra)`.
- **Frontend tests:** `npm run test` (vitest) desde `frontend/`.
- Locale `es-CL`; moneda por defecto `CLP`.

---

### Task 1: Serializer de solo lectura `PaymentTransactionAdminSerializer`

**Files:**
- Modify: `backend/core/serializers.py` (añadir clase tras `PaymentTransactionStatusSerializer`, ~línea 1628)
- Test: `backend/core/tests/test_payment_transaction_admin_serializer.py` (crear)

**Interfaces:**
- Consumes: modelo `PaymentTransaction` (`core/models.py:905`), `CustomUser` (`first_name`, `last_name`, `username`, `email`, `phone`), `Plan.name`, `StudentPlan`.
- Produces: `PaymentTransactionAdminSerializer` con estos campos de salida:
  `id, created_at, processed_at, status, status_detail, amount, plan_amount, enrollment_fee_amount, currency, student_name, student_email, student_phone, plan_name, concept, activated_student_plan, student_plan`.

- [ ] **Step 1: Write the failing test**

Crear `backend/core/tests/test_payment_transaction_admin_serializer.py`:

```python
from datetime import date

import pytest

from core.models import PaymentTransaction, Plan, StudentPlan
from core.serializers import PaymentTransactionAdminSerializer


@pytest.fixture
def org(make_organization):
    return make_organization('Gym A')


@pytest.fixture
def student(make_user, org):
    return make_user('ana', organization=org, role='student',
                     first_name='Ana', last_name='Pérez',
                     email='ana@gym.cl', phone='+56911111111')


def test_serializer_expone_datos_del_alumno_y_plan(org, student):
    plan = Plan.objects.create(organization=org, name='Mensual', plan_type='monthly',
                               total_classes=8, unlimited_classes=False, duration_days=30,
                               price=20000.0)
    tx = PaymentTransaction.objects.create(
        organization=org, user=student, plan=plan, amount=20000, plan_amount=20000,
        currency='CLP', status='approved')

    data = PaymentTransactionAdminSerializer(tx).data

    assert data['student_name'] == 'Ana Pérez'
    assert data['student_email'] == 'ana@gym.cl'
    assert data['student_phone'] == '+56911111111'
    assert data['plan_name'] == 'Mensual'
    assert data['concept'] == 'Plan: Mensual'
    assert data['status'] == 'approved'
    assert data['activated_student_plan'] is False


def test_serializer_activated_student_plan_true_cuando_activo_plan(org, student):
    plan = Plan.objects.create(organization=org, name='Mensual', plan_type='monthly',
                               total_classes=8, unlimited_classes=False, duration_days=30,
                               price=20000.0)
    sp = StudentPlan.objects.create(user=student, plan=plan, start_date=date(2026, 7, 1),
                                    end_date=date(2026, 7, 31), total_classes=8)
    tx = PaymentTransaction.objects.create(
        organization=org, user=student, plan=plan, amount=20000, currency='CLP',
        status='approved', student_plan=sp)

    data = PaymentTransactionAdminSerializer(tx).data

    assert data['activated_student_plan'] is True
    assert data['student_plan'] == sp.id


def test_serializer_nombre_cae_a_username_y_concepto_matricula(org, student):
    student.first_name = ''
    student.last_name = ''
    student.save(update_fields=['first_name', 'last_name'])
    plan = Plan.objects.create(organization=org, name='Mensual', plan_type='monthly',
                               total_classes=8, unlimited_classes=False, duration_days=30,
                               price=20000.0)
    sp = StudentPlan.objects.create(user=student, plan=plan, start_date=date(2026, 7, 1),
                                    end_date=date(2026, 7, 31), total_classes=8)
    tx = PaymentTransaction.objects.create(
        organization=org, user=student, amount=5000, enrollment_fee_amount=5000,
        currency='CLP', status='pending', target_student_plan=sp)

    data = PaymentTransactionAdminSerializer(tx).data

    assert data['student_name'] == student.username
    assert data['plan_name'] is None
    assert data['concept'] == 'Matrícula'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest core/tests/test_payment_transaction_admin_serializer.py -v`
Expected: FAIL con `ImportError: cannot import name 'PaymentTransactionAdminSerializer'`.

- [ ] **Step 3: Write minimal implementation**

En `backend/core/serializers.py`, tras la clase `PaymentTransactionStatusSerializer` (~línea 1628), añadir:

```python
class PaymentTransactionAdminSerializer(serializers.ModelSerializer):
    """Vista de solo lectura de una PaymentTransaction para el panel del gym_admin.
    Incluye datos del alumno y si la transacción activó un StudentPlan."""
    student_name = serializers.SerializerMethodField()
    student_email = serializers.EmailField(source='user.email', read_only=True)
    student_phone = serializers.CharField(source='user.phone', read_only=True)
    plan_name = serializers.CharField(source='plan.name', read_only=True)
    concept = serializers.SerializerMethodField()
    activated_student_plan = serializers.SerializerMethodField()

    class Meta:
        model = PaymentTransaction
        fields = [
            'id', 'created_at', 'processed_at',
            'status', 'status_detail',
            'amount', 'plan_amount', 'enrollment_fee_amount', 'currency',
            'student_name', 'student_email', 'student_phone',
            'plan_name', 'concept',
            'activated_student_plan', 'student_plan',
        ]
        read_only_fields = fields

    def get_student_name(self, obj):
        full_name = f'{obj.user.first_name} {obj.user.last_name}'.strip()
        return full_name or obj.user.username

    def get_concept(self, obj):
        if obj.plan_id:
            return f'Plan: {obj.plan.name}'
        if obj.target_student_plan_id:
            return 'Matrícula'
        return '—'

    def get_activated_student_plan(self, obj):
        return bool(obj.student_plan_id)
```

Nota: `plan_name` con `source='plan.name'` devuelve `None` cuando `plan` es NULL (DRF corta la cadena de atributos en el primer `None`); no necesita `allow_null`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest core/tests/test_payment_transaction_admin_serializer.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/core/serializers.py backend/core/tests/test_payment_transaction_admin_serializer.py
git commit -m "feat(payments): serializer admin de PaymentTransaction (read-only)"
```

---

### Task 2: Endpoint `GET /api/payments/transactions/` (view + paginación + ruta)

**Files:**
- Modify: `backend/core/views_payments.py` (imports + 2 clases nuevas)
- Modify: `backend/core/urls.py` (import + 1 ruta)
- Test: `backend/core/tests/test_payments_transactions_list_api.py` (crear)

**Interfaces:**
- Consumes: `PaymentTransactionAdminSerializer` (Task 1); helper `_is_gym_admin` (ya importado en `views_payments.py` desde `.views`); modelo `PaymentTransaction`.
- Produces: `PaymentTransactionListView` (as_view en la URL name `payments-transactions-list`); `PaymentTransactionPagination`. Respuesta JSON `{count, next, previous, results: [...]}`.

- [ ] **Step 1: Write the failing test**

Crear `backend/core/tests/test_payments_transactions_list_api.py`:

```python
from datetime import date, datetime, timezone as dt_timezone

import pytest

from core.models import PaymentTransaction, Plan, StudentPlan

URL = '/api/payments/transactions/'


@pytest.fixture
def org_a(make_organization):
    return make_organization('Gym A')


@pytest.fixture
def org_b(make_organization):
    return make_organization('Gym B')


def _plan(org, name='Mensual'):
    return Plan.objects.create(organization=org, name=name, plan_type='monthly',
                               total_classes=8, unlimited_classes=False, duration_days=30,
                               price=20000.0)


def _tx(org, user, **kwargs):
    defaults = dict(organization=org, user=user, amount=1000, currency='CLP', status='pending')
    defaults.update(kwargs)
    return PaymentTransaction.objects.create(**defaults)


def _set_created(tx, dt):
    # created_at es auto_now_add: hay que forzarlo con update() para bypassear.
    PaymentTransaction.objects.filter(id=tx.id).update(created_at=dt)


def test_requiere_autenticacion(api_client):
    resp = api_client.get(URL)
    assert resp.status_code == 401


@pytest.mark.parametrize('role', ['superadmin', 'manager', 'monitor', 'teacher', 'student'])
def test_roles_no_gym_admin_reciben_403(api_client, org_a, make_user, role):
    org = None if role == 'superadmin' else org_a
    user = make_user('u', organization=org, role=role)
    api_client.force_authenticate(user=user)
    resp = api_client.get(URL)
    assert resp.status_code == 403


def test_gym_admin_ve_solo_su_organizacion(api_client, org_a, org_b, make_user):
    stu_a = make_user('sa', organization=org_a, role='student')
    stu_b = make_user('sb', organization=org_b, role='student')
    _tx(org_a, stu_a)
    _tx(org_a, stu_a)
    _tx(org_b, stu_b)   # de otra org: no debe verse
    admin_a = make_user('adminA', organization=org_a, role='gym_admin')
    api_client.force_authenticate(user=admin_a)

    resp = api_client.get(URL)

    assert resp.status_code == 200
    assert resp.data['count'] == 2
    orgs = {row['id'] for row in resp.data['results']}
    assert len(orgs) == 2


def test_admin_de_b_no_ve_tx_de_a(api_client, org_a, org_b, make_user):
    stu_a = make_user('sa2', organization=org_a, role='student')
    _tx(org_a, stu_a)
    admin_b = make_user('adminB', organization=org_b, role='gym_admin')
    api_client.force_authenticate(user=admin_b)

    resp = api_client.get(URL)

    assert resp.status_code == 200
    assert resp.data['count'] == 0


def test_orden_por_fecha_desc(api_client, org_a, make_user):
    stu = make_user('s', organization=org_a, role='student')
    old = _tx(org_a, stu, status='approved')
    new = _tx(org_a, stu, status='rejected')
    _set_created(old, datetime(2026, 1, 1, tzinfo=dt_timezone.utc))
    _set_created(new, datetime(2026, 6, 1, tzinfo=dt_timezone.utc))
    admin = make_user('adm', organization=org_a, role='gym_admin')
    api_client.force_authenticate(user=admin)

    resp = api_client.get(URL)

    assert [r['id'] for r in resp.data['results']] == [str(new.id), str(old.id)]


def test_paginacion(api_client, org_a, make_user):
    stu = make_user('s3', organization=org_a, role='student')
    for _ in range(30):
        _tx(org_a, stu)
    admin = make_user('adm3', organization=org_a, role='gym_admin')
    api_client.force_authenticate(user=admin)

    page1 = api_client.get(URL, {'page_size': 10})
    assert page1.data['count'] == 30
    assert len(page1.data['results']) == 10
    assert page1.data['next'] is not None

    page3 = api_client.get(URL, {'page_size': 10, 'page': 3})
    assert len(page3.data['results']) == 10
    assert page3.data['next'] is None


def test_filtro_por_status(api_client, org_a, make_user):
    stu = make_user('s4', organization=org_a, role='student')
    _tx(org_a, stu, status='approved')
    _tx(org_a, stu, status='rejected')
    admin = make_user('adm4', organization=org_a, role='gym_admin')
    api_client.force_authenticate(user=admin)

    resp = api_client.get(URL, {'status': 'approved'})

    assert resp.data['count'] == 1
    assert resp.data['results'][0]['status'] == 'approved'


def test_status_invalido_devuelve_400(api_client, org_a, make_user):
    admin = make_user('adm5', organization=org_a, role='gym_admin')
    api_client.force_authenticate(user=admin)
    resp = api_client.get(URL, {'status': 'noexiste'})
    assert resp.status_code == 400


def test_filtro_por_rango_de_fechas(api_client, org_a, make_user):
    stu = make_user('s6', organization=org_a, role='student')
    jan = _tx(org_a, stu)
    jun = _tx(org_a, stu)
    _set_created(jan, datetime(2026, 1, 15, tzinfo=dt_timezone.utc))
    _set_created(jun, datetime(2026, 6, 15, tzinfo=dt_timezone.utc))
    admin = make_user('adm6', organization=org_a, role='gym_admin')
    api_client.force_authenticate(user=admin)

    resp = api_client.get(URL, {'date_from': '2026-06-01', 'date_to': '2026-06-30'})

    assert resp.data['count'] == 1
    assert resp.data['results'][0]['id'] == str(jun.id)


def test_fecha_invalida_devuelve_400(api_client, org_a, make_user):
    admin = make_user('adm7', organization=org_a, role='gym_admin')
    api_client.force_authenticate(user=admin)
    resp = api_client.get(URL, {'date_from': '01-06-2026'})
    assert resp.status_code == 400
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest core/tests/test_payments_transactions_list_api.py -v`
Expected: FAIL — la URL no existe todavía (404 en vez de los códigos esperados) / `ImportError` de `PaymentTransactionListView`.

- [ ] **Step 3: Write minimal implementation**

En `backend/core/views_payments.py`, añadir a los imports del principio:

```python
from datetime import datetime

from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.generics import ListAPIView
from rest_framework.pagination import PageNumberPagination
```

Añadir `PaymentTransactionAdminSerializer` al import existente de serializers:

```python
from .serializers import (PaymentAccountSerializer, PaymentCheckoutRequestSerializer,
                          PaymentTransactionAdminSerializer,
                          PaymentTransactionStatusSerializer)
```

Al final del archivo, añadir:

```python
class PaymentTransactionPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = 'page_size'
    max_page_size = 100


class PaymentTransactionListView(ListAPIView):
    """Listado de solo lectura de las PaymentTransaction de la organización del
    gym_admin. Acceso EXCLUSIVO de gym_admin sobre su propia org: superadmin y el
    resto de roles reciben 403 (el superadmin no debe ver los pagos de todos los
    gimnasios). Paginado, orden por fecha desc, con filtros por estado y fecha."""
    permission_classes = [IsAuthenticated]
    serializer_class = PaymentTransactionAdminSerializer
    pagination_class = PaymentTransactionPagination

    def get_queryset(self):
        user = self.request.user
        if not (_is_gym_admin(user) and user.organization_id):
            raise PermissionDenied('Solo el administrador del gimnasio puede ver las transacciones.')

        qs = (PaymentTransaction.objects
              .filter(organization_id=user.organization_id)
              .select_related('user', 'plan', 'student_plan')
              .order_by('-created_at', '-id'))

        status_param = self.request.query_params.get('status')
        if status_param:
            valid = {choice[0] for choice in PaymentTransaction.STATUS_CHOICES}
            if status_param not in valid:
                raise ValidationError({'status': 'Estado inválido.'})
            qs = qs.filter(status=status_param)

        def _parse_date(value, field):
            try:
                return datetime.strptime(value, '%Y-%m-%d').date()
            except ValueError:
                raise ValidationError({field: 'Formato de fecha inválido (usa YYYY-MM-DD).'})

        date_from = self.request.query_params.get('date_from')
        if date_from:
            qs = qs.filter(created_at__date__gte=_parse_date(date_from, 'date_from'))
        date_to = self.request.query_params.get('date_to')
        if date_to:
            qs = qs.filter(created_at__date__lte=_parse_date(date_to, 'date_to'))
        return qs
```

En `backend/core/urls.py`, añadir `PaymentTransactionListView` al import desde `.views_payments`:

```python
from .views_payments import (
    PaymentAccountView,
    PaymentCheckoutView,
    PaymentConnectView,
    PaymentOAuthCallbackView,
    PaymentTransactionListView,
    PaymentTransactionStatusView,
    PaymentWebhookView,
)
```

Y añadir la ruta justo antes de la de `<uuid:pk>/status/`:

```python
    path('payments/transactions/', PaymentTransactionListView.as_view(),
         name='payments-transactions-list'),
    path('payments/transactions/<uuid:pk>/status/', PaymentTransactionStatusView.as_view(),
         name='payments-transaction-status'),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest core/tests/test_payments_transactions_list_api.py -v`
Expected: PASS (todos).

- [ ] **Step 5: Run full backend suite (no regressions)**

Run: `cd backend && python -m pytest -q`
Expected: toda la suite verde.

- [ ] **Step 6: Commit**

```bash
git add backend/core/views_payments.py backend/core/urls.py backend/core/tests/test_payments_transactions_list_api.py
git commit -m "feat(payments): endpoint GET /payments/transactions/ para gym_admin (paginado, filtros, aislado por org)"
```

---

### Task 3: Frontend — método API `paymentsApi.listTransactions`

**Files:**
- Modify: `frontend/src/api/client.js` (dentro del objeto `paymentsApi`, ~línea 617)
- Test: `frontend/src/api/paymentsApi.transactions.test.js` (crear)

**Interfaces:**
- Consumes: instancia axios `api` (ya definida en `client.js`).
- Produces: `paymentsApi.listTransactions({ page, pageSize, status, dateFrom, dateTo })` → devuelve `data` del backend `{ count, next, previous, results }`. Envía query params `page`, `page_size`, y opcionalmente `status`, `date_from`, `date_to`.

- [ ] **Step 1: Write the failing test**

Crear `frontend/src/api/paymentsApi.transactions.test.js`:

```javascript
import { describe, it, expect, vi, beforeEach } from 'vitest'

const getMock = vi.fn()
// Mock completo de axios: client.js hace axios.create() (x2) y api.interceptors.*.use()
// al cargar el módulo; defaults está para blindar setAuthToken si algo lo tocara.
vi.mock('axios', () => ({
  default: {
    create: () => ({
      get: getMock,
      post: vi.fn(),
      defaults: { headers: { common: {} } },
      interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
    }),
  },
}))

import { paymentsApi } from './client'

beforeEach(() => {
  vi.clearAllMocks()
})

describe('paymentsApi.listTransactions', () => {
  it('envía page/page_size y filtros, y devuelve data', async () => {
    getMock.mockResolvedValue({ data: { count: 0, results: [] } })

    const result = await paymentsApi.listTransactions({
      page: 2, pageSize: 10, status: 'approved', dateFrom: '2026-06-01', dateTo: '2026-06-30',
    })

    expect(getMock).toHaveBeenCalledWith('/payments/transactions/', {
      params: { page: 2, page_size: 10, status: 'approved', date_from: '2026-06-01', date_to: '2026-06-30' },
    })
    expect(result).toEqual({ count: 0, results: [] })
  })

  it('omite filtros vacíos', async () => {
    getMock.mockResolvedValue({ data: { count: 0, results: [] } })

    await paymentsApi.listTransactions({ page: 1, pageSize: 25 })

    expect(getMock).toHaveBeenCalledWith('/payments/transactions/', {
      params: { page: 1, page_size: 25 },
    })
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- src/api/paymentsApi.transactions.test.js`
Expected: FAIL — `paymentsApi.listTransactions is not a function`.

- [ ] **Step 3: Write minimal implementation**

En `frontend/src/api/client.js`, dentro del objeto `paymentsApi` (tras `transactionStatus`, ~línea 645), añadir:

```javascript
  // gym_admin: listado paginado (server-side) de transacciones de su organización.
  // Params: page, pageSize, status, dateFrom, dateTo. → { count, next, previous, results }
  listTransactions: async ({ page = 1, pageSize = 25, status, dateFrom, dateTo } = {}) => {
    const params = { page, page_size: pageSize }
    if (status) params.status = status
    if (dateFrom) params.date_from = dateFrom
    if (dateTo) params.date_to = dateTo
    const { data } = await api.get('/payments/transactions/', { params })
    return data
  },
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- src/api/paymentsApi.transactions.test.js`
Expected: PASS (2 tests).

> Fallback: si el `client.js` real fallara al cargarse bajo vitest por un side-effect de módulo no previsto, plegar este método en la Task 4 (dejarlo implementado sin este test unitario) y confiar en que la Task 4 mockea `paymentsApi`. El mapeo de params (`pageSize→page_size`, `dateFrom→date_from`) se cubriría entonces con un test que solo importe el objeto sin ejercitar el resto del módulo.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/client.js frontend/src/api/paymentsApi.transactions.test.js
git commit -m "feat(payments): paymentsApi.listTransactions (listado paginado)"
```

---

### Task 4: Frontend — página, ruta y Sidebar

**Files:**
- Create: `frontend/src/pages/GymAdminPaymentsTransactionsPage.jsx`
- Create: `frontend/src/pages/GymAdminPaymentsTransactionsPage.test.jsx`
- Modify: `frontend/src/App.jsx` (import + ruta)
- Modify: `frontend/src/components/layout/Sidebar.jsx` (item en grupo "Configuraciones")

**Interfaces:**
- Consumes: `paymentsApi.listTransactions` (Task 3); `DashboardHeader`; `TablePagination` (`frontend/src/components/ui/TablePagination.jsx`, props: `page, totalPages, pageSize, pageSizeOptions, startItem, endItem, totalItems, onPrevious, onNext, onPageSizeChange`); `firstApiError` de `../utils/format`.
- Produces: componente `GymAdminPaymentsTransactionsPage` (default export); ruta `/gym-admin/pagos/transacciones` (allowedRoles `['gym_admin']`); item de Sidebar.

- [ ] **Step 1: Write the failing test**

Crear `frontend/src/pages/GymAdminPaymentsTransactionsPage.test.jsx`:

```javascript
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../api/client', () => ({
  paymentsApi: { listTransactions: vi.fn() },
}))

import { paymentsApi } from '../api/client'
import GymAdminPaymentsTransactionsPage from './GymAdminPaymentsTransactionsPage'

const renderPage = () =>
  render(
    <MemoryRouter initialEntries={['/gym-admin/pagos/transacciones']}>
      <GymAdminPaymentsTransactionsPage />
    </MemoryRouter>,
  )

const row = (over = {}) => ({
  id: 'tx-1', created_at: '2026-06-15T14:30:00Z', processed_at: null,
  status: 'approved', status_detail: null,
  amount: '20000.00', plan_amount: '20000.00', enrollment_fee_amount: '0.00', currency: 'CLP',
  student_name: 'Ana Pérez', student_email: 'ana@gym.cl', student_phone: '+56911111111',
  plan_name: 'Mensual', concept: 'Plan: Mensual',
  activated_student_plan: true, student_plan: 5,
  ...over,
})

beforeEach(() => {
  vi.clearAllMocks()
})

describe('GymAdminPaymentsTransactionsPage', () => {
  it('renderiza filas con datos del alumno y badge de estado', async () => {
    paymentsApi.listTransactions.mockResolvedValue({ count: 1, next: null, previous: null, results: [row()] })
    renderPage()

    expect(await screen.findByText('Ana Pérez')).toBeInTheDocument()
    expect(screen.getByText('ana@gym.cl')).toBeInTheDocument()
    expect(screen.getByText('Plan: Mensual')).toBeInTheDocument()
    expect(screen.getByText(/approved/i)).toBeInTheDocument()
  })

  it('muestra estado vacío cuando no hay transacciones', async () => {
    paymentsApi.listTransactions.mockResolvedValue({ count: 0, next: null, previous: null, results: [] })
    renderPage()

    expect(await screen.findByText(/sin transacciones/i)).toBeInTheDocument()
  })

  it('el filtro de estado dispara un refetch con el status elegido', async () => {
    paymentsApi.listTransactions.mockResolvedValue({ count: 0, next: null, previous: null, results: [] })
    renderPage()

    await waitFor(() => expect(paymentsApi.listTransactions).toHaveBeenCalled())
    const select = screen.getByLabelText(/estado/i)
    await userEvent.selectOptions(select, 'approved')

    await waitFor(() =>
      expect(paymentsApi.listTransactions).toHaveBeenLastCalledWith(
        expect.objectContaining({ status: 'approved', page: 1 }),
      ),
    )
  })

  it('cambiar de página llama a la API con el page correcto', async () => {
    paymentsApi.listTransactions.mockResolvedValue({
      count: 30, next: 'x', previous: null, results: [row()],
    })
    renderPage()

    await waitFor(() => expect(paymentsApi.listTransactions).toHaveBeenCalled())
    const next = await screen.findByRole('button', { name: /siguiente/i })
    await userEvent.click(next)

    await waitFor(() =>
      expect(paymentsApi.listTransactions).toHaveBeenLastCalledWith(
        expect.objectContaining({ page: 2 }),
      ),
    )
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- src/pages/GymAdminPaymentsTransactionsPage.test.jsx`
Expected: FAIL — el módulo `./GymAdminPaymentsTransactionsPage` no existe.

- [ ] **Step 3: Write minimal implementation (la página)**

Crear `frontend/src/pages/GymAdminPaymentsTransactionsPage.jsx`:

```jsx
import { useEffect, useState } from 'react'
import DashboardHeader from '../components/DashboardHeader'
import TablePagination from '../components/ui/TablePagination'
import { paymentsApi } from '../api/client'
import { firstApiError } from '../utils/format'

const PAGE_SIZE = 25
const PAGE_SIZE_OPTIONS = [10, 25, 50, 100]

const STATUS_OPTIONS = [
  { value: '', label: 'Todos los estados' },
  { value: 'pending', label: 'Pendiente' },
  { value: 'in_process', label: 'En proceso' },
  { value: 'approved', label: 'Aprobado' },
  { value: 'rejected', label: 'Rechazado' },
  { value: 'cancelled', label: 'Cancelado' },
  { value: 'refunded', label: 'Reembolsado' },
]

const STATUS_STYLES = {
  approved: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200',
  rejected: 'border-brand-red/50 bg-brand-red/10 text-red-200',
  cancelled: 'border-brand-red/50 bg-brand-red/10 text-red-200',
  pending: 'border-amber-500/40 bg-amber-500/10 text-amber-200',
  in_process: 'border-amber-500/40 bg-amber-500/10 text-amber-200',
  refunded: 'border-brand-line bg-black/30 text-brand-muted',
}

function formatDateTime(value) {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString('es-CL', {
    day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

function formatMoney(amount, currency) {
  const n = Number(amount)
  if (Number.isNaN(n)) return '—'
  try {
    return n.toLocaleString('es-CL', { style: 'currency', currency: currency || 'CLP', maximumFractionDigits: 0 })
  } catch {
    return `${n} ${currency || ''}`.trim()
  }
}

function StatusBadge({ status }) {
  const style = STATUS_STYLES[status] || 'border-brand-line bg-black/30 text-brand-muted'
  return (
    <span className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-[11px] font-semibold ${style}`}>
      {status}
    </span>
  )
}

export default function GymAdminPaymentsTransactionsPage() {
  const [rows, setRows] = useState([])
  const [count, setCount] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(PAGE_SIZE)
  const [status, setStatus] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    const load = async () => {
      setLoading(true)
      setError('')
      try {
        const data = await paymentsApi.listTransactions({ page, pageSize, status, dateFrom, dateTo })
        if (!active) return
        setRows(Array.isArray(data?.results) ? data.results : [])
        setCount(Number(data?.count) || 0)
      } catch (apiError) {
        if (active) setError(firstApiError(apiError?.response?.data, 'No se pudieron cargar las transacciones.'))
      } finally {
        if (active) setLoading(false)
      }
    }
    load()
    return () => { active = false }
  }, [page, pageSize, status, dateFrom, dateTo])

  const totalPages = Math.max(1, Math.ceil(count / pageSize))
  const startItem = count === 0 ? 0 : (page - 1) * pageSize + 1
  const endItem = Math.min(page * pageSize, count)

  const onFilterChange = (setter) => (event) => {
    setPage(1)
    setter(event.target.value)
  }

  return (
    <div className="space-y-6">
      <DashboardHeader
        title="Transacciones"
        subtitle="Pagos de tus alumnos: fecha, alumno, concepto, monto y estado. Solo lectura."
        back={{ to: '/gym-admin/dashboard', label: 'Dashboard' }}
      />

      {error ? <p className="rounded-lg border border-brand-red/50 bg-brand-red/10 px-3 py-2 text-sm text-red-200">{error}</p> : null}

      <div className="card-surface p-4 sm:p-6">
        <div className="mb-4 flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1 text-xs text-brand-muted">
            Estado
            <select
              value={status}
              onChange={onFilterChange(setStatus)}
              className="rounded-lg border border-brand-line bg-black/30 px-2 py-1.5 text-sm text-brand-white focus:border-brand-blue focus:outline-none"
            >
              {STATUS_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs text-brand-muted">
            Desde
            <input type="date" value={dateFrom} onChange={onFilterChange(setDateFrom)}
              className="rounded-lg border border-brand-line bg-black/30 px-2 py-1.5 text-sm text-brand-white focus:border-brand-blue focus:outline-none" />
          </label>
          <label className="flex flex-col gap-1 text-xs text-brand-muted">
            Hasta
            <input type="date" value={dateTo} onChange={onFilterChange(setDateTo)}
              className="rounded-lg border border-brand-line bg-black/30 px-2 py-1.5 text-sm text-brand-white focus:border-brand-blue focus:outline-none" />
          </label>
        </div>

        {loading ? (
          <p className="py-8 text-center text-sm text-brand-muted">Cargando transacciones…</p>
        ) : rows.length === 0 ? (
          <p className="py-8 text-center text-sm text-brand-muted">Sin transacciones para los filtros actuales.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-left text-sm">
              <thead className="text-[11px] uppercase tracking-wide text-brand-dim">
                <tr className="border-b border-brand-line">
                  <th className="py-2 pr-3 font-semibold">Fecha</th>
                  <th className="py-2 pr-3 font-semibold">Alumno</th>
                  <th className="py-2 pr-3 font-semibold">Concepto</th>
                  <th className="py-2 pr-3 font-semibold text-right">Monto</th>
                  <th className="py-2 pr-3 font-semibold">Estado</th>
                  <th className="py-2 pr-3 font-semibold">Activó plan</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((tx) => (
                  <tr key={tx.id} className="border-b border-brand-line/50">
                    <td className="py-2 pr-3 text-brand-muted">{formatDateTime(tx.created_at)}</td>
                    <td className="py-2 pr-3">
                      <div className="font-medium text-brand-white">{tx.student_name}</div>
                      <div className="text-xs text-brand-muted">{tx.student_email || tx.student_phone || '—'}</div>
                    </td>
                    <td className="py-2 pr-3 text-brand-white">{tx.concept}</td>
                    <td className="py-2 pr-3 text-right font-medium text-brand-white">{formatMoney(tx.amount, tx.currency)}</td>
                    <td className="py-2 pr-3"><StatusBadge status={tx.status} /></td>
                    <td className="py-2 pr-3 text-brand-muted">{tx.activated_student_plan ? 'Sí' : 'No'}</td>
                  </tr>
                ))}
              </tbody>
            </table>

            <TablePagination
              page={page}
              totalPages={totalPages}
              pageSize={pageSize}
              pageSizeOptions={PAGE_SIZE_OPTIONS}
              startItem={startItem}
              endItem={endItem}
              totalItems={count}
              onPrevious={() => setPage((p) => Math.max(1, p - 1))}
              onNext={() => setPage((p) => Math.min(totalPages, p + 1))}
              onPageSizeChange={(size) => { setPage(1); setPageSize(size) }}
            />
          </div>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- src/pages/GymAdminPaymentsTransactionsPage.test.jsx`
Expected: PASS (4 tests).

- [ ] **Step 5: Wire route + Sidebar**

En `frontend/src/App.jsx`, añadir el import (junto a los otros `GymAdmin*`, ~línea 23):

```jsx
import GymAdminPaymentsTransactionsPage from './pages/GymAdminPaymentsTransactionsPage'
```

Y añadir la ruta dentro del bloque de rutas `/gym-admin/*` (p.ej. tras la ruta de `/gym-admin/import`, ~línea 305):

```jsx
      <Route
        path="/gym-admin/pagos/transacciones"
        element={
          <ProtectedRoute allowedRoles={['gym_admin']}>
            <ShellRoute>
              <GymAdminPaymentsTransactionsPage />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
```

En `frontend/src/components/layout/Sidebar.jsx`, en el grupo "Configuraciones" del array `gym_admin` (~línea 167-175), añadir el item al principio de `children`:

```jsx
      children: [
        { to: '/gym-admin/pagos/transacciones', label: 'Transacciones' },
        { to: '/ajustes/pagos', label: 'Pagos (MercadoPago)' },
        { to: '/gym-admin/settings/trial-followup', label: 'Emails de prueba' },
      ],
```

- [ ] **Step 6: Run full frontend suite (no regressions)**

Run: `cd frontend && npm run test`
Expected: toda la suite verde.

- [ ] **Step 7: Build sanity check**

Run: `cd frontend && npm run build`
Expected: build sin errores.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/pages/GymAdminPaymentsTransactionsPage.jsx frontend/src/pages/GymAdminPaymentsTransactionsPage.test.jsx frontend/src/App.jsx frontend/src/components/layout/Sidebar.jsx
git commit -m "feat(payments): página de transacciones para gym_admin (tabla paginada + filtros + ruta + sidebar)"
```

---

## Verificación final (tras todas las tareas)

- [ ] `cd backend && python -m pytest -q` → verde.
- [ ] `cd frontend && npm run test` → verde.
- [ ] Manual (opcional, con backend + frontend corriendo): loguearse como gym_admin, ir a **Configuraciones → Transacciones** (`/gym-admin/pagos/transacciones`), confirmar que solo aparecen las tx de su org, que la paginación y los filtros funcionan, y que un usuario de otra org / otro rol no accede.

## Notas de aislamiento a verificar en review

- El `get_queryset` filtra por `organization_id=user.organization_id` y lanza 403 para todo lo que no sea gym_admin (incluye superadmin) — cubierto por `test_roles_no_gym_admin_reciben_403` y los tests de aislamiento cross-tenant.
- Ninguna restricción vive solo en el frontend: el `ProtectedRoute` es cosmético; la frontera real es el 403 del backend.
