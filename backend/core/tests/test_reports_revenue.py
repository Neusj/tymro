"""Reporte de ingresos (P3.4 · Pieza 1) — `core.services.reports_revenue`.

Es código de PLATA: cada test de acá fija una afirmación que el reporte le hace al
administrador sobre su caja, y ninguna puede aflojarse "para que pase". Lo que se fija:

* la resta bruto − devoluciones = neto en TODOS los niveles (total, método, punto de serie);
* qué NO se resta (una devolución de un cobro que nunca entró) y qué NO se suma (una fila
  aprobada sin `collected_at`): el reporte no depende de `status`, que es pisable;
* base CAJA: la devolución pesa en el período en que ocurrió, incluso si eso deja el neto
  del período en negativo;
* aislamiento por organización y por sucursal;
* la comparación contra el período anterior (mismo largo, mismo filtro de método) y el
  porcentaje que vale `None` en vez de inventar un crecimiento;
* la serie rellenada con ceros, en día y en mes;
* el endpoint: solo `gym_admin`, sede ajena 404, y el CSV con las tres columnas separadas.
"""
from datetime import date, datetime
from decimal import Decimal

import pytest
from django.utils import timezone

from core.models import Branch, ManualPayment, PaymentTransaction, Plan, StudentPlan
from core.services.reports_base import METHOD_MERCADOPAGO, METHOD_UNKNOWN, ReportScope
from core.services.reports_revenue import build_revenue_report, revenue_export_spec

pytestmark = pytest.mark.django_db

URL = '/api/reports/revenue/'

JULY_FROM = date(2026, 7, 1)
JULY_TO = date(2026, 7, 31)


def _at(year, month, day, hour=12):
    """Instante LOCAL (`America/Santiago`). Mediodía a propósito: el reporte agrupa por fecha
    local y una hora al borde del día haría que el test midiera la conversión de zona en vez
    de la lógica del reporte."""
    return timezone.make_aware(datetime(year, month, day, hour, 0))


def _scope(org, *, date_from=JULY_FROM, date_to=JULY_TO, granularity='day', branch=None):
    return ReportScope(organization_id=org.id, date_from=date_from, date_to=date_to,
                       granularity=granularity, branch=branch)


def _plan(org, price=30000):
    return Plan.objects.create(organization=org, name='Pack', plan_type='pack',
                               total_classes=10, unlimited_classes=False,
                               duration_days=30, price=price)


def _membership(student, plan, branch=None):
    return StudentPlan.objects.create(
        user=student, plan=plan, organization_id=plan.organization_id, branch=branch,
        start_date=JULY_FROM, end_date=JULY_TO,
        total_classes=plan.total_classes, unlimited_classes=plan.unlimited_classes,
        classes_used=0, final_price=float(plan.price), is_active=True,
    )


def _tx(org, user, amount, *, collected_at=None, refunded_at=None, refunded_amount=0,
        branch=None, status='approved'):
    """Cobro en línea. `status` se pasa a mano y el reporte NO lo mira: existe en los tests
    justo para probar que no lo mira."""
    return PaymentTransaction.objects.create(
        organization=org, user=user, branch=branch, amount=Decimal(amount),
        status=status, collected_at=collected_at, refunded_at=refunded_at,
        refunded_amount=Decimal(refunded_amount),
    )


def _manual(org, membership, amount, method, recorded_at, branch=None):
    return ManualPayment.objects.create(
        organization=org, student_plan=membership, branch=branch,
        amount=Decimal(amount), method=method, recorded_at=recorded_at,
    )


@pytest.fixture
def org(make_organization):
    return make_organization('Gym A')


@pytest.fixture
def other_org(make_organization):
    return make_organization('Gym B')


@pytest.fixture
def student(make_user, org):
    return make_user('stu-rev', organization=org, role='student')


@pytest.fixture
def admin(make_user, org):
    return make_user('adm-rev', organization=org, role='gym_admin')


@pytest.fixture
def membership(student, org):
    return _membership(student, _plan(org))


def _method_row(data, method):
    return next(row for row in data['by_method'] if row['method'] == method)


def _bucket(data, key):
    return next(point for point in data['series'] if point['bucket'] == key)


# --------------------------------------------------------------------------------------
# A. La resta: bruto, devoluciones y neto
# --------------------------------------------------------------------------------------

def test_gross_minus_refunds_equals_net_at_every_level_of_the_payload(org, student,
                                                                     membership):
    """El neto es SIEMPRE la resta de los dos números publicados al lado, en el total, en la
    fila del método y en cada punto de la serie. Si algún nivel trajera un neto que no cumple
    la resta, el administrador estaría viendo tres cifras que no cierran entre sí."""
    _tx(org, student, 30000, collected_at=_at(2026, 7, 3))
    # Cobrado y devuelto DENTRO del mismo período: suma en su día y resta en el de la
    # devolución. `status='refunded'` ya pisó el estado y el bruto tiene que seguir contando.
    _tx(org, student, 20000, collected_at=_at(2026, 7, 5), refunded_at=_at(2026, 7, 10),
        refunded_amount=20000, status='refunded')
    _manual(org, membership, 15000, ManualPayment.METHOD_CASH, _at(2026, 7, 3))

    data = build_revenue_report(_scope(org))

    assert data['totals'] == {
        'gross': 65000, 'refunds': 20000, 'net': 45000,
        'payments_count': 3, 'refunds_count': 1,
    }
    mp_row = _method_row(data, METHOD_MERCADOPAGO)
    assert (mp_row['gross'], mp_row['refunds'], mp_row['net']) == (50000, 20000, 30000)
    assert (mp_row['payments_count'], mp_row['refunds_count']) == (2, 1)
    assert _bucket(data, '2026-07-03') == {'bucket': '2026-07-03', 'gross': 45000,
                                           'refunds': 0, 'net': 45000}
    assert _bucket(data, '2026-07-05') == {'bucket': '2026-07-05', 'gross': 20000,
                                           'refunds': 0, 'net': 20000}
    assert _bucket(data, '2026-07-10') == {'bucket': '2026-07-10', 'gross': 0,
                                           'refunds': 20000, 'net': -20000}
    for level in [data['totals'], *data['by_method'], *data['series']]:
        assert level['net'] == level['gross'] - level['refunds']
    # La serie tiene que sumar exactamente el total: es el mismo dinero mirado por día.
    assert sum(point['gross'] for point in data['series']) == data['totals']['gross']
    assert sum(point['refunds'] for point in data['series']) == data['totals']['refunds']


def test_a_refund_of_a_charge_that_was_never_collected_is_not_subtracted(org, student):
    """`collected_at__isnull=False` en las devoluciones: nunca se resta plata que no se sumó.

    Esas filas existen de verdad (el histórico irrecuperable de la migración 0044: cobros
    devueltos antes de que estos campos existieran, que quedaron sin `collected_at` a
    propósito). Restarlas fabricaría un neto negativo que ningún peso respalda.
    """
    _tx(org, student, 30000, collected_at=_at(2026, 7, 4))
    _tx(org, student, 99000, collected_at=None, refunded_at=_at(2026, 7, 6),
        refunded_amount=99000, status='refunded')

    data = build_revenue_report(_scope(org))

    assert data['totals']['gross'] == 30000
    assert data['totals']['refunds'] == 0
    assert data['totals']['net'] == 30000
    assert data['totals']['refunds_count'] == 0
    assert _bucket(data, '2026-07-06')['refunds'] == 0


def test_a_refund_is_charged_to_the_period_in_which_it_happened_not_to_the_sale(org, student):
    """BASE CAJA. Un cobro de junio devuelto en julio resta en JULIO y no reabre junio: el
    número de un período ya informado no puede cambiar después. La consecuencia legítima es
    que julio cierre con neto NEGATIVO — eso no es un error de cálculo, es plata que salió
    de la caja en julio."""
    _tx(org, student, 40000, collected_at=_at(2026, 6, 20), refunded_at=_at(2026, 7, 8),
        refunded_amount=40000, status='refunded')

    july = build_revenue_report(_scope(org))
    june = build_revenue_report(_scope(org, date_from=date(2026, 6, 1),
                                       date_to=date(2026, 6, 30)))

    assert july['totals'] == {'gross': 0, 'refunds': 40000, 'net': -40000,
                              'payments_count': 0, 'refunds_count': 1}
    assert june['totals']['gross'] == 40000
    assert june['totals']['refunds'] == 0      # junio NO se reabre
    assert june['totals']['net'] == 40000


def test_an_approved_transaction_without_collected_at_is_not_counted_as_gross(org, student):
    """El bruto sale de `collected_at` y de NINGÚN otro lado. `status` es pisable —una
    devolución lo reescribe y borra el rastro del cobro—, así que el reporte no lo consulta:
    una fila `approved` sin `collected_at` no es un ingreso datado y no puede caer en un
    período."""
    _tx(org, student, 50000, collected_at=None, status='approved')

    data = build_revenue_report(_scope(org))

    assert data['totals']['gross'] == 0
    assert data['totals']['payments_count'] == 0


def test_manual_methods_publish_their_refunds_explicitly_in_zero(org, membership):
    """Efectivo y transferencia no tienen mecanismo de devolución, pero las columnas viajan
    igual en 0: el front dibuja la misma resta en las tres filas, y un 0 declarado dice "no
    hubo" mientras que una clave ausente diría "no sé"."""
    _manual(org, membership, 10000, ManualPayment.METHOD_CASH, _at(2026, 7, 2))
    _manual(org, membership, 25000, ManualPayment.METHOD_TRANSFER, _at(2026, 7, 9))

    data = build_revenue_report(_scope(org))

    cash = _method_row(data, ManualPayment.METHOD_CASH)
    transfer = _method_row(data, ManualPayment.METHOD_TRANSFER)
    assert (cash['gross'], cash['refunds'], cash['net']) == (10000, 0, 10000)
    assert (transfer['gross'], transfer['refunds'], transfer['net']) == (25000, 0, 25000)
    assert cash['refunds_count'] == 0 and transfer['refunds_count'] == 0


def test_every_method_is_published_even_when_they_are_all_in_zero(org):
    """Sin filtro de método van TODAS las filas siempre. Omitir la fila de un método sin
    movimiento se leería como "este gimnasio no cobra así", que es otra afirmación.

    La ultima fila (`unknown`) no es un caso borde decorativo: son los cobros manuales
    anteriores a P3.2, que tienen `method=''` en producción y son plata real. Ver
    `test_reports_unknown_method.py`."""
    data = build_revenue_report(_scope(org))

    assert [row['method'] for row in data['by_method']] == [
        METHOD_MERCADOPAGO, ManualPayment.METHOD_CASH, ManualPayment.METHOD_TRANSFER,
        ManualPayment.METHOD_CARD, ManualPayment.METHOD_CHECK,
        METHOD_UNKNOWN]
    assert [row['label'] for row in data['by_method']] == [
        'MercadoPago', 'Efectivo', 'Transferencia', 'Tarjeta', 'Cheque',
        'Sin método registrado']
    assert all(row['gross'] == 0 and row['refunds'] == 0 and row['net'] == 0
               for row in data['by_method'])
    assert data['totals'] == {'gross': 0, 'refunds': 0, 'net': 0, 'payments_count': 0,
                              'refunds_count': 0}


# --------------------------------------------------------------------------------------
# B. Aislamiento: organización y sucursal
# --------------------------------------------------------------------------------------

def test_the_money_of_another_organization_never_appears_in_any_level(org, other_org,
                                                                     make_user, student,
                                                                     membership):
    """Regla 1 del backend: el reporte filtra por `organization_id` en las DOS tablas. Un
    cobro del gimnasio vecino no puede asomar ni en los totales, ni en `by_method`, ni en un
    punto de la serie."""
    foreign_student = make_user('stu-b', organization=other_org, role='student')
    foreign_membership = _membership(foreign_student, _plan(other_org))
    _tx(other_org, foreign_student, 80000, collected_at=_at(2026, 7, 3))
    _tx(other_org, foreign_student, 80000, collected_at=_at(2026, 7, 3),
        refunded_at=_at(2026, 7, 4), refunded_amount=80000, status='refunded')
    _manual(other_org, foreign_membership, 70000, ManualPayment.METHOD_CASH, _at(2026, 7, 3))
    _tx(org, student, 1000, collected_at=_at(2026, 7, 3))
    _manual(org, membership, 2000, ManualPayment.METHOD_TRANSFER, _at(2026, 7, 3))

    data = build_revenue_report(_scope(org))

    assert data['totals'] == {'gross': 3000, 'refunds': 0, 'net': 3000,
                              'payments_count': 2, 'refunds_count': 0}
    assert _method_row(data, METHOD_MERCADOPAGO)['gross'] == 1000
    assert _method_row(data, ManualPayment.METHOD_CASH)['gross'] == 0
    assert _bucket(data, '2026-07-03')['gross'] == 3000
    assert _bucket(data, '2026-07-04')['refunds'] == 0


def test_the_branch_filter_counts_only_that_branch_and_leaves_out_the_rows_without_branch(
        org, student, membership):
    """El filtro por sede se aplica a las dos tablas. Y las filas con `branch` NULL —plan
    global o fila anterior a esas columnas— quedan AFUERA: ahí NULL significa "sin dato", no
    "todas las sedes", así que repartirla entre las sedes sería inventar de dónde salió esa
    plata. Consecuencia asumida y documentada: los reportes por sede NO suman el de la org."""
    centro = Branch.objects.create(organization=org, name='Centro')
    norte = Branch.objects.create(organization=org, name='Norte')
    _tx(org, student, 10000, collected_at=_at(2026, 7, 3), branch=centro)
    _tx(org, student, 5000, collected_at=_at(2026, 7, 3), refunded_at=_at(2026, 7, 5),
        refunded_amount=5000, branch=centro, status='refunded')
    _tx(org, student, 90000, collected_at=_at(2026, 7, 3), branch=norte)
    _tx(org, student, 7000, collected_at=_at(2026, 7, 3), branch=None)
    _manual(org, membership, 3000, ManualPayment.METHOD_CASH, _at(2026, 7, 3), branch=centro)
    _manual(org, membership, 4000, ManualPayment.METHOD_CASH, _at(2026, 7, 3), branch=norte)

    centro_data = build_revenue_report(_scope(org, branch=centro))
    norte_data = build_revenue_report(_scope(org, branch=norte))
    whole_org = build_revenue_report(_scope(org))

    assert centro_data['filters']['branch_id'] == centro.id
    assert centro_data['filters']['branch_name'] == 'Centro'
    assert centro_data['totals'] == {'gross': 18000, 'refunds': 5000, 'net': 13000,
                                     'payments_count': 3, 'refunds_count': 1}
    assert _method_row(centro_data, ManualPayment.METHOD_CASH)['gross'] == 3000
    assert norte_data['totals']['gross'] == 94000        # no arrastra nada de Centro
    # La fila sin sede SÍ está en el total de la organización —es plata real, solo que sin
    # sede registrada—, y por eso las dos sedes no lo suman. Es la brecha documentada.
    assert whole_org['totals']['gross'] == 119000
    assert (centro_data['totals']['gross'] + norte_data['totals']['gross']
            == whole_org['totals']['gross'] - 7000)


# --------------------------------------------------------------------------------------
# C. Filtro por método
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize('method,expected_gross,expected_label', [
    (METHOD_MERCADOPAGO, 10000, 'MercadoPago'),
    (ManualPayment.METHOD_CASH, 20000, 'Efectivo'),
    (ManualPayment.METHOD_TRANSFER, 30000, 'Transferencia'),
])
def test_filtering_by_method_publishes_only_that_method(org, student, membership, method,
                                                        expected_gross, expected_label):
    """Con `method` puesto, `by_method` trae UNA fila y los totales son los de ese método —no
    un subtotal dentro del total de la org—. Los tres valores se recorren para que el catálogo
    de métodos no pueda divergir en silencio del de `views_reports`."""
    _tx(org, student, 10000, collected_at=_at(2026, 7, 3))
    _manual(org, membership, 20000, ManualPayment.METHOD_CASH, _at(2026, 7, 3))
    _manual(org, membership, 30000, ManualPayment.METHOD_TRANSFER, _at(2026, 7, 3))

    data = build_revenue_report(_scope(org), method=method)

    assert [row['method'] for row in data['by_method']] == [method]
    assert data['totals']['gross'] == expected_gross
    assert data['totals']['net'] == expected_gross
    assert data['filters']['method'] == method
    assert data['filters']['method_label'] == expected_label
    assert _bucket(data, '2026-07-03')['gross'] == expected_gross


def test_without_a_method_filter_the_filters_payload_says_so_explicitly(org):
    """`method`/`method_label` en `None` y no ausentes: el front lee siempre las mismas
    claves para decidir si está mirando un método o el consolidado."""
    data = build_revenue_report(_scope(org))

    assert data['filters']['method'] is None
    assert data['filters']['method_label'] is None


# --------------------------------------------------------------------------------------
# D. Comparación con el período anterior
# --------------------------------------------------------------------------------------

def test_the_comparison_uses_the_previous_window_of_the_same_length(org, student):
    """El período anterior son los MISMOS días inmediatamente antes (31 días para un julio
    completo → 31 de mayo a 30 de junio). Delta y porcentaje se calculan sobre esa ventana, o
    el número mediría la diferencia de largo del período y no el movimiento del negocio."""
    _tx(org, student, 30000, collected_at=_at(2026, 7, 10))
    _tx(org, student, 10000, collected_at=_at(2026, 6, 15))     # cae en la ventana anterior
    _tx(org, student, 999000, collected_at=_at(2026, 5, 1))     # fuera de las dos ventanas

    data = build_revenue_report(_scope(org))

    assert data['previous']['period']['date_from'] == '2026-05-31'
    assert data['previous']['period']['date_to'] == '2026-06-30'
    assert data['previous']['totals']['gross'] == 10000
    assert data['previous']['totals']['net'] == 10000
    assert data['comparison']['gross_delta'] == 20000
    assert data['comparison']['gross_delta_pct'] == 200.0
    assert data['comparison']['net_delta'] == 20000
    assert data['comparison']['net_delta_pct'] == 200.0


def test_the_percentage_is_none_when_the_previous_period_was_zero(org, student):
    """`None` y NO 0 ni 100: no hay porcentaje de crecimiento sobre una base inexistente, y
    un 100 % ahí haría que la UI dibuje un crecimiento inventado. El delta absoluto sí
    existe."""
    _tx(org, student, 30000, collected_at=_at(2026, 7, 10))

    data = build_revenue_report(_scope(org))

    assert data['previous']['totals']['gross'] == 0
    assert data['comparison']['gross_delta'] == 30000
    assert data['comparison']['gross_delta_pct'] is None
    assert data['comparison']['net_delta_pct'] is None


def test_the_previous_period_respects_the_method_filter(org, student, membership):
    """El período anterior se mide con el MISMO filtro de método. Si comparara el efectivo de
    julio contra TODO junio, el delta sería negativo por construcción."""
    _manual(org, membership, 5000, ManualPayment.METHOD_CASH, _at(2026, 7, 10))
    _manual(org, membership, 4000, ManualPayment.METHOD_CASH, _at(2026, 6, 15))
    _tx(org, student, 500000, collected_at=_at(2026, 6, 15))   # otro método: no cuenta

    data = build_revenue_report(_scope(org), method=ManualPayment.METHOD_CASH)

    assert data['previous']['totals']['gross'] == 4000
    assert data['comparison']['gross_delta'] == 1000


# --------------------------------------------------------------------------------------
# E. Serie
# --------------------------------------------------------------------------------------

def test_the_series_has_one_point_per_day_of_the_range_filled_with_zeros(org, student):
    """Un día sin ingresos es un DATO, no un hueco: la serie trae todos los buckets del rango,
    en orden, con ceros donde no hubo movimiento. Sin el relleno, el gráfico uniría el 2 con
    el 5 y dibujaría una pendiente que nadie facturó."""
    scope = _scope(org, date_from=date(2026, 7, 1), date_to=date(2026, 7, 5))
    _tx(org, student, 12000, collected_at=_at(2026, 7, 2))

    data = build_revenue_report(scope)

    assert [point['bucket'] for point in data['series']] == [
        '2026-07-01', '2026-07-02', '2026-07-03', '2026-07-04', '2026-07-05']
    assert [point['gross'] for point in data['series']] == [0, 12000, 0, 0, 0]
    assert all(point['refunds'] == 0 for point in data['series'])
    assert data['period']['days'] == 5
    assert data['period']['granularity'] == 'day'


def test_the_series_groups_by_month_over_a_long_range(org, student, membership):
    """Con granularidad `month` los buckets son `YYYY-MM` y siguen sin huecos: un rango de
    meses también necesita el mes en cero (un gimnasio cerrado en febrero es información)."""
    scope = _scope(org, date_from=date(2026, 1, 1), date_to=date(2026, 4, 30),
                   granularity='month')
    _tx(org, student, 100000, collected_at=_at(2026, 1, 15))
    _tx(org, student, 50000, collected_at=_at(2026, 3, 2), refunded_at=_at(2026, 4, 20),
        refunded_amount=50000, status='refunded')
    _manual(org, membership, 20000, ManualPayment.METHOD_CASH, _at(2026, 1, 31))

    data = build_revenue_report(scope)

    assert [point['bucket'] for point in data['series']] == [
        '2026-01', '2026-02', '2026-03', '2026-04']
    assert [point['gross'] for point in data['series']] == [120000, 0, 50000, 0]
    assert [point['refunds'] for point in data['series']] == [0, 0, 0, 50000]
    assert [point['net'] for point in data['series']] == [120000, 0, 50000, -50000]
    assert data['totals']['net'] == 120000


def test_a_payment_outside_the_range_does_not_enter_the_report(org, student):
    """Los bordes del rango son inclusivos y el día siguiente ya no cuenta."""
    scope = _scope(org, date_from=date(2026, 7, 1), date_to=date(2026, 7, 2))
    _tx(org, student, 1000, collected_at=_at(2026, 7, 1, hour=0))
    _tx(org, student, 2000, collected_at=_at(2026, 7, 2, hour=23))
    _tx(org, student, 9000, collected_at=_at(2026, 7, 3, hour=1))

    data = build_revenue_report(scope)

    assert data['totals']['gross'] == 3000
    assert len(data['series']) == 2


# --------------------------------------------------------------------------------------
# F. Export
# --------------------------------------------------------------------------------------

def test_the_export_spec_keeps_gross_refunds_and_net_in_separate_columns(org, student,
                                                                        membership):
    """El CSV muestra la MISMA resta que el JSON. Una sola columna de "ingresos" sería el
    único lugar del reporte donde la devolución queda escondida — y es justo el archivo que
    alguien después pega en una planilla."""
    scope = _scope(org, date_from=date(2026, 7, 1), date_to=date(2026, 7, 3))
    _tx(org, student, 20000, collected_at=_at(2026, 7, 1), refunded_at=_at(2026, 7, 2),
        refunded_amount=20000, status='refunded')
    _manual(org, membership, 5000, ManualPayment.METHOD_CASH, _at(2026, 7, 1))

    spec = revenue_export_spec(build_revenue_report(scope))

    assert spec['header'] == ['Período', 'Método', 'Bruto', 'Devoluciones', 'Neto',
                             'Cobros', 'Devoluciones (n)']
    # Un bloque por método (período completo) y un bloque por bucket de la serie: 6 + 3.
    assert len(spec['rows']) == 9
    by_method, series_rows = spec['rows'][:6], spec['rows'][6:]
    assert all(row[0] == '2026-07-01 a 2026-07-03' for row in by_method)
    assert ['MercadoPago', 20000, 20000, 0, 1, 1] == [by_method[0][1], *by_method[0][2:]]
    assert ['Efectivo', 5000, 0, 5000, 1, 0] == [by_method[1][1], *by_method[1][2:]]
    assert [row[0] for row in series_rows] == ['2026-07-01', '2026-07-02', '2026-07-03']
    assert [row[2:5] for row in series_rows] == [[25000, 0, 25000], [0, 20000, -20000],
                                                 [0, 0, 0]]
    # Las cantidades quedan VACÍAS en la serie: poner 0 al lado de un bruto positivo diría
    # "ese día no hubo cobros", una contradicción escrita en el archivo.
    assert all(row[5] == '' and row[6] == '' for row in series_rows)
    assert spec['total_row'] == ['TOTAL', 'Todos los métodos', 25000, 20000, 5000, 2, 1]


def test_the_export_labels_the_series_with_the_filtered_method(org, student):
    """Con filtro de método, la serie es de ESE método: rotularla "todos los métodos" sería
    falso en el archivo que el administrador archiva."""
    scope = _scope(org, date_from=date(2026, 7, 1), date_to=date(2026, 7, 1))
    _tx(org, student, 9000, collected_at=_at(2026, 7, 1))

    spec = revenue_export_spec(
        build_revenue_report(scope, method=METHOD_MERCADOPAGO))

    assert spec['rows'][-1][1] == 'MercadoPago'
    assert spec['total_row'][1] == 'MercadoPago'


# --------------------------------------------------------------------------------------
# G. Endpoint `GET /api/reports/revenue/`
# --------------------------------------------------------------------------------------

def test_via_http_the_gym_admin_gets_the_report_of_his_own_organization(
        api_client, org, other_org, admin, student, make_user, membership):
    """El endpoint no recibe `organization_id` por ningún lado: la organización es la del
    actor. Un cobro del gimnasio vecino no puede entrar por el query string."""
    foreign_student = make_user('stu-http-b', organization=other_org, role='student')
    _tx(other_org, foreign_student, 77000, collected_at=_at(2026, 7, 3))
    _tx(org, student, 11000, collected_at=_at(2026, 7, 3))
    _manual(org, membership, 4000, ManualPayment.METHOD_TRANSFER, _at(2026, 7, 4))
    api_client.force_authenticate(user=admin)

    resp = api_client.get(URL, {'date_from': '2026-07-01', 'date_to': '2026-07-31'})

    assert resp.status_code == 200
    assert resp.data['totals'] == {'gross': 15000, 'refunds': 0, 'net': 15000,
                                   'payments_count': 2, 'refunds_count': 0}
    assert resp.data['period']['date_from'] == '2026-07-01'
    assert len(resp.data['series']) == 31
    assert len(resp.data['by_method']) == 6


@pytest.mark.parametrize('role', ['manager', 'monitor', 'teacher', 'student'])
def test_via_http_no_role_other_than_gym_admin_can_read_the_revenue(api_client, org,
                                                                    make_user, role):
    """Plata AGREGADA es más sensible que una fila suelta: el reporte no puede ser más laxo
    que el recurso del que sale (`FinancialResourcePermission` ya excluye al manager)."""
    user = make_user(f'u-{role}', organization=org, role=role)
    api_client.force_authenticate(user=user)

    assert api_client.get(URL).status_code == 403


def test_via_http_the_superadmin_is_also_excluded(api_client, make_user):
    """No es un olvido: mismo criterio que `PaymentTransactionListView`. Darle el reporte al
    superadmin sería darle la facturación de todos los gimnasios en un endpoint, y sin
    organización propia no tendría alcance que scopear."""
    api_client.force_authenticate(user=make_user('root', organization=None,
                                                 role='superadmin'))

    assert api_client.get(URL).status_code == 403


def test_via_http_it_requires_authentication(api_client):
    assert api_client.get(URL).status_code == 401


def test_via_http_a_branch_of_another_organization_is_a_404(api_client, org, other_org,
                                                            admin):
    """404 y no 403: los ids son autoincrementales y adivinables, y un 403 confirmaría
    "existe, pero no es tuyo" — delataría la topología de sedes del vecino."""
    foreign_branch = Branch.objects.create(organization=other_org, name='Ajena')
    api_client.force_authenticate(user=admin)

    resp = api_client.get(URL, {'branch_id': foreign_branch.id})

    assert resp.status_code == 404


def test_via_http_an_invalid_method_is_rejected(api_client, org, admin):
    """El catálogo de métodos es cerrado: un valor cualquiera no puede devolver un reporte
    vacío que se lea como "no cobraste nada"."""
    api_client.force_authenticate(user=admin)

    resp = api_client.get(URL, {'method': 'bitcoin'})

    assert resp.status_code == 400
    assert 'method' in resp.data


def test_via_http_the_csv_export_shows_gross_refunds_and_net_separately(
        api_client, org, admin, student, membership):
    """`?export=csv` sale del MISMO cálculo que el JSON (mismo `_report_scope`, mismos datos),
    así que el archivo no puede divergir de la pantalla que el administrador está mirando."""
    _tx(org, student, 20000, collected_at=_at(2026, 7, 1), refunded_at=_at(2026, 7, 2),
        refunded_amount=20000, status='refunded')
    _manual(org, membership, 5000, ManualPayment.METHOD_CASH, _at(2026, 7, 1))
    api_client.force_authenticate(user=admin)

    resp = api_client.get(URL, {'date_from': '2026-07-01', 'date_to': '2026-07-03',
                                'export': 'csv'})

    assert resp.status_code == 200
    assert resp['Content-Type'].startswith('text/csv')
    body = resp.content.decode('utf-8-sig')
    assert 'Bruto,Devoluciones,Neto' in body
    assert 'MercadoPago,20000,20000,0,1,1' in body
    assert 'Efectivo,5000,0,5000,1,0' in body
    assert 'TOTAL,Todos los métodos,25000,20000,5000,2,1' in body
