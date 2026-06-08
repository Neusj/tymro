"""Aislamiento multi-tenant: un gym_admin de la Organización A no puede ver ni
tocar datos de la Organización B en los endpoints principales (clases, reservas,
usuarios, planes)."""
from datetime import timedelta

import pytest
from django.utils import timezone

from core.models import Branch, Enrollment, GymClass, Plan

pytestmark = pytest.mark.django_db

PASSWORD = 'Passw0rd2026'


def _ids(payload):
    """El backend no tiene paginación por defecto, pero toleramos ambas formas."""
    items = payload['results'] if isinstance(payload, dict) and 'results' in payload else payload
    return {item['id'] for item in items}


def _build_org(make_organization, make_user, suffix):
    org = make_organization(name=f'Gym {suffix}')
    admin = make_user(f'admin_{suffix}', organization=org, role='gym_admin')
    student = make_user(f'student_{suffix}', organization=org, role='student')
    branch = Branch.objects.create(organization=org, name=f'Sede {suffix}')
    start = timezone.now() + timedelta(days=1)
    gym_class = GymClass.objects.create(
        organization=org,
        branch=branch,
        name=f'Clase {suffix}',
        start_datetime=start,
        end_datetime=start + timedelta(hours=1),
    )
    enrollment = Enrollment.objects.create(gym_class=gym_class, student=student, status='active')
    plan = Plan.objects.create(
        organization=org,
        name=f'Plan {suffix}',
        plan_type=Plan.PlanType.MONTHLY,
        total_classes=8,
        duration_days=30,
        price=30000,
    )
    return {
        'org': org,
        'admin': admin,
        'student': student,
        'gym_class': gym_class,
        'enrollment': enrollment,
        'plan': plan,
    }


def test_gym_admin_cannot_access_other_organization_data(api_client, make_organization, make_user):
    a = _build_org(make_organization, make_user, 'A')
    b = _build_org(make_organization, make_user, 'B')

    # Autenticamos como admin de la Organización A.
    token = api_client.post(
        '/api/login/', {'username': 'admin_A', 'password': PASSWORD}, format='json'
    ).json()['token']
    api_client.credentials(HTTP_AUTHORIZATION=f'Token {token}')

    # --- Clases -------------------------------------------------------------
    classes = api_client.get('/api/classes/')
    assert classes.status_code == 200
    class_ids = _ids(classes.json())
    assert a['gym_class'].id in class_ids
    assert b['gym_class'].id not in class_ids
    # Detalle de una clase ajena -> 404 (no la encuentra en su queryset).
    assert api_client.get(f"/api/classes/{b['gym_class'].id}/").status_code == 404
    # Escritura sobre una clase ajena -> 404 (no puede tocarla).
    assert api_client.patch(
        f"/api/classes/{b['gym_class'].id}/", {'name': 'hackeada'}, format='json'
    ).status_code == 404
    b['gym_class'].refresh_from_db()
    assert b['gym_class'].name == 'Clase B'

    # --- Reservas (enrollments) --------------------------------------------
    enrollments = api_client.get('/api/enrollments/')
    assert enrollments.status_code == 200
    enrollment_ids = _ids(enrollments.json())
    assert a['enrollment'].id in enrollment_ids
    assert b['enrollment'].id not in enrollment_ids
    assert api_client.get(f"/api/enrollments/{b['enrollment'].id}/").status_code == 404

    # --- Usuarios -----------------------------------------------------------
    users = api_client.get('/api/users/')
    assert users.status_code == 200
    user_ids = _ids(users.json())
    assert a['admin'].id in user_ids
    assert b['admin'].id not in user_ids
    assert b['student'].id not in user_ids
    # Detalle y escritura de un usuario ajeno -> 404.
    assert api_client.get(f"/api/users/{b['student'].id}/").status_code == 404
    assert api_client.patch(
        f"/api/users/{b['student'].id}/", {'phone': '999'}, format='json'
    ).status_code == 404

    # --- Planes -------------------------------------------------------------
    plans = api_client.get('/api/plans/')
    assert plans.status_code == 200
    plan_ids = _ids(plans.json())
    assert a['plan'].id in plan_ids
    assert b['plan'].id not in plan_ids
    assert api_client.get(f"/api/plans/{b['plan'].id}/").status_code == 404
    assert api_client.patch(
        f"/api/plans/{b['plan'].id}/", {'name': 'hackeado'}, format='json'
    ).status_code == 404
    b['plan'].refresh_from_db()
    assert b['plan'].name == 'Plan B'
