from datetime import timedelta
from decimal import Decimal
import importlib

import pytest
from django.utils import timezone

from core.models import ManualPayment, Plan, StudentPlan
from core.services.plans import describe_student_plan

pytestmark = pytest.mark.django_db

ASSIGN_URL = '/api/plans/assign/'
QUOTE_URL = '/api/plans/assignment-quote/'
MANUAL_URL = '/api/manual-payments/'


def _plan(org, price=30000):
    return Plan.objects.create(
        organization=org,
        name='Pack',
        plan_type='pack',
        total_classes=8,
        duration_days=30,
        price=price,
    )


def _membership(student, plan, *, paid_at=None, due_at=None, fee=15000):
    today = timezone.localdate()
    return StudentPlan.objects.create(
        user=student,
        plan=plan,
        organization_id=plan.organization_id,
        start_date=today - timedelta(days=10),
        end_date=today + timedelta(days=20),
        total_classes=plan.total_classes,
        final_price=plan.price,
        enrollment_fee=Decimal(str(fee)),
        enrollment_fee_paid_at=paid_at,
        enrollment_fee_due_at=due_at,
    )


@pytest.fixture
def ctx(make_organization, make_user):
    org = make_organization()
    org.annual_enrollment_fee = Decimal('15000')
    org.save(update_fields=['annual_enrollment_fee'])
    student = make_user('annual-student', organization=org, role='student')
    admin = make_user('annual-admin', organization=org, role='gym_admin')
    plan = _plan(org)
    return {'org': org, 'student': student, 'admin': admin, 'plan': plan}


def _auth(api_client, admin):
    api_client.force_authenticate(user=admin)


def test_student_without_previous_enrollment_fee_is_quoted_and_charged(api_client, ctx):
    _auth(api_client, ctx['admin'])

    quote = api_client.post(QUOTE_URL, {
        'user': ctx['student'].id,
        'plan': ctx['plan'].id,
        'start_date': str(timezone.localdate()),
    }, format='json')
    assert quote.status_code == 200, quote.content
    assert quote.data['plan_amount'] == '30000.00'
    assert quote.data['enrollment_fee_amount'] == '15000.00'
    assert quote.data['total'] == '45000.00'

    resp = api_client.post(ASSIGN_URL, {
        'user': ctx['student'].id,
        'plan': ctx['plan'].id,
        'start_date': str(timezone.localdate()),
        'payment': {
            'method': 'manual',
            'amount': '45000.00',
            'manual_method': ManualPayment.METHOD_CASH,
        },
    }, format='json')

    assert resp.status_code == 201, resp.content
    membership = StudentPlan.objects.get(pk=resp.data['id'])
    payment = ManualPayment.objects.get(student_plan=membership)
    assert membership.enrollment_fee == Decimal('15000.00')
    assert membership.enrollment_fee_paid_at is not None
    assert membership.enrollment_fee_due_at == timezone.localdate() + timedelta(days=365)
    assert payment.plan_amount == Decimal('30000.00')
    assert payment.enrollment_fee_amount == Decimal('15000.00')


def test_renewal_before_enrollment_fee_due_copies_the_valid_fee(api_client, ctx):
    paid_at = timezone.now() - timedelta(days=30)
    due_at = timezone.localdate() + timedelta(days=335)
    previous = _membership(ctx['student'], ctx['plan'], paid_at=paid_at, due_at=due_at)
    _auth(api_client, ctx['admin'])

    quote = api_client.post(QUOTE_URL, {
        'user': ctx['student'].id,
        'plan': ctx['plan'].id,
        'start_date': str(timezone.localdate()),
    }, format='json')
    assert quote.status_code == 200, quote.content
    assert quote.data['enrollment_fee_amount'] == '0.00'

    resp = api_client.post(ASSIGN_URL, {
        'user': ctx['student'].id,
        'plan': ctx['plan'].id,
        'start_date': str(timezone.localdate()),
        'payment': {
            'method': 'manual',
            'amount': '30000.00',
            'manual_method': ManualPayment.METHOD_TRANSFER,
        },
    }, format='json')

    assert resp.status_code == 201, resp.content
    membership = StudentPlan.objects.get(pk=resp.data['id'])
    payment = ManualPayment.objects.get(student_plan=membership)
    assert membership.enrollment_fee_paid_at == previous.enrollment_fee_paid_at
    assert membership.enrollment_fee_due_at == due_at
    assert payment.enrollment_fee_amount == Decimal('0.00')


def test_renewal_after_enrollment_fee_due_requires_a_new_fee(api_client, ctx):
    _membership(
        ctx['student'],
        ctx['plan'],
        paid_at=timezone.now() - timedelta(days=400),
        due_at=timezone.localdate() - timedelta(days=1),
    )
    _auth(api_client, ctx['admin'])

    quote = api_client.post(QUOTE_URL, {
        'user': ctx['student'].id,
        'plan': ctx['plan'].id,
        'start_date': str(timezone.localdate()),
    }, format='json')

    assert quote.status_code == 200, quote.content
    assert quote.data['enrollment_fee_amount'] == '15000.00'
    assert quote.data['total'] == '45000.00'


def test_student_exempt_from_enrollment_fee_is_not_quoted_or_charged(api_client, ctx):
    ctx['student'].pays_enrollment_fee = False
    ctx['student'].save(update_fields=['pays_enrollment_fee'])
    _auth(api_client, ctx['admin'])

    quote = api_client.post(QUOTE_URL, {
        'user': ctx['student'].id,
        'plan': ctx['plan'].id,
        'start_date': str(timezone.localdate()),
    }, format='json')
    assert quote.status_code == 200, quote.content
    assert quote.data['enrollment_fee_amount'] == '0.00'
    assert quote.data['enrollment_fee_required'] is False
    assert quote.data['enrollment_fee_waived'] is True
    assert quote.data['total'] == '30000.00'

    resp = api_client.post(ASSIGN_URL, {
        'user': ctx['student'].id,
        'plan': ctx['plan'].id,
        'start_date': str(timezone.localdate()),
        'payment': {
            'method': 'manual',
            'amount': '30000.00',
            'manual_method': ManualPayment.METHOD_CASH,
        },
    }, format='json')

    assert resp.status_code == 201, resp.content
    membership = StudentPlan.objects.get(pk=resp.data['id'])
    payment = ManualPayment.objects.get(student_plan=membership)
    assert membership.enrollment_fee == Decimal('0.00')
    assert membership.enrollment_fee_paid_at is None
    assert membership.enrollment_fee_due_at is None
    assert payment.enrollment_fee_amount == Decimal('0.00')


def test_exempt_student_does_not_copy_previous_valid_enrollment_fee(api_client, ctx):
    _membership(
        ctx['student'],
        ctx['plan'],
        paid_at=timezone.now() - timedelta(days=30),
        due_at=timezone.localdate() + timedelta(days=335),
    )
    ctx['student'].pays_enrollment_fee = False
    ctx['student'].save(update_fields=['pays_enrollment_fee'])
    _auth(api_client, ctx['admin'])

    resp = api_client.post(ASSIGN_URL, {
        'user': ctx['student'].id,
        'plan': ctx['plan'].id,
        'start_date': str(timezone.localdate()),
        'payment': {
            'method': 'manual',
            'amount': '30000.00',
            'manual_method': ManualPayment.METHOD_TRANSFER,
        },
    }, format='json')

    assert resp.status_code == 201, resp.content
    membership = StudentPlan.objects.get(pk=resp.data['id'])
    assert membership.enrollment_fee == Decimal('0.00')
    assert membership.enrollment_fee_paid_at is None
    assert membership.enrollment_fee_due_at is None


def test_manual_enrollment_fee_payment_marks_fee_without_paying_the_plan(api_client, ctx):
    membership = _membership(ctx['student'], ctx['plan'], paid_at=None, due_at=None)
    _auth(api_client, ctx['admin'])

    resp = api_client.post(MANUAL_URL, {
        'student_plan': membership.id,
        'amount': '15000.00',
        'plan_amount': '0.00',
        'enrollment_fee_amount': '15000.00',
        'method': ManualPayment.METHOD_CARD,
    }, format='json')

    assert resp.status_code == 201, resp.content
    membership.refresh_from_db()
    assert membership.enrollment_fee_paid_at is not None
    assert membership.enrollment_fee_due_at == timezone.localdate() + timedelta(days=365)
    assert describe_student_plan(membership, timezone.localdate()).payment_status == 'unpaid'


def test_manual_enrollment_fee_payment_is_rejected_for_exempt_student(api_client, ctx):
    ctx['student'].pays_enrollment_fee = False
    ctx['student'].save(update_fields=['pays_enrollment_fee'])
    membership = _membership(ctx['student'], ctx['plan'], paid_at=None, due_at=None)
    _auth(api_client, ctx['admin'])

    resp = api_client.post(MANUAL_URL, {
        'student_plan': membership.id,
        'amount': '15000.00',
        'plan_amount': '0.00',
        'enrollment_fee_amount': '15000.00',
        'method': ManualPayment.METHOD_CARD,
    }, format='json')

    assert resp.status_code == 400
    assert ManualPayment.objects.count() == 0
    membership.refresh_from_db()
    assert membership.enrollment_fee_paid_at is None
    assert describe_student_plan(membership, timezone.localdate()).enrollment_fee_status == 'waived'


@pytest.mark.parametrize('method', [
    ManualPayment.METHOD_CASH,
    ManualPayment.METHOD_TRANSFER,
    ManualPayment.METHOD_CARD,
    ManualPayment.METHOD_CHECK,
])
def test_manual_methods_are_accepted(api_client, ctx, method):
    membership = _membership(ctx['student'], ctx['plan'], fee=0)
    _auth(api_client, ctx['admin'])

    resp = api_client.post(MANUAL_URL, {
        'student_plan': membership.id,
        'amount': '30000.00',
        'method': method,
    }, format='json')

    assert resp.status_code == 201, resp.content
    assert ManualPayment.objects.get().method == method


def test_mercadopago_is_not_a_manual_method(api_client, ctx):
    membership = _membership(ctx['student'], ctx['plan'], fee=0)
    _auth(api_client, ctx['admin'])

    resp = api_client.post(MANUAL_URL, {
        'student_plan': membership.id,
        'amount': '30000.00',
        'method': 'mercadopago',
    }, format='json')

    assert resp.status_code == 400
    assert ManualPayment.objects.count() == 0


def test_duplicate_enrollment_fee_payment_is_rejected(api_client, ctx):
    membership = _membership(
        ctx['student'],
        ctx['plan'],
        paid_at=timezone.now(),
        due_at=timezone.localdate() + timedelta(days=365),
    )
    _auth(api_client, ctx['admin'])

    resp = api_client.post(MANUAL_URL, {
        'student_plan': membership.id,
        'amount': '15000.00',
        'plan_amount': '0.00',
        'enrollment_fee_amount': '15000.00',
        'method': ManualPayment.METHOD_CHECK,
    }, format='json')

    assert resp.status_code == 400
    assert ManualPayment.objects.count() == 0


def test_enrollment_fee_config_endpoint_reads_and_updates_the_org_fee(api_client, ctx):
    _auth(api_client, ctx['admin'])
    url = f'/api/organizations/{ctx["org"].id}/enrollment-fee-config/'

    get_resp = api_client.get(url)
    assert get_resp.status_code == 200, get_resp.content
    assert get_resp.data['annual_enrollment_fee'] == '15000.00'

    put_resp = api_client.put(url, {'annual_enrollment_fee': '22000.00'}, format='json')
    assert put_resp.status_code == 200, put_resp.content
    assert put_resp.data['annual_enrollment_fee'] == '22000.00'
    ctx['org'].refresh_from_db()
    assert ctx['org'].annual_enrollment_fee == Decimal('22000.00')


def test_manual_payment_breakdown_migration_backfills_amount_as_plan_amount(ctx):
    membership = _membership(ctx['student'], ctx['plan'], fee=0)
    payment = ManualPayment.objects.create(
        organization=ctx['org'],
        student_plan=membership,
        amount=Decimal('12345.00'),
        plan_amount=Decimal('0.00'),
        enrollment_fee_amount=Decimal('0.00'),
        method=ManualPayment.METHOD_CASH,
    )
    migration = importlib.import_module(
        'core.migrations.0049_organization_annual_enrollment_fee_and_manual_breakdown'
    )

    class Apps:
        @staticmethod
        def get_model(app_label, model_name):
            assert (app_label, model_name) == ('core', 'ManualPayment')
            return ManualPayment

    migration.backfill_manual_payment_breakdown(Apps(), None)

    payment.refresh_from_db()
    assert payment.plan_amount == Decimal('12345.00')
    assert payment.enrollment_fee_amount == Decimal('0.00')
