"""Auto-registro público de prospectos + clase de prueba gratis (multitenant).

Cubre: registro feliz + verificación de email, que NO se puede crear en otra org
(slug desconocido, inyección de org/rol, interruptor on/off que desactiva el link),
que la clase de prueba es UNA sola por persona, los guards de la prueba y el
rate-limit del endpoint público. El link es público por slug (sin token).
"""
import re
from datetime import datetime, time, timedelta

import pytest
from django.utils import timezone

from core.models import Branch, Discipline, Enrollment, GymClass

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


def _local_dt(day, hour, minute=0):
    return timezone.make_aware(
        datetime.combine(day, time(hour=hour, minute=minute)),
        timezone.get_current_timezone(),
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
    assert user.trial_eligible is True
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
    student.trial_eligible = True
    student.save(update_fields=['email_verified', 'trial_eligible'])

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
    student.trial_eligible = True
    student.save(update_fields=['email_verified', 'trial_eligible'])
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
    student.trial_eligible = True
    student.save(update_fields=['email_verified', 'trial_eligible'])
    filler = make_user('filler', organization=org, role='student', email='filler@example.com')

    klass = _make_trial_class(org, branch, capacity=1)
    Enrollment.objects.create(gym_class=klass, student=filler, status='active')

    api_client.force_authenticate(user=student)
    resp = api_client.post(TRIAL_BOOK_URL, {'gym_class': klass.id}, format='json')
    assert resp.status_code == 400
    student.refresh_from_db()
    assert student.has_used_trial is False


def test_admin_created_student_cannot_book_free_trial(api_client, make_organization, make_user):
    org = make_organization(name='Org A')
    branch = Branch.objects.create(organization=org, name='Sede')
    student = make_user(
        'admin_created',
        organization=org,
        role='student',
        email='admin.created@example.com',
        email_verified=True,
    )
    klass = _make_trial_class(org, branch)

    api_client.force_authenticate(user=student)
    resp = api_client.post(TRIAL_BOOK_URL, {'gym_class': klass.id}, format='json')

    assert resp.status_code == 400
    assert 'no tiene clase de prueba gratis' in resp.json()['detail']
    student.refresh_from_db()
    assert student.trial_eligible is False
    assert student.has_used_trial is False


def test_trial_classes_are_day_filtered_limited_and_chronological(api_client, make_organization, make_user):
    org = make_organization(name='Org A')
    branch = Branch.objects.create(organization=org, name='Sede')
    student = make_user('stu', organization=org, role='student', email='stu@example.com')
    student.email_verified = True
    student.trial_eligible = True
    student.save(update_fields=['email_verified', 'trial_eligible'])

    target_day = timezone.localdate() + timedelta(days=1)
    other_day = target_day + timedelta(days=1)
    hours = [18, 7, 20, 9, 10, 11, 12, 13, 14, 15, 16, 17]
    created_by_hour = {
        hour: _make_trial_class(
            org,
            branch,
            when=_local_dt(target_day, hour),
            name=f'Clase {hour:02d}',
        )
        for hour in hours
    }
    _make_trial_class(org, branch, when=_local_dt(other_day, 8), name='Otro dia')

    api_client.force_authenticate(user=student)
    resp = api_client.get(TRIAL_CLASSES_URL, {
        'date': target_day.isoformat(),
        'include_filters': '1',
    })

    assert resp.status_code == 200
    data = resp.json()
    assert data['count'] == 12
    assert data['limit'] == 10
    assert data['has_more'] is True
    assert len(data['results']) == 10
    assert [row['id'] for row in data['results']] == [
        created_by_hour[hour].id for hour in [7, 9, 10, 11, 12, 13, 14, 15, 16, 17]
    ]


def test_trial_classes_search_and_filters_are_server_side(api_client, make_organization, make_user):
    org = make_organization(name='Org A')
    centro = Branch.objects.create(organization=org, name='Centro')
    norte = Branch.objects.create(organization=org, name='Norte')
    yoga = Discipline.objects.create(organization=org, name='Yoga')
    bjj = Discipline.objects.create(organization=org, name='BJJ')
    teacher = make_user(
        'ana_prof',
        organization=org,
        role='teacher',
        email='ana.prof@example.com',
        first_name='Ana',
        last_name='Lopez',
    )
    student = make_user('stu', organization=org, role='student', email='stu@example.com')
    student.email_verified = True
    student.trial_eligible = True
    student.save(update_fields=['email_verified', 'trial_eligible'])
    target_day = timezone.localdate() + timedelta(days=1)

    yoga_class = _make_trial_class(org, centro, when=_local_dt(target_day, 10), name='Flow suave')
    yoga_class.discipline = yoga
    yoga_class.teacher = teacher
    yoga_class.save(update_fields=['discipline', 'teacher'])
    bjj_class = _make_trial_class(org, norte, when=_local_dt(target_day, 11), name='Guard passing')
    bjj_class.discipline = bjj
    bjj_class.save(update_fields=['discipline'])

    full_class = _make_trial_class(org, centro, when=_local_dt(target_day, 12), capacity=1, name='Llena')
    Enrollment.objects.create(gym_class=full_class, student=student, status='active')
    cancelled = _make_trial_class(org, centro, when=_local_dt(target_day, 13), name='Cancelada')
    cancelled.status = GymClass.Status.CANCELLED
    cancelled.save(update_fields=['status'])
    _make_trial_class(org, centro, when=_local_dt(target_day, 14), eligible=False, name='No prueba')

    api_client.force_authenticate(user=student)
    searched = api_client.get(TRIAL_CLASSES_URL, {
        'date': target_day.isoformat(),
        'q': 'ana',
        'include_filters': '1',
    })
    assert searched.status_code == 200
    assert [row['id'] for row in searched.json()['results']] == [yoga_class.id]
    assert searched.json()['results'][0]['discipline_name'] == 'Yoga'

    filtered = api_client.get(TRIAL_CLASSES_URL, {
        'date': target_day.isoformat(),
        'branch_id': norte.id,
        'discipline_id': bjj.id,
        'include_filters': '1',
    })
    assert filtered.status_code == 200
    body = filtered.json()
    assert [row['id'] for row in body['results']] == [bjj_class.id]
    assert {item['name'] for item in body['filters']['branches']} == {'Centro', 'Norte'}
    assert {item['name'] for item in body['filters']['disciplines']} == {'BJJ', 'Yoga'}


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
    settings.BASE_DOMAIN = 'tymroapp.cl'
    settings.FRONTEND_URL = 'https://tymroapp.cl'


def test_verify_email_link_uses_subdomain(api_client, make_organization, mailoutbox, settings):
    _prod_settings(settings)
    make_organization(name='Cross')  # subdomain 'org-1'
    payload = {'first_name': 'Pros', 'email': 'pros@example.com', 'password': STRONG_PASSWORD}
    resp = api_client.post(REGISTER_URL, payload, format='json', HTTP_HOST='org-1.tymroapp.cl')
    assert resp.status_code == 201, resp.content
    assert 'https://org-1.tymroapp.cl/verify-email?uid=' in mailoutbox[0].body


def test_reset_password_link_uses_subdomain_for_org_user(api_client, make_organization, make_user, mailoutbox, settings):
    _prod_settings(settings)
    org = make_organization(name='Cross')
    make_user('stu', organization=org, role='student', email='stu@example.com')
    resp = api_client.post('/api/password-reset/', {'email': 'stu@example.com'}, format='json', HTTP_HOST='org-1.tymroapp.cl')
    assert resp.status_code == 200
    assert 'https://org-1.tymroapp.cl/reset-password?uid=' in mailoutbox[0].body


def test_reset_password_link_uses_app_subdomain_for_platform_user(api_client, make_user, mailoutbox, settings):
    _prod_settings(settings)
    make_user('root', organization=None, role='superadmin', email='root@example.com')
    resp = api_client.post('/api/password-reset/', {'email': 'root@example.com'}, format='json', HTTP_HOST='app.tymroapp.cl')
    assert resp.status_code == 200
    assert 'https://app.tymroapp.cl/reset-password?uid=' in mailoutbox[0].body


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


def test_registration_returns_201_even_if_email_send_fails(api_client, make_organization, monkeypatch):
    org = make_organization(name='Cross Santiago')

    def _boom(*args, **kwargs):
        raise RuntimeError('email provider down')

    monkeypatch.setattr('core.views.send_mail', _boom)

    resp = api_client.post(REGISTER_URL, _register_payload(org), format='json')

    # El envío falló pero el registro debe completarse igual.
    assert resp.status_code == 201

    from django.contrib.auth import get_user_model

    user = get_user_model().objects.get(email__iexact='pros@example.com')
    assert user.organization_id == org.id
    assert user.role == 'student'
