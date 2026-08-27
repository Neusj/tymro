from datetime import datetime, time, timedelta

import pytest
from django.utils import timezone

from core.models import (
    Branch,
    ClassTemplate,
    ClassType,
    ConsumptionLog,
    Discipline,
    Enrollment,
    GymClass,
    Plan,
    StudentPlan,
)

pytestmark = pytest.mark.django_db

ENDPOINT = '/api/classes/by-date/'


def _target_date(days=3):
    return timezone.localdate() + timedelta(days=days)


def _ids(rows):
    return {row['id'] for row in rows}


@pytest.fixture
def org_world(make_organization, make_user):
    org = make_organization('Org A')
    teacher_a = make_user('teacher_a', organization=org, role='teacher')
    teacher_b = make_user('teacher_b', organization=org, role='teacher')
    admin = make_user('admin_a', organization=org, role='gym_admin')
    student = make_user('student_a', organization=org, role='student', email='student_a@gym.cl')
    branch = Branch.objects.create(organization=org, name='Sede A')
    class_type = ClassType.objects.create(organization=org, name='Funcional')
    discipline = Discipline.objects.create(organization=org, name='Box')
    return {
        'org': org,
        'admin': admin,
        'teacher_a': teacher_a,
        'teacher_b': teacher_b,
        'student': student,
        'branch': branch,
        'class_type': class_type,
        'discipline': discipline,
    }


def _class(world, target_date, *, teacher=None, template=None, name='Clase', status=GymClass.Status.SCHEDULED,
           capacity=10, start_time=time(10, 0)):
    start = timezone.make_aware(
        datetime.combine(target_date, start_time),
        timezone.get_current_timezone(),
    )
    return GymClass.objects.create(
        organization=world['org'],
        branch=world['branch'],
        teacher=teacher or world['teacher_a'],
        class_type=world['class_type'],
        discipline=world['discipline'],
        class_template=template,
        name=name,
        start_datetime=start,
        end_datetime=start + timedelta(hours=1),
        capacity=capacity,
        status=status,
    )


def _template(world, target_date, *, teacher=None, name='Serie', start_time=time(10, 0), is_active=True):
    return ClassTemplate.objects.create(
        organization=world['org'],
        branch=world['branch'],
        teacher=teacher or world['teacher_a'],
        class_type=world['class_type'],
        discipline=world['discipline'],
        name=name,
        weekday=target_date.weekday(),
        start_time=start_time,
        end_time=time(start_time.hour + 1, start_time.minute),
        capacity=12,
        start_date=target_date - timedelta(days=7),
        is_active=is_active,
    )


def _plan(world, classes_used=0):
    today = timezone.localdate()
    plan = Plan.objects.create(
        organization=world['org'],
        name=f'Pack {world["student"].id}',
        plan_type='pack',
        total_classes=10,
        duration_days=30,
        price=30000,
    )
    return StudentPlan.objects.create(
        user=world['student'],
        plan=plan,
        organization_id=world['org'].id,
        start_date=today - timedelta(days=1),
        end_date=today + timedelta(days=30),
        total_classes=10,
        classes_used=classes_used,
        final_price=30000,
    )


def _consume(world, gym_class, student_plan):
    enrollment = Enrollment.objects.create(
        gym_class=gym_class,
        student=world['student'],
        status='active',
        student_plan=student_plan,
    )
    ConsumptionLog.objects.create(
        user=world['student'],
        student_plan=student_plan,
        class_instance=gym_class,
        branch=gym_class.branch,
    )
    return enrollment


def test_by_date_requires_valid_date(api_client, org_world):
    api_client.force_authenticate(user=org_world['admin'])

    missing = api_client.get(ENDPOINT)
    invalid = api_client.get(ENDPOINT, {'date': '08-07-2026'})

    assert missing.status_code == 400
    assert invalid.status_code == 400


def test_by_date_returns_materialized_classes_only(api_client, org_world):
    target = _target_date()
    gym_class = _class(org_world, target, name='Materializada')
    _class(org_world, target + timedelta(days=1), name='Otro dia')
    api_client.force_authenticate(user=org_world['admin'])

    resp = api_client.get(ENDPOINT, {'date': target.isoformat()})

    assert resp.status_code == 200, resp.content
    rows = resp.json()
    assert _ids(rows) == {gym_class.id}
    assert rows[0]['reservable'] is True


def test_old_classes_endpoint_still_lists_without_date(api_client, org_world):
    target = _target_date()
    first = _class(org_world, target, name='Primer dia')
    second = _class(org_world, target + timedelta(days=1), name='Segundo dia')
    api_client.force_authenticate(user=org_world['admin'])

    resp = api_client.get('/api/classes/')

    assert resp.status_code == 200, resp.content
    assert {first.id, second.id} <= _ids(resp.json())


def test_classes_lists_hide_future_instances_from_inactive_templates(api_client, org_world):
    target = _target_date()
    inactive_template = _template(org_world, target, name='Oculta', is_active=False)
    hidden = _class(org_world, target, template=inactive_template, name='Futura oculta')
    visible = _class(org_world, target, name='Suelta visible', start_time=time(12, 0))
    api_client.force_authenticate(user=org_world['admin'])

    by_date = api_client.get(ENDPOINT, {'date': target.isoformat()})
    listing = api_client.get('/api/classes/')

    assert by_date.status_code == 200, by_date.content
    assert listing.status_code == 200, listing.content
    assert hidden.id not in _ids(by_date.json())
    assert hidden.id not in _ids(listing.json())
    assert visible.id in _ids(by_date.json())
    assert visible.id in _ids(listing.json())


def test_class_template_history_filter_keeps_future_instances_from_inactive_templates(
    api_client, org_world,
):
    target = _target_date()
    inactive_template = _template(org_world, target, name='Historial', is_active=False)
    hidden_operationally = _class(
        org_world, target, template=inactive_template, name='Futura auditada'
    )
    api_client.force_authenticate(user=org_world['admin'])

    resp = api_client.get('/api/classes/', {'class_template': inactive_template.id})

    assert resp.status_code == 200, resp.content
    assert _ids(resp.json()) == {hidden_operationally.id}


def test_deactivating_template_hides_future_instances_and_refunds_active_enrollments(
    api_client, org_world,
):
    target = _target_date()
    template = _template(org_world, target, name='Con reserva')
    gym_class = _class(org_world, target, template=template, name='Futura con reserva')
    plan = _plan(org_world, classes_used=1)
    enrollment = _consume(org_world, gym_class, plan)
    api_client.force_authenticate(user=org_world['admin'])

    resp = api_client.patch(f'/api/class-templates/{template.id}/', {'is_active': False}, format='json')
    by_date = api_client.get(ENDPOINT, {'date': target.isoformat()})

    assert resp.status_code == 200, resp.content
    template.refresh_from_db()
    gym_class.refresh_from_db()
    enrollment.refresh_from_db()
    plan.refresh_from_db()
    assert template.is_active is False
    assert gym_class.status == GymClass.Status.SCHEDULED
    assert enrollment.status == 'cancelled'
    assert plan.classes_used == 0
    assert not ConsumptionLog.objects.filter(class_instance=gym_class).exists()
    assert gym_class.id not in _ids(by_date.json())


def test_bulk_deactivating_template_refunds_future_active_enrollments(api_client, org_world):
    target = _target_date()
    template = _template(org_world, target, name='Masiva con reserva')
    gym_class = _class(org_world, target, template=template, name='Futura masiva')
    plan = _plan(org_world, classes_used=1)
    enrollment = _consume(org_world, gym_class, plan)
    api_client.force_authenticate(user=org_world['admin'])

    resp = api_client.post(
        '/api/class-templates/bulk-action/',
        {'action': 'deactivate', 'template_ids': [template.id]},
        format='json',
    )

    assert resp.status_code == 200, resp.content
    template.refresh_from_db()
    gym_class.refresh_from_db()
    enrollment.refresh_from_db()
    plan.refresh_from_db()
    assert template.is_active is False
    assert gym_class.status == GymClass.Status.SCHEDULED
    assert enrollment.status == 'cancelled'
    assert plan.classes_used == 0


def test_by_date_projects_virtual_classes_without_creating_rows(api_client, org_world):
    target = _target_date()
    template = _template(org_world, target, name='Virtual')
    before = GymClass.objects.count()
    api_client.force_authenticate(user=org_world['admin'])

    resp = api_client.get(ENDPOINT, {'date': target.isoformat()})

    assert resp.status_code == 200, resp.content
    assert GymClass.objects.count() == before
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]['id'] == f'virtual:{template.id}:{target.isoformat()}'
    assert rows[0]['class_template'] == template.id
    assert rows[0]['teacher'] == org_world['teacher_a'].id
    assert rows[0]['enrollments_count'] == 0
    assert rows[0]['reservable'] is True


def test_by_date_returns_mixed_materialized_and_virtual_without_duplicate(api_client, org_world):
    target = _target_date()
    materialized_template = _template(org_world, target, name='Ya existe', start_time=time(9, 0))
    virtual_template = _template(org_world, target, name='Proyectada', start_time=time(11, 0))
    gym_class = _class(
        org_world,
        target,
        template=materialized_template,
        name='Instancia real',
        start_time=time(9, 0),
    )
    api_client.force_authenticate(user=org_world['admin'])

    resp = api_client.get(ENDPOINT, {'date': target.isoformat()})

    assert resp.status_code == 200, resp.content
    assert _ids(resp.json()) == {gym_class.id, f'virtual:{virtual_template.id}:{target.isoformat()}'}


@pytest.mark.parametrize(
    'window_days,target_offset,expected',
    [
        (3, 3, True),
        (2, 3, False),
    ],
)
def test_by_date_virtual_reservable_follows_org_window(
    api_client, org_world, window_days, target_offset, expected
):
    target = _target_date(target_offset)
    org_world['org'].max_reservation_window_days = window_days
    org_world['org'].save(update_fields=['max_reservation_window_days'])
    _template(org_world, target)
    api_client.force_authenticate(user=org_world['admin'])

    resp = api_client.get(ENDPOINT, {'date': target.isoformat()})

    assert resp.status_code == 200, resp.content
    assert resp.json()[0]['reservable'] is expected


def test_by_date_admin_sees_own_org_real_and_virtual_but_not_foreign(
    api_client, org_world, make_organization, make_user
):
    target = _target_date()
    own_class = _class(org_world, target, name='Propia')
    own_template = _template(org_world, target, name='Propia virtual', start_time=time(12, 0))
    other = org_world.copy()
    other['org'] = make_organization('Org B')
    other['teacher_a'] = make_user('teacher_foreign', organization=other['org'], role='teacher')
    other['branch'] = Branch.objects.create(organization=other['org'], name='Sede B')
    other['class_type'] = ClassType.objects.create(organization=other['org'], name='Yoga')
    other['discipline'] = Discipline.objects.create(organization=other['org'], name='Yoga')
    foreign_class = _class(other, target, name='Ajena')
    foreign_template = _template(other, target, name='Ajena virtual', start_time=time(13, 0))
    api_client.force_authenticate(user=org_world['admin'])

    resp = api_client.get(ENDPOINT, {'date': target.isoformat()})

    assert resp.status_code == 200, resp.content
    ids = _ids(resp.json())
    assert own_class.id in ids
    assert f'virtual:{own_template.id}:{target.isoformat()}' in ids
    assert foreign_class.id not in ids
    assert f'virtual:{foreign_template.id}:{target.isoformat()}' not in ids


def test_by_date_teacher_sees_only_own_real_and_virtual(api_client, org_world):
    target = _target_date()
    own_class = _class(org_world, target, teacher=org_world['teacher_a'], name='Mia')
    other_class = _class(org_world, target, teacher=org_world['teacher_b'], name='Otra', start_time=time(11, 0))
    own_template = _template(org_world, target, teacher=org_world['teacher_a'], start_time=time(12, 0))
    other_template = _template(org_world, target, teacher=org_world['teacher_b'], start_time=time(13, 0))
    api_client.force_authenticate(user=org_world['teacher_a'])

    resp = api_client.get(ENDPOINT, {'date': target.isoformat()})

    assert resp.status_code == 200, resp.content
    ids = _ids(resp.json())
    assert own_class.id in ids
    assert f'virtual:{own_template.id}:{target.isoformat()}' in ids
    assert other_class.id not in ids
    assert f'virtual:{other_template.id}:{target.isoformat()}' not in ids


def test_by_date_student_uses_existing_visibility_and_mine_rules(api_client, org_world):
    target = _target_date()
    visible = _class(org_world, target, name='Visible')
    suspended = _class(
        org_world,
        target,
        name='Suspendida',
        status=GymClass.Status.SUSPENDED,
        start_time=time(11, 0),
    )
    template = _template(org_world, target, name='Virtual', start_time=time(12, 0))
    Enrollment.objects.create(gym_class=visible, student=org_world['student'], status='active')
    api_client.force_authenticate(user=org_world['student'])

    all_resp = api_client.get(ENDPOINT, {'date': target.isoformat()})
    mine_resp = api_client.get(ENDPOINT, {'date': target.isoformat(), 'mine': 'true'})

    assert all_resp.status_code == 200, all_resp.content
    all_ids = _ids(all_resp.json())
    assert visible.id in all_ids
    assert suspended.id not in all_ids
    assert f'virtual:{template.id}:{target.isoformat()}' in all_ids

    assert mine_resp.status_code == 200, mine_resp.content
    assert _ids(mine_resp.json()) == {visible.id}
