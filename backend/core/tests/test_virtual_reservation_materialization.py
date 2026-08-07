from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time, timedelta
from threading import Barrier

import pytest
from django.db import close_old_connections
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import Branch, ClassTemplate, Enrollment, GymClass, Plan, StudentPlan

pytestmark = pytest.mark.django_db

ENDPOINT = '/api/enrollments/'


def _target_date(days=3):
    return timezone.localdate() + timedelta(days=days)


@pytest.fixture
def world(make_organization, make_user):
    org = make_organization('Org Virtual')
    org.max_reservation_window_days = 7
    org.save(update_fields=['max_reservation_window_days'])
    teacher = make_user('teacher-virtual', organization=org, role='teacher')
    student = make_user('student-virtual', organization=org, role='student', email='student-virtual@gym.cl')
    branch = Branch.objects.create(organization=org, name='Sede')
    return {'org': org, 'teacher': teacher, 'student': student, 'branch': branch}


def _student_plan(org, student, *, total_classes=20, classes_used=0):
    plan = Plan.objects.create(
        organization=org,
        name=f'Pack {student.id}',
        plan_type='pack',
        total_classes=total_classes,
        duration_days=60,
        price=30000,
    )
    return StudentPlan.objects.create(
        user=student,
        plan=plan,
        organization_id=org.id,
        start_date=timezone.localdate() - timedelta(days=1),
        end_date=timezone.localdate() + timedelta(days=60),
        total_classes=total_classes,
        classes_used=classes_used,
        final_price=plan.price,
    )


def _template(world, target_date, *, is_active=True, capacity=10, start_time=time(10, 0)):
    return ClassTemplate.objects.create(
        organization=world['org'],
        branch=world['branch'],
        teacher=world['teacher'],
        name='Serie virtual',
        weekday=target_date.weekday(),
        start_time=start_time,
        end_time=time(start_time.hour + 1, start_time.minute),
        capacity=capacity,
        start_date=target_date - timedelta(days=7),
        is_active=is_active,
    )


def _materialized_class(world, target_date):
    start = timezone.make_aware(datetime.combine(target_date, time(10, 0)), timezone.get_current_timezone())
    return GymClass.objects.create(
        organization=world['org'],
        branch=world['branch'],
        teacher=world['teacher'],
        name='Clase real',
        start_datetime=start,
        end_datetime=start + timedelta(hours=1),
        capacity=10,
        status=GymClass.Status.SCHEDULED,
    )


def test_reservation_with_real_gym_class_still_uses_the_existing_contract(api_client, world):
    gym_class = _materialized_class(world, _target_date())
    membership = _student_plan(world['org'], world['student'])
    api_client.force_authenticate(user=world['student'])

    resp = api_client.post(ENDPOINT, {'gym_class': gym_class.id}, format='json')

    assert resp.status_code == 201, resp.content
    enrollment = Enrollment.objects.get(id=resp.json()['id'])
    assert enrollment.gym_class_id == gym_class.id
    assert enrollment.student_id == world['student'].id
    assert GymClass.objects.count() == 1
    membership.refresh_from_db()
    assert membership.classes_used == 1


def test_virtual_reservation_inside_window_materializes_and_reserves(api_client, world):
    target_date = _target_date()
    template = _template(world, target_date)
    membership = _student_plan(world['org'], world['student'])
    api_client.force_authenticate(user=world['student'])

    resp = api_client.post(
        ENDPOINT,
        {'class_template_id': template.id, 'date': target_date.isoformat()},
        format='json',
    )

    assert resp.status_code == 201, resp.content
    gym_class = GymClass.objects.get(class_template=template)
    enrollment = Enrollment.objects.get(id=resp.json()['id'])
    assert enrollment.gym_class_id == gym_class.id
    assert timezone.localtime(gym_class.start_datetime).date() == target_date
    assert gym_class.organization_id == world['org'].id
    membership.refresh_from_db()
    assert membership.classes_used == 1


def test_virtual_reservation_outside_window_rejects_without_orphan_class(api_client, world):
    world['org'].max_reservation_window_days = 2
    world['org'].save(update_fields=['max_reservation_window_days'])
    target_date = _target_date(3)
    template = _template(world, target_date)
    _student_plan(world['org'], world['student'])
    api_client.force_authenticate(user=world['student'])

    resp = api_client.post(
        ENDPOINT,
        {'class_template_id': template.id, 'date': target_date.isoformat()},
        format='json',
    )

    assert resp.status_code == 400, resp.content
    assert GymClass.objects.filter(class_template=template).count() == 0
    assert Enrollment.objects.count() == 0


def test_virtual_reservation_foreign_template_matches_missing_template(
    api_client, world, make_organization, make_user
):
    target_date = _target_date()
    other_org = make_organization('Org Ajena')
    other_teacher = make_user('teacher-foreign-template', organization=other_org, role='teacher')
    other_branch = Branch.objects.create(organization=other_org, name='Sede ajena')
    foreign_template = ClassTemplate.objects.create(
        organization=other_org,
        branch=other_branch,
        teacher=other_teacher,
        name='Serie ajena',
        weekday=target_date.weekday(),
        start_time=time(10, 0),
        end_time=time(11, 0),
        capacity=10,
        start_date=target_date - timedelta(days=7),
    )
    _student_plan(world['org'], world['student'])
    api_client.force_authenticate(user=world['student'])

    foreign = api_client.post(
        ENDPOINT,
        {'class_template_id': foreign_template.id, 'date': target_date.isoformat()},
        format='json',
    )
    missing = api_client.post(
        ENDPOINT,
        {'class_template_id': 999999999, 'date': target_date.isoformat()},
        format='json',
    )

    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()
    assert GymClass.objects.count() == 0
    assert Enrollment.objects.count() == 0


def test_virtual_reservation_inactive_template_rejects_without_materializing(api_client, world):
    target_date = _target_date()
    template = _template(world, target_date, is_active=False)
    _student_plan(world['org'], world['student'])
    api_client.force_authenticate(user=world['student'])

    resp = api_client.post(
        ENDPOINT,
        {'class_template_id': template.id, 'date': target_date.isoformat()},
        format='json',
    )

    assert resp.status_code == 400, resp.content
    assert GymClass.objects.filter(class_template=template).count() == 0
    assert Enrollment.objects.count() == 0


@pytest.mark.django_db(transaction=True)
def test_two_concurrent_virtual_reservations_share_one_materialized_class(world, make_user):
    target_date = _target_date()
    template = _template(world, target_date, capacity=2)
    student_a = world['student']
    student_b = make_user('student-virtual-b', organization=world['org'], role='student')
    _student_plan(world['org'], student_a)
    _student_plan(world['org'], student_b)
    barrier = Barrier(2)

    def post_reservation(student_id):
        close_old_connections()
        try:
            from django.contrib.auth import get_user_model

            student = get_user_model().objects.get(pk=student_id)
            client = APIClient()
            client.force_authenticate(user=student)
            barrier.wait(timeout=5)
            response = client.post(
                ENDPOINT,
                {'class_template_id': template.id, 'date': target_date.isoformat()},
                format='json',
            )
            return response.status_code, response.json()
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(post_reservation, [student_a.id, student_b.id]))

    assert [status_code for status_code, _body in results] == [201, 201]
    gym_classes = list(GymClass.objects.filter(class_template=template))
    assert len(gym_classes) == 1
    assert Enrollment.objects.filter(gym_class=gym_classes[0], status='active').count() == 2
