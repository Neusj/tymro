"""Materializacion de una clase proyectada desde el ADMIN (no desde la reserva del alumno).

El alumno ya tenia su camino on-demand (`POST /api/enrollments/` con `class_template_id` +
`date`, ver test_virtual_reservation_materialization.py). El admin no tenia ninguno: el modal
de inscripcion exige PK real, asi que una fila `virtual:` quedaba inoperable.

Este endpoint es esa mitad faltante. La regla de rango es UNA SOLA y es la misma que obedece
el alumno: `Organization.max_reservation_window_days`. No se agrega un bypass para el admin.
"""
from datetime import time, timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import Branch, ClassTemplate, GymClass

pytestmark = pytest.mark.django_db


def _endpoint(template_id):
    return f'/api/class-templates/{template_id}/materialize/'


@pytest.fixture
def world(make_organization, make_user):
    org = make_organization('Org Admin Virtual')
    org.max_reservation_window_days = 7
    org.save(update_fields=['max_reservation_window_days'])
    return {
        'org': org,
        'admin': make_user('admin-virtual', organization=org, role='gym_admin'),
        'teacher': make_user('teacher-admin-virtual', organization=org, role='teacher'),
        'student': make_user('student-admin-virtual', organization=org, role='student'),
        'branch': Branch.objects.create(organization=org, name='Sede'),
    }


def _template(world, target_date, *, is_active=True):
    return ClassTemplate.objects.create(
        organization=world['org'],
        branch=world['branch'],
        teacher=world['teacher'],
        name='Serie proyectada',
        weekday=target_date.weekday(),
        start_time=time(10, 0),
        end_time=time(11, 0),
        capacity=10,
        start_date=target_date - timedelta(days=30),
        is_active=is_active,
    )


def _client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _tomorrow():
    return timezone.localdate() + timedelta(days=1)


def test_gym_admin_materializes_a_projected_class(world):
    target_date = _tomorrow()
    template = _template(world, target_date)
    # Premisa del bug: la clase NO existe todavia, por eso el listado la proyecta.
    assert not GymClass.objects.filter(class_template=template).exists()

    response = _client(world['admin']).post(
        _endpoint(template.id), {'date': target_date.isoformat()}, format='json'
    )

    assert response.status_code == 201, response.data
    gym_class = GymClass.objects.get(class_template=template)
    assert response.data['id'] == gym_class.id
    assert gym_class.organization_id == world['org'].id
    assert gym_class.capacity == template.capacity
    assert timezone.localtime(gym_class.start_datetime).date() == target_date


def test_materializing_twice_returns_the_same_class(world):
    target_date = _tomorrow()
    template = _template(world, target_date)
    client = _client(world['admin'])
    payload = {'date': target_date.isoformat()}

    first = client.post(_endpoint(template.id), payload, format='json')
    second = client.post(_endpoint(template.id), payload, format='json')

    assert first.status_code == 201, first.data
    assert second.status_code == 200, second.data
    assert first.data['id'] == second.data['id']
    assert GymClass.objects.filter(class_template=template, start_datetime__date=target_date).count() == 1


def test_admin_cannot_materialize_beyond_the_reservation_window(world):
    # La org configuro 7 dias; el dia 30 queda fuera del rango programado.
    target_date = timezone.localdate() + timedelta(days=30)
    template = _template(world, target_date)

    response = _client(world['admin']).post(
        _endpoint(template.id), {'date': target_date.isoformat()}, format='json'
    )

    assert response.status_code == 400, response.data
    assert not GymClass.objects.filter(class_template=template).exists()


def test_admin_cannot_materialize_a_past_date(world):
    target_date = timezone.localdate() - timedelta(days=1)
    template = _template(world, target_date)

    response = _client(world['admin']).post(
        _endpoint(template.id), {'date': target_date.isoformat()}, format='json'
    )

    assert response.status_code == 400, response.data
    assert not GymClass.objects.filter(class_template=template).exists()


def test_date_must_match_the_template_weekday(world):
    target_date = _tomorrow()
    template = _template(world, target_date)
    other_day = target_date + timedelta(days=1)

    response = _client(world['admin']).post(
        _endpoint(template.id), {'date': other_day.isoformat()}, format='json'
    )

    assert response.status_code == 400, response.data
    assert not GymClass.objects.filter(class_template=template).exists()


def test_inactive_template_cannot_be_materialized(world):
    target_date = _tomorrow()
    template = _template(world, target_date, is_active=False)

    response = _client(world['admin']).post(
        _endpoint(template.id), {'date': target_date.isoformat()}, format='json'
    )

    assert response.status_code == 400, response.data
    assert not GymClass.objects.filter(class_template=template).exists()


def test_admin_of_another_organization_gets_404(world, make_organization, make_user):
    target_date = _tomorrow()
    template = _template(world, target_date)
    other_org = make_organization('Org Ajena')
    intruder = make_user('admin-ajeno', organization=other_org, role='gym_admin')

    response = _client(intruder).post(
        _endpoint(template.id), {'date': target_date.isoformat()}, format='json'
    )

    # 404 y no 403: un 403 confirmaria que esa plantilla existe en otro tenant.
    assert response.status_code == 404, response.data
    assert not GymClass.objects.filter(class_template=template).exists()


@pytest.mark.parametrize('actor_key', ['teacher', 'student'])
def test_non_admin_roles_cannot_materialize(world, actor_key):
    target_date = _tomorrow()
    template = _template(world, target_date)

    response = _client(world[actor_key]).post(
        _endpoint(template.id), {'date': target_date.isoformat()}, format='json'
    )

    # 403 y no 404: son de la MISMA org y la plantilla ya les es visible en sus listados,
    # asi que ocultarla no protegeria nada. El 404 se reserva para el cruce entre orgs.
    assert response.status_code == 403, response.data
    assert not GymClass.objects.filter(class_template=template).exists()
