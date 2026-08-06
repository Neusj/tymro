import pytest
import requests
import responses

from core.services.providers.base import PaymentProviderError, RevocationUnverified
from core.services.providers.mercadopago import MercadoPagoProvider


def _provider():
    return MercadoPagoProvider(client_id='APP123', client_secret='SEC', webhook_secret='WH')


class _Resp:
    def __init__(self, status_code, text='{}'):
        self.status_code = status_code
        self.text = text


def _mock_delete(monkeypatch, resp):
    """Reemplaza requests.delete y devuelve la lista de llamadas capturadas.

    `resp` puede ser un `_Resp` o una excepción a levantar (para el fallo de red)."""
    calls = []

    def _fake_delete(url, **kwargs):
        calls.append({'url': url, **kwargs})
        if isinstance(resp, Exception):
            raise resp
        return resp

    monkeypatch.setattr(requests, 'delete', _fake_delete)
    return calls


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
    responses.add(responses.POST, MercadoPagoProvider.TOKEN_URL,
                  json={'error': 'invalid_grant'}, status=400)
    with pytest.raises(PaymentProviderError):
        _provider().exchange_code(code='BAD', redirect_uri='https://app.tymroapp.com/cb')


# --- revoke (P3.3) -----------------------------------------------------------------------
# Endpoint del host de Mercado LIBRE (comparte identidad/apps con MP): MP no publica
# revocación para el OAuth de split payments. Ver el bloque de comentarios en
# providers/mercadopago.py. Best-effort por diseño.

def test_revoke_hits_the_ml_endpoint_with_bearer_header(monkeypatch):
    calls = _mock_delete(monkeypatch, _Resp(200, '{"msg":"Autorización eliminada"}'))

    assert _provider().revoke(access_token='AT-SECRET', provider_user_id='987654') is None

    assert len(calls) == 1
    # user_id del vendedor + app_id = client_id de la app de TYMRO.
    assert calls[0]['url'] == 'https://api.mercadolibre.com/users/987654/applications/APP123'
    assert calls[0]['headers']['Authorization'] == 'Bearer AT-SECRET'
    assert calls[0]['headers']['Accept'] == 'application/json'
    assert calls[0]['timeout']
    # El token NO viaja en la URL (quedaría en logs de proxies/servidores): solo en el header.
    assert 'AT-SECRET' not in calls[0]['url']


def test_revoke_treats_404_as_already_revoked(monkeypatch):
    # 404 SÍ es éxito: es EVIDENCIA de que esa autorización ya no existe (la quitaron desde
    # el panel de MP, o una desconexión anterior la eliminó). Levantar solo generaría ruido
    # sobre una desconexión que en realidad está completa.
    _mock_delete(monkeypatch, _Resp(404, '{"message":"not found"}'))

    assert _provider().revoke(access_token='AT-SECRET', provider_user_id='987654') is None


def test_revoke_401_is_unverified_not_success(monkeypatch):
    """401 NO es éxito: es una revocación NO CONFIRMADA.

    El 401 solo prueba "no pude autenticar con este token", que es también lo que responde
    un token simplemente CADUCADO —caso común: los access_token de MP viven hasta 180 días
    y solo se refrescan al cobrar, así que un gym que conectó y nunca vendió tiene el token
    vencido en la fila— mientras la autorización sigue perfectamente viva bajo nuestro
    app_id. Contarlo como éxito dejaba justo el residuo que la revocación existe para matar.
    """
    _mock_delete(monkeypatch, _Resp(401, '{"message":"invalid_token"}'))

    with pytest.raises(RevocationUnverified) as exc_info:
        _provider().revoke(access_token='AT-SECRET', provider_user_id='987654')

    assert '401' in str(exc_info.value)
    assert 'AT-SECRET' not in str(exc_info.value)


def test_revoke_server_error_raises_without_leaking_the_token(monkeypatch):
    _mock_delete(monkeypatch, _Resp(500, '{"message":"internal error"}'))

    with pytest.raises(PaymentProviderError) as exc_info:
        _provider().revoke(access_token='AT-SECRET', provider_user_id='987654')

    assert '500' in str(exc_info.value)
    assert 'internal error' in str(exc_info.value)   # el body de MP sí es seguro de incluir
    assert 'AT-SECRET' not in str(exc_info.value)    # el token, jamás
    # Un 5xx es un fallo, NO un "no pude autenticar": el caller los loguea distinto.
    assert not isinstance(exc_info.value, RevocationUnverified)


def test_revoke_network_failure_becomes_provider_error(monkeypatch):
    _mock_delete(monkeypatch, requests.ConnectionError('dns'))

    with pytest.raises(PaymentProviderError) as exc_info:
        _provider().revoke(access_token='AT-SECRET', provider_user_id='987654')

    assert 'AT-SECRET' not in str(exc_info.value)
