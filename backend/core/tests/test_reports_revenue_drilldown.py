"""Drill-down del reporte de ingresos: capa 2 (listado de un medio) y capa 3 (detalle).

Es código de PLATA y además es la pantalla a la que se llega HACIENDO CLIC sobre un número:
cualquier diferencia entre lo que dice la capa 1 y lo que dice el listado se lee, con razón,
como que el reporte está roto. Lo que este archivo fija:

* **el cuadre**: para los cuatro medios, los `totals` de la capa 2 son EXACTAMENTE la fila de
  ese medio en `by_method`, incluido el caso duro de base caja (cobro de junio devuelto en
  julio: en julio no hay fila de cobro pero sí de devolución, y el total de devoluciones cuadra);
* **las dos listas**: `rows` suma `gross` y `refund_rows` suma `refunds`, y para los medios
  manuales `refund_rows` va declarada en `[]`;
* **el detalle discriminado por tipo**: lo que no aplica se OMITE, no se publica en null —se
  asevera la AUSENCIA de la clave, no que valga None—;
* **el aislamiento** en las tres capas (organización y sucursal), y el rol (solo `gym_admin`);
* **los ids malformados**: 400 y no 500, que en `ManualPayment` solo se reproduce en Postgres;
* la cobertura que venía del reporte de pagos manuales borrado: filas legacy con `method=''`,
  `recorded_by` NULL, `branch` NULL bajo filtro de sede, y el aviso de truncado DENTRO del CSV.
"""
from datetime import date, datetime
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.throttling import ScopedRateThrottle

from core.models import Branch, ManualPayment, PaymentTransaction, Plan, StudentPlan
from core.services import reports_revenue_detail
from core.services.reports_base import (METHOD_CASH, METHOD_MERCADOPAGO, METHOD_TRANSFER,
                                        METHOD_UNKNOWN, REVENUE_METHODS, ReportScope)
from core.services.reports_revenue import build_revenue_report
from core.services.reports_revenue_detail import (build_revenue_payments_report,
                                                  revenue_payments_export_spec)

pytestmark = pytest.mark.django_db

LIST_URL = '/api/reports/revenue/payments/'
REVENUE_URL = '/api/reports/revenue/'

JULY_FROM = date(2026, 7, 1)
JULY_TO = date(2026, 7, 31)
JULY_PARAMS = {'date_from': '2026-07-01', 'date_to': '2026-07-31'}


def _detail_url(kind, payment_id):
    return f'/api/reports/revenue/payments/{kind}/{payment_id}/'


def _at(year, month, day, hour=12):
    """Instante LOCAL (`America/Santiago`). Mediodía a propósito: el reporte agrupa por fecha
    local y una hora al borde del día haría que el test midiera la conversión de zona."""
    return timezone.make_aware(datetime(year, month, day, hour, 0))


def _scope(org, *, date_from=JULY_FROM, date_to=JULY_TO, granularity='day', branch=None):
    return ReportScope(organization_id=org.id, date_from=date_from, date_to=date_to,
                       granularity=granularity, branch=branch)


def _plan(org, name='Pack', price=30000, branch=None):
    return Plan.objects.create(organization=org, name=name, plan_type='pack',
                               total_classes=10, unlimited_classes=False,
                               duration_days=30, price=price, branch=branch)


def _membership(student, plan, branch=None):
    return StudentPlan.objects.create(
        user=student, plan=plan, organization_id=plan.organization_id, branch=branch,
        start_date=JULY_FROM, end_date=JULY_TO,
        total_classes=plan.total_classes, unlimited_classes=plan.unlimited_classes,
        classes_used=0, final_price=float(plan.price), is_active=True,
    )


_provider_ids = {'n': 0}


def _tx(org, user, amount, *, collected_at=None, refunded_at=None, refunded_amount=0,
        branch=None, status='approved', plan=None, student_plan=None,
        target_student_plan=None, provider_payment_id='auto', **extra):
    """Cobro en línea. `status` se pasa a mano y el reporte NO lo mira: existe en los tests
    justo para probar que no lo mira.

    `provider_payment_id` se autogenera único: la tabla tiene un `UniqueConstraint` parcial
    sobre (provider, provider_payment_id) y dos filas con el mismo id reventarían el INSERT.
    """
    if provider_payment_id == 'auto':
        _provider_ids['n'] += 1
        provider_payment_id = f'MP-{_provider_ids["n"]}'
    return PaymentTransaction.objects.create(
        organization=org, user=user, branch=branch, amount=Decimal(amount),
        status=status, collected_at=collected_at, refunded_at=refunded_at,
        refunded_amount=Decimal(refunded_amount), plan=plan, student_plan=student_plan,
        target_student_plan=target_student_plan, provider_payment_id=provider_payment_id,
        **extra,
    )


def _manual(org, membership, amount, method, recorded_at, branch=None, reference='',
            recorded_by=None):
    return ManualPayment.objects.create(
        organization=org, student_plan=membership, branch=branch,
        amount=Decimal(amount), method=method, recorded_at=recorded_at,
        reference=reference, recorded_by=recorded_by,
    )


def _legacy_manual(org, membership, amount, recorded_at):
    """Fila anterior a P3.2: `method=''`.

    Se crea con `cash` y se pisa con `.update()` porque `ManualPayment.clean()` rechaza una
    fila NUEVA con método vacío (ver models.py). Es exactamente la forma en que esas filas
    existen en producción: escritas antes de que la columna tuviera choices.
    """
    payment = _manual(org, membership, amount, ManualPayment.METHOD_CASH, recorded_at)
    ManualPayment.objects.filter(pk=payment.pk).update(method='')
    payment.refresh_from_db()
    return payment


@pytest.fixture
def org(make_organization):
    return make_organization('Gym A')


@pytest.fixture
def other_org(make_organization):
    return make_organization('Gym B')


@pytest.fixture
def student(make_user, org):
    return make_user('stu-dd', organization=org, role='student', first_name='Ana',
                     last_name='Pérez')


@pytest.fixture
def admin(make_user, org):
    return make_user('adm-dd', organization=org, role='gym_admin', first_name='Javier',
                     last_name='Neus')


@pytest.fixture
def membership(student, org):
    return _membership(student, _plan(org, name='Mensual 12'))


def _method_row(data, method):
    return next(row for row in data['by_method'] if row['method'] == method)


# --------------------------------------------------------------------------------------
# A. EL CUADRE con la capa 1
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize('method', REVENUE_METHODS)
def test_the_totals_of_a_method_are_exactly_its_row_in_by_method(org, student, membership,
                                                                 method):
    """LA REGLA DURA del drill-down, con datos de los DOS modelos y en los cuatro medios.

    No es "los dos cálculos dan lo mismo": es que hay un solo cálculo. La capa 2 pide los
    querysets y los totales a las mismas funciones de `reports_revenue` que arman `by_method`
    (`method_querysets`/`method_totals`), así que este test protege que nadie vuelva a escribir
    la consulta por su cuenta "para simplificar".
    """
    _tx(org, student, 70000, collected_at=_at(2026, 7, 3))
    _tx(org, student, 20000, collected_at=_at(2026, 7, 5), refunded_at=_at(2026, 7, 10),
        refunded_amount=20000, status='refunded')
    _manual(org, membership, 15000, ManualPayment.METHOD_CASH, _at(2026, 7, 3))
    _manual(org, membership, 5000, ManualPayment.METHOD_CASH, _at(2026, 7, 8))
    _manual(org, membership, 25000, ManualPayment.METHOD_TRANSFER, _at(2026, 7, 9))
    _legacy_manual(org, membership, 7000, _at(2026, 7, 4))

    scope = _scope(org)
    layer1 = _method_row(build_revenue_report(scope), method)
    layer2 = build_revenue_payments_report(scope, method)

    assert layer2['totals'] == {
        'gross': layer1['gross'], 'refunds': layer1['refunds'], 'net': layer1['net'],
        'payments_count': layer1['payments_count'],
        'refunds_count': layer1['refunds_count'],
    }
    # Y las listas suman su propio total: si el total viniera bien pero la lista de abajo
    # sumara otra cosa, el cuadre sería una mentira de una sola pantalla de profundidad.
    assert sum(row['amount'] for row in layer2['rows']) == layer1['gross']
    assert sum(row['amount'] for row in layer2['refund_rows']) == layer1['refunds']
    assert len(layer2['rows']) == layer1['payments_count']
    assert len(layer2['refund_rows']) == layer1['refunds_count']


def test_a_june_charge_refunded_in_july_appears_only_in_the_refund_list_of_july(org, student):
    """EL CASO DURO de base caja, y el motivo de que haya DOS listas.

    En julio ese pago no fue cobrado (no puede estar en `rows`) pero sí fue devuelto. Con una
    sola lista de cobros, el administrador vería `refunds: 40.000` arriba y ninguna fila que lo
    explique abajo — y concluiría que el drill-down no cuadra con el reporte del que salió.
    """
    _tx(org, student, 40000, collected_at=_at(2026, 6, 20), refunded_at=_at(2026, 7, 8),
        refunded_amount=40000, status='refunded')

    scope = _scope(org)
    layer1 = _method_row(build_revenue_report(scope), METHOD_MERCADOPAGO)
    layer2 = build_revenue_payments_report(scope, METHOD_MERCADOPAGO)

    assert layer2['rows'] == []
    assert layer2['totals']['gross'] == layer1['gross'] == 0
    assert layer2['totals']['refunds'] == layer1['refunds'] == 40000
    assert layer2['totals']['net'] == layer1['net'] == -40000
    assert len(layer2['refund_rows']) == 1
    refund = layer2['refund_rows'][0]
    # `occurred_at` es la fecha del EVENTO de la fila: la DEVOLUCIÓN, no el cobro.
    assert refund['occurred_at'].startswith('2026-07-08')
    assert refund['amount'] == 40000
    # Y las dos claves que el front usa para rotular "(cobrado el 20/06 — fuera del período)".
    assert refund['collected_at'].startswith('2026-06-20')
    assert refund['collected_in_period'] is False


def test_a_refund_of_a_charge_collected_inside_the_period_is_flagged_as_such(org, student):
    """La misma fila con el cobro DENTRO del período: la devolución no es un dato huérfano y
    el front no tiene que rotular nada. El cobro aparece además en `rows`, así que las dos
    listas mencionan el mismo pago sin contarlo dos veces (cada una suma su propio total)."""
    transaction = _tx(org, student, 20000, collected_at=_at(2026, 7, 5),
                      refunded_at=_at(2026, 7, 10), refunded_amount=20000, status='refunded')

    data = build_revenue_payments_report(_scope(org), METHOD_MERCADOPAGO)

    assert [row['id'] for row in data['rows']] == [str(transaction.id)]
    assert data['refund_rows'][0]['collected_in_period'] is True
    assert data['totals'] == {'gross': 20000, 'refunds': 20000, 'net': 0,
                              'payments_count': 1, 'refunds_count': 1}


def test_a_refund_of_a_charge_that_was_never_collected_is_not_listed(org, student):
    """Mismo filtro heredado que la capa 1 (`collected_at__isnull=False`): nunca se resta —ni
    se lista— plata que no se sumó. Esas filas existen (histórico de la migración 0044)."""
    _tx(org, student, 99000, collected_at=None, refunded_at=_at(2026, 7, 6),
        refunded_amount=99000, status='refunded')

    data = build_revenue_payments_report(_scope(org), METHOD_MERCADOPAGO)

    assert data['refund_rows'] == []
    assert data['totals']['refunds'] == 0


def test_the_branch_filter_reaches_the_drilldown_and_leaves_out_the_rows_without_branch(
        org, student, membership):
    """Cobertura migrada del reporte borrado: las filas con `branch` NULL quedan FUERA del
    filtro de sede. No hay forma de saber si "sin sede" significa "todas" o "ninguna", así que
    mostrarlas bajo cualquier sede inventaría el dato. Y el listado cuadra con la capa 1
    también bajo filtro de sede, que es donde una de las dos podría olvidarse del filtro."""
    centro = Branch.objects.create(organization=org, name='Sede Centro')
    norte = Branch.objects.create(organization=org, name='Sede Norte')
    inside = _manual(org, membership, 3000, ManualPayment.METHOD_CASH, _at(2026, 7, 3),
                     branch=centro)
    _manual(org, membership, 4000, ManualPayment.METHOD_CASH, _at(2026, 7, 3), branch=norte)
    _manual(org, membership, 9000, ManualPayment.METHOD_CASH, _at(2026, 7, 3), branch=None)

    scope = _scope(org, branch=centro)
    layer1 = _method_row(build_revenue_report(scope), METHOD_CASH)
    data = build_revenue_payments_report(scope, METHOD_CASH)

    assert [row['id'] for row in data['rows']] == [inside.id]
    assert data['totals']['gross'] == layer1['gross'] == 3000
    assert data['filters']['branch_id'] == centro.id
    assert data['filters']['branch_name'] == 'Sede Centro'


# --------------------------------------------------------------------------------------
# B. La capa 2 lista SOLO ese medio
# --------------------------------------------------------------------------------------

def test_asking_for_cash_brings_neither_mercadopago_nor_transfer_rows(org, student,
                                                                      membership):
    cash = _manual(org, membership, 10000, ManualPayment.METHOD_CASH, _at(2026, 7, 3))
    _manual(org, membership, 20000, ManualPayment.METHOD_TRANSFER, _at(2026, 7, 3))
    _legacy_manual(org, membership, 30000, _at(2026, 7, 3))
    _tx(org, student, 40000, collected_at=_at(2026, 7, 3))

    data = build_revenue_payments_report(_scope(org), METHOD_CASH)

    assert [row['id'] for row in data['rows']] == [cash.id]
    assert {row['kind'] for row in data['rows']} == {'manual'}
    assert {row['method'] for row in data['rows']} == {METHOD_CASH}
    assert data['totals']['gross'] == 10000
    assert data['filters']['method'] == METHOD_CASH
    assert data['filters']['method_label'] == 'Efectivo'


def test_manual_methods_declare_an_empty_refund_list_instead_of_omitting_it(org, membership):
    """`[]` declarada y `refunds_truncated: false`, mismo criterio que el `refunds: 0` de la
    capa 1: no existe mecanismo de devolución manual, y una clave ausente diría "no sé"
    mientras que la lista vacía dice "no hubo"."""
    _manual(org, membership, 10000, ManualPayment.METHOD_TRANSFER, _at(2026, 7, 3))

    data = build_revenue_payments_report(_scope(org), METHOD_TRANSFER)

    assert data['refund_rows'] == []
    assert data['refunds_truncated'] is False
    assert data['totals']['refunds'] == 0


def test_the_row_of_a_manual_payment_carries_what_the_gym_needs_to_audit_it(org, student,
                                                                            admin, membership):
    """Cobertura migrada: la fila trae CON QUÉ (medio), QUIÉN la anotó, CUÁNDO, A QUIÉN y por
    qué membresía. `reference` y `recorded_by_name` viajan además porque son dos columnas del
    export que este listado heredó del reporte borrado."""
    branch = Branch.objects.create(organization=org, name='Sede Centro')
    membership.branch = branch
    membership.save(update_fields=['branch'])
    payment = _manual(org, membership, 15000, ManualPayment.METHOD_TRANSFER, _at(2026, 7, 3),
                      branch=branch, reference='TRX-99', recorded_by=admin)
    # La fecha tal cual quedó en la base (UTC), no el objeto en memoria (hora local): el
    # reporte lee de la base y `isoformat()` de los dos no es el mismo texto.
    payment.refresh_from_db()

    data = build_revenue_payments_report(_scope(org), METHOD_TRANSFER)

    assert data['rows'] == [{
        'kind': 'manual',
        'id': payment.id,
        'occurred_at': payment.recorded_at.isoformat(),
        'amount': 15000,
        'student_id': student.id,
        'student_name': 'Ana Pérez',
        'plan_name': 'Mensual 12',
        'branch_id': branch.id,
        'branch_name': 'Sede Centro',
        'method': METHOD_TRANSFER,
        'method_label': 'Transferencia',
        'reference': 'TRX-99',
        'recorded_by_id': admin.id,
        'recorded_by_name': 'Javier Neus',
    }]


def test_a_null_recorder_is_declared_and_does_not_break_the_row(org, membership):
    """Cobertura migrada: `recorded_by` es SET_NULL (borrar al administrador que cobró no puede
    des-pagar la membresía), así que NULL es un estado legítimo. No puede reventar la fila ni
    salir como celda vacía indistinguible de un dato faltante por error."""
    _manual(org, membership, 1000, ManualPayment.METHOD_CASH, _at(2026, 7, 3),
            recorded_by=None)

    row = build_revenue_payments_report(_scope(org), METHOD_CASH)['rows'][0]

    assert row['recorded_by_id'] is None
    assert row['recorded_by_name'] == 'Usuario eliminado'


def test_names_fall_back_to_the_username_when_nobody_declared_one(org, make_user):
    """Cobertura migrada: `get_full_name()` devuelve '' cuando nombre y apellido están vacíos
    —son opcionales en el alta— y una celda vacía en un reporte de plata es peor que el
    username, que al menos identifica a quién sin ambigüedad."""
    nameless_student = make_user('stu-noname', organization=org, role='student')
    nameless_admin = make_user('adm-noname', organization=org, role='gym_admin')
    membership = _membership(nameless_student, _plan(org))
    _manual(org, membership, 1000, ManualPayment.METHOD_CASH, _at(2026, 7, 3),
            recorded_by=nameless_admin)

    row = build_revenue_payments_report(_scope(org), METHOD_CASH)['rows'][0]

    assert row['student_name'] == 'stu-noname'
    assert row['recorded_by_name'] == 'adm-noname'


def test_the_row_of_an_online_charge_carries_the_transaction_data(org, student, membership):
    """La fila de MercadoPago trae `status` y `provider_payment_id`: son las dos columnas
    propias de su export (`Estado`, `ID de transacción`) y el dato con el que el gimnasio
    concilia contra el panel del proveedor. El id viaja como STRING porque es un UUID y vuelve
    como segmento de URL en la capa 3."""
    plan = _plan(org, name='Mensual 12')
    transaction = _tx(org, student, 70000, collected_at=_at(2026, 7, 3), plan=plan,
                      student_plan=membership, provider_payment_id='12345')
    transaction.refresh_from_db()      # la fecha tal cual quedó en la base (UTC)

    row = build_revenue_payments_report(_scope(org), METHOD_MERCADOPAGO)['rows'][0]

    assert row['kind'] == 'mercadopago'
    assert row['id'] == str(transaction.id)
    assert isinstance(row['id'], str)
    assert row['occurred_at'] == transaction.collected_at.isoformat()
    assert row['amount'] == 70000
    assert row['student_id'] == student.id and row['student_name'] == 'Ana Pérez'
    assert row['plan_name'] == 'Mensual 12'
    assert row['method'] == METHOD_MERCADOPAGO and row['method_label'] == 'MercadoPago'
    assert row['status'] == 'approved'
    assert row['provider_payment_id'] == '12345'
    # Sin devolución no hay claves de devolución: son exclusivas de `refund_rows`.
    assert 'collected_in_period' not in row


def test_an_online_charge_of_a_deleted_catalog_plan_publishes_a_null_plan_name(org, student):
    """`PaymentTransaction.plan` es SET_NULL: el gimnasio puede borrar el plan de su catálogo
    y el cobro sigue siendo plata que entró. `plan_name` va en null y no se inventa un texto."""
    _tx(org, student, 50000, collected_at=_at(2026, 7, 3), plan=None)

    row = build_revenue_payments_report(_scope(org), METHOD_MERCADOPAGO)['rows'][0]

    assert row['plan_name'] is None


def test_rows_come_newest_first(org, membership):
    """Lo más reciente arriba, que es donde el administrador busca — y es también lo que hace
    que el recorte por `MAX_ROWS` deje afuera lo más viejo y no una muestra al azar."""
    old = _manual(org, membership, 1000, ManualPayment.METHOD_CASH, _at(2026, 7, 3))
    new = _manual(org, membership, 2000, ManualPayment.METHOD_CASH, _at(2026, 7, 20))

    data = build_revenue_payments_report(_scope(org), METHOD_CASH)

    assert [row['id'] for row in data['rows']] == [new.id, old.id]


# --------------------------------------------------------------------------------------
# C. Capa 3 — el detalle, discriminado por tipo
# --------------------------------------------------------------------------------------

def test_the_detail_of_a_manual_payment_has_the_recorder_and_nothing_of_mercadopago(
        api_client, org, admin, student, membership):
    """Las claves que no aplican se OMITEN, no van en null: el front decide qué mostrar por
    PRESENCIA de clave. Un `status: null` en un cobro de recepción no es "sin dato", es una
    pregunta que no existe."""
    branch = Branch.objects.create(organization=org, name='Sede Centro')
    payment = _manual(org, membership, 20000, ManualPayment.METHOD_CASH, _at(2026, 7, 3),
                      branch=branch, reference='caja 2', recorded_by=admin)
    payment.refresh_from_db()          # la fecha tal cual quedó en la base (UTC)
    api_client.force_authenticate(user=admin)

    resp = api_client.get(_detail_url('manual', payment.id))

    assert resp.status_code == 200, resp.content
    assert resp.data == {
        'kind': 'manual',
        'id': payment.id,
        'amount': 20000,
        'recorded_at': payment.recorded_at.isoformat(),
        'method': METHOD_CASH,
        'method_label': 'Efectivo',
        'reference': 'caja 2',
        'student_id': student.id,
        'student_name': 'Ana Pérez',
        'student_plan_id': membership.id,
        'plan_name': 'Mensual 12',
        'branch_id': branch.id,
        'branch_name': 'Sede Centro',
        'recorded_by_id': admin.id,
        'recorded_by_name': 'Javier Neus',
    }
    for absent in ('status', 'status_detail', 'provider', 'provider_payment_id',
                   'collected_at', 'processed_at', 'refunded_at', 'refunded_amount',
                   'currency', 'plan_amount', 'enrollment_fee_amount'):
        assert absent not in resp.data


def test_the_detail_of_an_online_charge_has_no_recorder_at_all(api_client, org, admin,
                                                               student, membership):
    """Ninguna clave `recorded_by*`, ni siquiera en null: este cobro lo escribió el webhook del
    proveedor, no una persona. Publicarla en null diría "no se sabe quién lo registró", y sí se
    sabe: nadie."""
    branch = Branch.objects.create(organization=org, name='Sede Centro')
    plan = _plan(org, name='Mensual 12')
    transaction = _tx(org, student, 70000, collected_at=_at(2026, 7, 3), branch=branch,
                      plan=plan, student_plan=membership, provider_payment_id='12345',
                      status_detail='accredited', processed_at=_at(2026, 7, 3, hour=13),
                      plan_amount=Decimal('70000'))
    transaction.refresh_from_db()      # las fechas tal cual quedaron en la base (UTC)
    api_client.force_authenticate(user=admin)

    resp = api_client.get(_detail_url('mercadopago', transaction.id))

    assert resp.status_code == 200, resp.content
    assert resp.data['kind'] == 'mercadopago'
    assert resp.data['id'] == str(transaction.id)
    assert resp.data['amount'] == 70000
    assert resp.data['currency'] == 'CLP'
    assert resp.data['status'] == 'approved'
    assert resp.data['status_detail'] == 'accredited'
    assert resp.data['provider'] == 'mercadopago'
    assert resp.data['provider_payment_id'] == '12345'
    assert resp.data['collected_at'] == transaction.collected_at.isoformat()
    assert resp.data['processed_at'] == transaction.processed_at.isoformat()
    assert resp.data['refunded_at'] is None
    assert resp.data['refunded_amount'] == 0
    assert resp.data['plan_amount'] == 70000
    assert resp.data['enrollment_fee_amount'] == 0
    assert resp.data['student_id'] == student.id
    assert resp.data['student_plan_id'] == membership.id
    assert resp.data['plan_name'] == 'Mensual 12'
    assert resp.data['branch_id'] == branch.id
    assert 'recorded_by_id' not in resp.data
    assert 'recorded_by_name' not in resp.data
    assert 'reference' not in resp.data


def test_the_detail_of_an_enrollment_fee_names_the_plan_of_the_targeted_membership(
        api_client, org, admin, student, membership):
    """En un cobro de MATRÍCULA `plan` es NULL por construcción —no se compró ningún plan— y la
    membresía sale de `target_student_plan`. Sin ese fallback la ficha diría solo "Ana Pérez" y
    el administrador no sabría de qué membresía le hablan."""
    transaction = _tx(org, student, 12000, collected_at=_at(2026, 7, 3), plan=None,
                      target_student_plan=membership,
                      enrollment_fee_amount=Decimal('12000'))
    api_client.force_authenticate(user=admin)

    resp = api_client.get(_detail_url('mercadopago', transaction.id))

    assert resp.status_code == 200, resp.content
    assert resp.data['student_plan_id'] == membership.id
    assert resp.data['plan_name'] == 'Mensual 12'
    assert resp.data['enrollment_fee_amount'] == 12000
    assert resp.data['plan_amount'] == 0


def test_the_detail_answers_for_a_transaction_that_never_got_collected(api_client, org, admin,
                                                                        student):
    """DECISIÓN DOCUMENTADA: el alcance del detalle es SOLO la organización.

    Sin período y sin exigir `collected_at`. Una transacción `pending` o `rejected` de la propia
    organización es dato propio del gimnasio, y filtrar acá por lo mismo que filtra el listado
    haría que la misma URL diera 404 según el rango que el usuario tuviera seleccionado."""
    transaction = _tx(org, student, 50000, collected_at=None, status='pending')
    api_client.force_authenticate(user=admin)

    resp = api_client.get(_detail_url('mercadopago', transaction.id))

    assert resp.status_code == 200, resp.content
    assert resp.data['status'] == 'pending'
    assert resp.data['collected_at'] is None


# --------------------------------------------------------------------------------------
# D. Aislamiento cross-org en las TRES capas
# --------------------------------------------------------------------------------------

def test_no_row_of_another_organization_ever_appears_in_either_list(org, other_org, make_user,
                                                                     student, membership):
    """Regla 1 del backend, en las dos listas y en los totales. El listado hereda el filtro de
    `method_querysets`, que ya filtra por organización — este test es la prueba de que lo
    hereda de verdad y no lo re-arma por su cuenta."""
    foreign_student = make_user('stu-foreign', organization=other_org, role='student')
    foreign_membership = _membership(foreign_student, _plan(other_org))
    _manual(other_org, foreign_membership, 999999, ManualPayment.METHOD_CASH, _at(2026, 7, 3))
    _tx(other_org, foreign_student, 888888, collected_at=_at(2026, 7, 3),
        refunded_at=_at(2026, 7, 4), refunded_amount=888888, status='refunded')
    _manual(org, membership, 1000, ManualPayment.METHOD_CASH, _at(2026, 7, 3))
    _tx(org, student, 2000, collected_at=_at(2026, 7, 3))

    cash = build_revenue_payments_report(_scope(org), METHOD_CASH)
    online = build_revenue_payments_report(_scope(org), METHOD_MERCADOPAGO)

    assert [row['amount'] for row in cash['rows']] == [1000]
    assert [row['amount'] for row in online['rows']] == [2000]
    assert online['refund_rows'] == []
    assert cash['totals']['gross'] == 1000
    assert online['totals'] == {'gross': 2000, 'refunds': 0, 'net': 2000,
                                'payments_count': 1, 'refunds_count': 0}


def test_a_plan_moved_to_another_organization_does_not_leak_its_name_or_the_membership_pk(
        org, other_org, student, membership):
    """La FILA es de esta organización pero el PLAN que cuelga de ella ya no.

    El escenario NO es hipotético: un `superadmin` mueve un `Plan` de organización con un
    `PATCH /api/plans/{id}/` —`PlanSerializer.validate` solo fuerza la organización cuando el
    actor es `gym_admin`— y ni `StudentPlan.organization` ni `ManualPayment.organization` se
    re-sincronizan. Ninguna constraint sostiene esa invariante, así que la LECTURA la corta:
    es el mismo criterio que `PaymentTransactionAdminSerializer.get_line_items` aplica sobre
    este mismo modelo.

    Lo que NO puede viajar es dato de NEGOCIO de otro tenant: el nombre del plan y el PK de la
    membresía. El NOMBRE DEL ALUMNO sí sigue viajando, y es deliberado (ver `_manual_row`):
    ese gimnasio cobró en efectivo a una persona que conocía por su nombre.
    """
    manual_payment = _manual(org, membership, 5000, ManualPayment.METHOD_CASH, _at(2026, 7, 3))
    online = _tx(org, student, 7000, collected_at=_at(2026, 7, 3), plan=membership.plan,
                 student_plan=membership)

    # La mudanza, por debajo del ORM igual que la haría el PATCH del superadmin.
    Plan.objects.filter(pk=membership.plan_id).update(organization=other_org)
    StudentPlan.objects.filter(pk=membership.pk).update(organization=other_org)

    cash = build_revenue_payments_report(_scope(org), METHOD_CASH)
    card = build_revenue_payments_report(_scope(org), METHOD_MERCADOPAGO)

    # Las filas siguen siendo de esta organización y la plata sigue contando: lo que se corta
    # es el join, no el ingreso.
    assert cash['totals']['gross'] == 5000
    assert card['totals']['gross'] == 7000
    assert cash['rows'][0]['plan_name'] is None
    assert card['rows'][0]['plan_name'] is None
    assert cash['rows'][0]['student_name'] == 'Ana Pérez'

    # `payment_id` ya tipado: la view lo valida antes (int para manual, UUID para el cobro en
    # línea), y `build_payment_detail` lo recibe listo.
    manual_detail = reports_revenue_detail.build_payment_detail(
        organization_id=org.id, kind='manual', payment_id=manual_payment.id)
    card_detail = reports_revenue_detail.build_payment_detail(
        organization_id=org.id, kind='mercadopago', payment_id=online.id)

    assert manual_detail['plan_name'] is None
    assert manual_detail['student_plan_id'] is None
    assert card_detail['plan_name'] is None
    assert card_detail['student_plan_id'] is None
    assert manual_detail['student_name'] == 'Ana Pérez'


def test_a_branch_of_another_organization_is_a_404_in_the_listing(api_client, org, other_org,
                                                                   admin):
    """404 y no 403: los ids de sede son adivinables y un 403 confirmaría "existe, pero no es
    tuyo" — delataría la topología de sedes del vecino."""
    foreign_branch = Branch.objects.create(organization=other_org, name='Ajena')
    api_client.force_authenticate(user=admin)

    resp = api_client.get(LIST_URL, {**JULY_PARAMS, 'method': METHOD_CASH,
                                     'branch_id': foreign_branch.id})

    assert resp.status_code == 404


def test_the_detail_of_a_manual_payment_of_another_organization_is_a_404(api_client, org,
                                                                         other_org, admin,
                                                                         make_user):
    foreign_student = make_user('stu-foreign-md', organization=other_org, role='student')
    foreign_membership = _membership(foreign_student, _plan(other_org))
    foreign_payment = _manual(other_org, foreign_membership, 1000,
                              ManualPayment.METHOD_CASH, _at(2026, 7, 3))
    api_client.force_authenticate(user=admin)

    resp = api_client.get(_detail_url('manual', foreign_payment.id))

    assert resp.status_code == 404


def test_the_detail_of_an_online_charge_of_another_organization_is_a_404(api_client, org,
                                                                         other_org, admin,
                                                                         make_user):
    foreign_student = make_user('stu-foreign-tx', organization=other_org, role='student')
    foreign_tx = _tx(other_org, foreign_student, 1000, collected_at=_at(2026, 7, 3))
    api_client.force_authenticate(user=admin)

    resp = api_client.get(_detail_url('mercadopago', foreign_tx.id))

    assert resp.status_code == 404


def test_an_unknown_kind_is_a_404(api_client, admin):
    """El `kind` es un segmento de RUTA: una ruta que no existe no es un parámetro inválido."""
    api_client.force_authenticate(user=admin)

    assert api_client.get(_detail_url('bitcoin', 1)).status_code == 404


# --------------------------------------------------------------------------------------
# E. Roles: el drill-down no abre ninguna puerta nueva
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize('role', ['manager', 'monitor', 'teacher', 'student'])
def test_no_org_role_other_than_gym_admin_can_open_either_layer(api_client, org, make_user,
                                                                 role):
    """Mismo `ReportPermission` que la capa 1: el manager tampoco, ni de lectura. Un drill-down
    más laxo que la pantalla desde la que se llega sería una puerta lateral a la misma plata."""
    api_client.force_authenticate(user=make_user(f'u-{role}', organization=org, role=role))

    assert api_client.get(LIST_URL, {'method': METHOD_CASH}).status_code == 403
    assert api_client.get(_detail_url('manual', 1)).status_code == 403


def test_the_superadmin_is_excluded_from_both_layers(api_client, make_user):
    """Rol de PLATAFORMA sin organización propia: no hay alcance que scopear, y darle el
    drill-down sería darle los cobros de todos los gimnasios."""
    api_client.force_authenticate(user=make_user('root-dd', organization=None,
                                                 role='superadmin'))

    assert api_client.get(LIST_URL, {'method': METHOD_CASH}).status_code == 403
    assert api_client.get(_detail_url('mercadopago', 1)).status_code == 403


def test_both_layers_require_authentication(api_client):
    assert api_client.get(LIST_URL, {'method': METHOD_CASH}).status_code == 401
    assert api_client.get(_detail_url('manual', 1)).status_code == 401


def test_the_detail_is_read_only(api_client, admin):
    api_client.force_authenticate(user=admin)

    assert api_client.post(_detail_url('manual', 1), {}, format='json').status_code == 405
    assert api_client.delete(_detail_url('manual', 1)).status_code == 405


# --------------------------------------------------------------------------------------
# F. Ids malformados: 400 y NO 500
# --------------------------------------------------------------------------------------

def test_a_manual_id_outside_the_bigint_range_is_a_400_and_not_a_500(api_client, admin):
    """⚠️ ESTE TEST SOLO FALLA EN POSTGRES, que es donde corre producción y esta suite.

    Un `filter(id=...)` con un entero fuera del rango de bigint revienta con 500 en PostgreSQL
    y SQLite lo deja pasar sin chistar (es el motivo por el que el fallback a SQLite está
    cerrado — ver backend/CLAUDE.md). Por eso la forma se valida ANTES de tocar la base, con el
    mismo `IntegerField` acotado que ya usa `_scoped_id`."""
    api_client.force_authenticate(user=admin)

    resp = api_client.get(_detail_url('manual', 99999999999999999999))

    assert resp.status_code == 400


@pytest.mark.parametrize('raw_id', ['no-soy-un-uuid', '123',
                                    '00000000-0000-4000-8000'])   # UUID truncado
def test_a_mercadopago_id_that_is_not_a_uuid_is_a_400_and_not_a_500(api_client, admin, raw_id):
    """`PaymentTransaction.id` es un `UUIDField`: un string cualquiera dentro del lookup levanta
    `ValidationError` desde el conversor del campo, que DRF no traduce — o sea un 500 en un
    endpoint de plata."""
    api_client.force_authenticate(user=admin)

    resp = api_client.get(_detail_url('mercadopago', raw_id))

    assert resp.status_code == 400


def test_a_wellformed_but_nonexistent_id_is_a_404(api_client, admin):
    """Malformado es 400 (no revela nada) y ajeno/inexistente es 404 (anti-oráculo): son dos
    respuestas distintas a propósito, y un 403 en el segundo caso confirmaría que el id
    existe."""
    api_client.force_authenticate(user=admin)

    assert api_client.get(_detail_url('manual', 987654)).status_code == 404
    assert api_client.get(
        _detail_url('mercadopago', '00000000-0000-4000-8000-000000000000')).status_code == 404


# --------------------------------------------------------------------------------------
# G. El parámetro `method` del listado
# --------------------------------------------------------------------------------------

def test_the_listing_without_a_method_is_a_400(api_client, admin):
    """Ausente NO significa "todos": este listado explica UNA fila de `by_method`, y caer al
    consolidado devolvería una mezcla de medios bajo un encabezado que nombra a uno solo —con
    columnas de export que además dependen de cuál es."""
    api_client.force_authenticate(user=admin)

    resp = api_client.get(LIST_URL, JULY_PARAMS)

    assert resp.status_code == 400
    assert 'method' in resp.data


def test_the_listing_with_an_invalid_method_is_a_400(api_client, admin):
    api_client.force_authenticate(user=admin)

    resp = api_client.get(LIST_URL, {**JULY_PARAMS, 'method': 'bitcoin'})

    assert resp.status_code == 400
    assert 'method' in resp.data


def test_the_listing_over_http_returns_the_same_totals_as_the_service(api_client, org, admin,
                                                                       student, membership):
    api_client.force_authenticate(user=admin)
    _tx(org, student, 70000, collected_at=_at(2026, 7, 3))
    _manual(org, membership, 5000, ManualPayment.METHOD_CASH, _at(2026, 7, 4))

    resp = api_client.get(LIST_URL, {**JULY_PARAMS, 'method': METHOD_MERCADOPAGO})

    assert resp.status_code == 200, resp.content
    assert resp.data['totals'] == {'gross': 70000, 'refunds': 0, 'net': 70000,
                                   'payments_count': 1, 'refunds_count': 0}
    assert resp.data['period']['date_from'] == '2026-07-01'
    assert resp.data['row_limit'] == reports_revenue_detail.MAX_ROWS
    assert resp.data['truncated'] is False
    assert resp.data['refunds_truncated'] is False
    assert len(resp.data['rows']) == 1


# --------------------------------------------------------------------------------------
# H. Tope de filas
# --------------------------------------------------------------------------------------

def test_the_totals_stay_whole_when_the_row_list_is_truncated(org, membership, monkeypatch):
    """El tope corta la LISTA, nunca los totales: esos se agregan en la base sobre todas las
    filas del período (`method_totals` no lleva `[:MAX_ROWS]`). Un tope silencioso que además
    mintiera en el número de arriba sería peor que no tener tope."""
    monkeypatch.setattr(reports_revenue_detail, 'MAX_ROWS', 2)
    for _ in range(5):
        _manual(org, membership, 1000, ManualPayment.METHOD_CASH, _at(2026, 7, 3))

    data = build_revenue_payments_report(_scope(org), METHOD_CASH)

    assert len(data['rows']) == 2
    assert data['row_limit'] == 2
    assert data['truncated'] is True
    assert data['totals']['gross'] == 5000
    assert data['totals']['payments_count'] == 5


def test_the_two_lists_are_capped_independently(org, student, monkeypatch):
    """El tope aplica a `rows` y a `refund_rows` por separado: tres devoluciones no pueden
    comerse el cupo de los cobros ni al revés."""
    monkeypatch.setattr(reports_revenue_detail, 'MAX_ROWS', 2)
    for day in (3, 4, 5):
        _tx(org, student, 1000, collected_at=_at(2026, 7, day))
    for day in (6, 7, 8):
        _tx(org, student, 2000, collected_at=_at(2026, 7, 2), refunded_at=_at(2026, 7, day),
            refunded_amount=2000, status='refunded')

    data = build_revenue_payments_report(_scope(org), METHOD_MERCADOPAGO)

    assert len(data['rows']) == 2 and data['truncated'] is True
    assert len(data['refund_rows']) == 2 and data['refunds_truncated'] is True
    # 3 cobros de 1000 + 3 cobros de 2000 (los devueltos también entraron en el período).
    assert data['totals']['gross'] == 9000
    assert data['totals']['refunds'] == 6000
    assert data['totals']['refunds_count'] == 3


# --------------------------------------------------------------------------------------
# I. Export
# --------------------------------------------------------------------------------------

def test_the_export_of_a_manual_method_keeps_the_columns_of_the_deleted_report(org, admin,
                                                                                membership):
    """El libro de caja que el gimnasio baja todos los meses y pega en su planilla: MISMAS ocho
    columnas que tenía `GET /api/reports/manual-payments/`. Cambiarlas al absorber el reporte le
    rompería fórmulas de una planilla que no controlamos."""
    _manual(org, membership, 4000, ManualPayment.METHOD_CASH, _at(2026, 7, 3),
            reference='REF-1', recorded_by=admin)
    _manual(org, membership, 6000, ManualPayment.METHOD_CASH, _at(2026, 7, 4),
            reference='REF-2', recorded_by=admin)

    spec = revenue_payments_export_spec(
        build_revenue_payments_report(_scope(org), METHOD_CASH))

    assert spec['header'] == ['Fecha', 'Alumno', 'Plan', 'Sede', 'Método', 'Referencia',
                              'Registrado por', 'Monto']
    assert len(spec['rows']) == 2
    assert all(len(row) == len(spec['header']) for row in spec['rows'])
    assert {row[-1] for row in spec['rows']} == {4000, 6000}
    assert {row[5] for row in spec['rows']} == {'REF-1', 'REF-2'}
    assert spec['total_row'][0] == 'TOTAL'
    assert spec['total_row'][-1] == 10000
    # Sin corte no hay fila de aviso: sumar la columna da el TOTAL.
    assert sum(row[-1] for row in spec['rows']) == spec['total_row'][-1]


def test_a_truncated_export_declares_the_cut_inside_the_file(org, membership, monkeypatch):
    """El descuadre del archivo no puede ser MUDO: la lista viene cortada y la fila TOTAL es del
    período completo, así que sumar la columna `Monto` no da el TOTAL. La pantalla ya avisa; el
    CSV viaja solo y tiene que avisarlo también, o el que lo abre concluye que el reporte está
    roto (o corrige el total a mano)."""
    monkeypatch.setattr(reports_revenue_detail, 'MAX_ROWS', 2)
    for _ in range(5):
        _manual(org, membership, 1000, ManualPayment.METHOD_CASH, _at(2026, 7, 3))

    spec = revenue_payments_export_spec(
        build_revenue_payments_report(_scope(org), METHOD_CASH))

    assert len(spec['rows']) == 3        # 2 filas de datos + el aviso
    notice = spec['rows'][-1][0]
    assert 'recortada' in notice and '2' in notice and '5' in notice
    assert len(spec['rows'][-1]) == len(spec['header'])
    assert spec['total_row'][-1] == 5000


def test_the_mercadopago_export_separates_charges_from_refunds_and_sums_to_the_net(
        org, student, membership):
    """Las devoluciones van en NEGATIVO para que sumar la columna `Monto` dé el NETO publicado.
    En positivo, la suma daría bruto + devoluciones: un número que no existe en ninguna pantalla
    y que INFLA el ingreso justo en los períodos donde salió plata de la caja."""
    plan = _plan(org, name='Mensual 12')
    _tx(org, student, 70000, collected_at=_at(2026, 7, 3), plan=plan,
        provider_payment_id='MP-A')
    _tx(org, student, 20000, collected_at=_at(2026, 7, 5), refunded_at=_at(2026, 7, 10),
        refunded_amount=20000, status='refunded', plan=plan, provider_payment_id='MP-B')

    data = build_revenue_payments_report(_scope(org), METHOD_MERCADOPAGO)
    spec = revenue_payments_export_spec(data)

    assert spec['header'] == ['Tipo', 'Fecha', 'Alumno', 'Plan', 'Sede',
                              'ID de transacción', 'Estado', 'Monto']
    assert [row[0] for row in spec['rows']] == ['Cobro', 'Cobro', 'Devolución']
    assert [row[-1] for row in spec['rows']] == [20000, 70000, -20000]
    assert [row[5] for row in spec['rows']] == ['MP-B', 'MP-A', 'MP-B']
    assert spec['total_row'][-1] == data['totals']['net'] == 70000
    assert sum(row[-1] for row in spec['rows']) == spec['total_row'][-1]


def test_the_csv_export_over_http_carries_the_manual_columns(api_client, org, admin,
                                                              membership):
    api_client.force_authenticate(user=admin)
    _manual(org, membership, 12345, ManualPayment.METHOD_TRANSFER, _at(2026, 7, 3),
            reference='TRX-csv', recorded_by=admin)

    resp = api_client.get(LIST_URL, {**JULY_PARAMS, 'method': METHOD_TRANSFER,
                                     'export': 'csv'})

    assert resp.status_code == 200, resp.content
    assert resp['Content-Type'].startswith('text/csv')
    body = resp.content.decode('utf-8-sig')
    assert 'Fecha,Alumno,Plan,Sede,Método,Referencia,Registrado por,Monto' in body
    assert 'TRX-csv' in body
    assert 'Javier Neus' in body
    assert 'TOTAL' in body and '12345' in body


def test_the_xlsx_export_does_not_blow_up(api_client, org, admin, student):
    api_client.force_authenticate(user=admin)
    _tx(org, student, 70000, collected_at=_at(2026, 7, 3), refunded_at=_at(2026, 7, 9),
        refunded_amount=70000, status='refunded')

    resp = api_client.get(LIST_URL, {**JULY_PARAMS, 'method': METHOD_MERCADOPAGO,
                                     'export': 'xlsx'})

    assert resp.status_code == 200, resp.content
    assert 'spreadsheetml.sheet' in resp['Content-Type']
    assert 'attachment; filename=' in resp['Content-Disposition']


def test_an_unknown_export_format_is_a_400(api_client, admin):
    """Pedir `pdf` y recibir un csv con 200 es un fallo silencioso, y el archivo que baja es
    plata que alguien va a pegar en una planilla."""
    api_client.force_authenticate(user=admin)

    resp = api_client.get(LIST_URL, {**JULY_PARAMS, 'method': METHOD_CASH, 'export': 'pdf'})

    assert resp.status_code == 400


def test_the_detail_declares_its_own_throttle_scope_but_not_its_own_permission(settings):
    """Calca `test_the_endpoint_declares_its_own_throttle_scope` de `AdvanceClassWindowsView`.

    Las dos mitades importan y dicen cosas distintas. El SCOPE es propio y más holgado a
    propósito: auditar caja es abrir decenas de pagos seguidos, y con el cupo compartido de los
    reportes el 429 caía en la mitad de una revisión contable. El PERMISO, en cambio, es
    LITERALMENTE la misma clase que el de la capa 1: si alguien alguna vez afloja el rol de esta
    view "para que haga juego con el throttle", este test lo frena. Cupo no es autorización.
    """
    from core.permissions import ReportPermission
    from core.views_reports import RevenuePaymentDetailView, RevenueReportView

    assert RevenuePaymentDetailView.throttle_scope == 'reports_detail'
    assert ScopedRateThrottle in RevenuePaymentDetailView.throttle_classes
    assert settings.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']['reports_detail'] == '600/hour'
    assert RevenuePaymentDetailView.permission_classes == [ReportPermission]
    assert RevenueReportView.permission_classes == [ReportPermission]
