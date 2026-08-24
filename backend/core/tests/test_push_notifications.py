from datetime import timedelta

import pytest
from django.utils import timezone

from core.models import Branch, Enrollment, GymClass, PushNotification, PushPreference, PushSubscription
from core.services import push_notifications
from core.services.push_notifications import (
    notify_class_cancelled,
    register_push_subscription,
    send_profile_completion_reminders,
)

pytestmark = pytest.mark.django_db

PASSWORD = 'Passw0rd2026'


def _login(api_client, user):
    host = {'HTTP_HOST': f'{user.organization.subdomain}.localhost'} if user.organization_id else {}
    token = api_client.post(
        '/api/login/', {'email': user.email, 'password': PASSWORD}, format='json', **host
    ).json()['token']
    api_client.credentials(HTTP_AUTHORIZATION=f'Token {token}')


@pytest.fixture
def world(make_organization, make_user):
    org = make_organization()
    other_org = make_organization()
    admin = make_user('admin-push', organization=org, role='gym_admin')
    teacher = make_user('teacher-push', organization=org, role='teacher')
    student = make_user('student-push', organization=org, role='student', email='student@gym.cl')
    student_2 = make_user('student-push-2', organization=org, role='student', email='student2@gym.cl')
    outsider = make_user('student-other-push', organization=other_org, role='student', email='student@other.cl')
    branch = Branch.objects.create(organization=org, name='Sede')
    start = timezone.now() + timedelta(days=1)
    gym_class = GymClass.objects.create(
        organization=org,
        branch=branch,
        teacher=teacher,
        name='Kickboxing',
        start_datetime=start,
        end_datetime=start + timedelta(hours=1),
        capacity=12,
        status=GymClass.Status.SCHEDULED,
    )
    return {
        'org': org,
        'other_org': other_org,
        'admin': admin,
        'teacher': teacher,
        'student': student,
        'student_2': student_2,
        'outsider': outsider,
        'gym_class': gym_class,
    }


@pytest.fixture
def webpush_spy(monkeypatch):
    calls = []
    monkeypatch.setattr(push_notifications, 'web_push_is_configured', lambda: True)
    monkeypatch.setattr(push_notifications, '_webpush', lambda subscription, payload: calls.append((subscription, payload)))
    return calls


def _register(user, suffix='1'):
    return register_push_subscription(
        user,
        endpoint=f'https://push.example/{user.id}/{suffix}',
        p256dh=f'p256dh-{suffix}',
        auth=f'auth-{suffix}',
        user_agent='pytest',
    )


def test_register_subscription_avoids_duplicates_and_allows_multiple_devices(api_client, world):
    _login(api_client, world['student'])

    payload = {'endpoint': 'https://push.example/device-1', 'keys': {'p256dh': 'key-a', 'auth': 'auth-a'}}
    first = api_client.post('/api/push/subscriptions/', payload, format='json')
    assert first.status_code == 201, first.content
    again = api_client.post('/api/push/subscriptions/', payload, format='json')
    assert again.status_code == 201, again.content
    second = api_client.post(
        '/api/push/subscriptions/',
        {'endpoint': 'https://push.example/device-2', 'keys': {'p256dh': 'key-b', 'auth': 'auth-b'}},
        format='json',
    )
    assert second.status_code == 201, second.content

    assert PushSubscription.objects.filter(user=world['student'], is_active=True).count() == 2
    preference = PushPreference.objects.get(user=world['student'])
    assert preference.push_enabled is True
    assert preference.prompt_status == PushPreference.PromptStatus.ENABLED


def test_subscription_endpoint_requires_auth_and_cannot_be_stolen(api_client, world):
    unauth = api_client.post(
        '/api/push/subscriptions/',
        {'endpoint': 'https://push.example/protected', 'keys': {'p256dh': 'key', 'auth': 'auth'}},
        format='json',
    )
    assert unauth.status_code == 401

    _register(world['student'], 'shared')
    _login(api_client, world['student_2'])
    resp = api_client.post(
        '/api/push/subscriptions/',
        {
            'endpoint': f'https://push.example/{world["student"].id}/shared',
            'keys': {'p256dh': 'key', 'auth': 'auth'},
        },
        format='json',
    )
    assert resp.status_code == 400


def test_invalid_provider_subscription_is_deactivated(world, monkeypatch):
    subscription = _register(world['student'])

    class FakeResponse:
        status_code = 410

    class FakeWebPushException(Exception):
        response = FakeResponse()

    def _raise_invalid(_subscription, _payload):
        raise FakeWebPushException('gone')

    monkeypatch.setattr(push_notifications, 'WebPushException', FakeWebPushException)
    monkeypatch.setattr(push_notifications, 'web_push_is_configured', lambda: True)
    monkeypatch.setattr(push_notifications, '_webpush', _raise_invalid)

    push_notifications.send_push_notification(
        world['student'],
        'Titulo',
        'Cuerpo',
        {'type': 'test'},
        organization=world['org'],
        event_type='test',
        dedupe_key='invalid-subscription',
    )

    subscription.refresh_from_db()
    assert subscription.is_active is False
    assert subscription.deactivated_at is not None


def test_cancel_class_pushes_only_affected_enabled_students(api_client, world, webpush_spy):
    _register(world['student'])
    _register(world['outsider'])
    Enrollment.objects.create(gym_class=world['gym_class'], student=world['student'], status='active')
    Enrollment.objects.create(gym_class=world['gym_class'], student=world['student_2'], status='active')

    _login(api_client, world['admin'])
    resp = api_client.post(
        f'/api/classes/{world["gym_class"].id}/cancel/',
        {'comment': 'Sin profesor'},
        format='json',
    )
    assert resp.status_code == 200, resp.content

    sent = PushNotification.objects.filter(event_type='class_cancelled', status=PushNotification.Status.SENT)
    skipped = PushNotification.objects.filter(event_type='class_cancelled', status=PushNotification.Status.SKIPPED)
    assert list(sent.values_list('user_id', flat=True)) == [world['student'].id]
    assert list(skipped.values_list('user_id', flat=True)) == [world['student_2'].id]
    assert not PushNotification.objects.filter(user=world['outsider']).exists()
    assert len(webpush_spy) == 1
    assert 'Kickboxing' in sent.get().body


def test_cancelled_class_push_is_idempotent(world, webpush_spy):
    _register(world['student'])
    Enrollment.objects.create(gym_class=world['gym_class'], student=world['student'], status='active')
    students = [world['student']]

    world['gym_class'].status = GymClass.Status.CANCELLED
    world['gym_class'].closure_comment = 'Clima'
    world['gym_class'].save(update_fields=['status', 'closure_comment', 'updated_at'])

    notify_class_cancelled(world['gym_class'], students)
    notify_class_cancelled(world['gym_class'], students)

    assert PushNotification.objects.filter(event_type='class_cancelled', user=world['student']).count() == 1
    assert len(webpush_spy) == 1


def test_profile_completion_reminder_groups_missing_rut_and_email_once_per_day(world, webpush_spy):
    student = world['student']
    student.rut = None
    student.email_verified = False
    student.save(update_fields=['rut', 'email_verified'])
    _register(student)

    first = send_profile_completion_reminders(today=timezone.localdate())
    second = send_profile_completion_reminders(today=timezone.localdate())

    notification = PushNotification.objects.get(event_type='profile_completion', user=student)
    assert first['sent'] == 1
    assert second['sent'] == 0
    assert 'verificar tu correo y completar tu RUT' in notification.body
    assert len(webpush_spy) == 1


def test_profile_completion_reminder_stops_when_completed(world, webpush_spy):
    student = world['student']
    student.rut = '12345678-5'
    student.email_verified = True
    student.save(update_fields=['rut', 'email_verified'])
    _register(student)

    result = send_profile_completion_reminders(today=timezone.localdate())

    assert result['sent'] == 0
    assert not PushNotification.objects.filter(event_type='profile_completion', user=student).exists()
    assert webpush_spy == []
