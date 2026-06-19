"""Visibilidad de asistencia:
- Un student NO puede leer el roster (enrolled-students) de una clase; recibe 403.
  gym_admin y teacher de la clase sí pueden.
- Un student ve su propio resultado de asistencia (attendance_status) en sus reservas.
"""
from datetime import timedelta

import pytest
from django.core import signing
from django.utils import timezone

from core import views
from core.models import Attendance, Branch, Enrollment, GymClass
from core.views import _build_checkin_grant, _build_qr_token

pytestmark = pytest.mark.django_db

PASSWORD = 'Passw0rd2026'

PREVIEW_URL = '/api/attendance-qr/preview/'
CHECKIN_URL = '/api/attendance-qr/check-in/'


def _login(api_client, username):
    from django.contrib.auth import get_user_model
    user = get_user_model().objects.get(username=username)
    host = {'HTTP_HOST': f'{user.organization.subdomain}.localhost'} if user.organization_id else {}
    token = api_client.post(
        '/api/login/', {'email': user.email, 'password': PASSWORD}, format='json', **host
    ).json()['token']
    api_client.credentials(HTTP_AUTHORIZATION=f'Token {token}')


@pytest.fixture
def gym_setup(make_organization, make_user):
    org = make_organization()
    admin = make_user('admin', organization=org, role='gym_admin')
    teacher = make_user('teacher', organization=org, role='teacher')
    student = make_user('student', organization=org, role='student')
    other_student = make_user('other', organization=org, role='student')
    branch = Branch.objects.create(organization=org, name='Sede')
    start = timezone.now() + timedelta(days=1)
    gym_class = GymClass.objects.create(
        organization=org,
        branch=branch,
        teacher=teacher,
        name='Clase',
        start_datetime=start,
        end_datetime=start + timedelta(hours=1),
    )
    Enrollment.objects.create(gym_class=gym_class, student=student, status='active')
    Enrollment.objects.create(gym_class=gym_class, student=other_student, status='active')
    return {
        'org': org,
        'admin': admin,
        'teacher': teacher,
        'student': student,
        'gym_class': gym_class,
    }


def test_student_cannot_read_enrolled_roster(api_client, gym_setup):
    gym_class = gym_setup['gym_class']

    _login(api_client, 'student')
    resp = api_client.get(f'/api/classes/{gym_class.id}/enrolled-students/')
    assert resp.status_code == 403


def test_gym_admin_and_teacher_can_read_enrolled_roster(api_client, gym_setup):
    gym_class = gym_setup['gym_class']

    _login(api_client, 'admin')
    assert api_client.get(f'/api/classes/{gym_class.id}/enrolled-students/').status_code == 200

    _login(api_client, 'teacher')
    assert api_client.get(f'/api/classes/{gym_class.id}/enrolled-students/').status_code == 200


def test_student_sees_own_attendance_status_in_reservations(api_client, gym_setup):
    student = gym_setup['student']
    gym_class = gym_setup['gym_class']
    now = timezone.now()
    Attendance.objects.create(
        gym_class=gym_class,
        student=student,
        status=Attendance.Status.PRESENT,
        source=Attendance.Source.QR,
        marked_at=now,
        checked_at=now,
    )

    _login(api_client, 'student')
    resp = api_client.get('/api/enrollments/my/')
    assert resp.status_code == 200

    payload = resp.json()
    items = payload['results'] if isinstance(payload, dict) and 'results' in payload else payload
    mine = [item for item in items if item['gym_class'] == gym_class.id]
    assert mine, 'El alumno deberia ver su reserva de la clase.'
    assert mine[0]['attendance_status'] == 'present'


# --- Check-in por QR: preview valida una vez, grant confirma ------------------


@pytest.fixture
def qr_setup(make_organization, make_user):
    """Clase EN VENTANA (empezó hace 2 min) con el alumno inscrito: el preview
    debe devolver status 'ready' + grant."""
    org = make_organization()
    student = make_user('student', organization=org, role='student')
    branch = Branch.objects.create(organization=org, name='Sede')
    start = timezone.now() - timedelta(minutes=2)
    gym_class = GymClass.objects.create(
        organization=org,
        branch=branch,
        name='Clase en curso',
        start_datetime=start,
        end_datetime=start + timedelta(hours=1),
    )
    Enrollment.objects.create(gym_class=gym_class, student=student, status='active')
    return {'org': org, 'student': student, 'gym_class': gym_class}


def test_preview_emits_grant_and_mark_works_even_if_qr_token_expired(api_client, qr_setup):
    org = qr_setup['org']
    gym_class = qr_setup['gym_class']
    _login(api_client, 'student')

    qr_token, _ = _build_qr_token(org.id)
    preview = api_client.get(PREVIEW_URL, {'token': qr_token})
    assert preview.status_code == 200
    body = preview.json()
    assert body['status'] == 'ready'
    grant = body.get('checkin_grant')
    assert grant, 'El preview debe emitir un checkin_grant cuando se puede marcar.'

    # El token del QR ya no interviene al confirmar: marcamos SOLO con el grant.
    # (Simula el desfase: aunque el QR de 20s ya hubiera rotado, el grant sigue válido.)
    resp = api_client.post(CHECKIN_URL, {'grant': grant}, format='json')
    assert resp.status_code == 200
    assert resp.json()['status'] == 'registered'
    attendance = Attendance.objects.get(gym_class=gym_class, student=qr_setup['student'])
    assert attendance.status == Attendance.Status.PRESENT
    assert attendance.source == Attendance.Source.QR


def test_mark_rejects_grant_of_another_student(api_client, qr_setup, make_user):
    org = qr_setup['org']
    gym_class = qr_setup['gym_class']
    intruder = make_user('intruder', organization=org, role='student')

    # Grant emitido para OTRO alumno (el intruso), pero confirma el alumno legítimo.
    foreign_grant = _build_checkin_grant(intruder.id, gym_class.id, org.id)

    _login(api_client, 'student')
    resp = api_client.post(CHECKIN_URL, {'grant': foreign_grant}, format='json')
    assert resp.status_code == 403
    assert not Attendance.objects.filter(gym_class=gym_class, student=qr_setup['student']).exists()


def test_mark_rejects_grant_for_other_organization(api_client, qr_setup, make_organization):
    gym_class = qr_setup['gym_class']
    other_org = make_organization()

    # Grant del mismo alumno pero apuntando a otra organización/clase.
    cross_grant = _build_checkin_grant(qr_setup['student'].id, gym_class.id, other_org.id)

    _login(api_client, 'student')
    resp = api_client.post(CHECKIN_URL, {'grant': cross_grant}, format='json')
    assert resp.status_code == 400
    assert not Attendance.objects.filter(gym_class=gym_class, student=qr_setup['student']).exists()


def test_mark_rejects_expired_grant(api_client, qr_setup, monkeypatch):
    org = qr_setup['org']
    gym_class = qr_setup['gym_class']
    grant = _build_checkin_grant(qr_setup['student'].id, gym_class.id, org.id)

    # TTL negativo => cualquier grant se considera caducado al validarlo.
    monkeypatch.setattr(views, 'QR_CHECKIN_GRANT_TTL_SECONDS', -1)

    _login(api_client, 'student')
    resp = api_client.post(CHECKIN_URL, {'grant': grant}, format='json')
    assert resp.status_code == 400
    assert not Attendance.objects.filter(gym_class=gym_class, student=qr_setup['student']).exists()


def test_double_mark_is_blocked(api_client, qr_setup):
    org = qr_setup['org']
    gym_class = qr_setup['gym_class']
    grant = _build_checkin_grant(qr_setup['student'].id, gym_class.id, org.id)

    _login(api_client, 'student')
    first = api_client.post(CHECKIN_URL, {'grant': grant}, format='json')
    assert first.status_code == 200
    assert first.json()['status'] == 'registered'

    # Reusar el grant (aún vigente) no crea una segunda asistencia.
    second = api_client.post(CHECKIN_URL, {'grant': grant}, format='json')
    assert second.status_code == 200
    assert second.json()['status'] == 'already_registered'
    assert Attendance.objects.filter(gym_class=gym_class, student=qr_setup['student']).count() == 1


# --- Ventana de aceptación del token del QR (~60s) ----------------------------


def _qr_token_with_age(org_id, age_seconds):
    """Reconstruye un token del QR como si se hubiera emitido hace `age_seconds`,
    usando la ventana de aceptación REAL del backend. Permite probar el borde de 60s
    sin esperar en tiempo real."""
    issued = timezone.now() - timedelta(seconds=age_seconds)
    expires = issued + timedelta(seconds=views.QR_TOKEN_ACCEPTANCE_SECONDS)
    payload = {
        'organization_id': org_id,
        'issued_at': issued.isoformat(),
        'expires_at': expires.isoformat(),
        'nonce': 'test-nonce',
    }
    return signing.dumps(payload, salt=views.QR_ATTENDANCE_SALT)


def test_qr_token_near_rotation_still_accepted(api_client, qr_setup):
    # Escaneado ~50s atrás (justo antes de rotar): aún dentro de los 60s de aceptación.
    token = _qr_token_with_age(qr_setup['org'].id, age_seconds=50)
    _login(api_client, 'student')
    resp = api_client.get(PREVIEW_URL, {'token': token})
    assert resp.status_code == 200
    body = resp.json()
    assert body['status'] == 'ready'
    assert body.get('checkin_grant')


def test_qr_token_beyond_acceptance_is_rejected(api_client, qr_setup):
    # Más de 60s de vida: el backend lo rechaza -> el front muestra el rescan hint.
    token = _qr_token_with_age(qr_setup['org'].id, age_seconds=65)
    _login(api_client, 'student')
    resp = api_client.get(PREVIEW_URL, {'token': token})
    assert resp.status_code == 400
    assert 'token' in resp.json()
