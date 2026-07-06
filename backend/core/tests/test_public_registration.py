"""Auto-registro público de prospectos + clase de prueba gratis (multitenant).

Cubre: registro feliz + verificación de email, que NO se puede crear en otra org
(slug desconocido, inyección de org/rol, interruptor on/off que desactiva el link),
que la clase de prueba es UNA sola por persona, los guards de la prueba y el
rate-limit del endpoint público. El link es público por slug (sin token).
"""
import re
from datetime import timedelta

import pytest
from django.utils import timezone

from core.models import Branch, Enrollment, GymClass

pytestmark = pytest.mark.django_db

STRONG_PASSWORD = 'Tr1alPass2026'

REGISTER_URL = '/api/public/register/'
VERIFY_URL = '/api/public/verify-email/'
INVITE_URL = '/api/public/invite/'
TRIAL_CLASSES_URL = '/api/public/trial-classes/'
TRIAL_BOOK_URL = '/api/public/trial/book/'


def _register_payload(org, **overrides):
    payload = {
        'slug': org.slug,
        'first_name': 'Pros',
        'last_name': 'Pecto',
        'email': 'pros@example.com',
        'password': STRONG_PASSWORD,
    }
    payload.update(overrides)
    return payload


def _extract_uid_token(email_body):
    match = re.search(r'verify-email\?uid=([^&\s]+)&token=([^\s]+)', email_body)
    assert match, f'No se encontró el link de verificación en:\n{email_body}'
    return match.group(1), match.group(2)


def _make_trial_class(org, branch, *, when=None, capacity=20, eligible=True, name='Clase Trial'):
    start = when or (timezone.now() + timedelta(days=1))
    return GymClass.objects.create(
        organization=org,
        branch=branch,
        name=name,
        start_datetime=start,
        end_datetime=start + timedelta(hours=1),
        capacity=capacity,
        is_trial_eligible=eligible,
    )


# --- 1) Registro feliz + verificación de email ----------------------------------

def test_public_registration_happy_path(api_client, make_organization, mailoutbox):
    org = make_organization(name='Cross Santiago')

    resp = api_client.post(REGISTER_URL, _register_payload(org), format='json')
    assert resp.status_code == 201

    from django.contrib.auth import get_user_model

    User = get_user_model()
    user = User.objects.get(email__iexact='pros@example.com')
    assert user.role == 'student'
    assert user.organization_id == org.id
    assert user.branch_id is None
    assert user.email_verified is False
    assert user.has_used_trial is False

    assert len(mailoutbox) == 1
    assert mailoutbox[0].to == ['pros@example.com']
    uid, token = _extract_uid_token(mailoutbox[0].body)

    verify = api_client.post(VERIFY_URL, {'uid': uid, 'token': token}, format='json')
    assert verify.status_code == 200
    assert verify.json()['token']
    assert verify.json()['role'] == 'student'

    user.refresh_from_db()
    assert user.email_verified is True


def test_invite_validate_returns_branding_for_valid_slug(api_client, make_organization):
    org = make_organization(name='Cross Santiago')

    ok = api_client.get(INVITE_URL, {'slug': org.slug})
    assert ok.status_code == 200
    assert ok.json()['name'] == 'Cross Santiago'
    # No se filtran datos internos.
    assert 'public_invite_token' not in ok.json()
    assert 'attendance_screen_code' not in ok.json()

    bad = api_client.get(INVITE_URL, {'slug': 'no-existe'})
    assert bad.status_code == 404


# --- 2) No se puede crear en otra organización ----------------------------------

def test_cannot_register_in_other_org_or_inject_role(api_client, make_organization):
    org_a = make_organization(name='Org A')
    org_b = make_organization(name='Org B')
    from django.contrib.auth import get_user_model

    User = get_user_model()

    # Slug inexistente -> 404 y sin usuario creado.
    bad_slug = api_client.post(
        REGISTER_URL, _register_payload(org_a, slug='no-existe'), format='json'
    )
    assert bad_slug.status_code == 404
    assert not User.objects.filter(email__iexact='pros@example.com').exists()

    # Inyección de organization/role en el payload -> ignorada: queda student en org A.
    injected = api_client.post(
        REGISTER_URL,
        _register_payload(org_a, organization=org_b.id, role='gym_admin'),
        format='json',
    )
    assert injected.status_code == 201
    user = User.objects.get(email__iexact='pros@example.com')
    assert user.role == 'student'
    assert user.organization_id == org_a.id


def test_disabling_registration_blocks_link(api_client, make_organization, make_user):
    org = make_organization(name='Org A')
    admin = make_user('admin_a', organization=org, role='gym_admin')

    # El gym_admin desactiva el registro público desde su panel.
    api_client.force_authenticate(user=admin)
    toggle = api_client.post(
        f'/api/organizations/{org.id}/set-public-registration/', {'enabled': False}, format='json'
    )
    assert toggle.status_code == 200
    assert toggle.json()['public_registration_enabled'] is False
    api_client.force_authenticate(user=None)

    # Con el registro desactivado, el link deja de servir.
    assert api_client.get(INVITE_URL, {'slug': org.slug}).status_code == 404
    assert api_client.post(REGISTER_URL, _register_payload(org), format='json').status_code == 404


# --- 3) La clase de prueba es UNA sola por persona ------------------------------

def test_trial_class_is_one_per_person(api_client, make_organization, make_user):
    org = make_organization(name='Org A')
    branch = Branch.objects.create(organization=org, name='Sede')
    student = make_user('stu', organization=org, role='student', email='stu@example.com')
    student.email_verified = True
    student.save(update_fields=['email_verified'])

    c1 = _make_trial_class(org, branch, when=timezone.now() + timedelta(days=1), name='C1')
    c2 = _make_trial_class(org, branch, when=timezone.now() + timedelta(days=2), name='C2')

    api_client.force_authenticate(user=student)

    first = api_client.post(TRIAL_BOOK_URL, {'gym_class': c1.id}, format='json')
    assert first.status_code == 201
    student.refresh_from_db()
    assert student.has_used_trial is True
    assert Enrollment.objects.filter(gym_class=c1, student=student, status='active').exists()

    # Segunda prueba -> rechazada.
    second = api_client.post(TRIAL_BOOK_URL, {'gym_class': c2.id}, format='json')
    assert second.status_code == 400

    # Cancelar la primera NO devuelve el derecho a prueba.
    Enrollment.objects.filter(gym_class=c1, student=student).update(status='cancelled')
    retry = api_client.post(TRIAL_BOOK_URL, {'gym_class': c2.id}, format='json')
    assert retry.status_code == 400


# --- 4) Guards de la prueba -----------------------------------------------------

def test_trial_requires_verified_email(api_client, make_organization, make_user):
    org = make_organization(name='Org A')
    branch = Branch.objects.create(organization=org, name='Sede')
    student = make_user('stu', organization=org, role='student', email='stu@example.com')
    # email_verified queda en False (default)
    klass = _make_trial_class(org, branch)

    api_client.force_authenticate(user=student)
    resp = api_client.post(TRIAL_BOOK_URL, {'gym_class': klass.id}, format='json')
    assert resp.status_code == 403
    assert not Enrollment.objects.filter(student=student, status='active').exists()


def test_trial_rejects_non_eligible_class(api_client, make_organization, make_user):
    org = make_organization(name='Org A')
    branch = Branch.objects.create(organization=org, name='Sede')
    student = make_user('stu', organization=org, role='student', email='stu@example.com')
    student.email_verified = True
    student.save(update_fields=['email_verified'])
    klass = _make_trial_class(org, branch, eligible=False)

    api_client.force_authenticate(user=student)
    resp = api_client.post(TRIAL_BOOK_URL, {'gym_class': klass.id}, format='json')
    assert resp.status_code == 400
    student.refresh_from_db()
    assert student.has_used_trial is False


def test_trial_respects_capacity(api_client, make_organization, make_user):
    org = make_organization(name='Org A')
    branch = Branch.objects.create(organization=org, name='Sede')
    student = make_user('stu', organization=org, role='student', email='stu@example.com')
    student.email_verified = True
    student.save(update_fields=['email_verified'])
    filler = make_user('filler', organization=org, role='student', email='filler@example.com')

    klass = _make_trial_class(org, branch, capacity=1)
    Enrollment.objects.create(gym_class=klass, student=filler, status='active')

    api_client.force_authenticate(user=student)
    resp = api_client.post(TRIAL_BOOK_URL, {'gym_class': klass.id}, format='json')
    assert resp.status_code == 400
    student.refresh_from_db()
    assert student.has_used_trial is False


# --- 6) Resolución por subdominio (sin slug en el path) -------------------------

def test_invite_by_subdomain_without_slug(api_client, make_organization):
    org = make_organization(name='Cross Santiago')  # subdomain 'org-1'
    ok = api_client.get(INVITE_URL, HTTP_HOST=f'{org.subdomain}.localhost')
    assert ok.status_code == 200
    assert ok.json()['name'] == 'Cross Santiago'


def test_register_by_subdomain_without_slug(api_client, make_organization):
    org = make_organization(name='Cross Santiago')
    from django.contrib.auth import get_user_model
    payload = {
        'first_name': 'Pros', 'last_name': 'Pecto',
        'email': 'pros@example.com', 'password': STRONG_PASSWORD,
    }
    resp = api_client.post(REGISTER_URL, payload, format='json', HTTP_HOST=f'{org.subdomain}.localhost')
    assert resp.status_code == 201, resp.content
    user = get_user_model().objects.get(email__iexact='pros@example.com')
    assert user.organization_id == org.id


def test_disabled_registration_blocks_by_subdomain(api_client, make_organization, make_user):
    org = make_organization(name='Org A')
    admin = make_user('admin_a', organization=org, role='gym_admin')
    api_client.force_authenticate(user=admin)
    api_client.post(f'/api/organizations/{org.id}/set-public-registration/', {'enabled': False}, format='json')
    api_client.force_authenticate(user=None)
    # En el subdominio, con el switch apagado -> 404 (respeta el interruptor).
    assert api_client.get(INVITE_URL, HTTP_HOST=f'{org.subdomain}.localhost').status_code == 404


# --- 7) Base de los emails por subdominio ---------------------------------------

def _prod_settings(settings):
    settings.BASE_DOMAIN = 'tymroapp.com'
    settings.FRONTEND_URL = 'https://tymroapp.com'


def test_verify_email_link_uses_subdomain(api_client, make_organization, mailoutbox, settings):
    _prod_settings(settings)
    make_organization(name='Cross')  # subdomain 'org-1'
    payload = {'first_name': 'Pros', 'email': 'pros@example.com', 'password': STRONG_PASSWORD}
    resp = api_client.post(REGISTER_URL, payload, format='json', HTTP_HOST='org-1.tymroapp.com')
    assert resp.status_code == 201, resp.content
    assert 'https://org-1.tymroapp.com/verify-email?uid=' in mailoutbox[0].body


def test_reset_password_link_uses_subdomain_for_org_user(api_client, make_organization, make_user, mailoutbox, settings):
    _prod_settings(settings)
    org = make_organization(name='Cross')
    make_user('stu', organization=org, role='student', email='stu@example.com')
    resp = api_client.post('/api/password-reset/', {'email': 'stu@example.com'}, format='json', HTTP_HOST='org-1.tymroapp.com')
    assert resp.status_code == 200
    assert 'https://org-1.tymroapp.com/reset-password?uid=' in mailoutbox[0].body


def test_reset_password_link_apex_for_platform_user(api_client, make_user, mailoutbox, settings):
    _prod_settings(settings)
    make_user('root', organization=None, role='superadmin', email='root@example.com')
    resp = api_client.post('/api/password-reset/', {'email': 'root@example.com'}, format='json', HTTP_HOST='tymroapp.com')
    assert resp.status_code == 200
    assert 'https://tymroapp.com/reset-password?uid=' in mailoutbox[0].body


# --- 5) Rate-limit del registro público -----------------------------------------

def test_public_register_is_rate_limited(api_client, make_organization):
    # El scope 'public_register' está configurado a 5/hour en settings.
    org = make_organization(name='Org A')

    statuses = []
    for i in range(6):
        resp = api_client.post(
            REGISTER_URL, _register_payload(org, email=f'p{i}@example.com'), format='json'
        )
        statuses.append(resp.status_code)

    assert statuses[:5] == [201, 201, 201, 201, 201]
    assert statuses[5] == 429
