"""Valor exacto de las URLs públicas construidas por subdominio de la organización."""
import pytest

from core.services.public_urls import organization_public_base_url, trial_signup_url

pytestmark = pytest.mark.django_db


def _prod(settings):
    settings.BASE_DOMAIN = 'tymroapp.com'
    settings.FRONTEND_URL = 'https://tymroapp.com'


def test_base_url_prod_shape(make_organization, settings):
    _prod(settings)
    org = make_organization('Gladiador')  # subdomain 'org-1'
    assert organization_public_base_url(org) == 'https://org-1.tymroapp.com'


def test_trial_signup_url_prod_shape(make_organization, settings):
    _prod(settings)
    org = make_organization('Gladiador')
    assert trial_signup_url(org) == 'https://org-1.tymroapp.com/clase-gratis'


def test_trial_signup_url_local_shape(make_organization, settings):
    settings.BASE_DOMAIN = 'localhost'
    settings.FRONTEND_URL = 'http://localhost:5173'
    org = make_organization('Gladiador')
    assert trial_signup_url(org) == 'http://org-1.localhost:5173/clase-gratis'


def test_base_url_falls_back_to_apex_without_subdomain(make_organization, settings):
    _prod(settings)
    org = make_organization('Gladiador')
    org.subdomain = None
    assert organization_public_base_url(org) == 'https://tymroapp.com'
    # trial_signup_url cae al link viejo por slug (lo captura el redirect del frontend).
    assert trial_signup_url(org) == f'https://tymroapp.com/{org.slug}/clase-gratis'


def test_base_url_none_org_is_apex(settings):
    _prod(settings)
    assert organization_public_base_url(None) == 'https://tymroapp.com'


# --- Serializers usan el helper (Task 2) ---------------------------------------

def test_organization_serializer_url_value(make_organization, settings):
    _prod(settings)
    from core.serializers import OrganizationSerializer
    org = make_organization('Gladiador')
    data = OrganizationSerializer(org).data
    assert data['public_registration_url'] == 'https://org-1.tymroapp.com/clase-gratis'


def test_branding_serializer_exposes_url_not_token(make_organization, settings):
    _prod(settings)
    from core.serializers import PublicOrganizationBrandingSerializer
    org = make_organization('Gladiador')
    data = PublicOrganizationBrandingSerializer(org).data
    assert data['public_registration_url'] == 'https://org-1.tymroapp.com/clase-gratis'
    assert 'public_invite_token' not in data
