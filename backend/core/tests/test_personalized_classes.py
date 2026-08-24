from datetime import timedelta

import pytest
from django.utils import timezone

from core.models import (
    Attendance,
    Branch,
    ConsumptionLog,
    GymClass,
    PersonalizedClassSession,
    Plan,
    StudentPlan,
)
from core.services.reservations import reserve_student_in_class
from core.services.teacher_payments import build_teacher_payment_summary

pytestmark = pytest.mark.django_db

QR_URL = '/api/personalized-classes/qr/'
PREVIEW_URL = '/api/attendance-qr/preview/'
CHECKIN_URL = '/api/attendance-qr/check-in/'
TODAY = timezone.localdate()


@pytest.fixture
def setup(make_organization, make_user):
    org = make_organization(name='Personalizados')
    org.personalized_classes_enabled = True
    org.save(update_fields=['personalized_classes_enabled'])
    other_org = make_organization(name='Otra')
    branch = Branch.objects.create(organization=org, name='Central')
    teacher_a = make_user('personal-teacher-a', organization=org, role='teacher')
    teacher_b = make_user('personal-teacher-b', organization=org, role='teacher')
    student = make_user('personal-student', organization=org, role='student')
    other_student = make_user('other-student', organization=other_org, role='student')
    normal_plan = Plan.objects.create(
        organization=org,
        name='Pack grupal',
        plan_type=Plan.PlanType.PACK,
        total_classes=10,
        duration_days=30,
        price=30000,
    )
    personalized_plan = Plan.objects.create(
        organization=org,
        name='Privadas 10',
        plan_type=Plan.PlanType.PERSONALIZED,
        total_classes=10,
        duration_days=30,
        price=120000,
    )
    normal_membership = _membership(student, normal_plan)
    personalized_membership = _membership(student, personalized_plan)
    return {
        'org': org,
        'other_org': other_org,
        'branch': branch,
        'teacher_a': teacher_a,
        'teacher_b': teacher_b,
        'student': student,
        'other_student': other_student,
        'normal_plan': normal_plan,
        'personalized_plan': personalized_plan,
        'normal_membership': normal_membership,
        'personalized_membership': personalized_membership,
    }


def _membership(student, plan, *, total=10, used=0):
    return StudentPlan.objects.create(
        user=student,
        plan=plan,
        organization_id=plan.organization_id,
        start_date=TODAY - timedelta(days=1),
        end_date=TODAY + timedelta(days=30),
        total_classes=total,
        classes_used=used,
        final_price=plan.price,
    )


def _future_class(setup):
    start = timezone.now() + timedelta(days=1)
    return GymClass.objects.create(
        organization=setup['org'],
        branch=setup['branch'],
        teacher=setup['teacher_a'],
        name='Clase grupal',
        start_datetime=start,
        end_datetime=start + timedelta(hours=1),
        capacity=10,
    )


def _personalized_token(api_client, teacher):
    api_client.force_authenticate(user=teacher)
    response = api_client.post(QR_URL, {}, format='json')
    assert response.status_code == 201, response.content
    return response.json()['token']


def _preview(api_client, student, token):
    api_client.force_authenticate(user=student)
    response = api_client.get(PREVIEW_URL, {'token': token})
    return response


def _check_in(api_client, student, grant):
    api_client.force_authenticate(user=student)
    return api_client.post(CHECKIN_URL, {'grant': grant}, format='json')


def _scan_personalized(api_client, student, token):
    preview = _preview(api_client, student, token)
    assert preview.status_code == 200, preview.content
    grant = preview.json()['checkin_grant']
    response = _check_in(api_client, student, grant)
    assert response.status_code == 200, response.content
    return response.json()


def test_normal_and_personalized_plans_keep_independent_balances(api_client, setup):
    gym_class = _future_class(setup)
    reserve_student_in_class(student=setup['student'], gym_class=gym_class)

    setup['normal_membership'].refresh_from_db()
    setup['personalized_membership'].refresh_from_db()
    assert setup['normal_membership'].classes_used == 1
    assert setup['personalized_membership'].classes_used == 0

    token = _personalized_token(api_client, setup['teacher_a'])
    payload = _scan_personalized(api_client, setup['student'], token)

    setup['normal_membership'].refresh_from_db()
    setup['personalized_membership'].refresh_from_db()
    assert setup['normal_membership'].classes_used == 1
    assert setup['personalized_membership'].classes_used == 1
    assert payload['remaining_classes'] == 9


def test_same_personalized_plan_tracks_multiple_real_teachers(api_client, setup):
    _scan_personalized(api_client, setup['student'], _personalized_token(api_client, setup['teacher_a']))
    _scan_personalized(api_client, setup['student'], _personalized_token(api_client, setup['teacher_b']))

    sessions = PersonalizedClassSession.objects.filter(
        student=setup['student'],
        student_plan=setup['personalized_membership'],
        status=PersonalizedClassSession.Status.CONFIRMED,
    ).order_by('confirmed_at')
    assert list(sessions.values_list('teacher_id', flat=True)) == [
        setup['teacher_a'].id,
        setup['teacher_b'].id,
    ]
    assert setup['personalized_membership'].consumption_logs.count() == 2


def test_personalized_qr_rejects_expired_reused_wrong_org_no_plan_and_no_balance(api_client, setup):
    token = _personalized_token(api_client, setup['teacher_a'])
    session = PersonalizedClassSession.objects.get()
    session.qr_expires_at = timezone.now() - timedelta(seconds=1)
    session.save(update_fields=['qr_expires_at'])
    expired = _preview(api_client, setup['student'], token)
    assert expired.status_code == 200
    assert expired.json()['status'] == 'expired_qr'

    token = _personalized_token(api_client, setup['teacher_a'])
    wrong_org = _preview(api_client, setup['other_student'], token)
    assert wrong_org.status_code == 200
    assert wrong_org.json()['status'] == 'wrong_organization'

    setup['personalized_membership'].classes_used = setup['personalized_membership'].total_classes
    setup['personalized_membership'].save(update_fields=['classes_used'])
    no_balance = _preview(api_client, setup['student'], token)
    assert no_balance.status_code == 200
    assert no_balance.json()['detail'] == 'No tienes sesiones personalizadas disponibles.'

    setup['personalized_membership'].classes_used = 0
    setup['personalized_membership'].save(update_fields=['classes_used'])
    preview = _preview(api_client, setup['student'], token)
    grant = preview.json()['checkin_grant']
    first = _check_in(api_client, setup['student'], grant)
    second = _check_in(api_client, setup['student'], grant)
    assert first.status_code == 200
    assert second.status_code == 400
    assert second.json()['code'] == 'qr_reused'

    no_plan_student = setup['other_student']
    no_plan_student.organization = setup['org']
    no_plan_student.save(update_fields=['organization'])
    token = _personalized_token(api_client, setup['teacher_a'])
    no_plan = _preview(api_client, no_plan_student, token)
    assert no_plan.status_code == 200
    assert no_plan.json()['detail'] == 'No tienes sesiones personalizadas disponibles.'


def test_personalized_consumption_creates_attendance_and_exactly_one_log(api_client, setup):
    payload = _scan_personalized(api_client, setup['student'], _personalized_token(api_client, setup['teacher_a']))
    session = PersonalizedClassSession.objects.get(id=payload['class']['personalized_session_id'])

    attendance = Attendance.objects.get(personalized_session=session, student=setup['student'])
    assert attendance.status == Attendance.Status.PRESENT
    assert attendance.source == Attendance.Source.QR
    assert ConsumptionLog.objects.get(personalized_session=session).student_plan == setup['personalized_membership']
    setup['personalized_membership'].refresh_from_db()
    assert setup['personalized_membership'].classes_used == 1


def test_personalized_sessions_are_counted_separately_in_teacher_summary(api_client, setup):
    start = timezone.now()
    GymClass.objects.create(
        organization=setup['org'],
        branch=setup['branch'],
        teacher=setup['teacher_a'],
        name='Clase grupal completada',
        start_datetime=start,
        end_datetime=start + timedelta(hours=1),
        capacity=10,
        status=GymClass.Status.COMPLETED,
    )
    _scan_personalized(api_client, setup['student'], _personalized_token(api_client, setup['teacher_a']))

    summary = build_teacher_payment_summary(setup['org'].id, TODAY, TODAY)
    row = next(item for item in summary['rows'] if item['teacher_id'] == setup['teacher_a'].id)
    assert row['classes_count'] == 2
    assert row['normal_classes_count'] == 1
    assert row['personalized_classes_count'] == 1
    assert {item['class_kind'] for item in row['classes']} == {'normal', 'personalized'}
    assert next(item for item in row['classes'] if item['class_kind'] == 'personalized')['student_id'] == setup['student'].id

    normal_summary = build_teacher_payment_summary(
        setup['org'].id, TODAY, TODAY, class_kind='normal'
    )
    normal_row = next(item for item in normal_summary['rows'] if item['teacher_id'] == setup['teacher_a'].id)
    assert normal_row['classes_count'] == 1
    assert normal_row['normal_classes_count'] == 1
    assert normal_row['personalized_classes_count'] == 0

    personalized_summary = build_teacher_payment_summary(
        setup['org'].id, TODAY, TODAY, class_kind='personalized'
    )
    personalized_row = next(
        item for item in personalized_summary['rows'] if item['teacher_id'] == setup['teacher_a'].id
    )
    assert personalized_row['classes_count'] == 1
    assert personalized_row['normal_classes_count'] == 0
    assert personalized_row['personalized_classes_count'] == 1


def test_feature_flag_blocks_teacher_qr(api_client, setup):
    setup['org'].personalized_classes_enabled = False
    setup['org'].save(update_fields=['personalized_classes_enabled'])
    api_client.force_authenticate(user=setup['teacher_a'])
    response = api_client.post(QR_URL, {}, format='json')
    assert response.status_code == 403
