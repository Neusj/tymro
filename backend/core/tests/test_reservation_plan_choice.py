"""9.1 — imputación de consumo por elección del alumno.

`resolve_student_plan_for_reservation` (`core/services/reservations.py`) reemplaza a
`validate_student_plan_for_reservation` como paso de resolución dentro de
`_validate_reservation_rules`: cuando el alumno tiene 2+ membresías vigentes y usables a la
vez (el caso que el modelo soporta a propósito, dos disciplinas — 4 BJJ + 8 kickboxing),
la reserva ya NO le descuenta a una arbitraria (el `.first()` de `get_active_student_plan`,
que sigue existiendo tal cual para DISPLAY). Con exactamente 1 candidato usable resuelve
solo, sin pedir nada; con 2+ exige `student_plan_id` o falla con `plan_choice_required`
("no adivinar" es la decisión de producto).

Anti-oráculo (lección 8.3, pertenencia-primero): un `student_plan_id` que no existe, que es
de OTRA organización, o que es propio pero SIN saldo/vencido son la MISMA
`ReservationRuleError` (`chosen_plan_unavailable`) — distinguirlas le regalaría al alumno
información sobre membresías que no son suyas.
"""
from datetime import time, timedelta

import pytest
from django.utils import timezone

from core.models import (
    Branch,
    ClassTemplate,
    ConsumptionLog,
    Enrollment,
    GymClass,
    Plan,
    RecurringEnrollment,
    StudentPlan,
)
from core.services.recurrence import create_enrollments_for_recurring_subscription
from core.services.reservations import ReservationRuleError, reserve_student_in_class

pytestmark = pytest.mark.django_db

PASSWORD = 'Passw0rd2026'
TODAY = timezone.localdate()

UNIFORM_MESSAGE = 'El plan elegido no está disponible.'
UNIFORM_CODE = 'chosen_plan_unavailable'


def _login(api_client, user):
    host = {'HTTP_HOST': f'{user.organization.subdomain}.localhost'} if user.organization_id else {}
    token = api_client.post(
        '/api/login/', {'email': user.email, 'password': PASSWORD}, format='json', **host
    ).json()['token']
    api_client.credentials(HTTP_AUTHORIZATION=f'Token {token}')


@pytest.fixture
def setup(make_organization, make_user):
    org = make_organization()
    teacher = make_user('teach-pc', organization=org, role='teacher')
    student = make_user('alu-pc', organization=org, role='student', email='alu-pc@gym.cl')
    branch = Branch.objects.create(organization=org, name='Sede')
    return {'org': org, 'teacher': teacher, 'student': student, 'branch': branch}


def _plan(org, name='Pack'):
    return Plan.objects.create(
        organization=org, name=name, plan_type='pack',
        total_classes=10, duration_days=30, price=30000,
    )


def _student_plan(org, student, *, classes_used=0, total_classes=10, plan=None):
    """Membresía VIGENTE y, salvo que se agote a propósito, USABLE: ventana que cubre HOY
    y saldo disponible. `plan` se puede fijar para que dos membresías del mismo alumno no
    compartan fila de `Plan` (no hace falta) o para reusar una ya creada."""
    plan = plan or _plan(org)
    return StudentPlan.objects.create(
        user=student, plan=plan, organization_id=plan.organization_id,
        start_date=TODAY - timedelta(days=1), end_date=TODAY + timedelta(days=30),
        total_classes=total_classes, classes_used=classes_used, final_price=plan.price,
    )


def _future_class(org, branch, teacher, days=1):
    start = timezone.now() + timedelta(days=days)
    return GymClass.objects.create(
        organization=org, branch=branch, teacher=teacher, name='Clase',
        start_datetime=start, end_datetime=start + timedelta(hours=1),
        capacity=10, status=GymClass.Status.SCHEDULED,
    )


def _chosen_plan_error(setup, student_plan_id, *, gym_class=None):
    gym_class = gym_class or _future_class(setup['org'], setup['branch'], setup['teacher'])
    with pytest.raises(ReservationRuleError) as exc_info:
        reserve_student_in_class(
            student=setup['student'], gym_class=gym_class, student_plan_id=student_plan_id,
        )
    return exc_info.value


# --------------------------------------------------------------------------------------
# a. Dos planes con saldo, se elige uno explícitamente: descuenta SOLO del elegido.
# --------------------------------------------------------------------------------------

def test_chosen_plan_id_gets_the_consumption_and_the_other_stays_intact(setup):
    plan_a = _student_plan(setup['org'], setup['student'])
    plan_b = _student_plan(setup['org'], setup['student'])
    gym_class = _future_class(setup['org'], setup['branch'], setup['teacher'])

    enrollment = reserve_student_in_class(
        student=setup['student'], gym_class=gym_class, student_plan_id=plan_a.id,
    )

    plan_a.refresh_from_db()
    plan_b.refresh_from_db()
    assert plan_a.classes_used == 1
    assert plan_b.classes_used == 0
    assert enrollment.student_plan_id == plan_a.id
    log = ConsumptionLog.objects.get(class_instance=gym_class, user=setup['student'])
    assert log.student_plan_id == plan_a.id


# --------------------------------------------------------------------------------------
# b. student_plan_id de OTRA organización → mismo error uniforme que "inexistente".
# --------------------------------------------------------------------------------------

def test_chosen_plan_of_another_organization_is_the_uniform_error(setup, make_organization, make_user):
    # El propio alumno tiene un plan usable: así el fallo es por el ID elegido, no por
    # "cero candidatos" (causa distinta, código distinto).
    _student_plan(setup['org'], setup['student'])
    other_org = make_organization()
    other_student = make_user('otro-org-pc', organization=other_org, role='student')
    other_plan = _student_plan(other_org, other_student)

    exc = _chosen_plan_error(setup, other_plan.id)

    assert exc.message == UNIFORM_MESSAGE
    assert exc.code == UNIFORM_CODE


# --------------------------------------------------------------------------------------
# c. student_plan_id propio pero SIN saldo → mismo error uniforme.
# --------------------------------------------------------------------------------------

def test_chosen_plan_without_balance_is_the_uniform_error(setup):
    _student_plan(setup['org'], setup['student'])  # usable, evita el caso "cero candidatos"
    exhausted = _student_plan(setup['org'], setup['student'], classes_used=10, total_classes=10)

    exc = _chosen_plan_error(setup, exhausted.id)

    assert exc.message == UNIFORM_MESSAGE
    assert exc.code == UNIFORM_CODE


# --------------------------------------------------------------------------------------
# d. student_plan_id inexistente → el mismo error uniforme (referencia de b y c).
# --------------------------------------------------------------------------------------

def test_chosen_plan_id_that_does_not_exist_is_the_reference_uniform_error(setup):
    _student_plan(setup['org'], setup['student'])  # usable, evita el caso "cero candidatos"

    exc = _chosen_plan_error(setup, 999999)

    assert exc.message == UNIFORM_MESSAGE
    assert exc.code == UNIFORM_CODE


def test_the_three_failure_causes_are_literally_indistinguishable(setup, make_organization, make_user):
    """b, c y d no son solo "el mismo mensaje": son literalmente la MISMA excepción
    (message y code), comparadas entre sí y no solo contra una constante — así una futura
    edición que cambie el string en un solo lugar no puede dejar a los otros dos atrás."""
    _student_plan(setup['org'], setup['student'])
    other_org = make_organization()
    other_student = make_user('otro-org-pc2', organization=other_org, role='student')
    other_org_plan = _student_plan(other_org, other_student)
    exhausted_plan = _student_plan(setup['org'], setup['student'], classes_used=10, total_classes=10)

    exc_other_org = _chosen_plan_error(setup, other_org_plan.id)
    exc_no_balance = _chosen_plan_error(setup, exhausted_plan.id)
    exc_missing = _chosen_plan_error(setup, 999999)

    assert exc_other_org.message == exc_no_balance.message == exc_missing.message == UNIFORM_MESSAGE
    assert exc_other_org.code == exc_no_balance.code == exc_missing.code == UNIFORM_CODE


# --------------------------------------------------------------------------------------
# e. Un solo plan usable, sin student_plan_id: resuelve solo y descuenta de ese.
# --------------------------------------------------------------------------------------

def test_single_usable_plan_resolves_without_a_choice(setup):
    plan = _student_plan(setup['org'], setup['student'])
    gym_class = _future_class(setup['org'], setup['branch'], setup['teacher'])

    enrollment = reserve_student_in_class(student=setup['student'], gym_class=gym_class)

    plan.refresh_from_db()
    assert plan.classes_used == 1
    assert enrollment.student_plan_id == plan.id


# --------------------------------------------------------------------------------------
# f. Dos planes usables, sin student_plan_id: `plan_choice_required`.
# --------------------------------------------------------------------------------------

def test_two_usable_plans_without_a_choice_requires_one(setup):
    plan_a = _student_plan(setup['org'], setup['student'])
    plan_b = _student_plan(setup['org'], setup['student'])
    gym_class = _future_class(setup['org'], setup['branch'], setup['teacher'])

    with pytest.raises(ReservationRuleError) as exc_info:
        reserve_student_in_class(student=setup['student'], gym_class=gym_class)

    assert exc_info.value.code == 'plan_choice_required'
    assert exc_info.value.message == 'Tienes más de un plan vigente. Elige con cuál reservar.'
    plan_a.refresh_from_db()
    plan_b.refresh_from_db()
    assert plan_a.classes_used == 0
    assert plan_b.classes_used == 0


# --------------------------------------------------------------------------------------
# g. Cero planes usables: el error histórico, sin cambios de string ni code.
# --------------------------------------------------------------------------------------

def test_zero_usable_plans_is_the_pre_existing_error(setup):
    gym_class = _future_class(setup['org'], setup['branch'], setup['teacher'])

    with pytest.raises(ReservationRuleError) as exc_info:
        reserve_student_in_class(student=setup['student'], gym_class=gym_class)

    assert exc_info.value.code == 'plan_unavailable'
    assert exc_info.value.message == 'No tienes clases disponibles o plan activo'


# --------------------------------------------------------------------------------------
# h. Recurrencia: la materialización no puede adivinar. Consecuencia documentada, NO
#    arreglada (recurrence.py no cambia): un alumno con 2+ planes usables queda `skipped`.
# --------------------------------------------------------------------------------------

def test_recurring_materialization_skips_with_plan_choice_required_when_ambiguous(setup):
    """`_create_enrollment_if_possible` llama `reserve_student_in_class` SIN
    `student_plan_id` -- no hay ningún humano eligiendo en el job de materialización --,
    así que antes de 9.1 le descontaba a una membresía arbitraria y ahora la reserva
    queda `skipped` con `reason == 'plan_choice_required'`. Es la decisión de producto
    ("no adivinar"), no un bug: no se toca `recurrence.py` para "arreglarlo"."""
    _student_plan(setup['org'], setup['student'])
    _student_plan(setup['org'], setup['student'])
    template = ClassTemplate.objects.create(
        organization=setup['org'], branch=setup['branch'], teacher=setup['teacher'],
        name='Serie', weekday=0, start_time=time(10, 0), end_time=time(11, 0),
        capacity=10, start_date=TODAY - timedelta(days=30),
    )
    recurring = RecurringEnrollment.objects.create(
        student=setup['student'], class_template=template, start_date=TODAY - timedelta(days=1),
    )
    start = timezone.now() + timedelta(days=1)
    gym_class = GymClass.objects.create(
        organization=setup['org'], branch=setup['branch'], teacher=setup['teacher'],
        class_template=template, name='Instancia', start_datetime=start,
        end_datetime=start + timedelta(hours=1), capacity=10,
        status=GymClass.Status.SCHEDULED,
    )

    summary = create_enrollments_for_recurring_subscription(recurring, class_instances=[gym_class])

    assert summary['created_count'] == 0
    assert summary['skipped'] == [{'class_id': gym_class.id, 'reason': 'plan_choice_required'}]
    assert not Enrollment.objects.filter(gym_class=gym_class, student=setup['student']).exists()


# --------------------------------------------------------------------------------------
# i. Nivel API: POST /api/enrollments/ con student_plan_id, y el mismo anti-oráculo en
#    el wire (otra organización vs inexistente, ambos 400 con `detail` idéntico).
# --------------------------------------------------------------------------------------

def test_api_post_with_valid_student_plan_id_deducts_from_the_chosen_plan(api_client, setup):
    plan_a = _student_plan(setup['org'], setup['student'])
    plan_b = _student_plan(setup['org'], setup['student'])
    gym_class = _future_class(setup['org'], setup['branch'], setup['teacher'])
    _login(api_client, setup['student'])

    resp = api_client.post('/api/enrollments/', {
        'gym_class': gym_class.id, 'student_plan_id': plan_a.id,
    }, format='json')

    assert resp.status_code == 201, resp.content
    plan_a.refresh_from_db()
    plan_b.refresh_from_db()
    assert plan_a.classes_used == 1
    assert plan_b.classes_used == 0
    assert Enrollment.objects.get(id=resp.json()['id']).student_plan_id == plan_a.id


def test_api_post_other_org_vs_inexistent_student_plan_id_are_identical_400(
        api_client, setup, make_organization, make_user):
    _student_plan(setup['org'], setup['student'])  # usable propio: el motivo es el ID elegido
    other_org = make_organization()
    other_student = make_user('otro-api-pc', organization=other_org, role='student')
    other_plan = _student_plan(other_org, other_student)
    gym_class_1 = _future_class(setup['org'], setup['branch'], setup['teacher'], days=1)
    gym_class_2 = _future_class(setup['org'], setup['branch'], setup['teacher'], days=2)
    _login(api_client, setup['student'])

    resp_other_org = api_client.post('/api/enrollments/', {
        'gym_class': gym_class_1.id, 'student_plan_id': other_plan.id,
    }, format='json')
    resp_missing = api_client.post('/api/enrollments/', {
        'gym_class': gym_class_2.id, 'student_plan_id': 999999,
    }, format='json')

    assert resp_other_org.status_code == resp_missing.status_code == 400
    assert resp_other_org.json() == resp_missing.json()


# --------------------------------------------------------------------------------------
# j. `student_plan_id` en un POST que NO activa (status='cancelled'): el pop en la vista
#    impide que el FK se escriba directo por el serializer.
# --------------------------------------------------------------------------------------

def test_api_post_cancelled_with_student_plan_id_does_not_write_the_fk_directly(
        api_client, setup, make_user):
    plan = _student_plan(setup['org'], setup['student'])
    gym_class = _future_class(setup['org'], setup['branch'], setup['teacher'])
    admin = make_user('admin-pc', organization=setup['org'], role='gym_admin')
    _login(api_client, admin)

    resp = api_client.post('/api/enrollments/', {
        'gym_class': gym_class.id, 'student': setup['student'].id,
        'status': 'cancelled', 'student_plan_id': plan.id,
    }, format='json')

    assert resp.status_code == 201, resp.content
    enrollment = Enrollment.objects.get(id=resp.json()['id'])
    assert enrollment.student_plan_id is None
    plan.refresh_from_db()
    assert plan.classes_used == 0
