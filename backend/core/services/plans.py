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
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from django.db import transaction

from core.models import StudentPlan


# Umbrales de aviso de vencimiento, en días. FUENTE ÚNICA: estaban duplicados como
# literales en `StudentPlanSerializer.get_expiry_alert_level` y en `_plan_status_payload`
# del roster, o sea las dos mitades de la misma feature podían divergir sin que nada lo
# detectara. Mismo criterio que `Plan.NOT_PURCHASABLE_ONLINE`: si el número vive en un solo
# lugar, no hay nada que sincronizar.
#
# El MAPEO de estos umbrales a nivel de alerta y a texto sigue en cada presentador, no acá:
# consolidar la presentación es 7.3.
EXPIRY_SOON_DAYS = 5
EXPIRY_WARNING_DAYS = 12


class PlanStatus:
    """Estados derivados de una membresía. Vocabulario definido en el backend.

    Los cinco primeros son los que ya existían repartidos entre el serializer y el roster.
    `EXHAUSTED` y `ENROLLMENT_FEE_UNPAID` son nuevos acá: hasta ahora esas dos condiciones
    solo se evaluaban dentro del validador de reservas, que las convertía en una excepción
    en vez de en un estado, así que ningún lector podía distinguir "vigente" de "vigente
    pero sin clases".
    """

    NO_PLAN = 'no_plan'
    EXPIRED = 'expired'
    UPCOMING = 'upcoming'
    INACTIVE = 'inactive'
    EXHAUSTED = 'exhausted'
    ENROLLMENT_FEE_UNPAID = 'enrollment_fee_unpaid'
    ACTIVE = 'active'


# Código de negocio del bloqueo. Coincide con los `code` que ya devolvía
# `ReservationRuleError` para que el estado unificado pueda alimentar al validador de
# reservas sin cambiarle a la API los códigos de error que el frontend ya maneja.
REASON_PLAN_UNAVAILABLE = 'plan_unavailable'
REASON_ENROLLMENT_FEE_UNPAID = 'enrollment_fee_unpaid'

_LABELS = {
    PlanStatus.NO_PLAN: 'Sin plan',
    PlanStatus.EXPIRED: 'Vencido',
    PlanStatus.UPCOMING: 'Por iniciar',
    PlanStatus.INACTIVE: 'Inactivo',
    PlanStatus.EXHAUSTED: 'Sin clases disponibles',
    PlanStatus.ENROLLMENT_FEE_UNPAID: 'Matrícula impaga',
    PlanStatus.ACTIVE: 'Vigente',
}


@dataclass(frozen=True)
class StudentPlanState:
    """Estado derivado de UNA membresía en UNA fecha. Inmutable: es una lectura."""

    status: str
    label: str
    reason_code: Optional[str]
    days_to_expiry: Optional[int]
    remaining_classes: Optional[int]
    is_usable: bool

    @property
    def passes_valid_on(self):
        """Espejo exacto de `StudentPlanQuerySet.valid_on`: ventana de fechas + `is_active`.

        Las dos mitades del predicado tienen que coincidir: si esto se separa de `valid_on`,
        vuelve la incoherencia entre lo que el queryset selecciona y lo que el estado dice.
        `EXHAUSTED` y `ENROLLMENT_FEE_UNPAID` pasan `valid_on` —el filtro no mira saldo ni
        matrícula—; `INACTIVE` no, porque tiene el flag apagado.
        """
        return self.status in _PASSES_VALID_ON_STATUSES


_PASSES_VALID_ON_STATUSES = frozenset({
    PlanStatus.ACTIVE,
    PlanStatus.EXHAUSTED,
    PlanStatus.ENROLLMENT_FEE_UNPAID,
})

# Proyección al vocabulario que la API YA expone (`validity_status` del serializer y
# `plan_status` del roster). Los dos estados nuevos colapsan a `active` a propósito: son
# refinamientos de "vigente" y publicarlos rompería a los consumidores actuales, que tratan
# todo lo que no es `active` como vencido. Exponerlos —y con qué nombre— es 7.3.
_WIRE_STATUS = {
    PlanStatus.EXHAUSTED: PlanStatus.ACTIVE,
    PlanStatus.ENROLLMENT_FEE_UNPAID: PlanStatus.ACTIVE,
}


def wire_validity_status(state: 'StudentPlanState'):
    """`(status, label)` del estado en el vocabulario público actual."""
    status = _WIRE_STATUS.get(state.status, state.status)
    return status, _LABELS[status]


def _remaining_classes(student_plan):
    if student_plan.unlimited_classes:
        return None
    return max((student_plan.total_classes or 0) - (student_plan.classes_used or 0), 0)


def _state(status, *, days_to_expiry=None, remaining_classes=None):
    usable = status == PlanStatus.ACTIVE
    if usable:
        reason_code = None
    elif status == PlanStatus.ENROLLMENT_FEE_UNPAID:
        reason_code = REASON_ENROLLMENT_FEE_UNPAID
    else:
        reason_code = REASON_PLAN_UNAVAILABLE
    return StudentPlanState(
        status=status,
        label=_LABELS[status],
        reason_code=reason_code,
        days_to_expiry=days_to_expiry,
        remaining_classes=remaining_classes,
        is_usable=usable,
    )


def describe_student_plan(student_plan: Optional[StudentPlan], on_date: date) -> StudentPlanState:
    """Estado derivado de `student_plan` en `on_date`. FUENTE ÚNICA del predicado.

    Reemplaza a las cinco copias del predicado que había en el backend y les suma las dos
    mitades que solo vivían dentro de `validate_student_plan_for_reservation`: el saldo y la
    matrícula.

    ORDEN DE PRECEDENCIA (importa): las FECHAS deciden primero y `is_active` después. Es el
    orden que ya usaban los dos presentadores, y es el único que hace que el estado no
    dependa del sentido que cada escritor le dio al flag —`activate_student_plan` lo deja en
    True para siempre porque significa "no fue reemplazada", y el importador lo deriva de
    `end_date >= hoy` porque para él significa "está vigente"—. Con las fechas adelante, una
    membresía vencida es `EXPIRED` sin importar cómo quedó el flag; dentro de la ventana, el
    flag conserva su único sentido defendible: "dada de baja".

    `on_date` es OBLIGATORIO: ver `StudentPlanQuerySet.valid_on`.

    NO decide CUÁL membresía mirar cuando el alumno tiene varias vigentes; eso es #9.
    """
    if student_plan is None:
        return _state(PlanStatus.NO_PLAN)

    days_to_expiry = None
    if student_plan.end_date:
        days_to_expiry = (student_plan.end_date - on_date).days
    remaining = _remaining_classes(student_plan)

    def build(status):
        return _state(status, days_to_expiry=days_to_expiry, remaining_classes=remaining)

    if student_plan.end_date and student_plan.end_date < on_date:
        return build(PlanStatus.EXPIRED)
    if student_plan.start_date and student_plan.start_date > on_date:
        return build(PlanStatus.UPCOMING)
    if not student_plan.is_active:
        return build(PlanStatus.INACTIVE)
    if not student_plan.unlimited_classes and (student_plan.classes_used or 0) >= (student_plan.total_classes or 0):
        return build(PlanStatus.EXHAUSTED)
    if (
        student_plan.enrollment_fee
        and student_plan.enrollment_fee > 0
        and not student_plan.enrollment_fee_paid_at
    ):
        return build(PlanStatus.ENROLLMENT_FEE_UNPAID)
    return build(PlanStatus.ACTIVE)


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
