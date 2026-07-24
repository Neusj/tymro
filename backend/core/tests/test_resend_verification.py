"""Reenvío del correo de confirmación de email (#26).

Cubre: un alumno autenticado SIN verificar recibe UN correo con el link a SU
subdominio y un token válido; si YA está verificado es no-op (0 correos, 200);
anónimo → 401/403; rate-limit del scope 'resend_verification'; y la integración
reenvío → verify → email_verified True.

El throttle se limpia entre tests con la fixture autouse `_clear_throttle_cache`
(conftest.py).
"""
import re

import pytest

pytestmark = pytest.mark.django_db

RESEND_URL = '/api/resend-verification/'
VERIFY_URL = '/api/public/verify-email/'


def _extract_uid_token(email_body):
    match = re.search(r'verify-email\?uid=([^&\s]+)&token=([^\s]+)', email_body)
    assert match, f'No se encontró el link de verificación en:\n{email_body}'
    return match.group(1), match.group(2)


def _prod_settings(settings):
    settings.BASE_DOMAIN = 'tymroapp.com'
    settings.FRONTEND_URL = 'https://tymroapp.com'


def test_resend_sends_one_email_with_subdomain_link(
    api_client, make_organization, make_user, mailoutbox, settings
):
    _prod_settings(settings)
    org = make_organization(name='Cross')  # subdomain 'org-1'
    student = make_user('stu', organization=org, role='student', email='stu@example.com')
    assert student.email_verified is False

    api_client.force_authenticate(user=student)
    resp = api_client.post(RESEND_URL, {}, format='json')

    assert resp.status_code == 200, resp.content
    assert len(mailoutbox) == 1
    assert mailoutbox[0].to == ['stu@example.com']
    # Link a SU subdominio (no al apex ni a otra org).
    assert 'https://org-1.tymroapp.com/verify-email?uid=' in mailoutbox[0].body


def test_resend_email_token_is_valid_and_verifies_account(
    api_client, make_organization, make_user, mailoutbox
):
    org = make_organization(name='Cross')
    student = make_user('stu', organization=org, role='student', email='stu@example.com')

    api_client.force_authenticate(user=student)
    resp = api_client.post(RESEND_URL, {}, format='json')
    assert resp.status_code == 200, resp.content
    assert len(mailoutbox) == 1

    uid, token = _extract_uid_token(mailoutbox[0].body)

    # El endpoint de verificación es público (AllowAny): faithful al flujo real,
    # limpiamos la auth antes de confirmar.
    api_client.force_authenticate(user=None)
    verify = api_client.post(VERIFY_URL, {'uid': uid, 'token': token}, format='json')
    assert verify.status_code == 200, verify.content

    student.refresh_from_db()
    assert student.email_verified is True


def test_resend_is_noop_when_already_verified(
    api_client, make_organization, make_user, mailoutbox
):
    org = make_organization(name='Cross')
    student = make_user('stu', organization=org, role='student', email='stu@example.com')
    student.email_verified = True
    student.save(update_fields=['email_verified'])

    api_client.force_authenticate(user=student)
    resp = api_client.post(RESEND_URL, {}, format='json')

    assert resp.status_code == 200, resp.content
    assert len(mailoutbox) == 0


def test_resend_requires_authentication(api_client):
    resp = api_client.post(RESEND_URL, {}, format='json')
    assert resp.status_code in (401, 403)


def test_resend_is_rate_limited(api_client, make_organization, make_user):
    # El scope 'resend_verification' está configurado a 3/hour en settings.
    org = make_organization(name='Cross')
    student = make_user('stu', organization=org, role='student', email='stu@example.com')
    api_client.force_authenticate(user=student)

    statuses = [
        api_client.post(RESEND_URL, {}, format='json').status_code for _ in range(4)
    ]
    assert statuses[:3] == [200, 200, 200]
    assert statuses[3] == 429
