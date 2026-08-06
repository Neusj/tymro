"""#12 (RED) — conceptos adicionales de cobro (`ChargeLineItem`) en el alta via `assign`.

Hoy un cobro es plano: `ManualPayment.amount` sin desglose, y no existe forma de registrar
un concepto extra ("pesas", "toalla") junto a la venta de una membresia. Este archivo fija
el contrato nuevo: `payment.line_items[]` OPCIONAL en `POST /api/plans/assign/` (solo via
`manual`), creado en la MISMA transaccion que la membresia y el pago, expuesto como
desglose (`line_items` + `line_items_total`) en el wire de la membresia, e invisible para
el monitor como el resto del dato financiero (7.3/8.x). La matricula (8.4) NO viaja por
aca. Todos los tests estan escritos para FALLAR contra el codigo actual, salvo los que
anclan guardas preexistentes (cross-org 403, monitor 403) que la feature no debe aflojar.
"""
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone

from core.models import ChargeLineItem, ManualPayment, Plan, StudentPlan

pytestmark = pytest.mark.django_db

ASSIGN_URL = '/api/plans/assign/'
TODAY = timezone.localdate()


def _plan(org, *, name='Plan 12', price=20000):
    return Plan.objects.create(
        organization=org, name=name, plan_type=Plan.PlanType.MONTHLY,
        total_classes=10, unlimited_classes=False, duration_days=30, price=price,
    )


def _counts():
    return (StudentPlan.objects.count(), ManualPayment.objects.count(),
            ChargeLineItem.objects.count())


@pytest.fixture
def world(make_organization, make_user):
    org = make_organization()
    admin = make_user('admin-12', organization=org, role='gym_admin')
    student = make_user('stu-12', organization=org, role='student')
    plan = _plan(org)
    return {'org': org, 'admin': admin, 'student': student, 'plan': plan}


def _manual_payload(world, line_items):
    return {
        'user': world['student'].id, 'plan': world['plan'].id, 'start_date': str(TODAY),
        'payment': {
            'method': 'manual', 'amount': '27000.00', 'manual_method': 'cash',
            'reference': 'efectivo', 'line_items': line_items,
        },
    }


# --------------------------------------------------------------------------------------
# 1. Alta con conceptos: misma venta, mismo INSERT logico, desglose en la respuesta
# --------------------------------------------------------------------------------------

def test_manual_assign_with_two_line_items_creates_them_in_the_same_sale(api_client, world):
    admin = world['admin']
    api_client.force_authenticate(admin)

    resp = api_client.post(ASSIGN_URL, _manual_payload(world, [
        {'concept': 'pesas', 'amount': '5000.00'},
        {'concept': 'toalla', 'amount': '2000.00'},
    ]), format='json')

    assert resp.status_code == 201, resp.data
    membership = StudentPlan.objects.get(id=resp.data['id'])
    items = list(ChargeLineItem.objects.filter(student_plan=membership).order_by('id'))
    assert [(i.concept, i.amount) for i in items] == [
        ('pesas', Decimal('5000.00')), ('toalla', Decimal('2000.00')),
    ]
    # La organizacion y el autor salen del ACTOR, nunca del payload.
    assert all(i.organization_id == admin.organization_id for i in items)
    assert all(i.created_by_id == admin.id for i in items)
    # Desglose en el wire de la membresia (misma respuesta del assign).
    assert [li['concept'] for li in resp.data['line_items']] == ['pesas', 'toalla']
    assert Decimal(str(resp.data['line_items_total'])) == Decimal('7000.00')
    # El ManualPayment sigue siendo UNO y con su monto de entrada intacto: el desglose no
    # reemplaza ni recalcula el cobro (mismo contrato 8.2: `amount` es dato, no derivacion).
    payment = ManualPayment.objects.get(student_plan=membership)
    assert payment.amount == Decimal('27000.00')


# --------------------------------------------------------------------------------------
# 2. Atomicidad: si el pago revienta, los conceptos no quedan huerfanos
# --------------------------------------------------------------------------------------

def test_payment_failure_rolls_back_membership_and_line_items(api_client, world, monkeypatch):
    """Los conceptos se insertan ANTES que el ManualPayment dentro del mismo atomic: si
    `record_manual_payment` falla, el rollback tiene que deshacer membresia Y conceptos.
    Se parchea `core.views.record_manual_payment` (import modulo-global, views.py:3624-3628)
    y se OBSERVA desde adentro que los conceptos ya estaban insertados al momento del pago:
    sin esa observacion, "nunca se crearon" y "se crearon y el rollback los deshizo" son
    indistinguibles y el test pasaria en vacio."""
    api_client.force_authenticate(world['admin'])
    before = _counts()
    seen = {}

    def _boom(**kwargs):
        seen['items_at_payment_time'] = ChargeLineItem.objects.count()
        raise DjangoValidationError('boom')

    monkeypatch.setattr('core.views.record_manual_payment', _boom)

    resp = api_client.post(ASSIGN_URL, _manual_payload(world, [
        {'concept': 'pesas', 'amount': '5000.00'},
    ]), format='json')

    assert resp.status_code == 400, resp.data
    assert seen['items_at_payment_time'] == 1
    assert _counts() == before


# --------------------------------------------------------------------------------------
# 3. Forma: monto > 0 y concepto obligatorio (400, sin side effects)
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize('amount', ['0', '-100.00'])
def test_line_item_with_non_positive_amount_is_rejected(api_client, world, amount):
    api_client.force_authenticate(world['admin'])
    before = _counts()

    resp = api_client.post(ASSIGN_URL, _manual_payload(world, [
        {'concept': 'pesas', 'amount': amount},
    ]), format='json')

    assert resp.status_code == 400, resp.data
    assert _counts() == before


def test_line_item_without_concept_is_rejected(api_client, world):
    api_client.force_authenticate(world['admin'])
    before = _counts()

    resp = api_client.post(ASSIGN_URL, _manual_payload(world, [
        {'concept': '', 'amount': '5000.00'},
    ]), format='json')

    assert resp.status_code == 400, resp.data
    assert _counts() == before


# --------------------------------------------------------------------------------------
# 4. Via free: beca total no admite conceptos cobrados (mismo criterio que amount/reference)
# --------------------------------------------------------------------------------------

def test_line_items_with_free_method_are_rejected(api_client, world):
    api_client.force_authenticate(world['admin'])
    before = _counts()

    resp = api_client.post(ASSIGN_URL, {
        'user': world['student'].id, 'plan': world['plan'].id, 'start_date': str(TODAY),
        'payment': {'method': 'free', 'line_items': [
            {'concept': 'pesas', 'amount': '5000.00'},
        ]},
    }, format='json')

    assert resp.status_code == 400, resp.data
    assert _counts() == before


# --------------------------------------------------------------------------------------
# 5. Orden 8.3: la guarda cross-org corta ANTES de leer/validar los line-items
# --------------------------------------------------------------------------------------

def test_cross_org_plan_with_line_items_answers_exactly_like_without_them(api_client,
                                                                            make_organization,
                                                                            make_user):
    """El payload con conceptos bien formados contra un plan ajeno tiene que devolver el
    MISMO 403 con el MISMO cuerpo que el payload sin conceptos (contrato preexistente de
    `assign`): si los line-items produjeran una respuesta distinta, el delta seria un
    oraculo nuevo sobre recursos de otro tenant."""
    org_a = make_organization()
    org_b = make_organization()
    admin_a = make_user('admin-12-a', organization=org_a, role='gym_admin')
    student_b = make_user('stu-12-b', organization=org_b, role='student')
    plan_b = _plan(org_b)
    api_client.force_authenticate(admin_a)
    before = _counts()

    base = {
        'user': student_b.id, 'plan': plan_b.id, 'start_date': str(TODAY),
        'payment': {'method': 'manual', 'amount': '27000.00', 'manual_method': 'cash'},
    }
    with_items = {
        **base,
        'payment': {**base['payment'], 'line_items': [
            {'concept': 'pesas', 'amount': '5000.00'},
        ]},
    }

    resp_without = api_client.post(ASSIGN_URL, base, format='json')
    resp_with = api_client.post(ASSIGN_URL, with_items, format='json')

    assert resp_without.status_code == 403, resp_without.data
    assert resp_with.status_code == 403, resp_with.data
    assert resp_with.data == resp_without.data
    assert _counts() == before


# --------------------------------------------------------------------------------------
# 6. Redaccion: el monitor no alcanza ninguna superficie con montos de conceptos
# --------------------------------------------------------------------------------------

def test_monitor_cannot_reach_any_surface_that_publishes_line_items(api_client, world,
                                                                     make_user):
    """`line_items` viaja en `StudentPlanSerializer` (assign/memberships/my-memberships) y
    en el listado de transacciones. El monitor ya tiene 403 en las dos superficies de
    lectura (check INLINE de `memberships`, views.py:3721-3722, y el scope exclusivo de
    gym_admin en `PaymentTransactionListView`): este test ancla que #12 no las afloja. El
    control positivo de que el campo SI existe para un lector legitimo es el test 1."""
    admin, student, plan = world['admin'], world['student'], world['plan']
    api_client.force_authenticate(admin)
    resp = api_client.post(ASSIGN_URL, _manual_payload(world, [
        {'concept': 'pesas', 'amount': '5000.00'},
    ]), format='json')
    assert resp.status_code == 201, resp.data

    monitor = make_user('monitor-12', organization=world['org'], role='monitor')
    api_client.force_authenticate(monitor)

    memberships_resp = api_client.get(f'/api/plans/{plan.id}/memberships/')
    assert memberships_resp.status_code == 403, memberships_resp.data

    transactions_resp = api_client.get('/api/payments/transactions/')
    assert transactions_resp.status_code == 403, transactions_resp.data


# --------------------------------------------------------------------------------------
# 7. Servicio: la puerta de escritura re-exige coherencia de organizacion
# --------------------------------------------------------------------------------------

def test_record_charge_line_items_rejects_cross_org_membership(world, make_organization,
                                                               make_user):
    """Espejo de `record_manual_payment`: la guarda vive en el SERVICIO ademas de la view,
    porque la puerta de escritura va a tener mas de un llamador y una guarda que solo vive
    en la view se pierde en el segundo camino (el patron exacto de los agujeros
    multitenant anteriores). Inalcanzable desde `assign` hoy: red para llamadores futuros."""
    from core.services.charge_line_items import (
        ChargeLineItemOrganizationMismatch,
        record_charge_line_items,
    )

    other_org = make_organization()
    other_admin = make_user('admin-12-other', organization=other_org, role='gym_admin')
    membership = StudentPlan.objects.create(
        user=world['student'], plan=world['plan'],
        organization_id=world['plan'].organization_id,
        start_date=TODAY, end_date=TODAY,
        total_classes=10, unlimited_classes=False,
        discount_percentage=0, final_price=20000, is_active=True,
    )

    with pytest.raises(ChargeLineItemOrganizationMismatch):
        record_charge_line_items(
            student_plan=membership,
            line_items=[{'concept': 'pesas', 'amount': Decimal('5000.00')}],
            created_by=other_admin,
            organization=other_org,
        )
    assert ChargeLineItem.objects.count() == 0


# --------------------------------------------------------------------------------------
# 8. Lectura defensiva: la transaccion no sigue una membresia de OTRA organizacion
# --------------------------------------------------------------------------------------

def test_transaction_serializer_hides_line_items_of_a_foreign_membership(world,
                                                                          make_organization):
    """Remediacion del security review de #12 (BAJO): `get_line_items` sigue la FK
    `tx.student_plan` confiando en la invariante `tx.organization == sp.organization`, que
    hoy se cumple pero NO esta garantizada por ninguna constraint (un plan movido de org
    por superadmin + checkout de matricula la rompe sin tocar codigo). Si la incoherencia
    existe, el desglose ajeno NO viaja: es el patron documentado "FK propia sin
    organizacion", cortado en la lectura."""
    from core.models import PaymentTransaction
    from core.serializers import PaymentTransactionAdminSerializer
    from core.services.charge_line_items import record_charge_line_items

    org_a, admin_a, student = world['org'], world['admin'], world['student']
    membership = StudentPlan.objects.create(
        user=student, plan=world['plan'], organization_id=org_a.id,
        start_date=TODAY, end_date=TODAY,
        total_classes=10, unlimited_classes=False,
        discount_percentage=0, final_price=20000, is_active=True,
    )
    record_charge_line_items(
        student_plan=membership,
        line_items=[{'concept': 'pesas', 'amount': Decimal('5000.00')}],
        created_by=admin_a, organization=org_a,
    )
    org_b = make_organization()
    incoherent_tx = PaymentTransaction.objects.create(
        organization=org_b, user=student, amount=5000, enrollment_fee_amount=5000,
        currency='CLP', status='approved', student_plan=membership,
    )
    coherent_tx = PaymentTransaction.objects.create(
        organization=org_a, user=student, amount=20000, plan_amount=20000,
        currency='CLP', status='approved', student_plan=membership,
    )

    assert PaymentTransactionAdminSerializer(incoherent_tx).data['line_items'] == []
    assert [li['concept'] for li in
            PaymentTransactionAdminSerializer(coherent_tx).data['line_items']] == ['pesas']
