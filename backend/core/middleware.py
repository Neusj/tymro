"""Resolución de organización (tenant) por subdominio del Host.

El host ``<subdomain>.<BASE_DOMAIN>`` mapea a una ``Organization`` por su campo
``subdomain``. El apex / hosts de plataforma resuelven a ``request.organization =
None`` (contexto plataforma: superadmins). Un subdominio que no mapea a ninguna
organización activa devuelve 404.

Notas:
- ``request.get_host()`` respeta ``USE_X_FORWARDED_HOST=True``: en dev el proxy de
  Vite reenvía el Host del subdominio vía ``X-Forwarded-Host`` (``xfwd: true``).
- El aislamiento de datos NO depende de este middleware (cada queryset filtra por
  ``request.user.organization_id``). Acá sólo se fija el contexto de org usado por el
  login (resolver el usuario dentro del subdominio) y el branding público.
"""

from django.conf import settings
from django.core.exceptions import DisallowedHost
from django.http import JsonResponse

from .models import RESERVED_SUBDOMAINS, Organization

# Prefijos de path que NO exigen un subdominio válido (infra/estáticos/SPA/health).
# Defensivo: callback y webhook de pagos llegan al apex (request.organization ya es
# None sin 404), pero esto los protege si un host tipo túnel se resolviera como subdominio.
_ALLOWLIST_PREFIXES = ('/admin', '/static', '/media', '/api/health',
                       '/api/payments/webhook', '/api/payments/oauth/callback')


def _base_domain():
    return getattr(settings, 'BASE_DOMAIN', 'localhost').lower()


def _resolve_subdomain(host, base):
    """Devuelve el label de subdominio para ``host`` o None si es apex/plataforma."""
    if host in {base, 'localhost', '127.0.0.1', '[::1]', 'testserver', f'app.{base}'}:
        return None
    suffix = '.' + base
    if not host.endswith(suffix):
        # Host que no cuelga del dominio base (IP directa, host de túnel, etc.).
        return None
    label = host[: -len(suffix)].split('.')[0]
    if not label or label in RESERVED_SUBDOMAINS:
        return None
    return label


class OrganizationMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.organization = None
        try:
            host = request.get_host().split(':')[0].lower()
        except DisallowedHost:
            return self.get_response(request)

        subdomain = _resolve_subdomain(host, _base_domain())
        if subdomain is not None:
            org = Organization.objects.filter(subdomain=subdomain, is_active=True).first()
            if org is None:
                path = request.path
                if not any(path.startswith(p) for p in _ALLOWLIST_PREFIXES):
                    return JsonResponse(
                        {'detail': f'Organización "{subdomain}" no encontrada.'},
                        status=404,
                    )
            request.organization = org

        return self.get_response(request)
