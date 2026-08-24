import json
import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError, models, transaction
from django.utils import timezone

from core.models import PushNotification, PushPreference, PushSubscription

logger = logging.getLogger(__name__)
User = get_user_model()


try:
    from pywebpush import WebPushException, webpush
except ImportError:  # pragma: no cover - dependency absence is handled at runtime.
    WebPushException = None
    webpush = None


def get_or_create_push_preference(user):
    if not user or not user.is_authenticated or not user.organization_id:
        return None
    preference, _ = PushPreference.objects.get_or_create(
        user=user,
        defaults={
            'organization_id': user.organization_id,
        },
    )
    if preference.organization_id != user.organization_id:
        preference.organization_id = user.organization_id
        preference.push_enabled = False
        preference.prompt_status = PushPreference.PromptStatus.UNDECIDED
        preference.save(update_fields=['organization', 'push_enabled', 'prompt_status', 'updated_at'])
    return preference


def web_push_is_configured():
    return bool(
        webpush
        and settings.WEB_PUSH_VAPID_PUBLIC_KEY
        and settings.WEB_PUSH_VAPID_PRIVATE_KEY
        and settings.WEB_PUSH_VAPID_SUBJECT
    )


def _webpush(subscription, payload):
    return webpush(
        subscription_info=subscription.webpush_payload,
        data=json.dumps(payload),
        vapid_private_key=settings.WEB_PUSH_VAPID_PRIVATE_KEY,
        vapid_claims={'sub': settings.WEB_PUSH_VAPID_SUBJECT},
    )


def _is_invalid_subscription_error(exc):
    response = getattr(exc, 'response', None)
    status_code = getattr(response, 'status_code', None)
    return status_code in {404, 410}


def _mark_preference_enabled(user):
    preference = get_or_create_push_preference(user)
    if not preference:
        return None
    preference.push_enabled = True
    preference.prompt_status = PushPreference.PromptStatus.ENABLED
    preference.save(update_fields=['push_enabled', 'prompt_status', 'updated_at'])
    return preference


def register_push_subscription(user, *, endpoint, p256dh, auth, user_agent=''):
    if not user.organization_id:
        raise ValueError('El usuario no pertenece a una organizacion.')

    endpoint = str(endpoint or '').strip()
    p256dh = str(p256dh or '').strip()
    auth = str(auth or '').strip()
    if not endpoint or not p256dh or not auth:
        raise ValueError('La suscripcion push esta incompleta.')

    existing = PushSubscription.objects.filter(endpoint=endpoint).first()
    if existing and existing.user_id != user.id:
        raise ValueError('Esta suscripcion ya pertenece a otro usuario.')

    subscription, _ = PushSubscription.objects.update_or_create(
        endpoint=endpoint,
        defaults={
            'user': user,
            'organization_id': user.organization_id,
            'p256dh': p256dh,
            'auth': auth,
            'user_agent': str(user_agent or '')[:1000],
            'is_active': True,
            'deactivated_at': None,
            'last_error': '',
        },
    )
    _mark_preference_enabled(user)
    return subscription


def deactivate_push_subscription(user, *, endpoint):
    subscription = PushSubscription.objects.filter(
        user=user,
        organization_id=user.organization_id,
        endpoint=str(endpoint or '').strip(),
    ).first()
    if not subscription:
        return False
    subscription.deactivate('Desactivada por el usuario.')
    if not PushSubscription.objects.filter(user=user, is_active=True).exists():
        preference = get_or_create_push_preference(user)
        if preference:
            preference.push_enabled = False
            preference.save(update_fields=['push_enabled', 'updated_at'])
    return True


def set_push_preference(user, *, push_enabled=None, prompt_status=None):
    preference = get_or_create_push_preference(user)
    if not preference:
        raise ValueError('El usuario no pertenece a una organizacion.')
    update_fields = ['updated_at']
    if push_enabled is not None:
        preference.push_enabled = bool(push_enabled)
        update_fields.append('push_enabled')
    if prompt_status is not None:
        valid = {choice for choice, _label in PushPreference.PromptStatus.choices}
        if prompt_status not in valid:
            raise ValueError('Estado de permiso push invalido.')
        preference.prompt_status = prompt_status
        update_fields.append('prompt_status')
    preference.save(update_fields=update_fields)
    return preference


def send_push_notification(user, title, body, data=None, *, organization=None, event_type='generic', dedupe_key=''):
    if not user or not user.organization_id:
        return None
    organization_id = organization.id if organization is not None else user.organization_id
    if organization_id != user.organization_id:
        raise ValueError('La organizacion del push no coincide con la del usuario.')

    data = data or {}
    dedupe_key = str(dedupe_key or f'{event_type}:{timezone.now().timestamp()}')[:160]

    try:
        with transaction.atomic():
            notification, created = PushNotification.objects.get_or_create(
                organization_id=organization_id,
                user=user,
                event_type=event_type,
                dedupe_key=dedupe_key,
                defaults={
                    'title': title,
                    'body': body,
                    'data': data,
                },
            )
    except IntegrityError:
        created = False
        notification = PushNotification.objects.get(
            organization_id=organization_id,
            user=user,
            event_type=event_type,
            dedupe_key=dedupe_key,
        )
    if not created:
        return notification

    preference = get_or_create_push_preference(user)
    if not preference or not preference.push_enabled:
        notification.status = PushNotification.Status.SKIPPED
        notification.error = 'Push desactivado para el usuario.'
        notification.save(update_fields=['status', 'error', 'updated_at'])
        return notification

    subscriptions = list(PushSubscription.objects.filter(
        user=user,
        organization_id=organization_id,
        is_active=True,
    ))
    if not subscriptions:
        notification.status = PushNotification.Status.SKIPPED
        notification.error = 'El usuario no tiene suscripciones push activas.'
        notification.save(update_fields=['status', 'error', 'updated_at'])
        return notification

    payload = {
        'title': title,
        'body': body,
        'data': data,
    }
    if not web_push_is_configured():
        notification.status = PushNotification.Status.FAILED
        notification.error = 'Web Push no esta configurado.'
        notification.save(update_fields=['status', 'error', 'updated_at'])
        return notification

    sent_count = 0
    errors = []
    for subscription in subscriptions:
        try:
            _webpush(subscription, payload)
            sent_count += 1
        except Exception as exc:  # pywebpush raises provider-specific exceptions.
            if WebPushException and isinstance(exc, WebPushException) and _is_invalid_subscription_error(exc):
                subscription.deactivate(f'Suscripcion invalida: {exc}')
            else:
                errors.append(str(exc))
                logger.warning('No se pudo enviar push a subscription %s: %s', subscription.id, exc)

    notification.sent_count = sent_count
    if sent_count:
        notification.status = PushNotification.Status.SENT
        notification.sent_at = timezone.now()
        notification.error = ''
    else:
        notification.status = PushNotification.Status.FAILED
        notification.error = '; '.join(errors)[:1000] or 'No se pudo enviar a ninguna suscripcion.'
    notification.save(update_fields=['status', 'sent_count', 'sent_at', 'error', 'updated_at'])
    return notification


def notify_class_cancelled(gym_class, students):
    date_text = timezone.localtime(gym_class.start_datetime).strftime('%d/%m/%Y')
    time_text = timezone.localtime(gym_class.start_datetime).strftime('%H:%M')
    body = f'Tu clase de {gym_class.name} del {date_text} a las {time_text} fue cancelada.'
    comment = str(gym_class.closure_comment or '').strip()
    if comment:
        body = f'{body} Motivo: {comment}'
    data = {
        'type': 'class_cancelled',
        'class_id': gym_class.id,
        'class_name': gym_class.name,
        'date': gym_class.start_datetime.date().isoformat(),
        'time': time_text,
        'url': '/student/classes/reservations',
    }
    for student in students:
        if student.organization_id != gym_class.organization_id:
            continue
        send_push_notification(
            student,
            'Clase cancelada',
            body,
            data,
            organization=gym_class.organization,
            event_type='class_cancelled',
            dedupe_key=f'class:{gym_class.id}',
        )


def _profile_reminder_message(user):
    missing_rut = not bool(user.rut)
    missing_email = not bool(user.email_verified)
    if missing_rut and missing_email:
        return 'Te queda pendiente verificar tu correo y completar tu RUT.'
    if missing_rut:
        return 'Te queda pendiente completar tu RUT.'
    if missing_email:
        return 'Te queda pendiente verificar tu correo.'
    return ''


def send_profile_completion_reminders(*, organization=None, today=None):
    today = today or timezone.localdate()
    queryset = User.objects.filter(is_active=True, organization__isnull=False)
    if organization is not None:
        queryset = queryset.filter(organization=organization)
    queryset = queryset.filter(
        models.Q(rut__isnull=True) | models.Q(rut='') | models.Q(email_verified=False)
    )

    sent = 0
    skipped = 0
    for user in queryset.select_related('organization'):
        message = _profile_reminder_message(user)
        if not message:
            skipped += 1
            continue
        preference = get_or_create_push_preference(user)
        if preference.last_profile_reminder_sent_on == today:
            skipped += 1
            continue
        notification = send_push_notification(
            user,
            'Completa tus datos',
            message,
            {
                'type': 'profile_completion',
                'url': '/profile',
            },
            organization=user.organization,
            event_type='profile_completion',
            dedupe_key=f'profile:{today.isoformat()}',
        )
        if notification and notification.status == PushNotification.Status.SENT:
            preference.last_profile_reminder_sent_on = today
            preference.save(update_fields=['last_profile_reminder_sent_on', 'updated_at'])
            sent += 1
        else:
            skipped += 1
    return {'sent': sent, 'skipped': skipped}
