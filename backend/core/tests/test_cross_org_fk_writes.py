"""Ninguna escritura puede aceptar una FK que apunte a OTRA organización.

Forzar `organization=user.organization` en `perform_create` no alcanza: la fila queda en
la org correcta, pero con una FK prestada de otra. Es la variante silenciosa del riesgo #1
—no filtra un listado, ata dos tenants por una FK— y abre consecuencias reales: nombres de
otra org que se serializan de vuelta, `RESTRICT`/`SET_NULL` que cruzan el borde al borrar,
y pagos calculados para un profesor ajeno.

La mayoría de los serializers ya lo valida (`GymClassSerializer` chequea branch,
class_type, discipline, class_template Y teacher; `PlanSerializer`, `HolidaySerializer`,
`CustomUserSerializer` y `TeacherPaymentRuleSerializer` chequean su branch). Este archivo
cierra los dos que faltaban y ancla los que ya estaban bien.
"""
from datetime import time, timedelta

import pytest
from django.utils import timezone

from core.models import (
    Branch,
    ClassTemplate,
    ClassType,
    Discipline,
    GymClass,
    Person,
    Plan,
)

pytestmark = pytest.mark.django_db

PASSWORD = 'Passw0rd2026'


def _login(api_client, user):
    host = {'HTTP_HOST': f'{user.organization.subdomain}.localhost'} if user.organization_id else {}
    token = api_client.post(
        '/api/login/', {'email': user.email, 'password': PASSWORD}, format='json', **host
    ).json()['token']
    api_client.credentials(HTTP_AUTHORIZATION=f'Token {token}')


@pytest.fixture
def orgs(make_organization, make_user):
    org_a = make_organization()
    org_b = make_organization()
    return {
        'a': org_a,
        'b': org_b,
        'admin_a': make_user('admin_a', organization=org_a, role='gym_admin'),
        'teacher_a': make_user('teach_a', organization=org_a, role='teacher'),
        'branch_a': Branch.objects.create(organization=org_a, name='Sede A'),
        'class_type_a': ClassType.objects.create(organization=org_a, name='Funcional A'),
        'discipline_a': Discipline.objects.create(organization=org_a, name='Yoga A'),
        # Los objetos AJENOS que el atacante va a intentar referenciar.
        'branch_b': Branch.objects.create(organization=org_b, name='Sede B'),
        'teacher_b': make_user('teach_b', organization=org_b, role='teacher'),
        'class_type_b': ClassType.objects.create(organization=org_b, name='Funcional B'),
        'discipline_b': Discipline.objects.create(organization=org_b, name='Yoga B'),
    }


# ---------------------------------------------------------------------------
# Person.branch — no se validaba
# ---------------------------------------------------------------------------

def test_person_cannot_borrow_a_branch_from_another_org(api_client, orgs):
    """`PersonSerializer.validate` descartaba el `organization` del payload pero nunca
    miraba `branch`: la persona quedaba en la org A colgada de una sede de la org B."""
    _login(api_client, orgs['admin_a'])

    resp = api_client.post('/api/people/', {
        'first_name': 'Ana', 'last_name': 'Perez', 'role': 'student',
        'branch': orgs['branch_b'].id,
    }, format='json')

    assert resp.status_code == 400, resp.content
    assert not Person.objects.filter(branch=orgs['branch_b']).exists()


def test_person_update_cannot_borrow_a_branch_from_another_org(api_client, orgs):
    """Mismo agujero por PATCH sobre una persona propia."""
    person = Person.objects.create(
        organization=orgs['a'], branch=orgs['branch_a'],
        first_name='Ana', role='student',
    )
    _login(api_client, orgs['admin_a'])

    resp = api_client.patch(f'/api/people/{person.id}/', {
        'branch': orgs['branch_b'].id,
    }, format='json')

    assert resp.status_code == 400, resp.content
    person.refresh_from_db()
    assert person.branch_id == orgs['branch_a'].id


def test_person_accepts_a_branch_of_its_own_org(api_client, orgs):
    """Regresión: la sede propia sigue funcionando."""
    _login(api_client, orgs['admin_a'])

    resp = api_client.post('/api/people/', {
        'first_name': 'Ana', 'role': 'student', 'branch': orgs['branch_a'].id,
    }, format='json')

    assert resp.status_code == 201, resp.content
    assert Person.objects.get(id=resp.json()['id']).branch_id == orgs['branch_a'].id


# ---------------------------------------------------------------------------
# ClassTemplate.teacher — no se validaba
# ---------------------------------------------------------------------------

def _template_payload(orgs, **overrides):
    payload = {
        'name': 'Serie', 'branch': orgs['branch_a'].id, 'teacher': orgs['teacher_a'].id,
        'class_type': orgs['class_type_a'].id, 'discipline': orgs['discipline_a'].id,
        'weekday': 0, 'start_time': '10:00', 'end_time': '11:00', 'capacity': 10,
        'start_date': str(timezone.localdate()),
        'end_date': str(timezone.localdate() + timedelta(days=14)),
    }
    payload.update(overrides)
    return payload


def test_template_cannot_borrow_a_teacher_from_another_org(api_client, orgs):
    """`ClassTemplate.clean()` validaba branch, class_type y discipline contra la org,
    y del profesor solo el ROL. Un profe de otra org pasaba, y las instancias que la
    serie genera no vuelven a pasar por `GymClassSerializer` (que sí lo valida): quedan
    clases de la org A dictadas por un profe de la org B, y con eso el cálculo de
    `TeacherPaymentRecord` cruza el borde."""
    _login(api_client, orgs['admin_a'])

    resp = api_client.post(
        '/api/class-templates/', _template_payload(orgs, teacher=orgs['teacher_b'].id),
        format='json',
    )

    assert resp.status_code == 400, resp.content
    assert not ClassTemplate.objects.filter(teacher=orgs['teacher_b']).exists()
    assert not GymClass.objects.filter(teacher=orgs['teacher_b']).exists(), (
        'la serie ya había generado instancias con el profe ajeno'
    )


def test_template_update_cannot_borrow_a_teacher_from_another_org(api_client, orgs):
    """Mismo agujero por PATCH: además `apply_to_future_instances` propagaría el profe
    ajeno a todas las instancias futuras."""
    template = ClassTemplate.objects.create(
        organization=orgs['a'], branch=orgs['branch_a'], teacher=orgs['teacher_a'],
        class_type=orgs['class_type_a'], discipline=orgs['discipline_a'],
        name='Serie', weekday=0, start_time=time(10, 0), end_time=time(11, 0),
        capacity=10, start_date=timezone.localdate(),
    )
    _login(api_client, orgs['admin_a'])

    resp = api_client.patch(f'/api/class-templates/{template.id}/', {
        'teacher': orgs['teacher_b'].id,
    }, format='json')

    assert resp.status_code == 400, resp.content
    template.refresh_from_db()
    assert template.teacher_id == orgs['teacher_a'].id


def test_template_cannot_borrow_a_branch_from_another_org(api_client, orgs):
    """Anclaje: la sede ajena ya estaba cerrada por `ClassTemplate.clean()`."""
    _login(api_client, orgs['admin_a'])

    resp = api_client.post(
        '/api/class-templates/', _template_payload(orgs, branch=orgs['branch_b'].id),
        format='json',
    )

    assert resp.status_code == 400, resp.content
    assert 'branch' in resp.json(), resp.content


def test_template_cannot_borrow_a_class_type_from_another_org(api_client, orgs):
    """Anclaje del mismo grupo de checks."""
    _login(api_client, orgs['admin_a'])

    resp = api_client.post(
        '/api/class-templates/', _template_payload(orgs, class_type=orgs['class_type_b'].id),
        format='json',
    )

    assert resp.status_code == 400, resp.content
    assert 'class_type' in resp.json(), resp.content


def test_template_with_its_own_org_fks_still_works(api_client, orgs):
    """Regresión: la serie legítima sigue creándose y generando instancias."""
    _login(api_client, orgs['admin_a'])

    resp = api_client.post('/api/class-templates/', _template_payload(orgs), format='json')

    assert resp.status_code == 201, resp.content
    template = ClassTemplate.objects.get(id=resp.json()['id'])
    assert template.teacher_id == orgs['teacher_a'].id
    assert template.organization_id == orgs['a'].id


# ---------------------------------------------------------------------------
# Anclajes de las superficies que ya validaban (que no se abran a futuro)
# ---------------------------------------------------------------------------

def test_gym_class_cannot_borrow_a_teacher_from_another_org(api_client, orgs):
    """Anclaje: `GymClassSerializer` ya valida el profesor."""
    _login(api_client, orgs['admin_a'])
    start = timezone.now() + timedelta(days=1)

    resp = api_client.post('/api/classes/', {
        'name': 'Clase', 'branch': orgs['branch_a'].id, 'teacher': orgs['teacher_b'].id,
        'class_type': orgs['class_type_a'].id, 'discipline': orgs['discipline_a'].id,
        'start_datetime': start.isoformat(), 'end_datetime': (start + timedelta(hours=1)).isoformat(),
        'capacity': 10,
    }, format='json')

    assert resp.status_code == 400, resp.content
    assert not GymClass.objects.filter(teacher=orgs['teacher_b']).exists()


def test_gym_class_cannot_borrow_a_branch_from_another_org(api_client, orgs):
    """Anclaje: la sede ajena en una clase debe rebotar."""
    _login(api_client, orgs['admin_a'])
    start = timezone.now() + timedelta(days=1)

    resp = api_client.post('/api/classes/', {
        'name': 'Clase', 'branch': orgs['branch_b'].id, 'teacher': orgs['teacher_a'].id,
        'class_type': orgs['class_type_a'].id, 'discipline': orgs['discipline_a'].id,
        'start_datetime': start.isoformat(), 'end_datetime': (start + timedelta(hours=1)).isoformat(),
        'capacity': 10,
    }, format='json')

    assert resp.status_code == 400, resp.content


def test_plan_cannot_borrow_a_branch_from_another_org(api_client, orgs):
    """Anclaje del trabajo de sucursales: `Plan.branch` define el alcance del plan, y
    una sede ajena ahí volvería el plan inalcanzable y ataría el RESTRICT cross-org."""
    _login(api_client, orgs['admin_a'])

    resp = api_client.post('/api/plans/', {
        'name': 'Pack 10', 'plan_type': 'pack', 'total_classes': 10,
        'duration_days': 30, 'price': 30000, 'branch': orgs['branch_b'].id,
    }, format='json')

    assert resp.status_code == 400, resp.content
    assert not Plan.objects.filter(branch=orgs['branch_b']).exists()


def test_user_cannot_borrow_a_branch_from_another_org(api_client, orgs):
    """Anclaje: `CustomUserSerializer` ya valida la sede del usuario."""
    _login(api_client, orgs['admin_a'])

    resp = api_client.post('/api/users/', {
        'username': 'nuevo_alu', 'email': 'nuevo_alu@a.cl', 'password': PASSWORD,
        'role': 'student', 'branch': orgs['branch_b'].id,
    }, format='json')

    assert resp.status_code == 400, resp.content


def test_holiday_cannot_borrow_a_branch_from_another_org(api_client, orgs):
    """Anclaje: `HolidaySerializer` ya valida la sede."""
    _login(api_client, orgs['admin_a'])

    resp = api_client.post('/api/holidays/', {
        'name': 'Aniversario', 'date': str(timezone.localdate() + timedelta(days=10)),
        'scope': 'branch', 'branch': orgs['branch_b'].id,
    }, format='json')

    assert resp.status_code == 400, resp.content


def test_payment_rule_cannot_borrow_a_branch_from_another_org(api_client, orgs):
    """Anclaje: `TeacherPaymentRuleSerializer` ya valida la sede."""
    _login(api_client, orgs['admin_a'])

    resp = api_client.post('/api/teacher-payment-rules/', {
        'payment_type': 'fixed_per_class', 'amount': 10000,
        'branch': orgs['branch_b'].id,
    }, format='json')

    assert resp.status_code == 400, resp.content
    assert 'branch' in resp.json(), resp.content


def test_payment_rule_cannot_assign_a_teacher_from_another_org(api_client, orgs):
    """Anclaje: `assignments` PUT valida los teacher_ids contra la org de la regla."""
    from core.models import TeacherPaymentRule
    rule = TeacherPaymentRule.objects.create(
        organization=orgs['a'], payment_type='fixed_per_class', amount=10000,
    )
    _login(api_client, orgs['admin_a'])

    resp = api_client.put(f'/api/teacher-payment-rules/{rule.id}/assignments/', {
        'teacher_ids': [orgs['teacher_b'].id],
    }, format='json')

    assert resp.status_code == 400, resp.content
    assert not rule.teachers.filter(id=orgs['teacher_b'].id).exists()
