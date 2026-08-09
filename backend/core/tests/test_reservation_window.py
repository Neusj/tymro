from datetime import datetime, time, timedelta

import pytest
from django.utils import timezone

from core.models import Branch, ClassTemplate, Enrollment, GymClass, Plan, StudentPlan
from core.services.reservations import REASON_MAX_RESERVATION_WINDOW_EXCEEDED

pytestmark = pytest.mark.django_db

ENROLLMENTS_URL = '/api/enrollments/'


def _target_date(days):
    return timezone.localdate() + timedelta(days=days)


@pytest.fixture
def world(make_organization, make_user):
    org = make_organization('Org Reservation Window')
    org.max_reservation_window_days = 7
    org.save(update_fields=['max_reservation_window_days'])
    teacher = make_user('teacher-res-window', organization=org, role='teacher')
    student = make_user('student-res-window', organization=org, role='student')
    admin = make_user('admin-res-window', organization=org, role='gym_admin')
    branch = Branch.objects.create(organization=org, name='Sede')
    return {'org': org, 'teacher': teacher, 'student': student, 'admin': admin, 'branch': branch}


def _student_plan(world):
    plan = Plan.objects.create(
        organization=world['org'],
        name='Pack reservas',
        plan_type='pack',
        total_classes=20,
        duration_days=90,
        price=30000,
    )
    return StudentPlan.objects.create(
        user=world['student'],
        plan=plan,
        organization_id=world['org'].id,
        start_date=timezone.localdate() - timedelta(days=1),
        end_date=timezone.localdate() + timedelta(days=90),
        total_classes=20,
        classes_used=0,
        final_price=plan.price,
    )


def _gym_class(world, days):
    target_date = _target_date(days)
    start = timezone.make_aware(
        datetime.combine(target_date, time(10, 0)),
        timezone.get_current_timezone(),
    )
    return GymClass.objects.create(
        organization=world['org'],
        branch=world['branch'],
        teacher=world['teacher'],
        name=f'Clase +{days}',
        start_datetime=start,
        end_datetime=start + timedelta(hours=1),
        capacity=10,
        status=GymClass.Status.SCHEDULED,
    )


def _template(world, days):
    target_date = _target_date(days)
    return ClassTemplate.objects.create(
        organization=world['org'],
        branch=world['branch'],
        teacher=world['teacher'],
        name='Serie ventana',
        weekday=target_date.weekday(),
        start_time=time(10, 0),
        end_time=time(11, 0),
        capacity=10,
        start_date=target_date - timedelta(days=7),
        is_active=True,
    )


def _reserve(api_client, student, gym_class):
    api_client.force_authenticate(user=student)
    return api_client.post(ENROLLMENTS_URL, {'gym_class': gym_class.id}, format='json')


def test_reservation_inside_window_is_allowed(api_client, world):
    membership = _student_plan(world)
    gym_class = _gym_class(world, 6)

    resp = _reserve(api_client, world['student'], gym_class)

    assert resp.status_code == 201, resp.content
    membership.refresh_from_db()
    assert membership.classes_used == 1


def test_reservation_exactly_at_max_window_is_allowed(api_client, world):
    membership = _student_plan(world)
    gym_class = _gym_class(world, 7)

    resp = _reserve(api_client, world['student'], gym_class)

    assert resp.status_code == 201, resp.content
    membership.refresh_from_db()
    assert membership.classes_used == 1


def test_reservation_one_day_outside_window_is_rejected_with_configured_limit(api_client, world):
    _student_plan(world)
    gym_class = _gym_class(world, 8)

    resp = _reserve(api_client, world['student'], gym_class)

    assert resp.status_code == 400
    body = resp.json()
    assert body['code'] == REASON_MAX_RESERVATION_WINDOW_EXCEEDED
    assert int(body['max_reservation_window_days']) == 7
    assert body['detail'] == 'No puedes reservar con más de 7 días de anticipación.'
    assert Enrollment.objects.count() == 0


def test_virtual_class_outside_window_is_listed_as_not_reservable(api_client, world):
    target_date = _target_date(8)
    _template(world, 8)
    api_client.force_authenticate(user=world['student'])

    resp = api_client.get('/api/classes/by-date/', {'date': target_date.isoformat()})

    assert resp.status_code == 200
    row = resp.json()[0]
    assert row['reservable'] is False
    assert row['reservation_block_code'] == REASON_MAX_RESERVATION_WINDOW_EXCEEDED
    assert row['max_reservation_window_days'] == 7
    assert row['reservation_block_message'] == 'No puedes reservar con más de 7 días de anticipación.'


def test_existing_gym_class_outside_window_is_listed_as_not_reservable(api_client, world):
    target_date = _target_date(8)
    _gym_class(world, 8)
    api_client.force_authenticate(user=world['student'])

    resp = api_client.get('/api/classes/by-date/', {'date': target_date.isoformat()})

    assert resp.status_code == 200
    row = resp.json()[0]
    assert row['reservable'] is False
    assert row['reservation_block_code'] == REASON_MAX_RESERVATION_WINDOW_EXCEEDED
    assert row['max_reservation_window_days'] == 7


def test_virtual_reservation_outside_window_rejects_without_materializing(api_client, world):
    target_date = _target_date(8)
    template = _template(world, 8)
    _student_plan(world)
    api_client.force_authenticate(user=world['student'])

    resp = api_client.post(
        ENROLLMENTS_URL,
        {'class_template_id': template.id, 'date': target_date.isoformat()},
        format='json',
    )

    assert resp.status_code == 400
    assert resp.json()['code'] == REASON_MAX_RESERVATION_WINDOW_EXCEEDED
    assert GymClass.objects.filter(class_template=template).count() == 0
    assert Enrollment.objects.count() == 0


def test_direct_enrollment_endpoint_cannot_bypass_window_with_materialized_class(api_client, world):
    _student_plan(world)
    gym_class = _gym_class(world, 8)
    api_client.force_authenticate(user=world['student'])

    resp = api_client.post(ENROLLMENTS_URL, {'gym_class': gym_class.id, 'status': 'active'}, format='json')

    assert resp.status_code == 400
    assert resp.json()['code'] == REASON_MAX_RESERVATION_WINDOW_EXCEEDED
    assert Enrollment.objects.count() == 0


def test_cancelled_enrollment_cannot_be_reactivated_to_bypass_window(api_client, world):
    _student_plan(world)
    gym_class = _gym_class(world, 8)
    api_client.force_authenticate(user=world['admin'])
    created = api_client.post(
        ENROLLMENTS_URL,
        {'gym_class': gym_class.id, 'student': world['student'].id, 'status': 'cancelled'},
        format='json',
    )
    assert created.status_code == 201, created.content

    resp = api_client.patch(
        f"{ENROLLMENTS_URL}{created.json()['id']}/",
        {'status': 'active'},
        format='json',
    )

    assert resp.status_code == 400
    assert resp.json()['code'] == REASON_MAX_RESERVATION_WINDOW_EXCEEDED
    assert Enrollment.objects.get(id=created.json()['id']).status == 'cancelled'


def test_gym_admin_can_update_reservation_window_config(api_client, world):
    api_client.force_authenticate(user=world['admin'])

    resp = api_client.put(
        f"/api/organizations/{world['org'].id}/reservation-window-config/",
        {'max_reservation_window_days': 180},
        format='json',
    )

    assert resp.status_code == 200, resp.content
    assert resp.json()['max_reservation_window_days'] == 180
    world['org'].refresh_from_db()
    assert world['org'].max_reservation_window_days == 180


def test_updated_reservation_window_takes_effect_immediately(api_client, world):
    _student_plan(world)
    gym_class = _gym_class(world, 8)
    api_client.force_authenticate(user=world['admin'])
    api_client.put(
        f"/api/organizations/{world['org'].id}/reservation-window-config/",
        {'max_reservation_window_days': 8},
        format='json',
    )
    api_client.force_authenticate(user=world['student'])

    resp = api_client.post(ENROLLMENTS_URL, {'gym_class': gym_class.id}, format='json')

    assert resp.status_code == 201, resp.content
