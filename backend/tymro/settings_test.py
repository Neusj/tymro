"""Settings para la suite de tests.

Fija las variables de entorno necesarias ANTES de importar la base, de modo que
``settings.py`` mantenga intacto el fail-hard de SECRET_KEY en producción mientras
los tests corren con valores controlados.
"""
import os

os.environ.setdefault('SECRET_KEY', 'test-secret-key-not-for-prod')
os.environ.setdefault('DJANGO_DEBUG', 'True')
os.environ.setdefault('EMAIL_BACKEND', 'django.core.mail.backends.locmem.EmailBackend')

from .settings import *  # noqa: F401,F403,E402
