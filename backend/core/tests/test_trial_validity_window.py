"""#19 — Ventana de validez de la clase de prueba (configurable por org, default 7d).

El alumno solo debe poder AGENDAR clases de prueba dentro de la ventana: las que
caen fuera no se ofrecen (no aparecen en el listado) y se bloquean al reservarlas.
Sin configuración explícita, la ventana es de 7 días.
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from core.models import Branch, GymClass

pytestmark = pytest.mark.django_db

TRIAL_CLASSES_URL = '/api/public/trial-classes/'
TRIAL_BOOK_URL = '/api/public/trial/book/'


def _verified_student(make_user, org):
    student = make_user('stu', organization=org, role='student', email='stu@example.com')
    student.email_verified = True
    student.trial_eligible = True
    student.save(update_fields=['email_verified', 'trial_eligible'])
    return student


def _trial_class(org, branch, *, days_ahead, name='Trial'):
    start = timezone.now() + timedelta(days=days_ahead)
    return GymClass.objects.create(
        organization=org,
        branch=branch,
        name=name,
        start_datetime=start,
        end_datetime=start + timedelta(hours=1),
        capacity=20,
        is_trial_eligible=True,
    )


def test_default_window_is_7_days_when_not_configured(api_client, make_organization, make_user):
    org = make_organization()
    branch = Branch.objects.create(organization=org, name='Sede')
    inside = _trial_class(org, branch, days_ahead=6, name='Dentro')
    outside = _trial_class(org, branch, days_ahead=8, name='Fuera')
    student = _verified_student(make_user, org)

    api_client.force_authenticate(user=student)
    resp = api_client.get(TRIAL_CLASSES_URL)
    assert resp.status_code == 200
    ids = [c['id'] for c in resp.json()]
    assert inside.id in ids
    assert outside.id not in ids  # a 8 días queda fuera de la ventana default de 7


def test_class_within_window_is_bookable(api_client, make_organization, make_user):
    org = make_organization()
    branch = Branch.objects.create(organization=org, name='Sede')
    klass = _trial_class(org, branch, days_ahead=3)
    student = _verified_student(make_user, org)

    api_client.force_authenticate(user=student)
    resp = api_client.post(TRIAL_BOOK_URL, {'gym_class': klass.id}, format='json')
    assert resp.status_code == 201, resp.content


def test_class_outside_window_is_not_offered(api_client, make_organization, make_user):
    org = make_organization()
    branch = Branch.objects.create(organization=org, name='Sede')
    outside = _trial_class(org, branch, days_ahead=30)
    student = _verified_student(make_user, org)

    api_client.force_authenticate(user=student)
    resp = api_client.get(TRIAL_CLASSES_URL)
    assert resp.status_code == 200
    assert outside.id not in [c['id'] for c in resp.json()]


def test_class_outside_window_is_blocked_on_book(api_client, make_organization, make_user):
    org = make_organization()
    branch = Branch.objects.create(organization=org, name='Sede')
    outside = _trial_class(org, branch, days_ahead=30)
    student = _verified_student(make_user, org)

    api_client.force_authenticate(user=student)
    resp = api_client.post(TRIAL_BOOK_URL, {'gym_class': outside.id}, format='json')
    assert resp.status_code == 400
    student.refresh_from_db()
    assert student.has_used_trial is False


def test_window_is_configurable_per_org(api_client, make_organization, make_user):
    org = make_organization()
    org.trial_validity_days = 30
    org.save(update_fields=['trial_validity_days'])
    branch = Branch.objects.create(organization=org, name='Sede')
    klass = _trial_class(org, branch, days_ahead=20)  # fuera de 7, dentro de 30
    student = _verified_student(make_user, org)

    api_client.force_authenticate(user=student)
    listed = api_client.get(TRIAL_CLASSES_URL)
    assert klass.id in [c['id'] for c in listed.json()]

    booked = api_client.post(TRIAL_BOOK_URL, {'gym_class': klass.id}, format='json')
    assert booked.status_code == 201, booked.content
