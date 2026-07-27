"""`DELETE /api/enrollments/{id}/` tiene que devolver el saldo y respetar el deadline.

`EnrollmentViewSet.perform_destroy` hacía `instance.delete()` a secas. `ConsumptionLog`
NO tiene FK a `Enrollment` (cuelga de user + class_instance + student_plan), así que el
borrado dejaba el log vivo y `classes_used` inflado. Tres consecuencias:

1. El alumno queda cobrado sin inscripción.
2. El log queda huérfano (consumo sin inscripción activa), que es justo el estado que
   ciega las guardas de series y de clases — ver `test_recurrence_delete_refunds`.
3. Un alumno podía usar DELETE en vez de la acción `cancel` para saltarse
   `STUDENT_CANCEL_DEADLINE_HOURS`.

La reversión es INCONDICIONAL (no aplica `should_refund_consumption`): si la inscripción
desaparece del historial, su consumo tiene que desaparecer con ella. La política de
ventana de cancelación gobierna SI se permite borrar, no si se devuelve el saldo — un
borrado que dejara el log detrás reintroduciría el saldo fantasma.
"""
from datetime import timedelta

import pytest
from django.test import override_settings
from django.utils import timezone

from core.models import Branch, ConsumptionLog, Enrollment, GymClass, Plan, StudentPlan

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
    make_user('admin', organization=org, role='gym_admin')
    teacher = make_user('teach', organization=org, role='teacher')
    student = make_user('alu', organization=org, role='student', email='alu@gym.cl')
    otro = make_user('otro', organization=org, role='student', email='otro@gym.cl')
    branch = Branch.objects.create(organization=org, name='Sede Centro')
    return {
        'org': org, 'teacher': teacher, 'student': student, 'otro': otro,
        'branch': branch,
    }


def _class(setup, hours=48, status=GymClass.Status.SCHEDULED):
    start = timezone.now() + timedelta(hours=hours)
    return GymClass.objects.create(
        organization=setup['org'], branch=setup['branch'], teacher=setup['teacher'],
        name='Clase', start_datetime=start, end_datetime=start + timedelta(hours=1),
        capacity=10, status=status,
    )


def _student_plan(setup, student=None, classes_used=0):
    today = timezone.localdate()
    plan = Plan.objects.create(
        organization=setup['org'], name='Pack 10', plan_type='pack',
        total_classes=10, duration_days=30, price=30000,
    )
    return StudentPlan.objects.create(
        user=student or setup['student'], plan=plan,
        start_date=today - timedelta(days=1), end_date=today + timedelta(days=30),
        total_classes=10, classes_used=classes_used, final_price=30000,
    )


def _consumed_enrollment(setup, gym_class, student=None, student_plan=None, status='active'):
    """Inscripción con su consumo ya registrado, como la deja `reserve_student_in_class`."""
    student = student or setup['student']
    student_plan = student_plan or _student_plan(setup, student=student)
    enrollment = Enrollment.objects.create(
        gym_class=gym_class, student=student, status=status,
    )
    ConsumptionLog.objects.create(
        user=student, student_plan=student_plan, class_instance=gym_class,
        branch=gym_class.branch,
    )
    student_plan.classes_used += 1
    student_plan.save(update_fields=['classes_used', 'updated_at'])
    return enrollment, student_plan


def _assert_no_phantom(student_plan):
    student_plan.refresh_from_db()
    backing = ConsumptionLog.objects.filter(student_plan=student_plan).count()
    assert student_plan.classes_used == backing, (
        f'saldo fantasma: classes_used={student_plan.classes_used} pero hay '
        f'{backing} consumo(s) que lo respalden'
    )


# ---------------------------------------------------------------------------
# Reversión del consumo
# ---------------------------------------------------------------------------

def test_admin_destroy_reverts_the_consumption(api_client, setup):
    """Borrar la inscripción devuelve la clase al plan y no deja log huérfano."""
    gym_class = _class(setup)
    enrollment, student_plan = _consumed_enrollment(setup, gym_class)
    _login(api_client, 'admin')

    resp = api_client.delete(f'/api/enrollments/{enrollment.id}/')

    assert resp.status_code == 204, resp.content
    assert not Enrollment.objects.filter(id=enrollment.id).exists()
    student_plan.refresh_from_db()
    assert student_plan.classes_used == 0, 'borrar debe devolver el saldo'
    assert not ConsumptionLog.objects.filter(
        class_instance=gym_class, user=setup['student'],
    ).exists(), 'no puede quedar un ConsumptionLog sin inscripción que lo respalde'
    _assert_no_phantom(student_plan)


def test_destroy_of_a_past_class_leaves_no_orphan_log(api_client, setup):
    """Clase ya terminada: `should_refund_consumption` diría "no devolver", pero el log
    NO puede sobrevivir a la inscripción — si sobrevive, queda el consumo huérfano que
    ciega las guardas de borrado de clases y series."""
    gym_class = _class(setup, hours=-48, status=GymClass.Status.COMPLETED)
    enrollment, student_plan = _consumed_enrollment(setup, gym_class)
    _login(api_client, 'admin')

    resp = api_client.delete(f'/api/enrollments/{enrollment.id}/')

    assert resp.status_code == 204, resp.content
    assert not ConsumptionLog.objects.filter(class_instance=gym_class).exists()
    _assert_no_phantom(student_plan)


def test_destroy_of_a_cancelled_enrollment_keeps_the_invariant(api_client, setup):
    """Una inscripción cancelada FUERA de la ventana de reembolso conserva su consumo
    (el alumno gastó la clase). Al borrarla, el log se va con ella y el contador baja:
    `rollback_consumption_for_enrollment` no sirve acá porque exige status='active'."""
    gym_class = _class(setup, hours=-48, status=GymClass.Status.COMPLETED)
    enrollment, student_plan = _consumed_enrollment(setup, gym_class, status='cancelled')
    _login(api_client, 'admin')

    resp = api_client.delete(f'/api/enrollments/{enrollment.id}/')

    assert resp.status_code == 204, resp.content
    assert not ConsumptionLog.objects.filter(class_instance=gym_class).exists()
    _assert_no_phantom(student_plan)


def test_destroy_only_touches_its_own_consumption(api_client, setup):
    """El reverso del saldo se limita a (alumno, clase) de ESA inscripción: el consumo
    de otro alumno en la misma clase, y el del mismo alumno en otra clase, quedan."""
    gym_class = _class(setup)
    otra = _class(setup, hours=72)
    enrollment, student_plan = _consumed_enrollment(setup, gym_class)
    _, otro_plan = _consumed_enrollment(setup, gym_class, student=setup['otro'])
    ConsumptionLog.objects.create(
        user=setup['student'], student_plan=student_plan, class_instance=otra,
        branch=otra.branch,
    )
    student_plan.classes_used += 1
    student_plan.save(update_fields=['classes_used', 'updated_at'])
    _login(api_client, 'admin')

    resp = api_client.delete(f'/api/enrollments/{enrollment.id}/')

    assert resp.status_code == 204, resp.content
    student_plan.refresh_from_db()
    assert student_plan.classes_used == 1, 'solo se devuelve el consumo de esta clase'
    assert ConsumptionLog.objects.filter(
        class_instance=otra, user=setup['student'],
    ).exists()
    otro_plan.refresh_from_db()
    assert otro_plan.classes_used == 1, 'el consumo del otro alumno no se toca'
    assert ConsumptionLog.objects.filter(
        class_instance=gym_class, user=setup['otro'],
    ).exists()
    _assert_no_phantom(student_plan)
    _assert_no_phantom(otro_plan)


def test_destroy_without_consumption_still_works(api_client, setup):
    """Regresión: borrar una inscripción sin ConsumptionLog no puede romperse."""
    gym_class = _class(setup)
    enrollment = Enrollment.objects.create(gym_class=gym_class, student=setup['student'])
    _login(api_client, 'admin')

    resp = api_client.delete(f'/api/enrollments/{enrollment.id}/')

    assert resp.status_code == 204, resp.content
    assert not Enrollment.objects.filter(id=enrollment.id).exists()


# ---------------------------------------------------------------------------
# STUDENT_CANCEL_DEADLINE_HOURS
# ---------------------------------------------------------------------------

@override_settings(STUDENT_CANCEL_DEADLINE_HOURS=24)
def test_student_destroy_respects_the_cancel_deadline(api_client, setup):
    """DELETE no puede ser la puerta trasera de la acción `cancel`: dentro de las 24h el
    alumno no puede deshacerse de la reserva ni recuperar el saldo."""
    gym_class = _class(setup, hours=2)
    enrollment, student_plan = _consumed_enrollment(setup, gym_class)
    _login(api_client, 'alu')

    resp = api_client.delete(f'/api/enrollments/{enrollment.id}/')

    assert resp.status_code == 400, resp.content
    assert Enrollment.objects.filter(id=enrollment.id).exists(), 'la reserva sobrevive'
    student_plan.refresh_from_db()
    assert student_plan.classes_used == 1, 'el saldo NO se devuelve'
    _assert_no_phantom(student_plan)


@override_settings(STUDENT_CANCEL_DEADLINE_HOURS=24)
def test_student_destroy_outside_the_deadline_reverts(api_client, setup):
    """Con margen suficiente, el alumno sí puede borrar y recupera su clase."""
    gym_class = _class(setup, hours=48)
    enrollment, student_plan = _consumed_enrollment(setup, gym_class)
    _login(api_client, 'alu')

    resp = api_client.delete(f'/api/enrollments/{enrollment.id}/')

    assert resp.status_code == 204, resp.content
    student_plan.refresh_from_db()
    assert student_plan.classes_used == 0
    _assert_no_phantom(student_plan)


@override_settings(STUDENT_CANCEL_DEADLINE_HOURS=24)
def test_student_cannot_destroy_a_started_class_enrollment(api_client, setup):
    """Clase ya iniciada: el alumno no puede borrar su asistencia ni su consumo."""
    gym_class = _class(setup, hours=-2, status=GymClass.Status.COMPLETED)
    enrollment, student_plan = _consumed_enrollment(setup, gym_class)
    _login(api_client, 'alu')

    resp = api_client.delete(f'/api/enrollments/{enrollment.id}/')

    assert resp.status_code == 400, resp.content
    assert Enrollment.objects.filter(id=enrollment.id).exists()
    student_plan.refresh_from_db()
    assert student_plan.classes_used == 1


@override_settings(STUDENT_CANCEL_DEADLINE_HOURS=24)
def test_admin_destroy_is_not_bound_by_the_student_deadline(api_client, setup):
    """El deadline es una regla para el alumno; el admin de la org sigue pudiendo borrar."""
    gym_class = _class(setup, hours=2)
    enrollment, student_plan = _consumed_enrollment(setup, gym_class)
    _login(api_client, 'admin')

    resp = api_client.delete(f'/api/enrollments/{enrollment.id}/')

    assert resp.status_code == 204, resp.content
    student_plan.refresh_from_db()
    assert student_plan.classes_used == 0


# ---------------------------------------------------------------------------
# Scoping (que el fix no abra otra puerta)
# ---------------------------------------------------------------------------

def test_admin_of_another_org_cannot_destroy(api_client, setup, make_organization, make_user):
    """Aislamiento: gym_admin de la org B no alcanza una inscripción de la org A."""
    gym_class = _class(setup)
    enrollment, student_plan = _consumed_enrollment(setup, gym_class)
    org_b = make_organization()
    make_user('admin_b', organization=org_b, role='gym_admin')
    _login(api_client, 'admin_b')

    resp = api_client.delete(f'/api/enrollments/{enrollment.id}/')

    assert resp.status_code == 404, resp.content
    assert Enrollment.objects.filter(id=enrollment.id).exists()
    student_plan.refresh_from_db()
    assert student_plan.classes_used == 1, 'no se toca el saldo de otra organización'


def test_student_cannot_destroy_another_students_enrollment(api_client, setup):
    """Un alumno no puede borrar (ni reembolsar) la reserva de un compañero."""
    gym_class = _class(setup)
    enrollment, student_plan = _consumed_enrollment(setup, gym_class)
    _login(api_client, 'otro')

    resp = api_client.delete(f'/api/enrollments/{enrollment.id}/')

    assert resp.status_code == 404, resp.content
    assert Enrollment.objects.filter(id=enrollment.id).exists()
    student_plan.refresh_from_db()
    assert student_plan.classes_used == 1


def test_teacher_cannot_destroy_enrollments(api_client, setup):
    """Anclaje: el profe cancela (acción `cancel`) pero no borra el registro."""
    gym_class = _class(setup)
    enrollment, student_plan = _consumed_enrollment(setup, gym_class)
    _login(api_client, 'teach')

    resp = api_client.delete(f'/api/enrollments/{enrollment.id}/')

    assert resp.status_code in {403, 404}, resp.content
    assert Enrollment.objects.filter(id=enrollment.id).exists()
    student_plan.refresh_from_db()
    assert student_plan.classes_used == 1
