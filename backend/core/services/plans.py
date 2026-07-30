"""Activación/renovación de StudentPlan. Fuente única de verdad usada por la
acción admin `assign` y por el webhook de pagos.

NOTA DE DISEÑO PARA EL BLOQUE DE FRONTEND
-----------------------------------------
"Contratar nuevamente" (renovar un plan que el alumno ya tuvo) y "contratar desde cero"
(un plan que nunca tuvo) son la MISMA operación y tienen que converger acá: ambas llaman
`activate_student_plan` y el resultado es una fila NUEVA de `StudentPlan`.

Ningún camino puede reusar ni mutar una membresía existente —ni "revivir" una vencida
cambiándole las fechas, ni sumarle clases al saldo, ni voltear su `is_active`—. Cada
contratación es un hecho propio con su precio, su descuento y su ventana de fechas; el
historial de lo anterior tiene que quedar intacto porque es lo que respalda los cobros y
los `ConsumptionLog` ya emitidos. Si la UI necesita mostrar "renovar", es una etiqueta
sobre este mismo POST, no otro endpoint ni otra semántica.
"""
from datetime import timedelta

from django.db import transaction

from core.models import StudentPlan


class PlanOrganizationMismatch(Exception):
    """El plan que se intenta activar no es de la organización del alumno."""


def activate_student_plan(*, student, plan, start_date, discount_percentage=None):
    # La membresía la vende `plan.organization` y solo la consume un alumno de esa misma
    # organización: `get_active_student_plan` y `my-memberships` filtran por ahí, así que
    # activar un plan ajeno crearía una fila que ningún endpoint muestra ni consume. Mejor
    # fallar que persistir algo inerte —el webhook de pagos entra por este mismo camino y
    # el alumno pudo cambiar de organización entre el checkout y la aprobación—.
    if plan.organization_id != student.organization_id:
        raise PlanOrganizationMismatch(
            'El plan no pertenece a la organización del alumno.'
        )

    discount = discount_percentage if discount_percentage is not None else (plan.discount_percentage or 0)
    end_date = start_date + timedelta(days=max(plan.duration_days - 1, 0))
    final_price = max(float(plan.price) * (1 - (discount / 100)), 0)
    with transaction.atomic():
        # Activar NO desactiva nada. Un alumno puede tener varias membresías vigentes a la
        # vez en la misma organización (dos disciplinas, p. ej. 4 BJJ + 8 kickboxing), así
        # que cada contratación agrega su fila y deja las demás como estaban.
        #
        # Tampoco hay lock. El que había existía para volver atómico el par
        # "desactivar las vigentes + crear la nueva"; sin ese `update` esto es un INSERT
        # suelto, no hay secuencia leer-y-después-escribir que proteger, y dos activaciones
        # concurrentes creando dos filas es el resultado CORRECTO. Mantenerlo solo dejaría
        # contención sobre la fila del alumno y un AB-BA con el importador —que lockea
        # primero la fila de StudentPlan (`_commit_update`) y después la del alumno
        # (`_build_membership`)— cuyo deadlock el motor del importador no captura.
        return StudentPlan.objects.create(
            user=student, plan=plan,
            # Copia de la organización del plan —quien vende la membresía—. Nunca
            # `student.organization`: son iguales acá porque la guarda de arriba lo exige,
            # pero la fuente de verdad es el plan.
            organization_id=plan.organization_id,
            # Registro histórico de la sede: se deriva del alcance del plan. Un plan
            # global no tiene sede de activación, así que queda en NULL.
            branch=plan.branch,
            start_date=start_date, end_date=end_date,
            total_classes=plan.total_classes,
            unlimited_classes=plan.unlimited_classes,
            discount_percentage=discount,
            final_price=final_price,
            is_active=True,
        )
