"""Reporte de pagos manuales (P3.4 · Pieza 2) — `core/services/reports_manual.py`.

PRIMERA LECTURA que existe de `ManualPayment` (hasta P3.4 el modelo era solo-POST, ver
`test_manual_payment.py`). Este archivo cubre la capa de servicio (`build_manual_payments_
report`/`manual_payments_export_spec`) Y el endpoint HTTP `GET /api/reports/manual-payments/`
de punta a punta.

OJO con la sección B (HTTP): al momento de escribir esto, `core/urls.py` importa
`views_reports`, que a su vez importa `services/reports_revenue.py` y
`services/reports_occupancy.py` -otras piezas de P3.4 en construcción en paralelo-. Si esos
módulos todavía no existen, CUALQUIER request de esta sección revienta con `ImportError` al
resolver el URLconf (no en la colección de este archivo: `reports_manual.py` no depende de
esos hermanos). La sección A no tiene esa dependencia y corre siempre.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from core.models import Branch, ManualPayment, Plan, StudentPlan
from core.services import reports_manual
from core.services.reports_base import GRANULARITY_DAY, ReportScope
from core.services.reports_manual import (build_manual_payments_report,
                                          manual_payments_export_spec)

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()
URL = '/api/reports/manual-payments/'


# --------------------------------------------------------------------------------------
# Fixtures locales (mismo estilo que test_manual_payment.py: helpers, no fixtures pytest,
# porque cada test necesita variar un parámetro distinto).
# --------------------------------------------------------------------------------------

def _plan(org, name='Pack', total_classes=10, price=30000):
    return Plan.objects.create(
        organization=org, name=name, plan_type='pack', total_classes=total_classes,
        unlimited_classes=False, duration_days=30, price=price,
    )


def _membership(student, plan, branch=None, start_offset=-30, end_offset=30):
    return StudentPlan.objects.create(
        user=student, plan=plan, organization_id=plan.organization_id, branch=branch,
        start_date=TODAY + timedelta(days=start_offset),
        end_date=TODAY + timedelta(days=end_offset),
        total_classes=plan.total_classes, unlimited_classes=plan.unlimited_classes,
        classes_used=0, final_price=plan.price,
    )


def _payment(student_plan, *, amount=Decimal('10000'), method=ManualPayment.METHOD_CASH,
             reference='', recorded_by=None, recorded_at=None, branch='__default__'):
    """Crea la fila directo por el ORM, no por `record_manual_payment`: estos tests
    ejercitan la LECTURA (el servicio de escritura ya tiene su propia suite en
    `test_manual_payment.py`) y necesitan fijar `recorded_at` a mano -la puerta de
    escritura siempre lo estampa con `timezone.now()`- para ubicar cada fila en el período
    que cada test necesita.

    `branch='__default__'` (y no `None`) como sentinel: `None` es un valor válido y
    distinto -"sin sede"-, así que hace falta un tercer valor para "heredá la de la
    membresía", que es lo que hace la puerta de escritura real (`branch_id=student_plan.
    branch_id` en `services/manual_payments.py`).
    """
    return ManualPayment.objects.create(
        organization=student_plan.organization,
        student_plan=student_plan,
        branch=student_plan.branch if branch == '__default__' else branch,
        amount=amount,
        method=method,
        reference=reference,
        recorded_by=recorded_by,
        recorded_at=recorded_at or timezone.now(),
    )


def _scope(org, date_from=None, date_to=None, branch=None):
    return ReportScope(
        organization_id=org.id,
        date_from=date_from or (TODAY - timedelta(days=30)),
        date_to=date_to or TODAY,
        granularity=GRANULARITY_DAY,
        branch=branch,
    )


# --------------------------------------------------------------------------------------
# A. Servicio (`build_manual_payments_report` / `manual_payments_export_spec`), sin HTTP.
# --------------------------------------------------------------------------------------

def test_a_row_carries_method_recorder_timestamp_student_plan_and_branch(
        make_organization, make_user):
    """La fila del reporte tiene que traer, sin vueltas, todo lo que el gimnasio necesita
    para auditar un cobro de recepción: CON QUÉ (método), QUIÉN lo anotó y CUÁNDO, más A
    QUIÉN y por QUÉ membresía."""
    org = make_organization()
    branch = Branch.objects.create(organization=org, name='Sede Centro')
    student = make_user('stu-a', organization=org, role='student', first_name='Ana',
                        last_name='Pérez')
    admin = make_user('admin-a', organization=org, role='gym_admin', first_name='Rita',
                      last_name='Gomez')
    plan = _plan(org, name='Mensual 8')
    membership = _membership(student, plan, branch=branch)
    payment = _payment(membership, amount=Decimal('15000'),
                       method=ManualPayment.METHOD_TRANSFER, reference='TRX-99',
                       recorded_by=admin, recorded_at=timezone.now() - timedelta(days=1))
    payment.refresh_from_db()   # recorded_at tal cual quedó en la base, no el valor previo

    data = build_manual_payments_report(_scope(org))

    assert len(data['rows']) == 1
    row = data['rows'][0]
    assert row['id'] == payment.id
    assert row['method'] == 'transfer'
    assert row['method_label'] == 'Transferencia'
    assert row['reference'] == 'TRX-99'
    assert row['recorded_by_id'] == admin.id
    assert row['recorded_by_name'] == 'Rita Gomez'
    assert row['recorded_at'] == payment.recorded_at.isoformat()
    assert row['student_id'] == student.id
    assert row['student_name'] == 'Ana Pérez'
    assert row['student_plan_id'] == membership.id
    assert row['plan_name'] == 'Mensual 8'
    assert row['branch_id'] == branch.id
    assert row['branch_name'] == 'Sede Centro'
    assert row['amount'] == 15000


def test_student_and_recorder_names_fall_back_to_username_without_a_full_name(
        make_organization, make_user):
    """`get_full_name()` devuelve '' cuando la persona no declaró nombre -dato opcional en
    el alta-, y una celda vacía en un reporte de plata es peor que el username: al menos
    identifica a quién sin ambigüedad."""
    org = make_organization()
    student = make_user('stu-noname', organization=org, role='student')
    admin = make_user('admin-noname', organization=org, role='gym_admin')
    membership = _membership(student, _plan(org))
    _payment(membership, amount=Decimal('1000'), recorded_by=admin)

    data = build_manual_payments_report(_scope(org))

    row = data['rows'][0]
    assert row['student_name'] == 'stu-noname'
    assert row['recorded_by_name'] == 'admin-noname'


def test_totals_break_down_cash_vs_transfer_with_counts(make_organization, make_user):
    """Cobertura #2: el KPI del reporte -cuánto entró por cada instrumento y cuántas filas
    hay de cada uno-, sin ningún filtro de método."""
    org = make_organization()
    student = make_user('stu-b', organization=org, role='student')
    membership = _membership(student, _plan(org))
    _payment(membership, amount=Decimal('10000'), method=ManualPayment.METHOD_CASH)
    _payment(membership, amount=Decimal('5000'), method=ManualPayment.METHOD_CASH)
    _payment(membership, amount=Decimal('7000'), method=ManualPayment.METHOD_TRANSFER)

    data = build_manual_payments_report(_scope(org))

    assert data['totals'] == {
        'cash': 15000, 'transfer': 7000, 'unknown': 0, 'total': 22000,
        'count': 3, 'cash_count': 2, 'transfer_count': 1, 'unknown_count': 0,
    }
    assert data['truncated'] is False
    assert data['row_limit'] == reports_manual.MAX_ROWS


def test_filtering_by_period_excludes_payments_outside_the_range(make_organization,
                                                                   make_user):
    org = make_organization()
    student = make_user('stu-c', organization=org, role='student')
    membership = _membership(student, _plan(org))
    inside = _payment(membership, amount=Decimal('1000'),
                      recorded_at=timezone.now() - timedelta(days=5))
    _payment(membership, amount=Decimal('2000'),
            recorded_at=timezone.now() - timedelta(days=60))

    scope = _scope(org, date_from=TODAY - timedelta(days=10), date_to=TODAY)
    data = build_manual_payments_report(scope)

    assert [row['id'] for row in data['rows']] == [inside.id]
    assert data['totals']['total'] == 1000


def test_filtering_by_branch_excludes_other_branches_and_the_null_branch(
        make_organization, make_user):
    """Filas con `branch` NULL quedan FUERA del filtro por sucursal: no hay forma de saber
    si "sin sede" significa "todas" o "ninguna" (ver el comentario de `_base_queryset` en
    reports_manual.py), así que mostrarlas bajo cualquier sede inventaría el dato."""
    org = make_organization()
    branch_a = Branch.objects.create(organization=org, name='Sede A')
    branch_b = Branch.objects.create(organization=org, name='Sede B')
    student = make_user('stu-d', organization=org, role='student')
    membership_a = _membership(student, _plan(org, name='Plan A'), branch=branch_a)
    membership_b = _membership(student, _plan(org, name='Plan B'), branch=branch_b)
    membership_none = _membership(student, _plan(org, name='Plan Global'), branch=None)
    payment_a = _payment(membership_a, amount=Decimal('1000'))
    _payment(membership_b, amount=Decimal('2000'))
    _payment(membership_none, amount=Decimal('3000'))

    data = build_manual_payments_report(_scope(org, branch=branch_a))

    assert [row['id'] for row in data['rows']] == [payment_a.id]
    assert data['totals']['total'] == 1000
    assert data['filters']['branch_id'] == branch_a.id
    assert data['filters']['branch_name'] == 'Sede A'


def test_filtering_by_method_zeroes_out_the_other_instrument_everywhere(make_organization,
                                                                         make_user):
    """Decisión 2 del módulo (`reports_manual.py`): `method`, si viene, filtra TODO -serie,
    totales y filas-, no solo la lista. Filtrar por `cash` tiene que dejar
    `totals.transfer` en cero, no mostrar el total mixto debajo de una lista recortada."""
    org = make_organization()
    student = make_user('stu-e', organization=org, role='student')
    membership = _membership(student, _plan(org))
    cash_payment = _payment(membership, amount=Decimal('1000'),
                            method=ManualPayment.METHOD_CASH)
    _payment(membership, amount=Decimal('2000'), method=ManualPayment.METHOD_TRANSFER)

    data = build_manual_payments_report(_scope(org), method=ManualPayment.METHOD_CASH)

    assert [row['id'] for row in data['rows']] == [cash_payment.id]
    assert data['totals'] == {
        'cash': 1000, 'transfer': 0, 'unknown': 0, 'total': 1000,
        'count': 1, 'cash_count': 1, 'transfer_count': 0, 'unknown_count': 0,
    }
    assert data['filters']['method'] == 'cash'
    assert data['filters']['method_label'] == 'Efectivo'
    assert all(point['transfer'] == 0 for point in data['series'])


def test_payments_of_another_organization_never_appear_in_rows_totals_or_series(
        make_organization, make_user):
    """Cobertura #4: aislamiento multitenant (regla 1 de backend/CLAUDE.md), en las TRES
    superficies que el reporte publica, no solo en `rows`."""
    org_a = make_organization()
    org_b = make_organization()
    student_a = make_user('stu-f-a', organization=org_a, role='student')
    student_b = make_user('stu-f-b', organization=org_b, role='student')
    membership_a = _membership(student_a, _plan(org_a))
    membership_b = _membership(student_b, _plan(org_b))
    _payment(membership_a, amount=Decimal('1000'))
    _payment(membership_b, amount=Decimal('999999'))

    data = build_manual_payments_report(_scope(org_a))

    assert len(data['rows']) == 1
    assert data['totals']['total'] == 1000
    assert sum(point['total'] for point in data['series']) == 1000


def test_a_null_recorder_does_not_break_the_row(make_organization, make_user):
    """Cobertura #6: `recorded_by` es SET_NULL (el administrador que cobró se borró
    después) y no puede reventar el reporte ni confundirse con una celda vacía por error;
    se declara con un texto explícito."""
    org = make_organization()
    student = make_user('stu-g', organization=org, role='student')
    membership = _membership(student, _plan(org))
    _payment(membership, amount=Decimal('1000'), recorded_by=None)

    data = build_manual_payments_report(_scope(org))

    row = data['rows'][0]
    assert row['recorded_by_id'] is None
    assert row['recorded_by_name'] == 'Usuario eliminado'


def test_totals_and_series_stay_correct_when_the_row_list_is_truncated(make_organization,
                                                                        make_user,
                                                                        monkeypatch):
    """Cobertura #7: bajamos `MAX_ROWS` con monkeypatch en vez de fabricar 2000 filas. Lo
    que importa es que `totals`/`series` agreguen sobre TODO el período (la consulta de
    `_totals`/`_series` no lleva `[:MAX_ROWS]`), no sobre lo que quedó después del corte de
    `rows` -un tope silencioso que además mintiera en los números de arriba sería peor que
    no tener tope."""
    monkeypatch.setattr(reports_manual, 'MAX_ROWS', 2)
    org = make_organization()
    student = make_user('stu-h', organization=org, role='student')
    membership = _membership(student, _plan(org))
    for _ in range(5):
        _payment(membership, amount=Decimal('1000'))

    data = build_manual_payments_report(_scope(org))

    assert len(data['rows']) == 2
    assert data['row_limit'] == 2
    assert data['truncated'] is True
    assert data['totals']['total'] == 5000
    assert data['totals']['count'] == 5
    assert sum(point['total'] for point in data['series']) == 5000


def test_a_truncated_export_declares_the_cut_inside_the_file(monkeypatch, make_organization,
                                                             make_user):
    """El descuadre del archivo no puede ser MUDO.

    `rows` viene cortado a `MAX_ROWS` y la fila TOTAL se agrega sobre el período completo: las
    dos cosas son correctas por separado, pero juntas producen una planilla donde sumar la
    columna `Monto` no da el TOTAL. La pantalla ya avisa del corte; el archivo viaja solo y
    tiene que avisarlo también, o el que lo abre concluye que el reporte está roto (o corrige el
    total a mano)."""
    monkeypatch.setattr(reports_manual, 'MAX_ROWS', 2)
    org = make_organization()
    student = make_user('stu-trunc-export', organization=org, role='student')
    membership = _membership(student, _plan(org))
    for _ in range(5):
        _payment(membership, amount=Decimal('1000'))

    spec = manual_payments_export_spec(build_manual_payments_report(_scope(org)))

    # 2 filas de datos + la fila que declara el corte.
    assert len(spec['rows']) == 3
    notice = spec['rows'][-1][0]
    assert 'recortada' in notice and '2' in notice and '5' in notice
    assert spec['total_row'][-1] == 5000


def test_an_untruncated_export_has_no_notice_row(make_organization, make_user):
    """El aviso aparece SOLO cuando hay corte: una nota permanente sería ruido en el archivo
    normal, y peor, entrenaría a ignorarla justo cuando importa."""
    org = make_organization()
    student = make_user('stu-full-export', organization=org, role='student')
    membership = _membership(student, _plan(org))
    _payment(membership, amount=Decimal('1000'))

    spec = manual_payments_export_spec(build_manual_payments_report(_scope(org)))

    assert len(spec['rows']) == 1
    assert sum(row[-1] for row in spec['rows']) == spec['total_row'][-1]


def test_series_is_zero_filled_for_days_without_any_payment(make_organization, make_user):
    """`bucket_keys(scope)` fija la grilla completa del período (reports_base.py): un día
    sin cobros tiene que aparecer con cash=transfer=total=0, no saltearse -una línea que
    une dos días activos por encima de uno sin movimiento dibujaría una pendiente que
    nadie cobró."""
    org = make_organization()
    student = make_user('stu-series', organization=org, role='student')
    membership = _membership(student, _plan(org))
    scope = _scope(org, date_from=TODAY - timedelta(days=2), date_to=TODAY)
    _payment(membership, amount=Decimal('500'), recorded_at=timezone.now())

    data = build_manual_payments_report(scope)

    expected_buckets = [
        (TODAY - timedelta(days=2)).isoformat(),
        (TODAY - timedelta(days=1)).isoformat(),
        TODAY.isoformat(),
    ]
    assert [point['bucket'] for point in data['series']] == expected_buckets
    by_bucket = {point['bucket']: point for point in data['series']}
    assert by_bucket[(TODAY - timedelta(days=2)).isoformat()] == {
        'bucket': (TODAY - timedelta(days=2)).isoformat(), 'cash': 0, 'transfer': 0,
        'unknown': 0, 'total': 0,
    }
    assert by_bucket[(TODAY - timedelta(days=1)).isoformat()]['total'] == 0
    assert by_bucket[TODAY.isoformat()]['cash'] == 500


def test_legacy_rows_without_a_declared_method_are_included_under_the_unknown_instrument(
        make_organization, make_user):
    """Decisión 1 del módulo, CORREGIDA durante la integración de P3.4.

    La primera versión de este reporte dejaba las filas anteriores a P3.2 (`method=''`)
    afuera del reporte entero, para preservar la identidad `total == cash + transfer`. Estaba
    mal: esas filas son cobros REALES que ya viven en producción, y este reporte es la ÚNICA
    lectura que existe de `ManualPayment` — dejarlas afuera hacía que plata cobrada no
    apareciera en ninguna pantalla del producto.
    La identidad se preservó agregándole el tercer término (`unknown`) en vez de descartando
    los datos. El detalle completo, y el mismo bug en el reporte de ingresos, están en
    `test_reports_unknown_method.py`."""
    org = make_organization()
    student = make_user('stu-legacy', organization=org, role='student')
    membership = _membership(student, _plan(org))
    _payment(membership, amount=Decimal('1000'), method=ManualPayment.METHOD_CASH)
    # Fila legacy: se salta el ORM normal porque `ManualPayment.clean()` rechaza `method`
    # vacío en una fila NUEVA (ver models.py); `.update()` simula una fila que ya vivía en
    # la base antes de que P3.2 agregara la columna.
    legacy = ManualPayment.objects.create(
        organization=org, student_plan=membership, amount=Decimal('50000'),
        method=ManualPayment.METHOD_CASH, reference='', recorded_at=timezone.now(),
    )
    ManualPayment.objects.filter(pk=legacy.pk).update(method='')

    data = build_manual_payments_report(_scope(org))
    totals = data['totals']

    assert len(data['rows']) == 2
    assert totals['unknown'] == 50000
    assert totals['unknown_count'] == 1
    assert totals['total'] == totals['cash'] + totals['transfer'] + totals['unknown'] == 51000
    assert totals['count'] == 2


def test_export_spec_header_rows_and_total_row(make_organization, make_user):
    """`manual_payments_export_spec` tal como lo consume `reports_base.export_response`:
    header en español, una fila por pago con el monto en la última columna, y una fila
    TOTAL con el agregado en esa misma columna."""
    org = make_organization()
    student = make_user('stu-export', organization=org, role='student')
    admin = make_user('admin-export', organization=org, role='gym_admin')
    membership = _membership(student, _plan(org, name='Plan Export'))
    _payment(membership, amount=Decimal('4000'), method=ManualPayment.METHOD_CASH,
            reference='REF-1', recorded_by=admin)
    _payment(membership, amount=Decimal('6000'), method=ManualPayment.METHOD_TRANSFER,
            reference='REF-2', recorded_by=admin)

    data = build_manual_payments_report(_scope(org))
    spec = manual_payments_export_spec(data)

    assert spec['header'] == [
        'Fecha', 'Alumno', 'Plan', 'Sede', 'Método', 'Referencia', 'Registrado por', 'Monto',
    ]
    assert len(spec['rows']) == 2
    assert all(len(row) == len(spec['header']) for row in spec['rows'])
    assert {row[-1] for row in spec['rows']} == {4000, 6000}
    assert spec['total_row'][0] == 'TOTAL'
    assert spec['total_row'][-1] == 10000


# --------------------------------------------------------------------------------------
# B. Endpoint HTTP `GET /api/reports/manual-payments/` de punta a punta.
#
# Ver el aviso de módulo: si `reports_revenue.py`/`reports_occupancy.py` (otras piezas de
# P3.4, en construcción en paralelo) todavía no existen, TODOS los tests de esta sección
# revientan con `ImportError` al resolver el URLconf. No es un fallo de este archivo.
# --------------------------------------------------------------------------------------

def test_http_gym_admin_gets_200_with_the_expected_totals(api_client, make_organization,
                                                            make_user):
    """Cobertura #5 (mitad feliz): el `gym_admin` de la organización recibe 200 y el
    payload trae lo que la capa de servicio ya probó por su lado."""
    org = make_organization()
    student = make_user('stu-http-a', organization=org, role='student')
    admin = make_user('admin-http-a', organization=org, role='gym_admin')
    membership = _membership(student, _plan(org))
    _payment(membership, amount=Decimal('1000'), method=ManualPayment.METHOD_CASH,
            recorded_by=admin)
    api_client.force_authenticate(user=admin)

    resp = api_client.get(URL, {
        'date_from': str(TODAY - timedelta(days=1)),
        'date_to': str(TODAY + timedelta(days=1)),
    })

    assert resp.status_code == 200, resp.content
    assert resp.data['totals']['cash'] == 1000
    assert len(resp.data['rows']) == 1


@pytest.mark.parametrize('role', ['manager', 'monitor', 'teacher', 'student'])
def test_http_non_gym_admin_org_roles_get_403(api_client, make_organization, make_user,
                                               role):
    """Cobertura #5: `ReportPermission` es EXCLUSIVA del `gym_admin` (permissions.py); ni
    siquiera el `manager` -que sí gestiona el roster- puede leer plata agregada."""
    org = make_organization()
    actor = make_user(f'actor-http-{role}', organization=org, role=role)
    api_client.force_authenticate(user=actor)

    resp = api_client.get(URL)

    assert resp.status_code == 403


def test_http_superadmin_gets_403(api_client, make_user):
    """Cobertura #5: el `superadmin` es rol de PLATAFORMA sin `organization_id` propia -el
    mismo criterio que ya cierra `PaymentTransactionListView`- y no hay alcance que
    scopear para él."""
    superadmin = make_user('super-http', organization=None, role='superadmin')
    api_client.force_authenticate(user=superadmin)

    resp = api_client.get(URL)

    assert resp.status_code == 403


def test_http_an_anonymous_request_is_rejected(api_client):
    resp = api_client.get(URL)

    assert resp.status_code in (401, 403)


def test_http_a_branch_id_from_another_organization_is_a_404(api_client, make_organization,
                                                               make_user):
    """Cobertura #5: mismo criterio anti-oráculo que `views_payments._branch_scope` -una
    sede ajena no puede distinguirse de una sede inexistente."""
    org_a = make_organization()
    org_b = make_organization()
    foreign_branch = Branch.objects.create(organization=org_b, name='Sede ajena')
    admin_a = make_user('admin-http-branch', organization=org_a, role='gym_admin')
    api_client.force_authenticate(user=admin_a)

    resp = api_client.get(URL, {'branch_id': foreign_branch.id})

    assert resp.status_code == 404


def test_http_export_csv_returns_the_expected_columns(api_client, make_organization,
                                                        make_user):
    """Cobertura #8: `?export=csv` devuelve `text/csv` con las columnas del reporte, no el
    JSON de siempre."""
    org = make_organization()
    student = make_user('stu-http-csv', organization=org, role='student')
    admin = make_user('admin-http-csv', organization=org, role='gym_admin')
    membership = _membership(student, _plan(org, name='Mensual CSV'))
    _payment(membership, amount=Decimal('12345'), method=ManualPayment.METHOD_TRANSFER,
            reference='TRX-csv', recorded_by=admin)
    api_client.force_authenticate(user=admin)

    resp = api_client.get(URL, {
        'export': 'csv',
        'date_from': str(TODAY - timedelta(days=1)),
        'date_to': str(TODAY + timedelta(days=1)),
    })

    assert resp.status_code == 200, resp.content
    assert resp['Content-Type'].startswith('text/csv')
    body = resp.content.decode('utf-8-sig')
    assert 'Fecha' in body and 'Monto' in body
    assert 'TRX-csv' in body
    assert 'TOTAL' in body
