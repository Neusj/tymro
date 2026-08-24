from datetime import timedelta

import pytest
from django.core import signing
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
LIST_URL = '/api/personalized-classes/'
PREVIEW_URL = '/api/attendance-qr/preview/'
CHECKIN_URL = '/api/attendance-qr/check-in/'
PERSONALIZED_QR_SALT = 'tymro.personalized-class.qr'
TODAY = timezone.localdate()


@pytest.fixture
def setup(make_organization, make_user):
    org = make_organization(name='Personalizados')
    org.personalized_classes_enabled = True
    org.save(update_fields=['personalized_classes_enabled'])
    other_org = make_organization(name='Otra')
    branch = Branch.objects.create(organization=org, name='Central')
    admin = make_user('personal-admin', organization=org, role='gym_admin')
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
        'admin': admin,
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


def _finish_personalized(api_client, actor, session_id):
    api_client.force_authenticate(user=actor)
    response = api_client.post(f'/api/personalized-classes/{session_id}/finish/', {}, format='json')
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


def test_personalized_qr_generation_does_not_store_unused_sessions(api_client, setup):
    _personalized_token(api_client, setup['teacher_a'])

    assert PersonalizedClassSession.objects.count() == 0


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


def test_personalized_classes_are_listed_for_teacher_admin_and_student(api_client, setup):
    first_payload = _scan_personalized(api_client, setup['student'], _personalized_token(api_client, setup['teacher_a']))
    first_session = PersonalizedClassSession.objects.get(id=first_payload['class']['personalized_session_id'])
    _finish_personalized(api_client, setup['teacher_a'], first_session.id)
    second_payload = _scan_personalized(api_client, setup['student'], _personalized_token(api_client, setup['teacher_b']))
    second_session_id = second_payload['class']['personalized_session_id']

    api_client.force_authenticate(user=setup['teacher_a'])
    teacher_response = api_client.get(LIST_URL)
    assert teacher_response.status_code == 200, teacher_response.content
    teacher_payload = teacher_response.json()
    teacher_items = teacher_payload['results']
    assert teacher_payload['count'] == 1
    assert [item['id'] for item in teacher_items] == [first_session.id]
    assert teacher_items[0]['status'] == PersonalizedClassSession.Status.FINISHED
    assert teacher_items[0]['student_id'] == setup['student'].id

    api_client.force_authenticate(user=setup['admin'])
    admin_response = api_client.get(LIST_URL)
    assert admin_response.status_code == 200, admin_response.content
    assert admin_response.json()['count'] == 2
    assert {item['id'] for item in admin_response.json()['results']} == {first_session.id, second_session_id}

    api_client.force_authenticate(user=setup['student'])
    student_response = api_client.get(LIST_URL)
    assert student_response.status_code == 200, student_response.content
    assert student_response.json()['count'] == 2
    assert {item['id'] for item in student_response.json()['results']} == {first_session.id, second_session_id}


def test_personalized_class_list_supports_search_status_and_pagination(api_client, setup):
    first_payload = _scan_personalized(api_client, setup['student'], _personalized_token(api_client, setup['teacher_a']))
    first_session = PersonalizedClassSession.objects.get(id=first_payload['class']['personalized_session_id'])
    _finish_personalized(api_client, setup['teacher_a'], first_session.id)
    _scan_personalized(api_client, setup['student'], _personalized_token(api_client, setup['teacher_b']))

    api_client.force_authenticate(user=setup['admin'])
    response = api_client.get(LIST_URL, {'status': 'finished', 'search': 'Privadas', 'page': 1, 'page_size': 1})

    assert response.status_code == 200, response.content
    payload = response.json()
    assert payload['count'] == 1
    assert payload['total_pages'] == 1
    assert payload['results'][0]['id'] == first_session.id


def test_personalized_class_finish_requires_confirmed_session_and_owner(api_client, setup):
    token = _personalized_token(api_client, setup['teacher_a'])
    api_client.force_authenticate(user=setup['teacher_a'])
    pending_response = api_client.post('/api/personalized-classes/999999/finish/', {}, format='json')
    assert pending_response.status_code == 404

    payload = _scan_personalized(api_client, setup['student'], token)
    session = PersonalizedClassSession.objects.get(id=payload['class']['personalized_session_id'])
    api_client.force_authenticate(user=setup['teacher_b'])
    wrong_teacher = api_client.post(f'/api/personalized-classes/{session.id}/finish/', {}, format='json')
    assert wrong_teacher.status_code == 403

    finished_payload = _finish_personalized(api_client, setup['teacher_a'], session.id)
    session.refresh_from_db()
    assert session.status == PersonalizedClassSession.Status.FINISHED
    assert session.finished_by == setup['teacher_a']
    assert finished_payload['finished_at'] is not None


def test_personalized_qr_rejects_expired_reused_wrong_org_no_plan_and_no_balance(api_client, setup):
    now = timezone.now()
    token = signing.dumps(
        {
            'kind': 'personalized',
            'organization_id': setup['org'].id,
            'teacher_id': setup['teacher_a'].id,
            'branch_id': None,
            'discipline_id': None,
            'class_type_id': None,
            'qr_jti': 'expired-personalized-token',
            'issued_at': (now - timedelta(minutes=4)).isoformat(),
            'expires_at': (now - timedelta(seconds=1)).isoformat(),
        },
        salt=PERSONALIZED_QR_SALT,
    )
    expired = _preview(api_client, setup['student'], token)
    assert expired.status_code == 400
    assert 'expir' in str(expired.json()).lower()

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
    payload = _scan_personalized(api_client, setup['student'], _personalized_token(api_client, setup['teacher_a']))
    session = PersonalizedClassSession.objects.get(id=payload['class']['personalized_session_id'])

    summary_before_finish = build_teacher_payment_summary(setup['org'].id, TODAY, TODAY)
    row_before_finish = next(item for item in summary_before_finish['rows'] if item['teacher_id'] == setup['teacher_a'].id)
    assert row_before_finish['classes_count'] == 1
    assert row_before_finish['personalized_classes_count'] == 0

    _finish_personalized(api_client, setup['teacher_a'], session.id)

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


def test_gym_admin_can_toggle_personalized_classes_from_ui_endpoint(api_client, setup, make_user):
    admin = make_user('personalized-admin', organization=setup['org'], role='gym_admin')
    setup['org'].personalized_classes_enabled = False
    setup['org'].save(update_fields=['personalized_classes_enabled'])

    api_client.force_authenticate(user=admin)
    response = api_client.post(
        f"/api/organizations/{setup['org'].id}/set-personalized-classes/",
        {'enabled': True},
        format='json',
    )

    assert response.status_code == 200, response.content
    setup['org'].refresh_from_db()
    assert setup['org'].personalized_classes_enabled is True
    assert response.json()['personalized_classes_enabled'] is True
