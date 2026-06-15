"""E2E Flujo de marcha blanca — operación de un día de clases.

Profesor con alumnos inscritos -> el profe pasa lista (check-in) por la API ->
cierra la clase -> el sistema calcula el pago al profesor -> el profe lo ve.

La RESERVA del alumno se valida en el E2E de Feature 3; aquí los alumnos ya están
inscritos (precondición por ORM) y el foco es el ciclo check-in -> cierre -> pago.
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from core.models import Attendance, GymClass, TeacherPaymentRule
from .conftest import auth
from . import factories as f

pytestmark = pytest.mark.django_db(transaction=True)

PER_STUDENT = TeacherPaymentRule.PaymentType.PER_STUDENT


def test_full_day_teacher_checkin_and_payment(api, login, make_organization, make_user):
    org = make_organization('Gimnasio Marcha Blanca')
    make_user('mb_admin', organization=org, role='gym_admin')
    teacher = make_user('mb_teach', organization=org, role='teacher', first_name='Ana')
    s1 = make_user('mb_s1', organization=org, role='student', email='s1@gym.cl')
    s2 = make_user('mb_s2', organization=org, role='student', email='s2@gym.cl')
    branch = f.make_branch(org)

    # Clase EN CURSO (empezó hace 30', termina en 30').
    start = timezone.now() - timedelta(minutes=30)
    gym_class = f.make_class(
        org, branch, teacher, start=start, end=start + timedelta(hours=1),
        status=GymClass.Status.SCHEDULED, name='Clase del día',
    )
    # Alumnos con plan, ya inscritos (reserva validada en Feature 3).
    for s in (s1, s2):
        f.give_student_plan(s, f.make_plan(org, 8, 32000), 8, 32000)
        f.enroll(gym_class, s)

    # Pago por alumno presente: $3.000 c/u.
    f.make_rule(org, PER_STUDENT, amount=3000, teacher=teacher)

    teacher_token = login('mb_teach')

    # 1) El profe ve su clase en curso.
    listed = api.get('/api/classes/', headers=auth(teacher_token))
    assert listed.status == 200, listed.text()
    rows = listed.json()
    rows = rows if isinstance(rows, list) else rows.get('results', [])
    this_class = next(r for r in rows if r['id'] == gym_class.id)
    assert this_class['status'] == GymClass.Status.IN_PROGRESS, this_class

    # 2) Check-in: pasa lista marcando a ambos presentes.
    checkin = api.post(
        f'/api/classes/{gym_class.id}/attendance/',
        data={'attendances': [
            {'student_id': s1.id, 'status': Attendance.Status.PRESENT},
            {'student_id': s2.id, 'status': Attendance.Status.PRESENT},
        ]},
        headers=auth(teacher_token),
    )
    assert checkin.status == 200, checkin.text()
    present = [a for a in checkin.json() if a['status'] == Attendance.Status.PRESENT]
    assert len(present) == 2

    # 3) Cierra la clase -> dispara cálculo de pago.
    close = api.post(
        f'/api/classes/{gym_class.id}/complete-early/',
        data={'comment': 'Cierre de la clase del día'},
        headers=auth(teacher_token),
    )
    assert close.status == 200, close.text()
    assert close.json()['status'] == GymClass.Status.COMPLETED_EARLY

    # 4) El profe ve su pago: 2 presentes x $3.000 = $6.000.
    payments = api.get('/api/teacher-payments/my/', headers=auth(teacher_token))
    assert payments.status == 200, payments.text()
    records = payments.json()
    assert len(records) == 1, records
    assert records[0]['total_students'] == 2
    assert float(records[0]['total_amount']) == 6000.0
