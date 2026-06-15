"""E2E Feature 2 — Reserva de prueba marca is_trial + email de seguimiento.

Parte A (HTTP, server real): un alumno con email verificado agenda su clase de
prueba por /api/public/trial/book/ y la inscripción queda marcada is_trial=True
(verificado por la API que consume el frontend).

Parte B (comando real + backend de email): tras una clase de prueba COMPLETADA a
la que el alumno ASISTIÓ, el comando ``send_trial_followups`` dispara el email.
"""
from datetime import timedelta

import pytest
from django.core.management import call_command

from core.models import Attendance, GymClass
from .conftest import auth
from . import factories as f

pytestmark = pytest.mark.django_db(transaction=True)


def test_public_trial_booking_marks_is_trial(api, login, make_organization, make_user):
    org = make_organization('Gimnasio Trial')
    make_user('trial_admin', organization=org, role='gym_admin')
    teacher = make_user('trial_teach', organization=org, role='teacher')
    student = make_user(
        'trial_maria', organization=org, role='student',
        email='maria@gym.cl', first_name='Maria', email_verified=True,
    )
    branch = f.make_branch(org)
    start = f.now() + timedelta(days=1)
    gym_class = f.make_class(
        org, branch, teacher, start=start, end=start + timedelta(hours=1),
        status=GymClass.Status.SCHEDULED, is_trial_eligible=True, name='Clase Gratis',
    )

    # El alumno agenda su prueba por la API pública real.
    student_token = login('trial_maria')
    book = api.post('/api/public/trial/book/', data={'gym_class': gym_class.id},
                    headers=auth(student_token))
    assert book.status == 201, book.text()

    # La inscripción quedó marcada is_trial (lo que ve el admin por la API).
    admin_token = login('trial_admin')
    enrollments = api.get(f'/api/enrollments/?gym_class={gym_class.id}',
                          headers=auth(admin_token))
    assert enrollments.status == 200, enrollments.text()
    rows = enrollments.json()
    rows = rows if isinstance(rows, list) else rows.get('results', [])
    mine = [r for r in rows if r['student'] == student.id]
    assert len(mine) == 1
    assert mine[0]['is_trial'] is True


def test_trial_followup_email_fires_for_attended_trial(make_organization, make_user, mailoutbox):
    org = make_organization('Gimnasio Email')
    teacher = make_user('email_teach', organization=org, role='teacher', first_name='Ana')
    student = make_user(
        'email_maria', organization=org, role='student',
        email='maria@gym.cl', first_name='Maria', email_verified=True,
    )
    branch = f.make_branch(org)

    end = f.now() - timedelta(minutes=90)
    gym_class = f.make_class(
        org, branch, teacher, start=end - timedelta(hours=1), end=end,
        status=GymClass.Status.COMPLETED, name='Yoga prueba',
    )
    f.enroll(gym_class, student, is_trial=True)
    f.mark_attendance(gym_class, student, Attendance.Status.PRESENT)
    f.trial_config(
        org, minutes_after_class_end=30,
        email_subject='Hola {student_name}',
        email_body='Gracias por venir a {class_name} en {org_name}. {signup_link}',
    )

    call_command('send_trial_followups')

    assert len(mailoutbox) == 1
    assert mailoutbox[0].to == ['maria@gym.cl']
    assert mailoutbox[0].subject == 'Hola Maria'
    assert 'Yoga prueba' in mailoutbox[0].body
    assert '{' not in mailoutbox[0].body  # variables sustituidas

    # Idempotente: una segunda corrida no reenvía.
    call_command('send_trial_followups')
    assert len(mailoutbox) == 1
