from django.conf import settings


def test_payment_settings_exist_with_defaults():
    assert hasattr(settings, 'PAYMENTS_PROVIDER')
    assert settings.PAYMENTS_PROVIDER == 'mercadopago'
    # En test/dev no se exige el resto, pero los atributos deben existir (default '').
    for name in ('PAYMENTS_ENCRYPTION_KEY', 'MP_CLIENT_ID', 'MP_CLIENT_SECRET',
                 'MP_WEBHOOK_SECRET', 'MP_OAUTH_REDIRECT_URI', 'PAYMENTS_APEX_BASE_URL'):
        assert hasattr(settings, name)
