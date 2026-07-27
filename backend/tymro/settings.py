from pathlib import Path
import os
from urllib.parse import parse_qsl, unquote, urlparse

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

# Ruta al build del SPA (Vite). En la imagen de producción, frontend/dist se copia
# junto al backend, de modo que BASE_DIR.parent/frontend/dist apunta al build.
FRONTEND_DIST = BASE_DIR.parent / 'frontend' / 'dist'

def _env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


def _env_list(name, default=None):
    raw_value = os.getenv(name)
    if not raw_value:
        return default or []
    return [item.strip() for item in raw_value.split(',') if item.strip()]


def _postgres_database_from_url(database_url):
    parsed = urlparse(database_url)
    if parsed.scheme not in {'postgres', 'postgresql'}:
        raise ValueError('DATABASE_URL must use postgres:// or postgresql://')

    config = {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': unquote(parsed.path.lstrip('/')),
        'USER': unquote(parsed.username or ''),
        'PASSWORD': unquote(parsed.password or ''),
        'HOST': parsed.hostname or '',
        'PORT': str(parsed.port or 5432),
    }
    query_options = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if query_options:
        config['OPTIONS'] = query_options
    return config


def _database_config():
    database_url = os.getenv('DATABASE_URL')
    if database_url:
        return _postgres_database_from_url(database_url)

    postgres_name = os.getenv('POSTGRES_DB')
    postgres_user = os.getenv('POSTGRES_USER')
    postgres_host = os.getenv('POSTGRES_HOST')
    if postgres_name and postgres_user and postgres_host:
        return {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': postgres_name,
            'USER': postgres_user,
            'PASSWORD': os.getenv('POSTGRES_PASSWORD', ''),
            'HOST': postgres_host,
            'PORT': os.getenv('POSTGRES_PORT', '5432'),
        }

    return {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / os.getenv('SQLITE_DB_NAME', 'db.sqlite3'),
    }


DEBUG = _env_bool('DJANGO_DEBUG', _env_bool('DEBUG', False))

# SECRET_KEY: solo de entorno. En prod (DEBUG=False) la app FALLA al arrancar si no está.
SECRET_KEY = os.getenv('SECRET_KEY')
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = 'tymro-dev-secret-key'  # default solo para desarrollo local
    else:
        raise ImproperlyConfigured(
            'SECRET_KEY no está definida. Configúrala como variable de entorno antes de '
            'arrancar en producción (DEBUG=False).'
        )
ALLOWED_HOSTS = _env_list(
    'ALLOWED_HOSTS',
    [
        'localhost', '127.0.0.1', 'backend', 'frontend',
        '.localhost',  # subdominios de tenant en dev (r2b-qa.localhost, gym-test.localhost, ...)
        'tymroapp.com', 'qa.tymroapp.com', '.tymroapp.com',  # apex + subdominios de tenant en prod
        '.trycloudflare.com',
    ],
)

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'corsheaders',
    'rest_framework',
    'rest_framework.authtoken',
    'accounts',
    'core',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    # WhiteNoise sirve los estáticos (admin/DRF) y el build del SPA. Va justo
    # después de SecurityMiddleware, como recomienda la documentación.
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    # Resuelve la organización (tenant) desde el subdominio del Host. Va al final:
    # necesita acceso a DB y al host ya validado.
    'core.middleware.OrganizationMiddleware',
]

# Dominio base para resolver el subdominio de tenant. dev: 'localhost'
# (los subdominios *.localhost resuelven a 127.0.0.1 en Chromium); prod: 'tymroapp.com'.
BASE_DOMAIN = os.getenv('BASE_DOMAIN', 'localhost')

ROOT_URLCONF = 'tymro.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        # Incluye el dist del SPA para poder servir index.html como template
        # en el catch-all de React Router.
        'DIRS': [FRONTEND_DIST],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'tymro.wsgi.application'

DATABASES = {
    'default': _database_config()
}

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        'OPTIONS': {'min_length': 8},
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

LANGUAGE_CODE = 'es-cl'
TIME_ZONE = 'America/Santiago'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# WhiteNoise: estáticos de admin/DRF comprimidos + manifest (cache-busting).
STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
    },
}

# WhiteNoise sirve además el build del SPA (assets con hash de Vite) en la raíz,
# p.ej. /assets/index-xxxx.js. El index.html se entrega vía el catch-all (ver urls.py).
if FRONTEND_DIST.exists():
    WHITENOISE_ROOT = FRONTEND_DIST

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
AUTH_USER_MODEL = 'accounts.CustomUser'

CORS_ALLOW_ALL_ORIGINS = _env_bool('CORS_ALLOW_ALL_ORIGINS', DEBUG)
CORS_ALLOWED_ORIGINS = _env_list(
    'CORS_ALLOWED_ORIGINS',
    [
        'http://localhost:5173',
        'http://127.0.0.1:5173',
        'https://tymroapp.com',
        'https://qa.tymroapp.com',
    ],
)
CORS_ALLOWED_ORIGIN_REGEXES = [
    r'^https://.*\.trycloudflare\.com$',
    # Subdominios de tenant: dev (*.localhost:5173) y prod (*.tymroapp.com).
    r'^http://[a-z0-9-]+\.localhost:5173$',
    r'^https://[a-z0-9-]+\.tymroapp\.com$',
]
CSRF_TRUSTED_ORIGINS = _env_list(
    'CSRF_TRUSTED_ORIGINS',
    [
        'http://localhost:5173',
        'http://127.0.0.1:5173',
        'http://*.localhost:5173',
        'https://tymroapp.com',
        'https://qa.tymroapp.com',
        'https://*.tymroapp.com',
        'https://*.trycloudflare.com',
    ],
)

USE_X_FORWARDED_HOST = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Caducidad del token DRF (horas). El token se rota al re-loguear (ver core.views.LoginView).
TOKEN_TTL_HOURS = int(os.getenv('TOKEN_TTL_HOURS', '12'))

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'core.authentication.ExpiringTokenAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    # Proxies de confianza que apendean al X-Forwarded-For delante de gunicorn.
    # En Railway hay UNO: el edge. La imagen de prod es single-service
    # (Dockerfile.prod): gunicorn sirve la API y el SPA vía WhiteNoise, así que
    # NO hay nginx en el camino. El `frontend/nginx.conf` es sólo del stack
    # docker-compose local/QA.
    #
    # Sin este valor DRF arma la clave del throttle con la cadena XFF COMPLETA,
    # que el cliente controla: mandando un XFF distinto en cada intento, cada uno
    # cae en una clave nueva y el 5/min de login no aplica nunca.
    #
    # Con 1, DRF toma la ÚLTIMA entrada, que siempre la escribe el edge: es
    # correcto tanto si el edge apendea al XFF del cliente ("<falso>, <IP real>")
    # como si lo reemplaza ("<IP real>"). Subirlo a 2 en esta topología sería
    # peor que no tenerlo: tomaría la entrada que manda el cliente, dejando el
    # bypass abierto y habilitando envenenar el cupo de una víctima mandando SU
    # IP. Si algún día se mete un CDN o nginx delante, hay que subirlo.
    #
    # Configurable por entorno porque el conteo de hops NO es el mismo en todos
    # lados: el stack docker-compose local sí tiene nginx delante (2). El default
    # 1 es el de producción, que es el que no se puede equivocar.
    'NUM_PROXIES': int(os.getenv('NUM_PROXIES', '1')),
    'DEFAULT_THROTTLE_RATES': {
        'anon': '60/min',
        'user': '1000/day',
        # Override por env para que el E2E local no tope el límite con varios logins.
        'login': os.getenv('THROTTLE_LOGIN', '5/min'),
        # Pedir reset envía un email -> acotado para anti-spam (override por env en E2E).
        'password_reset': os.getenv('THROTTLE_PASSWORD_RESET', '3/hour'),
        # Confirmar permite reintentos (el usuario puede equivocarse al tipear la clave).
        'password_reset_confirm': '10/hour',
        # Registro público: crea cuenta + envía email -> acotado contra bots/spam.
        'public_register': '5/hour',
        # Validar el link de invitación es barato (sólo lectura de branding).
        'public_invite': '30/hour',
        # Confirmar email permite algún reintento.
        'public_verify': '10/hour',
        # Reenviar el correo de confirmación envía un email -> acotado (calca password_reset).
        'resend_verification': os.getenv('THROTTLE_RESEND_VERIFICATION', '3/hour'),
    },
}

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Email — consola en dev, Resend (API HTTPS) en prod. Railway bloquea SMTP saliente (587/465).
EMAIL_BACKEND = os.getenv(
    'EMAIL_BACKEND',
    'django.core.mail.backends.console.EmailBackend'
    if DEBUG
    else 'anymail.backends.resend.EmailBackend',
)
ANYMAIL = {'RESEND_API_KEY': os.getenv('RESEND_API_KEY', '')}
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'no-reply@tymroapp.com')

# URL base del frontend para armar el link de reset de contraseña.
FRONTEND_URL = os.getenv('FRONTEND_URL', 'http://localhost:5173')

# Validez del token de reset de contraseña (segundos). Default 3 días.
PASSWORD_RESET_TIMEOUT = int(os.getenv('PASSWORD_RESET_TIMEOUT', str(60 * 60 * 24 * 3)))

# --- Pagos (MercadoPago) ---
PAYMENTS_PROVIDER = os.getenv('PAYMENTS_PROVIDER', 'mercadopago')
PAYMENTS_ENCRYPTION_KEY = os.getenv('PAYMENTS_ENCRYPTION_KEY', '')
# Base pública en el APEX (sin subdominio) para callback OAuth y webhook.
PAYMENTS_APEX_BASE_URL = os.getenv('PAYMENTS_APEX_BASE_URL', 'http://localhost:8000')
MP_CLIENT_ID = os.getenv('MP_CLIENT_ID', '')
MP_CLIENT_SECRET = os.getenv('MP_CLIENT_SECRET', '')
MP_WEBHOOK_SECRET = os.getenv('MP_WEBHOOK_SECRET', '')
MP_OAUTH_REDIRECT_URI = os.getenv(
    'MP_OAUTH_REDIRECT_URI',
    f'{PAYMENTS_APEX_BASE_URL}/api/payments/oauth/callback/',
)
# Settings de pagos que no pueden faltar en producción (ver fail-fast más abajo).
PAYMENTS_REQUIRED_IN_PROD = [
    'PAYMENTS_ENCRYPTION_KEY', 'MP_CLIENT_ID', 'MP_CLIENT_SECRET', 'MP_WEBHOOK_SECRET',
]

# Hardening adicional cuando NO estamos en desarrollo.
if not DEBUG:
    SECURE_SSL_REDIRECT = _env_bool('SECURE_SSL_REDIRECT', True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(os.getenv('SECURE_HSTS_SECONDS', str(60 * 60 * 24 * 30)))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True

    _missing_payment = [
        name for name in PAYMENTS_REQUIRED_IN_PROD
        if not globals().get(name)
    ]
    if _missing_payment:
        raise ImproperlyConfigured(
            f'Faltan variables de entorno de pagos en producción: {", ".join(_missing_payment)}'
        )

    if ('localhost' in PAYMENTS_APEX_BASE_URL) or not PAYMENTS_APEX_BASE_URL.startswith('https://'):
        raise ImproperlyConfigured(
            'PAYMENTS_APEX_BASE_URL debe ser una URL https pública en producción'
        )
