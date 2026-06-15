"""Feature 4: estado SUSPENDED de una clase.

Endpoints suspend/reactivate (solo superadmin / org-admin / profesor dueño),
notificación por email a inscritos, y exclusión de las clases suspendidas del
listado del alumno.
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from core.models import Branch, Enrollment, GymClass

pytestmark = pytest.mark.django_db

PASSWORD = 'Passw0rd2026'


def _login(api_client, username):
    token = api_client.post(
        '/api/login/', {'username': username, 'password': PASSWORD}, format='json'
    ).json()['token']
    api_client.credentials(HTTP_AUTHORIZATION=f'Token {token}')


@pytest.fixture
def setup(make_organization, make_user):
    org = make_organization()
    admin = make_user('admin', organization=org, role='gym_admin')
    teacher = make_user('teach', organization=org, role='teacher')
    student = make_user('alu', organization=org, role='student', email='alu@gym.cl')
    branch = Branch.objects.create(organization=org, name='Sede')
    return {'org': org, 'admin': admin, 'teacher': teacher, 'student': student, 'branch': branch}


def _future_class(setup, status=GymClass.Status.SCHEDULED):
    start = timezone.now() + timedelta(days=1)
    return GymClass.objects.create(
        organization=setup['org'], branch=setup['branch'], teacher=setup['teacher'],
        name='Clase', start_datetime=start, end_datetime=start + timedelta(hours=1),
        capacity=10, status=status,
    )


def test_suspend_class(api_client, setup):
    gym_class = _future_class(setup)
    _login(api_client, 'admin')
    resp = api_client.post(
        f'/api/classes/{gym_class.id}/suspend/',
        {'suspend_reason': 'Profesor enfermo', 'reactivation_expected_date': '2026-07-01'},
        format='json',
    )
    assert resp.status_code == 200, resp.content
    assert resp.json()['status'] == GymClass.Status.SUSPENDED
    assert resp.json()['is_suspended'] is True

    gym_class.refresh_from_db()
    assert gym_class.status == GymClass.Status.SUSPENDED
    assert gym_class.suspended_by_id == setup['admin'].id
    assert gym_class.suspend_reason == 'Profesor enfermo'


def test_reactivate_class(api_client, setup):
    gym_class = _future_class(setup, status=GymClass.Status.SUSPENDED)
    _login(api_client, 'admin')
    resp = api_client.post(f'/api/classes/{gym_class.id}/reactivate/', {}, format='json')
    assert resp.status_code == 200, resp.content
    assert resp.json()['status'] == GymClass.Status.SCHEDULED

    gym_class.refresh_from_db()
    assert gym_class.suspended_at is None
    assert gym_class.suspended_by_id is None


def test_student_cannot_suspend(api_client, setup):
    gym_class = _future_class(setup)
    _login(api_client, 'alu')
    resp = api_client.post(f'/api/classes/{gym_class.id}/suspend/', {}, format='json')
    assert resp.status_code == 403


def test_other_org_admin_cannot_suspend(api_client, setup, make_organization, make_user):
    other_org = make_organization()
    make_user('admin2', organization=other_org, role='gym_admin')
    gym_class = _future_class(setup)
    _login(api_client, 'admin2')
    resp = api_client.post(f'/api/classes/{gym_class.id}/suspend/', {}, format='json')
    assert resp.status_code == 404  # ni siquiera ve la clase de otra organización


def test_suspended_class_hidden_from_student_my_list(api_client, setup):
    gym_class = _future_class(setup)
    Enrollment.objects.create(gym_class=gym_class, student=setup['student'], status='active')

    _login(api_client, 'admin')
    api_client.post(f'/api/classes/{gym_class.id}/suspend/', {}, format='json')

    _login(api_client, 'alu')
    data = api_client.get('/api/classes/', {'mine': '1'}).json()
    ids = {row['id'] for row in (data if isinstance(data, list) else data.get('results', []))}
    assert gym_class.id not in ids


def test_suspend_notifies_enrolled_students(api_client, setup, mailoutbox):
    gym_class = _future_class(setup)
    Enrollment.objects.create(gym_class=gym_class, student=setup['student'], status='active')

    _login(api_client, 'admin')
    resp = api_client.post(
        f'/api/classes/{gym_class.id}/suspend/', {'suspend_reason': 'Mantención'}, format='json',
    )
    assert resp.status_code == 200
    recipients = [r for m in mailoutbox for r in m.to]
    assert setup['student'].email in recipients


def test_cannot_suspend_completed_class(api_client, setup):
    start = timezone.now() - timedelta(hours=2)
    gym_class = GymClass.objects.create(
        organization=setup['org'], branch=setup['branch'], teacher=setup['teacher'],
        name='Clase', start_datetime=start, end_datetime=start + timedelta(hours=1),
        capacity=10, status=GymClass.Status.COMPLETED,
    )
    _login(api_client, 'admin')
    resp = api_client.post(f'/api/classes/{gym_class.id}/suspend/', {}, format='json')
    assert resp.status_code == 400


def test_cannot_reactivate_non_suspended(api_client, setup):
    gym_class = _future_class(setup)
    _login(api_client, 'admin')
    resp = api_client.post(f'/api/classes/{gym_class.id}/reactivate/', {}, format='json')
    assert resp.status_code == 400
