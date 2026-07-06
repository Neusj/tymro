"""Campo de modelo cifrado en reposo con Fernet (para tokens OAuth de pagos).

La clave viene de settings.PAYMENTS_ENCRYPTION_KEY. Soporta rotación: varias
claves separadas por coma; la primera cifra, todas descifran (MultiFernet).
"""
from cryptography.fernet import Fernet, MultiFernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import models


def generate_encryption_key() -> str:
    return Fernet.generate_key().decode()


def _fernet() -> MultiFernet:
    raw = (settings.PAYMENTS_ENCRYPTION_KEY or '').strip()
    if not raw:
        raise ImproperlyConfigured('PAYMENTS_ENCRYPTION_KEY no configurada.')
    keys = [Fernet(k.strip().encode()) for k in raw.split(',') if k.strip()]
    if not keys:
        raise ImproperlyConfigured('PAYMENTS_ENCRYPTION_KEY vacía o inválida.')
    return MultiFernet(keys)


class EncryptedTextField(models.TextField):
    """TextField cuyo valor se cifra antes de guardarse y se descifra al leerse."""

    def get_prep_value(self, value):
        if value is None:
            return None
        token = _fernet().encrypt(str(value).encode())
        return token.decode()

    def from_db_value(self, value, expression, connection):
        if value is None:
            return None
        return _fernet().decrypt(value.encode()).decode()
