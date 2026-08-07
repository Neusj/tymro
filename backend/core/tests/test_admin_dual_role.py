"""P4 — Doble identidad del `gym_admin`: profesor Y alumno de su propio gimnasio.

`CustomUser.role` es una opción única y (email, RUT) es único por organización, así que un
admin que además dicta y entrena NO puede tener un segundo usuario ni un segundo rol. En
vez de inventar un rol compuesto —que encendería el riesgo de autopago y autoasignación en
todos los endpoints a la vez— se amplió la ELEGIBILIDAD de rol en los gates de integridad,
reusando los flujos del alumno y del profesor tal cual.

Lo que este archivo fija:

  A. El admin es elegible como PROFESOR de su org: clase puntual, serie recurrente, pool de
     asignaciones de reglas de pago, y liquidación por `mark-paid`.
  B. El admin es sujeto de ALUMNO completo en su org: recibe plan, se inscribe, aparece en
     el roster, el profe le marca asistencia, se auto-marca por QR y lee sus `/my-*`.
  C. Los DOS candados que la ampliación obliga a poner: no puede registrarse un pago manual
     a sí mismo, y solo puede autoasignarse planes por la vía `free` (con la config de
     valor de clase gratis cargada).
  D. Cross-org: cada ampliación intersecta `organization_id`. Un admin de OTRA org no es
     asignable, ni liquidable, ni inscribible, ni se marca asistencia acá.
  E. Regresión: teacher/student normales intactos, manager/monitor siguen rechazados en las
     dos identidades, y la redacción de `plan_payment_status` al monitor sigue en pie.
"""
from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone

from core.models import (
    Attendance,
    Branch,
    ClassTemplate,
    ClassType,
    Discipline,
    Enrollment,
    GymClass,
    ManualPayment,
    Plan,
    RecurringEnrollment,
    StudentPlan,
    TeacherPaymentRule,
)
from core.views import _build_checkin_grant, _build_qr_token

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()

ASSIGN_URL = '/api/plans/assign/'
MANUAL_PAYMENT_URL = '/api/manual-payments/'
MARK_PAID_URL = '/api/teacher-payments/mark-paid/'
PREVIEW_URL = '/api/attendance-qr/preview/'
CHECKIN_URL = '/api/attendance-qr/check-in/'
MY_RESERVATIONS_URL = '/api/enrollments/my/'
MY_RECURRING_URL = '/api/recurring-enrollments/my/'
MY_PLAN_URL = '/api/plans/my-plan/'
MY_MEMBERSHIPS_URL = '/api/plans/my-memberships/'


def _org_world(make_organization, make_user, tag, *, free_class_value=0):
    """Organización autosuficiente. `admin` es el de doble identidad; `admin2` existe para
    poder probar el camino legítimo con SEGUNDA FIRMA (otro admin le cobra al primero)."""
    org = make_organization()
    if free_class_value:
        org.free_class_teacher_payment_value = free_class_value
        org.save(update_fields=['free_class_teacher_payment_value'])
    return {
        'org': org,
        'admin': make_user(f'admin-{tag}', organization=org, role='gym_admin'),
        'admin2': make_user(f'admin2-{tag}', organization=org, role='gym_admin'),
        'teacher': make_user(f'teach-{tag}', organization=org, role='teacher'),
        'student': make_user(f'alu-{tag}', organization=org, role='student'),
        'manager': make_user(f'mgr-{tag}', organization=org, role='manager'),
        'monitor': make_user(f'mon-{tag}', organization=org, role='monitor'),
        'branch': Branch.objects.create(organization=org, name=f'Sede {tag}'),
        'class_type': ClassType.objects.create(organization=org, name=f'Tipo {tag}'),
        'discipline': Discipline.objects.create(organization=org, name=f'Disc {tag}'),
    }


@pytest.fixture
def world(make_organization, make_user):
    return _org_world(make_organization, make_user, 'p4', free_class_value=5000)


@pytest.fixture
def other(make_organization, make_user):
    """Segunda organización completa: la fuente de todos los sujetos cross-org."""
    return _org_world(make_organization, make_user, 'p4x', free_class_value=5000)


def _plan(org, *, name='Plan P4', price=20000, total_classes=10):
    return Plan.objects.create(
        organization=org, name=name, plan_type=Plan.PlanType.MONTHLY,
        total_classes=total_classes, unlimited_classes=False,
        duration_days=30, price=price,
    )


def _membership(user, plan, *, final_price=20000):
    return StudentPlan.objects.create(
        user=user, plan=plan, organization_id=plan.organization_id,
        start_date=TODAY - timedelta(days=1), end_date=TODAY + timedelta(days=20),
        total_classes=plan.total_classes, unlimited_classes=False,
        classes_used=0, final_price=final_price, is_active=True,
    )


def _gym_class(ctx, *, teacher=None, start=None, status=GymClass.Status.SCHEDULED):
    start = start or (timezone.now() + timedelta(days=1))
    return GymClass.objects.create(
        organization=ctx['org'], branch=ctx['branch'],
        teacher=teacher if teacher is not None else ctx['teacher'],
        class_type=ctx['class_type'], discipline=ctx['discipline'],
        name='Clase P4', start_datetime=start, end_datetime=start + timedelta(hours=1),
        capacity=20, status=status,
    )


def _class_payload(ctx, teacher, **overrides):
    start = timezone.now() + timedelta(days=2)
    data = {
        'name': 'Clase nueva',
        'branch': ctx['branch'].id,
        'teacher': teacher.id,
        'class_type': ctx['class_type'].id,
        'discipline': ctx['discipline'].id,
        'start_datetime': start.isoformat(),
        'end_datetime': (start + timedelta(hours=1)).isoformat(),
        'capacity': 15,
    }
    data.update(overrides)
    return data


def _template_payload(ctx, teacher, **overrides):
    data = {
        'name': 'Serie nueva',
        'branch': ctx['branch'].id,
        'teacher': teacher.id,
        'class_type': ctx['class_type'].id,
        'discipline': ctx['discipline'].id,
        'start_time': '10:00',
        'end_time': '11:00',
        'capacity': 12,
        'weekday': 1,
    }
    data.update(overrides)
    return data


# ==========================================================================================
# A. El admin como PROFESOR de su organización
# ==========================================================================================

def test_admin_can_be_assigned_as_teacher_of_a_class(api_client, world):
    api_client.force_authenticate(world['admin'])

    resp = api_client.post('/api/classes/', _class_payload(world, world['admin']), format='json')

    assert resp.status_code == 201, resp.content
    assert GymClass.objects.get(id=resp.json()['id']).teacher_id == world['admin'].id


def test_admin_can_be_assigned_as_teacher_of_a_recurring_series(api_client, world):
    api_client.force_authenticate(world['admin'])

    resp = api_client.post(
        '/api/class-templates/', _template_payload(world, world['admin']), format='json'
    )

    assert resp.status_code == 201, resp.content
    assert ClassTemplate.objects.filter(teacher_id=world['admin'].id).exists()


def test_the_series_model_itself_accepts_an_admin_as_teacher(world):
    """El gate vive en `ClassTemplate.clean()`, no solo en el serializer: las instancias que
    la serie genera no vuelven a pasar por la API."""
    template = ClassTemplate(
        organization=world['org'], branch=world['branch'], teacher=world['admin'],
        class_type=world['class_type'], discipline=world['discipline'],
        name='Serie directa', weekday=1, start_time='10:00', end_time='11:00',
        capacity=10, start_date=TODAY,
    )
    template.full_clean()  # no debe levantar


def test_admin_appears_in_the_payment_rule_assignment_pool(api_client, world):
    rule = TeacherPaymentRule.objects.create(
        organization=world['org'], payment_type=TeacherPaymentRule.PaymentType.FIXED_PER_CLASS,
        amount=10000,
    )
    api_client.force_authenticate(world['admin'])

    resp = api_client.get(f'/api/teacher-payment-rules/{rule.id}/assignments/')

    assert resp.status_code == 200, resp.content
    pool_ids = {row['teacher_id'] for row in resp.json()}
    assert world['admin'].id in pool_ids
    assert world['teacher'].id in pool_ids, 'el profe normal sigue en el pool'


def test_admin_can_be_assigned_to_a_payment_rule(api_client, world):
    rule = TeacherPaymentRule.objects.create(
        organization=world['org'], payment_type=TeacherPaymentRule.PaymentType.FIXED_PER_CLASS,
        amount=10000,
    )
    api_client.force_authenticate(world['admin'])

    resp = api_client.put(
        f'/api/teacher-payment-rules/{rule.id}/assignments/',
        {'teacher_ids': [world['admin'].id]}, format='json',
    )

    assert resp.status_code == 200, resp.content
    assert list(rule.teachers.values_list('id', flat=True)) == [world['admin'].id]


def test_admin_is_liquidable_via_mark_paid(api_client, world):
    """Sin esto el pago le quedaba CALCULADO (`calculate_teacher_payment` nunca miró el rol)
    pero sin poder marcarse: `mark-paid` respondía "Profesor no encontrado"."""
    api_client.force_authenticate(world['admin'])

    resp = api_client.post(MARK_PAID_URL, {
        'teacher_id': world['admin'].id, 'year': TODAY.year, 'month': TODAY.month,
    }, format='json')

    assert resp.status_code == 200, resp.content
    assert resp.json()['teacher_id'] == world['admin'].id


# ==========================================================================================
# A-cross. El admin de OTRA organización no es ni profesor ni liquidable acá
# ==========================================================================================

def test_admin_of_another_org_is_not_assignable_as_class_teacher(api_client, world, other):
    api_client.force_authenticate(world['admin'])

    resp = api_client.post(
        '/api/classes/', _class_payload(world, other['admin']), format='json'
    )

    assert resp.status_code == 400, resp.content
    assert 'teacher' in resp.json()


def test_admin_of_another_org_is_not_assignable_as_series_teacher(api_client, world, other):
    api_client.force_authenticate(world['admin'])

    resp = api_client.post(
        '/api/class-templates/', _template_payload(world, other['admin']), format='json'
    )

    assert resp.status_code == 400, resp.content


def test_the_series_model_rejects_an_admin_from_another_org(world, other):
    template = ClassTemplate(
        organization=world['org'], branch=world['branch'], teacher=other['admin'],
        class_type=world['class_type'], discipline=world['discipline'],
        name='Serie ajena', weekday=1, start_time='10:00', end_time='11:00',
        capacity=10, start_date=TODAY,
    )
    with pytest.raises(DjangoValidationError) as exc:
        template.full_clean()
    assert 'teacher' in exc.value.message_dict


def test_admin_of_another_org_is_not_in_the_pool_nor_assignable(api_client, world, other):
    rule = TeacherPaymentRule.objects.create(
        organization=world['org'], payment_type=TeacherPaymentRule.PaymentType.FIXED_PER_CLASS,
        amount=10000,
    )
    api_client.force_authenticate(world['admin'])

    listed = api_client.get(f'/api/teacher-payment-rules/{rule.id}/assignments/')
    assert other['admin'].id not in {row['teacher_id'] for row in listed.json()}

    resp = api_client.put(
        f'/api/teacher-payment-rules/{rule.id}/assignments/',
        {'teacher_ids': [other['admin'].id]}, format='json',
    )
    assert resp.status_code == 400, resp.content
    assert rule.teachers.count() == 0


def test_admin_of_another_org_is_not_liquidable(api_client, world, other):
    api_client.force_authenticate(world['admin'])

    resp = api_client.post(MARK_PAID_URL, {
        'teacher_id': other['admin'].id, 'year': TODAY.year, 'month': TODAY.month,
    }, format='json')

    assert resp.status_code == 400, resp.content


@pytest.mark.parametrize('role_key', ['admin', 'teacher', 'student', 'manager', 'monitor'])
def test_a_foreign_user_id_never_reveals_its_role_as_teacher(api_client, world, other, role_key):
    """Anti-oráculo (lección 8.3): con el check de ROL adelante, "no es profesor" vs "no
    pertenece a la organización" delataba el rol de cuentas de otro tenant sobre ids
    autoincrementales. Todos los ids ajenos tienen que responder LO MISMO."""
    api_client.force_authenticate(world['admin'])

    resp = api_client.post(
        '/api/classes/', _class_payload(world, other[role_key]), format='json'
    )

    assert resp.status_code == 400, resp.content
    assert resp.json()['teacher'] == ['El profesor debe pertenecer a la misma organización.']


@pytest.mark.parametrize('role_key', ['admin', 'teacher', 'student', 'manager', 'monitor'])
def test_a_foreign_user_id_never_reveals_its_role_as_enrollment_subject(
        api_client, world, other, role_key):
    gym_class = _gym_class(world)
    api_client.force_authenticate(world['admin'])

    resp = api_client.post('/api/enrollments/', {
        'gym_class': gym_class.id, 'student': other[role_key].id, 'status': 'active',
    }, format='json')

    assert resp.status_code == 400, resp.content
    assert resp.json()['student'] == ['No puedes inscribir alumnos de otra organización.']


@pytest.mark.parametrize('role_key', ['admin', 'teacher', 'student', 'manager', 'monitor'])
def test_a_foreign_class_plus_foreign_subject_reveals_nothing_either(
        api_client, world, other, role_key):
    """El caso que el swap sujeto↔clase NO cubría: sujeto Y clase AMBOS de la otra org.

    Ese par es coherente entre sí, así que pasaba el check de organización y el mensaje lo
    volvía a decidir el ROL — y de yapa, los roles elegibles seguían de largo hacia los
    checks de estado y horario, filtrando si una clase AJENA está cancelada, cerrada o ya
    empezó. La guarda actor↔clase tiene que ser la PRIMERA."""
    foreign_class = _gym_class(other)
    api_client.force_authenticate(world['admin'])

    resp = api_client.post('/api/enrollments/', {
        'gym_class': foreign_class.id, 'student': other[role_key].id, 'status': 'active',
    }, format='json')

    assert resp.status_code == 400, resp.content
    assert resp.json() == {'gym_class': ['Solo puedes gestionar clases de tu organización.']}
    assert not Enrollment.objects.filter(gym_class=foreign_class).exists()


@pytest.mark.parametrize('foreign_status', [
    GymClass.Status.CANCELLED,
    GymClass.Status.SCHEDULED,
])
def test_the_state_of_a_foreign_class_is_never_revealed(
        api_client, world, other, foreign_status):
    """Mismo mensaje sea cual sea el estado de la clase ajena: si no, el endpoint es un
    oráculo del calendario de otro gimnasio."""
    foreign_class = _gym_class(other, status=foreign_status)
    api_client.force_authenticate(world['admin'])

    resp = api_client.post('/api/enrollments/', {
        'gym_class': foreign_class.id, 'student': other['student'].id, 'status': 'active',
    }, format='json')

    assert resp.status_code == 400, resp.content
    assert resp.json() == {'gym_class': ['Solo puedes gestionar clases de tu organización.']}


# ==========================================================================================
# B. El admin como ALUMNO completo de su organización
# ==========================================================================================

def test_admin_can_receive_a_plan(api_client, world):
    """Camino legítimo: se lo asigna OTRO admin, así que la vía manual está permitida."""
    plan = _plan(world['org'])
    api_client.force_authenticate(world['admin2'])

    resp = api_client.post(ASSIGN_URL, {
        'user': world['admin'].id, 'plan': plan.id, 'start_date': str(TODAY),
        'payment': {'method': 'manual', 'manual_method': 'cash', 'amount': '20000'},
    }, format='json')

    assert resp.status_code == 201, resp.content
    assert StudentPlan.objects.filter(user=world['admin'], is_active=True).exists()


def test_admin_can_be_enrolled_in_a_class(api_client, world):
    """Reusa el flujo del alumno TAL CUAL: la reserva activa exige membresía vigente y
    descuenta saldo, igual que para cualquier alumno."""
    membership = _membership(world['admin'], _plan(world['org']))
    gym_class = _gym_class(world)
    api_client.force_authenticate(world['admin'])

    resp = api_client.post('/api/enrollments/', {
        'gym_class': gym_class.id, 'student': world['admin'].id, 'status': 'active',
    }, format='json')

    assert resp.status_code == 201, resp.content
    assert Enrollment.objects.filter(gym_class=gym_class, student=world['admin']).exists()
    membership.refresh_from_db()
    assert membership.classes_used == 1, 'la reserva del admin consume su plan como la de cualquier alumno'


def test_admin_without_a_plan_cannot_reserve(api_client, world):
    """La identidad de alumno no trae privilegios: sin plan vigente el admin choca con la
    misma regla de reserva que un alumno sin plan."""
    gym_class = _gym_class(world)
    api_client.force_authenticate(world['admin'])

    resp = api_client.post('/api/enrollments/', {
        'gym_class': gym_class.id, 'student': world['admin'].id, 'status': 'active',
    }, format='json')

    assert resp.status_code == 400, resp.content


def test_admin_can_be_the_subject_of_a_recurring_enrollment(world):
    """El gate vive en `RecurringEnrollment.clean()`."""
    template = ClassTemplate.objects.create(
        organization=world['org'], branch=world['branch'], teacher=world['teacher'],
        class_type=world['class_type'], discipline=world['discipline'],
        name='Serie', weekday=1, start_time='10:00', end_time='11:00',
        capacity=10, start_date=TODAY,
    )
    recurring = RecurringEnrollment(
        class_template=template, student=world['admin'], start_date=TODAY,
    )
    recurring.full_clean(exclude=['student_plan'])  # no debe levantar por el rol


def test_admin_sees_own_reservations_in_my_endpoint(api_client, world):
    gym_class = _gym_class(world)
    Enrollment.objects.create(gym_class=gym_class, student=world['admin'], status='active')
    api_client.force_authenticate(world['admin'])

    resp = api_client.get(MY_RESERVATIONS_URL)

    assert resp.status_code == 200, resp.content
    body = resp.json()
    rows = body['results'] if isinstance(body, dict) and 'results' in body else body
    assert [row['gym_class'] for row in rows] == [gym_class.id]


def test_my_reservations_returns_only_the_admins_own_rows(api_client, world):
    """El admin ve TODA la org por `get_queryset`; `/my/` tiene que reducirlo a lo propio."""
    gym_class = _gym_class(world)
    Enrollment.objects.create(gym_class=gym_class, student=world['admin'], status='active')
    Enrollment.objects.create(gym_class=gym_class, student=world['student'], status='active')
    api_client.force_authenticate(world['admin'])

    resp = api_client.get(MY_RESERVATIONS_URL)

    body = resp.json()
    rows = body['results'] if isinstance(body, dict) and 'results' in body else body
    assert {row['student'] for row in rows} == {world['admin'].id}


def test_admin_sees_own_plan_and_memberships(api_client, world):
    plan = _plan(world['org'])
    _membership(world['admin'], plan)
    api_client.force_authenticate(world['admin'])

    my_plan = api_client.get(MY_PLAN_URL)
    assert my_plan.status_code == 200, my_plan.content
    assert my_plan.json() is not None
    assert my_plan.json()['user'] == world['admin'].id

    memberships = api_client.get(MY_MEMBERSHIPS_URL)
    assert memberships.status_code == 200, memberships.content
    assert [row['user'] for row in memberships.json()] == [world['admin'].id]


def test_admin_sees_own_recurring_series(api_client, world):
    template = ClassTemplate.objects.create(
        organization=world['org'], branch=world['branch'], teacher=world['teacher'],
        class_type=world['class_type'], discipline=world['discipline'],
        name='Serie', weekday=1, start_time='10:00', end_time='11:00',
        capacity=10, start_date=TODAY,
    )
    RecurringEnrollment.objects.create(
        class_template=template, student=world['admin'], start_date=TODAY, is_active=True,
    )
    RecurringEnrollment.objects.create(
        class_template=template, student=world['student'], start_date=TODAY, is_active=True,
    )
    api_client.force_authenticate(world['admin'])

    resp = api_client.get(MY_RECURRING_URL)

    assert resp.status_code == 200, resp.content
    assert {row['student'] for row in resp.json()} == {world['admin'].id}


def test_admin_self_checks_in_by_qr(api_client, world):
    start = timezone.now() - timedelta(minutes=2)
    gym_class = _gym_class(world, start=start)
    Enrollment.objects.create(gym_class=gym_class, student=world['admin'], status='active')
    api_client.force_authenticate(world['admin'])

    qr_token, _ = _build_qr_token(world['org'].id)
    preview = api_client.get(PREVIEW_URL, {'token': qr_token})
    assert preview.status_code == 200, preview.content
    assert preview.json()['status'] == 'ready'
    grant = preview.json()['checkin_grant']

    resp = api_client.post(CHECKIN_URL, {'grant': grant}, format='json')

    assert resp.status_code == 200, resp.content
    assert resp.json()['status'] == 'registered'
    attendance = Attendance.objects.get(gym_class=gym_class, student=world['admin'])
    assert attendance.status == Attendance.Status.PRESENT


def test_admin_cannot_self_check_in_to_a_class_he_is_not_enrolled_in(api_client, world):
    """Mismo scope que el alumno: `_find_qr_candidate` solo mira clases con enrollment
    propio, así que sin inscripción no hay clase que marcar."""
    _gym_class(world, start=timezone.now() - timedelta(minutes=2))
    api_client.force_authenticate(world['admin'])

    qr_token, _ = _build_qr_token(world['org'].id)
    preview = api_client.get(PREVIEW_URL, {'token': qr_token})

    assert preview.status_code == 200
    assert preview.json()['status'] == 'no_available_class'
    assert preview.json().get('checkin_grant') is None


def test_admin_appears_in_the_roster_and_the_teacher_can_mark_his_attendance(api_client, world):
    gym_class = _gym_class(world)
    Enrollment.objects.create(gym_class=gym_class, student=world['admin'], status='active')

    api_client.force_authenticate(world['teacher'])
    roster = api_client.get(f'/api/classes/{gym_class.id}/enrolled-students/')
    assert roster.status_code == 200, roster.content
    body = roster.json()
    rows = body['results'] if isinstance(body, dict) and 'results' in body else body
    assert world['admin'].id in {row['student_id'] for row in rows}

    marked = api_client.post(f'/api/classes/{gym_class.id}/attendance/', {
        'attendances': [{'student_id': world['admin'].id, 'status': 'present'}],
    }, format='json')
    assert marked.status_code == 200, marked.content
    assert Attendance.objects.filter(
        gym_class=gym_class, student=world['admin'], status=Attendance.Status.PRESENT,
    ).exists()


# ==========================================================================================
# B-cross. El admin de OTRA organización no es sujeto de nada acá
# ==========================================================================================

def test_admin_of_another_org_cannot_be_enrolled(api_client, world, other):
    gym_class = _gym_class(world)
    api_client.force_authenticate(world['admin'])

    resp = api_client.post('/api/enrollments/', {
        'gym_class': gym_class.id, 'student': other['admin'].id, 'status': 'active',
    }, format='json')

    assert resp.status_code == 400, resp.content
    assert not Enrollment.objects.filter(gym_class=gym_class, student=other['admin']).exists()


def test_admin_of_another_org_cannot_receive_a_plan_of_this_org(api_client, world, other):
    """Plan de acá + sujeto de allá: muere en la coherencia de organización del serializer,
    exactamente igual que con un ALUMNO de otra org (mismo código, mismo mensaje). La
    ampliación no le dio al admin ajeno un camino que el alumno ajeno no tuviera."""
    plan = _plan(world['org'])
    api_client.force_authenticate(world['admin'])

    for subject in (other['admin'], other['student']):
        resp = api_client.post(ASSIGN_URL, {
            'user': subject.id, 'plan': plan.id, 'start_date': str(TODAY),
            'payment': {'method': 'free'},
        }, format='json')
        assert resp.status_code == 400, resp.content
        assert 'plan' in resp.json()
        assert not StudentPlan.objects.filter(user=subject).exists()


def test_admin_cannot_assign_a_foreign_plan_to_a_foreign_admin(api_client, world, other):
    """El caso que SÍ llega a la guarda de la view: plan y sujeto coherentes entre sí, pero
    los dos de OTRA organización. Es el 403 cross-tenant."""
    foreign_plan = _plan(other['org'], name='Plan ajeno')
    api_client.force_authenticate(world['admin'])

    resp = api_client.post(ASSIGN_URL, {
        'user': other['admin'].id, 'plan': foreign_plan.id, 'start_date': str(TODAY),
        'payment': {'method': 'free'},
    }, format='json')

    assert resp.status_code == 403, resp.content
    assert not StudentPlan.objects.filter(user=other['admin']).exists()


@pytest.mark.parametrize('foreign_is_active', [True, False])
def test_the_is_active_of_a_foreign_series_is_never_revealed(
        api_client, world, other, foreign_is_active):
    """El `is_active` se chequeaba ANTES que la organización, así que "solo plantillas
    activas" vs "no pertenece a tu organización" delataba el estado de las series de otro
    gimnasio. Es el corte que de verdad corre en este flujo: el `validate()` del serializer
    devuelve antes de instanciar el modelo."""
    foreign_template = ClassTemplate.objects.create(
        organization=other['org'], branch=other['branch'], teacher=other['teacher'],
        class_type=other['class_type'], discipline=other['discipline'],
        name='Serie ajena', weekday=1, start_time='10:00', end_time='11:00',
        capacity=10, start_date=TODAY, is_active=foreign_is_active,
    )
    api_client.force_authenticate(world['student'])

    resp = api_client.post('/api/recurring-enrollments/', {
        'class_template': foreign_template.id, 'student': world['student'].id,
        'start_date': str(TODAY),
    }, format='json')

    assert resp.status_code == 400, resp.content
    assert resp.json()['class_template'] == ['La plantilla no pertenece a tu organización.']


def test_the_recurring_model_rejects_an_admin_from_another_org(world, other):
    template = ClassTemplate.objects.create(
        organization=world['org'], branch=world['branch'], teacher=world['teacher'],
        class_type=world['class_type'], discipline=world['discipline'],
        name='Serie', weekday=1, start_time='10:00', end_time='11:00',
        capacity=10, start_date=TODAY,
    )
    recurring = RecurringEnrollment(
        class_template=template, student=other['admin'], start_date=TODAY,
    )
    with pytest.raises(DjangoValidationError) as exc:
        recurring.full_clean(exclude=['student_plan'])
    assert 'class_template' in exc.value.message_dict


def test_admin_cannot_check_in_with_a_grant_of_another_org(api_client, world, other):
    start = timezone.now() - timedelta(minutes=2)
    foreign_class = _gym_class(other, start=start)
    api_client.force_authenticate(world['admin'])

    grant = _build_checkin_grant(world['admin'].id, foreign_class.id, other['org'].id)
    resp = api_client.post(CHECKIN_URL, {'grant': grant}, format='json')

    assert resp.status_code == 400, resp.content
    assert not Attendance.objects.filter(gym_class=foreign_class).exists()


def test_qr_preview_with_a_token_of_another_org_is_rejected(api_client, world, other):
    api_client.force_authenticate(world['admin'])

    qr_token, _ = _build_qr_token(other['org'].id)
    resp = api_client.get(PREVIEW_URL, {'token': qr_token})

    assert resp.status_code == 200
    assert resp.json()['status'] == 'wrong_organization'
    assert resp.json().get('checkin_grant') is None


def test_my_endpoints_never_show_rows_of_another_org(api_client, world, other):
    """Un admin movido de organización (o con datos viejos) no arrastra la superficie
    ajena: `StudentPlan.user`/`Enrollment.student` son CASCADE sobre el USUARIO."""
    foreign_plan = _plan(other['org'], name='Plan ajeno')
    _membership(world['admin'], foreign_plan)
    foreign_class = _gym_class(other)
    Enrollment.objects.create(gym_class=foreign_class, student=world['admin'], status='active')
    api_client.force_authenticate(world['admin'])

    # `.data` y no `.json()`: "sin plan vigente" es `Response(None)`, con cuerpo vacío.
    assert api_client.get(MY_PLAN_URL).data is None
    assert api_client.get(MY_MEMBERSHIPS_URL).json() == []
    reservations = api_client.get(MY_RESERVATIONS_URL).json()
    rows = reservations['results'] if isinstance(reservations, dict) else reservations
    assert rows == []


# ==========================================================================================
# C. Los dos candados ALTO
# ==========================================================================================

def test_admin_cannot_register_a_manual_payment_on_his_own_membership(api_client, world):
    """Autopago: sería plata que nadie recibió entrando al reporte de ingresos."""
    membership = _membership(world['admin'], _plan(world['org']))
    api_client.force_authenticate(world['admin'])

    resp = api_client.post(MANUAL_PAYMENT_URL, {
        'student_plan': membership.id, 'amount': '20000', 'method': 'cash', 'reference': '',
    }, format='json')

    assert resp.status_code == 400, resp.content
    assert not ManualPayment.objects.filter(student_plan=membership).exists()


def test_another_admin_can_register_the_payment_on_that_same_membership(api_client, world):
    """La contraparte del candado: el cobro legítimo existe, solo exige segunda firma."""
    membership = _membership(world['admin'], _plan(world['org']))
    api_client.force_authenticate(world['admin2'])

    resp = api_client.post(MANUAL_PAYMENT_URL, {
        'student_plan': membership.id, 'amount': '20000', 'method': 'cash', 'reference': '',
    }, format='json')

    assert resp.status_code == 201, resp.content
    assert ManualPayment.objects.filter(student_plan=membership).count() == 1


def test_admin_can_still_register_a_manual_payment_for_a_student(api_client, world):
    """Regresión: el candado es por IDENTIDAD, no un cierre del endpoint."""
    membership = _membership(world['student'], _plan(world['org']))
    api_client.force_authenticate(world['admin'])

    resp = api_client.post(MANUAL_PAYMENT_URL, {
        'student_plan': membership.id, 'amount': '20000', 'method': 'cash', 'reference': '',
    }, format='json')

    assert resp.status_code == 201, resp.content


def test_admin_can_self_assign_a_free_plan(api_client, world):
    """Cortesía legítima: la beca no mueve caja. La org tiene la config cargada."""
    plan = _plan(world['org'])
    api_client.force_authenticate(world['admin'])

    resp = api_client.post(ASSIGN_URL, {
        'user': world['admin'].id, 'plan': plan.id, 'start_date': str(TODAY),
        'payment': {'method': 'free'},
    }, format='json')

    assert resp.status_code == 201, resp.content
    membership = StudentPlan.objects.get(user=world['admin'], is_active=True)
    assert ManualPayment.objects.filter(student_plan=membership).count() == 0


def test_admin_cannot_self_assign_declaring_a_manual_payment(api_client, world):
    plan = _plan(world['org'])
    api_client.force_authenticate(world['admin'])

    resp = api_client.post(ASSIGN_URL, {
        'user': world['admin'].id, 'plan': plan.id, 'start_date': str(TODAY),
        'payment': {'method': 'manual', 'manual_method': 'cash', 'amount': '20000'},
    }, format='json')

    assert resp.status_code == 400, resp.content
    assert not StudentPlan.objects.filter(user=world['admin']).exists()
    assert ManualPayment.objects.count() == 0


def test_admin_self_assigned_scholarship_requires_the_free_class_config(
        api_client, make_organization, make_user):
    """La beca fija `discount_percentage=100` SIN pasar por la validación de config de
    `PlanViewSet`: sin este candado el autoservicio era una puerta trasera a un plan
    gratuito con el valor de clase gratis en cero (y el profe cobrando $0)."""
    ctx = _org_world(make_organization, make_user, 'p4noconf')  # free_class_value = 0
    plan = _plan(ctx['org'])
    api_client.force_authenticate(ctx['admin'])

    resp = api_client.post(ASSIGN_URL, {
        'user': ctx['admin'].id, 'plan': plan.id, 'start_date': str(TODAY),
        'payment': {'method': 'free'},
    }, format='json')

    assert resp.status_code == 400, resp.content
    assert not StudentPlan.objects.filter(user=ctx['admin']).exists()


def test_the_scholarship_config_gate_does_not_touch_assignments_to_students(
        api_client, make_organization, make_user):
    """El candado es del AUTOSERVICIO. Becar a un alumno (con segunda persona de por medio)
    sigue funcionando igual que antes, org sin config incluida."""
    ctx = _org_world(make_organization, make_user, 'p4noconf2')
    plan = _plan(ctx['org'])
    api_client.force_authenticate(ctx['admin'])

    resp = api_client.post(ASSIGN_URL, {
        'user': ctx['student'].id, 'plan': plan.id, 'start_date': str(TODAY),
        'payment': {'method': 'free'},
    }, format='json')

    assert resp.status_code == 201, resp.content


# ==========================================================================================
# E. Regresión: nadie más se coló por la ampliación
# ==========================================================================================

@pytest.mark.parametrize('role_key', ['manager', 'monitor', 'student'])
def test_other_roles_are_still_rejected_as_class_teacher(api_client, world, role_key):
    api_client.force_authenticate(world['admin'])

    resp = api_client.post(
        '/api/classes/', _class_payload(world, world[role_key]), format='json'
    )

    assert resp.status_code == 400, resp.content
    assert 'teacher' in resp.json()


@pytest.mark.parametrize('role_key', ['manager', 'monitor', 'teacher'])
def test_other_roles_are_still_rejected_as_plan_subject(api_client, world, role_key):
    plan = _plan(world['org'])
    api_client.force_authenticate(world['admin'])

    resp = api_client.post(ASSIGN_URL, {
        'user': world[role_key].id, 'plan': plan.id, 'start_date': str(TODAY),
        'payment': {'method': 'free'},
    }, format='json')

    assert resp.status_code == 400, resp.content
    assert not StudentPlan.objects.filter(user=world[role_key]).exists()


@pytest.mark.parametrize('role_key', ['manager', 'monitor', 'teacher'])
def test_other_roles_are_still_rejected_as_enrollment_subject(api_client, world, role_key):
    gym_class = _gym_class(world)
    api_client.force_authenticate(world['admin'])

    resp = api_client.post('/api/enrollments/', {
        'gym_class': gym_class.id, 'student': world[role_key].id, 'status': 'active',
    }, format='json')

    assert resp.status_code == 400, resp.content


@pytest.mark.parametrize('url', [MY_RESERVATIONS_URL, MY_RECURRING_URL, MY_PLAN_URL,
                                 MY_MEMBERSHIPS_URL])
@pytest.mark.parametrize('role_key', ['manager', 'monitor', 'teacher'])
def test_my_endpoints_stay_closed_for_the_other_roles(api_client, world, url, role_key):
    api_client.force_authenticate(world[role_key])

    assert api_client.get(url).status_code == 403


@pytest.mark.parametrize('role_key', ['manager', 'monitor', 'teacher'])
def test_qr_self_checkin_stays_closed_for_the_other_roles(api_client, world, role_key):
    api_client.force_authenticate(world[role_key])
    qr_token, _ = _build_qr_token(world['org'].id)

    assert api_client.get(PREVIEW_URL, {'token': qr_token}).status_code == 403
    assert api_client.post(CHECKIN_URL, {'grant': 'x'}, format='json').status_code == 403


def test_the_normal_student_flow_is_unchanged(api_client, world):
    """El alumno de siempre sigue haciendo todo lo suyo."""
    plan = _plan(world['org'])
    _membership(world['student'], plan)
    gym_class = _gym_class(world)
    Enrollment.objects.create(gym_class=gym_class, student=world['student'], status='active')
    api_client.force_authenticate(world['student'])

    assert api_client.get(MY_PLAN_URL).status_code == 200
    assert api_client.get(MY_MEMBERSHIPS_URL).status_code == 200
    assert api_client.get(MY_RESERVATIONS_URL).status_code == 200
    assert api_client.get(MY_RECURRING_URL).status_code == 200


def test_the_normal_teacher_flow_is_unchanged(api_client, world):
    api_client.force_authenticate(world['admin'])

    created = api_client.post(
        '/api/classes/', _class_payload(world, world['teacher']), format='json'
    )
    assert created.status_code == 201, created.content

    paid = api_client.post(MARK_PAID_URL, {
        'teacher_id': world['teacher'].id, 'year': TODAY.year, 'month': TODAY.month,
    }, format='json')
    assert paid.status_code == 200, paid.content


def test_the_monitor_still_never_sees_the_payment_status_of_an_admin_membership(
        api_client, world):
    """Regresión de la redacción `_may_see_plan_reason`: que el sujeto del plan sea ahora un
    admin no puede abrir por otra puerta lo que el corte del monitor cierra."""
    gym_class = _gym_class(world)
    Enrollment.objects.create(gym_class=gym_class, student=world['admin'], status='active')
    _membership(world['admin'], _plan(world['org']))

    api_client.force_authenticate(world['monitor'])
    resp = api_client.get(f'/api/classes/{gym_class.id}/enrolled-students/')

    assert resp.status_code == 200, resp.content
    body = resp.json()
    rows = body['results'] if isinstance(body, dict) and 'results' in body else body
    row = next(r for r in rows if r['student_id'] == world['admin'].id)
    assert 'plan_payment_status' not in row
    assert 'plan_enrollment_fee_status' not in row


def test_the_admin_still_sees_the_payment_status_in_the_roster(api_client, world):
    """La contraparte: la redacción es del monitor, no de todos."""
    gym_class = _gym_class(world)
    Enrollment.objects.create(gym_class=gym_class, student=world['admin'], status='active')
    _membership(world['admin'], _plan(world['org']))

    api_client.force_authenticate(world['admin2'])
    resp = api_client.get(f'/api/classes/{gym_class.id}/enrolled-students/')

    body = resp.json()
    rows = body['results'] if isinstance(body, dict) and 'results' in body else body
    row = next(r for r in rows if r['student_id'] == world['admin'].id)
    assert 'plan_payment_status' in row


# ==========================================================================================
# F. Prompt 1b — la doble identidad, alcanzable desde la UI + membresía desatascada
# ==========================================================================================

def test_the_teacher_picker_lists_admins_of_the_org(api_client, world):
    """`GET /api/users/?role=teacher,gym_admin` es lo que llenan los tres selectores de
    profesor del front. Sin esto el admin no era elegible por UI y la doble identidad
    quedaba solo-API."""
    api_client.force_authenticate(world['admin'])

    resp = api_client.get('/api/users/', {'role': 'teacher,gym_admin'})

    assert resp.status_code == 200, resp.content
    body = resp.json()
    rows = body['results'] if isinstance(body, dict) and 'results' in body else body
    listed = {row['id'] for row in rows}
    assert world['admin'].id in listed
    assert world['teacher'].id in listed, 'el profe normal sigue apareciendo'
    assert world['student'].id not in listed, 'el filtro sigue filtrando'
    assert world['manager'].id not in listed
    assert world['monitor'].id not in listed


def test_the_teacher_picker_never_lists_users_of_another_org(api_client, world, other):
    api_client.force_authenticate(world['admin'])

    resp = api_client.get('/api/users/', {'role': 'teacher,gym_admin'})

    body = resp.json()
    rows = body['results'] if isinstance(body, dict) and 'results' in body else body
    listed = {row['id'] for row in rows}
    assert other['admin'].id not in listed
    assert other['teacher'].id not in listed
    assert listed


def test_a_single_role_filter_still_behaves_exactly_as_before(api_client, world):
    """Regresión del contrato viejo: `?role=teacher` sigue devolviendo SOLO profes."""
    api_client.force_authenticate(world['admin'])

    resp = api_client.get('/api/users/', {'role': 'teacher'})

    body = resp.json()
    rows = body['results'] if isinstance(body, dict) and 'results' in body else body
    assert {row['id'] for row in rows} == {world['teacher'].id}


def test_the_superadmin_still_needs_an_org_to_list_organization_roles(
        api_client, make_user, world):
    """La multi-selección no puede ser un rodeo para el `organization_id` obligatorio del
    superadmin: basta un rol de organización en la lista para exigirlo."""
    superadmin = make_user('super-p4ui', organization=None, role='superadmin')
    api_client.force_authenticate(superadmin)

    assert api_client.get('/api/users/', {'role': 'teacher,gym_admin'}).status_code == 403
    assert api_client.get('/api/users/', {'role': 'superadmin,gym_admin'}).status_code == 403
    # Solo-plataforma sigue permitido sin organización.
    assert api_client.get('/api/users/', {'role': 'superadmin'}).status_code == 200


def test_admin_appears_in_the_enrollable_students_picker(api_client, world):
    gym_class = _gym_class(world)
    api_client.force_authenticate(world['admin'])

    resp = api_client.get(f'/api/classes/{gym_class.id}/enrollable-students/')

    assert resp.status_code == 200, resp.content
    body = resp.json()
    rows = body['results'] if isinstance(body, dict) and 'results' in body else body
    listed = {row['id'] for row in rows}
    assert world['admin'].id in listed
    assert world['student'].id in listed, 'el alumno normal sigue apareciendo'
    assert world['teacher'].id not in listed
    assert world['manager'].id not in listed
    assert world['monitor'].id not in listed


def test_the_enrollable_picker_never_lists_admins_of_another_org(api_client, world, other):
    gym_class = _gym_class(world)
    api_client.force_authenticate(world['admin'])

    resp = api_client.get(f'/api/classes/{gym_class.id}/enrollable-students/')

    body = resp.json()
    rows = body['results'] if isinstance(body, dict) and 'results' in body else body
    listed = {row['id'] for row in rows}
    assert other['admin'].id not in listed
    assert other['student'].id not in listed


def test_the_monitor_still_gets_the_enrollable_picker_redacted(api_client, world):
    """Regresión: ampliar el picker no puede filtrarle el eje financiero al monitor."""
    gym_class = _gym_class(world)
    _membership(world['admin'], _plan(world['org']))
    api_client.force_authenticate(world['monitor'])

    resp = api_client.get(f'/api/classes/{gym_class.id}/enrollable-students/')

    assert resp.status_code == 200, resp.content
    body = resp.json()
    rows = body['results'] if isinstance(body, dict) and 'results' in body else body
    row = next(r for r in rows if r['id'] == world['admin'].id)
    assert 'plan_payment_status' not in row
    assert 'plan_enrollment_fee_status' not in row


# --- La membresía del admin ya no queda en limbo -----------------------------------------

def test_the_admins_own_membership_is_visible_in_plan_memberships(api_client, world):
    plan = _plan(world['org'])
    membership = _membership(world['admin'], plan)
    api_client.force_authenticate(world['admin2'])

    resp = api_client.get(f'/api/plans/{plan.id}/memberships/')

    assert resp.status_code == 200, resp.content
    assert [row['id'] for row in resp.json()] == [membership.id]


def test_the_admins_own_membership_can_be_removed(api_client, world):
    plan = _plan(world['org'])
    membership = _membership(world['admin'], plan)
    api_client.force_authenticate(world['admin2'])

    resp = api_client.delete(f'/api/plans/{plan.id}/memberships/{membership.id}/')

    assert resp.status_code == 204, resp.content
    assert not StudentPlan.objects.filter(id=membership.id).exists()


def test_a_plan_with_an_admin_membership_is_no_longer_stuck(api_client, world):
    """El limbo completo, de punta a punta: autoasignarse → quitar la membresía → borrar el
    plan. Antes: la membresía no se listaba, el DELETE daba 404, y el borrado del plan daba
    400 autodesactivándolo, sin ninguna salida por API."""
    plan = _plan(world['org'])
    api_client.force_authenticate(world['admin'])
    created = api_client.post(ASSIGN_URL, {
        'user': world['admin'].id, 'plan': plan.id, 'start_date': str(TODAY),
        'payment': {'method': 'free'},
    }, format='json')
    assert created.status_code == 201, created.content
    membership_id = StudentPlan.objects.get(user=world['admin']).id

    listed = api_client.get(f'/api/plans/{plan.id}/memberships/')
    assert [row['id'] for row in listed.json()] == [membership_id]

    removed = api_client.delete(f'/api/plans/{plan.id}/memberships/{membership_id}/')
    assert removed.status_code == 204, removed.content

    deleted = api_client.delete(f'/api/plans/{plan.id}/')
    assert deleted.status_code == 204, deleted.content
    assert not Plan.objects.filter(id=plan.id).exists()


def test_the_admin_membership_of_another_org_is_still_unreachable(api_client, world, other):
    """La ampliación es por ROL, no por organización: la membresía del admin ajeno sigue
    invisible e imborrable desde acá, con el 404 uniforme de siempre."""
    foreign_plan = _plan(other['org'], name='Plan ajeno')
    foreign_membership = _membership(other['admin'], foreign_plan)
    api_client.force_authenticate(world['admin'])

    assert api_client.get(f'/api/plans/{foreign_plan.id}/memberships/').status_code == 404

    removed = api_client.delete(
        f'/api/plans/{foreign_plan.id}/memberships/{foreign_membership.id}/'
    )
    assert removed.status_code == 404, removed.content
    assert StudentPlan.objects.filter(id=foreign_membership.id).exists()


def test_removing_a_normal_student_membership_still_works(api_client, world):
    """Regresión del camino de siempre."""
    plan = _plan(world['org'])
    membership = _membership(world['student'], plan)
    api_client.force_authenticate(world['admin'])

    resp = api_client.delete(f'/api/plans/{plan.id}/memberships/{membership.id}/')

    assert resp.status_code == 204, resp.content


# ==========================================================================================
# G. Prompt 1c — limbo cerrado para TODOS los roles, picker sin dato financiero y sin el
#    profesor de la clase
# ==========================================================================================

@pytest.mark.parametrize('role_key', ['student', 'admin', 'teacher', 'manager', 'monitor'])
def test_a_membership_is_visible_and_removable_whatever_the_owners_current_role(
        api_client, world, role_key):
    """El limbo NO era del admin: era de cualquier dueño cuyo rol ACTUAL no estuviera en el
    filtro. El caso frecuente es el ALUMNO CON PLAN QUE ASCIENDE A PROFE — nada impide ese
    cambio de rol, y la membresía histórica quedaba invisible pero seguía bloqueando el
    borrado del plan. Filtrar por el rol de hoy para decidir si una venta de ayer existe es
    la premisa equivocada."""
    plan = _plan(world['org'])
    membership = _membership(world[role_key], plan)
    api_client.force_authenticate(world['admin2'])

    listed = api_client.get(f'/api/plans/{plan.id}/memberships/')
    assert listed.status_code == 200, listed.content
    assert [row['id'] for row in listed.json()] == [membership.id]

    removed = api_client.delete(f'/api/plans/{plan.id}/memberships/{membership.id}/')
    assert removed.status_code == 204, removed.content
    assert not StudentPlan.objects.filter(id=membership.id).exists()


def test_a_student_promoted_to_teacher_no_longer_strands_the_plan(api_client, world):
    """El ciclo completo del limbo con el caso real: el alumno compra, después lo ascienden
    a profe, y recién ahí alguien intenta dar de baja el plan."""
    plan = _plan(world['org'])
    membership = _membership(world['student'], plan)
    world['student'].role = 'teacher'
    world['student'].save(update_fields=['role'])
    api_client.force_authenticate(world['admin'])

    assert [row['id'] for row in api_client.get(f'/api/plans/{plan.id}/memberships/').json()] == [
        membership.id
    ]
    assert api_client.delete(
        f'/api/plans/{plan.id}/memberships/{membership.id}/'
    ).status_code == 204

    deleted = api_client.delete(f'/api/plans/{plan.id}/')
    assert deleted.status_code == 204, deleted.content
    assert not Plan.objects.filter(id=plan.id).exists()


def test_the_membership_scope_is_still_the_organization_not_the_role(api_client, world, other):
    """Sacar el filtro de rol NO ensancha la organización: la membresía ajena sigue con su
    404 uniforme."""
    foreign_plan = _plan(other['org'], name='Plan ajeno')
    foreign_membership = _membership(other['student'], foreign_plan)
    api_client.force_authenticate(world['admin'])

    assert api_client.get(f'/api/plans/{foreign_plan.id}/memberships/').status_code == 404
    assert api_client.delete(
        f'/api/plans/{foreign_plan.id}/memberships/{foreign_membership.id}/'
    ).status_code == 404
    assert StudentPlan.objects.filter(id=foreign_membership.id).exists()


# --- El picker no publica dato financiero, y no ofrece al profe de la clase ---------------

@pytest.mark.parametrize('actor_key', ['admin', 'manager', 'monitor', 'teacher'])
def test_the_picker_never_publishes_payment_fields_to_any_reader(api_client, world, actor_key):
    """El corte es por SUPERFICIE, no por lector: ni siquiera el admin recibe el eje de pago
    en el picker. Antes, el profe de la clase leía el estado de pago de su administrador."""
    gym_class = _gym_class(world)
    _membership(world['admin'], _plan(world['org']))
    _membership(world['student'], _plan(world['org'], name='Otro'))
    api_client.force_authenticate(world[actor_key])

    resp = api_client.get(f'/api/classes/{gym_class.id}/enrollable-students/')

    assert resp.status_code == 200, resp.content
    body = resp.json()
    rows = body['results'] if isinstance(body, dict) and 'results' in body else body
    assert rows, 'precondición: el picker devuelve candidatos'
    for row in rows:
        assert 'plan_payment_status' not in row
        assert 'plan_enrollment_fee_status' not in row
        # Lo OPERATIVO se conserva: es lo que decide si se puede inscribir.
        assert 'has_available_classes' in row
        assert 'available_classes' in row


def test_the_picker_excludes_the_teacher_of_that_very_class(api_client, world):
    """Un `gym_admin` que dicta la clase no puede ofrecerse como alumno de ella: se marcaría
    presente y esa asistencia alimenta su propia liquidación."""
    gym_class = _gym_class(world, teacher=world['admin'])
    api_client.force_authenticate(world['admin2'])

    resp = api_client.get(f'/api/classes/{gym_class.id}/enrollable-students/')

    assert resp.status_code == 200, resp.content
    body = resp.json()
    rows = body['results'] if isinstance(body, dict) and 'results' in body else body
    listed = {row['id'] for row in rows}
    assert world['admin'].id not in listed, 'dicta esta clase: no es candidato'
    assert world['student'].id in listed, 'el resto de los elegibles sigue apareciendo'
    assert world['admin2'].id in listed, 'otro admin que NO la dicta sí es candidato'


def test_the_same_admin_is_still_a_candidate_in_a_class_he_does_not_teach(api_client, world):
    """La exclusión es por CLASE, no una baja global del admin como sujeto."""
    other_class = _gym_class(world, teacher=world['teacher'])
    api_client.force_authenticate(world['admin2'])

    resp = api_client.get(f'/api/classes/{other_class.id}/enrollable-students/')

    body = resp.json()
    rows = body['results'] if isinstance(body, dict) and 'results' in body else body
    assert world['admin'].id in {row['id'] for row in rows}


def test_a_class_without_teacher_still_lists_every_candidate(api_client, world):
    """`GymClass.teacher` es nullable (SET_NULL): la exclusión no puede tragarse la lista."""
    orphan_class = _gym_class(world)
    orphan_class.teacher = None
    orphan_class.save(update_fields=['teacher'])
    api_client.force_authenticate(world['admin'])

    resp = api_client.get(f'/api/classes/{orphan_class.id}/enrollable-students/')

    assert resp.status_code == 200, resp.content
    body = resp.json()
    rows = body['results'] if isinstance(body, dict) and 'results' in body else body
    listed = {row['id'] for row in rows}
    assert world['admin'].id in listed
    assert world['student'].id in listed


def test_enrolling_a_normal_student_still_works_after_the_picker_changes(api_client, world):
    """Regresión: el picker cambió de payload, no de función."""
    membership = _membership(world['student'], _plan(world['org']))
    gym_class = _gym_class(world)
    api_client.force_authenticate(world['admin'])

    resp = api_client.post('/api/enrollments/', {
        'gym_class': gym_class.id, 'student': world['student'].id, 'status': 'active',
    }, format='json')

    assert resp.status_code == 201, resp.content
    membership.refresh_from_db()
    assert membership.classes_used == 1
