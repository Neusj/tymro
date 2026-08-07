"""P4 · Feature B — vista integral de UN alumno (SOLO LECTURA, SOLO `gym_admin`).

`GET /api/students/{id}/overview/` consolida membresías (con `payment_status`/`validity_status`
de la FUENTE ÚNICA, `describe_student_plan`), consumo, asistencia, reservas y recurrencias
vigentes. Es superficie FINANCIERA (`payment_status`), así que el corte de rol es el mismo que
reportería (`ReportPermission`: solo `gym_admin` con organización, `superadmin` afuera) más un
check inline — este archivo prueba que el monitor NUNCA la ve (ni el 200, ni el dato), y que el
alumno ajeno/inexistente da el MISMO 404 (anti-oráculo, mismo criterio que
`test_attendance_history_endpoint.py` y `test_reports_revenue_drilldown.py`).
"""
from datetime import time, timedelta

import pytest
from django.utils import timezone

from core.models import (
    Attendance,
    Branch,
    ClassTemplate,
    ConsumptionLog,
    Enrollment,
    GymClass,
    Plan,
    RecurringEnrollment,
    StudentPlan,
)
from core.services.plans import describe_student_plan
from core.views_student_overview import DEFAULT_HISTORY_LIMIT, MAX_HISTORY_LIMIT

pytestmark = pytest.mark.django_db


def _overview_url(student_id):
    return f'/api/students/{student_id}/overview/'


def _plan(org, **extra):
    defaults = dict(
        name='Pack 10', plan_type=Plan.PlanType.PACK, total_classes=10,
        unlimited_classes=False, duration_days=30, price=30000,
    )
    defaults.update(extra)
    return Plan.objects.create(organization=org, **defaults)


def _membership(student, plan, **extra):
    today = timezone.localdate()
    defaults = dict(
        user=student, plan=plan, organization_id=plan.organization_id,
        start_date=today - timedelta(days=5), end_date=today + timedelta(days=25),
        total_classes=plan.total_classes, unlimited_classes=plan.unlimited_classes,
        classes_used=2, final_price=float(plan.price), is_active=True,
    )
    defaults.update(extra)
    return StudentPlan.objects.create(**defaults)


def _branch(org):
    return Branch.objects.create(organization=org, name='Sede')


def _gym_class(org, branch, **extra):
    now = timezone.now()
    defaults = dict(
        organization=org, branch=branch, name='Clase',
        start_datetime=now - timedelta(days=1),
        end_datetime=now - timedelta(days=1) + timedelta(hours=1),
        capacity=10, status=GymClass.Status.COMPLETED,
    )
    defaults.update(extra)
    return GymClass.objects.create(**defaults)


@pytest.fixture
def setup(make_organization, make_user):
    org = make_organization()
    admin = make_user('admin-so', organization=org, role='gym_admin')
    student = make_user(
        'student-so', organization=org, role='student', first_name='Ana', last_name='Perez',
    )
    branch = _branch(org)
    plan = _plan(org)
    membership = _membership(student, plan)
    gym_class = _gym_class(org, branch)
    return {
        'org': org,
        'admin': admin,
        'student': student,
        'branch': branch,
        'plan': plan,
        'membership': membership,
        'gym_class': gym_class,
    }


# --------------------------------------------------------------------------------------
# 1. gym_admin ve la vista integral completa de un alumno de su org.
# --------------------------------------------------------------------------------------

def test_gym_admin_sees_full_overview_of_a_student_in_their_org(api_client, setup):
    student = setup['student']
    membership = setup['membership']
    gym_class = setup['gym_class']

    ConsumptionLog.objects.create(
        user=student, student_plan=membership, class_instance=gym_class, branch=setup['branch'],
    )
    Attendance.objects.create(
        gym_class=gym_class, student=student,
        status=Attendance.Status.PRESENT, source=Attendance.Source.QR,
    )
    Enrollment.objects.create(
        gym_class=gym_class, student=student, status='active', student_plan=membership,
    )

    api_client.force_authenticate(user=setup['admin'])
    resp = api_client.get(_overview_url(student.id))

    assert resp.status_code == 200, resp.content
    data = resp.json()

    assert data['student']['id'] == student.id
    assert data['student']['name'] == 'Ana Perez'

    assert len(data['memberships']) == 1
    membership_payload = data['memberships'][0]
    assert membership_payload['id'] == membership.id
    assert 'payment_status' in membership_payload
    assert 'validity_status' in membership_payload
    assert 'expiry_alert_level' in membership_payload

    assert len(data['consumption']['items']) == 1
    assert data['consumption']['items'][0]['class']['id'] == gym_class.id

    assert len(data['attendance']['items']) == 1
    assert data['attendance']['items'][0]['status'] == 'present'

    assert len(data['reservations']['items']) == 1
    assert data['reservations']['items'][0]['status'] == 'active'

    assert data['recurring_enrollments'] == []


# --------------------------------------------------------------------------------------
# 2. Cross-org: mismo 404 exacto que un alumno inexistente (anti-oráculo).
# --------------------------------------------------------------------------------------

def test_cross_org_and_nonexistent_student_return_the_identical_404(
    api_client, setup, make_organization, make_user,
):
    other_org = make_organization()
    other_admin = make_user('admin-so-other', organization=other_org, role='gym_admin')

    api_client.force_authenticate(user=other_admin)
    resp_foreign = api_client.get(_overview_url(setup['student'].id))

    nonexistent_id = setup['student'].id + 999000
    resp_missing = api_client.get(_overview_url(nonexistent_id))

    assert resp_foreign.status_code == 404, resp_foreign.content
    assert resp_missing.status_code == 404, resp_missing.content
    assert resp_foreign.json() == resp_missing.json()


# --------------------------------------------------------------------------------------
# 3. monitor: 403 y CERO dato financiero (la trampa del check inline).
# --------------------------------------------------------------------------------------

def test_monitor_is_rejected_and_never_sees_financial_data(api_client, setup, make_user):
    monitor = make_user('monitor-so', organization=setup['org'], role='monitor')
    api_client.force_authenticate(user=monitor)

    resp = api_client.get(_overview_url(setup['student'].id))

    assert resp.status_code == 403, resp.content
    # No solo el status: si algún día se afloja el check inline y monitor cuela hasta el
    # handler, este assert sigue cortando cualquier fuga de `payment_status` en el body.
    assert b'payment_status' not in resp.content


# --------------------------------------------------------------------------------------
# 4. manager/teacher/student: 403 (ninguno de los tres es lector de esta pantalla).
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize('role', ['manager', 'teacher', 'student'])
def test_other_org_roles_are_rejected(api_client, setup, make_user, role):
    other_user = make_user(f'u-so-{role}', organization=setup['org'], role=role)
    api_client.force_authenticate(user=other_user)

    resp = api_client.get(_overview_url(setup['student'].id))

    assert resp.status_code == 403, resp.content


def test_superadmin_is_rejected_even_with_an_organization(api_client, setup, make_user):
    """Decisión a confirmar por Javier: la pantalla es de la organización del `gym_admin`, no
    de la plataforma — mismo criterio que `ReportPermission` (reportería)."""
    root = make_user('root-so', organization=setup['org'], role='superadmin')
    api_client.force_authenticate(user=root)

    resp = api_client.get(_overview_url(setup['student'].id))

    assert resp.status_code == 403, resp.content


def test_overview_requires_authentication(api_client, setup):
    resp = api_client.get(_overview_url(setup['student'].id))

    assert resp.status_code == 401, resp.content


# --------------------------------------------------------------------------------------
# 5. El estado/saldo publicado COINCIDE con `describe_student_plan` (fuente única).
# --------------------------------------------------------------------------------------

def test_membership_state_matches_describe_student_plan(api_client, setup):
    api_client.force_authenticate(user=setup['admin'])
    resp = api_client.get(_overview_url(setup['student'].id))
    assert resp.status_code == 200, resp.content

    membership_payload = resp.json()['memberships'][0]
    membership = StudentPlan.objects.get(pk=membership_payload['id'])
    state = describe_student_plan(membership, timezone.localdate())

    assert membership_payload['validity_status'] == state.status
    assert membership_payload['validity_status_label'] == state.label
    assert membership_payload['payment_status'] == state.payment_status
    assert membership_payload['days_to_expiry'] == state.days_to_expiry
    assert membership_payload['remaining_classes'] == max(
        (membership.total_classes or 0) - (membership.classes_used or 0), 0,
    )


# --------------------------------------------------------------------------------------
# 6. Rendimiento: historial acotado con `has_more`, y el tope duro no se puede saltar.
# --------------------------------------------------------------------------------------

def test_history_is_capped_with_has_more_and_the_hard_cap_cannot_be_bypassed(api_client, setup):
    student = setup['student']
    membership = setup['membership']
    gym_class = setup['gym_class']
    branch = setup['branch']

    total_rows = DEFAULT_HISTORY_LIMIT + 5
    for _ in range(total_rows):
        ConsumptionLog.objects.create(
            user=student, student_plan=membership, class_instance=gym_class, branch=branch,
        )

    api_client.force_authenticate(user=setup['admin'])

    resp_default = api_client.get(_overview_url(student.id))
    assert resp_default.status_code == 200, resp_default.content
    consumption_default = resp_default.json()['consumption']
    assert len(consumption_default['items']) == DEFAULT_HISTORY_LIMIT
    assert consumption_default['has_more'] is True
    assert consumption_default['limit'] == DEFAULT_HISTORY_LIMIT

    # Pedir MUCHO más que el tope duro: el `limit` publicado queda clavado en
    # `MAX_HISTORY_LIMIT`, sin importar lo que pida el query param.
    resp_over_cap = api_client.get(
        _overview_url(student.id), {'consumption_limit': MAX_HISTORY_LIMIT + 500},
    )
    assert resp_over_cap.status_code == 200, resp_over_cap.content
    consumption_over_cap = resp_over_cap.json()['consumption']
    assert consumption_over_cap['limit'] == MAX_HISTORY_LIMIT
    assert len(consumption_over_cap['items']) <= MAX_HISTORY_LIMIT


# --------------------------------------------------------------------------------------
# Bonus: id malformado -> 400 (nunca 404), por el mismo motivo que documenta `urls.py`.
# --------------------------------------------------------------------------------------

def test_a_malformed_student_id_is_a_400_and_not_a_404(api_client, setup):
    api_client.force_authenticate(user=setup['admin'])

    resp = api_client.get(_overview_url('no-soy-un-id'))

    assert resp.status_code == 400, resp.content


def test_a_student_id_outside_the_bigint_range_is_a_400_and_not_a_500(api_client, setup):
    """Mismo motivo que `test_reports_revenue_drilldown.py`: en PostgreSQL un `filter(pk=...)`
    fuera del rango de bigint revienta con 500 si no se valida la forma antes."""
    api_client.force_authenticate(user=setup['admin'])

    resp = api_client.get(_overview_url(99999999999999999999))

    assert resp.status_code == 400, resp.content


# --------------------------------------------------------------------------------------
# 7. "FK propia sin organización": el alumno movido de tenant.
#
#    El escenario canónico del repo, y el que faltaba: el alumno ES de la organización del
#    actor (`user.organization` = A, así que la guarda de pertenencia lo deja pasar), pero
#    arrastra datos VIVOS de la organización B donde estuvo antes. `StudentPlan.user`,
#    `ConsumptionLog.user`, `Attendance.student`, `Enrollment.student` y
#    `RecurringEnrollment.student` son FKs sobre el USUARIO, no sobre la organización: mover
#    a alguien de tenant NO se lleva sus filas viejas, quedan alcanzables por `user_id`.
#
#    Un `filter(user_id=...)`/`student_id=...` pelado en cualquiera de las cinco colecciones
#    publica acá los datos de la organización B. Este test es la red de esos cinco filtros:
#    sin él, aflojar cualquiera de los cinco sigue dando la suite en verde.
# --------------------------------------------------------------------------------------

def test_collections_exclude_rows_that_belong_to_another_organization(
    api_client, setup, make_organization, make_user,
):
    student = setup['student']          # `student.organization` es la org A del actor
    other_org = make_organization()

    other_branch = _branch(other_org)
    other_plan = _plan(other_org, name='Pack ajeno')
    other_membership = _membership(student, other_plan)
    other_class = _gym_class(other_org, other_branch, name='Clase ajena')

    ConsumptionLog.objects.create(
        user=student, student_plan=other_membership, class_instance=other_class,
        branch=other_branch,
    )
    Attendance.objects.create(
        gym_class=other_class, student=student,
        status=Attendance.Status.PRESENT, source=Attendance.Source.QR,
    )
    Enrollment.objects.create(
        gym_class=other_class, student=student, status='active',
        student_plan=other_membership,
    )
    other_template = ClassTemplate.objects.create(
        organization=other_org, branch=other_branch, name='Serie ajena',
        weekday=0, start_time=time(10, 0), end_time=time(11, 0),
        start_date=timezone.localdate() - timedelta(days=10),
    )
    RecurringEnrollment.objects.create(
        student=student, class_template=other_template,
        start_date=timezone.localdate() - timedelta(days=10),
        is_active=True, student_plan=other_membership,
    )

    # Guarda de NO-VACUIDAD: las cinco filas ajenas existen y son alcanzables por el filtro
    # INGENUO (`user_id`/`student_id` pelado, sin intersectar organización). Sin esto, el test
    # pasaría igual si el setup no hubiera creado nada y no probaría absolutamente nada: lo
    # que se afirma abajo es que los filtros por organización las descartan, no que no estén.
    assert StudentPlan.objects.filter(user_id=student.id).count() == 2
    assert ConsumptionLog.objects.filter(user_id=student.id).count() == 1
    assert Attendance.objects.filter(student_id=student.id).count() == 1
    assert Enrollment.objects.filter(student_id=student.id).count() == 1
    assert RecurringEnrollment.objects.filter(student_id=student.id).count() == 1

    api_client.force_authenticate(user=setup['admin'])
    resp = api_client.get(_overview_url(student.id))

    assert resp.status_code == 200, resp.content
    data = resp.json()

    # La membresía de la organización B no aparece: el acotamiento va por
    # `StudentPlan.organization` (copia de `plan.organization`), NUNCA por `user.organization`
    # —que acá es justamente la org A y traería la fila ajena—.
    assert [row['id'] for row in data['memberships']] == [setup['membership'].id]
    assert 'Pack ajeno' not in resp.content.decode()
    assert 'Clase ajena' not in resp.content.decode()

    assert data['consumption']['items'] == []
    assert data['attendance']['items'] == []
    assert data['reservations']['items'] == []
    assert data['recurring_enrollments'] == []


def test_a_legacy_row_pointing_at_a_foreign_membership_does_not_leak_the_plan_name(
    api_client, setup, make_organization,
):
    """El nombre del plan se REDACTA si la membresía colgada de la reserva es de otra org.

    `Enrollment.student_plan` es una FK propia sin organización: el queryset se acota por
    `gym_class__organization_id`, lo que NO dice nada de la organización de la MEMBRESÍA. Es
    la forma exacta del hallazgo del drill-down de ingresos. La API de hoy no deja fabricar
    esta fila —las escrituras anclan la org antes—, pero `get_enrollment_student_plan`
    documenta que existen filas legacy así, anteriores al fix de scoping multitenant; por eso
    se arma por ORM directo, que es como llegaron a producción.

    Se redacta el NOMBRE y no se filtra la FILA a propósito: `student_plan` es nullable
    (clase de prueba), así que filtrar por la membresía borraría reservas legítimas.
    """
    student = setup['student']
    other_org = make_organization()
    foreign_membership = _membership(student, _plan(other_org, name='Pack secreto ajeno'))

    Enrollment.objects.create(
        gym_class=setup['gym_class'],        # clase de la org A: la fila SÍ se lista
        student=student, status='active',
        student_plan=foreign_membership,     # membresía de la org B: el nombre NO se publica
    )

    api_client.force_authenticate(user=setup['admin'])
    resp = api_client.get(_overview_url(student.id))

    assert resp.status_code == 200, resp.content
    reservations = resp.json()['reservations']['items']

    assert len(reservations) == 1
    assert reservations[0]['plan_name'] is None
    assert 'Pack secreto ajeno' not in resp.content.decode()
