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
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from core.models import PaymentTransaction, Plan, RecurringEnrollment, StudentPlan, StudentPlanFreeze


# Umbrales de aviso de vencimiento, en días. FUENTE ÚNICA: estaban duplicados como
# literales en `StudentPlanSerializer.get_expiry_alert_level` y en `_plan_status_payload`
# del roster, o sea las dos mitades de la misma feature podían divergir sin que nada lo
# detectara. Mismo criterio que `Plan.NOT_PURCHASABLE_ONLINE`: si el número vive en un solo
# lugar, no hay nada que sincronizar.
#
# El MAPEO de estos umbrales a nivel de alerta y a texto también vive acá desde 7.3
# (`_plan_alert`): tenerlo en cada presentador era lo que hacía que el mismo plan dijera
# "Vence pronto" en el roster y "5 dias vigentes" en el serializer.
EXPIRY_SOON_DAYS = 5
EXPIRY_WARNING_DAYS = 12


class PlanStatus:
    """Estados derivados de una membresía. Vocabulario definido en el backend.

    Los cinco primeros son los que ya existían repartidos entre el serializer y el roster.
    `EXHAUSTED` es nuevo acá: hasta ahora esa condición solo se evaluaba dentro del
    validador de reservas, que la convertía en una excepción en vez de en un estado, así que
    ningún lector podía distinguir "vigente" de "vigente pero sin clases". La matrícula
    impaga YA NO es un estado de vigencia (8.4): la decisión de producto es que es SOLO
    INFORMATIVA, así que pasó al eje ortogonal `EnrollmentFeeStatus`, espejo de
    `PlanPaymentStatus`.
    """

    NO_PLAN = 'no_plan'
    EXPIRED = 'expired'
    UPCOMING = 'upcoming'
    INACTIVE = 'inactive'
    FROZEN = 'frozen'
    EXHAUSTED = 'exhausted'
    ACTIVE = 'active'


# Código de negocio del bloqueo. Coincide con el `code` que ya devolvía
# `ReservationRuleError` para que el estado unificado pueda alimentar al validador de
# reservas sin cambiarle a la API el código de error que el frontend ya maneja.
REASON_PLAN_UNAVAILABLE = 'plan_unavailable'

_LABELS = {
    PlanStatus.NO_PLAN: 'Sin plan',
    PlanStatus.EXPIRED: 'Vencido',
    PlanStatus.UPCOMING: 'Por iniciar',
    PlanStatus.INACTIVE: 'Inactivo',
    PlanStatus.FROZEN: 'Congelada',
    PlanStatus.EXHAUSTED: 'Sin clases disponibles',
    PlanStatus.ACTIVE: 'Vigente',
}


class PlanPaymentStatus:
    """EJE DE PAGO. Vocabulario SEPARADO del de vigencia (`PlanStatus`), no una extensión.

    Una membresía tiene dos preguntas independientes encima: si sirve hoy (`PlanStatus`) y
    si está pagada (esto). Las combinaciones son libres —`active` + `unpaid` es el plan que
    el admin asignó a mano y nadie cobró, y es perfectamente usable—, así que meter el pago
    dentro de `PlanStatus` obligaría a elegir cuál de los dos hechos publicar y perdería el
    otro. Por eso son dos campos y no uno.

    `FREE` no es "gratis" en el sentido de sin valor: es "el gimnasio decidió no cobrar
    esto" (beca, giftcard, cortesía). Se distingue de `PAID` a propósito, porque una beca no
    es un cobro conseguido y confundirlas ensucia cualquier lectura de ingresos.
    """

    PAID = 'paid'
    UNPAID = 'unpaid'
    FREE = 'free'


DISCOUNT_SOURCE_PLAN = 'plan'
DISCOUNT_SOURCE_STUDENT = 'student_benefit'


@dataclass(frozen=True)
class PlanPurchaseQuote:
    original_amount: Decimal
    discount_percentage: Decimal
    discount_amount: Decimal
    final_amount: Decimal
    discount_source: str
    student_discount_percentage: Decimal
    student_discount_applicable: bool
    plan_discount_percentage: Decimal

    def payload(self):
        return {
            'original_amount': str(self.original_amount),
            'discount_percentage': str(self.discount_percentage),
            'discount_amount': str(self.discount_amount),
            'final_amount': str(self.final_amount),
            'discount_source': self.discount_source,
            'student_discount_percentage': str(self.student_discount_percentage),
            'student_discount_applicable': self.student_discount_applicable,
            'plan_discount_percentage': str(self.plan_discount_percentage),
        }


class EnrollmentFeeStatus:
    """EJE DE MATRÍCULA. Vocabulario SEPARADO del de vigencia (`PlanStatus`), espejo exacto
    de `PlanPaymentStatus` (8.4): si la matrícula está pagada es una pregunta aparte de si
    la membresía sirve hoy, y las combinaciones son libres —`active` + `pending` es el caso
    común del alumno que todavía no pagó su matrícula y de todos modos puede reservar—. Meter
    esto dentro de `PlanStatus` era justo el bug que este eje resuelve: obligaba a elegir
    entre publicar la vigencia o la deuda de matrícula y perdía la otra.

    Son los MISMOS cuatro strings que el serializer ya publicaba antes de 8.4: el wire no
    cambia, solo la fuente que decide cuál de los cuatro corresponde.
    """

    WAIVED = 'waived'    # enrollment_fee <= 0: no hay matrícula que cobrar
    PAID = 'paid'
    PENDING = 'pending'  # impaga, sin vencer (due_at NULL o >= on_date)
    OVERDUE = 'overdue'  # impaga y vencida (due_at < on_date)


class AlertLevel:
    """Severidad del aviso. Es lo ÚNICO que la UI traduce a color; el texto ya viene hecho.

    No es un segundo vocabulario de estado: `EXPIRED` acá es una severidad heredada del
    payload que la API ya publicaba, no el `PlanStatus.EXPIRED`. Los dos estados que 7.3
    destapa son `DANGER` —bloquean, pero la membresía sigue dentro de su ventana—.
    """

    NEUTRAL = 'neutral'
    SAFE = 'safe'
    WARNING = 'warning'
    DANGER = 'danger'
    EXPIRED = 'expired'


# Aviso de los estados que no dependen de la fecha. `EXHAUSTED` reusa su etiqueta: el motivo
# del bloqueo ES el mensaje. Antes caía en el `else` de cada presentador y salía como "12
# dias vigentes", que es lo contrario de lo que pasa.
_STATIC_ALERTS = {
    PlanStatus.NO_PLAN: (AlertLevel.NEUTRAL, 'Sin plan vigente'),
    PlanStatus.EXPIRED: (AlertLevel.EXPIRED, _LABELS[PlanStatus.EXPIRED]),
    PlanStatus.UPCOMING: (AlertLevel.SAFE, _LABELS[PlanStatus.UPCOMING]),
    PlanStatus.INACTIVE: (AlertLevel.NEUTRAL, 'No vigente'),
    PlanStatus.FROZEN: (AlertLevel.WARNING, 'Membresía congelada'),
    PlanStatus.EXHAUSTED: (AlertLevel.DANGER, _LABELS[PlanStatus.EXHAUSTED]),
}


def _plan_alert(status, days_to_expiry):
    """`(nivel, mensaje)` del aviso. FUENTE ÚNICA de la presentación (7.3).

    Reemplaza a las dos copias que re-ramificaban sobre el string del estado
    —`StudentPlanSerializer` y `_plan_status_payload` del roster—. Se conserva el texto del
    serializer, que es el que el alumno ya ve hoy en pantalla; el del roster ("Vence
    pronto" / "Por vencer") no lo leía ningún consumidor.
    """
    if status != PlanStatus.ACTIVE:
        return _STATIC_ALERTS[status]
    if days_to_expiry is None:
        return AlertLevel.NEUTRAL, 'Sin fecha de vencimiento'
    if days_to_expiry <= 0:
        return AlertLevel.DANGER, 'Vence hoy'
    message = '1 dia vigente' if days_to_expiry == 1 else f'{days_to_expiry} dias vigentes'
    if days_to_expiry <= EXPIRY_SOON_DAYS:
        return AlertLevel.DANGER, message
    if days_to_expiry <= EXPIRY_WARNING_DAYS:
        return AlertLevel.WARNING, message
    return AlertLevel.SAFE, message


@dataclass(frozen=True)
class StudentPlanState:
    """Estado derivado de UNA membresía en UNA fecha. Inmutable: es una lectura."""

    status: str
    label: str
    reason_code: Optional[str]
    # Fecha en que termina la ventana. La publica el estado —y no la leen los consumidores
    # de `student_plan.end_date`— porque 7.4 la manda por correo junto con
    # `days_to_expiry`: si el aviso sacara la fecha del modelo y los días de acá, un cambio
    # en cómo se deriva la vigencia haría que el correo se contradijera a sí mismo.
    expiry_date: Optional[date]
    days_to_expiry: Optional[int]
    remaining_classes: Optional[int]
    is_usable: bool
    alert_level: str
    alert_message: str
    payment_status: Optional[str] = None
    # ORTOGONAL, espejo exacto de `payment_status` (8.4): no entra en `usable` ni en
    # `reason_code`. La matrícula impaga NO bloquea —si alguna vez tiene que bloquear, es una
    # decisión de producto que se toma aparte y se escribe acá arriba, no un efecto colateral
    # de publicar el campo.
    enrollment_fee_status: Optional[str] = None

    @property
    def passes_valid_on(self):
        """Espejo exacto de `StudentPlanQuerySet.valid_on`: ventana de fechas + `is_active`.

        Las dos mitades del predicado tienen que coincidir: si esto se separa de `valid_on`,
        vuelve la incoherencia entre lo que el queryset selecciona y lo que el estado dice.
        `EXHAUSTED` pasa `valid_on` —el filtro no mira saldo—; `INACTIVE` no, porque tiene el
        flag apagado.
        """
        return self.status in _PASSES_VALID_ON_STATUSES


_PASSES_VALID_ON_STATUSES = frozenset({
    PlanStatus.ACTIVE,
    PlanStatus.EXHAUSTED,
})

# 7.3 quitó `_WIRE_STATUS`, que proyectaba `EXHAUSTED` y `ENROLLMENT_FEE_UNPAID` a `active`
# antes de publicarlos. El colapso existía para no romper a los consumidores, que trataban
# todo lo que no era `active` como vencido; ahora leen la etiqueta y el aviso que vienen de
# acá, así que el wire publica los seis estados de vigencia tal cual. La matrícula, desde
# 8.4, ya no es uno de ellos: salió del vocabulario entero, es el eje aparte
# `enrollment_fee_status`.


def _remaining_classes(student_plan):
    if student_plan.unlimited_classes:
        return None
    return max((student_plan.total_classes or 0) - (student_plan.classes_used or 0), 0)


def _payment_status(student_plan):
    """Eje de pago de UNA membresía. DERIVACIÓN DEFINITIVA (8.2).

    8.1 tenía que adivinar el `PAID` porque no existía dónde anotar un cobro en efectivo.
    Ahora hay dos contrapartes financieras posibles y las dos valen igual: la transacción
    aprobada del proveedor (MercadoPago) y el `ManualPayment` que registró el gimnasio.

    Tres reglas, en este orden:

    * `FREE` gana sobre todo: si el precio de venta es 0, no había nada que cobrar y no hay
      cobro que reconocer. Se exige un 0 EXPLÍCITO —`final_price` es NULLABLE— porque "no se
      registró el precio" no es lo mismo que "se decidió no cobrar", y colapsarlos declararía
      becada cualquier fila vieja o creada desde el admin de Django. Una membresía en 0 con
      un `ManualPayment` encima SIGUE siendo `free`: el registro del cobro no reescribe la
      decisión comercial de no cobrar.
    * `PAID` si hay (a) una transacción APROBADA de la MISMA organización colgada de la
      membresía Y QUE HAYA PAGADO EL PLAN (`plan_amount > 0`), o (b) un `ManualPayment` de la
      MISMA organización sobre esta membresía. El orden entre (a) y (b) da igual —las dos
      devuelven lo mismo— y se dejan así solo para que el diff contra 8.1 sea mínimo.
    * `UNPAID` el resto: hay (o puede haber) algo que cobrar y no consta cobrado.

    `plan_amount > 0` es la AMBIGÜEDAD QUE 8.1 DEJÓ FIJADA y que 8.2 resuelve.
    `apply_provider_payment` setea `tx.student_plan` en sus DOS ramas: cuando el cobro compró
    el plan y cuando pagó solo la MATRÍCULA de una membresía preexistente (`payments.py`,
    rama `target_student_plan`), y esa segunda tx tiene `plan_amount == 0`. Sin este filtro,
    un plan que el admin asignó a mano —impago— cuyo alumno pagó su matrícula en línea salía
    `paid`. Pagar la matrícula no paga el plan. No hay regresión sobre las compras reales:
    `create_checkout` siempre escribe `plan_amount = precio con descuento` cuando hay plan, y
    el único caso en que eso da 0 es un plan de precio 0 (o 100% de descuento), que la regla
    `FREE` atrapa antes de llegar acá.

    El filtro por `organization_id` NO es redundante en NINGUNA de las dos ramas:
    `PaymentTransaction.student_plan` y `ManualPayment.student_plan` son FKs propias y
    ninguna constraint obliga a que la contraparte sea del tenant que vendió la membresía, así
    que seguirlas sin intersectar la organización dejaría que un cobro de la org B le declare
    pagada una deuda a la org A (el agujero multitenant recurrente del proyecto).

    NO se intersecta `tx.user_id` con `student_plan.user_id` (decisión de 8.2): un tercero
    —el padre, la empresa— puede pagar la membresía de otro, y exigir que coincidan
    convertiría ese pago legítimo en una deuda.

    NO se compara `amount` contra `final_price`. El eje tiene tres valores y ninguno es
    "parcial": un abono de 10.000 sobre una membresía de 30.000 deja la fila en `paid`. Si
    algún día hace falta saber cuánto falta, es un campo nuevo y una decisión de producto, no
    un cuarto valor de este vocabulario.

    Los DOS recorridos son sobre `.all()` en Python en vez de filtros en la DB para que un
    `prefetch_related('origin_transactions', 'manual_payments')` del llamador los resuelva sin
    consultas extra: los lectores de lista (roster, membresías del plan, job nocturno) los
    prefetchean, y así el eje no introduce un N+1 por alumno. Sin prefetch cuesta dos consultas
    por membresía. Si alguien cambia esto por un `.filter(...)`, los tests de conteo de
    `test_plan_payment_status.py` se ponen rojos.
    """
    price = student_plan.final_price
    if price is not None and price <= 0:
        return PlanPaymentStatus.FREE
    for transaction in student_plan.origin_transactions.all():
        if (
            transaction.status == PaymentTransaction.STATUS_APPROVED
            and transaction.organization_id == student_plan.organization_id
            and (transaction.plan_amount or 0) > 0
        ):
            return PlanPaymentStatus.PAID
    for payment in student_plan.manual_payments.all():
        if (
            payment.organization_id == student_plan.organization_id
            and (
                (payment.plan_amount or 0) > 0
                or (
                    (payment.plan_amount or 0) == 0
                    and (payment.enrollment_fee_amount or 0) == 0
                )
            )
        ):
            return PlanPaymentStatus.PAID
    return PlanPaymentStatus.UNPAID


def _enrollment_fee_status(student_plan, on_date):
    """Eje de matrícula de UNA membresía en `on_date`. Espejo de `_payment_status` (8.4).

    FUENTE ÚNICA que reemplaza al cálculo que el serializer hacía por su cuenta contra
    `timezone.localdate()`: acá SIEMPRE se deriva de `on_date`, la MISMA fecha que resuelve
    el resto del estado, para que `describe_student_plan(sp, on_date)` no pueda contradecir
    a lo que pinta el serializer (la contradicción que este eje viene a matar).
    """
    if not getattr(student_plan.user, 'pays_enrollment_fee', True):
        return EnrollmentFeeStatus.WAIVED
    fee = student_plan.enrollment_fee or 0
    if fee <= 0:
        return EnrollmentFeeStatus.WAIVED
    if student_plan.enrollment_fee_paid_at:
        return EnrollmentFeeStatus.PAID
    due = student_plan.enrollment_fee_due_at
    if due and due < on_date:
        return EnrollmentFeeStatus.OVERDUE
    return EnrollmentFeeStatus.PENDING


def _active_freeze_for_date(student_plan, on_date):
    freezes = getattr(student_plan, '_prefetched_objects_cache', {}).get('freezes')
    if freezes is None:
        freezes = student_plan.freezes.filter(status=StudentPlanFreeze.Status.ACTIVE)
    for freeze in freezes:
        if (
            freeze.status == StudentPlanFreeze.Status.ACTIVE
            and freeze.start_date <= on_date < freeze.planned_end_date
        ):
            return freeze
    return None


def _state(status, *, expiry_date=None, days_to_expiry=None, remaining_classes=None,
           payment_status=None, enrollment_fee_status=None):
    usable = status == PlanStatus.ACTIVE
    reason_code = None if usable else REASON_PLAN_UNAVAILABLE
    alert_level, alert_message = _plan_alert(status, days_to_expiry)
    return StudentPlanState(
        status=status,
        label=_LABELS[status],
        reason_code=reason_code,
        expiry_date=expiry_date,
        days_to_expiry=days_to_expiry,
        remaining_classes=remaining_classes,
        is_usable=usable,
        alert_level=alert_level,
        alert_message=alert_message,
        # ORTOGONAL: no entra en `usable` ni en `reason_code`. Deber plata no bloquea —si
        # alguna vez tiene que bloquear, es una decisión de producto que se toma aparte y se
        # escribe acá arriba, no un efecto colateral de publicar el campo.
        payment_status=payment_status,
        # ORTOGONAL, espejo exacto de `payment_status` (8.4): no entra en `usable` ni en
        # `reason_code`. La matrícula impaga NO bloquea —si alguna vez tiene que bloquear, es
        # una decisión de producto que se toma aparte y se escribe acá arriba, no un efecto
        # colateral de publicar el campo.
        enrollment_fee_status=enrollment_fee_status,
    )


def describe_student_plan(student_plan: Optional[StudentPlan], on_date: date) -> StudentPlanState:
    """Estado derivado de `student_plan` en `on_date`. FUENTE ÚNICA del predicado.

    Reemplaza a las cinco copias del predicado que había en el backend y le suma el saldo,
    que hasta 7.2 solo vivía dentro de `validate_student_plan_for_reservation`. La matrícula
    NO entra acá desde 8.4: la decisión de producto es que es SOLO INFORMATIVA, así que se
    resuelve como el eje aparte `enrollment_fee_status` (ver más abajo), nunca como una rama
    de este predicado.

    ORDEN DE PRECEDENCIA (importa): las FECHAS deciden primero y `is_active` después. Es el
    orden que ya usaban los dos presentadores, y es el único que hace que el estado no
    dependa del sentido que cada escritor le dio al flag —`activate_student_plan` lo deja en
    True para siempre porque significa "no fue reemplazada", y el importador lo deriva de
    `end_date >= hoy` porque para él significa "está vigente"—. Con las fechas adelante, una
    membresía vencida es `EXPIRED` sin importar cómo quedó el flag; dentro de la ventana, el
    flag conserva su único sentido defendible: "dada de baja".

    El estado de PAGO (`payment_status`) y el de MATRÍCULA (`enrollment_fee_status`) viajan
    en el mismo objeto pero son EJES APARTE: no participan de esta cadena de precedencia ni
    la alteran. `active` + `unpaid` + `pending` es una combinación válida y usable.

    `on_date` es OBLIGATORIO: ver `StudentPlanQuerySet.valid_on`.

    NO decide CUÁL membresía mirar cuando el alumno tiene varias vigentes; eso es #9.
    """
    if student_plan is None:
        return _state(PlanStatus.NO_PLAN)

    days_to_expiry = None
    if student_plan.end_date:
        days_to_expiry = (student_plan.end_date - on_date).days
    remaining = _remaining_classes(student_plan)
    # Se resuelven UNA vez y fuera de las ramas: ninguno de los dos ejes depende de la
    # vigencia, así que calcularlos dentro de cada `return` invitaría a que alguna rama los
    # omitiera y el campo apareciera y desapareciera según el estado.
    payment_status = _payment_status(student_plan)
    enrollment_fee_status = _enrollment_fee_status(student_plan, on_date)
    current_freeze = _active_freeze_for_date(student_plan, on_date)

    def build(status):
        return _state(
            status,
            expiry_date=student_plan.end_date,
            days_to_expiry=days_to_expiry,
            remaining_classes=remaining,
            payment_status=payment_status,
            enrollment_fee_status=enrollment_fee_status,
        )

    if student_plan.start_date and student_plan.start_date > on_date:
        return build(PlanStatus.UPCOMING)
    if current_freeze is not None:
        return build(PlanStatus.FROZEN)
    if student_plan.end_date and student_plan.end_date < on_date:
        return build(PlanStatus.EXPIRED)
    if not student_plan.is_active:
        return build(PlanStatus.INACTIVE)
    if not student_plan.unlimited_classes and (student_plan.classes_used or 0) >= (student_plan.total_classes or 0):
        return build(PlanStatus.EXHAUSTED)
    return build(PlanStatus.ACTIVE)


class PlanOrganizationMismatch(Exception):
    """El plan que se intenta activar no es de la organización del alumno."""


def money(value):
    return Decimal(str(value or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def student_benefit_expiry_for(on_date):
    return date(on_date.year, 12, 31)


def student_benefit_is_active(user, on_date=None):
    on_date = on_date or timezone.localdate()
    if not getattr(user, 'student_benefit_enabled', False):
        return False
    activated_on = getattr(user, 'student_benefit_activated_on', None)
    expires_on = getattr(user, 'student_benefit_expires_on', None)
    if activated_on and activated_on > on_date:
        return False
    if not expires_on or expires_on < on_date:
        return False
    return True


def plan_is_monthly(plan):
    return plan.plan_type == Plan.PlanType.MONTHLY


def _percent(value):
    pct = money(value)
    if pct < 0:
        return Decimal('0.00')
    if pct > 100:
        return Decimal('100.00')
    return pct


def quote_plan_purchase(*, student, plan, on_date=None, override_discount_percentage=None):
    on_date = on_date or timezone.localdate()
    original = money(plan.price)
    plan_discount = _percent(plan.discount_percentage or 0)
    student_discount = Decimal('0.00')
    student_applicable = False

    if plan_is_monthly(plan) and student_benefit_is_active(student, on_date):
        student_applicable = True
        student_discount = _percent(getattr(plan.organization, 'student_discount_percentage', 0))

    if override_discount_percentage is not None:
        discount = _percent(override_discount_percentage)
        source = DISCOUNT_SOURCE_PLAN if discount > 0 else ''
    elif student_discount > plan_discount:
        discount = student_discount
        source = DISCOUNT_SOURCE_STUDENT if discount > 0 else ''
    else:
        discount = plan_discount
        source = DISCOUNT_SOURCE_PLAN if discount > 0 else ''

    final_amount = money(original * (Decimal('1') - (discount / Decimal('100'))))
    if final_amount < 0:
        final_amount = Decimal('0.00')
    discount_amount = original - final_amount
    if discount_amount < 0:
        discount_amount = Decimal('0.00')
    return PlanPurchaseQuote(
        original_amount=original,
        discount_percentage=discount,
        discount_amount=discount_amount,
        final_amount=final_amount,
        discount_source=source,
        student_discount_percentage=student_discount,
        student_discount_applicable=student_applicable and student_discount > 0,
        plan_discount_percentage=plan_discount,
    )


def enrollment_fee_due_from_paid_at(paid_at):
    if paid_at is None:
        return None
    return (timezone.localtime(paid_at).date() + timedelta(days=365))


def effective_enrollment_fee_due_at(student_plan):
    if student_plan.enrollment_fee_due_at:
        return student_plan.enrollment_fee_due_at
    return enrollment_fee_due_from_paid_at(student_plan.enrollment_fee_paid_at)


def enrollment_fee_is_valid(student_plan, on_date):
    due_at = effective_enrollment_fee_due_at(student_plan)
    return bool(student_plan.enrollment_fee_paid_at and due_at and due_at >= on_date)


def current_valid_enrollment_fee_membership(*, student, organization, on_date):
    candidates = (
        StudentPlan.objects
        .filter(
            user=student,
            organization=organization,
            enrollment_fee__gt=0,
            enrollment_fee_paid_at__isnull=False,
        )
        .order_by('-enrollment_fee_due_at', '-enrollment_fee_paid_at', '-id')
    )
    for candidate in candidates:
        if enrollment_fee_is_valid(candidate, on_date):
            return candidate
    return None


@dataclass(frozen=True)
class AssignmentQuote:
    plan_original_amount: Decimal
    plan_amount: Decimal
    discount_percentage: Decimal
    discount_amount: Decimal
    discount_source: str
    enrollment_fee_amount: Decimal
    line_items_total: Decimal
    total: Decimal
    enrollment_fee_required: bool
    enrollment_fee_waived: bool = False
    enrollment_fee_paid_at: object = None
    enrollment_fee_due_at: Optional[date] = None

    def payload(self):
        return {
            'plan_original_amount': str(self.plan_original_amount),
            'plan_amount': str(self.plan_amount),
            'discount_percentage': str(self.discount_percentage),
            'discount_amount': str(self.discount_amount),
            'discount_source': self.discount_source,
            'enrollment_fee_amount': str(self.enrollment_fee_amount),
            'line_items_total': str(self.line_items_total),
            'total': str(self.total),
            'enrollment_fee_required': self.enrollment_fee_required,
            'enrollment_fee_waived': self.enrollment_fee_waived,
            'enrollment_fee_paid_at': (
                self.enrollment_fee_paid_at.isoformat()
                if self.enrollment_fee_paid_at else None
            ),
            'enrollment_fee_due_at': (
                self.enrollment_fee_due_at.isoformat()
                if self.enrollment_fee_due_at else None
            ),
        }


def quote_student_plan_assignment(*, student, plan, discount_percentage=None,
                                  line_items=None, on_date=None):
    if plan.organization_id != student.organization_id:
        raise PlanOrganizationMismatch(
            'El plan no pertenece a la organización del alumno.'
        )
    on_date = on_date or timezone.localdate()
    purchase_quote = quote_plan_purchase(
        student=student,
        plan=plan,
        on_date=on_date,
        override_discount_percentage=discount_percentage,
    )
    plan_amount = purchase_quote.final_amount
    line_items_total = sum((money(item['amount']) for item in (line_items or [])), Decimal('0.00'))

    student_pays_enrollment_fee = getattr(student, 'pays_enrollment_fee', True)
    valid_fee_membership = (
        current_valid_enrollment_fee_membership(
            student=student, organization=plan.organization, on_date=on_date,
        )
        if student_pays_enrollment_fee else None
    )
    annual_fee = money(getattr(plan.organization, 'annual_enrollment_fee', 0))
    enrollment_fee_amount = Decimal('0.00')
    if student_pays_enrollment_fee and valid_fee_membership is None and annual_fee > 0:
        enrollment_fee_amount = annual_fee

    return AssignmentQuote(
        plan_original_amount=purchase_quote.original_amount,
        plan_amount=plan_amount,
        discount_percentage=purchase_quote.discount_percentage,
        discount_amount=purchase_quote.discount_amount,
        discount_source=purchase_quote.discount_source,
        enrollment_fee_amount=enrollment_fee_amount,
        line_items_total=line_items_total,
        total=plan_amount + enrollment_fee_amount + line_items_total,
        enrollment_fee_required=enrollment_fee_amount > 0,
        enrollment_fee_waived=not student_pays_enrollment_fee,
        enrollment_fee_paid_at=getattr(valid_fee_membership, 'enrollment_fee_paid_at', None),
        enrollment_fee_due_at=(
            effective_enrollment_fee_due_at(valid_fee_membership)
            if valid_fee_membership is not None else None
        ),
    )


def _repoint_recurring_series_to_renewed_membership(new_student_plan, *, on_date):
    """Reapunta las series recurrentes VIVAS que quedaron colgadas de una instancia
    AGOTADA/VENCIDA/INACTIVA del MISMO plan de catálogo que `new_student_plan`.

    `RecurringEnrollment.student_plan` (R1, migración 0036) es la elección VIGENTE que
    gobierna las reservas futuras de la serie, y apunta a una INSTANCIA concreta. Renovar
    crea una fila NUEVA (regla 7.1: `activate_student_plan` nunca reusa ni muta la
    anterior), así que sin esto la serie sigue apuntando a la vieja y el loop la skippea
    mudo con `chosen_plan_unavailable` (`recurrence.py:_create_enrollment_if_possible`).

    Lo que este reapunte NO hace, a propósito:

    * NO toca series que apuntan a instancias de OTROS planes de catálogo. Un alumno puede
      tener N membresías vigentes a la vez (7.1: 4 BJJ + 8 kickboxing) y renovar el pack de
      BJJ no puede reimputar la serie de kickboxing. El filtro `student_plan__plan_id` es
      la definición de "mismo linaje".
    * NO toca series cuya instancia vieja TODAVÍA es usable. Renovar por adelantado (la
      vieja vence mañana, la nueva empieza mañana) deja la serie donde está: mientras la
      elección del alumno siga sirviendo, pisarla sería adivinar. Consecuencia conocida: esa
      serie se va a romper cuando la vieja venza, porque nadie vuelve a correr esto.
    * NO revalida SUCURSAL. El alcance por sede lo manda `plan.branch`
      (`plan_covers_branch`, reservations.py), y vieja y nueva comparten el MISMO `Plan`,
      así que su cobertura de sedes es idéntica por construcción — no hay nada que chequear
      que no fuera ya cierto antes del reapunte.
    """
    def _candidates():
        """Series candidatas: mismo alumno/org/linaje y VIVAS. Factorizado en un closure
        porque el SELECT de abajo y el UPDATE final tienen que compartir EXACTAMENTE el
        mismo WHERE (ver el comentario junto al `.update()` — security review, hallazgo
        BAJO 1)."""
        return (
            RecurringEnrollment.objects
            .filter(
                # La serie es del alumno que renovó.
                student_id=new_student_plan.user_id,
                # Regla 6: NULL = legacy / ambigua del backfill 0036. Esas re-resuelven por
                # instancia y no se tocan.
                student_plan__isnull=False,
                # Regla 1: MISMO plan de catálogo (old.plan_id == new.plan_id).
                student_plan__plan_id=new_student_plan.plan_id,
                # Regla 2: la instancia vieja la vendió la MISMA organización. No es
                # redundante con el filtro de `plan_id`: `StudentPlan.organization` es una
                # COPIA de `plan.organization` hecha al vender y nada revalida las ventas
                # históricas si el plan se mueve de tenant, así que dos instancias del
                # mismo `Plan` pueden tener organizaciones distintas.
                student_plan__organization_id=new_student_plan.organization_id,
                # Regla 2: la instancia vieja es del MISMO alumno. Redundante con
                # `student_id` salvo en filas patológicas (un pin cross-alumno que ninguna
                # API puede crear hoy); explícito para no "repararlas" en silencio cambiando
                # quién paga.
                student_plan__user_id=new_student_plan.user_id,
                # Regla 2: la serie está anclada en la organización de la SUSCRIPCIÓN
                # (`class_template.organization_id`), MISMO criterio que el backfill de
                # 0036 y que `resolve_student_plan_for_recurring_enrollment`
                # (reservations.py). `RecurringEnrollment.student` es CASCADE sobre el
                # USUARIO y no sobre el tenant: filtrar solo por alumno es el agujero
                # multitenant recurrente del proyecto.
                class_template__organization_id=new_student_plan.organization_id,
            )
            # Regla 5: serie VIVA. El corte es la FECHA y no `is_active` — una serie
            # PAUSADA sin `end_date` vencido es reactivable desde "Mis recurrencias" y SÍ
            # cuenta como viva (mismo criterio que 0036). Escrito en POSITIVO y no como
            # `.exclude(end_date__lt=on_date)` para no depender de cómo Django trata los
            # NULL al negar un lookup: `end_date` es nullable y NULL significa "sin
            # término".
            .filter(Q(end_date__isnull=True) | Q(end_date__gte=on_date))
        )

    series = (
        _candidates()
        .select_related('student_plan')
        # `describe_student_plan` resuelve el eje de PAGO recorriendo dos FK inversas: sin
        # esto son 2 consultas por serie. No participa de `is_usable`, pero se paga igual
        # por preguntar el estado.
        .prefetch_related('student_plan__origin_transactions', 'student_plan__manual_payments')
    )

    # "NO usable" se le PREGUNTA a `describe_student_plan` (más arriba en este módulo), la
    # fuente única del predicado —la misma que usan el roster, el serializer y los dos
    # resolvedores de imputación—. No se reimplementa como `filter()`: la mitad de saldo
    # (`unlimited_classes` / `classes_used >= total_classes`) no se puede expresar en SQL
    # sin duplicar la regla, que es exactamente el motivo por el que 0036 y
    # `_usable_student_plan_candidates` también iteran en Python. El volumen es de unidades
    # (series de UN alumno para UN plan).
    stale_ids = [
        recurring.pk for recurring in series
        if not describe_student_plan(recurring.student_plan, on_date).is_usable
    ]
    if not stale_ids:
        return 0
    # `.update()` en bloque y no `save()` fila por fila: una sola sentencia, sin recorrer
    # `full_clean()` (que valida rol/fechas/plantilla, nada de esta FK) y sin señales —el
    # proyecto no tiene NINGÚN receiver registrado—. Mismo instrumento que el backfill de
    # 0036 (`.update(student_plan_id=...)`) y que `cancel_future_instances_for_template`.
    #
    # `pk__in=stale_ids` SOLO no alcanza: entre el SELECT de arriba (`stale_ids`) y este
    # UPDATE no hay lock (§ el diseño lo evita a propósito por el AB-BA con el importador),
    # así que otra transacción pudo reapuntar o cerrar alguna de esas series entremedio.
    # Repetir `_candidates()` re-chequea el WHERE completo AL MOMENTO DEL UPDATE, no al
    # momento del SELECT: si alguna ya no matchea, el UPDATE la deja en paz en vez de
    # pisarla en silencio.
    return _candidates().filter(pk__in=stale_ids).update(
        student_plan=new_student_plan,
        # `auto_now` no corre en un `.update()`; se setea a mano para que la fila no quede
        # con un `updated_at` que miente sobre cuándo cambió su imputación.
        updated_at=timezone.now(),
    )


def activate_student_plan(*, student, plan, start_date, discount_percentage=None,
                          discount_source='', enrollment_fee=None, enrollment_fee_paid_at=None,
                          enrollment_fee_due_at=None):
    # La membresía la vende `plan.organization` y solo la consume un alumno de esa misma
    # organización: `get_active_student_plan` y `my-memberships` filtran por ahí, así que
    # activar un plan ajeno crearía una fila que ningún endpoint muestra ni consume. Mejor
    # fallar que persistir algo inerte —el webhook de pagos entra por este mismo camino y
    # el alumno pudo cambiar de organización entre el checkout y la aprobación—.
    if plan.organization_id != student.organization_id:
        raise PlanOrganizationMismatch(
            'El plan no pertenece a la organización del alumno.'
        )

    purchase_quote = quote_plan_purchase(
        student=student,
        plan=plan,
        on_date=start_date,
        override_discount_percentage=discount_percentage,
    )
    discount = float(purchase_quote.discount_percentage)
    source = discount_source or purchase_quote.discount_source
    end_date = start_date + timedelta(days=max(plan.duration_days - 1, 0))
    final_price = float(purchase_quote.final_amount)
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
        student_plan = StudentPlan.objects.create(
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
            discount_source=source,
            final_price=final_price,
            enrollment_fee=money(enrollment_fee) if enrollment_fee is not None else Decimal('0.00'),
            enrollment_fee_paid_at=enrollment_fee_paid_at,
            enrollment_fee_due_at=enrollment_fee_due_at,
            is_active=True,
        )
        # Reapunte de las series recurrentes del mismo linaje (follow-up de R1). Va ACÁ,
        # DENTRO del mismo atomic y DESPUÉS del INSERT: si algo posterior revienta (p. ej.
        # `record_manual_payment` en el caller, `views.py`), el rollback se lleva la
        # membresía nueva Y el reapunte juntos, y ninguna serie queda apuntando a una
        # membresía que no existe.
        _repoint_recurring_series_to_renewed_membership(
            student_plan, on_date=timezone.localdate(),
        )
        return student_plan
