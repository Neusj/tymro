from datetime import timedelta

import pytest
from django.utils import timezone

from core.models import Plan, StudentPlan, StudentPlanChangeLog

pytestmark = pytest.mark.django_db


def _plan(org):
    return Plan.objects.create(
        organization=org,
        name='Pack 10',
        plan_type=Plan.PlanType.PACK,
        total_classes=10,
        duration_days=30,
        price=30000,
    )


def _membership(student, plan, *, classes_used=2, total_classes=10):
    today = timezone.localdate()
    return StudentPlan.objects.create(
        user=student,
        plan=plan,
        organization_id=plan.organization_id,
        start_date=today - timedelta(days=1),
        end_date=today + timedelta(days=30),
        total_classes=total_classes,
        classes_used=classes_used,
        discount_percentage=0,
        final_price=30000,
    )


def test_gym_admin_updates_membership_and_records_change_logs(api_client, make_organization, make_user):
    org = make_organization()
    admin = make_user('admin-memberships', organization=org, role='gym_admin')
    student = make_user('student-memberships', organization=org, role='student')
    plan = _plan(org)
    membership = _membership(student, plan, classes_used=2, total_classes=10)
    api_client.force_authenticate(admin)

    response = api_client.patch(
        f'/api/plans/{plan.id}/memberships/{membership.id}/edit/',
        {
            'classes_used': 1,
            'total_classes': 12,
            'reason': 'Correccion administrativa',
        },
        format='json',
    )

    assert response.status_code == 200, response.content
    membership.refresh_from_db()
    assert membership.classes_used == 1
    assert membership.total_classes == 12
    assert response.data['classes_used'] == 1
    assert response.data['total_classes'] == 12

    logs = {
        item.field: item
        for item in StudentPlanChangeLog.objects.filter(student_plan=membership)
    }
    assert logs['classes_used'].old_value == '2'
    assert logs['classes_used'].new_value == '1'
    assert logs['classes_used'].reason == 'Correccion administrativa'
    assert logs['classes_used'].changed_by_id == admin.id
    assert logs['total_classes'].old_value == '10'
    assert logs['total_classes'].new_value == '12'
    assert logs['total_classes'].organization_id == org.id


def test_gym_admin_can_read_membership_change_log(api_client, make_organization, make_user):
    org = make_organization()
    admin = make_user('admin-log', organization=org, role='gym_admin')
    student = make_user('student-log', organization=org, role='student')
    plan = _plan(org)
    membership = _membership(student, plan)
    StudentPlanChangeLog.objects.create(
        student_plan=membership,
        organization=org,
        changed_by=admin,
        field='classes_used',
        old_value='2',
        new_value='1',
        reason='Ajuste',
    )
    api_client.force_authenticate(admin)

    response = api_client.get(f'/api/plans/{plan.id}/memberships/{membership.id}/change-log/')

    assert response.status_code == 200, response.content
    assert response.data[0]['field'] == 'classes_used'
    assert response.data[0]['changed_by'] == admin.id
    assert response.data[0]['changed_by_name']


def test_membership_update_rejects_used_classes_over_total(api_client, make_organization, make_user):
    org = make_organization()
    admin = make_user('admin-invalid-membership', organization=org, role='gym_admin')
    student = make_user('student-invalid-membership', organization=org, role='student')
    plan = _plan(org)
    membership = _membership(student, plan, classes_used=2, total_classes=10)
    api_client.force_authenticate(admin)

    response = api_client.patch(
        f'/api/plans/{plan.id}/memberships/{membership.id}/edit/',
        {
            'classes_used': 11,
            'total_classes': 10,
            'reason': 'Intento invalido',
        },
        format='json',
    )

    assert response.status_code == 400, response.content
    membership.refresh_from_db()
    assert membership.classes_used == 2
    assert not StudentPlanChangeLog.objects.filter(student_plan=membership).exists()

