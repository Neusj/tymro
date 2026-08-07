"""8.4 — la matrícula pasa a ser SOLO INFORMATIVA (RED).

Hoy conviven dos semánticas de matrícula impaga que se contradicen: `describe_student_plan`
la trata como bloqueo de vigencia (`PlanStatus.ENROLLMENT_FEE_UNPAID`, que apaga `is_usable`
y rechaza la reserva vía `validate_student_plan_for_reservation`), y el serializer recalcula
por su cuenta `pending`/`overdue` contra `due_at` sin tocar la vigencia. La decisión de
producto ya está tomada: la matrícula se MUESTRA pero NO bloquea. Pasa a ser un eje ortogonal
propio (`enrollment_fee_status`), igual que `payment_status` (8.1/8.2).

Este archivo fija el comportamiento NUEVO. Todos los tests menos el 6 (ancla de regresión,
lectura cross-organización) deben fallar hoy: la rama de vigencia todavía apaga `is_usable`
y `StudentPlanState` todavía no tiene el campo `enrollment_fee_status`.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from core.models import Branch, Enrollment, GymClass, ManualPayment, Plan, StudentPlan
from core.serializers import StudentPlanSerializer
from core.services.plans import PlanStatus, describe_student_plan
from core.services.reservations import reserve_student_in_class

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()


def _plan(org, name='Pack', total_classes=10, unlimited=False, price=30000):
    return Plan.objects.create(
        organization=org, name=name, plan_type='pack',
        total_classes=total_classes, unlimited_classes=unlimited,
        duration_days=30, price=price,
    )


def _plan_with_fee(org, user, fee, *, paid=False, due_at=None, plan=None):
    """Espejo de `_plan_with_fee` de `test_enrollment_fee.py`: matrícula individual del
    alumno (no del plan). `due_at` se fuerza DESPUÉS del alta porque el default lo
    autocalcula el `save()` (un año desde la creación) y acá hace falta poder vencerlo.
    """
    plan = plan or _plan(org)
    sp = StudentPlan(
        user=user, plan=plan, start_date=TODAY, end_date=TODAY + timedelta(days=30),
        organization_id=plan.organization_id,
        total_classes=plan.total_classes, classes_used=0, final_price=plan.price,
        enrollment_fee=fee,
    )
    if paid:
        sp.enrollment_fee_paid_at = timezone.now()
    sp.save()
    if due_at is not None:
        sp.enrollment_fee_due_at = due_at
        sp.save(update_fields=['enrollment_fee_due_at'])
    return sp


def _future_class(org, branch, teacher):
    start = timezone.now() + timedelta(days=1)
    return GymClass.objects.create(
        organization=org, branch=branch, teacher=teacher, name='Clase',
        start_datetime=start, end_datetime=start + timedelta(hours=1),
        capacity=10, status=GymClass.Status.SCHEDULED,
    )


def _manual_payment(membership, *, organization=None, amount=30000):
    """Cobro fuera de línea de la MISMA organización que vendió la membresía (patrón de
    `test_plan_payment_status.py`): es la contraparte que hace `payment_status == 'paid'`."""
    return ManualPayment.objects.create(
        organization=organization or membership.organization,
        student_plan=membership,
        amount=amount,
    )


@pytest.fixture
def setup(make_organization, make_user):
    org = make_organization()
    teacher = make_user('teach-efi', organization=org, role='teacher')
    student = make_user('alu-efi', organization=org, role='student', email='alu-efi@gym.cl')
    branch = Branch.objects.create(organization=org, name='Sede')
    return {'org': org, 'teacher': teacher, 'student': student, 'branch': branch}


@pytest.fixture
def roster(make_organization, make_user):
    """Mismo montaje que `test_plan_presentation.py`: clase futura con un alumno YA
    inscrito (para leer su fila por `enrolled-students`) y el elenco de roles lectores."""
    org = make_organization()
    branch = Branch.objects.create(organization=org, name='Sede')
    teacher = make_user('prof-efi', organization=org, role='teacher')
    student = make_user('stu-roster-efi', organization=org, role='student')
    candidate = make_user('stu-candidate-efi', organization=org, role='student')
    start = timezone.now() + timedelta(days=1)
    gym_class = GymClass.objects.create(
        organization=org, branch=branch, teacher=teacher, name='Clase',
        start_datetime=start, end_datetime=start + timedelta(hours=1), capacity=10,
        status=GymClass.Status.SCHEDULED,
    )
    Enrollment.objects.create(gym_class=gym_class, student=student, status='active')
    return {
        'org': org, 'student': student, 'candidate': candidate, 'gym_class': gym_class,
        'teacher': teacher,
        'admin': make_user('admin-efi', organization=org, role='gym_admin'),
        'monitor': make_user('monitor-efi', organization=org, role='monitor'),
    }


def _roster_row(api_client, ctx, endpoint='enrolled-students', actor='admin'):
    target = ctx['student'] if endpoint == 'enrolled-students' else ctx['candidate']
    api_client.force_authenticate(user=ctx[actor])
    resp = api_client.get(f'/api/classes/{ctx["gym_class"].id}/{endpoint}/')
    assert resp.status_code == 200, resp.content
    body = resp.json()
    rows = body['results'] if isinstance(body, dict) else body
    key = 'student_id' if endpoint == 'enrolled-students' else 'id'
    matching = [row for row in rows if row[key] == target.id]
    assert matching, f'precondicion: el alumno aparece en {endpoint}'
    return matching[0]


# --------------------------------------------------------------------------------------
# 1. EL cambio de comportamiento: la matrícula impaga deja de bloquear la reserva.
# --------------------------------------------------------------------------------------

def test_reservation_with_unpaid_enrollment_fee_is_no_longer_blocked(setup):
    """Hoy `reserve_student_in_class` levanta `ReservationRuleError('enrollment_fee_unpaid')`
    (`validate_student_plan_for_reservation` vía `describe_student_plan`). 8.4 saca la
    matrícula de la vigencia, así que la reserva tiene que completarse igual que si no
    hubiera matrícula: la membresía queda `ACTIVE` y la inscripción, `active`."""
    _plan_with_fee(setup['org'], setup['student'], Decimal('50000'))
    gym_class = _future_class(setup['org'], setup['branch'], setup['teacher'])

    enrollment = reserve_student_in_class(student=setup['student'], gym_class=gym_class)

    assert enrollment.status == 'active'


# --------------------------------------------------------------------------------------
# 2. Estado: matrícula impaga ya no apaga `is_usable` ni pone `reason_code`.
# --------------------------------------------------------------------------------------

def test_unpaid_enrollment_fee_state_is_active_and_usable_with_its_own_axis(setup):
    """Hoy: `status == ENROLLMENT_FEE_UNPAID`, `is_usable is False`,
    `reason_code == 'enrollment_fee_unpaid'`, y el campo `enrollment_fee_status` no existe
    en `StudentPlanState` (`AttributeError`). 8.4 exige los cuatro en el otro sentido."""
    sp = _plan_with_fee(setup['org'], setup['student'], Decimal('50000'))

    state = describe_student_plan(sp, TODAY)

    assert state.status == PlanStatus.ACTIVE
    assert state.is_usable is True
    assert state.reason_code is None
    assert state.enrollment_fee_status == 'pending'


# --------------------------------------------------------------------------------------
# 3. Fuente única: los 4 casos del eje coinciden entre el estado y el serializer, y la
#    matrícula deja de teñir `validity_status` en ninguno de los 4.
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize(
    'kwargs,expected_fee_status',
    [
        ({'fee': Decimal('0')}, 'waived'),
        ({'fee': Decimal('50000')}, 'pending'),
        ({'fee': Decimal('50000'), 'paid': True}, 'paid'),
        ({'fee': Decimal('50000'), 'due_at': TODAY - timedelta(days=1)}, 'overdue'),
    ],
)
def test_state_and_serializer_agree_on_the_single_source_of_enrollment_fee_status(
        setup, kwargs, expected_fee_status):
    """Mata la contradicción pending/día-0: hoy el serializer (`get_enrollment_fee_status`)
    calcula por su cuenta contra `due_at`/`timezone.localdate()` mientras que la vigencia
    (`describe_student_plan`) mira solo `enrollment_fee_paid_at`, así que pueden divergir Y
    ADEMÁS la vigencia se contamina: en los dos casos impagos, `validity_status` da
    `enrollment_fee_unpaid` en vez de `active`. 8.4 exige una sola fuente y vigencia intacta.
    """
    sp = _plan_with_fee(setup['org'], setup['student'], **kwargs)

    state = describe_student_plan(sp, TODAY)
    data = StudentPlanSerializer(sp).data

    assert state.enrollment_fee_status == data['enrollment_fee_status']['status']
    assert state.enrollment_fee_status == expected_fee_status
    assert data['validity_status'] == 'active'


# --------------------------------------------------------------------------------------
# 4. `overdue` es informativo: vencida la matrícula, la membresía se sigue viendo y
#    reservando; el aviso de vigencia no la nombra.
# --------------------------------------------------------------------------------------

def test_overdue_enrollment_fee_is_purely_informational(setup):
    """Hoy una matrícula vencida sigue siendo, ante todo, una matrícula IMPAGA: entra por la
    misma rama que la recién vencida (`enrollment_fee_paid_at` es `None` en las dos) y
    `describe_student_plan` no distingue `due_at`, así que también apaga `is_usable` y
    bloquea la reserva. 8.4: vencida o no, es dato informativo; la alerta de vigencia sale
    de las fechas de la membresía, no de la matrícula, y la reserva pasa."""
    sp = _plan_with_fee(
        setup['org'], setup['student'], Decimal('50000'),
        due_at=TODAY - timedelta(days=1),
    )

    state = describe_student_plan(sp, TODAY)

    assert state.is_usable is True
    assert 'matr' not in state.alert_message.lower()
    assert 'matr' not in state.alert_level.lower()

    gym_class = _future_class(setup['org'], setup['branch'], setup['teacher'])
    enrollment = reserve_student_in_class(student=setup['student'], gym_class=gym_class)
    assert enrollment.status == 'active'


# --------------------------------------------------------------------------------------
# 5. Roster: el monitor no recibe el eje de matrícula (ya no hay bloqueo que redactar);
#    gym_admin/teacher sí lo reciben con su valor real.
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize('endpoint', ['enrolled-students', 'enrollable-students'])
def test_no_roster_ever_shows_the_enrollment_fee_axis_to_the_monitor(
        api_client, roster, endpoint):
    """Hoy la matrícula impaga sigue bloqueando la vigencia, así que
    `_is_redacted_for_non_financial` (vigente-pero-inusable) redacta la fila del monitor a
    `plan_status == 'unavailable'`. 8.4 saca la matrícula del bloqueo: ya no hay nada que
    redactar por ese motivo y el monitor ve `plan_status == 'active'`, sin la clave nueva
    `plan_enrollment_fee_status` (mismo criterio incondicional que ya usa `plan_payment_status`,
    regresión 8.1).

    La mitad del MONITOR sigue parametrizada sobre los dos rosters: para él el corte vale en
    los dos, y por motivos distintos (en `enrolled-students` porque es monitor, en
    `enrollable-students` porque el picker ya no lo publica para nadie).
    """
    target = roster['student'] if endpoint == 'enrolled-students' else roster['candidate']
    _plan_with_fee(roster['org'], target, Decimal('50000'), plan=_plan(roster['org']))

    monitor_row = _roster_row(api_client, roster, endpoint=endpoint, actor='monitor')
    assert 'plan_enrollment_fee_status' not in monitor_row
    assert 'plan_payment_status' not in monitor_row
    assert monitor_row['plan_status'] == 'active'


def test_the_enrolled_roster_shows_the_enrollment_fee_axis_to_staff(api_client, roster):
    """El staff financiero SÍ recibe el eje con su valor real — pero SOLO en el roster de
    inscritos.

    ⚠️ Este test estaba parametrizado sobre los DOS rosters, con el argumento de que nada
    anclaba que siguieran compartiendo `_plan_status_payload` y un refactor podía
    des-gatearlo en `enrollable-students` sin que nada se pusiera rojo. Ese argumento seguía
    siendo bueno: es exactamente lo que pasó, salvo que **a propósito**. P4/1c separó los dos
    rosters porque el picker no es una vista financiera y, con el `gym_admin` como sujeto
    inscribible, publicar ahí el eje le entregaba al profesor de la clase el estado de pago
    de su administrador. La divergencia ahora está anclada por el test explícito
    `test_the_enrollment_picker_never_publishes_the_payment_axis_to_anyone`
    (`test_plan_payment_status.py`), que es el que hay que romper para revertirla.
    """
    _plan_with_fee(roster['org'], roster['student'], Decimal('50000'), plan=_plan(roster['org']))

    staff_row = _roster_row(api_client, roster, endpoint='enrolled-students', actor='admin')

    assert 'plan_enrollment_fee_status' in staff_row
    assert staff_row['plan_enrollment_fee_status'] == 'pending'


# --------------------------------------------------------------------------------------
# 6. Ancla de regresión: anti-oráculo de LECTURA cross-organización. YA DEBE PASAR HOY.
# --------------------------------------------------------------------------------------

def test_reading_another_organizations_membership_fee_is_not_an_oracle(
        api_client, make_organization, make_user):
    """No es del alcance de 8.4 (no hay endpoint ni lookup nuevo), pero ancla que la lectura
    YA existente de `GET /api/plans/{id}/memberships/` no distingue "existe en otra org" de
    "no existe": `MembershipPlanViewSet.get_queryset` acota por `organization_id` del
    gym_admin ANTES de llegar a `get_object()`, así que un plan de la org B nunca entra al
    queryset y da el mismo 404 que un id inventado. Se espera que esto YA pase hoy."""
    org_a = make_organization()
    org_b = make_organization()
    admin_a = make_user('admin-a-efi', organization=org_a, role='gym_admin')
    student_b = make_user('alu-b-efi', organization=org_b, role='student')
    plan_b = _plan(org_b, name='Plan de la org B')
    _plan_with_fee(org_b, student_b, Decimal('50000'), plan=plan_b)

    api_client.force_authenticate(user=admin_a)
    resp_other_org = api_client.get(f'/api/plans/{plan_b.id}/memberships/')
    resp_inexistente = api_client.get('/api/plans/999999/memberships/')

    assert resp_other_org.status_code == resp_inexistente.status_code == 404
    assert resp_other_org.json() == resp_inexistente.json()


# --------------------------------------------------------------------------------------
# 7. Ortogonalidad con el eje de pago (regresión 8.1/8.2): conviven en el mismo estado.
# --------------------------------------------------------------------------------------

def test_enrollment_fee_status_and_payment_status_coexist_independently(setup):
    """Hoy `state.enrollment_fee_status` no existe (`AttributeError`): el eje de matrícula
    todavía no está separado del de vigencia. `payment_status` sí es correcto ya hoy —lo
    fija 8.1/8.2 y no debe cambiar—, así que esta es la mitad que YA pasa: la matrícula
    impaga de la membresía es asunto aparte de que el PLAN esté pagado con un
    `ManualPayment` de la organización."""
    sp = _plan_with_fee(setup['org'], setup['student'], Decimal('50000'))
    _manual_payment(sp)

    state = describe_student_plan(sp, TODAY)

    assert state.payment_status == 'paid'
    assert state.enrollment_fee_status == 'pending'
