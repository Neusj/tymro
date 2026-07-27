"""Matriz de anclaje: ninguna escritura de la org B alcanza un objeto de la org A.

El aislamiento de TYMRO es MANUAL —no hay manager base ni middleware que resuelva el
tenant—, así que cada `perform_create/update/destroy` y cada `@action` de escritura lo
sostiene por su cuenta. Un endpoint nuevo que olvide el filtro no rompe ningún test: falla
en silencio. Este archivo recorre TODA la superficie de escritura y ancla el borde, para
que abrir un agujero cueste un test rojo.

Dos formas de anclaje, según el contrato del endpoint:

* **detail** (`/{id}/` y sus acciones): el objeto ajeno no existe para el actor →
  403/404, y el objeto queda intacto.
* **detail=False con ids en el body** (`bulk-close`, `bulk-action`, `assign`,
  `mark-paid`): `get_object()` no protege. Los de bulk responden 200 y reportan la fila
  en `skipped` —es su contrato—, así que acá lo que se ancla es que NO ESCRIBIERON.
"""
from datetime import time, timedelta

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
    Person,
    Plan,
    RecurringEnrollment,
    StudentPlan,
    TeacherPaymentRule,
)

pytestmark = pytest.mark.django_db

PASSWORD = 'Passw0rd2026'
DENIED = {403, 404}


def _login(api_client, user):
    host = {'HTTP_HOST': f'{user.organization.subdomain}.localhost'} if user.organization_id else {}
    token = api_client.post(
        '/api/login/', {'email': user.email, 'password': PASSWORD}, format='json', **host
    ).json()['token']
    api_client.credentials(HTTP_AUTHORIZATION=f'Token {token}')


@pytest.fixture
def world(make_organization, make_user):
    """Un mundo completo en la org A (la víctima) y los actores de la org B."""
    org_a = make_organization()
    org_b = make_organization()

    teacher_a = make_user('teach_a', organization=org_a, role='teacher')
    student_a = make_user('alu_a', organization=org_a, role='student', email='alu_a@a.cl')
    branch_a = Branch.objects.create(organization=org_a, name='Sede A')
    class_type_a = ClassType.objects.create(organization=org_a, name='Funcional A')
    discipline_a = Discipline.objects.create(organization=org_a, name='Yoga A')
    holiday_a = Holiday.objects.create(
        organization=org_a, branch=branch_a, name='Aniversario A',
        date=timezone.localdate() + timedelta(days=20), scope=Holiday.Scope.BRANCH,
    )
    person_a = Person.objects.create(
        organization=org_a, branch=branch_a, first_name='Ana', role='student',
    )
    start = timezone.now() + timedelta(days=2)
    class_a = GymClass.objects.create(
        organization=org_a, branch=branch_a, teacher=teacher_a, class_type=class_type_a,
        discipline=discipline_a, name='Clase A', start_datetime=start,
        end_datetime=start + timedelta(hours=1), capacity=10,
        status=GymClass.Status.SCHEDULED,
    )
    template_a = ClassTemplate.objects.create(
        organization=org_a, branch=branch_a, teacher=teacher_a, class_type=class_type_a,
        discipline=discipline_a, name='Serie A', weekday=0, start_time=time(10, 0),
        end_time=time(11, 0), capacity=10, start_date=timezone.localdate(),
    )
    enrollment_a = Enrollment.objects.create(
        gym_class=class_a, student=student_a, status='active',
    )
    recurring_a = RecurringEnrollment.objects.create(
        student=student_a, class_template=template_a,
        start_date=timezone.localdate(), is_active=True,
    )
    plan_a = Plan.objects.create(
        organization=org_a, name='Pack A', plan_type='pack',
        total_classes=10, duration_days=30, price=30000,
    )
    membership_a = StudentPlan.objects.create(
        user=student_a, plan=plan_a, start_date=timezone.localdate() - timedelta(days=1),
        end_date=timezone.localdate() + timedelta(days=30), total_classes=10,
        final_price=30000,
    )
    rule_a = TeacherPaymentRule.objects.create(
        organization=org_a, payment_type='fixed_per_class', amount=10000,
    )

    return {
        'org_a': org_a, 'org_b': org_b,
        'teacher_a': teacher_a, 'student_a': student_a, 'branch_a': branch_a,
        'class_type_a': class_type_a, 'discipline_a': discipline_a,
        'holiday_a': holiday_a, 'person_a': person_a, 'class_a': class_a,
        'template_a': template_a, 'enrollment_a': enrollment_a,
        'recurring_a': recurring_a, 'plan_a': plan_a, 'membership_a': membership_a,
        'rule_a': rule_a,
        # Actores de la org B: un rol por cada nivel de privilegio de organización.
        'admin_b': make_user('admin_b', organization=org_b, role='gym_admin'),
        'manager_b': make_user('gerente_b', organization=org_b, role='manager'),
        'monitor_b': make_user('monitor_b', organization=org_b, role='monitor'),
        'teacher_b': make_user('teach_b', organization=org_b, role='teacher'),
        'student_b': make_user('alu_b', organization=org_b, role='student', email='alu_b@b.cl'),
    }


def _detail_writes(world):
    """(nombre, método, url, payload) de cada escritura `detail` sobre un objeto de A."""
    class_id = world['class_a'].id
    template_id = world['template_a'].id
    return [
        ('branch:patch', 'patch', f'/api/branches/{world["branch_a"].id}/', {'name': 'Hackeada'}),
        ('branch:delete', 'delete', f'/api/branches/{world["branch_a"].id}/', None),
        ('user:patch', 'patch', f'/api/users/{world["student_a"].id}/', {'first_name': 'Hack'}),
        ('user:delete', 'delete', f'/api/users/{world["student_a"].id}/', None),
        ('person:patch', 'patch', f'/api/people/{world["person_a"].id}/', {'first_name': 'Hack'}),
        ('person:delete', 'delete', f'/api/people/{world["person_a"].id}/', None),
        ('class_type:patch', 'patch', f'/api/class-types/{world["class_type_a"].id}/', {'name': 'Hack'}),
        ('class_type:delete', 'delete', f'/api/class-types/{world["class_type_a"].id}/', None),
        ('discipline:patch', 'patch', f'/api/disciplines/{world["discipline_a"].id}/', {'name': 'Hack'}),
        ('discipline:delete', 'delete', f'/api/disciplines/{world["discipline_a"].id}/', None),
        ('holiday:patch', 'patch', f'/api/holidays/{world["holiday_a"].id}/', {'name': 'Hack'}),
        ('holiday:delete', 'delete', f'/api/holidays/{world["holiday_a"].id}/', None),
        ('class:patch', 'patch', f'/api/classes/{class_id}/', {'name': 'Hack'}),
        ('class:delete', 'delete', f'/api/classes/{class_id}/', None),
        ('class:cancel', 'post', f'/api/classes/{class_id}/cancel/', {'comment': 'hack'}),
        ('class:complete_early', 'post', f'/api/classes/{class_id}/complete-early/', {'comment': 'hack'}),
        ('class:suspend', 'post', f'/api/classes/{class_id}/suspend/', {'suspend_reason': 'hack'}),
        ('class:reactivate', 'post', f'/api/classes/{class_id}/reactivate/', {}),
        ('class:attendance', 'post', f'/api/classes/{class_id}/attendance/', {
            'attendances': [{'student_id': world['student_a'].id, 'status': 'present'}],
        }),
        ('template:patch', 'patch', f'/api/class-templates/{template_id}/', {'name': 'Hack'}),
        ('template:delete', 'delete', f'/api/class-templates/{template_id}/', None),
        ('template:generate', 'post', f'/api/class-templates/{template_id}/generate/', {}),
        ('template:recurring_enroll', 'post', f'/api/class-templates/{template_id}/recurring-enroll/', {
            'student': world['student_a'].id, 'start_date': str(timezone.localdate()),
        }),
        ('template:cancel_future', 'post', f'/api/class-templates/{template_id}/cancel-future-instances/', {'comment': 'hack'}),
        ('template:reactivate_future', 'post', f'/api/class-templates/{template_id}/reactivate-future-cancelled/', {}),
        ('recurring:patch', 'patch', f'/api/recurring-enrollments/{world["recurring_a"].id}/', {'is_active': False}),
        ('recurring:delete', 'delete', f'/api/recurring-enrollments/{world["recurring_a"].id}/', None),
        ('enrollment:patch', 'patch', f'/api/enrollments/{world["enrollment_a"].id}/', {'status': 'cancelled'}),
        ('enrollment:delete', 'delete', f'/api/enrollments/{world["enrollment_a"].id}/', None),
        ('enrollment:cancel', 'post', f'/api/enrollments/{world["enrollment_a"].id}/cancel/', {}),
        ('plan:patch', 'patch', f'/api/plans/{world["plan_a"].id}/', {'name': 'Hack'}),
        ('plan:delete', 'delete', f'/api/plans/{world["plan_a"].id}/', None),
        ('plan:remove_membership', 'delete',
         f'/api/plans/{world["plan_a"].id}/memberships/{world["membership_a"].id}/', None),
        ('rule:patch', 'patch', f'/api/teacher-payment-rules/{world["rule_a"].id}/', {'amount': 1}),
        ('rule:delete', 'delete', f'/api/teacher-payment-rules/{world["rule_a"].id}/', None),
        ('rule:assignments', 'put', f'/api/teacher-payment-rules/{world["rule_a"].id}/assignments/', {
            'teacher_ids': [world['teacher_a'].id],
        }),
        ('organization:patch', 'patch', f'/api/organizations/{world["org_a"].id}/', {'name': 'Hack'}),
        ('organization:set_public_registration', 'post',
         f'/api/organizations/{world["org_a"].id}/set-public-registration/', {'enabled': True}),
        ('organization:trial_followup', 'put',
         f'/api/organizations/{world["org_a"].id}/trial-followup-config/', {'is_enabled': True}),
    ]


def _snapshot(world):
    """Estado observable de los objetos de la org A que las escrituras podrían tocar."""
    world['branch_a'].refresh_from_db()
    world['class_a'].refresh_from_db()
    world['template_a'].refresh_from_db()
    world['enrollment_a'].refresh_from_db()
    world['recurring_a'].refresh_from_db()
    world['plan_a'].refresh_from_db()
    world['rule_a'].refresh_from_db()
    world['org_a'].refresh_from_db()
    return {
        'branch_name': world['branch_a'].name,
        'branch_active': world['branch_a'].is_active,
        'class_name': world['class_a'].name,
        'class_status': world['class_a'].status,
        'class_exists': GymClass.objects.filter(id=world['class_a'].id).exists(),
        'template_name': world['template_a'].name,
        'template_exists': ClassTemplate.objects.filter(id=world['template_a'].id).exists(),
        'instances': world['template_a'].instances.count(),
        'enrollment_status': world['enrollment_a'].status,
        'enrollment_exists': Enrollment.objects.filter(id=world['enrollment_a'].id).exists(),
        'recurring_active': world['recurring_a'].is_active,
        'recurring_exists': RecurringEnrollment.objects.filter(id=world['recurring_a'].id).exists(),
        'plan_name': world['plan_a'].name,
        'plan_exists': Plan.objects.filter(id=world['plan_a'].id).exists(),
        'membership_exists': StudentPlan.objects.filter(id=world['membership_a'].id).exists(),
        'rule_amount': world['rule_a'].amount,
        'rule_teachers': set(world['rule_a'].teachers.values_list('id', flat=True)),
        'org_name': world['org_a'].name,
        'org_public_registration': world['org_a'].public_registration_enabled,
        'person_name': Person.objects.get(id=world['person_a'].id).first_name,
        'student_name': world['student_a'].first_name,
        'attendances': world['class_a'].attendances.count(),
        'classes_in_a': GymClass.objects.filter(organization=world['org_a']).count(),
    }


@pytest.mark.parametrize('actor', ['admin_b', 'manager_b', 'monitor_b', 'teacher_b', 'student_b'])
def test_no_role_of_another_org_can_write(api_client, world, actor):
    """Cada rol de la org B contra TODA la superficie de escritura de la org A."""
    before = _snapshot(world)
    _login(api_client, world[actor])

    allowed = []
    for name, method, url, payload in _detail_writes(world):
        kwargs = {'format': 'json'} if payload is not None else {}
        response = getattr(api_client, method)(url, payload, **kwargs) if payload is not None \
            else getattr(api_client, method)(url)
        if response.status_code not in DENIED:
            allowed.append(f'{name} -> {response.status_code} {response.content[:180]}')

    assert not allowed, (
        f'[{actor}] estas escrituras cross-org NO fueron rechazadas:\n  ' + '\n  '.join(allowed)
    )
    assert _snapshot(world) == before, f'[{actor}] una escritura cross-org modificó la org A'


@pytest.mark.parametrize('actor', ['admin_b', 'manager_b'])
def test_bulk_endpoints_do_not_touch_another_org(api_client, world, actor):
    """`bulk-close` y `bulk-action` reciben los ids en el body, donde `get_object()` no
    protege. Su contrato es responder 200 y reportar la fila en `skipped`: lo que se
    ancla acá es que no ESCRIBIERON nada en la org A."""
    before = _snapshot(world)
    _login(api_client, world[actor])

    close = api_client.post('/api/classes/bulk-close/', {
        'class_ids': [world['class_a'].id], 'action': 'cancel', 'comment': 'hack',
    }, format='json')
    assert close.status_code == 200, close.content
    assert close.json()['updated_ids'] == [], close.content

    for bulk_action in ('delete', 'deactivate', 'cancel_future_instances', 'generate_pending'):
        resp = api_client.post('/api/class-templates/bulk-action/', {
            'action': bulk_action, 'template_ids': [world['template_a'].id], 'comment': 'hack',
        }, format='json')
        assert resp.status_code == 200, resp.content
        assert resp.json()['updated_ids'] == [], (bulk_action, resp.content)
        assert resp.json()['deleted_ids'] == [], (bulk_action, resp.content)

    assert _snapshot(world) == before, f'[{actor}] un bulk cross-org modificó la org A'


def test_create_referencing_another_orgs_objects_is_rejected(api_client, world):
    """Crear en la PROPIA org pero referenciando objetos de otra: la organización se
    fuerza a la del actor, así que la FK ajena tiene que rebotar. Acá el rechazo llega
    como 400 del serializer (no 404): es el mismo borde por otra puerta, y lo que se
    exige es que no se escriba nada."""
    _login(api_client, world['admin_b'])
    start = timezone.now() + timedelta(days=3)
    before = _snapshot(world)

    resp = api_client.post('/api/classes/', {
        'name': 'Hack', 'branch': world['branch_a'].id, 'teacher': world['teacher_a'].id,
        'class_type': world['class_type_a'].id, 'discipline': world['discipline_a'].id,
        'start_datetime': start.isoformat(),
        'end_datetime': (start + timedelta(hours=1)).isoformat(), 'capacity': 5,
    }, format='json')

    assert resp.status_code == 400, resp.content
    assert 'branch' in resp.json(), resp.content
    assert not GymClass.objects.filter(name='Hack').exists()
    assert _snapshot(world) == before


def test_plan_assign_cannot_cross_orgs(api_client, world):
    """`assign` es detail=False: el plan y el alumno llegan por el body."""
    before = _snapshot(world)
    _login(api_client, world['admin_b'])

    resp = api_client.post('/api/plans/assign/', {
        'user': world['student_a'].id, 'plan': world['plan_a'].id,
        'start_date': str(timezone.localdate()),
    }, format='json')

    assert resp.status_code in DENIED | {400}, resp.content
    assert StudentPlan.objects.filter(user=world['student_a']).count() == 1, (
        'se activó una membresía a un alumno de otra organización'
    )
    assert _snapshot(world) == before


def test_mark_paid_cannot_cross_orgs(api_client, world):
    """`mark-paid` es detail=False: el profe llega por el body y la org se fuerza."""
    from core.models import TeacherPayout
    _login(api_client, world['admin_b'])
    today = timezone.localdate()

    resp = api_client.post('/api/teacher-payments/mark-paid/', {
        'teacher_id': world['teacher_a'].id, 'year': today.year, 'month': today.month,
        'organization_id': world['org_a'].id,
    }, format='json')

    assert resp.status_code in DENIED | {400}, resp.content
    assert not TeacherPayout.objects.filter(teacher=world['teacher_a']).exists(), (
        'se marcó como pagado a un profesor de otra organización'
    )


def test_a_user_without_organization_cannot_write_anywhere(api_client, world, make_user):
    """Un usuario sin organización cae en la rama `.none()`: no alcanza nada."""
    orphan = make_user('huerfano', organization=None, role='gym_admin', email='huerfano@x.cl')
    before = _snapshot(world)
    token = api_client.post(
        '/api/login/', {'email': orphan.email, 'password': PASSWORD}, format='json',
    ).json()['token']
    api_client.credentials(HTTP_AUTHORIZATION=f'Token {token}')

    allowed = []
    for name, method, url, payload in _detail_writes(world):
        kwargs = {'format': 'json'} if payload is not None else {}
        response = getattr(api_client, method)(url, payload, **kwargs) if payload is not None \
            else getattr(api_client, method)(url)
        if response.status_code not in DENIED:
            allowed.append(f'{name} -> {response.status_code} {response.content[:180]}')

    assert not allowed, 'un usuario sin organización escribió:\n  ' + '\n  '.join(allowed)
    assert _snapshot(world) == before


def test_the_owning_admin_can_still_write(api_client, world, make_user):
    """Contra-prueba: la matriz no está pasando por estar todo roto. El gym_admin de la
    PROPIA organización sí puede escribir sobre estos mismos objetos."""
    admin_a = make_user('admin_a', organization=world['org_a'], role='gym_admin')
    _login(api_client, admin_a)

    assert api_client.patch(
        f'/api/branches/{world["branch_a"].id}/', {'name': 'Sede A renombrada'}, format='json',
    ).status_code == 200
    assert api_client.patch(
        f'/api/classes/{world["class_a"].id}/', {'name': 'Clase A renombrada'}, format='json',
    ).status_code == 200
    assert api_client.post(
        f'/api/classes/{world["class_a"].id}/suspend/', {'suspend_reason': 'lluvia'}, format='json',
    ).status_code == 200
    assert api_client.delete(
        f'/api/enrollments/{world["enrollment_a"].id}/'
    ).status_code == 204
