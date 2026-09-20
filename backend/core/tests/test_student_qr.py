from datetime import timedelta

import pytest
from django.utils import timezone

from core.models import Branch, GymClass


pytestmark = pytest.mark.django_db


@pytest.fixture
def qr_context(make_organization, make_user):
    org_a = make_organization(name='A')
    org_b = make_organization(name='B')
    teacher = make_user('teacher', organization=org_a, role='teacher')
    stranger = make_user('stranger', organization=org_a, role='teacher')
    student = make_user('student', organization=org_a, role='student')
    other_student = make_user('other', organization=org_b, role='student')
    branch = Branch.objects.create(organization=org_a, name='Sede')
    start = timezone.now() + timedelta(hours=1)
    gym_class = GymClass.objects.create(
        organization=org_a, branch=branch, teacher=teacher, name='QR',
        start_datetime=start, end_datetime=start + timedelta(hours=1),
    )
    return locals()


def test_student_gets_own_opaque_qr_token_only(api_client, qr_context):
    api_client.force_authenticate(user=qr_context['student'])
    response = api_client.get('/api/me/student-qr/')
    assert response.status_code == 200
    assert response.json()['token'] == str(qr_context['student'].student_qr_token)


def test_teacher_resolves_student_qr_only_in_own_class_tenant(api_client, qr_context):
    data = qr_context
    api_client.force_authenticate(user=data['teacher'])
    response = api_client.post(
        f"/api/classes/{data['gym_class'].id}/student-qr/",
        {'token': str(data['student'].student_qr_token)}, format='json',
    )
    assert response.status_code == 200
    assert response.json()['student']['id'] == data['student'].id
    assert response.json()['enrolled'] is False

    cross_tenant = api_client.post(
        f"/api/classes/{data['gym_class'].id}/student-qr/",
        {'token': str(data['other_student'].student_qr_token)}, format='json',
    )
    assert cross_tenant.status_code == 404


def test_unassigned_teacher_cannot_resolve_student_qr(api_client, qr_context):
    data = qr_context
    api_client.force_authenticate(user=data['stranger'])
    response = api_client.post(
        f"/api/classes/{data['gym_class'].id}/student-qr/",
        {'token': str(data['student'].student_qr_token)}, format='json',
    )
    # El queryset de clases del profesor no revela una clase ajena.
    assert response.status_code == 404
