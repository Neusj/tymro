"""Settings para la suite de tests. **Postgres OBLIGATORIO, SQLite descartado.**

Fija las variables de entorno necesarias ANTES de importar la base, de modo que
``settings.py`` mantenga intacto el fail-hard de SECRET_KEY en producción mientras
los tests corren con valores controlados.

POR QUÉ POSTGRES Y NO SQLITE
----------------------------
Producción es Postgres, y hay tests de esta suite cuyo resultado DEPENDE del motor: el
caso canónico es el tope de ``student_plan`` en ``ManualPaymentCreateSerializer``, que
existe porque un ``filter(pk=...)`` fuera del rango de bigint revienta con 500 en
Postgres y en SQLite pasa sin chistar. Una suite verde en SQLite NO es evidencia de que
la rama esté sana. Además ``--testmon`` guarda un único mapa test→archivos por máquina,
así que alternar de motor lo ensucia y lo hace subseleccionar en silencio.

El fallback a SQLite de ``settings._database_config()`` sigue existiendo para el
desarrollo local (``runserver`` sin Postgres levantado), pero acá está EXPLÍCITAMENTE
descartado: este módulo fuerza Postgres y, si no está disponible, la suite FALLA con un
mensaje claro en vez de caer a SQLite y devolver un verde que no significa nada. Esa
caída silenciosa ya pasó y se descubrió tarde: es exactamente el modo de fallo que este
archivo existe para impedir.
"""
import os
import socket

from django.core.exceptions import ImproperlyConfigured

# Postgres de verificación local (contenedor `tymro-pg-verify`, ver backend/CLAUDE.md).
# Es el default para que `python -m pytest` a secas ya corra contra Postgres, sin que nadie
# tenga que acordarse de exportar DATABASE_URL.
DEFAULT_TEST_DATABASE_URL = 'postgresql://tymro:tymro@127.0.0.1:55432/tymro'

os.environ.setdefault('SECRET_KEY', 'test-secret-key-not-for-prod')
os.environ.setdefault('DJANGO_DEBUG', 'True')
os.environ.setdefault('EMAIL_BACKEND', 'django.core.mail.backends.locmem.EmailBackend')

# `setdefault` y no asignación directa: si alguien ya apuntó DATABASE_URL a otro Postgres
# (CI, otra instancia local), se respeta. Lo que NO se acepta es que no haya ninguno y se
# caiga a SQLite. La trinca POSTGRES_DB/USER/HOST es el otro camino válido de
# `_database_config()`, así que si viene completa se la deja ganar en vez de pisarla.
_has_postgres_trio = all(os.getenv(name) for name in ('POSTGRES_DB', 'POSTGRES_USER',
                                                      'POSTGRES_HOST'))
if not _has_postgres_trio:
    os.environ.setdefault('DATABASE_URL', DEFAULT_TEST_DATABASE_URL)

from .settings import *  # noqa: F401,F403,E402


def _fail(detail):
    """Aborta la suite con un mensaje que dice QUÉ pasa y CÓMO arreglarlo."""
    raise ImproperlyConfigured(
        f'Postgres no disponible: {detail}\n'
        '\n'
        'Los tests de TYMRO corren SIEMPRE contra Postgres; el fallback a SQLite está '
        'descartado a propósito (ver el docstring de tymro/settings_test.py).\n'
        '\n'
        'Para levantar el Postgres de verificación:\n'
        '    docker start tymro-pg-verify\n'
        'Si el contenedor no existe todavía:\n'
        '    docker run -d --name tymro-pg-verify -p 127.0.0.1:55432:5432 \\\n'
        '        -e POSTGRES_USER=tymro -e POSTGRES_PASSWORD=tymro -e POSTGRES_DB=tymro \\\n'
        '        postgres:16\n'
        'Para apuntar a otro Postgres, exportá DATABASE_URL antes de correr.'
    )


# --- Guarda 1: el motor resuelto TIENE que ser Postgres ----------------------------------
# Ataja el caso en que `_database_config()` haya caído al fallback de SQLite (o que alguien
# haya exportado un DATABASE_URL de sqlite). Sin esta guarda ese caso es un verde silencioso.
_engine = DATABASES['default']['ENGINE']  # noqa: F405
if 'postgresql' not in _engine:
    _fail(f'la configuración resolvió el motor «{_engine}» en vez de Postgres')

# --- Guarda 2: además de estar configurado, tiene que RESPONDER ---------------------------
# Sin esto, un Postgres apagado da un OperationalError críptico en medio de la creación de
# las bases de test (y con `-n auto`, multiplicado por worker). Un socket con timeout corto
# convierte eso en una sola línea legible ANTES de que arranque la suite. Se chequea la
# conexión TCP y no una query: alcanza para distinguir "no está levantado" —el modo de fallo
# real, el contenedor parado— y no arrastra el costo de autenticar en cada worker de xdist.
_host = DATABASES['default']['HOST'] or '127.0.0.1'    # noqa: F405
_port = int(DATABASES['default']['PORT'] or 5432)      # noqa: F405
_probe = socket.socket()
_probe.settimeout(3)
try:
    _probe.connect((_host, _port))
except OSError as exc:
    _fail(f'no responde en {_host}:{_port} ({exc})')
finally:
    _probe.close()
