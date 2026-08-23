"""10.2 — auditoría de correcciones de asistencia (`AttendanceChangeLog`).

Tomar lista (crear un `Attendance` que no existía) sigue abierto a profe/gym_admin/
superadmin y NO deja rastro: no hay "corrección" que auditar todavía. Corregir un
`status` ya registrado queda abierto para gym_admin/superadmin y para el profe dueno
hasta el limite configurado de su organizacion despues del fin de la clase (manager queda AFUERA: es `is_org_admin`
pero este es el corte de ADMIN_WRITE_ROLES/profe operativo) y escribe UNA fila de
`AttendanceChangeLog` dentro de la MISMA transacción que el `save()` del `Attendance` (`core/views.py`, acción `attendance` de
`GymClassViewSet`): todo-o-nada, sin oráculo cross-org (queryset scopeado por
organización → 404, no 403, para un admin ajeno).
"""
from datetime import timedelta
from unittest import mock

import pytest
from django.utils import timezone

from core.models import (
    Attendance,
    AttendanceChangeLog,
    Branch,
    ConsumptionLog,
    Enrollment,
    GymClass,
    Plan,
    StudentPlan,
)

pytestmark = pytest.mark.django_db

PASSWORD = 'Passw0rd2026'
TODAY = timezone.localdate()


def _login(api_client, user):
    host = {'HTTP_HOST': f'{user.organization.subdomain}.localhost'} if user.organization_id else {}
    token = api_client.post(
        '/api/login/', {'email': user.email, 'password': PASSWORD}, format='json', **host
    ).json()['token']
    api_client.credentials(HTTP_AUTHORIZATION=f'Token {token}')


def _attendance_url(gym_class):
    return f'/api/classes/{gym_class.id}/attendance/'


@pytest.fixture
def setup(make_organization, make_user):
    org = make_organization()
    admin = make_user('admin-acl', organization=org, role='gym_admin')
    teacher = make_user('teacher-acl', organization=org, role='teacher')
    student = make_user('student-acl', organization=org, role='student')
    other_student = make_user('other-acl', organization=org, role='student')
    branch = Branch.objects.create(organization=org, name='Sede')
    start = timezone.now() + timedelta(days=1)
    gym_class = GymClass.objects.create(
        organization=org,
        branch=branch,
        teacher=teacher,
        name='Clase',
        start_datetime=start,
        end_datetime=start + timedelta(hours=1),
        capacity=10,
    )
    Enrollment.objects.create(gym_class=gym_class, student=student, status='active')
    Enrollment.objects.create(gym_class=gym_class, student=other_student, status='active')
    return {
        'org': org,
        'admin': admin,
        'teacher': teacher,
        'student': student,
        'other_student': other_student,
        'gym_class': gym_class,
        'branch': branch,
    }


def _mark_attendance(gym_class, student, status, *, marked_by=None, marked_at=None):
    now = marked_at or timezone.now()
    return Attendance.objects.create(
        gym_class=gym_class,
        student=student,
        status=status,
        source=Attendance.Source.MANUAL,
        marked_by=marked_by,
        marked_at=now,
        checked_at=now,
    )


# --------------------------------------------------------------------------------------
# 1. Profe dueño toma lista (sin registros previos): crea, sin logs.
# --------------------------------------------------------------------------------------

def test_teacher_taking_attendance_for_the_first_time_creates_no_log(api_client, setup):
    gym_class = setup['gym_class']
    _login(api_client, setup['teacher'])

    resp = api_client.post(_attendance_url(gym_class), {
        'attendances': [
            {'student_id': setup['student'].id, 'status': 'present'},
            {'student_id': setup['other_student'].id, 'status': 'absent'},
        ],
    }, format='json')

    assert resp.status_code == 200, resp.content
    assert Attendance.objects.filter(gym_class=gym_class).count() == 2
    assert AttendanceChangeLog.objects.count() == 0


# --------------------------------------------------------------------------------------
# 2. Profe dueno corrige dentro de la ventana operativa: 200 y log auditado.
#    Variante: payload mixto (una creacion + una correccion) tambien es todo-o-nada.
# --------------------------------------------------------------------------------------

def test_teacher_can_correct_an_existing_attendance_within_grace_window(api_client, setup):
    gym_class = setup['gym_class']
    student = setup['student']
    other_student = setup['other_student']
    marked_at = timezone.now() - timedelta(hours=1)
    _mark_attendance(gym_class, student, Attendance.Status.PRESENT, marked_by=setup['admin'], marked_at=marked_at)
    _mark_attendance(gym_class, other_student, Attendance.Status.PRESENT, marked_by=setup['admin'], marked_at=marked_at)

    _login(api_client, setup['teacher'])
    resp = api_client.post(_attendance_url(gym_class), {
        'attendances': [
            {'student_id': student.id, 'status': 'absent'},
            {'student_id': other_student.id, 'status': 'present'},
        ],
    }, format='json')

    assert resp.status_code == 200, resp.content
    attendance = Attendance.objects.get(gym_class=gym_class, student=student)
    assert attendance.status == Attendance.Status.ABSENT
    assert AttendanceChangeLog.objects.count() == 1
    log = AttendanceChangeLog.objects.get()
    assert log.attendance_id == attendance.id
    assert log.previous_status == Attendance.Status.PRESENT
    assert log.new_status == Attendance.Status.ABSENT
    assert log.changed_by_id == setup['teacher'].id


def test_teacher_mixed_payload_new_plus_correction_is_all_or_nothing_within_grace(api_client, setup):
    """Un alumno con registro previo (correccion) mezclado con un alumno nuevo (creacion):
    el profe puede guardar ambos dentro de la ventana operativa; si una escritura fallara,
    el request completo debe revertirse."""
    gym_class = setup['gym_class']
    student = setup['student']
    other_student = setup['other_student']
    marked_at = timezone.now() - timedelta(hours=1)
    _mark_attendance(gym_class, student, Attendance.Status.PRESENT, marked_by=setup['admin'], marked_at=marked_at)
    # `other_student` NO tiene registro todavía: sería una creación legítima si viajara sola.

    _login(api_client, setup['teacher'])
    resp = api_client.post(_attendance_url(gym_class), {
        'attendances': [
            {'student_id': student.id, 'status': 'absent'},  # corrección
            {'student_id': other_student.id, 'status': 'present'},  # creación
        ],
    }, format='json')

    assert resp.status_code == 200, resp.content
    attendance = Attendance.objects.get(gym_class=gym_class, student=student)
    assert attendance.status == Attendance.Status.ABSENT
    assert Attendance.objects.filter(
        gym_class=gym_class,
        student=other_student,
        status=Attendance.Status.PRESENT,
    ).exists()
    assert AttendanceChangeLog.objects.count() == 1


def test_manager_cannot_correct_an_existing_attendance(api_client, setup, make_user):
    """Manager es `is_org_admin` (y por eso puede TOMAR lista, como hoy), pero la
    corrección corta en gym_admin/superadmin: mismo grupo que ADMIN_WRITE_ROLES."""
    gym_class = setup['gym_class']
    student = setup['student']
    other_student = setup['other_student']
    marked_at = timezone.now() - timedelta(hours=1)
    _mark_attendance(gym_class, student, Attendance.Status.PRESENT, marked_by=setup['admin'], marked_at=marked_at)
    _mark_attendance(gym_class, other_student, Attendance.Status.PRESENT, marked_by=setup['admin'], marked_at=marked_at)

    manager = make_user('manager-acl', organization=setup['org'], role='manager')
    _login(api_client, manager)
    resp = api_client.post(_attendance_url(gym_class), {
        'attendances': [
            {'student_id': student.id, 'status': 'absent'},
            {'student_id': other_student.id, 'status': 'present'},
        ],
    }, format='json')

    assert resp.status_code == 403, resp.content
    attendance = Attendance.objects.get(gym_class=gym_class, student=student)
    assert attendance.status == Attendance.Status.PRESENT
    assert AttendanceChangeLog.objects.count() == 0


# --------------------------------------------------------------------------------------
# 3. gym_admin de la org corrige: 200, status actualizado, exactamente 1 log correcto.
# --------------------------------------------------------------------------------------

def test_gym_admin_correction_writes_exactly_one_log(api_client, setup):
    gym_class = setup['gym_class']
    student = setup['student']
    other_student = setup['other_student']
    marked_at = timezone.now() - timedelta(hours=1)
    _mark_attendance(gym_class, student, Attendance.Status.PRESENT, marked_by=setup['teacher'], marked_at=marked_at)
    _mark_attendance(gym_class, other_student, Attendance.Status.ABSENT, marked_by=setup['teacher'], marked_at=marked_at)

    _login(api_client, setup['admin'])
    resp = api_client.post(_attendance_url(gym_class), {
        'attendances': [
            {'student_id': student.id, 'status': 'absent'},
            {'student_id': other_student.id, 'status': 'absent'},  # sin cambio -> no-op
        ],
    }, format='json')

    assert resp.status_code == 200, resp.content
    attendance = Attendance.objects.get(gym_class=gym_class, student=student)
    assert attendance.status == Attendance.Status.ABSENT

    assert AttendanceChangeLog.objects.count() == 1
    log = AttendanceChangeLog.objects.get()
    assert log.attendance_id == attendance.id
    assert log.previous_status == Attendance.Status.PRESENT
    assert log.new_status == Attendance.Status.ABSENT
    assert log.changed_by_id == setup['admin'].id
    assert log.organization_id == gym_class.organization_id


# --------------------------------------------------------------------------------------
# 4. Re-guardar con el MISMO status es no-op: 200, sin log, sin re-estampar marked_at/marked_by.
# --------------------------------------------------------------------------------------

def test_resaving_the_same_status_is_a_noop_and_does_not_restamp(api_client, setup):
    gym_class = setup['gym_class']
    student = setup['student']
    other_student = setup['other_student']
    original_marked_at = timezone.now() - timedelta(hours=2)
    attendance = _mark_attendance(
        gym_class, student, Attendance.Status.PRESENT,
        marked_by=setup['teacher'], marked_at=original_marked_at,
    )
    _mark_attendance(gym_class, other_student, Attendance.Status.PRESENT, marked_by=setup['teacher'], marked_at=original_marked_at)

    _login(api_client, setup['admin'])
    resp = api_client.post(_attendance_url(gym_class), {
        'attendances': [
            {'student_id': student.id, 'status': 'present'},  # mismo status -> no-op
            {'student_id': other_student.id, 'status': 'present'},
        ],
    }, format='json')

    assert resp.status_code == 200, resp.content
    attendance.refresh_from_db()
    assert attendance.status == Attendance.Status.PRESENT
    assert attendance.marked_by_id == setup['teacher'].id
    assert attendance.marked_at == original_marked_at
    assert AttendanceChangeLog.objects.count() == 0


# --------------------------------------------------------------------------------------
# 5. Atomicidad: si falla la escritura del log, el status del Attendance NO cambia.
# --------------------------------------------------------------------------------------

def test_correction_rolls_back_if_the_log_write_fails(api_client, setup):
    gym_class = setup['gym_class']
    student = setup['student']
    other_student = setup['other_student']
    marked_at = timezone.now() - timedelta(hours=1)
    _mark_attendance(gym_class, student, Attendance.Status.PRESENT, marked_by=setup['teacher'], marked_at=marked_at)
    _mark_attendance(gym_class, other_student, Attendance.Status.PRESENT, marked_by=setup['teacher'], marked_at=marked_at)

    _login(api_client, setup['admin'])

    with mock.patch(
        'core.views.AttendanceChangeLog.objects.create',
        side_effect=RuntimeError('boom'),
    ):
        with pytest.raises(RuntimeError):
            api_client.post(_attendance_url(gym_class), {
                'attendances': [
                    {'student_id': student.id, 'status': 'absent'},
                    {'student_id': other_student.id, 'status': 'present'},
                ],
            }, format='json')

    attendance = Attendance.objects.get(gym_class=gym_class, student=student)
    assert attendance.status == Attendance.Status.PRESENT, 'el rollback debe deshacer también el save() del Attendance'
    assert AttendanceChangeLog.objects.count() == 0


# --------------------------------------------------------------------------------------
# 6. Consumo desacoplado: ni tomar lista ni corregir tocan StudentPlan/ConsumptionLog.
# --------------------------------------------------------------------------------------

def test_attendance_creation_and_correction_do_not_touch_consumption(api_client, setup):
    gym_class = setup['gym_class']
    student = setup['student']
    plan = Plan.objects.create(
        organization=setup['org'], name='Pack', plan_type='pack',
        total_classes=10, duration_days=30, price=30000,
    )
    student_plan = StudentPlan.objects.create(
        user=student, plan=plan, organization_id=plan.organization_id,
        start_date=TODAY - timedelta(days=1), end_date=TODAY + timedelta(days=30),
        total_classes=10, classes_used=0, final_price=plan.price,
    )
    assert ConsumptionLog.objects.count() == 0

    _login(api_client, setup['teacher'])
    create_resp = api_client.post(_attendance_url(gym_class), {
        'attendances': [
            {'student_id': student.id, 'status': 'present'},
            {'student_id': setup['other_student'].id, 'status': 'present'},
        ],
    }, format='json')
    assert create_resp.status_code == 200, create_resp.content

    student_plan.refresh_from_db()
    assert student_plan.classes_used == 0
    assert ConsumptionLog.objects.count() == 0

    _login(api_client, setup['admin'])
    correct_resp = api_client.post(_attendance_url(gym_class), {
        'attendances': [
            {'student_id': student.id, 'status': 'absent'},
            {'student_id': setup['other_student'].id, 'status': 'present'},
        ],
    }, format='json')
    assert correct_resp.status_code == 200, correct_resp.content

    student_plan.refresh_from_db()
    assert student_plan.classes_used == 0
    assert ConsumptionLog.objects.count() == 0


# --------------------------------------------------------------------------------------
# 7. gym_admin de OTRA organización: 404 (el queryset org-scoped no expone la clase).
# --------------------------------------------------------------------------------------

def test_gym_admin_of_another_organization_gets_404(api_client, setup, make_organization, make_user):
    gym_class = setup['gym_class']
    student = setup['student']
    marked_at = timezone.now() - timedelta(hours=1)
    _mark_attendance(gym_class, student, Attendance.Status.PRESENT, marked_by=setup['teacher'], marked_at=marked_at)

    other_org = make_organization()
    other_admin = make_user('admin-acl-other', organization=other_org, role='gym_admin')

    _login(api_client, other_admin)
    resp = api_client.post(_attendance_url(gym_class), {
        'attendances': [
            {'student_id': student.id, 'status': 'absent'},
        ],
    }, format='json')

    assert resp.status_code == 404, resp.content
    attendance = Attendance.objects.get(gym_class=gym_class, student=student)
    assert attendance.status == Attendance.Status.PRESENT
    assert AttendanceChangeLog.objects.count() == 0
