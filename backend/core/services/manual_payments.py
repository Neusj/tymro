"""Registro de cobros recibidos fuera de línea (efectivo/transferencia).

FUENTE ÚNICA de la escritura de `ManualPayment`. Lo que importa acá no es el INSERT —es
trivial— sino QUÉ organización queda estampada en la fila: la del actor que cobró, nunca la
del payload y nunca la derivada de `recorded_by.organization` (esa FK es SET_NULL y el
usuario puede mudarse de organización después). El eje de pago de la membresía intersecta
esa columna, así que una fila con la organización equivocada le declara pagada una deuda a
otro tenant.
"""
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.models import ManualPayment, StudentPlan
from core.services.plans import (
    enrollment_fee_is_valid,
    money,
)


class ManualPaymentOrganizationMismatch(Exception):
    """La membresía que se intenta pagar no es de la organización que registra el cobro."""


def _stamp_enrollment_fee_payment(*, student_plan, amount, organization):
    today = timezone.localdate()
    if not getattr(student_plan.user, 'pays_enrollment_fee', True):
        raise ValidationError({
            'enrollment_fee_amount': (
                'Este alumno no tiene matrícula obligatoria; no corresponde cobrarla.'
            ),
        })
    if enrollment_fee_is_valid(student_plan, today):
        raise ValidationError({
            'enrollment_fee_amount': (
                'La matrícula del alumno sigue vigente; no corresponde cobrarla nuevamente.'
            ),
        })

    expected = money(student_plan.enrollment_fee)
    if expected <= 0:
        expected = money(getattr(organization, 'annual_enrollment_fee', 0))
    if expected <= 0:
        raise ValidationError({
            'enrollment_fee_amount': 'La organización no tiene una matrícula anual configurada.',
        })
    amount = money(amount)
    if amount != expected:
        raise ValidationError({
            'enrollment_fee_amount': f'La matrícula vigente a cobrar es {expected}.',
        })

    now = timezone.now()
    student_plan.enrollment_fee = expected
    student_plan.enrollment_fee_paid_at = now
    student_plan.enrollment_fee_due_at = timezone.localtime(now).date() + timedelta(days=365)
    student_plan.save(update_fields=[
        'enrollment_fee',
        'enrollment_fee_paid_at',
        'enrollment_fee_due_at',
        'updated_at',
    ])
    return student_plan


def record_manual_payment(*, student_plan, amount, reference, recorded_by, organization, method,
                          plan_amount=None, enrollment_fee_amount=None):
    """Registra un cobro fuera de línea sobre `student_plan`. Devuelve la fila creada.

    Vuelve a exigir la coherencia de organización aunque el llamador ya la haya validado:
    esta función es LA puerta de escritura y va a tener más de un llamador (carga de cobros
    históricos, matrícula en 8.4). Una guarda que solo vive en la view se pierde en el
    segundo camino, y ese es el patrón exacto que dejó los agujeros multitenant anteriores.

    Espejo de `activate_student_plan` + `PlanOrganizationMismatch` (`services/plans.py`):
    excepción de dominio propia, no `PermissionDenied` de DRF, para que el servicio no sepa
    nada de HTTP.

    `method` es un keyword REQUERIDO, sin default (P3.2): esta función es LA puerta de
    escritura -el comentario de arriba ya lo dice- y un default acá sería precisamente el
    agujero que esta columna existe para cerrar. Obligarlo acá convierte el olvido en un
    `TypeError` en desarrollo en vez de un dato mudo en producción.

    OJO: el kwarg obligatorio por sí solo NO cierra el agujero -solo fuerza a PASAR algo,
    no a pasar algo VÁLIDO-. Nada impide `method=''` o `method=None` a nivel de firma, y
    ambos crearían una fila nueva indistinguible de las legacy (`method=None` ni siquiera
    llega tan lejos: revienta como `IntegrityError` en el INSERT si algo se saltea
    `full_clean()`). Quien de verdad corta ese caso es `ManualPayment.clean()`
    (`models.py`), que rechaza `method` vacío en toda fila NUEVA (`self._state.adding`) y
    deja pasar sin problema las filas legacy existentes. Como esta función ya llama
    `full_clean()` más abajo, la guarda real de "no nace vacía" vive ahí y no acá -que es
    justo lo que también protege al próximo caller (la carga histórica de CSV) sin que
    tenga que acordarse de repetir el chequeo.
    """
    amount = money(amount)
    fee_amount = money(enrollment_fee_amount)
    plan_amount = money(amount if plan_amount is None and fee_amount <= 0 else plan_amount)

    with transaction.atomic():
        student_plan = StudentPlan.objects.select_for_update().get(pk=student_plan.pk)
        if student_plan.organization_id != organization.id:
            raise ManualPaymentOrganizationMismatch(
                'La membresía no pertenece a la organización que registra el pago.'
            )
        if fee_amount > 0:
            _stamp_enrollment_fee_payment(
                student_plan=student_plan,
                amount=fee_amount,
                organization=organization,
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
            plan_amount=plan_amount,
            enrollment_fee_amount=fee_amount,
            method=method,
            reference=reference or '',
            recorded_by=recorded_by,
        )
        payment.full_clean()
        payment.save()
        return payment
