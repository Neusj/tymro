"""Ronda 4 — capacidades de manager y monitor.

Manager = mismo acceso que gym_admin sobre recursos operativos (grupo a), scoped a
su organización; NADA sobre pagos/planes (403) y solo lectura en sucursales.
Monitor = solo lectura sobre todo lo de su organización; escritura -> 403.
Ni manager ni monitor ven jamás otra organización.

Auth vía force_authenticate (la autenticación ya está cubierta en test_auth)."""
from datetime import date, time, timedelta

import pytest
from django.utils import timezone

from core.models import (
    Branch,
    ClassTemplate,
    ClassType,
    Discipline,
    Enrollment,
    GymClass,
    Holiday,
    Plan,
    TeacherPaymentRule,
)

pytestmark = pytest.mark.django_db

DENIED = (400, 403)


def _build_org(make_organization, make_user, suffix):
    org = make_organization(name=f'Gym {suffix}')
    gym_admin = make_user(f'admin_{suffix}', organization=org, role='gym_admin')
    manager = make_user(f'manager_{suffix}', organization=org, role='manager')
    monitor = make_user(f'monitor_{suffix}', organization=org, role='monitor')
    teacher = make_user(f'teacher_{suffix}', organization=org, role='teacher')
    student = make_user(f'student_{suffix}', organization=org, role='student')

    branch = Branch.objects.create(organization=org, name=f'Sede {suffix}')
    class_type = ClassType.objects.create(organization=org, name=f'Tipo {suffix}')
    discipline = Discipline.objects.create(organization=org, name=f'Disciplina {suffix}')

    start = timezone.now() + timedelta(days=1)
    gym_class = GymClass.objects.create(
        organization=org,
        branch=branch,
        teacher=teacher,
        class_type=class_type,
        discipline=discipline,
        name=f'Clase {suffix}',
        start_datetime=start,
        end_datetime=start + timedelta(hours=1),
    )
    enrollment = Enrollment.objects.create(gym_class=gym_class, student=student, status='active')

    template = ClassTemplate.objects.create(
        organization=org,
        branch=branch,
        name=f'Plantilla {suffix}',
        weekday=ClassTemplate.Weekday.MONDAY,
        start_time=time(10, 0),
        end_time=time(11, 0),
        start_date=date(2026, 1, 5),
    )
    plan = Plan.objects.create(
        organization=org,
        name=f'Plan {suffix}',
        plan_type=Plan.PlanType.MONTHLY,
        total_classes=8,
        duration_days=30,
        price=30000,
    )
    payment_rule = TeacherPaymentRule.objects.create(
        organization=org,
        payment_type=TeacherPaymentRule.PaymentType.FIXED_PER_CLASS,
        amount=10000,
    )
    holiday = Holiday.objects.create(
        organization=org,
        date=date(2026, 9, 18),
        name=f'Feriado {suffix}',
        scope=Holiday.Scope.ORGANIZATION,
    )
    return {
        'org': org, 'gym_admin': gym_admin, 'manager': manager, 'monitor': monitor,
        'teacher': teacher, 'student': student, 'branch': branch, 'class_type': class_type,
        'discipline': discipline, 'gym_class': gym_class, 'enrollment': enrollment,
        'template': template, 'plan': plan, 'payment_rule': payment_rule, 'holiday': holiday,
    }


@pytest.fixture
def org_a(make_organization, make_user):
    return _build_org(make_organization, make_user, 'A')


@pytest.fixture
def org_b(make_organization, make_user):
    return _build_org(make_organization, make_user, 'B')


def _ids(payload):
    items = payload['results'] if isinstance(payload, dict) and 'results' in payload else payload
    return {item['id'] for item in items}


# ---------------------------------------------------------------------------
# 1. Manager: escritura en grupo (a), scoped a su org
# ---------------------------------------------------------------------------

def test_manager_writes_operational_resources(api_client, org_a):
    api_client.force_authenticate(user=org_a['manager'])
    org = org_a['org']

    assert api_client.post('/api/class-types/', {'name': 'Spinning', 'organization': org.id}, format='json').status_code == 201
    assert api_client.post('/api/disciplines/', {'name': 'Yoga', 'organization': org.id}, format='json').status_code == 201
    assert api_client.post(
        '/api/holidays/',
        {'name': 'Aniversario', 'date': '2026-10-10', 'scope': 'organization', 'organization': org.id},
        format='json',
    ).status_code == 201

    patch = api_client.patch(f"/api/classes/{org_a['gym_class'].id}/", {'name': 'Clase editada'}, format='json')
    assert patch.status_code == 200
    assert api_client.delete(f"/api/enrollments/{org_a['enrollment'].id}/").status_code == 204


def test_manager_create_is_forced_to_own_org(api_client, org_a, org_b):
    """Manager A intenta crear un tipo de clase en la org B: se fuerza a su propia org."""
    api_client.force_authenticate(user=org_a['manager'])
    response = api_client.post('/api/class-types/', {'name': 'Crossfit', 'organization': org_b['org'].id}, format='json')
    assert response.status_code == 201
    assert response.json()['organization'] == org_a['org'].id


# ---------------------------------------------------------------------------
# 2. Manager: grupo (b) — sucursales solo lectura; pagos/planes 403 total
# ---------------------------------------------------------------------------

def test_manager_branches_read_only(api_client, org_a):
    api_client.force_authenticate(user=org_a['manager'])
    listing = api_client.get('/api/branches/')
    assert listing.status_code == 200
    assert org_a['branch'].id in _ids(listing.json())

    assert api_client.post('/api/branches/', {'name': 'Nueva sede', 'organization': org_a['org'].id}, format='json').status_code in DENIED
    assert api_client.patch(f"/api/branches/{org_a['branch'].id}/", {'name': 'x'}, format='json').status_code in DENIED


def test_manager_blocked_from_finance(api_client, org_a):
    api_client.force_authenticate(user=org_a['manager'])
    assert api_client.get('/api/plans/').status_code == 403
    assert api_client.post('/api/plans/', {'name': 'P', 'organization': org_a['org'].id}, format='json').status_code == 403
    assert api_client.get('/api/teacher-payment-rules/').status_code == 403
    assert api_client.get('/api/teacher-payments/').status_code == 403


# ---------------------------------------------------------------------------
# 3. Monitor: lectura (200) sobre todos los recursos de su org
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('url_key', [
    ('/api/classes/', 'gym_class'),
    ('/api/class-types/', 'class_type'),
    ('/api/disciplines/', 'discipline'),
    ('/api/class-templates/', 'template'),
    ('/api/enrollments/', 'enrollment'),
    ('/api/branches/', 'branch'),
    ('/api/holidays/', 'holiday'),
    ('/api/plans/', 'plan'),
    ('/api/teacher-payment-rules/', 'payment_rule'),
])
def test_monitor_reads_own_org(api_client, org_a, url_key):
    url, obj_key = url_key
    api_client.force_authenticate(user=org_a['monitor'])
    response = api_client.get(url)
    assert response.status_code == 200
    assert org_a[obj_key].id in _ids(response.json())


def test_monitor_reads_teacher_payments_list(api_client, org_a):
    api_client.force_authenticate(user=org_a['monitor'])
    assert api_client.get('/api/teacher-payments/').status_code == 200


# ---------------------------------------------------------------------------
# 4. Monitor: cualquier escritura -> 403
# ---------------------------------------------------------------------------

def test_monitor_cannot_write(api_client, org_a):
    api_client.force_authenticate(user=org_a['monitor'])
    org = org_a['org']
    assert api_client.post('/api/class-types/', {'name': 'X', 'organization': org.id}, format='json').status_code in DENIED
    assert api_client.post('/api/classes/', {'name': 'X', 'organization': org.id}, format='json').status_code in DENIED
    assert api_client.patch(f"/api/classes/{org_a['gym_class'].id}/", {'name': 'X'}, format='json').status_code in DENIED
    assert api_client.post('/api/branches/', {'name': 'X', 'organization': org.id}, format='json').status_code in DENIED
    assert api_client.post('/api/plans/', {'name': 'X', 'organization': org.id}, format='json').status_code in DENIED
    assert api_client.post('/api/holidays/', {'name': 'X', 'date': '2026-10-10', 'scope': 'organization', 'organization': org.id}, format='json').status_code in DENIED
    assert api_client.patch(f"/api/enrollments/{org_a['enrollment'].id}/", {'status': 'cancelled'}, format='json').status_code in DENIED
    assert api_client.delete(f"/api/enrollments/{org_a['enrollment'].id}/").status_code in DENIED


# ---------------------------------------------------------------------------
# 5. Multi-tenant (riesgo #1): manager/monitor nunca ven otra org
# ---------------------------------------------------------------------------

def test_manager_cannot_reach_other_org(api_client, org_a, org_b):
    api_client.force_authenticate(user=org_a['manager'])

    classes = api_client.get('/api/classes/')
    assert classes.status_code == 200
    ids = _ids(classes.json())
    assert org_a['gym_class'].id in ids
    assert org_b['gym_class'].id not in ids

    assert api_client.get(f"/api/classes/{org_b['gym_class'].id}/").status_code == 404
    assert api_client.patch(f"/api/classes/{org_b['gym_class'].id}/", {'name': 'hack'}, format='json').status_code == 404
    org_b['gym_class'].refresh_from_db()
    assert org_b['gym_class'].name == 'Clase B'


def test_monitor_cannot_reach_other_org(api_client, org_a, org_b):
    api_client.force_authenticate(user=org_a['monitor'])

    class_types = api_client.get('/api/class-types/')
    assert class_types.status_code == 200
    ct_ids = _ids(class_types.json())
    assert org_a['class_type'].id in ct_ids
    assert org_b['class_type'].id not in ct_ids

    plans = api_client.get('/api/plans/')
    assert plans.status_code == 200
    plan_ids = _ids(plans.json())
    assert org_a['plan'].id in plan_ids
    assert org_b['plan'].id not in plan_ids
    assert api_client.get(f"/api/plans/{org_b['plan'].id}/").status_code == 404
