"""Desglose de conceptos extra de la venta de una membresía (#12: "pesas $5000").

FUENTE ÚNICA de la escritura de `ChargeLineItem` — espejo exacto de `record_manual_payment`
(`services/manual_payments.py`): lo que importa no son los INSERTs sino QUÉ organización
queda estampada en cada fila — la del actor que registra, nunca la del payload y nunca la
derivada de `created_by.organization` (esa FK es SET_NULL y el usuario puede mudarse de
organización después).
"""
from django.db import transaction

from core.models import ChargeLineItem


class ChargeLineItemOrganizationMismatch(Exception):
    """La membresía a la que se adjunta el desglose no es de la organización que registra."""


def record_charge_line_items(*, student_plan, line_items, created_by, organization):
    """Registra el desglose de conceptos extra sobre `student_plan`. Devuelve las filas.

    Vuelve a exigir la coherencia de organización aunque el llamador ya la haya validado:
    mismo argumento que `record_manual_payment` — esta función es LA puerta de escritura y
    una guarda que solo vive en la view se pierde en el segundo llamador. Hoy es
    inalcanzable desde `assign` (la membresía se crea en la misma request), pero es la red
    para el próximo camino de escritura.

    `line_items` son dicts ya validados en FORMA (`concept`, `amount`) por el serializer de
    entrada; `full_clean()` corre igual por fila —validador de `amount` y coherencia a nivel
    de modelo—, mismo criterio que `record_manual_payment`.
    """
    if student_plan.organization_id != organization.id:
        raise ChargeLineItemOrganizationMismatch(
            'La membresía no pertenece a la organización que registra los conceptos.'
        )

    # A diferencia de `record_manual_payment` (un solo INSERT), acá hay VARIAS filas y el
    # desglose es todo-o-nada: sin esto, un llamador futuro sin atomic propio que reviente
    # en la fila 3 dejaría persistidas la 1 y la 2. Dentro del atomic de `assign` esto es
    # solo un savepoint, no cambia la semántica de esa transacción.
    created = []
    with transaction.atomic():
        for item in line_items:
            row = ChargeLineItem(
                organization=organization,
                student_plan=student_plan,
                concept=item['concept'],
                amount=item['amount'],
                created_by=created_by,
            )
            row.full_clean()
            row.save()
            created.append(row)
    return created
