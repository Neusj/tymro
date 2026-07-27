"""Dos huecos del alcance por sucursal detectados en revisión.

1. El importador de membresías construye `StudentPlan` sin `branch`, mientras que
   `activate_student_plan` y el backfill de la migración sí lo derivan del plan.
   Onboardear un gimnasio por importador dejaba todas las membresías de planes
   exclusivos con `branch=NULL`.
2. `BranchSerializer` deja `organization` editable para superadmin, así que una sucursal
   se podía mover de organización dejando atrás sus dependientes. Con `Plan.branch` eso
   pasa a filtrar el nombre de una sucursal ajena en `GET /api/plans/` (`branch_name`) y
   deja la organización destino sin poder borrarse (RESTRICT → 500).
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from core.models import Branch, GymClass, Plan

pytestmark = pytest.mark.django_db

PASSWORD = 'Passw0rd2026'


def _login(api_client, username):
    from django.contrib.auth import get_user_model
    user = get_user_model().objects.get(username=username)
    host = {'HTTP_HOST': f'{user.organization.subdomain}.localhost'} if user.organization_id else {}
    token = api_client.post(
        '/api/login/', {'email': user.email, 'password': PASSWORD}, format='json', **host
    ).json()['token']
    api_client.credentials(HTTP_AUTHORIZATION=f'Token {token}')


@pytest.fixture
def setup(make_organization, make_user):
    org = make_organization()
    make_user('admin', organization=org, role='gym_admin')
    student = make_user('alu', organization=org, role='student', email='alu@gym.cl')
    centro = Branch.objects.create(organization=org, name='Sede Centro')
    return {'org': org, 'student': student, 'centro': centro}


# --- 1. Importador de membresías -------------------------------------------------


def test_importer_records_branch_on_membership_of_exclusive_plan(setup):
    from core.importer.specs.memberships import _build_membership

    plan = Plan.objects.create(
        organization=setup['org'], branch=setup['centro'], name='Pack Centro',
        plan_type='pack', total_classes=10, duration_days=30, price=30000,
    )

    membership = _build_membership(
        {'user': setup['student'], 'plan': plan, 'start_date': timezone.localdate()},
        setup['org'],
    )

    assert membership.branch_id == setup['centro'].id


def test_importer_leaves_branch_null_for_global_plan(setup):
    from core.importer.specs.memberships import _build_membership

    plan = Plan.objects.create(
        organization=setup['org'], branch=None, name='Pack Global',
        plan_type='pack', total_classes=10, duration_days=30, price=30000,
    )

    membership = _build_membership(
        {'user': setup['student'], 'plan': plan, 'start_date': timezone.localdate()},
        setup['org'],
    )

    assert membership.branch_id is None


# --- 2. Mover una sucursal de organización ---------------------------------------


def test_superadmin_cannot_move_branch_with_dependents_to_another_org(
    api_client, setup, make_organization, make_user,
):
    """Mover la sucursal dejaría sus planes/clases apuntando cross-tenant."""
    Plan.objects.create(
        organization=setup['org'], branch=setup['centro'], name='Exclusivo',
        plan_type='pack', total_classes=10, duration_days=30, price=30000,
    )
    other_org = make_organization(name='Otra Org')
    make_user('root', role='superadmin', organization=None)
    _login(api_client, 'root')

    resp = api_client.patch(
        f'/api/branches/{setup["centro"].id}/',
        {'organization': other_org.id}, format='json',
    )

    assert resp.status_code == 400, resp.content
    setup['centro'].refresh_from_db()
    assert setup['centro'].organization_id == setup['org'].id


def test_plan_never_exposes_a_branch_name_from_another_org(
    api_client, setup, make_organization, make_user,
):
    """El nombre de la sucursal no puede filtrarse entre organizaciones vía branch_name."""
    Plan.objects.create(
        organization=setup['org'], branch=setup['centro'], name='Exclusivo',
        plan_type='pack', total_classes=10, duration_days=30, price=30000,
    )
    other_org = make_organization(name='Otra Org')
    make_user('root', role='superadmin', organization=None)
    _login(api_client, 'root')
    api_client.patch(
        f'/api/branches/{setup["centro"].id}/', {'organization': other_org.id}, format='json',
    )

    _login(api_client, 'admin')
    rows = api_client.get('/api/plans/').json()

    for row in rows:
        plan = Plan.objects.get(id=row['id'])
        if plan.branch_id:
            assert plan.branch.organization_id == plan.organization_id, (
                'un plan quedó apuntando a una sucursal de otra organización'
            )


def test_superadmin_can_still_move_a_branch_without_dependents(
    api_client, setup, make_organization, make_user,
):
    """Regresión: sin dependientes el movimiento sigue permitido."""
    empty = Branch.objects.create(organization=setup['org'], name='Sede Vacia')
    other_org = make_organization(name='Otra Org')
    make_user('root', role='superadmin', organization=None)
    _login(api_client, 'root')

    resp = api_client.patch(
        f'/api/branches/{empty.id}/', {'organization': other_org.id}, format='json',
    )

    assert resp.status_code == 200, resp.content
    empty.refresh_from_db()
    assert empty.organization_id == other_org.id


def test_superadmin_cannot_move_branch_with_classes(
    api_client, setup, make_organization, make_user,
):
    start = timezone.now() + timedelta(days=1)
    teacher = make_user('teach', organization=setup['org'], role='teacher')
    GymClass.objects.create(
        organization=setup['org'], branch=setup['centro'], teacher=teacher,
        name='Clase', start_datetime=start, end_datetime=start + timedelta(hours=1),
        capacity=10,
    )
    other_org = make_organization(name='Otra Org')
    make_user('root', role='superadmin', organization=None)
    _login(api_client, 'root')

    resp = api_client.patch(
        f'/api/branches/{setup["centro"].id}/',
        {'organization': other_org.id}, format='json',
    )

    assert resp.status_code == 400, resp.content
