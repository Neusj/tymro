import responses

from core.services.providers.mercadopago import MercadoPagoProvider


def _provider():
    return MercadoPagoProvider(client_id='APP123', client_secret='SEC', webhook_secret='WH')


def test_authorization_url_has_required_params():
    url = _provider().get_authorization_url(state='ST', redirect_uri='https://app.tymroapp.com/cb')
    assert url.startswith('https://auth.mercadopago.cl/authorization')
    assert 'client_id=APP123' in url
    assert 'response_type=code' in url
    assert 'state=ST' in url
    assert 'redirect_uri=' in url


@responses.activate
def test_exchange_code_parses_tokens():
    responses.add(responses.POST, MercadoPagoProvider.TOKEN_URL, json={
        'access_token': 'AT', 'refresh_token': 'RT', 'expires_in': 15552000,
        'user_id': 987654, 'public_key': 'PK', 'scope': 'offline_access read write',
    }, status=200)
    tokens = _provider().exchange_code(code='CODE', redirect_uri='https://app.tymroapp.com/cb')
    assert tokens.access_token == 'AT'
    assert tokens.refresh_token == 'RT'
    assert tokens.expires_in == 15552000
    assert tokens.provider_user_id == '987654'
    assert tokens.public_key == 'PK'


@responses.activate
def test_refresh_tokens_parses_tokens():
    responses.add(responses.POST, MercadoPagoProvider.TOKEN_URL, json={
        'access_token': 'AT2', 'refresh_token': 'RT2', 'expires_in': 15552000,
        'user_id': 987654, 'public_key': 'PK',
    }, status=200)
    tokens = _provider().refresh_tokens(refresh_token='RT')
    assert tokens.access_token == 'AT2'
    assert tokens.refresh_token == 'RT2'


@responses.activate
def test_exchange_code_error_raises():
    from core.services.providers.base import PaymentProviderError
    responses.add(responses.POST, MercadoPagoProvider.TOKEN_URL,
                  json={'error': 'invalid_grant'}, status=400)
    import pytest
    with pytest.raises(PaymentProviderError):
        _provider().exchange_code(code='BAD', redirect_uri='https://app.tymroapp.com/cb')
