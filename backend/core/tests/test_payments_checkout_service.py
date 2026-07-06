from decimal import Decimal

import pytest

from core.models import Plan, PaymentTransaction, StudentPlan
from core.services import payments
from core.services.providers.fake import FakePaymentProvider


@pytest.fixture(autouse=True)
def _fake(settings):
    settings.PAYMENTS_PROVIDER = 'fake'
    settings.PAYMENTS_ENCRYPTION_KEY = __import__(
        'core.fields', fromlist=['generate_encryption_key']).generate_encryption_key()
    settings.PAYMENTS_APEX_BASE_URL = 'https://app.tymroapp.com'


@pytest.fixture
def connected_org(make_organization):
    org = make_organization()
    payments.connect_callback(code='C', state=payments._sign_state(org.id))
    return org


def test_checkout_for_plan_creates_pending_transaction(connected_org, make_user):
    org = connected_org
    student = make_user('stu', organization=org, role='student')
    plan = Plan.objects.create(organization=org, name='Mensual', plan_type='monthly',
                               total_classes=12, unlimited_classes=False, duration_days=30,
                               price=30000.0, discount_percentage=0)
    tx, url = payments.create_checkout(organization=org, user=student, plan=plan)
    assert isinstance(tx, PaymentTransaction)
    assert tx.status == 'pending'
    assert tx.plan_amount == Decimal('30000')
    assert tx.enrollment_fee_amount == Decimal('0')
    assert tx.amount == Decimal('30000')
    assert url.startswith('https://fake.mp/checkout/')


def test_checkout_for_enrollment_fee(connected_org, make_user):
    org = connected_org
    student = make_user('stu2', organization=org, role='student')
    plan = Plan.objects.create(organization=org, name='M', plan_type='monthly', total_classes=1,
                               unlimited_classes=False, duration_days=30, price=1000.0)
    sp = StudentPlan.objects.create(user=student, plan=plan, start_date='2026-07-01',
                                    end_date='2026-07-30', total_classes=1,
                                    enrollment_fee=Decimal('20000'))
    tx, url = payments.create_checkout(organization=org, user=student, target_student_plan=sp)
    assert tx.enrollment_fee_amount == Decimal('20000')
    assert tx.plan_amount == Decimal('0')
    assert tx.amount == Decimal('20000')
    assert tx.target_student_plan_id == sp.id


def test_checkout_without_connected_account_raises(make_organization, make_user):
    org = make_organization()   # no conectada
    student = make_user('stu3', organization=org, role='student')
    plan = Plan.objects.create(organization=org, name='M', plan_type='monthly', total_classes=1,
                               unlimited_classes=False, duration_days=30, price=1000.0)
    with pytest.raises(payments.NotConnected):
        payments.create_checkout(organization=org, user=student, plan=plan)


def test_checkout_rejects_plan_from_other_org(connected_org, make_organization, make_user):
    org = connected_org
    other = make_organization()
    student = make_user('stu4', organization=org, role='student')
    foreign_plan = Plan.objects.create(organization=other, name='X', plan_type='monthly',
                                       total_classes=1, unlimited_classes=False,
                                       duration_days=30, price=1000.0)
    with pytest.raises(payments.CheckoutError):
        payments.create_checkout(organization=org, user=student, plan=foreign_plan)


def test_checkout_back_urls_point_to_org_subdomain(connected_org, make_user, settings):
    settings.BASE_DOMAIN = 'tymroapp.com'
    settings.FRONTEND_URL = 'https://tymroapp.com'
    org = connected_org            # subdominio 'org-1'
    student = make_user('stu6', organization=org, role='student')
    plan = Plan.objects.create(organization=org, name='Mensual', plan_type='monthly',
                               total_classes=12, unlimited_classes=False, duration_days=30,
                               price=30000.0, discount_percentage=0)
    tx, _ = payments.create_checkout(organization=org, user=student, plan=plan)

    pref = FakePaymentProvider().created_preferences[-1]
    expected = f'https://{org.subdomain}.tymroapp.com/pagos/resultado?tx={tx.id}'
    assert pref['back_urls'] == {'success': expected, 'pending': expected, 'failure': expected}
    # regresión: NUNCA el apex (sin cert TLS válido)
    for url in pref['back_urls'].values():
        assert not url.startswith('https://tymroapp.com/')
    # el webhook sí va al apex del backend
    assert pref['notification_url'] == f'https://app.tymroapp.com/api/payments/webhook/?tx={tx.id}'
    # Nota: una org persistida nunca queda sin subdominio (Organization.save() lo re-deriva del
    # slug), así que el checkout siempre arma back_urls sobre el subdominio. El fallback al apex
    # del helper (org sin subdominio / None) está cubierto en test_public_urls.py.


def test_checkout_rejects_trial_plan(connected_org, make_user):
    org = connected_org
    student = make_user('stu5', organization=org, role='student')
    trial_plan = Plan.objects.create(organization=org, name='Trial', plan_type='trial',
                                     total_classes=1, unlimited_classes=False,
                                     duration_days=7, price=0.0, is_public=True, is_active=True)
    with pytest.raises(payments.CheckoutError):
        payments.create_checkout(organization=org, user=student, plan=trial_plan)
