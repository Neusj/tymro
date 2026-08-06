"""P3.4 — la plata cobrada SIN instrumento declarado (`ManualPayment.method=''`) no se cae.

POR QUÉ ESTE ARCHIVO EXISTE APARTE: es la regresión de un bug de dinero que apareció durante
la construcción de P3.4, y el mismo error se cometió DOS VECES de forma independiente en los
dos reportes de plata que había entonces. La trampa es que `ManualPayment.method` tiene
`choices` de dos valores, así que filtrar por `method__in=('cash', 'transfer')` se lee como
"todos los instrumentos" —pero no lo es—: la columna nació en P3.2 con `blank=True, default=''`
y su migración NO hizo backfill a propósito, porque de los cobros de 8.2/8.3 no se sabe con qué
se pagaron. Esas filas están HOY en producción, son cobros que el gimnasio recibió, y con ese
filtro desaparecían del ingreso bruto: el reporte informaba menos plata de la que entró.

QUÉ CAMBIÓ Y QUÉ NO: el segundo reporte (`GET /api/reports/manual-payments/`) se borró al
construir el drill-down de ingresos, y la pantalla que lo reemplaza es la CAPA 2 de ese
drill-down. La afirmación de producto es la misma y por eso este archivo NO se borró con él:
NINGUNA pantalla puede perder plata cobrada por no saber cómo se cobró. Ahora se verifica sobre
las capas 1 y 2 —que además están a un clic de distancia, así que un descuadre entre ellas es
visible para el administrador—. Si alguien vuelve a acotar un filtro de método, este archivo es
el que lo frena.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from core.models import ManualPayment, Plan, StudentPlan
from core.services.reports_base import (GRANULARITY_DAY, METHOD_CASH, METHOD_UNKNOWN,
                                        ReportScope)
from core.services.reports_revenue import build_revenue_report
from core.services.reports_revenue_detail import build_revenue_payments_report

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()
REVENUE_URL = '/api/reports/revenue/'
REVENUE_PAYMENTS_URL = '/api/reports/revenue/payments/'


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
# B. Capa 2 del drill-down (el listado que reemplazó al reporte de pagos manuales)
# --------------------------------------------------------------------------------------

def test_the_drilldown_lists_the_legacy_payment_instead_of_hiding_it(scope, legacy_scenario):
    """Esta es la ÚNICA lectura que existe de `ManualPayment` desde que se borró su reporte:
    si acá no está, para el gimnasio ese cobro no existe en ninguna pantalla."""
    data = build_revenue_payments_report(scope, METHOD_UNKNOWN)
    methods = [row['method'] for row in data['rows']]

    assert len(data['rows']) == 1
    assert methods == [METHOD_UNKNOWN]
    # Nunca `''` en el cable: una celda vacía es indistinguible de un dato perdido.
    assert '' not in methods
    assert data['rows'][0]['method_label'] == 'Sin método registrado'
    assert data['rows'][0]['amount'] == 7000


def test_the_drilldown_of_cash_does_not_swallow_the_legacy_row(scope, legacy_scenario):
    """El otro lado del mismo bug: la fila legacy no puede aparecer DENTRO de "Efectivo".

    Esconderla ahí sumaría bien el total pero le atribuiría al gimnasio un instrumento que
    nunca declaró — y borraría del producto la pregunta "¿con qué cobré estos $7.000?".
    """
    data = build_revenue_payments_report(scope, METHOD_CASH)

    assert [row['amount'] for row in data['rows']] == [10000]
    assert data['totals']['gross'] == 10000


# --------------------------------------------------------------------------------------
# C. Las dos capas cuentan LA MISMA plata
# --------------------------------------------------------------------------------------

def test_the_two_layers_agree_on_every_manual_method(scope, legacy_scenario):
    """Cruce que habría cazado el bug incluso si solo una de las dos capas lo tuviera.

    El administrador llega a la capa 2 haciendo CLIC sobre la fila de la capa 1, así que los dos
    números están literalmente uno detrás del otro en la pantalla: cualquier diferencia se lee
    como que el reporte está roto. Y en `unknown` es donde la diferencia aparecería primero.
    """
    revenue = build_revenue_report(scope)

    for row in revenue['by_method']:
        drilldown = build_revenue_payments_report(scope, row['method'])
        assert drilldown['totals']['gross'] == row['gross'], row['method']
        assert drilldown['totals']['payments_count'] == row['payments_count'], row['method']
        assert sum(r['amount'] for r in drilldown['rows']) == row['gross'], row['method']


def test_the_unknown_method_is_accepted_by_both_endpoints(api_client, legacy_scenario, org):
    """La lista de medios que valida la view es la MISMA que usa el cálculo: si divergieran,
    el filtro rechazaría con 400 un valor que el reporte sabe calcular."""
    admin, _ = legacy_scenario
    api_client.force_authenticate(user=admin)
    params = {'date_from': (TODAY - timedelta(days=2)).isoformat(),
              'date_to': TODAY.isoformat(), 'method': METHOD_UNKNOWN}

    revenue = api_client.get(REVENUE_URL, params)
    drilldown = api_client.get(REVENUE_PAYMENTS_URL, params)

    assert revenue.status_code == 200
    assert revenue.data['totals']['gross'] == 7000
    assert drilldown.status_code == 200
    assert drilldown.data['totals']['gross'] == 7000
    assert drilldown.data['filters']['method_label'] == 'Sin método registrado'
