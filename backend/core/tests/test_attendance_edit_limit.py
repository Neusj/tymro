from datetime import timedelta
from unittest import mock

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


@pytest.fixture
def setup(make_organization, make_user):
    org = make_organization()
    admin = make_user('admin-att-limit', organization=org, role='gym_admin')
    teacher = make_user('teacher-att-limit', organization=org, role='teacher')
    student = make_user('student-att-limit', organization=org, role='student')
    other_student = make_user('other-att-limit', organization=org, role='student')
    branch = Branch.objects.create(organization=org, name='Sede')
    start = timezone.now() - timedelta(hours=2)
    gym_class = GymClass.objects.create(
        organization=org,
        branch=branch,
        teacher=teacher,
        name='Clase',
        start_datetime=start,
        end_datetime=start + timedelta(hours=1),
        capacity=10,
        status=GymClass.Status.COMPLETED,
        is_active=False,
        closed_at=start + timedelta(hours=1),
    )
    Enrollment.objects.create(gym_class=gym_class, student=student, status='active')
    Enrollment.objects.create(gym_class=gym_class, student=other_student, status='active')
    Attendance.objects.create(
        gym_class=gym_class,
        student=student,
        status=Attendance.Status.PRESENT,
        source=Attendance.Source.MANUAL,
        marked_by=admin,
        marked_at=start,
        checked_at=start,
    )
    Attendance.objects.create(
        gym_class=gym_class,
        student=other_student,
        status=Attendance.Status.PRESENT,
        source=Attendance.Source.MANUAL,
        marked_by=admin,
        marked_at=start,
        checked_at=start,
    )
    return {
        'org': org,
        'admin': admin,
        'teacher': teacher,
        'student': student,
        'other_student': other_student,
        'gym_class': gym_class,
    }


def _correction_payload(setup):
    return {
        'attendances': [
            {'student_id': setup['student'].id, 'status': 'absent'},
            {'student_id': setup['other_student'].id, 'status': 'present'},
        ],
    }


def _post_at(api_client, gym_class, payload, at):
    with mock.patch('core.views.timezone.now', return_value=at):
        return api_client.post(_attendance_url(gym_class), payload, format='json')


def test_teacher_can_edit_before_default_limit(api_client, setup):
    gym_class = setup['gym_class']
    _login(api_client, setup['teacher'])

    resp = _post_at(
        api_client,
        gym_class,
        _correction_payload(setup),
        gym_class.end_datetime + timedelta(minutes=29),
    )

    assert resp.status_code == 200, resp.content
    assert Attendance.objects.get(gym_class=gym_class, student=setup['student']).status == Attendance.Status.ABSENT


def test_teacher_can_edit_exactly_at_default_limit(api_client, setup):
    gym_class = setup['gym_class']
    _login(api_client, setup['teacher'])

    resp = _post_at(
        api_client,
        gym_class,
        _correction_payload(setup),
        gym_class.end_datetime + timedelta(minutes=30),
    )

    assert resp.status_code == 200, resp.content
    assert AttendanceChangeLog.objects.count() == 1


def test_teacher_cannot_edit_after_default_limit(api_client, setup):
    gym_class = setup['gym_class']
    _login(api_client, setup['teacher'])

    resp = _post_at(
        api_client,
        gym_class,
        _correction_payload(setup),
        gym_class.end_datetime + timedelta(minutes=30, seconds=1),
    )

    assert resp.status_code == 403, resp.content
    assert '30 minutos' in resp.json()['detail']
    assert Attendance.objects.get(gym_class=gym_class, student=setup['student']).status == Attendance.Status.PRESENT
    assert AttendanceChangeLog.objects.count() == 0


def test_teacher_limit_uses_organization_configuration(api_client, setup):
    org = setup['org']
    org.teacher_attendance_edit_limit_minutes = 15
    org.save(update_fields=['teacher_attendance_edit_limit_minutes'])
    gym_class = setup['gym_class']
    _login(api_client, setup['teacher'])

    allowed = _post_at(
        api_client,
        gym_class,
        _correction_payload(setup),
        gym_class.end_datetime + timedelta(minutes=15),
    )
    assert allowed.status_code == 200, allowed.content

    Attendance.objects.filter(gym_class=gym_class, student=setup['student']).update(status=Attendance.Status.PRESENT)
    AttendanceChangeLog.objects.all().delete()

    blocked = _post_at(
        api_client,
        gym_class,
        _correction_payload(setup),
        gym_class.end_datetime + timedelta(minutes=15, seconds=1),
    )
    assert blocked.status_code == 403, blocked.content
    assert '15 minutos' in blocked.json()['detail']
    assert Attendance.objects.get(gym_class=gym_class, student=setup['student']).status == Attendance.Status.PRESENT


def test_admin_can_edit_after_limit(api_client, setup):
    gym_class = setup['gym_class']
    ended_at = timezone.now() - timedelta(days=2)
    gym_class.start_datetime = ended_at - timedelta(hours=1)
    gym_class.end_datetime = ended_at
    gym_class.closed_at = ended_at
    gym_class.save(update_fields=['start_datetime', 'end_datetime', 'closed_at', 'updated_at'])
    _login(api_client, setup['admin'])

    resp = api_client.post(_attendance_url(gym_class), _correction_payload(setup), format='json')

    assert resp.status_code == 200, resp.content
    assert Attendance.objects.get(gym_class=gym_class, student=setup['student']).status == Attendance.Status.ABSENT


def test_attendance_edit_config_endpoint(api_client, setup):
    _login(api_client, setup['admin'])
    url = f'/api/organizations/{setup["org"].id}/attendance-edit-config/'

    get_resp = api_client.get(url)
    assert get_resp.status_code == 200, get_resp.content
    assert get_resp.json()['teacher_attendance_edit_limit_minutes'] == 30
    assert get_resp.json()['teacher_enrollment_edit_limit_minutes'] == 30

    put_resp = api_client.put(
        url,
        {
            'teacher_attendance_edit_limit_minutes': 10,
            'teacher_enrollment_edit_limit_minutes': 20,
        },
        format='json',
    )
    assert put_resp.status_code == 200, put_resp.content
    assert put_resp.json()['teacher_attendance_edit_limit_minutes'] == 10
    assert put_resp.json()['teacher_enrollment_edit_limit_minutes'] == 20
    setup['org'].refresh_from_db()
    assert setup['org'].teacher_attendance_edit_limit_minutes == 10
    assert setup['org'].teacher_enrollment_edit_limit_minutes == 20
