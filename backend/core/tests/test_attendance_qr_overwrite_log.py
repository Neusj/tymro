"""10.2-H1 — el check-in por QR no puede pisar un status ya registrado sin dejar rastro.

`AttendanceQrCheckInView.post` usa `update_or_create`: si ya había un `Attendance` con un
`status` distinto de PRESENT (p.ej. un admin lo corrigió a `absent`), el QR lo pisaba a
`present` en silencio. Ahora, en la MISMA transacción que el `update_or_create`, si había
un registro previo con status != PRESENT se escribe una fila de `AttendanceChangeLog` con
`source='qr'` y `changed_by` = el alumno que hizo el check-in. Si NO había registro previo
(primer marcado normal) el comportamiento es idéntico al de antes: sin log. El caso
`existing.status == PRESENT` sigue siendo el early-return `already_registered` sin
escribir nada (ya cubierto por `test_double_mark_is_blocked` en test_attendance.py).
"""
from datetime import timedelta

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
from core.views import _build_checkin_grant

pytestmark = pytest.mark.django_db

PASSWORD = 'Passw0rd2026'
CHECKIN_URL = '/api/attendance-qr/check-in/'
TODAY = timezone.localdate()


def _login(api_client, user):
    host = {'HTTP_HOST': f'{user.organization.subdomain}.localhost'} if user.organization_id else {}
    token = api_client.post(
        '/api/login/', {'email': user.email, 'password': PASSWORD}, format='json', **host
    ).json()['token']
    api_client.credentials(HTTP_AUTHORIZATION=f'Token {token}')


@pytest.fixture
def setup(make_organization, make_user):
    org = make_organization()
    admin = make_user('admin-qro', organization=org, role='gym_admin')
    student = make_user('student-qro', organization=org, role='student')
    branch = Branch.objects.create(organization=org, name='Sede')
    # Clase EN VENTANA (empezó hace 2 min): el grant siempre valida sobre una clase
    # ya en curso, igual que en test_attendance.py::qr_setup.
    start = timezone.now() - timedelta(minutes=2)
    gym_class = GymClass.objects.create(
        organization=org,
        branch=branch,
        name='Clase en curso',
        start_datetime=start,
        end_datetime=start + timedelta(hours=1),
    )
    Enrollment.objects.create(gym_class=gym_class, student=student, status='active')
    return {'org': org, 'admin': admin, 'student': student, 'gym_class': gym_class}


def _mark_attendance(gym_class, student, status, *, marked_by=None):
    now = timezone.now() - timedelta(minutes=1)
    return Attendance.objects.create(
        gym_class=gym_class,
        student=student,
        status=status,
        source=Attendance.Source.MANUAL,
        marked_by=marked_by,
        marked_at=now,
        checked_at=now,
    )


def _grant(setup):
    return _build_checkin_grant(setup['student'].id, setup['gym_class'].id, setup['org'].id)


# --------------------------------------------------------------------------------------
# 1. Check-in normal (sin registro previo): crea present/qr, CERO logs.
# --------------------------------------------------------------------------------------

def test_checkin_without_previous_record_creates_no_log(api_client, setup):
    gym_class = setup['gym_class']
    student = setup['student']

    _login(api_client, student)
    resp = api_client.post(CHECKIN_URL, {'grant': _grant(setup)}, format='json')

    assert resp.status_code == 200, resp.content
    assert resp.json()['status'] == 'registered'
    attendance = Attendance.objects.get(gym_class=gym_class, student=student)
    assert attendance.status == Attendance.Status.PRESENT
    assert attendance.source == Attendance.Source.QR
    assert AttendanceChangeLog.objects.count() == 0


# --------------------------------------------------------------------------------------
# 2. QR pisa un status existente (admin dejó `absent`): Attendance queda present/qr Y
#    hay exactamente 1 log con previous_status='absent', changed_by=alumno, source='qr'.
# --------------------------------------------------------------------------------------

def test_qr_overwriting_existing_status_writes_exactly_one_log(api_client, setup):
    gym_class = setup['gym_class']
    student = setup['student']
    admin = setup['admin']
    _mark_attendance(gym_class, student, Attendance.Status.ABSENT, marked_by=admin)

    _login(api_client, student)
    resp = api_client.post(CHECKIN_URL, {'grant': _grant(setup)}, format='json')

    assert resp.status_code == 200, resp.content
    assert resp.json()['status'] == 'registered'

    attendance = Attendance.objects.get(gym_class=gym_class, student=student)
    assert attendance.status == Attendance.Status.PRESENT
    assert attendance.source == Attendance.Source.QR

    assert AttendanceChangeLog.objects.count() == 1
    log = AttendanceChangeLog.objects.get()
    assert log.attendance_id == attendance.id
    assert log.previous_status == Attendance.Status.ABSENT
    assert log.new_status == Attendance.Status.PRESENT
    assert log.changed_by_id == student.id
    assert log.source == Attendance.Source.QR
    assert log.organization_id == gym_class.organization_id


# --------------------------------------------------------------------------------------
# 3. QR con registro previo YA present: 'already_registered', sin log, sin cambios
#    (el early-return existente, que nunca llega al bloque nuevo).
# --------------------------------------------------------------------------------------

def test_qr_on_already_present_record_is_a_noop_without_log(api_client, setup):
    gym_class = setup['gym_class']
    student = setup['student']
    original = _mark_attendance(gym_class, student, Attendance.Status.PRESENT, marked_by=setup['admin'])

    _login(api_client, student)
    resp = api_client.post(CHECKIN_URL, {'grant': _grant(setup)}, format='json')

    assert resp.status_code == 200, resp.content
    assert resp.json()['status'] == 'already_registered'

    attendance = Attendance.objects.get(gym_class=gym_class, student=student)
    assert attendance.status == Attendance.Status.PRESENT
    assert attendance.source == Attendance.Source.MANUAL, 'no-op: el registro previo no debe tocarse'
    assert attendance.marked_by_id == setup['admin'].id
    assert attendance.marked_at == original.marked_at
    assert AttendanceChangeLog.objects.count() == 0


# --------------------------------------------------------------------------------------
# 4. `attendance-history` (gym_admin de la org) incluye el log del QR con source='qr',
#    y los manuales (10.2) siguen saliendo source='manual'.
# --------------------------------------------------------------------------------------

def test_attendance_history_reports_qr_and_manual_sources(api_client, setup):
    gym_class = setup['gym_class']
    student = setup['student']
    admin = setup['admin']
    _mark_attendance(gym_class, student, Attendance.Status.ABSENT, marked_by=admin)

    _login(api_client, student)
    checkin_resp = api_client.post(CHECKIN_URL, {'grant': _grant(setup)}, format='json')
    assert checkin_resp.status_code == 200, checkin_resp.content

    # Ahora un admin corrige a mano (10.2): debe convivir con el log del QR y salir
    # etiquetado 'manual', sin pisar ni mezclar con el anterior.
    _login(api_client, admin)
    correction_resp = api_client.post(f'/api/classes/{gym_class.id}/attendance/', {
        'attendances': [
            {'student_id': student.id, 'status': 'absent'},
        ],
    }, format='json')
    assert correction_resp.status_code == 200, correction_resp.content

    assert AttendanceChangeLog.objects.count() == 2

    history_resp = api_client.get(f'/api/classes/{gym_class.id}/attendance-history/')
    assert history_resp.status_code == 200, history_resp.content
    data = history_resp.json()
    assert len(data) == 2

    sources = {item['source'] for item in data}
    assert sources == {'qr', 'manual'}

    qr_entry = next(item for item in data if item['source'] == 'qr')
    assert qr_entry['previous_status'] == 'absent'
    assert qr_entry['new_status'] == 'present'
    assert qr_entry['changed_by'] == student.id

    manual_entry = next(item for item in data if item['source'] == 'manual')
    assert manual_entry['previous_status'] == 'present'
    assert manual_entry['new_status'] == 'absent'
    assert manual_entry['changed_by'] == admin.id


# --------------------------------------------------------------------------------------
# 5. La pisada por QR NO toca consumo: sin ConsumptionLog, sin cambios en classes_used.
# --------------------------------------------------------------------------------------

def test_qr_overwrite_does_not_touch_consumption(api_client, setup):
    gym_class = setup['gym_class']
    student = setup['student']
    plan = Plan.objects.create(
        organization=setup['org'], name='Pack', plan_type='pack',
        total_classes=10, duration_days=30, price=30000,
    )
    student_plan = StudentPlan.objects.create(
        user=student, plan=plan, organization_id=plan.organization_id,
        start_date=TODAY - timedelta(days=1), end_date=TODAY + timedelta(days=30),
        total_classes=10, classes_used=3, final_price=plan.price,
    )
    _mark_attendance(gym_class, student, Attendance.Status.ABSENT, marked_by=setup['admin'])
    assert ConsumptionLog.objects.count() == 0

    _login(api_client, student)
    resp = api_client.post(CHECKIN_URL, {'grant': _grant(setup)}, format='json')
    assert resp.status_code == 200, resp.content

    student_plan.refresh_from_db()
    assert student_plan.classes_used == 3
    assert ConsumptionLog.objects.count() == 0
