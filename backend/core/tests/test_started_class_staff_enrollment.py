from datetime import timedelta

import pytest
from django.utils import timezone

from core.models import Branch, Enrollment, GymClass, Plan, StudentPlan

pytestmark = pytest.mark.django_db

ENROLLMENTS_URL = '/api/enrollments/'


@pytest.fixture
def world(make_organization, make_user):
    org = make_organization('Org Started Enrollment')
    teacher = make_user('started-teacher', organization=org, role='teacher')
    admin = make_user('started-admin', organization=org, role='gym_admin')
    student = make_user(
        'started-student',
        organization=org,
        role='student',
        email='started-student@gym.cl',
    )
    branch = Branch.objects.create(organization=org, name='Sede')
    return {'org': org, 'teacher': teacher, 'admin': admin, 'student': student, 'branch': branch}


def _student_plan(world):
    plan = Plan.objects.create(
        organization=world['org'],
        name='Pack en curso',
        plan_type='pack',
        total_classes=10,
        duration_days=30,
        price=30000,
    )
    return StudentPlan.objects.create(
        user=world['student'],
        plan=plan,
        organization_id=world['org'].id,
        start_date=timezone.localdate() - timedelta(days=1),
        end_date=timezone.localdate() + timedelta(days=30),
        total_classes=10,
        classes_used=0,
        final_price=plan.price,
    )


def _started_class(world):
    start = timezone.now() - timedelta(minutes=10)
    return GymClass.objects.create(
        organization=world['org'],
        branch=world['branch'],
        teacher=world['teacher'],
        name='Clase en curso',
        start_datetime=start,
        end_datetime=start + timedelta(hours=1),
        capacity=10,
        status=GymClass.Status.IN_PROGRESS,
    )


def _ended_class(world, *, status=GymClass.Status.SCHEDULED):
    start = timezone.now() - timedelta(hours=2)
    return GymClass.objects.create(
        organization=world['org'],
        branch=world['branch'],
        teacher=world['teacher'],
        name='Clase terminada',
        start_datetime=start,
        end_datetime=start + timedelta(hours=1),
        capacity=10,
        status=status,
    )


def _recently_ended_class(world, *, minutes_since_end, status=GymClass.Status.COMPLETED):
    end = timezone.now() - timedelta(minutes=minutes_since_end)
    return GymClass.objects.create(
        organization=world['org'],
        branch=world['branch'],
        teacher=world['teacher'],
        name='Clase terminada reciente',
        start_datetime=end - timedelta(hours=1),
        end_datetime=end,
        capacity=10,
        status=status,
    )


def test_teacher_can_enroll_student_after_class_started(api_client, world):
    membership = _student_plan(world)
    gym_class = _started_class(world)
    api_client.force_authenticate(user=world['teacher'])

    resp = api_client.post(
        ENROLLMENTS_URL,
        {'gym_class': gym_class.id, 'student': world['student'].id, 'status': 'active'},
        format='json',
    )

    assert resp.status_code == 201, resp.content
    assert Enrollment.objects.filter(gym_class=gym_class, student=world['student'], status='active').exists()
    membership.refresh_from_db()
    assert membership.classes_used == 1


def test_gym_admin_can_enroll_student_after_class_started(api_client, world):
    membership = _student_plan(world)
    gym_class = _started_class(world)
    api_client.force_authenticate(user=world['admin'])

    resp = api_client.post(
        ENROLLMENTS_URL,
        {'gym_class': gym_class.id, 'student': world['student'].id, 'status': 'active'},
        format='json',
    )

    assert resp.status_code == 201, resp.content
    assert Enrollment.objects.filter(gym_class=gym_class, student=world['student'], status='active').exists()
    membership.refresh_from_db()
    assert membership.classes_used == 1


def test_student_still_cannot_reserve_after_class_started(api_client, world):
    _student_plan(world)
    gym_class = _started_class(world)
    api_client.force_authenticate(user=world['student'])

    resp = api_client.post(
        ENROLLMENTS_URL,
        {'gym_class': gym_class.id, 'status': 'active'},
        format='json',
    )

    assert resp.status_code == 400
    assert resp.json()['gym_class'] == ['No puedes reservar clases pasadas o ya iniciadas.']
    assert Enrollment.objects.count() == 0


def test_gym_admin_can_enroll_student_after_class_ended(api_client, world):
    membership = _student_plan(world)
    gym_class = _ended_class(world, status=GymClass.Status.COMPLETED)
    api_client.force_authenticate(user=world['admin'])

    resp = api_client.post(
        ENROLLMENTS_URL,
        {'gym_class': gym_class.id, 'student': world['student'].id, 'status': 'active'},
        format='json',
    )

    assert resp.status_code == 201, resp.content
    assert Enrollment.objects.filter(gym_class=gym_class, student=world['student'], status='active').exists()
    membership.refresh_from_db()
    assert membership.classes_used == 1


def test_teacher_can_enroll_student_until_configured_minutes_after_class_ended(api_client, world):
    membership = _student_plan(world)
    gym_class = _recently_ended_class(world, minutes_since_end=29, status=GymClass.Status.COMPLETED)
    api_client.force_authenticate(user=world['teacher'])

    resp = api_client.post(
        ENROLLMENTS_URL,
        {'gym_class': gym_class.id, 'student': world['student'].id, 'status': 'active'},
        format='json',
    )

    assert resp.status_code == 201, resp.content
    assert Enrollment.objects.filter(gym_class=gym_class, student=world['student'], status='active').exists()
    membership.refresh_from_db()
    assert membership.classes_used == 1


def test_teacher_cannot_enroll_student_after_configured_minutes(api_client, world):
    _student_plan(world)
    gym_class = _recently_ended_class(world, minutes_since_end=31, status=GymClass.Status.COMPLETED)
    api_client.force_authenticate(user=world['teacher'])

    resp = api_client.post(
        ENROLLMENTS_URL,
        {'gym_class': gym_class.id, 'student': world['student'].id, 'status': 'active'},
        format='json',
    )

    assert resp.status_code == 400
    assert resp.json()['gym_class'] == ['No puedes reservar una clase cerrada.']
    assert Enrollment.objects.count() == 0


def test_teacher_enrollment_after_class_end_uses_organization_configuration(api_client, world):
    world['org'].teacher_enrollment_edit_limit_minutes = 10
    world['org'].save(update_fields=['teacher_enrollment_edit_limit_minutes'])
    _student_plan(world)
    gym_class = _recently_ended_class(world, minutes_since_end=11, status=GymClass.Status.COMPLETED)
    api_client.force_authenticate(user=world['teacher'])

    resp = api_client.post(
        ENROLLMENTS_URL,
        {'gym_class': gym_class.id, 'student': world['student'].id, 'status': 'active'},
        format='json',
    )

    assert resp.status_code == 400
    assert resp.json()['gym_class'] == ['No puedes reservar una clase cerrada.']
    assert Enrollment.objects.count() == 0


def test_teacher_can_unenroll_student_after_class_started(api_client, world):
    gym_class = _started_class(world)
    enrollment = Enrollment.objects.create(
        gym_class=gym_class,
        student=world['student'],
        status='active',
    )
    api_client.force_authenticate(user=world['teacher'])

    resp = api_client.post(f'{ENROLLMENTS_URL}{enrollment.id}/cancel/')

    assert resp.status_code == 200, resp.content
    enrollment.refresh_from_db()
    assert enrollment.status == 'cancelled'


def test_teacher_cannot_unenroll_student_after_class_ended(api_client, world):
    gym_class = _ended_class(world)
    enrollment = Enrollment.objects.create(
        gym_class=gym_class,
        student=world['student'],
        status='active',
    )
    api_client.force_authenticate(user=world['teacher'])

    resp = api_client.post(f'{ENROLLMENTS_URL}{enrollment.id}/cancel/')

    assert resp.status_code == 400
    assert resp.json()['detail'] == 'La clase ya termino y no admite cambios.'
    enrollment.refresh_from_db()
    assert enrollment.status == 'active'
