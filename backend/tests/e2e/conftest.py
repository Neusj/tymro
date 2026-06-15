"""Harness E2E para TYMRO.

Estrategia: levantamos un servidor Django REAL (fixture ``live_server`` de
pytest-django) y lo manejamos por HTTP con el ``APIRequestContext`` de Playwright.
Esto ejercita la pila completa de extremo a extremo —WSGI, middleware,
autenticación por Token, serializers, servicios, señales y el backend de email—
contra exactamente la misma API que consume el frontend React.

No se usa navegador (ni binarios de Playwright): el contexto ``request`` de
Playwright habla HTTP directo, que es lo más estable y reproducible para validar
las 5 features con alta confianza, sin depender de levantar Vite ni de selectores
de UI frágiles.

NOTA sobre la base de datos: la suite corre con SQLite en memoria. ``live_server``
de pytest-django comparte la conexión con el hilo del servidor, de modo que los
datos creados por ORM en el test SON visibles para el servidor. Por seguridad los
tests E2E se marcan ``transaction=True``.

NOTA sobre el event loop: la API *sync* de Playwright mantiene un event loop
asyncio en el hilo principal. El guard de Django (``SynchronousOnlyOperation``)
rechaza el ORM al detectarlo. En este harness el ORM corre sincrónicamente en el
hilo principal (Playwright no toca la DB), así que habilitamos el bypass sólo para
tests con ``DJANGO_ALLOW_ASYNC_UNSAFE`` —es el workaround estándar pytest-playwright
+ Django y es seguro en este contexto de test.
"""
import os
import time

os.environ.setdefault('DJANGO_ALLOW_ASYNC_UNSAFE', '1')

import pytest


PASSWORD = 'Passw0rd2026'


def _warmup(context, attempts=80, gap=0.25):
    """Reintenta una request real (con el mismo cliente Playwright) hasta que el
    servidor responda.

    El ``live_server`` de pytest-django es de SESIÓN: solo la primera request
    puede llegar durante el arranque del hilo del servidor y fallar (ETIMEDOUT /
    ECONNREFUSED en Windows). Calentamos el cliente aquí para que la primera
    request del test ya golpee un servidor+cliente probados.
    """
    last_error = None
    for _ in range(attempts):
        try:
            resp = context.get('/api/health/', timeout=3000)
            if resp.status < 500:
                return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        time.sleep(gap)
    raise AssertionError(f'El live_server no respondió tras el warmup: {last_error}')


@pytest.fixture
def api(live_server, playwright):
    """APIRequestContext de Playwright apuntando al servidor Django vivo.

    Forzamos 127.0.0.1 (IPv4): en Windows ``localhost`` puede resolver a ``::1``
    (IPv6) mientras el live_server escucha en IPv4, lo que produce ECONNREFUSED
    intermitente. Fijar la IP elimina esa flakiness.
    """
    base_url = live_server.url.replace('localhost', '127.0.0.1')
    context = playwright.request.new_context(base_url=base_url)
    _warmup(context)
    yield context
    context.dispose()


@pytest.fixture
def login(api):
    """Devuelve un helper que loguea por la API real y deja el token en headers.

    Retorna el token; las siguientes llamadas con ``api`` deben pasar el header
    Authorization (ver helper ``auth``).
    """
    def _login(username, password=PASSWORD):
        resp = api.post('/api/login/', data={'username': username, 'password': password})
        assert resp.status == 200, f'login {username} -> {resp.status}: {resp.text()}'
        return resp.json()['token']

    return _login


def auth(token):
    """Header Authorization para un token dado."""
    return {'Authorization': f'Token {token}'}
