from decimal import Decimal

import pytest

from core.models import Plan, PaymentTransaction, StudentPlan
from core.services import payments
from core.services.providers.base import PaymentStatus


@pytest.fixture(autouse=True)
def _fake(settings):
    settings.PAYMENTS_PROVIDER = 'fake'
    settings.PAYMENTS_ENCRYPTION_KEY = __import__(
        'core.fields', fromlist=['generate_encryption_key']).generate_encryption_key()
    settings.PAYMENTS_APEX_BASE_URL = 'https://app.tymroapp.com'


@pytest.fixture
def scenario(make_organization, make_user):
    org = make_organization()
    payments.connect_callback(code='C', state=payments._sign_state(org.id))
    student = make_user('stu', organization=org, role='student')
    plan = Plan.objects.create(organization=org, name='Mensual', plan_type='monthly',
                               total_classes=12, unlimited_classes=False, duration_days=30,
                               price=30000.0, discount_percentage=0)
    tx, _ = payments.create_checkout(organization=org, user=student, plan=plan)
    return org, student, plan, tx


def _approve(tx, provider):
    provider.queue_payment(external_reference=str(tx.id), status=PaymentStatus.APPROVED,
                           amount=Decimal('30000'), provider_payment_id='PAY1')


def test_approved_payment_activates_student_plan(scenario):
    org, student, plan, tx = scenario
    from core.services.providers import get_payment_provider
    provider = get_payment_provider()
    _approve(tx, provider)
    result = payments.process_payment_notification(tx_id=str(tx.id), provider_payment_id='PAY1')
    result.refresh_from_db()
    assert result.status == 'approved'
    assert result.processed_at is not None
    assert result.student_plan_id is not None
    assert StudentPlan.objects.filter(user=student, is_active=True).count() == 1


def test_idempotent_double_processing_creates_one_plan(scenario):
    org, student, plan, tx = scenario
    from core.services.providers import get_payment_provider
    provider = get_payment_provider()
    _approve(tx, provider)
    payments.process_payment_notification(tx_id=str(tx.id), provider_payment_id='PAY1')
    first_processed = PaymentTransaction.objects.get(id=tx.id).processed_at
    # Segundo webhook (duplicado) para el mismo pago:
    payments.process_payment_notification(tx_id=str(tx.id), provider_payment_id='PAY1')
    tx.refresh_from_db()
    assert tx.processed_at == first_processed            # no se re-procesó
    assert StudentPlan.objects.filter(user=student, is_active=True).count() == 1   # un solo plan


def test_rejected_payment_does_not_activate(scenario):
    org, student, plan, tx = scenario
    from core.services.providers import get_payment_provider
    provider = get_payment_provider()
    provider.queue_payment(external_reference=str(tx.id), status=PaymentStatus.REJECTED,
                           amount=Decimal('30000'), provider_payment_id='PAYX')
    payments.process_payment_notification(tx_id=str(tx.id), provider_payment_id='PAYX')
    tx.refresh_from_db()
    assert tx.status == 'rejected'
    assert tx.processed_at is None
    assert StudentPlan.objects.filter(user=student, is_active=True).count() == 0


def test_amount_mismatch_is_rejected(scenario):
    org, student, plan, tx = scenario
    from core.services.providers import get_payment_provider
    provider = get_payment_provider()
    provider.queue_payment(external_reference=str(tx.id), status=PaymentStatus.APPROVED,
                           amount=Decimal('1'), provider_payment_id='PAYBAD')   # monto no cuadra
    with pytest.raises(payments.PaymentIntegrityError):
        payments.process_payment_notification(tx_id=str(tx.id), provider_payment_id='PAYBAD')
    tx.refresh_from_db()
    assert tx.processed_at is None


def test_unknown_tx_returns_none(scenario):
    import uuid
    assert payments.process_payment_notification(
        tx_id=str(uuid.uuid4()), provider_payment_id='X') is None


def test_enrollment_fee_payment_marks_paid(make_organization, make_user):
    org = make_organization()
    payments.connect_callback(code='C', state=payments._sign_state(org.id))
    student = make_user('stu5', organization=org, role='student')
    plan = Plan.objects.create(organization=org, name='M', plan_type='monthly', total_classes=1,
                               unlimited_classes=False, duration_days=30, price=1000.0)
    sp = StudentPlan.objects.create(user=student, plan=plan, start_date='2026-07-01',
                                    end_date='2026-07-30', total_classes=1,
                                    enrollment_fee=Decimal('20000'))
    tx, _ = payments.create_checkout(organization=org, user=student, target_student_plan=sp)
    from core.services.providers import get_payment_provider
    provider = get_payment_provider()
    provider.queue_payment(external_reference=str(tx.id), status=PaymentStatus.APPROVED,
                           amount=Decimal('20000'), provider_payment_id='PAYE')
    payments.process_payment_notification(tx_id=str(tx.id), provider_payment_id='PAYE')
    sp.refresh_from_db()
    assert sp.enrollment_fee_paid_at is not None
