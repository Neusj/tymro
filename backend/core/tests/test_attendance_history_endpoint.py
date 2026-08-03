"""10.2 — endpoint de lectura del historial de correcciones de asistencia.

`GET /classes/{id}/attendance-history/` expone las filas de `AttendanceChangeLog` de
una clase. El historial es auditoría de staff: solo lo ve un admin de la MISMA
organización (o superadmin). Ni el profe dueño de la clase ni el alumno lo ven, aunque
el queryset org-scoped de `GymClassViewSet.get_object()` sí les resuelva la clase (por
eso el corte real es el check inline -> 403, no un 404 del queryset). Un admin de OTRA
organización sí choca contra el queryset org-scoped -> 404, sin oráculo de existencia.
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from core.models import Attendance, AttendanceChangeLog, Branch, Enrollment, GymClass

pytestmark = pytest.mark.django_db

PASSWORD = 'Passw0rd2026'


def _login(api_client, user):
    host = {'HTTP_HOST': f'{user.organization.subdomain}.localhost'} if user.organization_id else {}
    token = api_client.post(
        '/api/login/', {'email': user.email, 'password': PASSWORD}, format='json', **host
    ).json()['token']
    api_client.credentials(HTTP_AUTHORIZATION=f'Token {token}')


def _attendance_url(gym_class):
    return f'/api/classes/{gym_class.id}/attendance/'


def _history_url(gym_class):
    return f'/api/classes/{gym_class.id}/attendance-history/'


@pytest.fixture
def setup(make_organization, make_user):
    org = make_organization()
    admin = make_user('admin-ahe', organization=org, role='gym_admin')
    teacher = make_user('teacher-ahe', organization=org, role='teacher')
    student = make_user('student-ahe', organization=org, role='student')
    other_student = make_user('other-ahe', organization=org, role='student')
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


def _correct_via_api(api_client, gym_class, attendances):
    """Corrige asistencia(s) ya registrada(s) vía el POST /attendance/ (como haría el
    admin en producción), para que quede la fila de `AttendanceChangeLog` real que el
    endpoint bajo prueba debe exponer. El payload debe traer exactamente los alumnos
    inscritos activos de la clase (lo valida la action), así que `attendances` debe
    listar a TODOS, no solo al que cambia."""
    return api_client.post(_attendance_url(gym_class), {
        'attendances': attendances,
    }, format='json')


# --------------------------------------------------------------------------------------
# 1. gym_admin de la org: 200, ve los logs con los campos esperados, orden -changed_at.
# --------------------------------------------------------------------------------------

def test_gym_admin_sees_history_ordered_most_recent_first(api_client, setup):
    gym_class = setup['gym_class']
    student = setup['student']
    other_student = setup['other_student']
    marked_at = timezone.now() - timedelta(hours=2)
    _mark_attendance(gym_class, student, Attendance.Status.PRESENT, marked_by=setup['teacher'], marked_at=marked_at)
    _mark_attendance(gym_class, other_student, Attendance.Status.ABSENT, marked_by=setup['teacher'], marked_at=marked_at)

    _login(api_client, setup['admin'])

    # Primera corrección.
    resp1 = _correct_via_api(api_client, gym_class, [
        {'student_id': student.id, 'status': 'absent'},
        {'student_id': other_student.id, 'status': 'absent'},  # sin cambio -> no-op
    ])
    assert resp1.status_code == 200, resp1.content

    # Segunda corrección (otro alumno), debe quedar ordenada antes que la primera.
    resp2 = _correct_via_api(api_client, gym_class, [
        {'student_id': student.id, 'status': 'absent'},  # sin cambio -> no-op
        {'student_id': other_student.id, 'status': 'present'},
    ])
    assert resp2.status_code == 200, resp2.content

    assert AttendanceChangeLog.objects.count() == 2

    resp = api_client.get(_history_url(gym_class))
    assert resp.status_code == 200, resp.content
    data = resp.json()
    assert len(data) == 2

    # Orden más-reciente-primero: la segunda corrección (other_student) va primero.
    assert data[0]['student'] == other_student.id
    assert data[0]['previous_status'] == 'absent'
    assert data[0]['new_status'] == 'present'
    assert data[0]['changed_by'] == setup['admin'].id
    assert data[0]['changed_by_username'] == setup['admin'].username
    full_name = f"{other_student.first_name} {other_student.last_name}".strip()
    assert data[0]['student_name'] == (full_name or other_student.username)

    assert data[1]['student'] == student.id
    assert data[1]['previous_status'] == 'present'
    assert data[1]['new_status'] == 'absent'
    assert data[1]['changed_by'] == setup['admin'].id

    log_ids = {log['id'] for log in data}
    assert log_ids == set(AttendanceChangeLog.objects.values_list('id', flat=True))
    attendance_ids = {log['attendance'] for log in data}
    assert attendance_ids == set(AttendanceChangeLog.objects.values_list('attendance_id', flat=True))


# --------------------------------------------------------------------------------------
# 2. Profe dueño de la clase: 403 (la auditoría es exclusiva de admin, aunque el profe
#    resuelva la clase por el queryset org-scoped).
# --------------------------------------------------------------------------------------

def test_teacher_owner_of_the_class_gets_403(api_client, setup):
    gym_class = setup['gym_class']
    student = setup['student']
    other_student = setup['other_student']
    marked_at = timezone.now() - timedelta(hours=1)
    _mark_attendance(gym_class, student, Attendance.Status.PRESENT, marked_by=setup['teacher'], marked_at=marked_at)
    _mark_attendance(gym_class, other_student, Attendance.Status.PRESENT, marked_by=setup['teacher'], marked_at=marked_at)

    _login(api_client, setup['admin'])
    correction = _correct_via_api(api_client, gym_class, [
        {'student_id': student.id, 'status': 'absent'},
        {'student_id': other_student.id, 'status': 'present'},
    ])
    assert correction.status_code == 200, correction.content

    _login(api_client, setup['teacher'])
    resp = api_client.get(_history_url(gym_class))

    assert resp.status_code == 403, resp.content


def test_manager_of_the_org_gets_403(api_client, setup, make_user):
    """Manager es `is_org_admin` pero el historial corta en gym_admin/superadmin
    (mismo corte que la corrección: grupo ADMIN_WRITE_ROLES, no el operativo)."""
    gym_class = setup['gym_class']
    student = setup['student']
    other_student = setup['other_student']
    marked_at = timezone.now() - timedelta(hours=1)
    _mark_attendance(gym_class, student, Attendance.Status.PRESENT, marked_by=setup['teacher'], marked_at=marked_at)
    _mark_attendance(gym_class, other_student, Attendance.Status.PRESENT, marked_by=setup['teacher'], marked_at=marked_at)

    _login(api_client, setup['admin'])
    correction = _correct_via_api(api_client, gym_class, [
        {'student_id': student.id, 'status': 'absent'},
        {'student_id': other_student.id, 'status': 'present'},
    ])
    assert correction.status_code == 200, correction.content

    manager = make_user('manager-ahe', organization=setup['org'], role='manager')
    _login(api_client, manager)
    resp = api_client.get(_history_url(gym_class))

    assert resp.status_code == 403, resp.content


# --------------------------------------------------------------------------------------
# 3. Alumno de la org: no ve datos. El queryset de estudiante SI resuelve la clase (misma
#    org, no suspendida), así que el corte lo da el check inline -> 403.
# --------------------------------------------------------------------------------------

def test_student_of_the_org_does_not_see_history(api_client, setup):
    gym_class = setup['gym_class']
    student = setup['student']
    other_student = setup['other_student']
    marked_at = timezone.now() - timedelta(hours=1)
    _mark_attendance(gym_class, student, Attendance.Status.PRESENT, marked_by=setup['teacher'], marked_at=marked_at)
    _mark_attendance(gym_class, other_student, Attendance.Status.PRESENT, marked_by=setup['teacher'], marked_at=marked_at)

    _login(api_client, setup['admin'])
    correction = _correct_via_api(api_client, gym_class, [
        {'student_id': student.id, 'status': 'absent'},
        {'student_id': other_student.id, 'status': 'present'},
    ])
    assert correction.status_code == 200, correction.content

    _login(api_client, student)
    resp = api_client.get(_history_url(gym_class))

    # El queryset de GymClassViewSet para alumnos SI incluye clases de su propia
    # organización (no filtra por inscripción salvo `?mine=1`), así que `get_object()`
    # resuelve la clase y el corte real es el check inline de la action -> 403.
    assert resp.status_code == 403, resp.content


# --------------------------------------------------------------------------------------
# 4. gym_admin de OTRA organización: 404 (el queryset org-scoped no expone la clase; sin
#    oráculo de existencia, mismo patrón que el POST /attendance/).
# --------------------------------------------------------------------------------------

def test_gym_admin_of_another_organization_gets_404(api_client, setup, make_organization, make_user):
    gym_class = setup['gym_class']
    student = setup['student']
    other_student = setup['other_student']
    marked_at = timezone.now() - timedelta(hours=1)
    _mark_attendance(gym_class, student, Attendance.Status.PRESENT, marked_by=setup['teacher'], marked_at=marked_at)
    _mark_attendance(gym_class, other_student, Attendance.Status.PRESENT, marked_by=setup['teacher'], marked_at=marked_at)

    _login(api_client, setup['admin'])
    correction = _correct_via_api(api_client, gym_class, [
        {'student_id': student.id, 'status': 'absent'},
        {'student_id': other_student.id, 'status': 'present'},
    ])
    assert correction.status_code == 200, correction.content

    other_org = make_organization()
    other_admin = make_user('admin-ahe-other', organization=other_org, role='gym_admin')

    _login(api_client, other_admin)
    resp = api_client.get(_history_url(gym_class))

    assert resp.status_code == 404, resp.content


# --------------------------------------------------------------------------------------
# 5. Clase sin correcciones: 200 con lista vacía (no 404, no error).
# --------------------------------------------------------------------------------------

def test_class_without_corrections_returns_empty_list(api_client, setup):
    gym_class = setup['gym_class']

    _login(api_client, setup['admin'])
    resp = api_client.get(_history_url(gym_class))

    assert resp.status_code == 200, resp.content
    assert resp.json() == []
