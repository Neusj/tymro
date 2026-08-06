"""P3.4 · Pieza 0 — el cimiento de la reportería: alcance, períodos, buckets y plomería HTTP.

Cada reporte tiene su propio archivo de test. Acá se fija lo que COMPARTEN, y que por lo tanto
ninguno de ellos puede aflojar por su cuenta: la aritmética de `ReportScope`, el relleno de
buckets, y las guardas del único camino de entrada (`views_reports._report_scope`) — rol,
rango, granularidad, formato de export y el 404 anti-oráculo de la sucursal ajena.

La guarda de rol se prueba sobre LOS TRES endpoints en la misma tabla: es la clase de regla
que se agrega bien en un endpoint y se olvida en el que se sumó después. El tercero de la tabla
era `GET /api/reports/manual-payments/`, que se borró al construir el drill-down de ingresos;
su lugar lo toma la CAPA 2 de ese drill-down, que es la pantalla que lo reemplaza y el endpoint
de reportería más nuevo — justamente el que más riesgo tiene de haberse saltado una guarda.
"""
from datetime import date

import pytest

from core.services import reports_base
from core.services.reports_base import (GRANULARITY_DAY, GRANULARITY_MONTH, MAX_PERIOD_DAYS,
                                        METHOD_CASH, ReportScope, bucket_keys, pct_delta)

pytestmark = pytest.mark.django_db

REVENUE_URL = '/api/reports/revenue/'
REVENUE_PAYMENTS_URL = '/api/reports/revenue/payments/'
OCCUPANCY_URL = '/api/reports/occupancy/'
ALL_URLS = (REVENUE_URL, REVENUE_PAYMENTS_URL, OCCUPANCY_URL)

#: Parámetros SIN LOS CUALES el endpoint no puede responder, por endpoint. Hoy solo el listado
#: del drill-down tiene uno (`method` es obligatorio ahí: ese listado explica UNA fila de
#: `by_method` y "todos los medios" no es una fila). Se inyectan en las guardas compartidas para
#: que lo que se mida sea la guarda y no la falta del parámetro.
REQUIRED_PARAMS = {REVENUE_PAYMENTS_URL: {'method': METHOD_CASH}}


def _get(api_client, url, params=None):
    return api_client.get(url, {**REQUIRED_PARAMS.get(url, {}), **(params or {})})


def _scope(date_from, date_to, granularity=GRANULARITY_DAY, organization_id=1, branch=None):
    return ReportScope(organization_id=organization_id, date_from=date_from, date_to=date_to,
                       granularity=granularity, branch=branch)


# --------------------------------------------------------------------------------------
# A. Aritmética del alcance (pura, sin BD)
# --------------------------------------------------------------------------------------

def test_the_previous_period_has_exactly_the_same_length_in_days():
    """La comparación tiene que ser contra una ventana del MISMO tamaño.

    Si el período anterior fuera "el mes calendario anterior", el delta de un rango de 10 días
    mediría la diferencia de días y no la del negocio."""
    scope = _scope(date(2026, 7, 10), date(2026, 7, 19))    # 10 días
    previous = scope.previous()

    assert previous.days == scope.days == 10
    assert previous.date_to == date(2026, 7, 9)              # pegado, sin solaparse
    assert previous.date_from == date(2026, 6, 30)           # cruza el mes, y está bien


def test_the_previous_period_keeps_the_branch_and_the_granularity():
    """El período anterior compara lo MISMO: misma sede, misma escala."""
    scope = _scope(date(2026, 7, 1), date(2026, 7, 31), granularity=GRANULARITY_MONTH)
    previous = scope.previous()

    assert previous.granularity == GRANULARITY_MONTH
    assert previous.branch is scope.branch
    assert previous.organization_id == scope.organization_id


def test_day_buckets_have_no_gaps():
    """Un día sin movimiento es un DATO (cero), no una ausencia de dato.

    Sin el relleno, la línea del gráfico une el 1 con el 4 y dibuja una pendiente que nadie
    facturó."""
    keys = bucket_keys(_scope(date(2026, 7, 1), date(2026, 7, 4)))

    assert keys == ['2026-07-01', '2026-07-02', '2026-07-03', '2026-07-04']


def test_month_buckets_cross_the_year_boundary():
    """El bucket mensual se calcula sobre (año, mes) y no sumando 30 días."""
    keys = bucket_keys(_scope(date(2026, 11, 15), date(2027, 2, 3),
                              granularity=GRANULARITY_MONTH))

    assert keys == ['2026-11', '2026-12', '2027-01', '2027-02']


def test_a_single_day_range_produces_exactly_one_bucket():
    assert bucket_keys(_scope(date(2026, 7, 3), date(2026, 7, 3))) == ['2026-07-03']


def test_the_granularity_falls_to_month_only_for_long_ranges():
    """Una serie de 365 puntos no se lee en un gráfico; un trimestre día por día sí."""
    assert reports_base.resolve_granularity('auto', date(2026, 1, 1), date(2026, 2, 1)) == GRANULARITY_DAY
    assert reports_base.resolve_granularity('auto', date(2026, 1, 1), date(2026, 12, 31)) == GRANULARITY_MONTH
    # Lo explícito gana sobre el largo del rango.
    assert reports_base.resolve_granularity('day', date(2026, 1, 1), date(2026, 12, 31)) == GRANULARITY_DAY
    assert reports_base.resolve_granularity('month', date(2026, 7, 1), date(2026, 7, 2)) == GRANULARITY_MONTH


def test_the_percentage_delta_is_none_when_there_is_no_base():
    """`None` y NO 0 ni 100: "creció infinito" no es un número que se pueda mostrar, y un
    100 % haría que la UI dibuje un crecimiento inventado sobre una base inexistente."""
    assert pct_delta(50000, 0) is None
    assert pct_delta(0, 0) is None
    assert pct_delta(150, 100) == 50.0
    assert pct_delta(50, 100) == -50.0


# --------------------------------------------------------------------------------------
# B. Guardas del camino de entrada (HTTP)
# --------------------------------------------------------------------------------------

@pytest.fixture
def org_a(make_organization):
    return make_organization('Gym A')


@pytest.fixture
def org_b(make_organization):
    return make_organization('Gym B')


@pytest.fixture
def gym_admin(org_a, make_user):
    return make_user('admin-a', organization=org_a, role='gym_admin')


@pytest.mark.parametrize('url', ALL_URLS)
def test_an_anonymous_request_is_rejected(api_client, url):
    assert _get(api_client, url).status_code == 401


@pytest.mark.parametrize('url', ALL_URLS)
@pytest.mark.parametrize('role', ['superadmin', 'manager', 'monitor', 'teacher', 'student'])
def test_only_gym_admin_can_read_any_report(api_client, org_a, make_user, url, role):
    """La superficie de reportería es EXCLUSIVA de gym_admin, y en los tres endpoints.

    `manager` incluido, ni de lectura: es la línea que ya traza `FinancialResourcePermission`
    para pagos y planes, y un agregado de plata no puede ser más laxo que las filas de las que
    sale. `superadmin` también fuera, por el mismo criterio que
    `PaymentTransactionListView`: sería la facturación de todos los gimnasios en un endpoint.
    """
    org = None if role == 'superadmin' else org_a
    api_client.force_authenticate(user=make_user('u', organization=org, role=role))

    assert _get(api_client, url).status_code == 403


@pytest.mark.parametrize('url', ALL_URLS)
def test_a_gym_admin_gets_its_report(api_client, gym_admin, url):
    """Sin datos el reporte responde 200 con ceros, no 404 ni 500: un gimnasio nuevo tiene
    que poder abrir la pantalla."""
    api_client.force_authenticate(user=gym_admin)
    resp = _get(api_client, url)

    assert resp.status_code == 200
    assert resp.data['period']['date_from']
    assert resp.data['filters']['branch_id'] is None


@pytest.mark.parametrize('url', ALL_URLS)
def test_a_branch_from_another_organization_is_indistinguishable_from_a_missing_one(
        api_client, gym_admin, org_b, url):
    """404 y NO 403: los ids de sede son autoincrementales y adivinables, y un 403
    confirmaría "esa sede existe, pero es de otro gimnasio" — delataría la topología de sedes
    de otro tenant. Y de paso: el filtro de sede NO es un camino para leer otra org."""
    from core.models import Branch
    foreign = Branch.objects.create(organization=org_b, name='Sede ajena')
    api_client.force_authenticate(user=gym_admin)

    assert _get(api_client, url, {'branch_id': foreign.id}).status_code == 404


@pytest.mark.parametrize('url', ALL_URLS)
def test_the_organization_never_travels_in_the_request(api_client, gym_admin, org_b, url):
    """Un `organization_id` en el query string se IGNORA: la organización del reporte sale
    del actor y de ningún otro lugar (regla 1 de backend/CLAUDE.md, orden 8.3)."""
    api_client.force_authenticate(user=gym_admin)
    resp = _get(api_client, url, {'organization_id': org_b.id, 'organization': org_b.id})

    assert resp.status_code == 200


@pytest.mark.parametrize('url', ALL_URLS)
def test_a_malformed_date_is_a_400(api_client, gym_admin, url):
    api_client.force_authenticate(user=gym_admin)

    assert _get(api_client, url, {'date_from': '03-07-2026'}).status_code == 400
    assert _get(api_client, url, {'date_to': 'ayer'}).status_code == 400


@pytest.mark.parametrize('url', ALL_URLS)
def test_an_inverted_range_is_a_400(api_client, gym_admin, url):
    api_client.force_authenticate(user=gym_admin)
    resp = _get(api_client, url, {'date_from': '2026-07-31', 'date_to': '2026-07-01'})

    assert resp.status_code == 400


@pytest.mark.parametrize('url', ALL_URLS)
def test_a_range_longer_than_the_cap_is_a_400(api_client, gym_admin, url):
    """El tope no es capricho: el peor caso de un reporte de 10 años recorre todo el histórico
    de pagos del tenant dentro de una request de gunicorn con `--timeout 30`."""
    api_client.force_authenticate(user=gym_admin)
    resp = _get(api_client, url, {'date_from': '2016-01-01', 'date_to': '2026-01-01'})

    assert resp.status_code == 400
    # Y el límite exacto sí pasa.
    from datetime import timedelta
    start = date(2026, 1, 1)
    ok = _get(api_client, url,
              {'date_from': start.isoformat(),
               'date_to': (start + timedelta(days=MAX_PERIOD_DAYS - 1)).isoformat()})
    assert ok.status_code == 200


@pytest.mark.parametrize('url', ALL_URLS)
def test_a_date_before_the_floor_is_a_400_and_not_a_500(api_client, gym_admin, url):
    """`ReportScope.previous()` resta un día a `date_from` para armar el período de
    comparación, y con el año 1 esa resta levanta `OverflowError` —que DRF no traduce—, o sea un
    500 en un endpoint de dinero. El piso lo corta antes, con un mensaje que dice qué está mal."""
    api_client.force_authenticate(user=gym_admin)

    assert _get(api_client, url, {'date_from': '0001-01-01',
                                  'date_to': '0001-01-01'}).status_code == 400
    assert _get(api_client, url, {'date_from': '1999-12-31',
                                  'date_to': '2000-01-01'}).status_code == 400
    # Y el piso exacto sí pasa.
    assert _get(api_client, url, {'date_from': '2000-01-01',
                                  'date_to': '2000-01-31'}).status_code == 200


@pytest.mark.parametrize('url', ALL_URLS)
def test_an_unknown_granularity_is_a_400_and_not_a_silent_fallback(api_client, gym_admin, url):
    """Pedir semanas y recibir meses con 200 dibuja un gráfico con la escala equivocada y
    nadie se enteraría."""
    api_client.force_authenticate(user=gym_admin)

    assert _get(api_client, url, {'granularity': 'week'}).status_code == 400
    assert _get(api_client, url, {'granularity': 'auto'}).status_code == 200


@pytest.mark.parametrize('url', ALL_URLS)
def test_an_unknown_export_format_is_a_400_and_not_a_csv(api_client, gym_admin, url):
    """Pedir `pdf` y recibir un csv con 200 es un fallo silencioso, y el archivo que baja es
    plata que alguien va a pegar en una planilla."""
    api_client.force_authenticate(user=gym_admin)

    assert _get(api_client, url, {'export': 'pdf'}).status_code == 400


@pytest.mark.parametrize('url', ALL_URLS)
@pytest.mark.parametrize('fmt,content_type', [
    ('csv', 'text/csv'),
    ('xlsx', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
])
def test_the_export_uses_the_same_scope_as_the_json(api_client, gym_admin, url, fmt, content_type):
    """El export no es un endpoint aparte: mismo alcance, mismos datos. Si fueran dos
    caminos, el CSV podría divergir del gráfico que el administrador está mirando."""
    api_client.force_authenticate(user=gym_admin)
    resp = _get(api_client, url, {'export': fmt})

    assert resp.status_code == 200
    assert content_type in resp['Content-Type']
    assert 'attachment; filename=' in resp['Content-Disposition']


@pytest.mark.parametrize('url', ALL_URLS)
def test_a_report_is_read_only(api_client, gym_admin, url):
    """Ningún reporte acepta escritura: no es un recurso, es una lectura agregada."""
    api_client.force_authenticate(user=gym_admin)

    assert api_client.post(url, {}, format='json').status_code == 405
    assert api_client.delete(url).status_code == 405
