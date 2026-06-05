from pathlib import Path
import os
from urllib.parse import parse_qsl, unquote, urlparse

BASE_DIR = Path(__file__).resolve().parent.parent

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


SECRET_KEY = os.getenv('SECRET_KEY', 'tymro-dev-secret-key')
DEBUG = _env_bool('DJANGO_DEBUG', _env_bool('DEBUG', True))
ALLOWED_HOSTS = _env_list(
    'ALLOWED_HOSTS',
    ['localhost', '127.0.0.1', 'backend', 'frontend', 'tymroapp.com', '.trycloudflare.com'],
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
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'tymro.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
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

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = 'es-cl'
TIME_ZONE = 'America/Santiago'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
AUTH_USER_MODEL = 'accounts.CustomUser'

CORS_ALLOW_ALL_ORIGINS = _env_bool('CORS_ALLOW_ALL_ORIGINS', DEBUG)
CORS_ALLOWED_ORIGINS = _env_list(
    'CORS_ALLOWED_ORIGINS',
    [
        'http://localhost:5173',
        'http://127.0.0.1:5173',
        'https://tymroapp.com',
    ],
)
CORS_ALLOWED_ORIGIN_REGEXES = [
    r'^https://.*\.trycloudflare\.com$',
]
CSRF_TRUSTED_ORIGINS = _env_list(
    'CSRF_TRUSTED_ORIGINS',
    [
        'http://localhost:5173',
        'http://127.0.0.1:5173',
        'https://tymroapp.com',
        'https://*.trycloudflare.com',
    ],
)

USE_X_FORWARDED_HOST = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.TokenAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
}

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'
