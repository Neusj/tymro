from datetime import timedelta

import pytest
from django.utils import timezone

from core.models import Plan, StudentPlan

pytestmark = pytest.mark.django_db


def _plan(org, total_classes=10, unlimited=False):
    return Plan.objects.create(
        organization=org,
        name=f'Plan {total_classes}-{unlimited}',
        plan_type='pack',
        total_classes=total_classes,
        unlimited_classes=unlimited,
        duration_days=30,
        price=30000,
    )


def _membership(student, plan, *, start_offset=-10, end_offset=10, classes_used=0):
    today = timezone.localdate()
    return StudentPlan.objects.create(
        user=student,
        plan=plan,
        organization=plan.organization,
        start_date=today + timedelta(days=start_offset),
        end_date=today + timedelta(days=end_offset),
        total_classes=plan.total_classes,
        unlimited_classes=plan.unlimited_classes,
        classes_used=classes_used,
        final_price=plan.price,
        is_active=True,
    )


def test_dashboard_counts_active_and_inactive_students(api_client, make_organization, make_user):
    org = make_organization()
    org.student_inactivity_grace_days = 3
    org.save(update_fields=['student_inactivity_grace_days'])
    admin = make_user('activity-admin', organization=org, role='gym_admin')
    plan = _plan(org)

    active = make_user('activity-active', organization=org, role='student')
    expired_outside_grace = make_user('activity-expired', organization=org, role='student')
    expired_inside_grace = make_user('activity-grace', organization=org, role='student')
    no_plan = make_user('activity-noplan', organization=org, role='student')

    _membership(active, plan)
    _membership(expired_outside_grace, plan, start_offset=-40, end_offset=-3)
    _membership(expired_inside_grace, plan, start_offset=-40, end_offset=-2)

    api_client.force_authenticate(user=admin)
    response = api_client.get('/api/dashboard/')

    assert response.status_code == 200
    assert response.data['students'] == 4
    assert response.data['students_active'] == 1
    assert response.data['students_inactive'] == 2
    assert response.data['student_inactivity_grace_days'] == 3


def test_user_list_filters_students_by_activity(api_client, make_organization, make_user):
    org = make_organization()
    org.student_inactivity_grace_days = 3
    org.save(update_fields=['student_inactivity_grace_days'])
    admin = make_user('activity-filter-admin', organization=org, role='gym_admin')
    plan = _plan(org)

    active = make_user('activity-filter-active', organization=org, role='student')
    inactive = make_user('activity-filter-inactive', organization=org, role='student')
    grace = make_user('activity-filter-grace', organization=org, role='student')
    no_plan = make_user('activity-filter-noplan', organization=org, role='student')
    teacher = make_user('activity-filter-teacher', organization=org, role='teacher')

    _membership(active, plan)
    _membership(inactive, plan, start_offset=-40, end_offset=-3)
    _membership(grace, plan, start_offset=-40, end_offset=-2)

    api_client.force_authenticate(user=admin)

    active_response = api_client.get('/api/users/', {'role': 'student', 'student_status': 'active'})
    inactive_response = api_client.get('/api/users/', {'role': 'student', 'student_status': 'inactive'})

    assert active_response.status_code == 200
    assert [item['id'] for item in active_response.data] == [active.id]

    assert inactive_response.status_code == 200
    inactive_ids = {item['id'] for item in inactive_response.data}
    assert inactive_ids == {inactive.id, no_plan.id}
    assert grace.id not in inactive_ids
    assert teacher.id not in inactive_ids


def test_student_inactivity_config_changes_inactive_threshold(api_client, make_organization, make_user):
    org = make_organization()
    admin = make_user('activity-config-admin', organization=org, role='gym_admin')
    plan = _plan(org)
    expired_yesterday = make_user('activity-config-student', organization=org, role='student')
    _membership(expired_yesterday, plan, start_offset=-40, end_offset=-1)

    api_client.force_authenticate(user=admin)
    update_response = api_client.put(
        f'/api/organizations/{org.id}/student-inactivity-config/',
        {'student_inactivity_grace_days': 1},
        format='json',
    )
    dashboard_response = api_client.get('/api/dashboard/')

    assert update_response.status_code == 200
    assert update_response.data['student_inactivity_grace_days'] == 1
    assert dashboard_response.data['students_inactive'] == 1
