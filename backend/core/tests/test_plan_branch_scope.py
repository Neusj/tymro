"""Alcance de sucursal en planes.

`Plan.branch` NULL = plan GLOBAL (vale en toda la organización). Con sucursal = plan
EXCLUSIVO (solo cubre las clases de esa sede). `StudentPlan.branch` y
`ConsumptionLog.branch` registran dónde se activó la membresía y dónde se consumió la
sesión.

Ojo con la semántica de NULL: igual que en `TeacherPaymentRule.branch`, aquí NULL
significa "todas las sedes", así que borrar una sucursal no puede dejar sus planes
exclusivos en NULL (los volvería globales). Por eso el borrado de sucursal también se
bloquea cuando hay planes exclusivos.
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from core.models import Branch, ConsumptionLog, GymClass, Plan, StudentPlan

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
    admin = make_user('admin', organization=org, role='gym_admin')
    teacher = make_user('teach', organization=org, role='teacher')
    student = make_user('alu', organization=org, role='student', email='alu@gym.cl')
    centro = Branch.objects.create(organization=org, name='Sede Centro')
    barrio = Branch.objects.create(organization=org, name='Sede Barrio')
    return {
        'org': org, 'admin': admin, 'teacher': teacher, 'student': student,
        'centro': centro, 'barrio': barrio,
    }


def _plan(setup, branch=None, name='Pack 10'):
    return Plan.objects.create(
        organization=setup['org'], branch=branch, name=name, plan_type='pack',
        total_classes=10, duration_days=30, price=30000,
    )


def _student_plan(setup, plan):
    today = timezone.localdate()
    return StudentPlan.objects.create(
        user=setup['student'], plan=plan, branch=plan.branch,
        start_date=today - timedelta(days=1), end_date=today + timedelta(days=30),
        total_classes=10, classes_used=0, final_price=30000,
    )


def _future_class(setup, branch, days=1):
    # `days` separa las clases en el tiempo: dos clases a la misma hora chocarían con la
    # regla de solape del alumno y enmascararían lo que se está testeando (la sucursal).
    start = timezone.now() + timedelta(days=days)
    return GymClass.objects.create(
        organization=setup['org'], branch=branch, teacher=setup['teacher'],
        name=f'Clase {branch.name} +{days}d', start_datetime=start,
        end_datetime=start + timedelta(hours=1), capacity=10,
        status=GymClass.Status.SCHEDULED,
    )


def _reserve(api_client, gym_class):
    return api_client.post(
        '/api/enrollments/', {'gym_class': gym_class.id}, format='json',
    )


# --- A. Plan GLOBAL: reserva en cualquier sucursal ------------------------------


def test_global_plan_reserves_in_any_branch(api_client, setup):
    plan = _plan(setup, branch=None)
    _student_plan(setup, plan)
    _login(api_client, 'alu')

    for days, branch in enumerate((setup['centro'], setup['barrio']), start=1):
        resp = _reserve(api_client, _future_class(setup, branch, days=days))
        assert resp.status_code == 201, f'{branch.name}: {resp.content}'


# --- B. Plan EXCLUSIVO: solo su sucursal ----------------------------------------


def test_exclusive_plan_reserves_in_its_own_branch(api_client, setup):
    plan = _plan(setup, branch=setup['centro'])
    _student_plan(setup, plan)
    _login(api_client, 'alu')

    resp = _reserve(api_client, _future_class(setup, setup['centro']))

    assert resp.status_code == 201, resp.content


def test_exclusive_plan_blocked_outside_its_branch(api_client, setup):
    plan = _plan(setup, branch=setup['centro'])
    student_plan = _student_plan(setup, plan)
    _login(api_client, 'alu')

    resp = _reserve(api_client, _future_class(setup, setup['barrio']))

    assert resp.status_code == 400, resp.content
    assert 'exclusivo' in str(resp.content, 'utf-8').lower()
    student_plan.refresh_from_db()
    assert student_plan.classes_used == 0, 'una reserva rechazada no debe consumir saldo'


def test_exclusive_plan_rejection_creates_no_enrollment(api_client, setup):
    from core.models import Enrollment

    plan = _plan(setup, branch=setup['centro'])
    _student_plan(setup, plan)
    gym_class = _future_class(setup, setup['barrio'])
    _login(api_client, 'alu')

    _reserve(api_client, gym_class)

    assert not Enrollment.objects.filter(gym_class=gym_class).exists()


def test_admin_cannot_enroll_student_outside_exclusive_plan_branch(api_client, setup):
    """La regla vive en el servicio de reservas, así que aplica también cuando el que
    inscribe es un admin, no solo el alumno."""
    plan = _plan(setup, branch=setup['centro'])
    _student_plan(setup, plan)
    _login(api_client, 'admin')

    resp = api_client.post('/api/enrollments/', {
        'gym_class': _future_class(setup, setup['barrio']).id,
        'student': setup['student'].id,
    }, format='json')

    assert resp.status_code == 400, resp.content


# --- C. Registro de sucursal en membresía y consumo -----------------------------


def test_consumption_log_records_the_class_branch(api_client, setup):
    plan = _plan(setup, branch=None)
    _student_plan(setup, plan)
    gym_class = _future_class(setup, setup['barrio'])
    _login(api_client, 'alu')

    assert _reserve(api_client, gym_class).status_code == 201

    log = ConsumptionLog.objects.get(class_instance=gym_class, user=setup['student'])
    assert log.branch_id == setup['barrio'].id


def test_activate_student_plan_records_the_plan_branch(setup):
    from core.services.plans import activate_student_plan

    plan = _plan(setup, branch=setup['centro'])

    student_plan = activate_student_plan(
        student=setup['student'], plan=plan, start_date=timezone.localdate(),
    )

    assert student_plan.branch_id == setup['centro'].id


def test_activate_global_plan_leaves_branch_null(setup):
    from core.services.plans import activate_student_plan

    plan = _plan(setup, branch=None)

    student_plan = activate_student_plan(
        student=setup['student'], plan=plan, start_date=timezone.localdate(),
    )

    assert student_plan.branch_id is None


# --- D. Multitenancy: la sucursal del plan no puede cruzar organizaciones --------


def test_gym_admin_cannot_set_branch_from_another_org_on_a_plan(
    api_client, setup, make_organization,
):
    other_org = make_organization(name='Otra Org')
    foreign_branch = Branch.objects.create(organization=other_org, name='Sede Ajena')
    _login(api_client, 'admin')

    resp = api_client.post('/api/plans/', {
        'name': 'Pack ajeno', 'plan_type': 'pack', 'total_classes': 10,
        'duration_days': 30, 'price': 30000, 'branch': foreign_branch.id,
    }, format='json')

    assert resp.status_code == 400, resp.content
    assert 'branch' in resp.json(), resp.content


def test_gym_admin_can_create_exclusive_plan_in_own_branch(api_client, setup):
    _login(api_client, 'admin')

    resp = api_client.post('/api/plans/', {
        'name': 'Pack Centro', 'plan_type': 'pack', 'total_classes': 10,
        'duration_days': 30, 'price': 30000, 'branch': setup['centro'].id,
    }, format='json')

    assert resp.status_code == 201, resp.content
    assert Plan.objects.get(id=resp.json()['id']).branch_id == setup['centro'].id


def test_plan_branch_is_exposed_in_the_api(api_client, setup):
    _plan(setup, branch=setup['centro'], name='Exclusivo')
    _login(api_client, 'admin')

    rows = api_client.get('/api/plans/').json()
    row = next(r for r in rows if r['name'] == 'Exclusivo')

    assert row['branch'] == setup['centro'].id
    assert row['branch_name'] == 'Sede Centro'


# --- E. El borrado de sucursal no puede huerfanar planes exclusivos --------------


def test_delete_branch_with_exclusive_plans_is_blocked(api_client, setup):
    plan = _plan(setup, branch=setup['centro'])
    _login(api_client, 'admin')

    resp = api_client.delete(f'/api/branches/{setup["centro"].id}/')

    assert resp.status_code == 400, resp.content
    plan.refresh_from_db()
    assert plan.branch_id == setup['centro'].id, 'el plan no debe volverse global'
    setup['centro'].refresh_from_db()
    assert setup['centro'].is_active is False


def test_delete_branch_without_exclusive_plans_still_works(api_client, setup):
    _plan(setup, branch=None)  # plan global: no ata a ninguna sucursal
    _login(api_client, 'admin')

    resp = api_client.delete(f'/api/branches/{setup["centro"].id}/')

    assert resp.status_code == 204, resp.content


# --- E bis. Backstop a nivel DB: por qué Plan.branch es RESTRICT y no SET_NULL ---


def test_direct_branch_delete_with_exclusive_plan_raises_at_db_level(setup):
    """Aunque alguien esquive la guarda de la API (admin de Django, shell), la FK debe
    impedir que el plan exclusivo quede en NULL, que es decir 'global'."""
    from django.db.models import RestrictedError

    _plan(setup, branch=setup['centro'])

    with pytest.raises(RestrictedError):
        setup['centro'].delete()


def test_org_delete_still_cascades_through_restricted_plan_branch(setup):
    """RESTRICT no puede romper el borrado de organización: ahí el plan también se
    elimina en cascada, así que Django lo permite."""
    from core.models import Organization

    _plan(setup, branch=setup['centro'])
    org_id = setup['org'].id

    setup['org'].delete()

    assert not Organization.objects.filter(id=org_id).exists()
    assert not Plan.objects.filter(organization_id=org_id).exists()


# --- F. Backfill de la migración -------------------------------------------------


def test_migration_backfills_consumption_log_branch_from_class(setup):
    """La migración deriva `ConsumptionLog.branch` de `class_instance.branch`. Se
    simula una fila pre-migración (branch=NULL) y se corre la función de datos."""
    from importlib import import_module

    from django.apps import apps as global_apps

    plan = _plan(setup, branch=None)
    student_plan = _student_plan(setup, plan)
    gym_class = _future_class(setup, setup['barrio'])
    log = ConsumptionLog.objects.create(
        user=setup['student'], student_plan=student_plan, class_instance=gym_class,
    )
    ConsumptionLog.objects.filter(id=log.id).update(branch=None)

    module = import_module('core.migrations.0029_plan_studentplan_consumptionlog_branch')
    module.backfill_consumption_branch(global_apps, None)

    log.refresh_from_db()
    assert log.branch_id == setup['barrio'].id


def test_migration_backfill_leaves_no_orphans(setup):
    """Tras el backfill no debe quedar ningún ConsumptionLog sin sucursal, porque
    `GymClass.branch` es obligatoria."""
    from importlib import import_module

    from django.apps import apps as global_apps

    plan = _plan(setup, branch=None)
    student_plan = _student_plan(setup, plan)
    for branch in (setup['centro'], setup['barrio']):
        log = ConsumptionLog.objects.create(
            user=setup['student'], student_plan=student_plan,
            class_instance=_future_class(setup, branch),
        )
        ConsumptionLog.objects.filter(id=log.id).update(branch=None)

    module = import_module('core.migrations.0029_plan_studentplan_consumptionlog_branch')
    module.backfill_consumption_branch(global_apps, None)

    assert not ConsumptionLog.objects.filter(branch__isnull=True).exists()
