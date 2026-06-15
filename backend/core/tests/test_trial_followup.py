"""Feature 2: marca is_trial en la reserva pública + comando de email de seguimiento.

El comando ``send_trial_followups`` envía un email a los alumnos que ASISTIERON
a una clase de prueba, una vez transcurrido el delay configurado. Es idempotente
(marca ``Attendance.trial_followup_sent_at``) y respeta multitenancy.
"""
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from core.models import (
    Attendance,
    Branch,
    Enrollment,
    GymClass,
    TrialFollowupConfiguration,
)

pytestmark = pytest.mark.django_db

PASSWORD = 'Passw0rd2026'


def _login(api_client, username):
    token = api_client.post(
        '/api/login/', {'username': username, 'password': PASSWORD}, format='json'
    ).json()['token']
    api_client.credentials(HTTP_AUTHORIZATION=f'Token {token}')


@pytest.fixture
def setup(make_organization, make_user):
    org = make_organization('Gimnasio Uno')
    teacher = make_user('teach', organization=org, role='teacher')
    student = make_user(
        'maria', organization=org, role='student',
        email='maria@gym.cl', first_name='Maria', email_verified=True,
    )
    branch = Branch.objects.create(organization=org, name='Sede')
    return {'org': org, 'teacher': teacher, 'student': student, 'branch': branch}


def _completed_class(setup, ended_minutes_ago=90):
    end = timezone.now() - timedelta(minutes=ended_minutes_ago)
    start = end - timedelta(hours=1)
    return GymClass.objects.create(
        organization=setup['org'], branch=setup['branch'], teacher=setup['teacher'],
        name='Yoga prueba', start_datetime=start, end_datetime=end,
        status=GymClass.Status.COMPLETED,
    )


def _trial_attendee(gym_class, student, attendance_status=Attendance.Status.PRESENT):
    Enrollment.objects.create(gym_class=gym_class, student=student, status='active', is_trial=True)
    Attendance.objects.create(gym_class=gym_class, student=student, status=attendance_status)


def _config(org, **kwargs):
    return TrialFollowupConfiguration.objects.create(organization=org, **kwargs)


# ---- F2A: marca is_trial en la reserva pública ----

def test_public_trial_booking_marks_is_trial(api_client, setup):
    start = timezone.now() + timedelta(days=1)
    gym_class = GymClass.objects.create(
        organization=setup['org'], branch=setup['branch'], teacher=setup['teacher'],
        name='Clase prueba', start_datetime=start, end_datetime=start + timedelta(hours=1),
        capacity=10, status=GymClass.Status.SCHEDULED, is_trial_eligible=True,
    )
    _login(api_client, 'maria')
    resp = api_client.post('/api/public/trial/book/', {'gym_class': gym_class.id}, format='json')
    assert resp.status_code == 201, resp.content

    enrollment = Enrollment.objects.get(gym_class=gym_class, student=setup['student'])
    assert enrollment.is_trial is True


# ---- F2B: comando de seguimiento ----

def test_command_sends_followup_to_present_trial_attendee(setup, mailoutbox):
    gym_class = _completed_class(setup, ended_minutes_ago=90)
    _trial_attendee(gym_class, setup['student'])
    _config(setup['org'], minutes_after_class_end=30)

    call_command('send_trial_followups')

    assert len(mailoutbox) == 1
    assert mailoutbox[0].to == ['maria@gym.cl']
    attendance = Attendance.objects.get(gym_class=gym_class, student=setup['student'])
    assert attendance.trial_followup_sent_at is not None


def test_command_is_idempotent(setup, mailoutbox):
    gym_class = _completed_class(setup)
    _trial_attendee(gym_class, setup['student'])
    _config(setup['org'], minutes_after_class_end=30)

    call_command('send_trial_followups')
    call_command('send_trial_followups')
    assert len(mailoutbox) == 1  # no se reenvía


def test_command_respects_delay(setup, mailoutbox):
    gym_class = _completed_class(setup, ended_minutes_ago=20)
    _trial_attendee(gym_class, setup['student'])
    config = _config(setup['org'], minutes_after_class_end=30)

    call_command('send_trial_followups')
    assert len(mailoutbox) == 0  # solo pasaron 20 min de 30

    config.minutes_after_class_end = 15
    config.save(update_fields=['minutes_after_class_end'])
    call_command('send_trial_followups')
    assert len(mailoutbox) == 1  # ahora 20 > 15


def test_command_skips_disabled_config(setup, mailoutbox):
    gym_class = _completed_class(setup)
    _trial_attendee(gym_class, setup['student'])
    _config(setup['org'], is_active=False, minutes_after_class_end=30)

    call_command('send_trial_followups')
    assert len(mailoutbox) == 0


def test_command_skips_absent_trial_students(setup, mailoutbox):
    gym_class = _completed_class(setup)
    _trial_attendee(gym_class, setup['student'], attendance_status=Attendance.Status.ABSENT)
    _config(setup['org'], minutes_after_class_end=30)

    call_command('send_trial_followups')
    assert len(mailoutbox) == 0  # no asistió -> no se le agradece


def test_command_dry_run_does_not_send_or_mark(setup, mailoutbox):
    gym_class = _completed_class(setup)
    _trial_attendee(gym_class, setup['student'])
    _config(setup['org'], minutes_after_class_end=30)

    call_command('send_trial_followups', dry_run=True)
    assert len(mailoutbox) == 0
    attendance = Attendance.objects.get(gym_class=gym_class, student=setup['student'])
    assert attendance.trial_followup_sent_at is None


def test_command_substitutes_template_variables(setup, mailoutbox):
    gym_class = _completed_class(setup)
    _trial_attendee(gym_class, setup['student'])
    _config(
        setup['org'], minutes_after_class_end=30,
        email_subject='Hola {student_name}',
        email_body='Gracias por venir a {class_name} en {org_name}. {signup_link}',
    )

    call_command('send_trial_followups')
    assert len(mailoutbox) == 1
    assert mailoutbox[0].subject == 'Hola Maria'
    body = mailoutbox[0].body
    assert 'Yoga prueba' in body
    assert 'Gimnasio Uno' in body
    assert '{' not in body  # todas las variables fueron reemplazadas


def test_command_is_multitenant_scoped(setup, mailoutbox, make_organization, make_user):
    # Org del fixture: cumple todo.
    gym_class = _completed_class(setup)
    _trial_attendee(gym_class, setup['student'])
    _config(setup['org'], minutes_after_class_end=30)

    # Otra organización que también cumple todo.
    org_b = make_organization('Gimnasio Dos')
    teacher_b = make_user('teach_b', organization=org_b, role='teacher')
    student_b = make_user('pedro', organization=org_b, role='student', email='pedro@gym.cl')
    branch_b = Branch.objects.create(organization=org_b, name='Sede B')
    end = timezone.now() - timedelta(minutes=90)
    class_b = GymClass.objects.create(
        organization=org_b, branch=branch_b, teacher=teacher_b, name='Box',
        start_datetime=end - timedelta(hours=1), end_datetime=end, status=GymClass.Status.COMPLETED,
    )
    _trial_attendee(class_b, student_b)
    _config(org_b, minutes_after_class_end=30)

    call_command('send_trial_followups', org_id=setup['org'].id)

    recipients = [r for m in mailoutbox for r in m.to]
    assert recipients == ['maria@gym.cl']  # solo la org pedida, sin fuga cross-tenant
