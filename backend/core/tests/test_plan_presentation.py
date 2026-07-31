"""Presentacion del estado de una membresia — FUENTE UNICA (7.3).

7.2 dejo el predicado en `describe_student_plan`, pero la PRESENTACION seguia partida en
dos: `StudentPlanSerializer` y `_plan_status_payload` del roster re-ramificaban cada uno
sobre el string del estado, y el wire colapsaba `exhausted` y `enrollment_fee_unpaid` a
`active` para no romper a los consumidores.

Este archivo fija las tres consecuencias de cerrar eso:

1. El wire publica los siete estados sin colapsar.
2. Los dos presentadores derivan (alert_level, alert_message) de la MISMA funcion, asi que
   no pueden volver a divergir.
3. El roster deja de ofrecer "inscribir" a quien la reserva va a rechazar, y dice POR QUE.
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from core.models import Branch, Enrollment, GymClass, Plan, StudentPlan
from core.serializers import StudentPlanSerializer
from core.services.plans import PlanStatus, _plan_alert

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()


def _plan(org, name='Pack', total_classes=10, unlimited=False):
    return Plan.objects.create(
        organization=org, name=name, plan_type='pack',
        total_classes=total_classes, unlimited_classes=unlimited,
        duration_days=30, price=30000,
    )


def _membership(student, plan, *, start_offset=-1, end_offset=20, classes_used=0,
                is_active=True, enrollment_fee=0, enrollment_fee_paid_at=None):
    return StudentPlan.objects.create(
        user=student, plan=plan, organization_id=plan.organization_id,
        start_date=TODAY + timedelta(days=start_offset),
        end_date=TODAY + timedelta(days=end_offset),
        total_classes=plan.total_classes, unlimited_classes=plan.unlimited_classes,
        classes_used=classes_used, final_price=30000, is_active=is_active,
        enrollment_fee=enrollment_fee, enrollment_fee_paid_at=enrollment_fee_paid_at,
    )


@pytest.fixture
def student_with_plan(make_organization, make_user):
    org = make_organization()
    student = make_user('stu-present', organization=org, role='student')
    return org, student, _plan(org)


@pytest.fixture
def roster(make_organization, make_user):
    """Clase futura con un alumno inscrito y otro inscribible, mas el admin que consulta.

    Hacen falta DOS alumnos: `enrollable-students` excluye a quien ya tiene inscripcion
    activa, asi que el mismo alumno no puede cubrir los dos endpoints.
    """
    org = make_organization()
    branch = Branch.objects.create(organization=org, name='Sede')
    teacher = make_user('prof-present', organization=org, role='teacher')
    student = make_user('stu-roster-present', organization=org, role='student')
    candidate = make_user('stu-candidate-present', organization=org, role='student')
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
        'admin': make_user('admin-present', organization=org, role='gym_admin'),
        'manager': make_user('manager-present', organization=org, role='manager'),
        'monitor': make_user('monitor-present', organization=org, role='monitor'),
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
# 1. El wire deja de colapsar
# --------------------------------------------------------------------------------------

def test_serializer_publishes_exhausted_instead_of_active(student_with_plan):
    """Saldo agotado deja de disfrazarse de `active` en `validity_status`."""
    org, student, plan = student_with_plan
    membership = _membership(student, plan, classes_used=plan.total_classes)

    data = StudentPlanSerializer(membership).data

    assert data['validity_status'] == 'exhausted'
    assert data['validity_status_label'] == 'Sin clases disponibles'


def test_serializer_publishes_enrollment_fee_unpaid_instead_of_active(student_with_plan):
    """Matricula impaga deja de disfrazarse de `active` en `validity_status`."""
    org, student, plan = student_with_plan
    membership = _membership(student, plan, classes_used=2, enrollment_fee=15000)

    data = StudentPlanSerializer(membership).data

    assert data['validity_status'] == 'enrollment_fee_unpaid'
    assert data['validity_status_label'] == 'Matrícula impaga'


def test_roster_publishes_exhausted_instead_of_active(api_client, roster):
    """Mismo destape en el vocabulario del roster (`plan_status`)."""
    plan = _plan(roster['org'], name='Pack 4', total_classes=4)
    _membership(roster['student'], plan, classes_used=4)

    row = _roster_row(api_client, roster)

    assert row['plan_status'] == 'exhausted'
    assert row['plan_status_label'] == 'Sin clases disponibles'


def test_serializer_keeps_publishing_active_for_a_usable_membership(student_with_plan):
    """Contraprueba: destapar los dos estados nuevos no reetiqueta al plan sano."""
    org, student, plan = student_with_plan
    membership = _membership(student, plan, classes_used=2)

    data = StudentPlanSerializer(membership).data

    assert data['validity_status'] == 'active'
    assert data['validity_status_label'] == 'Vigente'


# --------------------------------------------------------------------------------------
# 2. Un solo mapeo estado -> (alert_level, alert_message)
# --------------------------------------------------------------------------------------

def test_exhausted_alert_stops_reading_like_a_vigente_countdown(student_with_plan):
    """Sin saldo la alerta era 'neutral' + 'N dias vigentes': decia vigente sin serlo."""
    org, student, plan = student_with_plan
    membership = _membership(student, plan, classes_used=plan.total_classes)

    data = StudentPlanSerializer(membership).data

    assert data['expiry_alert_level'] == 'danger'
    assert data['expiry_alert_message'] == 'Sin clases disponibles'


def test_enrollment_fee_unpaid_alert_names_the_matricula(student_with_plan):
    org, student, plan = student_with_plan
    membership = _membership(student, plan, classes_used=2, enrollment_fee=15000)

    data = StudentPlanSerializer(membership).data

    assert data['expiry_alert_level'] == 'danger'
    assert data['expiry_alert_message'] == 'Matrícula impaga'


def test_roster_exhausted_alert_stops_saying_dias_vigentes(api_client, roster):
    """El roster mandaba 'safe' + '20 dias vigentes' para una membresia sin saldo."""
    plan = _plan(roster['org'], name='Pack 4', total_classes=4)
    _membership(roster['student'], plan, classes_used=4)

    row = _roster_row(api_client, roster)

    assert row['plan_expiry_alert_level'] == 'danger'
    assert row['plan_expiry_alert_message'] == 'Sin clases disponibles'


@pytest.mark.parametrize(
    'end_offset,expected_level,expected_message',
    [
        (20, 'safe', '20 dias vigentes'),
        (12, 'warning', '12 dias vigentes'),
        (6, 'warning', '6 dias vigentes'),
        (5, 'danger', '5 dias vigentes'),
        (1, 'danger', '1 dia vigente'),
        (0, 'danger', 'Vence hoy'),
    ],
)
def test_active_alert_thresholds_are_preserved(student_with_plan, end_offset,
                                               expected_level, expected_message):
    """Los umbrales 5/12 de 7.2 y el texto que el alumno ya ve no cambian."""
    org, student, plan = student_with_plan
    membership = _membership(student, plan, classes_used=1, end_offset=end_offset)

    data = StudentPlanSerializer(membership).data

    assert data['expiry_alert_level'] == expected_level
    assert data['expiry_alert_message'] == expected_message


@pytest.mark.parametrize(
    'kwargs',
    [
        # Las tres BANDAS de un plan vigente, que es donde los dos presentadores diferian:
        # el roster decia 'Vence pronto' / 'Por vencer' y el serializer el conteo de dias.
        {'classes_used': 1, 'end_offset': 20},   # safe    (la unica banda que ya coincidia)
        {'classes_used': 1, 'end_offset': 8},    # warning ('Por vencer' en el roster)
        {'classes_used': 1, 'end_offset': 5},    # danger  ('Vence pronto' en el roster)
        {'classes_used': 1, 'end_offset': 0},    # vence hoy
        # Y los estados donde uno decia 'safe' y el otro 'neutral'.
        {'classes_used': 10},
        {'classes_used': 1, 'enrollment_fee': 15000},
        {'is_active': False},
        {'start_offset': 3, 'end_offset': 30},
        {'start_offset': -40, 'end_offset': -10},
    ],
)
def test_both_presenters_emit_the_same_alert(api_client, roster, kwargs):
    """LA prueba de 7.3: serializer y roster no pueden volver a divergir.

    Antes el mismo plan producia 'Vence pronto' en el roster y '5 dias vigentes' en el
    serializer, y con `exhausted` uno decia 'safe' y el otro 'neutral'.
    """
    plan = _plan(roster['org'], name='Pack 10', total_classes=10)
    membership = _membership(roster['student'], plan, **kwargs)

    row = _roster_row(api_client, roster)
    data = StudentPlanSerializer(membership).data

    assert row['plan_status'] == data['validity_status']
    assert row['plan_status_label'] == data['validity_status_label']
    assert row['plan_expiry_alert_level'] == data['expiry_alert_level']
    assert row['plan_expiry_alert_message'] == data['expiry_alert_message']


def _declared_statuses():
    return [
        value for name, value in vars(PlanStatus).items()
        if not name.startswith('_') and isinstance(value, str)
    ]


def test_every_status_has_an_alert():
    """Agregar un estado sin su aviso ya no es un 500 en produccion, es un test rojo.

    `_plan_alert` corre en TODOS los caminos —serializer, roster y validador de reservas—,
    asi que un `PlanStatus` sin entrada en `_STATIC_ALERTS` reventaria los tres con
    `KeyError`. Este test recorre el vocabulario declarado en vez de una lista escrita a
    mano, para que el olvido lo detecte el CI y no el usuario.
    """
    for status in _declared_statuses():
        level, message = _plan_alert(status, 3)
        assert level, f'{status} sin nivel de alerta'
        assert message, f'{status} sin mensaje de alerta'


# --------------------------------------------------------------------------------------
# 3. El roster deja de ofrecer lo que la reserva rechaza, y dice por que
# --------------------------------------------------------------------------------------

def test_unpaid_enrollment_fee_is_not_offered_for_enrollment(api_client, roster):
    """Se ofrecia inscribir y el POST devolvia 400 'Debes pagar la matricula'.

    El saldo se sigue informando tal cual (8 clases existen de verdad); lo que cambia es
    que la membresia no se ofrece como inscribible.
    """
    plan = _plan(roster['org'], name='Pack 10', total_classes=10)
    _membership(roster['candidate'], plan, classes_used=2, enrollment_fee=15000)

    row = _roster_row(api_client, roster, endpoint='enrollable-students')

    assert row['has_available_classes'] is False
    assert row['available_classes'] == 8
    assert row['plan_status'] == 'enrollment_fee_unpaid'


def test_paid_enrollment_fee_is_still_offered(api_client, roster):
    """Contraprueba del anterior: pagar la matricula vuelve a habilitar la inscripcion."""
    plan = _plan(roster['org'], name='Pack 10', total_classes=10)
    _membership(
        roster['candidate'], plan, classes_used=2, enrollment_fee=15000,
        enrollment_fee_paid_at=timezone.now(),
    )

    row = _roster_row(api_client, roster, endpoint='enrollable-students')

    assert row['has_available_classes'] is True
    assert row['available_classes'] == 8
    assert row['plan_status'] == 'active'


def test_unlimited_membership_with_unpaid_fee_is_not_offered(api_client, roster):
    """El atajo de `unlimited_classes` tambien tiene que respetar la matricula."""
    plan = _plan(roster['org'], name='Full', total_classes=0, unlimited=True)
    _membership(roster['candidate'], plan, enrollment_fee=15000)

    row = _roster_row(api_client, roster, endpoint='enrollable-students')

    assert row['has_available_classes'] is False
    assert row['unlimited_classes'] is True


@pytest.mark.parametrize(
    'kwargs,expected_reason',
    [
        ({'classes_used': 2}, None),
        ({'classes_used': 2, 'enrollment_fee': 15000}, 'enrollment_fee_unpaid'),
        ({'classes_used': 10}, 'plan_unavailable'),
        ({'start_offset': -40, 'end_offset': -10}, 'plan_unavailable'),
    ],
)
def test_roster_reason_code_distinguishes_why_the_plan_blocks(api_client, roster, kwargs,
                                                              expected_reason):
    """Sin esto la UI dice 'sin clases disponibles' a quien tiene 8 clases y debe matricula."""
    plan = _plan(roster['org'], name='Pack 10', total_classes=10)
    _membership(roster['student'], plan, **kwargs)

    row = _roster_row(api_client, roster)

    assert row['plan_reason_code'] == expected_reason


# --------------------------------------------------------------------------------------
# 4. La matricula impaga es un dato financiero: el monitor no lo recibe
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize('actor', ['admin', 'manager', 'teacher'])
def test_financial_readers_get_the_whole_payload(api_client, roster, actor):
    """gym_admin, manager y el profe de la clase ya podian inferirlo intentando inscribir:
    el POST devuelve 'Debes pagar la matricula...'. Para ellos el dato no agrega capacidad,
    solo les evita el intento fallido, asi que reciben el payload entero."""
    plan = _plan(roster['org'], name='Pack 10', total_classes=10)
    _membership(roster['student'], plan, classes_used=2, enrollment_fee=15000)

    row = _roster_row(api_client, roster, actor=actor)

    assert row['plan_status'] == 'enrollment_fee_unpaid'
    assert row['plan_status_label'] == 'Matrícula impaga'
    assert row['plan_expiry_alert_message'] == 'Matrícula impaga'
    assert row['plan_reason_code'] == 'enrollment_fee_unpaid'


def test_monitor_never_receives_the_financial_fact(api_client, roster):
    """El monitor lee el roster pero NO puede inscribir, asi que no tenia el oraculo del 400.

    `FinancialResourcePermission` le niega la superficie financiera; publicarle la deuda del
    alumno en una superficie operativa seria darle un dato que la politica del proyecto
    trata como financiero. Se redactan los CUATRO campos: degradar solo `plan_reason_code`
    dejaba el hecho en `plan_status_label` y en el mensaje, que es justo lo que la UI pinta.
    """
    plan = _plan(roster['org'], name='Pack 10', total_classes=10)
    _membership(roster['student'], plan, classes_used=2, enrollment_fee=15000)

    row = _roster_row(api_client, roster, actor='monitor')

    assert row['plan_status'] == 'unavailable'
    assert row['plan_status_label'] == 'No disponible'
    assert row['plan_expiry_alert_message'] == 'No disponible'
    assert row['plan_expiry_alert_level'] == 'danger'
    assert row['plan_reason_code'] == 'plan_unavailable'
    # Y en ningun campo del row sobrevive el rastro del dato financiero.
    assert 'matr' not in str(row).lower()
    assert 'enrollment_fee' not in str(row)


def test_monitor_cannot_tell_unpaid_fee_from_exhausted(api_client, roster):
    """Sin esto la redaccion no redacta: si solo se ocultara la matricula, "No disponible"
    seria sinonimo de deuda y el monitor lo inferiria por eliminacion. Los dos estados que
    7.3 destapo —y que el monitor antes veia como `active`— caen al MISMO balde."""
    plan = _plan(roster['org'], name='Pack 4', total_classes=4)
    _membership(roster['student'], plan, classes_used=4)

    exhausted_row = _roster_row(api_client, roster, actor='monitor')

    StudentPlan.objects.all().delete()
    _membership(roster['student'], plan, classes_used=1, enrollment_fee=15000)

    unpaid_row = _roster_row(api_client, roster, actor='monitor')

    for key in ('plan_status', 'plan_status_label', 'plan_expiry_alert_level',
                'plan_expiry_alert_message', 'plan_reason_code'):
        assert exhausted_row[key] == unpaid_row[key], key


@pytest.mark.parametrize(
    'kwargs,expected_status,expected_label',
    [
        ({'start_offset': -40, 'end_offset': -10}, 'expired', 'Vencido'),
        ({'start_offset': 3, 'end_offset': 30}, 'upcoming', 'Por iniciar'),
        ({'is_active': False}, 'inactive', 'Inactivo'),
    ],
)
def test_monitor_keeps_seeing_the_non_financial_states(api_client, roster, kwargs,
                                                      expected_status, expected_label):
    """La redaccion no le quita al monitor lo que siempre vio: vencido, por iniciar,
    inactivo y sin plan no son datos financieros y se siguen mostrando tal cual."""
    plan = _plan(roster['org'], name='Pack 10', total_classes=10)
    _membership(roster['student'], plan, **kwargs)

    row = _roster_row(api_client, roster, actor='monitor')

    assert row['plan_status'] == expected_status
    assert row['plan_status_label'] == expected_label


def test_monitor_still_sees_that_the_plan_blocks(api_client, roster):
    """Degradar el motivo no puede degradar el bloqueo: la UI del monitor sigue igual."""
    plan = _plan(roster['org'], name='Pack 10', total_classes=10)
    _membership(roster['candidate'], plan, classes_used=2, enrollment_fee=15000)

    row = _roster_row(api_client, roster, endpoint='enrollable-students', actor='monitor')

    assert row['has_available_classes'] is False
    assert row['available_classes'] == 8


@pytest.mark.parametrize('actor', ['admin', 'manager', 'teacher', 'monitor'])
def test_degrading_does_not_invent_a_reason_for_a_usable_plan(api_client, roster, actor):
    """Contraprueba: la degradacion no puede convertir `None` en un motivo de bloqueo."""
    plan = _plan(roster['org'], name='Pack 10', total_classes=10)
    _membership(roster['student'], plan, classes_used=2)

    row = _roster_row(api_client, roster, actor=actor)

    assert row['plan_reason_code'] is None
    assert row['plan_status'] == 'active'


def test_roster_without_membership_reports_plan_unavailable(api_client, roster):
    row = _roster_row(api_client, roster)

    assert row['plan_status'] == 'no_plan'
    assert row['plan_reason_code'] == 'plan_unavailable'
    assert row['has_available_classes'] is False
