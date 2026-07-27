"""Activación/renovación de StudentPlan. Fuente única de verdad usada por la
acción admin `assign` y por el webhook de pagos."""
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
        # La invariante "una sola membresía activa" es POR ORGANIZACIÓN. Sin el filtro,
        # asignar un plan en la org B ponía `is_active=False` en la membresía vigente que
        # había vendido la org A: un tenant desactivando datos de otro.
        StudentPlan.objects.filter(
            user=student,
            plan__organization_id=plan.organization_id,
            is_active=True,
        ).update(is_active=False)
        return StudentPlan.objects.create(
            user=student, plan=plan,
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
