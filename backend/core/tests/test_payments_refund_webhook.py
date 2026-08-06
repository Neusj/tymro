"""P3.4 · Pieza 0 — la DEVOLUCIÓN queda registrada en nuestra base.

EL BUG QUE ESTE ARCHIVO FIJA: `apply_provider_payment` cortaba con `if tx.processed_at is not
None: return tx`, así que todo aviso posterior a la activación era un no-op ABSOLUTO. Un
`refunded`/`charged_back` de MercadoPago —el gimnasio devolvió la plata— se descartaba
entero: la fila seguía diciendo `approved` y el ingreso seguía contando el cobro completo.
Cualquier reporte de ingresos construido sobre eso miente hacia arriba.

Lo que se prueba acá es el registro LOCAL del hecho: que la devolución exista en la base con
monto y fecha, que sea idempotente, que valide el mismo collector que el cobro, y que el
camino del `approved` normal no cambie en nada. NO se prueba la desactivación de la
membresía, que a propósito no se implementó (ver el TODO en `_stamp_refund`).

`test_payments_process_webhook.py` cubre el flujo de aprobación y sus tests siguen valiendo
tal cual: si algo de acá los rompiera, el fix estaría mal.
"""
from decimal import Decimal

import pytest

from core.models import Plan, PaymentTransaction, StudentPlan
from core.services import payments
from core.services.providers.base import PaymentStatus

pytestmark = pytest.mark.django_db


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


def _provider():
    from core.services.providers import get_payment_provider
    return get_payment_provider()


def _notify(tx, status, *, provider_payment_id='PAY1', amount=Decimal('30000'),
            collector_id='fake-collector'):
    """Encola un pago en el proveedor falso y dispara la notificación del webhook.

    El fake indexa por `external_reference`, así que re-encolar la MISMA tx con otro estado es
    exactamente lo que hace MercadoPago cuando el mismo pago cambia de estado."""
    _provider().queue_payment(external_reference=str(tx.id), status=status, amount=amount,
                              provider_payment_id=provider_payment_id,
                              collector_id=collector_id)
    return payments.process_payment_notification(
        tx_id=str(tx.id), provider_payment_id=provider_payment_id)


# --------------------------------------------------------------------------------------
# A. El cobro deja rastro propio (`collected_at`), independiente de la activación
# --------------------------------------------------------------------------------------

def test_an_approved_payment_stamps_collected_at(scenario):
    """`collected_at` es el marcador de "la plata entró" y nace con la aprobación."""
    org, student, plan, tx = scenario
    _notify(tx, PaymentStatus.APPROVED)
    tx.refresh_from_db()
    assert tx.collected_at is not None
    assert tx.processed_at is not None


def test_collected_at_is_stamped_even_when_the_plan_activation_aborts(scenario, make_organization):
    """El caso que obliga a que `collected_at` exista y no sea `processed_at`.

    El alumno cambió de organización entre el checkout y la aprobación: `activate_student_plan`
    levanta `PlanOrganizationMismatch` y la fila queda COBRADA y SIN `processed_at` a
    propósito. La plata igual entró a la cuenta del gimnasio, así que el ingreso bruto tiene
    que verla; un reporte que sumara por `processed_at` la perdería."""
    org, student, plan, tx = scenario
    student.organization = make_organization()
    student.save(update_fields=['organization'])

    with pytest.raises(payments.PaymentIntegrityError):
        _notify(tx, PaymentStatus.APPROVED)

    tx.refresh_from_db()
    assert tx.processed_at is None          # la activación no pasó
    assert tx.collected_at is not None      # pero el cobro sí


def test_a_repeated_approval_does_not_move_collected_at(scenario):
    """`collected_at` es histórico: un reintento del webhook no puede cambiarle el período."""
    org, student, plan, tx = scenario
    _notify(tx, PaymentStatus.APPROVED)
    first = PaymentTransaction.objects.get(id=tx.id).collected_at

    _notify(tx, PaymentStatus.APPROVED)

    tx.refresh_from_db()
    assert tx.collected_at == first


# --------------------------------------------------------------------------------------
# B. La devolución posterior a la activación se REGISTRA (antes era un no-op)
# --------------------------------------------------------------------------------------

def test_a_refund_after_activation_is_recorded_instead_of_ignored(scenario):
    """EL FIX. Antes: `processed_at` cortaba y la devolución no quedaba en ninguna parte."""
    org, student, plan, tx = scenario
    _notify(tx, PaymentStatus.APPROVED)
    processed_before = PaymentTransaction.objects.get(id=tx.id).processed_at

    _notify(tx, PaymentStatus.REFUNDED)

    tx.refresh_from_db()
    assert tx.refunded_at is not None
    assert tx.refunded_amount == tx.amount
    assert tx.status == 'refunded'
    # El cobro NO se borra: bruto y devoluciones son dos hechos y el reporte los resta.
    assert tx.collected_at is not None
    # Y la activación tampoco se re-hace ni se pierde (la membresía no se desactiva: TODO).
    assert tx.processed_at == processed_before


def test_a_second_refund_notification_is_idempotent(scenario):
    """MercadoPago reintenta los webhooks: la devolución no puede duplicarse ni moverse."""
    org, student, plan, tx = scenario
    _notify(tx, PaymentStatus.APPROVED)
    _notify(tx, PaymentStatus.REFUNDED)
    first_refund = PaymentTransaction.objects.get(id=tx.id).refunded_at

    _notify(tx, PaymentStatus.REFUNDED)

    tx.refresh_from_db()
    assert tx.refunded_at == first_refund
    assert tx.refunded_amount == tx.amount


def test_a_refund_from_another_collector_is_rejected(scenario):
    """El camino nuevo valida lo MISMO que el cobro.

    Sin este chequeo, un pago de otro vendedor cuyo id llegue por el webhook podría marcar
    como devuelta una venta ajena — y el reporte restaría plata que nadie devolvió."""
    org, student, plan, tx = scenario
    _notify(tx, PaymentStatus.APPROVED)

    with pytest.raises(payments.PaymentIntegrityError):
        _notify(tx, PaymentStatus.REFUNDED, collector_id='someone-elses-collector')

    tx.refresh_from_db()
    assert tx.refunded_at is None
    assert tx.status == 'approved'


def test_a_refund_whose_payment_names_another_transaction_is_rejected(scenario,
                                                                     make_organization,
                                                                     make_user):
    """El aviso tiene que ser de ESTA venta, no de otra de la misma cuenta de MercadoPago.

    El `?tx=` del webhook queda FUERA del manifest del HMAC de MP, así que una notificación con
    firma válida se puede re-apuntar a otra transacción. Si el `external_reference` no atara el
    pago a la fila, ese re-apunte marcaría como devuelta una venta buena."""
    org, student, plan, tx = scenario
    other_tx, _ = payments.create_checkout(organization=org, user=student, plan=plan)
    _notify(tx, PaymentStatus.APPROVED)

    # Pago cuyo external_reference apunta a `other_tx`, notificado sobre `tx`.
    _provider().queue_payment(external_reference=str(other_tx.id),
                              status=PaymentStatus.REFUNDED, amount=Decimal('30000'),
                              provider_payment_id='PAYOTHER')
    with pytest.raises(payments.PaymentIntegrityError):
        payments.process_payment_notification(tx_id=str(tx.id),
                                              provider_payment_id='PAYOTHER')

    tx.refresh_from_db()
    assert tx.refunded_at is None
    assert tx.status == 'approved'


def test_a_refund_without_external_reference_is_rejected(scenario):
    """EL AGUJERO QUE CIERRA LA ATADURA DURA (hallazgo de seguridad de P3.4).

    `_assert_payment_belongs_to_transaction` compara el `external_reference` solo SI viene, y un
    pago cobrado por la misma cuenta de MP fuera de nuestro checkout (QR en recepción, link del
    panel, Point) llega SIN él. En el camino de activación esa laxitud es vieja y se conserva;
    acá NO alcanza, porque este camino muta una fila de dinero ya liquidada y lo único que
    quedaba en pie era el collector — que dos gimnasios con el mismo vendedor de MP comparten
    (`PaymentAccount` no tiene unicidad global de `provider_user_id`).

    Toda `tx` nace en `create_checkout`, que manda `external_reference=str(tx.id)`: un aviso de
    devolución sin él no es de esta venta."""
    org, student, plan, tx = scenario
    _notify(tx, PaymentStatus.APPROVED)

    _provider().queue_payment(external_reference='', status=PaymentStatus.REFUNDED,
                              amount=Decimal('30000'), provider_payment_id='PAYNOREF')
    with pytest.raises(payments.PaymentIntegrityError):
        payments.process_payment_notification(tx_id=str(tx.id),
                                              provider_payment_id='PAYNOREF')

    tx.refresh_from_db()
    assert tx.refunded_at is None
    assert tx.refunded_amount == 0
    assert tx.status == 'approved'


def test_a_refund_of_a_payment_that_was_never_applied_is_recorded(scenario):
    """Devolución sin aprobación previa: el aviso es un hecho y se registra igual.

    `collected_at` queda en NULL —nunca contamos ese cobro— y es el REPORTE el que no resta
    lo que nunca sumó. La fila no miente para que el neto cuadre."""
    org, student, plan, tx = scenario

    _notify(tx, PaymentStatus.REFUNDED)

    tx.refresh_from_db()
    assert tx.status == 'refunded'
    assert tx.refunded_at is not None
    assert tx.refunded_amount == tx.amount
    assert tx.collected_at is None
    assert StudentPlan.objects.filter(user=student, is_active=True).count() == 0


def test_a_chargeback_arrives_as_a_refund(scenario):
    """`charged_back` (contracargo) y `refunded` son la MISMA devolución para el dominio.

    El mapeo vive en el proveedor real; se fija acá porque de él depende que el camino nuevo
    de `apply_provider_payment` se active para los contracargos, que son el caso más caro."""
    from core.services.providers.mercadopago import _STATUS_MAP

    assert _STATUS_MAP['charged_back'] is PaymentStatus.REFUNDED
    assert _STATUS_MAP['refunded'] is PaymentStatus.REFUNDED


# --------------------------------------------------------------------------------------
# C. El flujo de `approved` no cambió (guarda de regresión del fix)
# --------------------------------------------------------------------------------------

def test_a_rejected_notification_after_activation_is_still_a_no_op(scenario):
    """SOLO la devolución atraviesa la guarda de idempotencia. Nada más.

    Un `rejected` que llegue tarde y desordenado sobre un pago ya cobrado no puede tocar la
    fila: sería degradar una venta buena por un aviso viejo."""
    org, student, plan, tx = scenario
    _notify(tx, PaymentStatus.APPROVED)

    _notify(tx, PaymentStatus.REJECTED, provider_payment_id='PAY1')

    tx.refresh_from_db()
    assert tx.status == 'approved'
    assert tx.refunded_at is None
    assert StudentPlan.objects.filter(user=student, is_active=True).count() == 1
