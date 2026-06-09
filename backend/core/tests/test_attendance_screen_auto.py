"""Pantalla de asistencia automática por gimnasio: el enlace permanente
(`/attendance/screen/<code>`) devuelve el QR rotante sin sesión temporal."""
import pytest

pytestmark = pytest.mark.django_db

SCREEN_AUTO_URL = '/api/attendance-qr/screen-auto/'


def test_screen_auto_returns_rotating_qr_with_permanent_code(api_client, make_organization):
    org = make_organization(name='Cross Santiago')

    resp = api_client.get(SCREEN_AUTO_URL, {'code': org.attendance_screen_code})

    assert resp.status_code == 200
    body = resp.json()
    assert body['organization_name'] == 'Cross Santiago'
    assert body['token']
    assert '/attendance/check-in?token=' in body['check_in_url']
    assert body['expires_in_seconds'] > 0


def test_screen_auto_normalizes_code(api_client, make_organization):
    org = make_organization(name='Org A')

    # En minúsculas y con espacios → debe resolver igual (se normaliza).
    messy = f'  {org.attendance_screen_code.lower()}  '
    resp = api_client.get(SCREEN_AUTO_URL, {'code': messy})

    assert resp.status_code == 200
    assert resp.json()['token']


def test_screen_auto_rejects_unknown_code(api_client, make_organization):
    make_organization(name='Org A')

    resp = api_client.get(SCREEN_AUTO_URL, {'code': 'NOEXISTE123'})

    assert resp.status_code == 400


def test_screen_auto_requires_code(api_client):
    resp = api_client.get(SCREEN_AUTO_URL)
    assert resp.status_code == 400
