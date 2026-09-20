from concurrent.futures import ThreadPoolExecutor
from datetime import time, timedelta
from threading import Barrier

import pytest
from django.db import close_old_connections
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import Branch, ClassTemplate, GymClass


pytestmark = pytest.mark.django_db


@pytest.fixture
def world(make_organization, make_user):
    org = make_organization('Org Projected Operations')
    branch = Branch.objects.create(organization=org, name='Central')
    teacher = make_user('projected-teacher', organization=org, role='teacher')
    admin = make_user('projected-admin', organization=org, role='gym_admin')
    student = make_user('projected-student', organization=org, role='student')
    target = timezone.localdate() + timedelta(days=30)
    template = ClassTemplate.objects.create(
        organization=org,
        branch=branch,
        teacher=teacher,
        name='Clase proyectada',
        weekday=target.weekday(),
        start_time=time(10, 0),
        end_time=time(11, 0),
        capacity=12,
        start_date=target - timedelta(days=7),
    )
    return {
        'org': org,
        'teacher': teacher,
        'admin': admin,
        'student': student,
        'target': target,
        'template': template,
    }


def _client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _url():
    return '/api/classes/resolve-projection/'


def _payload(world):
    return {'id': f"virtual:{world['template'].id}:{world['target'].isoformat()}"}


@pytest.mark.parametrize('actor_key', ['teacher', 'admin'])
def test_staff_resolves_projection_to_real_class_outside_reservation_window(world, actor_key):
    response = _client(world[actor_key]).post(_url(), _payload(world), format='json')

    assert response.status_code == 201, response.data
    real_id = response.data['gym_class']['id']
    assert isinstance(real_id, int)
    gym_class = GymClass.objects.get(pk=real_id)
    assert gym_class.class_template_id == world['template'].id
    assert timezone.localtime(gym_class.start_datetime).date() == world['target']


def test_repeated_resolution_reuses_existing_instance(world):
    client = _client(world['teacher'])

    first = client.post(_url(), _payload(world), format='json')
    second = client.post(_url(), _payload(world), format='json')

    assert first.status_code == 201, first.data
    assert second.status_code == 200, second.data
    assert first.data['gym_class']['id'] == second.data['gym_class']['id']
    assert GymClass.objects.filter(class_template=world['template']).count() == 1


def test_student_cannot_materialize_projection_without_reserving(world):
    response = _client(world['student']).post(_url(), _payload(world), format='json')

    assert response.status_code == 403, response.data
    assert not GymClass.objects.filter(class_template=world['template']).exists()


def test_teacher_cannot_resolve_another_teachers_projection(world, make_user):
    other = make_user('other-projected-teacher', organization=world['org'], role='teacher')

    response = _client(other).post(_url(), _payload(world), format='json')

    assert response.status_code == 404, response.data
    assert not GymClass.objects.filter(class_template=world['template']).exists()


@pytest.mark.django_db(transaction=True)
def test_concurrent_resolution_creates_one_instance(world):
    barrier = Barrier(2)

    def resolve(_):
        close_old_connections()
        try:
            from django.contrib.auth import get_user_model

            teacher = get_user_model().objects.get(pk=world['teacher'].id)
            client = _client(teacher)
            barrier.wait(timeout=5)
            response = client.post(_url(), _payload(world), format='json')
            return response.status_code, response.json()
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(resolve, range(2)))

    assert sorted(code for code, _ in results) == [200, 201]
    ids = {body['gym_class']['id'] for _, body in results}
    assert len(ids) == 1
    assert GymClass.objects.filter(class_template=world['template']).count() == 1
