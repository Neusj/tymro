"""Un pago cobrado no puede perderse porque el alumno cambió de organización.

`activate_student_plan` ahora rechaza un plan que no sea de la organización del alumno
(`PlanOrganizationMismatch`), y `apply_provider_payment` lo traduce a
`PaymentIntegrityError`. El problema: esa excepción escapaba del `atomic()` que envuelve
toda la función, así que el `tx.save()` se revertía y la transacción quedaba EXACTAMENTE
como un checkout abandonado —`status='pending'`, `provider_payment_id=None`— sobre un pago
que el proveedor sí cobró.

Y era irrecuperable: `reconcile_payments` solo toma transacciones con
`provider_payment_id__isnull=False`, que es justo el campo que el rollback borraba. El único
rastro quedaba en el blob crudo de `WebhookEvent`.

Lo que se exige acá: el estado del proveedor se PERSISTE (status, provider_payment_id,
status_detail, payload) y `processed_at` queda en None, de modo que la transacción sea
visible como cobrada-sin-activar y `reconcile` la pueda volver a tomar.
"""
from decimal import Decimal

import pytest

from core.models import Plan, PaymentTransaction, StudentPlan
from core.services import payments
from core.services.providers import get_payment_provider
from core.services.providers.base import PaymentStatus

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _fake(settings):
    settings.PAYMENTS_PROVIDER = 'fake'
    settings.PAYMENTS_ENCRYPTION_KEY = __import__(
        'core.fields', fromlist=['generate_encryption_key']).generate_encryption_key()
    settings.PAYMENTS_APEX_BASE_URL = 'https://app.tymroapp.com'


@pytest.fixture
def moved_after_checkout(make_organization, make_user):
    """Checkout hecho en la org A por un alumno que se mueve a la org B antes de aprobar."""
    org_a = make_organization()
    org_b = make_organization()
    payments.connect_callback(code='C', state=payments._sign_state(org_a.id))
    student = make_user('nomade', organization=org_a, role='student', email='nomade@x.cl')
    plan_a = Plan.objects.create(
        organization=org_a, name='Pack de A', plan_type='pack', total_classes=10,
        unlimited_classes=False, duration_days=30, price=30000.0, discount_percentage=0,
    )
    tx, _ = payments.create_checkout(organization=org_a, user=student, plan=plan_a)

    student.organization = org_b
    student.save(update_fields=['organization'])

    provider = get_payment_provider()
    provider.queue_payment(
        external_reference=str(tx.id), status=PaymentStatus.APPROVED,
        amount=Decimal('30000'), provider_payment_id='PAY-MISMATCH',
    )
    return {'tx': tx, 'student': student, 'org_a': org_a, 'org_b': org_b}


def test_mismatch_persists_the_provider_state_instead_of_losing_it(moved_after_checkout):
    tx = moved_after_checkout['tx']

    # La excepcion es intencional: la vista del webhook la ackea con 200 y no re-encola
    # (`core/views_payments.py`). Lo que se audita aca es lo que quedo PERSISTIDO.
    with pytest.raises(payments.PaymentIntegrityError):
        payments.process_payment_notification(
            tx_id=str(tx.id), provider_payment_id='PAY-MISMATCH',
        )

    tx.refresh_from_db()
    assert tx.provider_payment_id == 'PAY-MISMATCH', (
        'sin provider_payment_id la transacción es indistinguible de un checkout '
        'abandonado y reconcile_payments no la vuelve a tomar'
    )
    assert tx.status == PaymentStatus.APPROVED.value, tx.status
    assert tx.processed_at is None, 'no se activó nada: no puede quedar como procesada'
    assert tx.raw_provider_payload, 'el payload del proveedor tiene que quedar guardado'
    assert tx.student_plan_id is None
    assert not StudentPlan.objects.filter(user=moved_after_checkout['student']).exists()


def test_reconcile_can_still_pick_up_the_mismatched_transaction(moved_after_checkout):
    """La consecuencia práctica: el pago queda recuperable."""
    tx = moved_after_checkout['tx']
    with pytest.raises(payments.PaymentIntegrityError):
        payments.process_payment_notification(
            tx_id=str(tx.id), provider_payment_id='PAY-MISMATCH',
        )

    recoverable = PaymentTransaction.objects.filter(
        provider_payment_id__isnull=False, processed_at__isnull=True,
    )

    assert list(recoverable.values_list('id', flat=True)) == [tx.id]


def test_the_happy_path_still_activates_the_plan(make_organization, make_user):
    """Regresión: el webhook normal sigue activando la membresía."""
    org = make_organization()
    payments.connect_callback(code='C', state=payments._sign_state(org.id))
    student = make_user('alu', organization=org, role='student', email='alu@x.cl')
    plan = Plan.objects.create(
        organization=org, name='Pack', plan_type='pack', total_classes=10,
        unlimited_classes=False, duration_days=30, price=30000.0, discount_percentage=0,
    )
    tx, _ = payments.create_checkout(organization=org, user=student, plan=plan)
    provider = get_payment_provider()
    provider.queue_payment(
        external_reference=str(tx.id), status=PaymentStatus.APPROVED,
        amount=Decimal('30000'), provider_payment_id='PAY-OK',
    )

    result = payments.process_payment_notification(
        tx_id=str(tx.id), provider_payment_id='PAY-OK',
    )

    result.refresh_from_db()
    assert result.processed_at is not None
    assert result.student_plan_id is not None
    assert StudentPlan.objects.get(id=result.student_plan_id).is_active is True
