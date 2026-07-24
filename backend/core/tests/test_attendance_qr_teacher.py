"""#12 — El profesor asignado a una clase puede EXPONER el QR de asistencia,
SIEMPRE scoped por org (nunca el QR de otra org, nunca de una clase ajena).

El QR es org-scoped (`_build_qr_token(org.id)`); el `class_id` se usa solo para
AUTORIZAR al profesor (debe dictar esa clase, y ser de su propia org). El gym_admin
sigue generando el QR sin necesidad de indicar una clase.
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from core.models import Branch, GymClass

pytestmark = pytest.mark.django_db

CURRENT_URL = '/api/attendance-qr/current/'


@pytest.fixture
def qr_teacher_setup(make_organization, make_user):
    org_a = make_organization(name='Org A')
    org_b = make_organization(name='Org B')
    admin_a = make_user('admin_a', organization=org_a, role='gym_admin')
    teacher_a = make_user('teacher_a', organization=org_a, role='teacher')
    teacher_a2 = make_user('teacher_a2', organization=org_a, role='teacher')
    teacher_b = make_user('teacher_b', organization=org_b, role='teacher')
    branch = Branch.objects.create(organization=org_a, name='Sede')
    start = timezone.now() + timedelta(hours=1)
    gym_class = GymClass.objects.create(
        organization=org_a,
        branch=branch,
        teacher=teacher_a,
        name='Clase de A',
        start_datetime=start,
        end_datetime=start + timedelta(hours=1),
    )
    return {
        'org_a': org_a,
        'org_b': org_b,
        'admin_a': admin_a,
        'teacher_a': teacher_a,
        'teacher_a2': teacher_a2,
        'teacher_b': teacher_b,
        'gym_class': gym_class,
    }


def test_assigned_teacher_can_expose_qr(api_client, qr_teacher_setup):
    s = qr_teacher_setup
    api_client.force_authenticate(user=s['teacher_a'])
    resp = api_client.get(CURRENT_URL, {'class_id': s['gym_class'].id})
    assert resp.status_code == 200, resp.content
    assert resp.json()['token']


def test_unassigned_teacher_same_org_gets_403(api_client, qr_teacher_setup):
    s = qr_teacher_setup
    api_client.force_authenticate(user=s['teacher_a2'])
    # Mismo org, pero NO dicta esa clase -> nunca la clase ajena.
    resp = api_client.get(CURRENT_URL, {'class_id': s['gym_class'].id})
    assert resp.status_code == 403


def test_teacher_of_other_org_gets_403(api_client, qr_teacher_setup):
    s = qr_teacher_setup
    api_client.force_authenticate(user=s['teacher_b'])
    # Profe de OTRA org apuntando al id de una clase de org A -> 403 (cross-tenant).
    resp = api_client.get(CURRENT_URL, {'class_id': s['gym_class'].id})
    assert resp.status_code == 403


def test_teacher_without_class_id_gets_403(api_client, qr_teacher_setup):
    s = qr_teacher_setup
    api_client.force_authenticate(user=s['teacher_a'])
    # Sin clase indicada no se puede exponer el QR (evita QR sin contexto de clase).
    resp = api_client.get(CURRENT_URL)
    assert resp.status_code == 403


def test_teacher_with_non_numeric_class_id_gets_403_not_500(api_client, qr_teacher_setup):
    # Input malformado (class_id no numérico) debe rechazarse limpio, no reventar en 500.
    s = qr_teacher_setup
    api_client.force_authenticate(user=s['teacher_a'])
    resp = api_client.get(CURRENT_URL, {'class_id': 'abc'})
    assert resp.status_code == 403


def test_gym_admin_still_can_expose_qr(api_client, qr_teacher_setup):
    s = qr_teacher_setup
    api_client.force_authenticate(user=s['admin_a'])
    resp = api_client.get(CURRENT_URL)  # sin class_id, como hoy
    assert resp.status_code == 200, resp.content
    assert resp.json()['token']
