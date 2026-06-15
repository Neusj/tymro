"""E2E Feature 4 — Suspensión de clase: no aparece al alumno; se reactiva.

Camino real por HTTP contra el server vivo:
  admin suspende -> el alumno inscrito ya NO ve la clase (ni en 'mis clases' ni en
  el listado general) -> admin reactiva -> el alumno la vuelve a ver.
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from core.models import GymClass
from .conftest import auth
from . import factories as f

pytestmark = pytest.mark.django_db(transaction=True)


def _ids(resp):
    rows = resp.json()
    rows = rows if isinstance(rows, list) else rows.get('results', [])
    return {r['id'] for r in rows}


def test_suspended_class_hidden_then_reactivated(api, login, make_organization, make_user):
    org = make_organization('Gimnasio Suspender')
    make_user('sus_admin', organization=org, role='gym_admin')
    teacher = make_user('sus_teach', organization=org, role='teacher')
    student = make_user('sus_alu', organization=org, role='student', email='alu@gym.cl')
    branch = f.make_branch(org)

    start = timezone.now() + timedelta(days=1)
    gym_class = f.make_class(
        org, branch, teacher, start=start, end=start + timedelta(hours=1),
        status=GymClass.Status.SCHEDULED, name='Clase Suspendible',
    )
    f.enroll(gym_class, student)

    admin_token = login('sus_admin')
    student_token = login('sus_alu')

    # Visible para el alumno antes de suspender.
    before = api.get('/api/classes/?mine=1', headers=auth(student_token))
    assert before.status == 200, before.text()
    assert gym_class.id in _ids(before)

    # Admin suspende.
    suspend = api.post(
        f'/api/classes/{gym_class.id}/suspend/',
        data={'suspend_reason': 'Profesor enfermo', 'reactivation_expected_date': '2026-07-01'},
        headers=auth(admin_token),
    )
    assert suspend.status == 200, suspend.text()
    assert suspend.json()['status'] == GymClass.Status.SUSPENDED

    # El alumno ya no la ve (ni en 'mine' ni en el listado general).
    after_mine = api.get('/api/classes/?mine=1', headers=auth(student_token))
    assert gym_class.id not in _ids(after_mine)
    after_all = api.get('/api/classes/', headers=auth(student_token))
    assert gym_class.id not in _ids(after_all)

    # Admin reactiva.
    reactivate = api.post(f'/api/classes/{gym_class.id}/reactivate/', data={},
                          headers=auth(admin_token))
    assert reactivate.status == 200, reactivate.text()
    assert reactivate.json()['status'] == GymClass.Status.SCHEDULED

    # Vuelve a ser visible para el alumno.
    again = api.get('/api/classes/?mine=1', headers=auth(student_token))
    assert gym_class.id in _ids(again)


def test_student_cannot_suspend_class(api, login, make_organization, make_user):
    org = make_organization('Gimnasio Suspender2')
    teacher = make_user('sus2_teach', organization=org, role='teacher')
    student = make_user('sus2_alu', organization=org, role='student')
    branch = f.make_branch(org)
    start = timezone.now() + timedelta(days=1)
    gym_class = f.make_class(
        org, branch, teacher, start=start, end=start + timedelta(hours=1),
        status=GymClass.Status.SCHEDULED,
    )

    resp = api.post(f'/api/classes/{gym_class.id}/suspend/', data={},
                    headers=auth(login('sus2_alu')))
    assert resp.status == 403, resp.text()
