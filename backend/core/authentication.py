from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework.authentication import TokenAuthentication
from rest_framework.exceptions import AuthenticationFailed


class ExpiringTokenAuthentication(TokenAuthentication):
    """TokenAuthentication con caducidad.

    Rechaza el token si su antigüedad (``token.created``) supera
    ``settings.TOKEN_TTL_HOURS``. El token se rota al re-loguear
    (ver ``core.views.LoginView``). Mantiene el formato ``Authorization: Token <key>``.
    """

    def authenticate_credentials(self, key):
        user, token = super().authenticate_credentials(key)

        ttl_hours = getattr(settings, 'TOKEN_TTL_HOURS', 0)
        if ttl_hours:
            if token.created < timezone.now() - timedelta(hours=ttl_hours):
                token.delete()
                raise AuthenticationFailed('Token expirado. Iniciá sesión nuevamente.')

        return user, token
