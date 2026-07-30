"""Los lectores de membresías resuelven la organización por la COLUMNA, no por el join (7.2).

`StudentPlan.organization` (7.1) es una copia de `plan.organization` que registra quién
VENDIÓ la membresía. Los lectores seguían llegando a la organización atravesando el plan
(`plan__organization_id`) o —peor— por el usuario (`user__organization_id`), y las tres
rutas se separan en casos reales:

* `user__organization_id`: un alumno movido de la org A a la org B deja de aparecer en las
  membresías que le vendió A, o sea el gym que cobró pierde de vista su propia venta.
* `plan__organization_id`: `Plan` no tiene `clean()` y nada revalida las membresías que
  cuelgan de él, así que mover un plan de organización se lleva puestas las ventas
  históricas. La columna se queda con el vendedor, que es la semántica declarada.
"""
from datetime import timedelta

import pytest
from django.test.utils import CaptureQueriesContext
from django.db import connection
from django.utils import timezone

from core.models import Plan, StudentPlan
from core.services.reservations import get_active_student_plan

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()


def _plan(org, name='Pack'):
    return Plan.objects.create(
        organization=org, name=name, plan_type='pack', total_classes=10,
        duration_days=30, price=30000,
    )


def _membership(student, plan, classes_used=0):
    return StudentPlan.objects.create(
        user=student, plan=plan, organization_id=plan.organization_id,
        start_date=TODAY - timedelta(days=1), end_date=TODAY + timedelta(days=29),
        total_classes=plan.total_classes, classes_used=classes_used,
        final_price=30000, is_active=True,
    )


@pytest.fixture
def sale_of_org_a(make_organization, make_user):
    """La org A le vendió una membresía a un alumno que hoy está en la org B."""
    org_a = make_organization()
    org_b = make_organization()
    student = make_user('nomade-col', organization=org_a, role='student')
    plan = _plan(org_a, 'Pack de A')
    membership = _membership(student, plan)

    student.organization = org_b
    student.save(update_fields=['organization'])

    return {
        'org_a': org_a,
        'org_b': org_b,
        'student': student,
        'plan': plan,
        'membership': membership,
        'admin_a': make_user('admin-a-col', organization=org_a, role='gym_admin'),
    }


# --------------------------------------------------------------------------------------
# user__organization_id -> organization: el vendedor no pierde su venta
# --------------------------------------------------------------------------------------

def test_memberships_action_still_lists_the_sale_of_a_student_who_moved_out(api_client, sale_of_org_a):
    """El gym_admin de A vendió la membresía y tiene que seguir viéndola.

    Scopeaba por `user__organization_id`, así que al mover al alumno a la org B la venta
    desaparecía del listado del plan —del propio plan de A, mirado por el admin de A—.
    """
    api_client.force_authenticate(user=sale_of_org_a['admin_a'])

    resp = api_client.get(f'/api/plans/{sale_of_org_a["plan"].id}/memberships/')

    assert resp.status_code == 200, resp.content
    assert [row['id'] for row in resp.json()] == [sale_of_org_a['membership'].id]


def test_remove_membership_still_reaches_the_sale_of_a_student_who_moved_out(api_client, sale_of_org_a):
    """Misma frontera del lado de la escritura: si el admin de A no la ve, tampoco la puede
    quitar, y la membresía queda inalcanzable para el único tenant con derecho a tocarla."""
    api_client.force_authenticate(user=sale_of_org_a['admin_a'])

    resp = api_client.delete(
        f'/api/plans/{sale_of_org_a["plan"].id}/memberships/{sale_of_org_a["membership"].id}/'
    )

    assert resp.status_code == 204, resp.content
    assert not StudentPlan.objects.filter(id=sale_of_org_a['membership'].id).exists()


def test_memberships_action_does_not_leak_a_sale_of_another_org(api_client, make_organization, make_user):
    """Contra-prueba de la anterior: la columna sigue siendo una frontera.

    El admin de A no puede ver una membresía vendida por B ni siquiera si el alumno está
    hoy en A —el caso simétrico al del test anterior—.
    """
    org_a = make_organization()
    org_b = make_organization()
    student = make_user('cruzado-col', organization=org_b, role='student')
    plan_b = _plan(org_b, 'Pack de B')
    _membership(student, plan_b)
    student.organization = org_a
    student.save(update_fields=['organization'])
    admin_a = make_user('admin-a2-col', organization=org_a, role='gym_admin')
    api_client.force_authenticate(user=admin_a)

    resp = api_client.get(f'/api/plans/{plan_b.id}/memberships/')

    assert resp.status_code == 404, resp.content


# --------------------------------------------------------------------------------------
# plan__organization_id -> organization: la venta se queda con el vendedor
# --------------------------------------------------------------------------------------

def test_active_membership_lookup_reads_the_stored_organization_not_the_plans(make_organization, make_user):
    """Mover el PLAN de organización no puede mover las ventas históricas.

    `Plan` no tiene `clean()` y nada revalida sus membresías, así que este cambio es
    reachable. Con el scope por join, la membresía se iba con el plan a la otra
    organización y el alumno se quedaba sin plan vigente de un momento a otro.
    """
    org_a = make_organization()
    org_b = make_organization()
    student = make_user('stu-moved-plan', organization=org_a, role='student')
    plan = _plan(org_a)
    membership = _membership(student, plan)

    plan.organization = org_b
    plan.save(update_fields=['organization'])

    assert get_active_student_plan(student, on_date=TODAY) == membership


def test_my_memberships_reads_the_stored_organization_not_the_plans(api_client, make_organization, make_user):
    org_a = make_organization()
    org_b = make_organization()
    student = make_user('stu-mine-col', organization=org_a, role='student')
    plan = _plan(org_a)
    membership = _membership(student, plan)

    plan.organization = org_b
    plan.save(update_fields=['organization'])

    api_client.force_authenticate(user=student)
    resp = api_client.get('/api/plans/my-memberships/')

    assert resp.status_code == 200, resp.content
    assert [row['id'] for row in resp.json()] == [membership.id]


def test_active_membership_lookup_does_not_join_the_plan_table(make_organization, make_user):
    """El objetivo explícito de migrar a la columna: sacar el join del camino caliente.

    `get_active_student_plan` corre en cada reserva. Sin `select_related('plan')` de por
    medio, su consulta no tiene ninguna razón para tocar `core_plan`.
    """
    org = make_organization()
    student = make_user('stu-nojoin', organization=org, role='student')
    _membership(student, _plan(org))

    with CaptureQueriesContext(connection) as captured:
        get_active_student_plan(student, on_date=TODAY)

    sql = ' '.join(q['sql'] for q in captured.captured_queries)
    assert 'core_studentplan' in sql, sql
    assert 'core_plan' not in sql, f'la consulta sigue atravesando el plan: {sql}'
