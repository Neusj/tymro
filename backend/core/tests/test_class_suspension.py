"""Feature 4: estado SUSPENDED de una clase.

Endpoints suspend/reactivate (solo superadmin / org-admin / profesor dueño),
notificación por email a inscritos, y exclusión de las clases suspendidas del
listado del alumno.
"""
from datetime import time, timedelta

import pytest
from django.utils import timezone

from core.models import Branch, ClassTemplate, ConsumptionLog, Enrollment, GymClass, Plan, StudentPlan

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


def _student_plan(setup, student):
    plan = Plan.objects.create(
        organization=setup['org'], name=f'Pack {student.id}', plan_type='pack',
        total_classes=8, duration_days=30, price=20000,
    )
    return StudentPlan.objects.create(
        organization=setup['org'], user=student, plan=plan,
        start_date=timezone.localdate() - timedelta(days=1),
        end_date=timezone.localdate() + timedelta(days=30),
        total_classes=8, classes_used=0, final_price=plan.price,
    )


def _reserve_as_admin(api_client, setup, gym_class, student):
    api_client.force_authenticate(user=setup['admin'])
    response = api_client.post(
        '/api/enrollments/',
        {'gym_class': gym_class.id, 'student': student.id, 'status': 'active'},
        format='json',
    )
    assert response.status_code == 201, response.content
    return Enrollment.objects.get(pk=response.json()['id'])


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
    gym_class.suspended_at = timezone.now()
    gym_class.suspended_by = setup['admin']
    gym_class.suspend_reason = 'Mantencion'
    gym_class.save(update_fields=['suspended_at', 'suspended_by', 'suspend_reason'])
    _login(api_client, 'admin')
    resp = api_client.post(f'/api/classes/{gym_class.id}/reactivate/', {}, format='json')
    assert resp.status_code == 200, resp.content
    assert resp.json()['status'] == GymClass.Status.SCHEDULED

    gym_class.refresh_from_db()
    assert gym_class.suspended_at is not None
    assert gym_class.suspended_by_id == setup['admin'].id
    assert gym_class.reactivated_at is not None
    assert gym_class.reactivated_by_id == setup['admin'].id

    repeated = api_client.post(f'/api/classes/{gym_class.id}/reactivate/', {}, format='json')
    assert repeated.status_code == 400


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


def test_suspended_class_visible_to_student_but_not_reservable(api_client, setup):
    gym_class = _future_class(setup)
    Enrollment.objects.create(gym_class=gym_class, student=setup['student'], status='active')

    _login(api_client, 'admin')
    api_client.post(f'/api/classes/{gym_class.id}/suspend/', {}, format='json')

    _login(api_client, 'alu')
    data = api_client.get('/api/classes/').json()
    ids = {row['id'] for row in (data if isinstance(data, list) else data.get('results', []))}
    assert gym_class.id in ids
    row = next(row for row in data if row['id'] == gym_class.id)
    assert row['status'] == GymClass.Status.SUSPENDED

    reserve = api_client.post('/api/enrollments/', {'gym_class': gym_class.id}, format='json')
    assert reserve.status_code == 400, reserve.content


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


def test_suspended_class_rejects_attendance_and_early_completion(api_client, setup):
    gym_class = _future_class(setup, status=GymClass.Status.SUSPENDED)
    _login(api_client, 'admin')

    attendance = api_client.post(
        f'/api/classes/{gym_class.id}/attendance/', {'attendances': []}, format='json',
    )
    complete = api_client.post(
        f'/api/classes/{gym_class.id}/complete-early/', {'comment': 'Cierre'}, format='json',
    )

    assert attendance.status_code == 403
    assert complete.status_code == 400


@pytest.mark.parametrize('student_count', [1, 3])
def test_suspend_cancels_enrollments_and_refunds_each_credit_once(
    api_client, setup, make_user, student_count
):
    gym_class = _future_class(setup)
    students = [setup['student']]
    students.extend(
        make_user(f'alu-extra-{index}', organization=setup['org'], role='student')
        for index in range(1, student_count)
    )
    plans = []
    enrollments = []
    for student in students:
        plans.append(_student_plan(setup, student))
        enrollments.append(_reserve_as_admin(api_client, setup, gym_class, student))

    assert ConsumptionLog.objects.filter(class_instance=gym_class).count() == student_count
    assert all(StudentPlan.objects.get(pk=plan.pk).classes_used == 1 for plan in plans)

    response = api_client.post(f'/api/classes/{gym_class.id}/suspend/', {}, format='json')

    assert response.status_code == 200, response.content
    gym_class.refresh_from_db()
    assert gym_class.status == GymClass.Status.SUSPENDED
    assert gym_class.suspended_by_id == setup['admin'].id
    assert Enrollment.objects.filter(pk__in=[item.pk for item in enrollments]).count() == student_count
    assert not Enrollment.objects.filter(pk__in=[item.pk for item in enrollments], status='active').exists()
    assert not ConsumptionLog.objects.filter(class_instance=gym_class).exists()
    assert all(StudentPlan.objects.get(pk=plan.pk).classes_used == 0 for plan in plans)

    repeated = api_client.post(f'/api/classes/{gym_class.id}/suspend/', {}, format='json')
    assert repeated.status_code == 400
    assert all(StudentPlan.objects.get(pk=plan.pk).classes_used == 0 for plan in plans)


def test_reactivate_does_not_reenroll_or_consume_and_allows_new_reservation(api_client, setup):
    gym_class = _future_class(setup)
    student_plan = _student_plan(setup, setup['student'])
    enrollment = _reserve_as_admin(api_client, setup, gym_class, setup['student'])
    api_client.post(f'/api/classes/{gym_class.id}/suspend/', {}, format='json')

    response = api_client.post(f'/api/classes/{gym_class.id}/reactivate/', {}, format='json')

    assert response.status_code == 200, response.content
    enrollment.refresh_from_db()
    student_plan.refresh_from_db()
    assert enrollment.status == 'cancelled'
    assert student_plan.classes_used == 0
    assert not ConsumptionLog.objects.filter(class_instance=gym_class).exists()

    reserve = api_client.post(
        '/api/enrollments/',
        {'gym_class': gym_class.id, 'student': setup['student'].id, 'status': 'active'},
        format='json',
    )
    assert reserve.status_code == 201, reserve.content
    enrollment.refresh_from_db()
    student_plan.refresh_from_db()
    assert enrollment.status == 'active'
    assert student_plan.classes_used == 1


def test_projected_class_materializes_then_stays_suspended_without_virtual_duplicate(api_client, setup):
    target = timezone.localdate() + timedelta(days=2)
    template = ClassTemplate.objects.create(
        organization=setup['org'], branch=setup['branch'], teacher=setup['teacher'],
        name='Serie suspendible', weekday=target.weekday(), start_time=time(10, 0),
        end_time=time(11, 0), capacity=10, start_date=target - timedelta(days=7),
    )
    api_client.force_authenticate(user=setup['admin'])
    virtual_id = f'virtual:{template.id}:{target.isoformat()}'

    resolved = api_client.post('/api/classes/resolve-projection/', {'id': virtual_id}, format='json')
    assert resolved.status_code == 201, resolved.content
    gym_class_id = resolved.json()['gym_class']['id']
    suspended = api_client.post(f'/api/classes/{gym_class_id}/suspend/', {}, format='json')
    assert suspended.status_code == 200, suspended.content

    rows = api_client.get('/api/classes/by-date/', {'date': target.isoformat()}).json()
    matching = [row for row in rows if row.get('class_template') == template.id]
    assert len(matching) == 1
    assert matching[0]['id'] == gym_class_id
    assert matching[0]['status'] == GymClass.Status.SUSPENDED
