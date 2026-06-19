"""Configuración global de pytest para el backend de TYMRO.

Las variables de entorno del entorno de test (SECRET_KEY, DEBUG, EMAIL_BACKEND
locmem para la fixture `mailoutbox`) se fijan en ``tymro.settings_test``.
"""
import pytest
from django.core.cache import cache
from rest_framework.test import APIClient


@pytest.fixture(autouse=True)
def _clear_throttle_cache():
    """El throttling de DRF usa el caché; lo limpiamos entre tests para que los
    contadores de rate-limit no se filtren de un test a otro."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def make_organization(db):
    counter = {'n': 0}

    def _make(name=None):
        counter['n'] += 1
        idx = counter['n']
        from core.models import Organization

        return Organization.objects.create(
            name=name or f'Org {idx}',
            slug=f'org-{idx}',
            subdomain=f'org-{idx}',
        )

    return _make


@pytest.fixture
def make_user(db):
    def _make(username, organization=None, role='gym_admin', password='Passw0rd2026', **extra):
        from django.contrib.auth import get_user_model

        User = get_user_model()
        # Email por defecto derivado del username (único, ya que el username lo es):
        # el login ahora es por email y el serializer lo exige. Los tests que quieran
        # un email específico lo pasan en **extra.
        extra.setdefault('email', f'{username}@test.local')
        return User.objects.create_user(
            username=username,
            password=password,
            organization=organization,
            role=role,
            **extra,
        )

    return _make
