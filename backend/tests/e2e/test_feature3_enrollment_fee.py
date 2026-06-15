"""E2E Feature 3 — Matrícula (enrollment fee) bloquea la reserva si está impaga.

Camino real del alumno: POST /api/enrollments/ {gym_class} contra el server vivo.
Con matrícula > 0 impaga -> 400. Tras pagarla -> 201.
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from core.models import GymClass
from .conftest import auth
from . import factories as f

pytestmark = pytest.mark.django_db(transaction=True)


def test_reservation_blocked_until_enrollment_fee_paid(api, login, make_organization, make_user):
    org = make_organization('Gimnasio Matricula')
    teacher = make_user('fee_teach', organization=org, role='teacher')
    student = make_user('fee_alu', organization=org, role='student', email='alu@gym.cl')
    branch = f.make_branch(org)

    start = timezone.now() + timedelta(days=1)
    gym_class = f.make_class(
        org, branch, teacher, start=start, end=start + timedelta(hours=1),
        status=GymClass.Status.SCHEDULED, name='Clase Matricula',
    )
    # Plan activo con clases disponibles pero con matrícula de 50.000 SIN pagar.
    sp = f.give_student_plan(student, f.make_plan(org, 8, 40000), 8, 40000, fee=50000, paid=False)

    student_token = login('fee_alu')

    # 1) Reserva bloqueada por matrícula impaga.
    blocked = api.post('/api/enrollments/', data={'gym_class': gym_class.id},
                       headers=auth(student_token))
    assert blocked.status == 400, blocked.text()
    assert 'matrícula' in blocked.text().lower()

    # 2) Pagada la matrícula, la reserva procede.
    sp.enrollment_fee_paid_at = timezone.now()
    sp.save(update_fields=['enrollment_fee_paid_at', 'updated_at'])

    ok = api.post('/api/enrollments/', data={'gym_class': gym_class.id},
                  headers=auth(student_token))
    assert ok.status == 201, ok.text()
    assert ok.json()['status'] == 'active'


def test_reservation_allowed_when_no_enrollment_fee(api, login, make_organization, make_user):
    org = make_organization('Gimnasio SinMatricula')
    teacher = make_user('nofee_teach', organization=org, role='teacher')
    student = make_user('nofee_alu', organization=org, role='student', email='b@gym.cl')
    branch = f.make_branch(org)

    start = timezone.now() + timedelta(days=1)
    gym_class = f.make_class(
        org, branch, teacher, start=start, end=start + timedelta(hours=1),
        status=GymClass.Status.SCHEDULED, name='Clase SinMatricula',
    )
    f.give_student_plan(student, f.make_plan(org, 8, 40000), 8, 40000, fee=0)

    ok = api.post('/api/enrollments/', data={'gym_class': gym_class.id},
                  headers=auth(login('nofee_alu')))
    assert ok.status == 201, ok.text()
