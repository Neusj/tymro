"""Fuente única de verdad de las URLs públicas por subdominio de la organización.

El host se arma con ``{subdomain}.{BASE_DOMAIN}``; el esquema y el puerto se toman
de ``FRONTEND_URL`` (https en prod, http://...:5173 en QA local). Una org sin
subdominio (legacy) o ``None`` (contexto plataforma) cae al host de ``FRONTEND_URL``.
"""
from urllib.parse import urlsplit

from django.conf import settings


def organization_public_base_url(organization):
    parts = urlsplit(settings.FRONTEND_URL)
    subdomain = getattr(organization, 'subdomain', None)
    if not subdomain:
        return settings.FRONTEND_URL.rstrip('/')
    base_domain = getattr(settings, 'BASE_DOMAIN', 'localhost')
    host = f'{subdomain}.{base_domain}'
    if parts.port:
        host = f'{host}:{parts.port}'
    return f'{parts.scheme or "https"}://{host}'


def trial_signup_url(organization):
    if getattr(organization, 'subdomain', None):
        return f'{organization_public_base_url(organization)}/clase-gratis'
    # Org legacy sin subdominio: link viejo por slug (capturado por el redirect).
    return f'{settings.FRONTEND_URL.rstrip("/")}/{organization.slug}/clase-gratis'
