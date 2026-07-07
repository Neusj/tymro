"""Guardas del transporte de correo (Resend vía django-anymail).

No verifican envío real (settings_test usa locmem); verifican que la dependencia
esté instalada y que la config de Anymail/remitente exista y no arrastre Gmail.
"""
from django.conf import settings


def test_resend_backend_is_importable():
    from anymail.backends.resend import EmailBackend

    assert EmailBackend is not None


def test_anymail_configured_with_resend_key():
    assert 'RESEND_API_KEY' in settings.ANYMAIL


def test_default_from_is_not_gmail():
    assert settings.DEFAULT_FROM_EMAIL
    assert 'gmail' not in settings.DEFAULT_FROM_EMAIL.lower()
