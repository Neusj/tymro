from datetime import datetime, time, timedelta

import pytest
from django.utils import timezone

from core.models import (
    Branch,
    ClassType,
    ClassTemplate,
    Discipline,
    Enrollment,
    GymClass,
    Plan,
    RecurringEnrollment,
    StudentPlan,
)
from core.services.recurrence import create_enrollments_for_recurring_subscription
from core.services.reservations import reserve_student_in_class

pytestmark = pytest.mark.django_db

BATCH_URL = '/api/enrollments/batch/'
ENROLLMENTS_URL = '/api/enrollments/'
RECURRING_URL = '/api/recurring-enrollments/'


@pytest.fixture
def world(make_organization, make_user):
    org = make_organization('Org Batch')
    org.max_reservation_window_days = 60
    org.class_generation_window_days = 60
    org.save(update_fields=['max_reservation_window_days', 'class_generation_window_days'])
    teacher = make_user('teacher-batch', organization=org, role='teacher')
    student = make_user('student-batch', organization=org, role='student')
    admin = make_user('admin-batch', organization=org, role='gym_admin')
    branch = Branch.objects.create(organization=org, name='Sede')
    return {'org': org, 'teacher': teacher, 'student': student, 'admin': admin, 'branch': branch}


def _plan(world, *, total_classes=10, classes_used=0, start_offset=-1, end_offset=30):
    catalog = Plan.objects.create(
        organization=world['org'],
        name='Pack',
        plan_type='pack',
        total_classes=total_classes,
        duration_days=60,
        price=30000,
    )
    return StudentPlan.objects.create(
        user=world['student'],
        plan=catalog,
        organization_id=world['org'].id,
        branch=world['branch'],
        start_date=timezone.localdate() + timedelta(days=start_offset),
        end_date=timezone.localdate() + timedelta(days=end_offset),
        total_classes=total_classes,
        classes_used=classes_used,
        final_price=catalog.price,
    )


def _class(world, *, days=3, hour=10, capacity=10, discipline_name='Kickboxing', template=None):
    start = timezone.make_aware(
        datetime.combine(timezone.localdate() + timedelta(days=days), time(hour, 0)),
        timezone.get_current_timezone(),
    )
    discipline = Discipline.objects.create(
        organization=world['org'],
        name=f'{discipline_name}-{days}-{hour}',
    )
    return GymClass.objects.create(
        organization=world['org'],
        branch=world['branch'],
        teacher=world['teacher'],
        class_template=template,
        discipline=discipline,
        name=discipline_name,
        start_datetime=start,
        end_datetime=start + timedelta(hours=1),
        capacity=capacity,
        status=GymClass.Status.SCHEDULED,
    )


def _template(world, gym_class):
    class_date = timezone.localtime(gym_class.start_datetime).date()
    start_time = timezone.localtime(gym_class.start_datetime).time().replace(tzinfo=None)
    end_time = timezone.localtime(gym_class.end_datetime).time().replace(tzinfo=None)
    return ClassTemplate.objects.create(
        organization=world['org'],
        branch=world['branch'],
        teacher=world['teacher'],
        name='Serie semanal',
        weekday=class_date.weekday(),
        start_time=start_time,
        end_time=end_time,
        capacity=gym_class.capacity,
        start_date=timezone.localdate() - timedelta(days=1),
    )


def _program_template(world, *, weekday, name='Programa', start_hour=10, discipline=None, class_type=None):
    return ClassTemplate.objects.create(
        organization=world['org'],
        branch=world['branch'],
        teacher=world['teacher'],
        discipline=discipline,
        class_type=class_type,
        name=name,
        weekday=weekday,
        start_time=time(start_hour, 0),
        end_time=time(start_hour + 1, 0),
        capacity=10,
        start_date=timezone.localdate(),
    )


def test_individual_reservation_validates_plan_on_class_date(api_client, world):
    gym_class = _class(world, days=10)
    membership = _plan(world, total_classes=5, end_offset=5)
    api_client.force_authenticate(world['student'])

    response = api_client.post(ENROLLMENTS_URL, {'gym_class': gym_class.id}, format='json')

    assert response.status_code == 400, response.content
    assert Enrollment.objects.filter(student=world['student'], gym_class=gym_class).count() == 0
    membership.refresh_from_db()
    assert membership.classes_used == 0


def test_batch_reserves_explicit_classes_from_different_disciplines(api_client, world):
    kickboxing = _class(world, days=3, hour=10, discipline_name='Kickboxing')
    bjj = _class(world, days=5, hour=11, discipline_name='BJJ')
    membership = _plan(world, total_classes=8)
    api_client.force_authenticate(world['student'])

    response = api_client.post(
        BATCH_URL,
        {'classes': [{'gym_class': kickboxing.id}, {'gym_class': bjj.id}]},
        format='json',
    )

    assert response.status_code == 201, response.content
    assert response.json()['created_count'] == 2
    assert set(
        Enrollment.objects.filter(student=world['student']).values_list('gym_class_id', flat=True)
    ) == {kickboxing.id, bjj.id}
    membership.refresh_from_db()
    assert membership.classes_used == 2


def test_batch_is_all_or_nothing_when_one_class_is_full(api_client, world, make_user):
    open_class = _class(world, days=3, hour=10)
    full_class = _class(world, days=4, hour=12, capacity=1)
    other_student = make_user('student-full-seat', organization=world['org'], role='student')
    Enrollment.objects.create(student=other_student, gym_class=full_class, status='active')
    membership = _plan(world, total_classes=8)
    api_client.force_authenticate(world['student'])

    response = api_client.post(
        BATCH_URL,
        {'classes': [{'gym_class': open_class.id}, {'gym_class': full_class.id}]},
        format='json',
    )

    assert response.status_code == 400, response.content
    assert response.json()['code'] == 'batch_reservation_failed'
    assert Enrollment.objects.filter(student=world['student']).count() == 0
    membership.refresh_from_db()
    assert membership.classes_used == 0


def test_batch_is_all_or_nothing_when_balance_runs_out(api_client, world):
    first = _class(world, days=3, hour=10)
    second = _class(world, days=4, hour=11)
    membership = _plan(world, total_classes=1)
    api_client.force_authenticate(world['student'])

    response = api_client.post(
        BATCH_URL,
        {'classes': [{'gym_class': first.id}, {'gym_class': second.id}]},
        format='json',
    )

    assert response.status_code == 400, response.content
    assert response.json()['code'] == 'batch_reservation_failed'
    assert Enrollment.objects.filter(student=world['student']).count() == 0
    membership.refresh_from_db()
    assert membership.classes_used == 0


def test_same_template_candidates_reserve_next_weeks_up_to_balance(api_client, world):
    next_weekday = (timezone.localdate().weekday() + 1) % 7
    template = _program_template(world, weekday=next_weekday, name='Kickboxing semanal')
    membership = _plan(world, total_classes=4)
    api_client.force_authenticate(world['student'])

    candidates = api_client.post(
        f'/api/class-templates/{template.id}/reservation-candidates/',
        {'mode': 'same_template', 'limit': 4},
        format='json',
    )

    assert candidates.status_code == 200, candidates.content
    rows = candidates.json()['candidates']
    assert len(rows) == 4
    assert {row['class_template'] for row in rows} == {template.id}

    response = api_client.post(
        BATCH_URL,
        {'classes': [{'gym_class': row['id']} for row in rows]},
        format='json',
    )

    assert response.status_code == 201, response.content
    assert response.json()['created_count'] == 4
    membership.refresh_from_db()
    assert membership.classes_used == 4


def test_program_candidates_include_sibling_weekday_templates(api_client, world):
    today_weekday = timezone.localdate().weekday()
    weekdays = [(today_weekday + offset) % 7 for offset in (1, 3, 5)]
    discipline = Discipline.objects.create(organization=world['org'], name='BJJ Programa')
    class_type = ClassType.objects.create(organization=world['org'], name='Adultos')
    templates = [
        _program_template(
            world,
            weekday=weekday,
            name='BJJ LMW',
            discipline=discipline,
            class_type=class_type,
        )
        for weekday in weekdays
    ]
    membership = _plan(world, total_classes=6)
    api_client.force_authenticate(world['student'])

    candidates = api_client.post(
        f'/api/class-templates/{templates[0].id}/reservation-candidates/',
        {'mode': 'program', 'limit': 6},
        format='json',
    )

    assert candidates.status_code == 200, candidates.content
    rows = candidates.json()['candidates']
    assert len(rows) == 6
    assert len({row['class_template'] for row in rows}) >= 2

    response = api_client.post(
        BATCH_URL,
        {'classes': [{'gym_class': row['id']} for row in rows]},
        format='json',
    )

    assert response.status_code == 201, response.content
    assert response.json()['created_count'] == 6
    membership.refresh_from_db()
    assert membership.classes_used == 6


def test_manual_cancellation_of_recurring_instance_is_not_reactivated(api_client, world):
    gym_class = _class(world, days=3)
    template = _template(world, gym_class)
    gym_class.class_template = template
    gym_class.save(update_fields=['class_template'])
    membership = _plan(world)
    recurring = RecurringEnrollment.objects.create(
        student=world['student'],
        class_template=template,
        start_date=timezone.localdate() - timedelta(days=1),
        student_plan=membership,
    )
    enrollment = reserve_student_in_class(
        student=world['student'],
        gym_class=gym_class,
        recurring_enrollment=recurring,
        student_plan_id=membership.id,
    )
    api_client.force_authenticate(world['student'])

    cancelled = api_client.post(f'{ENROLLMENTS_URL}{enrollment.id}/cancel/')
    summary = create_enrollments_for_recurring_subscription(
        recurring,
        class_instances=[gym_class],
    )

    assert cancelled.status_code == 200, cancelled.content
    assert summary['created_count'] == 0
    assert summary['skipped'][0]['reason'] == 'manual_recurring_cancellation'
    enrollment.refresh_from_db()
    assert enrollment.status == 'cancelled'
    assert enrollment.recurring_resync_blocked is True
    membership.refresh_from_db()
    assert membership.classes_used == 0


def test_recurring_instance_falls_back_from_expired_pinned_plan_to_valid_plan(world):
    gym_class = _class(world, days=10)
    template = _template(world, gym_class)
    gym_class.class_template = template
    gym_class.save(update_fields=['class_template'])
    old_membership = _plan(world, total_classes=5, end_offset=5)
    renewed_membership = _plan(world, total_classes=5, start_offset=6, end_offset=40)
    recurring = RecurringEnrollment.objects.create(
        student=world['student'],
        class_template=template,
        start_date=timezone.localdate() - timedelta(days=1),
        student_plan=old_membership,
    )

    summary = create_enrollments_for_recurring_subscription(
        recurring,
        class_instances=[gym_class],
    )

    assert summary['created_count'] == 1
    assert summary['skipped'] == []
    enrollment = Enrollment.objects.get(student=world['student'], gym_class=gym_class)
    assert enrollment.student_plan_id == renewed_membership.id
    old_membership.refresh_from_db()
    renewed_membership.refresh_from_db()
    recurring.refresh_from_db()
    assert old_membership.classes_used == 0
    assert renewed_membership.classes_used == 1
    assert recurring.student_plan_id == renewed_membership.id


def test_admin_deleting_recurring_enrollment_cancels_future_instances(api_client, world):
    gym_class = _class(world, days=3)
    template = _template(world, gym_class)
    gym_class.class_template = template
    gym_class.save(update_fields=['class_template'])
    membership = _plan(world)
    recurring = RecurringEnrollment.objects.create(
        student=world['student'],
        class_template=template,
        start_date=timezone.localdate() - timedelta(days=1),
        student_plan=membership,
    )
    enrollment = reserve_student_in_class(
        student=world['student'],
        gym_class=gym_class,
        recurring_enrollment=recurring,
        student_plan_id=membership.id,
    )
    api_client.force_authenticate(world['admin'])

    response = api_client.delete(f'{RECURRING_URL}{recurring.id}/')

    assert response.status_code == 204, response.content
    assert not RecurringEnrollment.objects.filter(id=recurring.id).exists()
    enrollment.refresh_from_db()
    assert enrollment.status == 'cancelled'
    membership.refresh_from_db()
    assert membership.classes_used == 0
