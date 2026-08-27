from datetime import datetime, timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from ..models import ClassTemplate, Enrollment, GymClass, Holiday, Organization, RecurringEnrollment
from .reservations import (
    PLAN_RETRYABLE_CODES,
    ReservationRuleError,
    cancel_enrollment_with_refund,
    reservation_window_state_for_class,
    resolve_student_plan_for_class,
    reserve_student_in_class,
    revert_consumption_for_class,
)


def _delete_class_refunding_consumption(gym_class):
    """Borra una instancia devolviendo antes su consumo al saldo del alumno.

    `ConsumptionLog.class_instance` es CASCADE: borrar la clase a secas se lleva los
    consumos sin decrementar `StudentPlan.classes_used`. Las guardas de este módulo
    miran `Enrollment`, no `ConsumptionLog`, así que una clase sin inscripciones activas
    pero con un consumo huérfano (lo deja `DELETE /api/enrollments/`) pasaba el filtro y
    se borraba dejando saldo fantasma.
    """
    revert_consumption_for_class(gym_class)
    gym_class.delete()


TERMINAL_STATUSES = {
    GymClass.Status.CANCELLED,
    GymClass.Status.COMPLETED,
    GymClass.Status.COMPLETED_EARLY,
}


def recurring_skip_reason_for_instance(recurring_enrollment, gym_class):
    existing = Enrollment.objects.filter(
        gym_class=gym_class,
        student=recurring_enrollment.student,
    ).first()
    if existing and existing.status == 'active':
        return None
    if existing and existing.recurring_resync_blocked:
        return 'manual_recurring_cancellation'
    if gym_class.status == GymClass.Status.CANCELLED:
        return 'class_cancelled'
    if gym_class.status == GymClass.Status.SUSPENDED:
        return 'class_suspended'
    if gym_class.status in TERMINAL_STATUSES:
        return 'class_closed'
    if gym_class.start_datetime <= timezone.now():
        return 'class_started'
    if not reservation_window_state_for_class(gym_class)['within_window']:
        return 'outside_window'
    if gym_class.enrollments.filter(status='active').count() >= gym_class.capacity:
        return 'class_full'
    try:
        resolve_student_plan_for_class(
            recurring_enrollment.student,
            gym_class=gym_class,
            student_plan_id=recurring_enrollment.student_plan_id,
        )
    except ReservationRuleError as exc:
        if recurring_enrollment.student_plan_id and exc.code in PLAN_RETRYABLE_CODES:
            try:
                resolve_student_plan_for_class(
                    recurring_enrollment.student,
                    gym_class=gym_class,
                    student_plan_id=None,
                )
            except ReservationRuleError as fallback_exc:
                return fallback_exc.code
            return None
        return exc.code
    return None


def _combine_local_datetime(value_date, value_time):
    naive = datetime.combine(value_date, value_time)
    current_tz = timezone.get_current_timezone()
    return timezone.make_aware(naive, current_tz) if timezone.is_naive(naive) else timezone.localtime(naive, current_tz)


def _as_date(value):
    if value is None:
        return None
    if hasattr(value, 'year') and hasattr(value, 'month') and hasattr(value, 'day') and not isinstance(value, str):
        return value
    if isinstance(value, str):
        return datetime.strptime(value, '%Y-%m-%d').date()
    raise ValueError('Invalid date value')


def _iter_template_dates(template, from_date, until_date):
    if until_date < from_date:
        return
    days_until_target = (template.weekday - from_date.weekday()) % 7
    current = from_date + timedelta(days=days_until_target)
    while current <= until_date:
        yield current
        current += timedelta(days=7)


def materialization_window_cap(organization):
    """Última fecha que se puede MATERIALIZAR para esa organización: `hoy + ventana`.

    La ventana rodante (`Organization.class_generation_window_days`, default 21) reemplaza
    al viejo fallback de 365 días: una serie sin `end_date` ya no crea ~52 filas de
    `GymClass` el día del alta —y, con eso, ya no le descuenta al alumno el año entero por
    adelantado, porque el loop de recurrencia cobra cada instancia que ve—.

    La organización llega SIEMPRE desde el RECURSO (`template.organization`,
    `recurring_enrollment.class_template.organization`), nunca desde input del request:
    ninguna firma pública acepta la ventana desde afuera, así que no hay forma de que un
    cliente pida materializar más lejos que lo que su org tiene configurado (orden 8.3: la
    lectura de config de org queda detrás de las guardas de pertenencia de la view, que ya
    corrieron para poder llegar hasta acá con ese recurso).

    El default del MODELO es la única fuente de verdad del 21: la rama de fallback existe
    solo por defensa (una org sin el atributo cargado, p. ej. un objeto en memoria), y ojo
    con `or` acá —una ventana de 0 días es válida y significa "solo hasta hoy"—.
    """
    days = getattr(organization, 'class_generation_window_days', None)
    if days is None:
        days = Organization._meta.get_field('class_generation_window_days').default
    return timezone.localdate() + timedelta(days=int(days))


def is_holiday(value_date, organization=None, branch=None):
    holiday_query = Holiday.objects.filter(date=value_date, is_active=True)
    holiday_query = holiday_query.filter(
        Holiday.scope_q_global()
        | Holiday.scope_q_organization(organization_id=getattr(organization, 'id', organization))
        | Holiday.scope_q_branch(branch_id=getattr(branch, 'id', branch))
    )
    return holiday_query.exists()


def _create_enrollment_if_possible(*, recurring_enrollment, gym_class):
    """Materializa UNA instancia de la serie imputándola a la membresía que el alumno
    eligió en el alta (10.x).

    `student_plan_id` sale de la suscripción y baja tal cual hasta
    `resolve_student_plan_for_reservation`, que es el único que decide: no hay una segunda
    regla de imputación acá. Las dos ramas:

    * FK NULL (filas legacy y las que el backfill de 0036 dejó ambiguas) → se pasa `None` y
      cada instancia re-resuelve como antes de 10.x: con 1 candidato usable consume, con 2+
      queda `skipped: plan_choice_required`.
    * FK poblada → se consume de ESE plan. Es lo que hace que un alumno con 2+ membresías
      vigentes deje de perder la serie entera: eligió una vez, en el alta.

    CONSECUENCIA VIVA (ya no es la regla general, pero sigue siendo la del CAMINO
    ANTICIPADO): si el plan elegido se agota o vence, la serie salta a la membresía nueva
    del MISMO plan de catálogo en cuanto el alumno renueva —lo hace
    `activate_student_plan` (`services/plans.py`,
    `_repoint_recurring_series_to_renewed_membership`), DENTRO de la misma transacción que
    crea la fila nueva, no este loop—. Lo que sigue sin arreglarse es la renovación
    ANTICIPADA: si la instancia vieja todavía era usable en el momento de renovar, el
    reapunte no la toca (adivinar cuál va a servir sería peor), y esa serie va a volver a
    quedar `skipped: chosen_plan_unavailable` cuando la vieja venza, porque nada vuelve a
    correr el reapunte después. El loop en sí sigue sin adivinar nada: nunca elige, solo
    consume de la FK que ya viene resuelta.
    """
    def _reserve(student_plan_id):
        return reserve_student_in_class(
            student=recurring_enrollment.student,
            gym_class=gym_class,
            recurring_enrollment=recurring_enrollment,
            created_by=recurring_enrollment.created_by,
            require_plan=True,
            student_plan_id=student_plan_id,
        )

    try:
        enrollment = _reserve(recurring_enrollment.student_plan_id)
    except ReservationRuleError as exc:
        if recurring_enrollment.student_plan_id and exc.code in PLAN_RETRYABLE_CODES:
            try:
                enrollment = _reserve(None)
            except ReservationRuleError as fallback_exc:
                return False, fallback_exc.code
            if enrollment.student_plan_id and enrollment.student_plan_id != recurring_enrollment.student_plan_id:
                recurring_enrollment.student_plan_id = enrollment.student_plan_id
                recurring_enrollment.save(update_fields=['student_plan', 'updated_at'])
            return True, None
        return False, exc.code
    return True, None


@transaction.atomic
def create_enrollments_for_recurring_subscription(recurring_enrollment, class_instances=None, from_date=None, until_date=None):
    if not recurring_enrollment.is_active:
        return {'created_count': 0, 'skipped': [{'reason': 'inactive_recurring_enrollment'}]}

    template = recurring_enrollment.class_template
    effective_from = from_date or recurring_enrollment.start_date
    effective_from = max(effective_from, recurring_enrollment.start_date, template.start_date)

    # Normalizado a `date` antes de compararlo: abajo entra en un `min()` contra el tope de
    # la ventana, y un `until_date` string —que el `filter(...__lte=...)` de la ORM aceptaba
    # tal cual— reventaría ahí con TypeError.
    effective_until = _as_date(until_date) if until_date is not None else None
    if recurring_enrollment.end_date:
        effective_until = min(effective_until, recurring_enrollment.end_date) if effective_until else recurring_enrollment.end_date
    if template.end_date:
        effective_until = min(effective_until, template.end_date) if effective_until else template.end_date

    # Con `class_instances` explícitas NO se re-filtra por ventana: las trae
    # `sync_recurring_enrollments_for_generated_instances` con lo que acaba de crear
    # `generate_instances_for_template_range`, que ya nace dentro de la ventana (Pieza A).
    queryset = class_instances
    if queryset is None:
        # El universo del loop se topea con la ventana rodante de la org de la SERIE
        # (`class_template.organization`, el recurso; nunca input del request). Sin esto,
        # el alta de la recurrencia y el "reactivar" del alumno barrían TODAS las
        # instancias ya materializadas de la plantilla —incluidas las que dejó el
        # horizonte viejo de 365 días— y cobraban cada una por adelantado.
        window_cap = materialization_window_cap(template.organization)
        horizon = min(effective_until, window_cap) if effective_until else window_cap
        queryset = GymClass.objects.filter(class_template=template)
        queryset = queryset.filter(start_datetime__date__gte=effective_from)
        queryset = queryset.filter(start_datetime__date__lte=horizon)

    summary = {'created_count': 0, 'skipped': []}
    for gym_class in queryset:
        class_date = timezone.localtime(gym_class.start_datetime).date()
        if class_date < recurring_enrollment.start_date:
            summary['skipped'].append({'class_id': gym_class.id, 'reason': 'before_subscription_start'})
            continue
        if recurring_enrollment.end_date and class_date > recurring_enrollment.end_date:
            summary['skipped'].append({'class_id': gym_class.id, 'reason': 'after_subscription_end'})
            continue
        created, reason = _create_enrollment_if_possible(recurring_enrollment=recurring_enrollment, gym_class=gym_class)
        if created:
            summary['created_count'] += 1
        else:
            summary['skipped'].append({'class_id': gym_class.id, 'reason': reason})

    return summary


def sync_recurring_enrollments_for_generated_instances(template, class_instances):
    recurring_items = RecurringEnrollment.objects.filter(class_template=template, is_active=True).select_related('student')
    for recurring_enrollment in recurring_items:
        create_enrollments_for_recurring_subscription(
            recurring_enrollment=recurring_enrollment,
            class_instances=class_instances,
        )


@transaction.atomic
def generate_instances_for_template_range(template, from_date=None, until_date=None, created_by=None, skip_holidays=True):
    parsed_from = _as_date(from_date) if from_date is not None else None
    parsed_until = _as_date(until_date) if until_date is not None else None

    effective_from = max(template.start_date, parsed_from or timezone.localdate())
    # La ventana rodante de la org es el TOPE de todo el rail de materialización: manda el
    # MÁS CORTO entre `until_date` (input ya validado del caller), `template.end_date` y
    # `hoy + ventana`. Reemplaza al fallback de 365 días —que era lo que convertía un alta
    # de serie en ~52 clases y ~52 consumos por adelantado—, y aplica a TODOS los callers
    # (alta de plantilla, `POST .../generate/`, `generate_pending`, la regeneración de
    # `apply_template_updates_to_future_instances` y el importador): que la ventana no se
    # pueda pedir por parámetro es a propósito.
    #
    # Consecuencia buscada: una plantilla que arranca DESPUÉS de la ventana no materializa
    # nada todavía (`effective_until < effective_from` → summary vacío, sin error). Sus
    # clases van a aparecer cuando la ventana avance hasta ellas.
    candidates = [materialization_window_cap(template.organization)]
    if parsed_until is not None:
        candidates.append(parsed_until)
    if template.end_date:
        candidates.append(template.end_date)
    effective_until = min(candidates)

    summary = {'created_count': 0, 'created_ids': [], 'skipped': []}
    if not template.is_active:
        summary['skipped'].append({'reason': 'inactive_template'})
        return summary
    if effective_until < effective_from:
        return summary

    for occurrence_date in _iter_template_dates(template, effective_from, effective_until):
        if skip_holidays and is_holiday(occurrence_date, organization=template.organization_id, branch=template.branch_id):
            summary['skipped'].append({'date': occurrence_date.isoformat(), 'reason': 'holiday'})
            continue

        if GymClass.objects.filter(class_template=template, start_datetime__date=occurrence_date).exists():
            summary['skipped'].append({'date': occurrence_date.isoformat(), 'reason': 'duplicate_instance'})
            continue

        start_datetime = _combine_local_datetime(occurrence_date, template.start_time)
        end_datetime = _combine_local_datetime(occurrence_date, template.end_time)

        # Tarea 11.A: el solape de profesor ya no saltea la generación (el producto
        # decidió permitirlo). Acá vivía el chequeo `_has_teacher_conflict`.

        # El `exists()` de arriba NO alcanza: entre ese SELECT y este INSERT hay una
        # ventana en la que otro escritor (el cron `advance_class_windows`, el botón
        # "Actualizar clases", otra tab, otro admin) puede haber creado la misma
        # instancia. El `atomic` exterior no serializa nada —ambas transacciones ven la
        # tabla sin la fila del otro—, así que el desempate lo hace la BD con
        # `uniq_class_instance_per_template_slot` y acá solo se recoge el resultado.
        #
        # CRÍTICO: el `atomic()` INTERNO no es decorativo. Es un savepoint: sin él,
        # capturar IntegrityError dentro del atomic exterior deja la transacción de
        # Postgres abortada ("current transaction is aborted") y TODA query posterior del
        # loop revienta. Con el savepoint, solo se descarta el INSERT fallido.
        #
        # El perdedor de la carrera no suma a `created_ids` → su instancia no entra al
        # sync de recurrencias de abajo → no se le descuenta saldo al alumno por una
        # clase que el ganador ya cobró. Es exactamente el comportamiento buscado: pierde
        # limpio, y el resultado observable es el mismo `duplicate_instance` que reporta
        # la guarda optimista.
        try:
            with transaction.atomic():
                gym_class = GymClass.objects.create(
                    organization=template.organization,
                    class_template=template,
                    branch=template.branch,
                    teacher=template.teacher,
                    class_type=template.class_type,
                    discipline=template.discipline,
                    name=template.name or (template.class_type.name if template.class_type else f'Clase {template.get_weekday_display()}'),
                    start_datetime=start_datetime,
                    end_datetime=end_datetime,
                    capacity=template.capacity,
                    is_trial_eligible=template.is_trial_eligible,
                    status=GymClass.Status.SCHEDULED,
                    created_by=created_by or template.created_by,
                    is_active=True,
                    # P4 #A: la instancia nueva hereda el suplente default de la serie. Mismo
                    # tratamiento que el resto de los campos de plantilla en este `create`.
                    has_substitute=template.has_substitute,
                    substitute_name=template.substitute_name,
                    substitute_teacher=template.substitute_teacher,
                    substitution_source=template.substitution_source,
                    substitution_assigned_at=template.substitution_assigned_at,
                    substitution_assigned_by=template.substitution_assigned_by,
                )
        except IntegrityError:
            summary['skipped'].append({'date': occurrence_date.isoformat(), 'reason': 'duplicate_instance'})
            continue

        summary['created_count'] += 1
        summary['created_ids'].append(gym_class.id)

    if summary['created_ids']:
        instances = list(GymClass.objects.filter(id__in=summary['created_ids']).order_by('start_datetime'))
        sync_recurring_enrollments_for_generated_instances(template=template, class_instances=instances)

    return summary


@transaction.atomic
def apply_template_updates_to_future_instances(template, now=None):
    now = now or timezone.now()
    future_instances = GymClass.objects.filter(
        class_template=template,
        start_datetime__gt=now,
    ).exclude(status__in=TERMINAL_STATUSES)

    summary = {'updated_count': 0, 'protected_count': 0, 'protected_ids': []}
    for gym_class in future_instances:
        has_active_enrollments = gym_class.enrollments.filter(status='active').exists()
        if has_active_enrollments:
            summary['protected_count'] += 1
            summary['protected_ids'].append(gym_class.id)
            continue

        class_date = timezone.localtime(gym_class.start_datetime).date()
        if class_date < template.start_date:
            _delete_class_refunding_consumption(gym_class)
            continue
        if template.end_date and class_date > template.end_date:
            _delete_class_refunding_consumption(gym_class)
            continue
        if class_date.weekday() != template.weekday:
            _delete_class_refunding_consumption(gym_class)
            continue
        if is_holiday(class_date, organization=template.organization_id, branch=template.branch_id):
            _delete_class_refunding_consumption(gym_class)
            continue

        gym_class.name = template.name or gym_class.name
        gym_class.branch = template.branch
        gym_class.teacher = template.teacher
        gym_class.class_type = template.class_type
        gym_class.discipline = template.discipline
        gym_class.capacity = template.capacity
        gym_class.is_trial_eligible = template.is_trial_eligible
        gym_class.start_datetime = _combine_local_datetime(class_date, template.start_time)
        gym_class.end_datetime = _combine_local_datetime(class_date, template.end_time)
        # P4 #A: mismo contrato que `is_trial_eligible` — editar la serie reescribe el
        # suplente en las instancias futuras sin inscritos activos.
        gym_class.has_substitute = template.has_substitute
        gym_class.substitute_name = template.substitute_name
        gym_class.substitute_teacher = template.substitute_teacher
        gym_class.substitution_source = template.substitution_source
        gym_class.substitution_assigned_at = template.substitution_assigned_at
        gym_class.substitution_assigned_by = template.substitution_assigned_by

        # Tarea 11.A: el solape de profesor ya no protege la instancia de la
        # actualización (el producto decidió permitirlo). Acá vivía el chequeo
        # `_has_teacher_conflict`.

        gym_class.save(
            update_fields=[
                'name',
                'branch',
                'teacher',
                'class_type',
                'discipline',
                'capacity',
                'is_trial_eligible',
                'start_datetime',
                'end_datetime',
                'has_substitute',
                'substitute_name',
                'substitute_teacher',
                'substitution_source',
                'substitution_assigned_at',
                'substitution_assigned_by',
                'updated_at',
            ]
        )
        summary['updated_count'] += 1

    regeneration = generate_instances_for_template_range(
        template=template,
        from_date=max(timezone.localdate(), template.start_date),
        until_date=template.end_date,
        created_by=template.created_by,
    )
    summary['regeneration'] = regeneration
    return summary


def can_delete_template(template):
    instances = GymClass.objects.filter(class_template=template)
    if RecurringEnrollment.objects.filter(class_template=template).exists():
        return False, 'La serie tiene recurrencias de alumnos asociadas.'
    if instances.filter(enrollments__isnull=False).exists():
        return False, 'La serie tiene clases con alumnos inscritos o historial de reservas.'
    if instances.filter(attendances__isnull=False).exists():
        return False, 'La serie tiene asistencia registrada.'
    if instances.filter(status__in=[GymClass.Status.COMPLETED, GymClass.Status.COMPLETED_EARLY]).exists():
        return False, 'La serie tiene historial consolidado.'
    return True, None


@transaction.atomic
def delete_template_safely(template):
    can_delete, reason = can_delete_template(template)
    if not can_delete:
        return {'deleted': False, 'reason': reason}

    # Instancia por instancia y no un `.delete()` en bloque: cada una tiene que devolver
    # su consumo antes de que la cascada se lleve el ConsumptionLog. `can_delete_template`
    # mira Enrollment, así que un consumo huérfano llega hasta acá.
    for gym_class in GymClass.objects.filter(class_template=template):
        _delete_class_refunding_consumption(gym_class)
    template.delete()
    return {'deleted': True}


@transaction.atomic
def cancel_future_instances_for_template(template, actor=None, comment='Cancelacion masiva de serie'):
    """Cancela en bloque las instancias futuras SCHEDULED/IN_PROGRESS de la serie Y
    devuelve el consumo de sus inscripciones activas (10.1).

    El `.update()` de abajo cambia el `status` de las clases a CANCELLED en una sola
    sentencia SQL, sin pasar por ningún reverso: antes de este fix, las `Enrollment`
    activas de esas instancias quedaban `active` sobre una clase ya `CANCELLED` y el
    alumno solo recuperaba el saldo si cancelaba su reserva a mano (deuda que
    documentaba `views.py`, guarda de `ClassTemplateViewSet.destroy`).

    Los ids se materializan ANTES del `.update()` y el `.update()` corre sobre ESE
    snapshot (`GymClass.objects.filter(id__in=instance_ids)`), no sobre el queryset
    original re-evaluado: si se re-evaluara, una instancia que otra transacción
    concurrente commiteó entre el SELECT y el UPDATE (p. ej. una regeneración de la
    serie que crea/reprograma una clase a SCHEDULED en el mismo rango) quedaría
    CANCELLED por este `.update()` sin haber estado en `instance_ids` — se cancela algo
    que nunca se reembolsa. Fijar el `.update()` al snapshot garantiza que "lo que se
    cancela" y "lo que se busca para reembolsar" sean EXACTAMENTE el mismo conjunto de
    ids, sin ventana entre ambas lecturas.

    El reembolso usa `cancel_enrollment_with_refund` —el mismo camino que ya usa la
    cancelación individual de una clase, `_refund_active_enrollments_for_cancelled_class`
    en views.py—: reembolsa vía el núcleo unificado (`revert_consumption`, FK primero,
    con lock) y deja la inscripción `cancelled`. El `select_related('gym_class')` lee
    la clase DESPUÉS del `.update()` de arriba, así que ya ve el status CANCELLED
    nuevo y `should_refund_consumption` lo detecta sin depender de la fecha de la
    clase.
    """
    now = timezone.now()
    instance_ids = list(
        GymClass.objects.filter(
            class_template=template,
            start_datetime__gt=now,
            status__in=[GymClass.Status.SCHEDULED, GymClass.Status.IN_PROGRESS],
        ).values_list('id', flat=True)
    )
    updated_count = GymClass.objects.filter(id__in=instance_ids).update(
        status=GymClass.Status.CANCELLED,
        is_active=False,
        closure_comment=comment,
        closed_by=actor if actor else None,
        closed_at=now,
    )

    cancelled_enrollments = 0
    active_enrollments = Enrollment.objects.filter(
        gym_class_id__in=instance_ids, status='active',
    ).select_related('gym_class')
    for enrollment in active_enrollments:
        cancel_enrollment_with_refund(enrollment)
        cancelled_enrollments += 1

    return {'updated_count': updated_count, 'cancelled_enrollments': cancelled_enrollments}


@transaction.atomic
def activate_template(template):
    if template.is_active:
        return {'updated': False, 'reason': 'already_active'}
    template.is_active = True
    template.save(update_fields=['is_active', 'updated_at'])
    return {'updated': True}


@transaction.atomic
def reactivate_future_cancelled_instances_for_template(template):
    now = timezone.now()
    cancelled_instances = GymClass.objects.filter(
        class_template=template,
        status=GymClass.Status.CANCELLED,
        start_datetime__gt=now,
    )

    summary = {'reactivated_count': 0, 'skipped': []}
    for gym_class in cancelled_instances:
        if gym_class.attendances.exists():
            summary['skipped'].append({'id': gym_class.id, 'reason': 'has_attendance'})
            continue
        if gym_class.closed_at and gym_class.closed_at <= now:
            summary['skipped'].append({'id': gym_class.id, 'reason': 'already_closed_in_past'})
            continue
        if template.end_date and timezone.localtime(gym_class.start_datetime).date() > template.end_date:
            summary['skipped'].append({'id': gym_class.id, 'reason': 'outside_template_range'})
            continue
        if is_holiday(
            timezone.localtime(gym_class.start_datetime).date(),
            organization=template.organization_id,
            branch=template.branch_id,
        ):
            summary['skipped'].append({'id': gym_class.id, 'reason': 'holiday'})
            continue
        # Tarea 11.A: el solape de profesor ya no saltea la reactivación (el producto
        # decidió permitirlo). Acá vivía el chequeo `_has_teacher_conflict`.

        gym_class.status = GymClass.Status.SCHEDULED
        gym_class.is_active = True
        gym_class.closed_at = None
        gym_class.closed_by = None
        gym_class.closure_comment = ''
        gym_class.save(update_fields=['status', 'is_active', 'closed_at', 'closed_by', 'closure_comment', 'updated_at'])
        summary['reactivated_count'] += 1

    return summary
