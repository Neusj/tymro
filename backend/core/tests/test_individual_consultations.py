from datetime import timedelta

import pytest
from django.utils import timezone

from core.models import ConsultationDateChange, IndividualConsultation, PaymentTransaction, Plan
from core.services.individual_consultations import create_consultation_from_payment

pytestmark = pytest.mark.django_db


@pytest.fixture
def setup(make_organization, make_user):
    org = make_organization(name='Nutrición')
    other = make_organization(name='Otro')
    admin = make_user('admin-consulta', organization=org, role='gym_admin')
    professional = make_user('nutri', organization=org, role='teacher')
    other_professional = make_user('otro-nutri', organization=org, role='teacher')
    student = make_user('alumno-consulta', organization=org, role='student')
    outsider = make_user('ajeno-consulta', organization=other, role='student')
    product = Plan.objects.create(organization=org, name='Consulta nutricional', plan_type=Plan.PlanType.CONSULTATION, total_classes=1, duration_days=90, price=30000, consultation_duration_minutes=60)
    return locals()


def create(api_client, setup, **extra):
    api_client.force_authenticate(setup['admin'])
    data = {'student_id': setup['student'].id, 'professional_id': setup['professional'].id, 'product_id': setup['product'].id, **extra}
    return api_client.post('/api/individual-consultations/', data, format='json')


def test_assign_without_schedule_and_visible_by_role(api_client, setup):
    response = create(api_client, setup)
    assert response.status_code == 201, response.content
    payload = response.json()
    assert payload['agreed_at'] is None and payload['status'] == 'available'
    assert payload['expected_duration_minutes'] == 60
    for user in (setup['admin'], setup['professional'], setup['student']):
        api_client.force_authenticate(user)
        assert api_client.get('/api/individual-consultations/').json()[0]['id'] == payload['id']


def test_date_history_start_uses_fixed_student_qr_and_finish(api_client, setup):
    item = create(api_client, setup).json()
    agreed = (timezone.now() + timedelta(days=3)).isoformat()
    api_client.force_authenticate(setup['professional'])
    response = api_client.put(f"/api/individual-consultations/{item['id']}/agreed-date/", {'agreed_at': agreed}, format='json')
    assert response.status_code == 200
    assert ConsultationDateChange.objects.filter(consultation_id=item['id']).count() == 1
    wrong = api_client.post(f"/api/individual-consultations/{item['id']}/start/", {'student_qr_token': str(setup['outsider'].student_qr_token)}, format='json')
    assert wrong.status_code == 400
    started = api_client.post(f"/api/individual-consultations/{item['id']}/start/", {'student_qr_token': str(setup['student'].student_qr_token)}, format='json')
    assert started.status_code == 200 and started.json()['status'] == 'started'
    assert api_client.post(f"/api/individual-consultations/{item['id']}/start/", {'student_qr_token': str(setup['student'].student_qr_token)}, format='json').status_code == 400
    finished = api_client.post(f"/api/individual-consultations/{item['id']}/finish/", {}, format='json')
    assert finished.status_code == 200 and finished.json()['actual_duration_seconds'] is not None
    assert api_client.post(f"/api/individual-consultations/{item['id']}/finish/", {}, format='json').status_code == 400


def test_wrong_professional_and_expired_consultation_cannot_start(api_client, setup):
    item = create(api_client, setup).json()
    consultation = IndividualConsultation.objects.get(pk=item['id'])
    consultation.expires_at = timezone.now() - timedelta(seconds=1)
    consultation.save(update_fields=['expires_at'])
    api_client.force_authenticate(setup['other_professional'])
    assert api_client.post(f"/api/individual-consultations/{item['id']}/start/", {'student_qr_token': str(setup['student'].student_qr_token)}, format='json').status_code == 403
    api_client.force_authenticate(setup['professional'])
    response = api_client.post(f"/api/individual-consultations/{item['id']}/start/", {'student_qr_token': str(setup['student'].student_qr_token)}, format='json')
    assert response.status_code == 400
    consultation.refresh_from_db()
    assert consultation.status == IndividualConsultation.Status.EXPIRED


def test_approved_purchase_materializes_one_consultation_with_product_professional(setup):
    setup['product'].consultation_professional = setup['professional']
    setup['product'].save(update_fields=['consultation_professional'])
    transaction = PaymentTransaction.objects.create(
        organization=setup['org'], user=setup['student'], plan=setup['product'],
        amount=setup['product'].price, plan_amount=setup['product'].price,
    )
    first = create_consultation_from_payment(payment_transaction=transaction)
    second = create_consultation_from_payment(payment_transaction=transaction)
    assert first.id == second.id
    assert first.professional_id == setup['professional'].id
    assert first.student_id == setup['student'].id
    assert first.status == IndividualConsultation.Status.AVAILABLE
    assert first.expected_duration_minutes == 60
