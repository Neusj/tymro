"""10.x — la regla del núcleo #9 aplicada al ALTA de una recurrencia, y la propagación
de esa elección a cada instancia que materializa la serie.

#9 (`resolve_student_plan_for_reservation`) resolvió la imputación de la reserva PUNTUAL:
con 1 membresía usable resuelve sola, con 2+ exige `student_plan_id`. La recurrencia
quedaba afuera: `_create_enrollment_if_possible` llamaba `reserve_student_in_class` SIN
elección, así que un alumno con 2+ membresías vigentes veía su serie entera `skipped` con
`plan_choice_required` (documentado en test_reservation_plan_choice.py, caso h). Acá se
cierra: el alta pide la elección UNA vez, la graba en `RecurringEnrollment.student_plan`
(FK de la Tarea A) y el loop la propaga a cada instancia.

Contrato del alta (matriz):

* 0 planes usables → 201 y FK NULL. NO bloquea: la serie sigue re-resolviendo por
  instancia (el alumno puede comprar su plan después de suscribirse).
* exactamente 1 usable → 201 y FK poblada sola, sin pedir nada en el payload.
* 2+ usables sin `student_plan_id` → 400 `plan_choice_required` (mismo mensaje que #9).
* `student_plan_id` inexistente o de OTRA organización → 404 uniforme, nunca 400: el id de
  `StudentPlan` es autoincremental y adivinable, así que distinguirlos convertiría el alta
  en un oráculo de membresías ajenas (mismo criterio que `ManualPaymentCreateView`, 8.2).
* `student_plan_id` de la MISMA organización pero de otro alumno, o del alumno sin
  saldo/vencido → 400: ya pasó la frontera de tenant, es una regla de negocio sobre un
  objeto que el actor puede ver.

FK NULL (filas legacy, y las que el backfill de 0036 dejó ambiguas) = comportamiento
anterior EXACTO: re-resolución por instancia.
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

pytestmark = pytest.mark.django_db

PASSWORD = 'Passw0rd2026'
TODAY = timezone.localdate()

CHOICE_REQUIRED_MESSAGE = 'Tienes más de un plan vigente. Elige con cuál reservar.'
CHOSEN_UNAVAILABLE_MESSAGE = 'El plan elegido no está disponible.'
NOT_FOUND_MESSAGE = 'Membresía no encontrada.'


def _login(api_client, user):
    host = {'HTTP_HOST': f'{user.organization.subdomain}.localhost'} if user.organization_id else {}
    token = api_client.post(
        '/api/login/', {'email': user.email, 'password': PASSWORD}, format='json', **host
    ).json()['token']
    api_client.credentials(HTTP_AUTHORIZATION=f'Token {token}')


def _detail(response):
    """Mensaje de error del wire, sin depender de si DRF lo envolvió en lista
    (`ValidationError({'detail': msg})`) o no (`NotFound(msg)`)."""
    body = response.json()
    detail = body.get('detail', body) if isinstance(body, dict) else body
    if isinstance(detail, list):
        return str(detail[0])
    return str(detail)


@pytest.fixture
def setup(make_organization, make_user):
    org = make_organization()
    teacher = make_user('teach-rpc', organization=org, role='teacher')
    student = make_user('alu-rpc', organization=org, role='student', email='alu-rpc@gym.cl')
    branch = Branch.objects.create(organization=org, name='Sede')
    template = ClassTemplate.objects.create(
        organization=org, branch=branch, teacher=teacher, name='Serie',
        weekday=0, start_time=time(10, 0), end_time=time(11, 0), capacity=10,
        start_date=TODAY - timedelta(days=30),
    )
    return {
        'org': org, 'teacher': teacher, 'student': student,
        'branch': branch, 'template': template,
    }


def _plan(org, name='Pack'):
    return Plan.objects.create(
        organization=org, name=name, plan_type='pack',
        total_classes=10, duration_days=30, price=30000,
    )


def _student_plan(org, student, *, classes_used=0, total_classes=10):
    """Membresía VIGENTE y —salvo que se agote a propósito— USABLE: ventana que cubre HOY
    y saldo disponible. La organización sale de la COLUMNA, igual que en producción."""
    plan = _plan(org)
    return StudentPlan.objects.create(
        user=student, plan=plan, organization_id=plan.organization_id,
        start_date=TODAY - timedelta(days=1), end_date=TODAY + timedelta(days=30),
        total_classes=total_classes, classes_used=classes_used, final_price=plan.price,
    )


def _future_instance(setup, days=1):
    """Instancia FUTURA de la serie: es lo que el alta materializa."""
    start = timezone.now() + timedelta(days=days)
    return GymClass.objects.create(
        organization=setup['org'], branch=setup['branch'], teacher=setup['teacher'],
        class_template=setup['template'], name='Instancia',
        start_datetime=start, end_datetime=start + timedelta(hours=1),
        capacity=10, status=GymClass.Status.SCHEDULED,
    )


def _post_alta(api_client, setup, **payload):
    """`student` va SIEMPRE en el payload porque el `UniqueTogetherValidator` que DRF
    deriva de `unique_active_recurring_enrollment` lo exige (comportamiento previo, no
    parte de este cambio). Da igual quién se mande: para un actor alumno,
    `RecurringEnrollmentSerializer.validate` lo pisa con el actor."""
    body = {
        'class_template': setup['template'].id,
        'student': setup['student'].id,
        'start_date': str(TODAY),
    }
    body.update(payload)
    return api_client.post('/api/recurring-enrollments/', body, format='json')


def _branch_exclusive_student_plan(org, student, branch):
    """Membresía usable de un plan EXCLUSIVO de `branch` (`plan.branch` con sede = solo
    cubre las clases de esa sede; NULL sería global)."""
    plan = Plan.objects.create(
        organization=org, branch=branch, name='Pack sede', plan_type='pack',
        total_classes=10, duration_days=30, price=30000,
    )
    return StudentPlan.objects.create(
        user=student, plan=plan, organization_id=org.id, branch=branch,
        start_date=TODAY - timedelta(days=1), end_date=TODAY + timedelta(days=30),
        total_classes=10, classes_used=0, final_price=plan.price,
    )


def _template_in(setup, branch, name='Serie sede'):
    return ClassTemplate.objects.create(
        organization=setup['org'], branch=branch, teacher=setup['teacher'], name=name,
        weekday=1, start_time=time(12, 0), end_time=time(13, 0), capacity=10,
        start_date=TODAY - timedelta(days=30),
    )


# --------------------------------------------------------------------------------------
# 1. Dos planes usables + elección explícita: la serie consume del ELEGIDO.
# --------------------------------------------------------------------------------------

def test_alta_with_two_usable_plans_and_explicit_choice_consumes_the_chosen_plan(api_client, setup):
    plan_a = _student_plan(setup['org'], setup['student'])
    plan_b = _student_plan(setup['org'], setup['student'])
    gym_class = _future_instance(setup)
    _login(api_client, setup['student'])

    resp = _post_alta(api_client, setup, student_plan_id=plan_a.id)

    assert resp.status_code == 201, resp.content
    recurring = RecurringEnrollment.objects.get(id=resp.json()['id'])
    assert recurring.student_plan_id == plan_a.id
    assert resp.json()['student_plan'] == plan_a.id
    # La serie SE MATERIALIZÓ (antes quedaba entera `skipped: plan_choice_required`)...
    enrollment = Enrollment.objects.get(gym_class=gym_class, student=setup['student'])
    assert enrollment.status == 'active'
    assert enrollment.student_plan_id == plan_a.id
    # ...consumiendo del plan elegido, y solo de ese.
    plan_a.refresh_from_db()
    plan_b.refresh_from_db()
    assert plan_a.classes_used == 1
    assert plan_b.classes_used == 0
    log = ConsumptionLog.objects.get(class_instance=gym_class, user=setup['student'])
    assert log.student_plan_id == plan_a.id


# --------------------------------------------------------------------------------------
# 2. Dos planes usables SIN elección: 400, no un skip mudo de la serie entera.
# --------------------------------------------------------------------------------------

def test_alta_with_two_usable_plans_without_a_choice_is_rejected(api_client, setup):
    plan_a = _student_plan(setup['org'], setup['student'])
    plan_b = _student_plan(setup['org'], setup['student'])
    gym_class = _future_instance(setup)
    _login(api_client, setup['student'])

    resp = _post_alta(api_client, setup)

    assert resp.status_code == 400, resp.content
    assert _detail(resp) == CHOICE_REQUIRED_MESSAGE
    assert not RecurringEnrollment.objects.filter(student=setup['student']).exists()
    assert not Enrollment.objects.filter(gym_class=gym_class).exists()
    plan_a.refresh_from_db()
    plan_b.refresh_from_db()
    assert (plan_a.classes_used, plan_b.classes_used) == (0, 0)


# --------------------------------------------------------------------------------------
# 3. Cross-org e inexistente: el MISMO 404 (anti-oráculo), nunca un 400 "plan inválido".
# --------------------------------------------------------------------------------------

def test_alta_with_a_plan_of_another_organization_is_404_identical_to_a_missing_id(
        api_client, setup, make_organization, make_user):
    # El alumno tiene un plan usable propio: así el fallo es por el ID elegido y no por
    # "cero candidatos".
    _student_plan(setup['org'], setup['student'])
    other_org = make_organization()
    other_student = make_user('alu-otra-org-rpc', organization=other_org, role='student')
    cross_org_plan = _student_plan(other_org, other_student)
    _login(api_client, setup['student'])

    resp_cross_org = _post_alta(api_client, setup, student_plan_id=cross_org_plan.id)
    resp_missing = _post_alta(api_client, setup, student_plan_id=999999)

    assert resp_cross_org.status_code == 404, resp_cross_org.content
    assert resp_missing.status_code == 404, resp_missing.content
    assert resp_cross_org.json() == resp_missing.json()
    assert _detail(resp_cross_org) == NOT_FOUND_MESSAGE
    assert not RecurringEnrollment.objects.filter(student=setup['student']).exists()


# --------------------------------------------------------------------------------------
# 4. Misma organización, OTRO alumno: 400. Ya se pasó la frontera de tenant; que la
#    membresía no sea del alumno de la suscripción es una regla de negocio.
# --------------------------------------------------------------------------------------

def test_alta_with_a_plan_of_another_student_in_the_same_org_is_400(api_client, setup, make_user):
    _student_plan(setup['org'], setup['student'])
    other_student = make_user('alu-vecino-rpc', organization=setup['org'], role='student')
    neighbour_plan = _student_plan(setup['org'], other_student)
    _login(api_client, setup['student'])

    resp = _post_alta(api_client, setup, student_plan_id=neighbour_plan.id)

    assert resp.status_code == 400, resp.content
    assert _detail(resp) == CHOSEN_UNAVAILABLE_MESSAGE
    assert not RecurringEnrollment.objects.filter(student=setup['student']).exists()


def test_alta_with_an_own_but_exhausted_plan_is_400(api_client, setup):
    _student_plan(setup['org'], setup['student'])
    exhausted = _student_plan(setup['org'], setup['student'], classes_used=10, total_classes=10)
    _login(api_client, setup['student'])

    resp = _post_alta(api_client, setup, student_plan_id=exhausted.id)

    assert resp.status_code == 400, resp.content
    assert _detail(resp) == CHOSEN_UNAVAILABLE_MESSAGE


# --------------------------------------------------------------------------------------
# 4.b Sucursal: un plan EXCLUSIVO de otra sede no puede fijarse como imputación de una
#     serie que se dicta en otra. Sin esta guarda la serie nacía MUERTA en silencio (alta
#     201 y después cada instancia `skipped: plan_branch_mismatch`).
#
#     Solo aplica a la elección EXPLÍCITA: el auto-resolve de 1 candidato NO filtra por
#     sucursal, fiel a la semántica de #9 (el branch-check corre en la materialización).
# --------------------------------------------------------------------------------------

def test_alta_with_a_plan_exclusive_to_another_branch_is_400(api_client, setup):
    other_branch = Branch.objects.create(organization=setup['org'], name='Sede 2')
    exclusive_plan = _branch_exclusive_student_plan(setup['org'], setup['student'], other_branch)
    _student_plan(setup['org'], setup['student'])  # segundo usable: la elección es real
    _login(api_client, setup['student'])

    resp = _post_alta(api_client, setup, student_plan_id=exclusive_plan.id)

    assert resp.status_code == 400, resp.content
    assert _detail(resp) == CHOSEN_UNAVAILABLE_MESSAGE
    assert not RecurringEnrollment.objects.filter(student=setup['student']).exists()


def test_alta_with_a_plan_exclusive_to_the_series_own_branch_is_accepted(api_client, setup):
    other_branch = Branch.objects.create(organization=setup['org'], name='Sede 2')
    exclusive_plan = _branch_exclusive_student_plan(setup['org'], setup['student'], other_branch)
    _student_plan(setup['org'], setup['student'])
    template_same_branch = _template_in(setup, other_branch)
    _login(api_client, setup['student'])

    resp = _post_alta(
        api_client, setup,
        class_template=template_same_branch.id, student_plan_id=exclusive_plan.id,
    )

    assert resp.status_code == 201, resp.content
    assert RecurringEnrollment.objects.get(id=resp.json()['id']).student_plan_id == exclusive_plan.id


# --------------------------------------------------------------------------------------
# 5. Contra-prueba NULL: la fila legacy (creada por ORM, sin FK) se comporta EXACTO como
#    antes — re-resolución por instancia.
# --------------------------------------------------------------------------------------

def test_legacy_row_with_null_fk_still_resolves_the_plan_per_instance(setup):
    plan = _student_plan(setup['org'], setup['student'])
    gym_class = _future_instance(setup)
    recurring = RecurringEnrollment.objects.create(
        student=setup['student'], class_template=setup['template'], start_date=TODAY,
    )
    assert recurring.student_plan_id is None, 'precondición: fila legacy sin elección'

    summary = create_enrollments_for_recurring_subscription(recurring, class_instances=[gym_class])

    assert summary['created_count'] == 1
    assert summary['skipped'] == []
    plan.refresh_from_db()
    assert plan.classes_used == 1
    assert Enrollment.objects.get(gym_class=gym_class, student=setup['student']).student_plan_id == plan.id


def test_legacy_row_with_null_fk_and_two_usable_plans_still_skips(setup):
    """La cobertura del camino NULL ambiguo no se pierde: sin elección grabada el loop
    sigue sin adivinar (es el comportamiento de las filas que dejó el backfill de 0036
    con 2+ candidatos)."""
    _student_plan(setup['org'], setup['student'])
    _student_plan(setup['org'], setup['student'])
    gym_class = _future_instance(setup)
    recurring = RecurringEnrollment.objects.create(
        student=setup['student'], class_template=setup['template'], start_date=TODAY,
    )

    summary = create_enrollments_for_recurring_subscription(recurring, class_instances=[gym_class])

    assert summary['created_count'] == 0
    assert summary['skipped'] == [{'class_id': gym_class.id, 'reason': 'plan_choice_required'}]


# --------------------------------------------------------------------------------------
# 6. Exactamente 1 plan usable: la FK queda poblada sola, sin payload.
# --------------------------------------------------------------------------------------

def test_alta_with_exactly_one_usable_plan_populates_the_fk_without_payload(api_client, setup):
    plan = _student_plan(setup['org'], setup['student'])
    gym_class = _future_instance(setup)
    _login(api_client, setup['student'])

    resp = _post_alta(api_client, setup)

    assert resp.status_code == 201, resp.content
    recurring = RecurringEnrollment.objects.get(id=resp.json()['id'])
    assert recurring.student_plan_id == plan.id
    plan.refresh_from_db()
    assert plan.classes_used == 1
    assert Enrollment.objects.filter(gym_class=gym_class, student=setup['student']).exists()


def test_alta_with_zero_usable_plans_is_not_blocked_and_leaves_the_fk_null(api_client, setup):
    """0 candidatos NO bloquea el alta: la serie queda suscrita con FK NULL y sigue
    re-resolviendo por instancia (el alumno puede comprar su plan después)."""
    gym_class = _future_instance(setup)
    _login(api_client, setup['student'])

    resp = _post_alta(api_client, setup)

    assert resp.status_code == 201, resp.content
    recurring = RecurringEnrollment.objects.get(id=resp.json()['id'])
    assert recurring.student_plan_id is None
    assert resp.json()['student_plan'] is None
    # La instancia queda sin reserva por el motivo histórico, no por la elección.
    assert not Enrollment.objects.filter(gym_class=gym_class, status='active').exists()


# --------------------------------------------------------------------------------------
# 6.b La elección sobrevive a pausar y reactivar. Es la prueba de que la propagación cubre
#     TODOS los call sites sin lógica duplicada: reactivar (views.py:3129) vuelve a llamar
#     `create_enrollments_for_recurring_subscription`, que relee la FK de la suscripción.
# --------------------------------------------------------------------------------------

def test_the_choice_survives_pause_and_reactivation(api_client, setup):
    plan_a = _student_plan(setup['org'], setup['student'])
    plan_b = _student_plan(setup['org'], setup['student'])
    gym_class = _future_instance(setup)
    _login(api_client, setup['student'])

    alta = _post_alta(api_client, setup, student_plan_id=plan_b.id)
    assert alta.status_code == 201, alta.content
    recurring_id = alta.json()['id']

    pause = api_client.patch(
        f'/api/recurring-enrollments/{recurring_id}/', {'is_active': False}, format='json',
    )
    reactivate = api_client.patch(
        f'/api/recurring-enrollments/{recurring_id}/', {'is_active': True}, format='json',
    )

    assert pause.status_code == 200, pause.content
    assert reactivate.status_code == 200, reactivate.content
    enrollment = Enrollment.objects.get(gym_class=gym_class, student=setup['student'])
    assert enrollment.status == 'active'
    assert enrollment.student_plan_id == plan_b.id
    plan_a.refresh_from_db()
    assert plan_a.classes_used == 0, 'el plan NO elegido nunca se toca'
    assert RecurringEnrollment.objects.get(id=recurring_id).student_plan_id == plan_b.id


# --------------------------------------------------------------------------------------
# 7. `student_plan_id` no puede escribir la FK sin pasar por la resolución (trampa T1 de
#    #9: `student_plan` es un FK real, así que `student_plan_id` en `validated_data` lo
#    escribiría directo).
# --------------------------------------------------------------------------------------

def test_patch_with_student_plan_id_does_not_write_the_fk_directly(api_client, setup, make_user):
    plan = _student_plan(setup['org'], setup['student'])
    recurring = RecurringEnrollment.objects.create(
        student=setup['student'], class_template=setup['template'], start_date=TODAY,
    )
    admin = make_user('admin-rpc', organization=setup['org'], role='gym_admin')
    _login(api_client, admin)

    resp = api_client.patch(
        f'/api/recurring-enrollments/{recurring.id}/',
        {'student_plan_id': plan.id}, format='json',
    )

    assert resp.status_code == 200, resp.content
    recurring.refresh_from_db()
    assert recurring.student_plan_id is None


# --------------------------------------------------------------------------------------
# 8. ORDEN (lección 8.3): la guarda de pertenencia del ACTOR corre ANTES del lookup del
#    plan. Si se invirtiera, un admin de otra organización distinguiría por el status si
#    ese id de membresía existe en la organización ajena (404 vs 403).
# --------------------------------------------------------------------------------------

def test_cross_org_actor_is_denied_before_the_plan_is_looked_up(
        api_client, setup, make_organization, make_user):
    existing_plan = _student_plan(setup['org'], setup['student'])
    other_org = make_organization()
    admin_b = make_user('admin-otra-org-rpc', organization=other_org, role='gym_admin')
    _login(api_client, admin_b)

    with_existing_id = _post_alta(api_client, setup, student_plan_id=existing_plan.id)
    with_missing_id = _post_alta(api_client, setup, student_plan_id=999999)

    assert with_existing_id.status_code == 403, with_existing_id.content
    assert with_existing_id.status_code == with_missing_id.status_code
    assert with_existing_id.json() == with_missing_id.json()
    assert not RecurringEnrollment.objects.exists()


# --------------------------------------------------------------------------------------
# 9. El alta por el otro punto de entrada (`recurring-enroll` de la serie) aplica la MISMA
#    regla: no hay dos contratos según la URL.
# --------------------------------------------------------------------------------------

def test_recurring_enroll_action_applies_the_same_choice_rule(api_client, setup):
    plan_a = _student_plan(setup['org'], setup['student'])
    plan_b = _student_plan(setup['org'], setup['student'])
    _future_instance(setup)
    _login(api_client, setup['student'])

    without_choice = api_client.post(
        f'/api/class-templates/{setup["template"].id}/recurring-enroll/',
        {'start_date': str(TODAY)}, format='json',
    )
    with_choice = api_client.post(
        f'/api/class-templates/{setup["template"].id}/recurring-enroll/',
        {'start_date': str(TODAY), 'student_plan_id': plan_b.id}, format='json',
    )

    assert without_choice.status_code == 400, without_choice.content
    assert _detail(without_choice) == CHOICE_REQUIRED_MESSAGE
    assert with_choice.status_code == 201, with_choice.content
    assert RecurringEnrollment.objects.get(id=with_choice.json()['id']).student_plan_id == plan_b.id
    plan_a.refresh_from_db()
    plan_b.refresh_from_db()
    assert (plan_a.classes_used, plan_b.classes_used) == (0, 1)
