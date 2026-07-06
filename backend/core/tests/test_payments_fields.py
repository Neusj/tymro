import pytest
from django.db import connection

from core.fields import EncryptedTextField, generate_encryption_key


@pytest.fixture
def enc_key(settings):
    key = generate_encryption_key()
    settings.PAYMENTS_ENCRYPTION_KEY = key
    return key


def test_generate_key_is_usable():
    key = generate_encryption_key()
    assert isinstance(key, str) and len(key) > 0


def test_roundtrip_encrypt_decrypt(enc_key):
    field = EncryptedTextField()
    stored = field.get_prep_value('super-secret-token')
    assert stored != 'super-secret-token'          # cifrado en DB
    back = field.from_db_value(stored, None, connection)
    assert back == 'super-secret-token'            # descifrado al leer


def test_none_passes_through(enc_key):
    field = EncryptedTextField()
    assert field.get_prep_value(None) is None
    assert field.from_db_value(None, None, connection) is None


def test_supports_key_rotation(settings):
    old = generate_encryption_key()
    new = generate_encryption_key()
    settings.PAYMENTS_ENCRYPTION_KEY = old
    stored = EncryptedTextField().get_prep_value('x')
    # Rotamos: nueva clave primero, vieja como secundaria.
    settings.PAYMENTS_ENCRYPTION_KEY = f'{new},{old}'
    assert EncryptedTextField().from_db_value(stored, None, connection) == 'x'
