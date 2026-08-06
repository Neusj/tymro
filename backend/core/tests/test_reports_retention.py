"""Reporte de vencimientos y renovaciones (P3.4 · parte 2, pieza 1) —
`core.services.reports_retention`.

Es código de RETENCIÓN: cada test fija una afirmación que el reporte le hace al administrador
sobre quién se queda y quién se va, y ninguna puede aflojarse "para que pase". Lo que se fija:

* qué es una renovación —mismo linaje, cobertura que se extiende, dentro de la gracia— y qué
  NO lo es (otro plan del catálogo, fuera de la gracia);
* las identidades declaradas: `lost = expired - renewed`, `renewed` es subconjunto de
  `expired` en cada bucket, y los tres cortes (totales, serie, por plan) suman lo mismo;
* el filtro de sede DECLARADAMENTE inclusivo de los planes globales
  (`branch=X OR (branch IS NULL AND plan.branch IS NULL)`), por qué un filtro a secas mentiría
  y por qué el `branch IS NULL` pelado también: esa columna es `SET_NULL`, así que su NULL
  también significa "la sucursal se borró", y el alcance real lo manda `plan.branch`;
* el aislamiento por organización, con el caso peligroso del alumno que existe en dos
  tenants;
* el KPI `upcoming`, anclado en HOY y no en el período del filtro;
* el endpoint: solo `gym_admin`, `plan_id` ajeno 404, export CSV/XLSX.
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from core.models import Branch, Plan, StudentPlan
from core.services import reports_retention
from core.services.reports_base import GRANULARITY_DAY, ReportScope
from core.services.reports_retention import build_retention_report, retention_export_spec

pytestmark = pytest.mark.django_db

URL = '/api/reports/retention/'


# --------------------------------------------------------------------------------------
# Fixtures y helpers.
# --------------------------------------------------------------------------------------

@pytest.fixture
def org(make_organization):
    return make_organization('Gym Retención')


@pytest.fixture
def other_org(make_organization):
    return make_organization('Gym Vecino Retención')


@pytest.fixture
def branch(org):
    return Branch.objects.create(organization=org, name='Sede Centro')


@pytest.fixture
def student(make_user, org):
    return make_user('stu-ret', organization=org, role='student')


@pytest.fixture
def admin(make_user, org):
    return make_user('adm-ret', organization=org, role='gym_admin')


def _plan(org, *, name='Pack 8', plan_type=Plan.PlanType.PACK, price=30000,
         total_classes=8, duration_days=30, branch=None):
    return Plan.objects.create(
        organization=org, name=name, plan_type=plan_type, total_classes=total_classes,
        unlimited_classes=False, duration_days=duration_days, price=price, branch=branch,
    )


def _membership(user, plan, *, start_date, end_date, branch=None, final_price=None,
                is_active=True):
    return StudentPlan.objects.create(
        user=user, plan=plan, organization_id=plan.organization_id, branch=branch,
        start_date=start_date, end_date=end_date, total_classes=plan.total_classes,
        unlimited_classes=plan.unlimited_classes, classes_used=0,
        final_price=plan.price if final_price is None else final_price,
        is_active=is_active,
    )


def _scope(org, *, date_from, date_to, granularity=GRANULARITY_DAY, branch=None):
    return ReportScope(organization_id=org.id, date_from=date_from, date_to=date_to,
                       granularity=granularity, branch=branch)


# --------------------------------------------------------------------------------------
# 1. Vencida sin renovar = PERDIDA.
# --------------------------------------------------------------------------------------

def test_an_expired_membership_without_a_renewal_counts_as_lost(org, student):
    today = timezone.localdate()
    plan = _plan(org)
    _membership(student, plan, start_date=today - timedelta(days=40), end_date=today)

    data = build_retention_report(_scope(org, date_from=today, date_to=today))

    assert data['totals']['expired'] == 1
    assert data['totals']['renewed'] == 0
    assert data['totals']['lost'] == 1
    assert data['totals']['switched_plan'] == 0
    assert data['totals']['churned'] == 1
    assert data['totals']['renewal_rate'] == 0.0


# --------------------------------------------------------------------------------------
# 2. Vencida CON instancia nueva del MISMO linaje = RENOVADA.
# --------------------------------------------------------------------------------------

def test_an_expired_membership_with_a_new_instance_of_the_same_lineage_counts_as_renewed(
        org, student):
    today = timezone.localdate()
    plan = _plan(org)
    _membership(student, plan, start_date=today - timedelta(days=40), end_date=today)
    # Instancia nueva del MISMO plan + MISMO alumno: extiende la cobertura más allá del
    # vencimiento.
    _membership(student, plan, start_date=today + timedelta(days=1),
               end_date=today + timedelta(days=31))

    data = build_retention_report(_scope(org, date_from=today, date_to=today))

    assert data['totals']['expired'] == 1
    assert data['totals']['renewed'] == 1
    assert data['totals']['lost'] == 0
    assert data['totals']['renewal_rate'] == 100.0


# --------------------------------------------------------------------------------------
# 3. La tasa de renovación, verificable a mano: 3 vencidas / 1 renovada = 33.3.
# --------------------------------------------------------------------------------------

def test_the_renewal_rate_is_verifiable_by_hand(org, make_user):
    today = timezone.localdate()
    plan = _plan(org)
    renewed_student = make_user('ret-rate-1', organization=org, role='student')
    lost_student_a = make_user('ret-rate-2', organization=org, role='student')
    lost_student_b = make_user('ret-rate-3', organization=org, role='student')

    _membership(renewed_student, plan, start_date=today - timedelta(days=40), end_date=today)
    _membership(renewed_student, plan, start_date=today + timedelta(days=1),
               end_date=today + timedelta(days=31))
    _membership(lost_student_a, plan, start_date=today - timedelta(days=40), end_date=today)
    _membership(lost_student_b, plan, start_date=today - timedelta(days=40), end_date=today)

    data = build_retention_report(_scope(org, date_from=today, date_to=today))

    assert data['totals']['expired'] == 3
    assert data['totals']['renewed'] == 1
    # 1/3 = 33.333...% redondeado a un decimal.
    assert data['totals']['renewal_rate'] == 33.3


# --------------------------------------------------------------------------------------
# 4. Renovación ANTICIPADA (mismo día o antes del vencimiento) SÍ cuenta.
# --------------------------------------------------------------------------------------

def test_an_early_renewal_that_overlaps_the_expiring_membership_counts_as_renewed(
        org, student):
    """La nueva instancia arranca el MISMO día en que vence la vieja (solapando un día), que
    es lo que pasa cuando el admin renueva el mismo día del vencimiento con `start_date=hoy`.
    El predicado exige `nueva.end_date > vieja.end_date`, NO `nueva.start_date > vieja.end_date`,
    así que este alumno —el más fiel— tiene que contar como renovado."""
    today = timezone.localdate()
    plan = _plan(org)
    _membership(student, plan, start_date=today - timedelta(days=30), end_date=today)
    _membership(student, plan, start_date=today, end_date=today + timedelta(days=30))

    data = build_retention_report(_scope(org, date_from=today, date_to=today))

    assert data['totals']['expired'] == 1
    assert data['totals']['renewed'] == 1
    assert data['totals']['lost'] == 0


# --------------------------------------------------------------------------------------
# 5. Recompra FUERA de la ventana de gracia NO cuenta.
# --------------------------------------------------------------------------------------

def test_a_repurchase_outside_the_grace_window_does_not_count_as_renewed(org, student,
                                                                         monkeypatch):
    monkeypatch.setattr(reports_retention, 'RENEWAL_GRACE_DAYS', 5)
    today = timezone.localdate()
    old_end = today - timedelta(days=20)
    plan = _plan(org)
    _membership(student, plan, start_date=old_end - timedelta(days=30), end_date=old_end)
    # La nueva instancia (mismo plan) empieza 10 días después del vencimiento, con una gracia
    # de solo 5: queda AFUERA de la ventana.
    _membership(student, plan, start_date=old_end + timedelta(days=10),
               end_date=old_end + timedelta(days=40))

    data = build_retention_report(
        _scope(org, date_from=old_end - timedelta(days=1), date_to=old_end + timedelta(days=1)))

    assert data['totals']['expired'] == 1
    assert data['totals']['renewed'] == 0
    assert data['totals']['lost'] == 1
    assert data['totals']['switched_plan'] == 0
    # La gracia (5 días) ya cerró hace mucho respecto de "hoy": el veredicto es definitivo.
    assert data['totals']['pending_grace'] == 0


# --------------------------------------------------------------------------------------
# 6. `switched_plan` no infla `renewal_rate`.
# --------------------------------------------------------------------------------------

def test_switching_to_another_catalog_plan_does_not_inflate_the_renewal_rate(org, student):
    today = timezone.localdate()
    old_plan = _plan(org, name='Pack 8')
    new_plan = _plan(org, name='Mensual ilimitado', plan_type=Plan.PlanType.MONTHLY)
    _membership(student, old_plan, start_date=today - timedelta(days=40), end_date=today)
    # Compró OTRO plan del catálogo dentro de la gracia: se retuvo, pero no renovó el linaje.
    _membership(student, new_plan, start_date=today + timedelta(days=1),
               end_date=today + timedelta(days=31))

    data = build_retention_report(_scope(org, date_from=today, date_to=today))

    assert data['totals']['expired'] == 1
    assert data['totals']['renewed'] == 0
    assert data['totals']['switched_plan'] == 1
    assert data['totals']['lost'] == 1
    assert data['totals']['churned'] == 0
    # Las dos tasas divergen: 0 % de renovación (linaje) contra 100 % de retención (cualquier
    # plan). `renewal_rate` nunca mezcla linajes.
    assert data['totals']['renewal_rate'] == 0.0
    assert data['totals']['retention_rate'] == 100.0


# --------------------------------------------------------------------------------------
# 7. Identidades: lost == expired - renewed; renewed ⊆ expired por bucket; Σ series == totals
#    == Σ by_plan.
# --------------------------------------------------------------------------------------

def test_identities_hold_across_totals_series_and_by_plan(org, make_user):
    today = timezone.localdate()
    day1, day2 = today - timedelta(days=1), today
    plan_a = _plan(org, name='Plan A')
    plan_b = _plan(org, name='Plan B')
    renewed_student = make_user('ret-id-1', organization=org, role='student')
    switched_student = make_user('ret-id-2', organization=org, role='student')
    lost_student = make_user('ret-id-3', organization=org, role='student')

    # Renovado: plan A vence día1, se renueva con plan A.
    _membership(renewed_student, plan_a, start_date=day1 - timedelta(days=30), end_date=day1)
    _membership(renewed_student, plan_a, start_date=day1 + timedelta(days=1),
               end_date=day1 + timedelta(days=31))
    # Cambió de plan: plan A vence día2, compra plan B.
    _membership(switched_student, plan_a, start_date=day2 - timedelta(days=30), end_date=day2)
    _membership(switched_student, plan_b, start_date=day2 + timedelta(days=1),
               end_date=day2 + timedelta(days=31))
    # Perdida: plan B vence día1, sin recompra.
    _membership(lost_student, plan_b, start_date=day1 - timedelta(days=30), end_date=day1)

    data = build_retention_report(_scope(org, date_from=day1, date_to=day2))

    totals = data['totals']
    assert totals['expired'] == 3
    assert totals['lost'] == totals['expired'] - totals['renewed']

    for point in data['series']:
        assert point['renewed'] <= point['expired']
        assert point['lost'] == point['expired'] - point['renewed']
    assert sum(point['expired'] for point in data['series']) == totals['expired']
    assert sum(point['renewed'] for point in data['series']) == totals['renewed']
    assert sum(point['switched_plan'] for point in data['series']) == totals['switched_plan']

    assert sum(item['expired'] for item in data['by_plan']) == totals['expired']
    assert sum(item['renewed'] for item in data['by_plan']) == totals['renewed']
    assert sum(item['switched_plan'] for item in data['by_plan']) == totals['switched_plan']


# --------------------------------------------------------------------------------------
# 8. El bloque `upcoming`: anclado en HOY, con `as_of`/`overlaps_period`.
# --------------------------------------------------------------------------------------

def test_upcoming_reports_expiring_memberships_anchored_on_today(org, student, monkeypatch):
    monkeypatch.setattr(reports_retention, 'UPCOMING_WINDOW_DAYS', 10)
    today = timezone.localdate()
    plan = _plan(org)
    # Vence en 5 días: cae dentro de la ventana de 10 días "por vencer" desde hoy.
    _membership(student, plan, start_date=today - timedelta(days=25),
               end_date=today + timedelta(days=5))
    # Período del filtro es un día PASADO, sin relación con la ventana de `upcoming`.
    past_day = today - timedelta(days=60)

    data = build_retention_report(_scope(org, date_from=past_day, date_to=past_day))

    assert data['upcoming']['as_of'] == today.isoformat()
    assert data['upcoming']['window_days'] == 10
    assert data['upcoming']['expiring'] == 1
    assert data['upcoming']['already_renewed'] == 0
    assert data['upcoming']['at_risk'] == 1
    # El período del filtro es un día pasado: no se superpone con la ventana "por vencer".
    assert data['upcoming']['overlaps_period'] is False


def test_upcoming_discounts_already_renewed_early_renewals(org, student, monkeypatch):
    monkeypatch.setattr(reports_retention, 'UPCOMING_WINDOW_DAYS', 10)
    today = timezone.localdate()
    plan = _plan(org)
    _membership(student, plan, start_date=today - timedelta(days=25),
               end_date=today + timedelta(days=5))
    # Renovación anticipada YA cargada: mismo linaje, empieza hoy.
    _membership(student, plan, start_date=today, end_date=today + timedelta(days=35))

    data = build_retention_report(
        _scope(org, date_from=today - timedelta(days=60), date_to=today - timedelta(days=59)))

    assert data['upcoming']['expiring'] == 1
    assert data['upcoming']['already_renewed'] == 1
    assert data['upcoming']['at_risk'] == 0
    # El período del filtro SÍ incluye hoy en este caso (ver el siguiente test para lo
    # contrario); acá solo interesa already_renewed/at_risk.


def test_upcoming_overlaps_period_when_the_filtered_range_includes_the_window(org):
    today = timezone.localdate()

    data = build_retention_report(_scope(org, date_from=today, date_to=today))

    assert data['upcoming']['overlaps_period'] is True


# --------------------------------------------------------------------------------------
# 9. Aislamiento por organización — incluido el cruce peligroso de un alumno que existe en
#    dos tenants.
# --------------------------------------------------------------------------------------

def test_another_organizations_memberships_never_leak_into_totals_or_by_plan(
        org, other_org, student, make_user):
    today = timezone.localdate()
    plan = _plan(org)
    foreign_plan = _plan(other_org, name='Plan ajeno')
    foreign_student = make_user('stu-ret-ajeno', organization=other_org, role='student')
    _membership(student, plan, start_date=today - timedelta(days=40), end_date=today)
    _membership(foreign_student, foreign_plan, start_date=today - timedelta(days=40),
               end_date=today)
    _membership(foreign_student, foreign_plan, start_date=today + timedelta(days=1),
               end_date=today + timedelta(days=31))

    data = build_retention_report(_scope(org, date_from=today, date_to=today))

    assert data['totals']['expired'] == 1
    assert data['totals']['renewed'] == 0
    assert [item['plan_name'] for item in data['by_plan']] == [plan.name]


def test_a_student_present_in_two_organizations_does_not_cross_the_renewal_search(
        org, other_org, make_user):
    """El linaje se busca por `(plan_id, user_id, organization_id=scope)`: aunque el MISMO
    usuario (CASCADE sobre la persona, no sobre el tenant) tenga una membresía vencida en
    `org` y compre algo en `other_org`, la búsqueda de sucesor de `org` está scopeada a
    `org` y no puede encontrar la fila de `other_org`."""
    today = timezone.localdate()
    shared_user = make_user('stu-ret-shared', organization=org, role='student')
    plan_here = _plan(org)
    plan_there = _plan(other_org)
    _membership(shared_user, plan_here, start_date=today - timedelta(days=40), end_date=today)
    # El mismo alumno "compra" en la otra organización (dato válido porque `user` es CASCADE
    # sobre la persona, no sobre el tenant). No puede rescatar la renovación de `org`.
    _membership(shared_user, plan_there, start_date=today + timedelta(days=1),
               end_date=today + timedelta(days=31))

    data = build_retention_report(_scope(org, date_from=today, date_to=today))

    assert data['totals']['expired'] == 1
    assert data['totals']['renewed'] == 0
    assert data['totals']['switched_plan'] == 0
    assert data['totals']['lost'] == 1


# --------------------------------------------------------------------------------------
# 10. Filtro de sede: sede elegida OR branch IS NULL (planes globales).
# --------------------------------------------------------------------------------------

def test_the_branch_filter_includes_global_plan_memberships_and_branches_do_not_sum_to_org(
        org, make_user):
    today = timezone.localdate()
    centro = Branch.objects.create(organization=org, name='Centro')
    norte = Branch.objects.create(organization=org, name='Norte')
    plan_centro = _plan(org, name='Plan Centro', branch=centro)
    plan_norte = _plan(org, name='Plan Norte', branch=norte)
    plan_global = _plan(org, name='Plan Global', branch=None)
    stu_centro = make_user('stu-ret-centro', organization=org, role='student')
    stu_norte = make_user('stu-ret-norte', organization=org, role='student')
    stu_global = make_user('stu-ret-global', organization=org, role='student')
    _membership(stu_centro, plan_centro, start_date=today - timedelta(days=10), end_date=today,
               branch=centro)
    _membership(stu_norte, plan_norte, start_date=today - timedelta(days=10), end_date=today,
               branch=norte)
    _membership(stu_global, plan_global, start_date=today - timedelta(days=10), end_date=today,
               branch=None)

    centro_data = build_retention_report(_scope(org, date_from=today, date_to=today,
                                                branch=centro))
    norte_data = build_retention_report(_scope(org, date_from=today, date_to=today,
                                               branch=norte))
    whole_org = build_retention_report(_scope(org, date_from=today, date_to=today))

    # Cada sede ve la suya MÁS la global.
    assert centro_data['totals']['expired'] == 2
    assert centro_data['totals']['global_plan_memberships'] == 1
    assert norte_data['totals']['expired'] == 2
    assert norte_data['totals']['global_plan_memberships'] == 1
    assert whole_org['totals']['expired'] == 3
    # Consecuencia declarada: las vistas por sede NO suman el total de la organización (la
    # global se cuenta en las dos).
    assert (centro_data['totals']['expired'] + norte_data['totals']['expired']
            != whole_org['totals']['expired'])
    assert centro_data['filters']['includes_global_plans'] is True


# --------------------------------------------------------------------------------------
# 10-bis. La otra mitad del filtro de sede: `StudentPlan.branch IS NULL` NO significa
# "global" por sí solo. Esa columna es SET_NULL, así que su NULL también aparece cuando la
# SUCURSAL SE BORRÓ, y el alcance real lo manda `plan.branch` (que es RESTRICT justamente
# para que su NULL solo pueda significar "toda la organización").
#
# Este test fija el hallazgo de la revisión de seguridad: con el filtro anterior
# (`branch=X OR branch IS NULL`) una membresía de una sede BORRADA sobre un plan EXCLUSIVO
# aparecía en el reporte de TODAS las sedes y encima se contaba como plan global, o sea un
# vencimiento imputado a una sede donde no ocurrió.
# --------------------------------------------------------------------------------------

def test_a_membership_left_without_branch_by_a_deleted_sede_is_not_treated_as_global(
        org, make_user):
    today = timezone.localdate()
    centro = Branch.objects.create(organization=org, name='Centro')
    norte = Branch.objects.create(organization=org, name='Norte')
    # Plan EXCLUSIVO de Norte y una membresía activada ahí.
    plan_exclusivo = _plan(org, name='Plan Norte', branch=norte)
    plan_global = _plan(org, name='Plan Global', branch=None)
    stu_norte = make_user('stu-ret-norte-borrada', organization=org, role='student')
    stu_global = make_user('stu-ret-global-2', organization=org, role='student')
    huerfana = _membership(stu_norte, plan_exclusivo, start_date=today - timedelta(days=10),
                           end_date=today, branch=norte)
    _membership(stu_global, plan_global, start_date=today - timedelta(days=10), end_date=today,
                branch=None)

    # El camino REAL y alcanzable dentro del tenant: se le cambia la sede al plan (con lo que
    # `Plan.branch`, que es RESTRICT, deja de proteger a Norte) y después se borra la sucursal
    # huérfana. `_cascade_blocker` (views.py) no bloquea por `StudentPlan.branch`.
    plan_exclusivo.branch = centro
    plan_exclusivo.save(update_fields=['branch'])
    norte.delete()

    # Sin esto el test no probaría nada: la premisa es que el SET_NULL efectivamente ocurrió.
    huerfana.refresh_from_db()
    assert huerfana.branch_id is None
    assert huerfana.plan.branch_id == centro.id     # el plan sigue siendo EXCLUSIVO

    centro_data = build_retention_report(_scope(org, date_from=today, date_to=today,
                                                branch=centro))
    whole_org = build_retention_report(_scope(org, date_from=today, date_to=today))

    # La vista de OTRA sede NO la ve: no se activó ahí y su plan no es global. Lo único que
    # entra por el NULL es la membresía del plan genuinamente global (el caso que el filtro
    # existe para rescatar, y que sigue funcionando).
    assert centro_data['totals']['expired'] == 1
    assert centro_data['totals']['global_plan_memberships'] == 1
    # Y no se rotula como global en NINGUNA vista: su plan es exclusivo. Este es el número que
    # el bug ensuciaba, porque se derivaba de `StudentPlan.branch` en vez de `plan.branch`.
    assert whole_org['totals']['expired'] == 2
    assert whole_org['totals']['global_plan_memberships'] == 1
    # Lectura conservadora declarada: el vencimiento existe y solo se ve en la vista de la
    # organización, porque el dato de dónde ocurrió se destruyó junto con la sucursal.
    assert whole_org['totals']['expired'] - centro_data['totals']['expired'] == 1


# --------------------------------------------------------------------------------------
# 11. Filtro `plan_id`.
# --------------------------------------------------------------------------------------

def test_the_plan_filter_narrows_the_denominator_to_that_plan(org, make_user):
    today = timezone.localdate()
    plan_a = _plan(org, name='Plan A')
    plan_b = _plan(org, name='Plan B')
    stu_a = make_user('stu-ret-plan-a', organization=org, role='student')
    stu_b = make_user('stu-ret-plan-b', organization=org, role='student')
    _membership(stu_a, plan_a, start_date=today - timedelta(days=10), end_date=today)
    _membership(stu_b, plan_b, start_date=today - timedelta(days=10), end_date=today)

    data = build_retention_report(_scope(org, date_from=today, date_to=today), plan=plan_a)

    assert data['totals']['expired'] == 1
    assert [item['plan_id'] for item in data['by_plan']] == [plan_a.id]
    assert data['filters']['plan_id'] == plan_a.id
    assert data['filters']['plan_name'] == plan_a.name


# --------------------------------------------------------------------------------------
# 12. Tasas viajan como `null` cuando el denominador es 0.
# --------------------------------------------------------------------------------------

def test_rates_travel_as_null_and_not_zero_when_there_is_nothing_expiring(org):
    today = timezone.localdate()

    data = build_retention_report(_scope(org, date_from=today, date_to=today))

    assert data['totals']['expired'] == 0
    assert data['totals']['renewal_rate'] is None
    assert data['totals']['retention_rate'] is None


# --------------------------------------------------------------------------------------
# 13. Export.
# --------------------------------------------------------------------------------------

def test_the_export_spec_mirrors_the_by_plan_payload(org, student):
    today = timezone.localdate()
    plan = _plan(org)
    _membership(student, plan, start_date=today - timedelta(days=40), end_date=today)

    data = build_retention_report(_scope(org, date_from=today, date_to=today))
    spec = retention_export_spec(data)

    assert spec['header'][0] == 'Plan'
    assert len(spec['rows']) == len(data['by_plan'])
    row = spec['rows'][0]
    assert row[0] == plan.name
    assert row[1] == data['by_plan'][0]['expired']
    total_row = spec['total_row']
    assert total_row[0] == 'TOTAL'
    assert total_row[1] == data['totals']['expired']


def test_export_csv_returns_a_spreadsheet_with_the_plan_breakdown(api_client, org, admin,
                                                                  student):
    today = timezone.localdate()
    plan = _plan(org)
    _membership(student, plan, start_date=today - timedelta(days=40), end_date=today)
    api_client.force_authenticate(user=admin)

    resp = api_client.get(URL, {'date_from': today.isoformat(), 'date_to': today.isoformat(),
                                'export': 'csv'})

    assert resp.status_code == 200, resp.content
    assert resp['Content-Type'].startswith('text/csv')
    assert 'vencimientos' in resp['Content-Disposition']
    content = resp.content.decode('utf-8-sig')
    assert plan.name in content
    assert 'TOTAL' in content


def test_export_xlsx_returns_a_workbook(api_client, org, admin, student):
    today = timezone.localdate()
    plan = _plan(org)
    _membership(student, plan, start_date=today - timedelta(days=40), end_date=today)
    api_client.force_authenticate(user=admin)

    resp = api_client.get(URL, {'date_from': today.isoformat(), 'date_to': today.isoformat(),
                                'export': 'xlsx'})

    assert resp.status_code == 200, resp.content
    assert resp['Content-Type'] == ('application/vnd.openxmlformats-officedocument'
                                    '.spreadsheetml.sheet')
    assert 'vencimientos' in resp['Content-Disposition']


# --------------------------------------------------------------------------------------
# 14. El endpoint: solo `gym_admin`, `plan_id` ajeno 404.
# --------------------------------------------------------------------------------------

def test_gym_admin_gets_the_report_of_their_own_organization(api_client, org, admin, student):
    today = timezone.localdate()
    plan = _plan(org)
    _membership(student, plan, start_date=today - timedelta(days=40), end_date=today)
    api_client.force_authenticate(user=admin)

    resp = api_client.get(URL, {'date_from': today.isoformat(), 'date_to': today.isoformat()})

    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body['totals']['expired'] == 1
    assert set(body) == {'period', 'filters', 'totals', 'previous', 'comparison', 'upcoming',
                         'by_plan', 'series'}


@pytest.mark.parametrize('role', ['manager', 'monitor', 'teacher', 'student'])
def test_no_other_organization_role_can_read_the_report(api_client, org, make_user, role):
    actor = make_user(f'{role}-ret', organization=org, role=role)
    api_client.force_authenticate(user=actor)

    resp = api_client.get(URL)

    assert resp.status_code == 403, resp.content


def test_superadmin_cannot_read_the_report_either(api_client, make_user):
    root = make_user('root-ret', organization=None, role='superadmin')
    api_client.force_authenticate(user=root)

    resp = api_client.get(URL)

    assert resp.status_code == 403, resp.content


def test_unauthenticated_request_is_rejected(api_client):
    assert api_client.get(URL).status_code == 401


def test_a_plan_id_of_another_organization_is_404(api_client, org, admin, other_org):
    foreign_plan = _plan(other_org, name='Plan ajeno')
    api_client.force_authenticate(user=admin)

    resp = api_client.get(URL, {'plan_id': foreign_plan.id})

    assert resp.status_code == 404, resp.content
