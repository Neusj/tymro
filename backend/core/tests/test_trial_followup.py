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


# ---- F2C: endpoints GET/PUT de configuración (panel gym_admin) ----
#
# Contrato externo: is_enabled / delay_minutes / email_subject / email_body.
# El modelo guarda is_active / minutes_after_class_end (mapeo vía serializer source).

def _config_url(org):
    return f'/api/organizations/{org.id}/trial-followup-config/'


def test_get_config_autocreates_with_defaults(api_client, make_organization, make_user):
    org = make_organization('Gym A')
    make_user('admin_a', organization=org, role='gym_admin')
    _login(api_client, 'admin_a')

    resp = api_client.get(_config_url(org))

    assert resp.status_code == 200, resp.content
    data = resp.json()
    assert data['is_enabled'] is True
    assert data['delay_minutes'] == 30
    assert data['email_subject'] == TrialFollowupConfiguration.DEFAULT_SUBJECT
    assert data['email_body'] == TrialFollowupConfiguration.DEFAULT_BODY
    # GET sin config previa la crea con los defaults del modelo.
    assert TrialFollowupConfiguration.objects.filter(organization=org).count() == 1


def test_gym_admin_updates_own_config(api_client, make_organization, make_user):
    org = make_organization('Gym A')
    make_user('admin_a', organization=org, role='gym_admin')
    _login(api_client, 'admin_a')

    payload = {
        'is_enabled': False,
        'delay_minutes': 90,
        'email_subject': 'Asunto {org_name}',
        'email_body': 'Hola {student_name}, gracias por {class_name}.',
    }
    resp = api_client.put(_config_url(org), payload, format='json')

    assert resp.status_code == 200, resp.content
    data = resp.json()
    assert data['is_enabled'] is False
    assert data['delay_minutes'] == 90

    config = TrialFollowupConfiguration.objects.get(organization=org)
    assert config.is_active is False
    assert config.minutes_after_class_end == 90
    assert config.email_subject == 'Asunto {org_name}'
    assert config.email_body == 'Hola {student_name}, gracias por {class_name}.'


def test_gym_admin_cannot_access_other_org_config(api_client, make_organization, make_user):
    org_a = make_organization('Gym A')
    org_b = make_organization('Gym B')
    make_user('admin_a', organization=org_a, role='gym_admin')
    _login(api_client, 'admin_a')

    resp_get = api_client.get(_config_url(org_b))
    resp_put = api_client.put(_config_url(org_b), {'delay_minutes': 5}, format='json')

    assert resp_get.status_code == 403, resp_get.content
    assert resp_put.status_code == 403, resp_put.content
    # El rechazo ocurre antes del get_or_create: no se crea config para la org ajena.
    assert not TrialFollowupConfiguration.objects.filter(organization=org_b).exists()


def test_superadmin_can_manage_any_org_config(api_client, make_organization, make_user):
    org = make_organization('Gym A')
    make_user('root', organization=None, role='superadmin')
    _login(api_client, 'root')

    resp_get = api_client.get(_config_url(org))
    resp_put = api_client.put(_config_url(org), {'delay_minutes': 45}, format='json')

    assert resp_get.status_code == 200, resp_get.content
    assert resp_put.status_code == 200, resp_put.content
    assert TrialFollowupConfiguration.objects.get(organization=org).minutes_after_class_end == 45


def test_unauthenticated_cannot_access_config(api_client, make_organization):
    org = make_organization('Gym A')

    resp = api_client.get(_config_url(org))

    assert resp.status_code == 401, resp.content


def test_invalid_config_payload_is_rejected(api_client, make_organization, make_user):
    org = make_organization('Gym A')
    make_user('admin_a', organization=org, role='gym_admin')
    _login(api_client, 'admin_a')
    url = _config_url(org)

    resp_negative = api_client.put(url, {'delay_minutes': -5}, format='json')
    resp_empty_subject = api_client.put(url, {'email_subject': ''}, format='json')

    assert resp_negative.status_code == 400, resp_negative.content
    assert 'delay_minutes' in resp_negative.json()
    assert resp_empty_subject.status_code == 400, resp_empty_subject.content
    assert 'email_subject' in resp_empty_subject.json()


@pytest.mark.parametrize('role', ['manager', 'monitor', 'teacher', 'student'])
def test_non_admin_org_roles_cannot_access_config(role, api_client, make_organization, make_user):
    # Blinda la matriz de roles: solo superadmin/gym_admin gestionan la config de
    # organización. Si alguien cambiara el check a uno que admita manager, esto falla.
    org = make_organization('Gym A')
    make_user('member', organization=org, role=role)
    _login(api_client, 'member')
    url = _config_url(org)

    resp_get = api_client.get(url)
    resp_put = api_client.put(url, {'delay_minutes': 5}, format='json')

    assert resp_get.status_code == 403, resp_get.content
    assert resp_put.status_code == 403, resp_put.content
    assert not TrialFollowupConfiguration.objects.filter(organization=org).exists()
