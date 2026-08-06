"""P3.4 — la plata cobrada SIN instrumento declarado (`ManualPayment.method=''`) no se cae.

POR QUÉ ESTE ARCHIVO EXISTE APARTE: es la regresión de un bug de dinero que apareció durante
la construcción de P3.4, y el mismo error se cometió DOS VECES de forma independiente en los
dos reportes de plata. La trampa es que `ManualPayment.method` tiene `choices` de dos valores,
así que filtrar por `method__in=('cash', 'transfer')` se lee como "todos los instrumentos"
—pero no lo es—: la columna nació en P3.2 con `blank=True, default=''` y su migración NO hizo
backfill a propósito, porque de los cobros de 8.2/8.3 no se sabe con qué se pagaron. Esas
filas están HOY en producción, son cobros que el gimnasio recibió, y con ese filtro
desaparecían del ingreso bruto: el reporte informaba menos plata de la que entró.

Los tests están juntos y no repartidos en `test_reports_revenue.py` /
`test_reports_manual.py` para que se lean como una sola afirmación de producto: NINGÚN reporte
puede perder plata cobrada por no saber cómo se cobró. Si alguien vuelve a acotar un filtro de
método, este archivo es el que lo frena.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from core.models import ManualPayment, Plan, StudentPlan
from core.services.reports_base import (GRANULARITY_DAY, METHOD_CASH, METHOD_UNKNOWN,
                                        ReportScope)
from core.services.reports_manual import build_manual_payments_report
from core.services.reports_revenue import build_revenue_report

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()
REVENUE_URL = '/api/reports/revenue/'
MANUAL_URL = '/api/reports/manual-payments/'


@pytest.fixture
def org(make_organization):
    return make_organization('Gym legacy')


@pytest.fixture
def scope(org):
    return ReportScope(organization_id=org.id, date_from=TODAY - timedelta(days=2),
                       date_to=TODAY, granularity=GRANULARITY_DAY)


def _membership(org, student):
    plan = Plan.objects.create(organization=org, name='Pack', plan_type='pack',
                               total_classes=10, unlimited_classes=False, duration_days=30,
                               price=30000)
    return StudentPlan.objects.create(
        user=student, plan=plan, organization_id=org.id,
        start_date=TODAY - timedelta(days=1), end_date=TODAY + timedelta(days=20),
        total_classes=10, final_price=30000)


def _manual(org, membership, admin, amount, method):
    """Cobro manual con el instrumento CRUDO de la columna (`''` = fila legacy).

    Se crea con `objects.create` y no por el servicio a propósito: el servicio (P3.2) exige
    `cash`/`transfer`, así que la fila con `''` solo se puede fabricar así — que es exactamente
    la forma en que existe en producción, escrita antes de que la columna tuviera choices.
    """
    return ManualPayment.objects.create(
        organization=org, student_plan=membership, amount=Decimal(amount), method=method,
        recorded_by=admin, recorded_at=timezone.now())


@pytest.fixture
def legacy_scenario(org, make_user):
    """$10.000 en efectivo declarado + $7.000 legacy sin instrumento. Total cobrado: $17.000."""
    admin = make_user('adm', organization=org, role='gym_admin')
    student = make_user('stu', organization=org, role='student')
    membership = _membership(org, student)
    _manual(org, membership, admin, 10000, ManualPayment.METHOD_CASH)
    _manual(org, membership, admin, 7000, '')      # la fila que se caía del reporte
    return admin, membership


# --------------------------------------------------------------------------------------
# A. Reporte de ingresos
# --------------------------------------------------------------------------------------

def test_the_revenue_report_counts_a_payment_with_no_declared_method_as_gross(
        scope, legacy_scenario):
    """EL BUG. Con el filtro acotado a cash/transfer, el bruto daba 10.000 y el gimnasio había
    cobrado 17.000: el reporte informaba $7.000 menos de los que entraron a la caja."""
    data = build_revenue_report(scope)

    assert data['totals']['gross'] == 17000
    assert data['totals']['net'] == 17000
    assert data['totals']['payments_count'] == 2


def test_the_unknown_method_has_its_own_row_and_the_rows_add_up_to_the_total(
        scope, legacy_scenario):
    """La plata no se esconde dentro de "Efectivo": tiene su propia fila, con nombre.

    Y los totales siguen siendo la SUMA de las filas publicadas — si `unknown` sumara al total
    sin aparecer como fila, el reporte no cuadraría consigo mismo y el front dibujaría un
    desglose que no llega al total."""
    data = build_revenue_report(scope)
    rows = {row['method']: row for row in data['by_method']}

    assert rows[METHOD_UNKNOWN]['gross'] == 7000
    assert rows[METHOD_UNKNOWN]['label'] == 'Sin método registrado'
    assert rows[METHOD_CASH]['gross'] == 10000
    assert sum(row['gross'] for row in data['by_method']) == data['totals']['gross']


def test_the_unknown_row_is_published_even_at_zero(scope, org, make_user):
    """Un gimnasio sin filas legacy ve la fila en 0. Un 0 declarado dice "no hay"; una fila
    ausente dice "no sé", y acá sí se sabe."""
    data = build_revenue_report(scope)
    methods = [row['method'] for row in data['by_method']]

    assert METHOD_UNKNOWN in methods
    assert next(r for r in data['by_method'] if r['method'] == METHOD_UNKNOWN)['gross'] == 0


def test_the_series_of_the_revenue_report_includes_the_unknown_money(scope, legacy_scenario):
    """El gráfico tiene que sumar lo mismo que la tarjeta: si la serie perdiera esos $7.000,
    la línea contaría una historia distinta al KPI de arriba."""
    data = build_revenue_report(scope)

    assert sum(point['gross'] for point in data['series']) == 17000


def test_the_revenue_report_can_isolate_the_unknown_method(scope, legacy_scenario):
    """`method=unknown` sirve para auditar justo esas filas históricas."""
    data = build_revenue_report(scope, method=METHOD_UNKNOWN)

    assert data['totals']['gross'] == 7000
    assert [row['method'] for row in data['by_method']] == [METHOD_UNKNOWN]
    assert data['filters']['method_label'] == 'Sin método registrado'


# --------------------------------------------------------------------------------------
# B. Reporte de pagos manuales
# --------------------------------------------------------------------------------------

def test_the_manual_report_lists_the_legacy_payment_instead_of_hiding_it(scope, legacy_scenario):
    """Este reporte es la ÚNICA lectura que existe de `ManualPayment`: si acá no está, para el
    gimnasio ese cobro no existe en ninguna pantalla."""
    data = build_manual_payments_report(scope)
    methods = [row['method'] for row in data['rows']]

    assert len(data['rows']) == 2
    assert METHOD_UNKNOWN in methods
    # Nunca `''` en el cable: una celda vacía es indistinguible de un dato perdido.
    assert '' not in methods
    unknown_row = next(r for r in data['rows'] if r['method'] == METHOD_UNKNOWN)
    assert unknown_row['method_label'] == 'Sin método registrado'


def test_the_manual_totals_keep_the_stacked_bar_identity(scope, legacy_scenario):
    """`total == cash + transfer + unknown`, con el tercer término. Es la identidad que sostiene
    la barra apilada del frontend Y la garantía de que no se cae plata del reporte."""
    totals = build_manual_payments_report(scope)['totals']

    assert totals['cash'] == 10000
    assert totals['transfer'] == 0
    assert totals['unknown'] == 7000
    assert totals['total'] == totals['cash'] + totals['transfer'] + totals['unknown'] == 17000
    assert totals['count'] == 2
    assert totals['unknown_count'] == 1


def test_the_manual_series_keeps_the_same_identity_per_bucket(scope, legacy_scenario):
    data = build_manual_payments_report(scope)

    for point in data['series']:
        assert point['total'] == point['cash'] + point['transfer'] + point['unknown']
    assert sum(point['total'] for point in data['series']) == 17000


# --------------------------------------------------------------------------------------
# C. Los dos reportes cuentan LA MISMA plata manual
# --------------------------------------------------------------------------------------

def test_both_money_reports_agree_on_the_manual_total(scope, legacy_scenario):
    """Cruce que habría cazado el bug incluso si solo uno de los dos módulos lo tuviera:
    el bruto manual del reporte de ingresos y el total del reporte de pagos manuales son la
    misma plata mirada desde dos pantallas, y un administrador va a comparar los dos números."""
    revenue = build_revenue_report(scope)
    manual = build_manual_payments_report(scope)
    manual_gross_in_revenue = sum(
        row['gross'] for row in revenue['by_method'] if row['method'] != 'mercadopago')

    assert manual_gross_in_revenue == manual['totals']['total']


def test_the_unknown_method_is_accepted_by_both_endpoints(api_client, legacy_scenario, org):
    """La lista de medios que valida la view es la MISMA que usa el cálculo: si divergieran,
    el filtro rechazaría con 400 un valor que el reporte sabe calcular."""
    admin, _ = legacy_scenario
    api_client.force_authenticate(user=admin)
    params = {'date_from': (TODAY - timedelta(days=2)).isoformat(),
              'date_to': TODAY.isoformat(), 'method': METHOD_UNKNOWN}

    revenue = api_client.get(REVENUE_URL, params)
    manual = api_client.get(MANUAL_URL, params)

    assert revenue.status_code == 200
    assert revenue.data['totals']['gross'] == 7000
    assert manual.status_code == 200
    assert manual.data['totals']['unknown'] == 7000
