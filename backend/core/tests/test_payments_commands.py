from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.utils import timezone

from core.models import Plan, PaymentAccount, PaymentTransaction, StudentPlan
from core.services import payments
from core.services.providers.base import PaymentStatus


@pytest.fixture(autouse=True)
def _fake(settings):
    settings.PAYMENTS_PROVIDER = 'fake'
    settings.PAYMENTS_ENCRYPTION_KEY = __import__(
        'core.fields', fromlist=['generate_encryption_key']).generate_encryption_key()
    settings.PAYMENTS_APEX_BASE_URL = 'https://app.tymroapp.com'


def test_reconcile_activates_pending_with_known_payment(make_organization, make_user):
    org = make_organization()
    payments.connect_callback(code='C', state=payments._sign_state(org.id))
    student = make_user('stu', organization=org, role='student')
    plan = Plan.objects.create(organization=org, name='M', plan_type='monthly', total_classes=12,
                               unlimited_classes=False, duration_days=30, price=30000.0)
    tx, _ = payments.create_checkout(organization=org, user=student, plan=plan)
    tx.provider_payment_id = 'PAY1'      # como si el webhook lo hubiera anotado pero no activó
    tx.save(update_fields=['provider_payment_id'])
    from core.services.providers import get_payment_provider
    get_payment_provider().queue_payment(external_reference=str(tx.id),
                                         status=PaymentStatus.APPROVED, amount=Decimal('30000'),
                                         provider_payment_id='PAY1')
    # Envejecer la transacción:
    PaymentTransaction.objects.filter(id=tx.id).update(
        created_at=timezone.now() - timedelta(minutes=30))

    call_command('reconcile_payments', '--minutes', '5')

    tx.refresh_from_db()
    assert tx.status == 'approved'
    assert StudentPlan.objects.filter(user=student, is_active=True).count() == 1


def test_refresh_tokens_updates_expiring_account(make_organization):
    org = make_organization()
    acc = payments.connect_callback(code='C', state=payments._sign_state(org.id))
    PaymentAccount.objects.filter(id=acc.id).update(
        token_expires_at=timezone.now() + timedelta(hours=1))   # dentro del margen

    call_command('refresh_payment_tokens')

    acc.refresh_from_db()
    assert acc.access_token == 'fake-access-2'   # refrescado
