"""Tests del flujo de autenticación endurecido para producción.

Cubre: login, /me, expiración de token, rotación, reset (request/confirm) y throttling.
"""
from datetime import timedelta

import pytest
from django.contrib.auth.tokens import default_token_generator
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework.authtoken.models import Token

pytestmark = pytest.mark.django_db

LOGIN_URL = '/api/login/'
ME_URL = '/api/me/'
RESET_URL = '/api/password-reset/'
RESET_CONFIRM_URL = '/api/password-reset/confirm/'

PASSWORD = 'Passw0rd2026'


@pytest.fixture
def user(make_user):
    return make_user('alice', role='gym_admin', email='alice@example.com', password=PASSWORD)


# --- Login -----------------------------------------------------------------

def test_login_success_returns_token_and_user_shape(api_client, user):
    resp = api_client.post(LOGIN_URL, {'email': 'alice@example.com', 'password': PASSWORD}, format='json')

    assert resp.status_code == 200
    body = resp.json()
    # La forma de la respuesta NO debe cambiar: el frontend depende de estas claves.
    assert {'token', 'user', 'role', 'organization', 'branch'} <= set(body.keys())
    assert body['token']
    assert body['role'] == 'gym_admin'
    assert Token.objects.filter(user=user, key=body['token']).exists()


def test_login_invalid_credentials_returns_400(api_client, user):
    resp = api_client.post(LOGIN_URL, {'email': 'alice@example.com', 'password': 'wrong'}, format='json')
    assert resp.status_code == 400


def test_login_missing_fields_returns_400(api_client):
    resp = api_client.post(LOGIN_URL, {'email': '', 'password': ''}, format='json')
    assert resp.status_code == 400


# --- /me --------------------------------------------------------------------

def test_me_with_fresh_token_returns_200(api_client, user):
    token = api_client.post(LOGIN_URL, {'email': 'alice@example.com', 'password': PASSWORD}, format='json').json()['token']
    api_client.credentials(HTTP_AUTHORIZATION=f'Token {token}')
    resp = api_client.get(ME_URL)
    assert resp.status_code == 200
    assert resp.json()['email'] == 'alice@example.com'


def test_me_without_token_returns_401(api_client, user):
    resp = api_client.get(ME_URL)
    assert resp.status_code == 401


# --- Rotación y expiración --------------------------------------------------

def test_relogin_rotates_token_and_invalidates_previous(api_client, user):
    first = api_client.post(LOGIN_URL, {'email': 'alice@example.com', 'password': PASSWORD}, format='json').json()['token']
    second = api_client.post(LOGIN_URL, {'email': 'alice@example.com', 'password': PASSWORD}, format='json').json()['token']

    assert first != second, 'el token debe rotar en cada login'

    # El token anterior ya no sirve.
    api_client.credentials(HTTP_AUTHORIZATION=f'Token {first}')
    assert api_client.get(ME_URL).status_code == 401

    # El nuevo sí.
    api_client.credentials(HTTP_AUTHORIZATION=f'Token {second}')
    assert api_client.get(ME_URL).status_code == 200


def test_expired_token_is_rejected(api_client, user, settings):
    token_key = api_client.post(LOGIN_URL, {'email': 'alice@example.com', 'password': PASSWORD}, format='json').json()['token']

    token = Token.objects.get(key=token_key)
    token.created = timezone.now() - timedelta(hours=settings.TOKEN_TTL_HOURS + 1)
    token.save(update_fields=['created'])

    api_client.credentials(HTTP_AUTHORIZATION=f'Token {token_key}')
    assert api_client.get(ME_URL).status_code == 401


def test_token_within_ttl_still_valid(api_client, user, settings):
    token_key = api_client.post(LOGIN_URL, {'email': 'alice@example.com', 'password': PASSWORD}, format='json').json()['token']

    token = Token.objects.get(key=token_key)
    token.created = timezone.now() - timedelta(hours=max(settings.TOKEN_TTL_HOURS - 1, 0))
    token.save(update_fields=['created'])

    api_client.credentials(HTTP_AUTHORIZATION=f'Token {token_key}')
    assert api_client.get(ME_URL).status_code == 200


# --- Reset de contraseña ----------------------------------------------------

def test_reset_request_sends_email_only_for_existing_user(api_client, user, mailoutbox):
    assert api_client.post(RESET_URL, {'email': 'alice@example.com'}, format='json').status_code == 200
    assert api_client.post(RESET_URL, {'email': 'nadie@example.com'}, format='json').status_code == 200

    # Anti-enumeración: ambos responden 200, pero solo se envía email al existente.
    assert len(mailoutbox) == 1
    assert mailoutbox[0].to == ['alice@example.com']
    assert 'reset-password?uid=' in mailoutbox[0].body


def test_reset_confirm_sets_new_password(api_client, user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)

    resp = api_client.post(
        RESET_CONFIRM_URL,
        {'uid': uid, 'token': token, 'new_password': 'NuevaClave2026'},
        format='json',
    )
    assert resp.status_code == 200

    user.refresh_from_db()
    assert user.check_password('NuevaClave2026')
    # El login con la nueva clave funciona.
    assert api_client.post(LOGIN_URL, {'email': 'alice@example.com', 'password': 'NuevaClave2026'}, format='json').status_code == 200


def test_reset_confirm_rejects_weak_password(api_client, user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)

    resp = api_client.post(
        RESET_CONFIRM_URL,
        {'uid': uid, 'token': token, 'new_password': '123'},
        format='json',
    )
    assert resp.status_code == 400
    user.refresh_from_db()
    assert not user.check_password('123')


def test_reset_confirm_rejects_invalid_token(api_client, user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    resp = api_client.post(
        RESET_CONFIRM_URL,
        {'uid': uid, 'token': 'token-invalido', 'new_password': 'NuevaClave2026'},
        format='json',
    )
    assert resp.status_code == 400


def test_reset_token_is_single_use(api_client, user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)

    first = api_client.post(
        RESET_CONFIRM_URL,
        {'uid': uid, 'token': token, 'new_password': 'NuevaClave2026'},
        format='json',
    )
    assert first.status_code == 200

    # Reusar el mismo token tras cambiar la clave debe fallar.
    second = api_client.post(
        RESET_CONFIRM_URL,
        {'uid': uid, 'token': token, 'new_password': 'OtraClave2026'},
        format='json',
    )
    assert second.status_code == 400


# --- Throttling -------------------------------------------------------------

def test_login_is_throttled_after_limit(api_client, user, settings):
    # Scope 'login' = 5/min. El 6º intento (aunque sea con credenciales malas) debe dar 429.
    rate = settings.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']['login']
    limit = int(rate.split('/')[0])

    codes = [
        api_client.post(LOGIN_URL, {'email': 'alice@example.com', 'password': 'wrong'}, format='json').status_code
        for _ in range(limit + 1)
    ]
    assert codes[-1] == 429
    assert codes[:limit].count(429) == 0  # los primeros `limit` no se bloquean
