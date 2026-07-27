"""Tests del flujo de autenticación endurecido para producción.

Cubre: login, /me, expiración de token, rotación, reset (request/confirm) y throttling.
"""
import importlib
import os
from datetime import timedelta

import pytest
from django.contrib.auth.tokens import default_token_generator
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework.authtoken.models import Token

from tymro import settings as settings_module

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


# --- role_display (etiqueta legible del rol) --------------------------------

# Contrato de etiquetas legibles (español), única fuente: los choices de
# CustomUser.Role vía get_role_display(). Si cambian los labels del modelo, este
# dict debe cambiar conscientemente.
ROLE_DISPLAY_LABELS = {
    'superadmin': 'Superadministrador',
    'gym_admin': 'Administrador',
    'manager': 'Gerente',
    'monitor': 'Monitor',
    'teacher': 'Profesor',
    'student': 'Alumno',
}


@pytest.mark.parametrize('role,label', list(ROLE_DISPLAY_LABELS.items()))
def test_me_exposes_readable_role_display(api_client, make_user, make_organization, role, label):
    org = None if role == 'superadmin' else make_organization()
    actor = make_user(f'u_{role}', organization=org, role=role)
    api_client.force_authenticate(user=actor)

    body = api_client.get(ME_URL).json()

    # `role` sigue siendo la key interna; `role_display` es la etiqueta legible.
    assert body['role'] == role
    assert body['role_display'] == label
    # Nunca filtra la key interna como display.
    assert body['role_display'] != body['role']


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


# --- Throttling detrás del proxy ---------------------------------------------
#
# Topología en producción (Railway): browser -> edge -> gunicorn. La imagen de
# prod es single-service (Dockerfile.prod): gunicorn sirve la API y el SPA con
# WhiteNoise, no hay nginx en el camino. O sea UN solo proxy de confianza.
#
# El edge apendea la IP real al final del X-Forwarded-For, así que la petición
# llega como "<lo que mandó el cliente>, <IP real>". Todo lo que está a la
# izquierda de la última entrada lo controla quien llama.

CLIENT_IP = '203.0.113.7'         # IP real del cliente (la escribe el edge)
OTHER_CLIENT_IP = '203.0.113.44'  # otro cliente distinto, mismo edge
VICTIM_IP = '203.0.113.99'        # cliente al que un atacante quiere bloquear
EDGE_IP = '198.51.100.1'          # quien abre la conexión TCP contra gunicorn


def _forwarded_for(*addresses):
    return ', '.join(addresses)


def test_login_throttle_counts_real_ip_and_ignores_spoofed_forwarded_for(api_client, user, settings):
    """Variar el XFF que controla el cliente NO debe abrir cupo nuevo de throttle.

    Sin esto, el 5/min de login es papel mojado: basta mandar un X-Forwarded-For
    distinto en cada intento para que cada uno caiga en una clave de caché nueva
    y la fuerza bruta quede sin barrera.
    """
    rate = settings.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']['login']
    limit = int(rate.split('/')[0])

    codes = []
    for attempt in range(limit + 1):
        # Lo único que cambia entre intentos es el prefijo falsificado; la IP
        # real que apendea el edge es siempre la misma.
        spoofed = f'10.0.0.{attempt}'
        codes.append(
            api_client.post(
                LOGIN_URL,
                {'email': 'alice@example.com', 'password': 'wrong'},
                format='json',
                HTTP_X_FORWARDED_FOR=_forwarded_for(spoofed, CLIENT_IP),
                REMOTE_ADDR=EDGE_IP,
            ).status_code
        )

    assert codes[-1] == 429
    assert codes[:limit].count(429) == 0


def test_login_throttle_does_not_lump_different_clients_behind_the_same_edge(api_client, user, settings):
    """Contar por una entrada demasiado a la derecha (la IP del edge, común a
    todos) metería a TODOS los usuarios en la misma clave: cinco intentos
    fallidos de cualquiera dejarían sin login a la plataforma entera. Este test
    fija el límite como algo por-cliente, no global."""
    rate = settings.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']['login']
    limit = int(rate.split('/')[0])

    for _ in range(limit + 1):
        api_client.post(
            LOGIN_URL,
            {'email': 'alice@example.com', 'password': 'wrong'},
            format='json',
            HTTP_X_FORWARDED_FOR=CLIENT_IP,
            REMOTE_ADDR=EDGE_IP,
        )

    # Otro cliente, mismo edge: su cupo está intacto.
    resp = api_client.post(
        LOGIN_URL,
        {'email': 'alice@example.com', 'password': PASSWORD},
        format='json',
        HTTP_X_FORWARDED_FOR=OTHER_CLIENT_IP,
        REMOTE_ADDR=EDGE_IP,
    )
    assert resp.status_code == 200
    assert resp.json()['token']


def test_login_throttle_cannot_be_poisoned_by_naming_someone_elses_ip(api_client, user, settings):
    """Un atacante no puede gastarle el cupo a otro nombrando su IP en el XFF.

    Si la clave saliera de una entrada que manda el cliente, bastaría con poner
    la IP de la víctima para dejarla sin login (5/min) o sin recuperar la
    contraseña (3/hora). La entrada elegida tiene que ser la que escribe el edge.
    """
    rate = settings.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']['login']
    limit = int(rate.split('/')[0])

    # El atacante agota el límite declarando la IP de la víctima.
    for _ in range(limit + 1):
        api_client.post(
            LOGIN_URL,
            {'email': 'alice@example.com', 'password': 'wrong'},
            format='json',
            HTTP_X_FORWARDED_FOR=_forwarded_for(VICTIM_IP, CLIENT_IP),
            REMOTE_ADDR=EDGE_IP,
        )

    # La víctima, desde su IP real, entra sin problemas.
    resp = api_client.post(
        LOGIN_URL,
        {'email': 'alice@example.com', 'password': PASSWORD},
        format='json',
        HTTP_X_FORWARDED_FOR=VICTIM_IP,
        REMOTE_ADDR=EDGE_IP,
    )
    assert resp.status_code == 200
    assert resp.json()['token']


def _reload_settings(num_proxies):
    """Re-ejecuta settings.py con (o sin) NUM_PROXIES en el entorno.

    Recarga el módulo crudo, no `django.conf.settings`, que conserva su propia
    copia del dict: el resto de la suite no se entera.
    """
    if num_proxies is None:
        os.environ.pop('NUM_PROXIES', None)
    else:
        os.environ['NUM_PROXIES'] = num_proxies
    return importlib.reload(settings_module)


@pytest.fixture
def settings_module_restored():
    yield
    os.environ.pop('NUM_PROXIES', None)
    importlib.reload(settings_module)


def test_num_proxies_default_is_one_for_railway(settings_module_restored):
    """Sin la variable de entorno —el caso de Railway— el valor tiene que ser 1.

    Es el default que protege producción: un solo proxy que apendea (el edge).
    Si alguien sube el default, prod pasa a contar por una IP común a todos.
    """
    assert _reload_settings(None).REST_FRAMEWORK['NUM_PROXIES'] == 1


def test_num_proxies_can_be_raised_for_stacks_with_nginx(settings_module_restored):
    """El stack docker-compose mete nginx delante del backend (2 hops), así que
    necesita otro valor. Con el número hardcodeado ese stack contaría por la IP
    del contenedor de nginx/cloudflared —la misma para todos— y cinco intentos
    fallidos de cualquiera dejarían sin login a todo el stack.
    """
    assert _reload_settings('2').REST_FRAMEWORK['NUM_PROXIES'] == 2


def test_login_behind_the_edge_still_authenticates(api_client, user):
    """Smoke del camino feliz detrás del edge: 200 + token. No discrimina el valor
    de NUM_PROXIES (pasa con cualquiera); está para que un error de config que
    rompa el login de plano no se cuele."""
    resp = api_client.post(
        LOGIN_URL,
        {'email': 'alice@example.com', 'password': PASSWORD},
        format='json',
        HTTP_X_FORWARDED_FOR=CLIENT_IP,
        REMOTE_ADDR=EDGE_IP,
    )

    assert resp.status_code == 200
    assert resp.json()['token']
    assert resp.json()['user']['email'] == 'alice@example.com'


def test_reset_request_returns_200_even_if_email_send_fails(api_client, user, monkeypatch):
    # Simula caída del proveedor de correo: el envío lanza.
    def _boom(*args, **kwargs):
        raise RuntimeError('email provider down')

    monkeypatch.setattr('core.views.send_mail', _boom)

    resp = api_client.post(RESET_URL, {'email': 'alice@example.com'}, format='json')

    # Anti-enumeración: responde 200 igual, sin propagar el 500.
    assert resp.status_code == 200
