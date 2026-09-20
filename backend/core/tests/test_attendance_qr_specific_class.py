from datetime import timedelta

import pytest
from django.utils import timezone

from core.models import Branch, Enrollment, GymClass
from core.views import _build_qr_token


pytestmark = pytest.mark.django_db
PREVIEW_URL = '/api/attendance-qr/preview/'
CHECKIN_URL = '/api/attendance-qr/check-in/'


@pytest.fixture
def specific_qr_setup(make_organization, make_user):
    org = make_organization()
    teacher = make_user('teacher-specific', organization=org, role='teacher')
    admin = make_user('admin-specific', organization=org, role='gym_admin')
    student = make_user('student-specific', organization=org, role='student')
    other_org = make_organization(name='Otra')
    outsider = make_user('outsider-specific', organization=other_org, role='student')
    branch = Branch.objects.create(organization=org, name='Sede')
    start = timezone.now() - timedelta(minutes=2)
    class_a = GymClass.objects.create(organization=org, branch=branch, teacher=teacher, name='Clase A', start_datetime=start, end_datetime=start + timedelta(hours=1))
    class_b = GymClass.objects.create(organization=org, branch=branch, teacher=teacher, name='Clase B', start_datetime=start, end_datetime=start + timedelta(hours=1))
    Enrollment.objects.create(gym_class=class_a, student=student, status='active')
    Enrollment.objects.create(gym_class=class_b, student=student, status='active')
    return locals()


def test_specific_qr_always_previews_the_signed_class_not_another_simultaneous_class(api_client, specific_qr_setup):
    s = specific_qr_setup
    api_client.force_authenticate(user=s['student'])
    token_a, _ = _build_qr_token(s['org'].id, s['class_a'].id)
    token_b, _ = _build_qr_token(s['org'].id, s['class_b'].id)
    preview_a = api_client.get(PREVIEW_URL, {'token': token_a})
    preview_b = api_client.get(PREVIEW_URL, {'token': token_b})
    assert preview_a.status_code == preview_b.status_code == 200
    assert preview_a.json()['class']['id'] == s['class_a'].id
    assert preview_b.json()['class']['id'] == s['class_b'].id


def test_specific_qr_checkin_marks_only_the_signed_class(api_client, specific_qr_setup):
    s = specific_qr_setup
    api_client.force_authenticate(user=s['student'])
    token, _ = _build_qr_token(s['org'].id, s['class_a'].id)
    preview = api_client.get(PREVIEW_URL, {'token': token}).json()
    response = api_client.post(CHECKIN_URL, {'grant': preview['checkin_grant']}, format='json')
    assert response.status_code == 200
    assert response.json()['class']['id'] == s['class_a'].id
    assert not s['class_b'].attendances.filter(student=s['student']).exists()


def test_general_qr_keeps_existing_candidate_selection(api_client, specific_qr_setup):
    s = specific_qr_setup
    api_client.force_authenticate(user=s['student'])
    token, _ = _build_qr_token(s['org'].id)
    response = api_client.get(PREVIEW_URL, {'token': token})
    assert response.status_code == 200
    # Orden histórico por inicio/id: la primera elegible sigue siendo A.
    assert response.json()['class']['id'] == s['class_a'].id


def test_specific_qr_rejects_student_from_another_tenant(api_client, specific_qr_setup):
    s = specific_qr_setup
    api_client.force_authenticate(user=s['outsider'])
    token, _ = _build_qr_token(s['org'].id, s['class_a'].id)
    response = api_client.get(PREVIEW_URL, {'token': token})
    assert response.status_code == 200
    assert response.json()['status'] == 'wrong_organization'
    assert response.json()['class'] is None


def test_teacher_and_admin_generate_specific_qr(api_client, specific_qr_setup):
    s = specific_qr_setup
    for user in (s['teacher'], s['admin']):
        api_client.force_authenticate(user=user)
        response = api_client.get('/api/attendance-qr/current/', {'class_id': s['class_a'].id})
        assert response.status_code == 200
        api_client.force_authenticate(user=s['student'])
        preview = api_client.get(PREVIEW_URL, {'token': response.json()['token']})
        assert preview.json()['class']['id'] == s['class_a'].id
