"""Registro de cobros recibidos fuera de línea (efectivo/transferencia).

FUENTE ÚNICA de la escritura de `ManualPayment`. Lo que importa acá no es el INSERT —es
trivial— sino QUÉ organización queda estampada en la fila: la del actor que cobró, nunca la
del payload y nunca la derivada de `recorded_by.organization` (esa FK es SET_NULL y el
usuario puede mudarse de organización después). El eje de pago de la membresía intersecta
esa columna, así que una fila con la organización equivocada le declara pagada una deuda a
otro tenant.
"""
from core.models import ManualPayment


class ManualPaymentOrganizationMismatch(Exception):
    """La membresía que se intenta pagar no es de la organización que registra el cobro."""


def record_manual_payment(*, student_plan, amount, reference, recorded_by, organization):
    """Registra un cobro fuera de línea sobre `student_plan`. Devuelve la fila creada.

    Vuelve a exigir la coherencia de organización aunque el llamador ya la haya validado:
    esta función es LA puerta de escritura y va a tener más de un llamador (carga de cobros
    históricos, matrícula en 8.4). Una guarda que solo vive en la view se pierde en el
    segundo camino, y ese es el patrón exacto que dejó los agujeros multitenant anteriores.

    Espejo de `activate_student_plan` + `PlanOrganizationMismatch` (`services/plans.py`):
    excepción de dominio propia, no `PermissionDenied` de DRF, para que el servicio no sepa
    nada de HTTP.
    """
    if student_plan.organization_id != organization.id:
        raise ManualPaymentOrganizationMismatch(
            'La membresía no pertenece a la organización que registra el pago.'
        )

    payment = ManualPayment(
        organization=organization,
        student_plan=student_plan,
        # Sede de la membresía cobrada, derivada de la FILA y nunca del payload (mismo
        # criterio que `organization`). NULL si la membresía es global. Se estampa acá, en la
        # única puerta de escritura, para que el segundo caller no se olvide.
        # `branch_id` y no `branch`: copiar el id no toca la base, mientras que leer
        # `student_plan.branch` dispara un SELECT extra para traer una fila que no se usa.
        branch_id=student_plan.branch_id,
        amount=amount,
        reference=reference or '',
        recorded_by=recorded_by,
    )
    # `full_clean()` y no solo `save()`: corre `clean()` —la misma coherencia de organización
    # a nivel de modelo— y el validador de `amount`. Mismo criterio que usa el importador
    # sobre `StudentPlan`. Es un solo INSERT, así que no hace falta `transaction.atomic()`:
    # no hay secuencia leer-y-después-escribir que proteger.
    payment.full_clean()
    payment.save()
    return payment
