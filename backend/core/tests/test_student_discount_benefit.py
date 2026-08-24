from datetime import date
from decimal import Decimal

import pytest
from django.utils import timezone

from core.models import PaymentTransaction, Plan, StudentPlan
from core.services import payments
from core.services.plans import (
    DISCOUNT_SOURCE_PLAN,
    DISCOUNT_SOURCE_STUDENT,
    quote_plan_purchase,
    student_benefit_expiry_for,
    student_benefit_is_active,
)
from core.services.providers.base import PaymentStatus

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _fake(settings):
    settings.PAYMENTS_PROVIDER = 'fake'
    settings.PAYMENTS_ENCRYPTION_KEY = __import__(
        'core.fields', fromlist=['generate_encryption_key']).generate_encryption_key()
    settings.PAYMENTS_APEX_BASE_URL = 'https://app.tymroapp.com'


def _plan(org, *, plan_type=Plan.PlanType.MONTHLY, price=30000, discount=0):
    return Plan.objects.create(
        organization=org,
        name=f'Plan {plan_type}',
        plan_type=plan_type,
        total_classes=12,
        unlimited_classes=False,
        duration_days=30,
        price=price,
        discount_percentage=discount,
    )


def _student_with_benefit(make_user, org, *, activated_on, expires_on=None, enabled=True):
    return make_user(
        f'stu-benefit-{org.id}-{activated_on:%Y%m%d}',
        organization=org,
        role='student',
        student_benefit_enabled=enabled,
        student_benefit_activated_on=activated_on,
        student_benefit_expires_on=expires_on or student_benefit_expiry_for(activated_on),
    )


def test_student_benefit_expiry_and_active_window(make_organization, make_user):
    org = make_organization()
    student = _student_with_benefit(make_user, org, activated_on=date(2026, 9, 15))

    assert student.student_benefit_expires_on == date(2026, 12, 31)
    assert student_benefit_is_active(student, date(2026, 12, 30)) is True
    assert student_benefit_is_active(student, date(2027, 1, 1)) is False

    student.student_benefit_activated_on = date(2027, 3, 3)
    student.student_benefit_expires_on = student_benefit_expiry_for(date(2027, 3, 3))
    student.save(update_fields=['student_benefit_activated_on', 'student_benefit_expires_on'])
    assert student.student_benefit_expires_on == date(2027, 12, 31)
    assert student_benefit_is_active(student, date(2027, 6, 1)) is True


@pytest.mark.parametrize('plan_type,expected_discount', [
    (Plan.PlanType.MONTHLY, Decimal('25.00')),
    (Plan.PlanType.PACK, Decimal('0.00')),
    (Plan.PlanType.SINGLE_CLASS, Decimal('0.00')),
])
def test_student_discount_applies_only_to_monthly_plans(make_organization, make_user,
                                                        plan_type, expected_discount):
    org = make_organization()
    org.student_discount_percentage = 25
    org.save(update_fields=['student_discount_percentage'])
    student = _student_with_benefit(make_user, org, activated_on=date(2026, 1, 10))
    plan = _plan(org, plan_type=plan_type)

    quote = quote_plan_purchase(student=student, plan=plan, on_date=date(2026, 6, 1))

    assert quote.discount_percentage == expected_discount
    assert quote.final_amount == (Decimal('22500.00') if plan_type == Plan.PlanType.MONTHLY else Decimal('30000.00'))


def test_student_discount_uses_organization_specific_percentage(make_organization, make_user):
    org_x = make_organization()
    org_y = make_organization()
    org_x.student_discount_percentage = 10
    org_y.student_discount_percentage = 40
    org_x.save(update_fields=['student_discount_percentage'])
    org_y.save(update_fields=['student_discount_percentage'])
    student_x = _student_with_benefit(make_user, org_x, activated_on=date(2026, 1, 1))
    student_y = _student_with_benefit(make_user, org_y, activated_on=date(2026, 1, 1))
    plan_x = _plan(org_x)
    plan_y = _plan(org_y)

    assert quote_plan_purchase(student=student_x, plan=plan_x, on_date=date(2026, 4, 1)).final_amount == Decimal('27000.00')
    assert quote_plan_purchase(student=student_y, plan=plan_y, on_date=date(2026, 4, 1)).final_amount == Decimal('18000.00')


@pytest.mark.parametrize('enabled,expires_on,expected_discount', [
    (True, date(2026, 12, 31), Decimal('20.00')),
    (False, date(2026, 12, 31), Decimal('0.00')),
    (True, date(2025, 12, 31), Decimal('0.00')),
])
def test_user_student_benefit_state_controls_discount(make_organization, make_user,
                                                      enabled, expires_on, expected_discount):
    org = make_organization()
    org.student_discount_percentage = 20
    org.save(update_fields=['student_discount_percentage'])
    student = _student_with_benefit(
        make_user,
        org,
        activated_on=date(2025, 1, 1),
        expires_on=expires_on,
        enabled=enabled,
    )
    plan = _plan(org)

    quote = quote_plan_purchase(student=student, plan=plan, on_date=date(2026, 8, 1))

    assert quote.discount_percentage == expected_discount


def test_existing_plan_discount_and_student_discount_do_not_stack(make_organization, make_user):
    org = make_organization()
    org.student_discount_percentage = 15
    org.save(update_fields=['student_discount_percentage'])
    student = _student_with_benefit(make_user, org, activated_on=date(2026, 1, 1))
    plan = _plan(org, discount=30)

    quote = quote_plan_purchase(student=student, plan=plan, on_date=date(2026, 8, 1))

    assert quote.discount_percentage == Decimal('30.00')
    assert quote.discount_source == DISCOUNT_SOURCE_PLAN
    assert quote.final_amount == Decimal('21000.00')

    org.student_discount_percentage = 35
    org.save(update_fields=['student_discount_percentage'])
    quote = quote_plan_purchase(student=student, plan=plan, on_date=date(2026, 8, 1))
    assert quote.discount_percentage == Decimal('35.00')
    assert quote.discount_source == DISCOUNT_SOURCE_STUDENT
    assert quote.final_amount == Decimal('19500.00')


def test_checkout_stores_discount_snapshot_and_membership_price(make_organization, make_user):
    org = make_organization()
    org.student_discount_percentage = 25
    org.save(update_fields=['student_discount_percentage'])
    payments.connect_callback(code='C', state=payments._sign_state(org.id))
    student = _student_with_benefit(make_user, org, activated_on=date(2026, 1, 1))
    plan = _plan(org, price=40000)

    tx, _ = payments.create_checkout(organization=org, user=student, plan=plan)

    assert tx.plan_original_amount == Decimal('40000.00')
    assert tx.discount_percentage == 25
    assert tx.discount_amount == Decimal('10000.00')
    assert tx.discount_source == DISCOUNT_SOURCE_STUDENT
    assert tx.plan_amount == Decimal('30000')
    assert tx.amount == Decimal('30000')

    from core.services.providers import get_payment_provider
    provider = get_payment_provider()
    provider.queue_payment(
        external_reference=str(tx.id),
        status=PaymentStatus.APPROVED,
        amount=Decimal('30000'),
        provider_payment_id='PAY-STUDENT-DISCOUNT',
    )
    payments.process_payment_notification(tx_id=str(tx.id), provider_payment_id='PAY-STUDENT-DISCOUNT')

    tx = PaymentTransaction.objects.get(id=tx.id)
    membership = StudentPlan.objects.get(id=tx.student_plan_id)
    assert membership.final_price == 30000.0
    assert membership.discount_percentage == 25
    assert membership.discount_source == DISCOUNT_SOURCE_STUDENT


def test_gym_admin_can_activate_and_deactivate_student_benefit(api_client, make_organization,
                                                               make_user, monkeypatch):
    org = make_organization()
    admin = make_user('benefit-admin', organization=org, role='gym_admin')
    student = make_user('benefit-student', organization=org, role='student')
    monkeypatch.setattr('core.serializers.timezone.localdate', lambda *args, **kwargs: date(2026, 9, 15))
    api_client.force_authenticate(admin)

    resp = api_client.patch(
        f'/api/users/{student.id}/',
        {'student_benefit_enabled': True},
        format='json',
    )

    assert resp.status_code == 200, resp.data
    student.refresh_from_db()
    assert student.student_benefit_enabled is True
    assert student.student_benefit_activated_on == date(2026, 9, 15)
    assert student.student_benefit_expires_on == date(2026, 12, 31)
    assert student.student_benefit_updated_by_id == admin.id
    assert resp.data['student_benefit_active'] is True

    resp = api_client.patch(
        f'/api/users/{student.id}/',
        {'student_benefit_enabled': False},
        format='json',
    )
    assert resp.status_code == 200, resp.data
    student.refresh_from_db()
    assert student.student_benefit_enabled is False
    assert student.student_benefit_expires_on == date(2026, 12, 31)


@pytest.mark.parametrize('role', ['student', 'teacher', 'manager', 'monitor'])
def test_non_gym_admin_roles_cannot_modify_student_benefit(api_client, make_organization,
                                                           make_user, role):
    org = make_organization()
    actor = make_user(f'benefit-actor-{role}', organization=org, role=role)
    student = make_user(f'benefit-target-{role}', organization=org, role='student')
    api_client.force_authenticate(actor)

    resp = api_client.patch(
        f'/api/users/{student.id if role != "student" else actor.id}/',
        {'student_benefit_enabled': True},
        format='json',
    )

    assert resp.status_code in (403, 404), resp.data


def test_student_discount_config_endpoint_is_org_scoped(api_client, make_organization, make_user):
    org = make_organization()
    other = make_organization()
    admin = make_user('student-discount-admin', organization=org, role='gym_admin')
    api_client.force_authenticate(admin)

    ok = api_client.put(
        f'/api/organizations/{org.id}/student-discount-config/',
        {'student_discount_percentage': 18},
        format='json',
    )
    assert ok.status_code == 200, ok.data
    org.refresh_from_db()
    assert org.student_discount_percentage == 18

    forbidden = api_client.put(
        f'/api/organizations/{other.id}/student-discount-config/',
        {'student_discount_percentage': 33},
        format='json',
    )
    assert forbidden.status_code == 403
