from datetime import datetime

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from ..models import (
    Attendance,
    ConsumptionLog,
    Enrollment,
    GymClass,
    PersonalizedClassSession,
    TeacherPaymentCalculationBatch,
    TeacherPaymentRecord,
    TeacherPayout,
    TeacherPaymentRule,
    TEACHER_ELIGIBLE_ROLES,
)
from .teacher_payment_cycles import (
    cycle_start_day_for_selected_month,
    is_full_calendar_month,
    payment_period_for_teacher,
)


def _match_rule_for_class(rules, class_instance):
    exact_branch_discipline = rules.filter(branch_id=class_instance.branch_id, discipline_id=class_instance.discipline_id).first()
    if exact_branch_discipline:
        return exact_branch_discipline

    exact_branch_type = rules.filter(branch_id=class_instance.branch_id, class_type_id=class_instance.class_type_id).first()
    if exact_branch_type:
        return exact_branch_type

    branch_only = rules.filter(branch_id=class_instance.branch_id, discipline__isnull=True, class_type__isnull=True).first()
    if branch_only:
        return branch_only

    discipline_only = rules.filter(branch__isnull=True, discipline_id=class_instance.discipline_id).first()
    if discipline_only:
        return discipline_only

    class_type_only = rules.filter(branch__isnull=True, class_type_id=class_instance.class_type_id).first()
    if class_type_only:
        return class_type_only

    return rules.filter(branch__isnull=True, discipline__isnull=True, class_type__isnull=True).first()


def _count_students_for_rule(class_instance, rule):
    if rule.payment_type == TeacherPaymentRule.PaymentType.FIXED_PER_CLASS:
        return 0
    if rule.payment_type == TeacherPaymentRule.PaymentType.PER_STUDENT:
        return Attendance.objects.filter(gym_class=class_instance, status=Attendance.Status.PRESENT).count()
    if rule.payment_type == TeacherPaymentRule.PaymentType.PER_ENROLLED:
        return Enrollment.objects.filter(gym_class=class_instance, status='active').count()
    if rule.payment_type == TeacherPaymentRule.PaymentType.PER_HOUR:
        return Attendance.objects.filter(gym_class=class_instance, status=Attendance.Status.PRESENT).count()
    if rule.payment_type == TeacherPaymentRule.PaymentType.PER_PLAN_PRICE:
        if rule.per_plan_price_base == TeacherPaymentRule.PerPlanPriceBase.PRESENT_ATTENDEES:
            return Attendance.objects.filter(gym_class=class_instance, status=Attendance.Status.PRESENT).count()
        return Enrollment.objects.filter(gym_class=class_instance, status='active').count()
    if rule.calculation_base == TeacherPaymentRule.CalculationBase.ENROLLMENT:
        return Enrollment.objects.filter(gym_class=class_instance, status='active').count()
    return Attendance.objects.filter(gym_class=class_instance, status=Attendance.Status.PRESENT).count()


def _class_hours(class_instance):
    start = class_instance.start_datetime
    end = class_instance.end_datetime
    if not start or not end:
        return 0.0
    seconds = (end - start).total_seconds()
    if seconds <= 0:
        return 0.0
    return seconds / 3600.0


def _calculate_revenue_for_class(class_instance):
    logs = ConsumptionLog.objects.select_related(
        'student_plan', 'student_plan__organization'
    ).filter(class_instance=class_instance)
    total_revenue = 0.0
    for log in logs:
        student_plan = getattr(log, 'student_plan', None)
        if not student_plan:
            continue
        # TODO(pagos-profesores): la política de revenue-share para planes ILIMITADOS
        # está pendiente de definir. No existe un "precio por clase" derivable
        # (no hay total_classes finito), y usar divisor=1 inflaría el ingreso por clase.
        # Hasta cerrar la política en el módulo de pagos a profesores, los consumos de
        # planes ilimitados se EXCLUYEN de la base de ingreso automática (no aportan).
        if student_plan.unlimited_classes:
            continue
        # Plan gratuito (build free-plans): `final_price` es 0 y dividirlo por
        # `total_classes` pagaría $0 al profesor, lo cual es incorrecto. Se usa DIRECTO
        # el valor de clase gratis configurado por la organización (NO se divide: es un
        # valor POR CLASE, no el precio del plan completo). Criterio "gratis" es
        # `discount_percentage == 100`, NO `final_price == 0` (ese campo puede quedar
        # NULL en registros legacy y no se quiere enganchar ese caso).
        # La organización sale de `student_plan.organization` (FK propia, copiada del
        # plan al vender) y NO de `student_plan.plan.organization`: ese join al catálogo
        # ya causó fugas cross-tenant en este repo (ver `fk-propia-sin-organizacion`).
        if float(student_plan.discount_percentage or 0) == 100:
            total_revenue += float(student_plan.organization.free_class_teacher_payment_value or 0)
            continue
        final_price = float(student_plan.final_price or 0)
        total_classes = int(student_plan.total_classes or 0)
        divisor = total_classes if total_classes > 0 else 1
        total_revenue += final_price / float(divisor)
    return total_revenue


def _calculate_plan_price_revenue_for_class(class_instance, base):
    """Suma del 'precio por clase' (final_price / total_classes) de los planes de
    los alumnos de la base elegida, excluyendo planes ilimitados.

    base == PRESENT_ATTENDEES -> solo alumnos marcados presentes.
    base == ACTIVE_ENROLLMENTS -> todos los alumnos con inscripción activa.

    Misma política de 'precio por clase' que revenue_share; la diferencia es el
    CONJUNTO de alumnos que aporta (inscritos vs presentes). El plan de cada
    alumno se resuelve por el ConsumptionLog real de ESTA clase.
    """
    if base == TeacherPaymentRule.PerPlanPriceBase.PRESENT_ATTENDEES:
        student_ids = set(
            Attendance.objects.filter(
                gym_class=class_instance, status=Attendance.Status.PRESENT
            ).values_list('student_id', flat=True)
        )
    else:
        student_ids = set(
            Enrollment.objects.filter(
                gym_class=class_instance, status='active'
            ).values_list('student_id', flat=True)
        )
    if not student_ids:
        return 0.0

    logs = (
        ConsumptionLog.objects.select_related('student_plan', 'student_plan__organization')
        .filter(class_instance=class_instance, user_id__in=student_ids)
        .order_by('user_id', '-consumed_at', '-id')
    )
    total_revenue = 0.0
    seen_users = set()
    for log in logs:
        if log.user_id in seen_users:
            continue
        seen_users.add(log.user_id)
        student_plan = getattr(log, 'student_plan', None)
        if not student_plan or student_plan.unlimited_classes:
            continue
        # Plan gratuito (build free-plans): mismo criterio y misma razón que en
        # `_calculate_revenue_for_class` (arriba) — valor de clase gratis de la org
        # DIRECTO, sin dividir por `total_classes`, por `discount_percentage == 100` y
        # no por `final_price == 0`. Org sale de `student_plan.organization` (FK propia).
        if float(student_plan.discount_percentage or 0) == 100:
            total_revenue += float(student_plan.organization.free_class_teacher_payment_value or 0)
            continue
        final_price = float(student_plan.final_price or 0)
        total_classes = int(student_plan.total_classes or 0)
        divisor = total_classes if total_classes > 0 else 1
        total_revenue += final_price / float(divisor)
    return total_revenue


def _payment_values_for_class(class_instance):
    if not class_instance or not isinstance(class_instance, GymClass):
        return None
    if class_instance.status not in {GymClass.Status.COMPLETED, GymClass.Status.COMPLETED_EARLY}:
        return None
    if not class_instance.teacher_id:
        return None

    active_rules = TeacherPaymentRule.objects.filter(
        organization_id=class_instance.organization_id,
        is_active=True,
    ).filter(
        Q(teachers__id=class_instance.teacher_id) | Q(teacher_id=class_instance.teacher_id)
    )
    # El sueldo mensual fijo no genera record por clase; se resuelve a nivel periodo en la agregacion.
    active_rules = active_rules.exclude(payment_type=TeacherPaymentRule.PaymentType.MONTHLY_FIXED)
    active_rules = active_rules.filter(Q(branch__isnull=True) | Q(branch_id=class_instance.branch_id))
    active_rules = active_rules.filter(Q(discipline__isnull=True) | Q(discipline_id=class_instance.discipline_id))
    active_rules = active_rules.filter(Q(class_type__isnull=True) | Q(class_type_id=class_instance.class_type_id))
    active_rules = active_rules.order_by('-id').distinct()
    rule = _match_rule_for_class(active_rules, class_instance)
    if not rule:
        return None

    total_students = _count_students_for_rule(class_instance, rule)
    if rule.payment_type == TeacherPaymentRule.PaymentType.FIXED_PER_CLASS:
        total_amount = float(rule.amount)
    elif rule.payment_type == TeacherPaymentRule.PaymentType.PER_STUDENT:
        total_amount = float(total_students) * float(rule.amount)
    elif rule.payment_type == TeacherPaymentRule.PaymentType.PER_ENROLLED:
        total_amount = float(total_students) * float(rule.amount)
    elif rule.payment_type == TeacherPaymentRule.PaymentType.PER_HOUR:
        total_amount = _class_hours(class_instance) * float(rule.amount)
    elif rule.payment_type == TeacherPaymentRule.PaymentType.PER_PLAN_PRICE:
        revenue = _calculate_plan_price_revenue_for_class(class_instance, rule.per_plan_price_base)
        total_amount = float(revenue) * (float(rule.amount) / 100.0)
    else:
        revenue = _calculate_revenue_for_class(class_instance)
        total_amount = float(revenue) * (float(rule.amount) / 100.0)

    return {
        'rule': rule,
        'total_students': int(total_students),
        'total_amount': round(float(total_amount), 2),
    }


def calculate_teacher_payment(class_instance, calculation_batch=None):
    values = _payment_values_for_class(class_instance)
    if values is None:
        return None, False

    record = TeacherPaymentRecord.objects.filter(
        teacher_id=class_instance.teacher_id,
        class_instance=class_instance,
        is_voided=False,
    ).first()
    created = record is None
    if created:
        record = TeacherPaymentRecord.objects.create(
            teacher_id=class_instance.teacher_id,
            class_instance=class_instance,
            rule=values['rule'],
            total_students=values['total_students'],
            total_amount=values['total_amount'],
            calculation_batch=calculation_batch,
        )
    else:
        record.rule = values['rule']
        record.total_students = values['total_students']
        record.total_amount = values['total_amount']
        if calculation_batch is not None:
            record.calculation_batch = calculation_batch
        update_fields = ['rule', 'total_students', 'total_amount', 'updated_at']
        if calculation_batch is not None:
            update_fields.append('calculation_batch')
        record.save(update_fields=update_fields)
    return record, created


def _completed_normal_classes(organization_id, date_from, date_to, teacher_id=None):
    queryset = (
        GymClass.objects.filter(
            organization_id=organization_id,
            status__in=[GymClass.Status.COMPLETED, GymClass.Status.COMPLETED_EARLY],
            teacher__isnull=False,
            start_datetime__date__gte=date_from,
            start_datetime__date__lte=date_to,
        )
        .select_related('teacher', 'branch', 'discipline', 'class_type')
        .order_by('start_datetime', 'id')
    )
    if teacher_id:
        queryset = queryset.filter(teacher_id=teacher_id)
    return queryset


def _teacher_periods_for_request(organization_id, date_from, date_to, teacher_id=None):
    User = get_user_model()
    queryset = User.objects.filter(
        organization_id=organization_id,
        role__in=TEACHER_ELIGIBLE_ROLES,
    )
    if teacher_id:
        queryset = queryset.filter(id=teacher_id)

    full_month = is_full_calendar_month(date_from, date_to)
    periods = {}
    for teacher in queryset:
        period_start, period_end = payment_period_for_teacher(teacher, date_from, date_to)
        cycle_start_day = (
            cycle_start_day_for_selected_month(teacher, date_from.year, date_from.month)
            if full_month else None
        )
        periods[teacher.id] = {
            'date_from': period_start,
            'date_to': period_end,
            'cycle_start_day': cycle_start_day,
            'monthly_units': 1 if full_month else _months_between(date_from, date_to),
        }
    return periods


def _query_bounds_for_periods(periods, date_from, date_to):
    if not periods:
        return date_from, date_to
    starts = [period['date_from'] for period in periods.values()]
    ends = [period['date_to'] for period in periods.values()]
    return min(starts), max(ends)


def _period_contains(period, value):
    if value is None:
        return False
    if isinstance(value, datetime):
        value_date = timezone.localtime(value).date() if value.tzinfo else value.date()
    else:
        value_date = value
    return period['date_from'] <= value_date <= period['date_to']


def _period_paid_teacher_ids(organization_id, date_from):
    return set(
        TeacherPayout.objects.filter(
            organization_id=organization_id,
            period_year=date_from.year,
            period_month=date_from.month,
        ).values_list('teacher_id', flat=True)
    )


def _active_records_by_class(organization_id, date_from, date_to, teacher_id=None):
    queryset = TeacherPaymentRecord.objects.filter(
        class_instance__organization_id=organization_id,
        class_instance__start_datetime__date__gte=date_from,
        class_instance__start_datetime__date__lte=date_to,
        is_voided=False,
    )
    if teacher_id:
        queryset = queryset.filter(teacher_id=teacher_id)
    return {record.class_instance_id: record for record in queryset}


def _calculation_candidates(organization_id, date_from, date_to, mode, teacher_id=None):
    if mode not in {
        TeacherPaymentCalculationBatch.Mode.MISSING,
        TeacherPaymentCalculationBatch.Mode.RECALCULATE_PENDING,
    }:
        raise ValueError('Modo de calculo invalido.')

    paid_teacher_ids = _period_paid_teacher_ids(organization_id, date_from)
    teacher_periods = _teacher_periods_for_request(organization_id, date_from, date_to, teacher_id=teacher_id)
    query_from, query_to = _query_bounds_for_periods(teacher_periods, date_from, date_to)
    active_records = _active_records_by_class(organization_id, query_from, query_to, teacher_id=teacher_id)
    skipped_paid_teachers = set()
    skipped_existing = 0
    skipped_no_rule = 0
    candidates = []
    total_amount = 0.0

    for gym_class in _completed_normal_classes(organization_id, query_from, query_to, teacher_id=teacher_id):
        period = teacher_periods.get(gym_class.teacher_id)
        if period is None or not _period_contains(period, gym_class.start_datetime):
            continue
        if gym_class.teacher_id in paid_teacher_ids:
            skipped_paid_teachers.add(gym_class.teacher_id)
            continue
        active_record = active_records.get(gym_class.id)
        has_record = active_record is not None
        if mode == TeacherPaymentCalculationBatch.Mode.MISSING and has_record:
            skipped_existing += 1
            continue

        values = _payment_values_for_class(gym_class)
        if values is None:
            skipped_no_rule += 1
            continue

        item = {
            'class_id': gym_class.id,
            'teacher_id': gym_class.teacher_id,
            'teacher_name': _teacher_display_name(gym_class.teacher),
            'class_name': gym_class.name,
            'start': gym_class.start_datetime.isoformat() if gym_class.start_datetime else None,
            'period': {
                'date_from': period['date_from'].isoformat(),
                'date_to': period['date_to'].isoformat(),
            },
            'action': 'update' if has_record else 'create',
            'rule_id': values['rule'].id,
            'payment_type': values['rule'].payment_type,
            'total_students': values['total_students'],
            'total_amount': values['total_amount'],
        }
        if active_record is not None:
            item.update({
                'record_id': active_record.id,
                'previous_rule_id': active_record.rule_id,
                'previous_total_students': active_record.total_students,
                'previous_total_amount': round(float(active_record.total_amount), 2),
                'previous_calculation_batch_id': active_record.calculation_batch_id,
            })
        candidates.append(item)
        total_amount += float(values['total_amount'])

    records_created = sum(1 for item in candidates if item['action'] == 'create')
    records_updated = sum(1 for item in candidates if item['action'] == 'update')
    return {
        'mode': mode,
        'period': {'date_from': date_from.isoformat(), 'date_to': date_to.isoformat()},
        'uses_teacher_cycles': is_full_calendar_month(date_from, date_to),
        'classes_count': len(candidates),
        'records_created_count': records_created,
        'records_updated_count': records_updated,
        'skipped_paid_teachers_count': len(skipped_paid_teachers),
        'skipped_existing_count': skipped_existing,
        'skipped_no_rule_count': skipped_no_rule,
        'total_amount': round(total_amount, 2),
        'items': candidates,
    }


def preview_teacher_payment_calculation(organization_id, date_from, date_to, mode, teacher_id=None):
    return _calculation_candidates(organization_id, date_from, date_to, mode, teacher_id=teacher_id)


@transaction.atomic
def run_teacher_payment_calculation(organization_id, date_from, date_to, mode, actor, teacher_id=None):
    preview = _calculation_candidates(organization_id, date_from, date_to, mode, teacher_id=teacher_id)
    batch = TeacherPaymentCalculationBatch.objects.create(
        organization_id=organization_id,
        period_start=date_from,
        period_end=date_to,
        mode=mode,
        created_by=actor if getattr(actor, 'is_authenticated', False) else None,
        classes_count=preview['classes_count'],
        records_created_count=preview['records_created_count'],
        records_updated_count=preview['records_updated_count'],
        skipped_paid_teachers_count=preview['skipped_paid_teachers_count'],
        skipped_existing_count=preview['skipped_existing_count'],
        skipped_no_rule_count=preview['skipped_no_rule_count'],
        total_amount=preview['total_amount'],
        metadata={'items': preview['items']},
    )

    created_count = 0
    updated_count = 0
    for item in preview['items']:
        gym_class = GymClass.objects.select_for_update().get(
            id=item['class_id'],
            organization_id=organization_id,
        )
        record, created = calculate_teacher_payment(gym_class, calculation_batch=batch)
        if record is None:
            continue
        if created:
            created_count += 1
        else:
            updated_count += 1

    batch.records_created_count = created_count
    batch.records_updated_count = updated_count
    batch.save(update_fields=['records_created_count', 'records_updated_count', 'updated_at'])
    return batch


@transaction.atomic
def void_teacher_payment_batch(batch, actor, reason=''):
    if batch.status == TeacherPaymentCalculationBatch.Status.VOIDED:
        return batch, 0

    items = list((batch.metadata or {}).get('items') or [])
    teacher_ids = {item.get('teacher_id') for item in items if item.get('teacher_id')}
    if teacher_ids and TeacherPayout.objects.filter(
        organization_id=batch.organization_id,
        period_year=batch.period_start.year,
        period_month=batch.period_start.month,
        teacher_id__in=teacher_ids,
    ).exists():
        raise ValueError('No puedes anular este lote porque ya hay profesores pagados en el periodo.')

    now = timezone.now()
    voided_count = 0
    for item in items:
        record = (
            TeacherPaymentRecord.objects.select_for_update()
            .filter(
                teacher_id=item.get('teacher_id'),
                class_instance_id=item.get('class_id'),
                calculation_batch=batch,
                is_voided=False,
            )
            .first()
        )
        if record is None:
            continue
        if item.get('action') == 'update':
            record.rule_id = item.get('previous_rule_id')
            record.total_students = int(item.get('previous_total_students') or 0)
            record.total_amount = round(float(item.get('previous_total_amount') or 0), 2)
            record.calculation_batch_id = item.get('previous_calculation_batch_id')
            record.save(update_fields=[
                'rule',
                'total_students',
                'total_amount',
                'calculation_batch',
                'updated_at',
            ])
            continue
        record.is_voided = True
        record.voided_at = now
        record.voided_by = actor if getattr(actor, 'is_authenticated', False) else None
        record.void_reason = reason
        record.save(update_fields=['is_voided', 'voided_at', 'voided_by', 'void_reason', 'updated_at'])
        voided_count += 1
    batch.status = TeacherPaymentCalculationBatch.Status.VOIDED
    batch.voided_at = now
    batch.voided_by = actor if getattr(actor, 'is_authenticated', False) else None
    batch.void_reason = reason
    batch.records_voided_count = voided_count
    batch.save(update_fields=[
        'status',
        'voided_at',
        'voided_by',
        'void_reason',
        'records_voided_count',
        'updated_at',
    ])
    return batch, voided_count


def _months_between(date_from, date_to):
    """Cantidad de meses calendario que toca el rango [date_from, date_to] inclusive.
    Un periodo de un solo mes = 1. Sin prorrateo de rangos parciales."""
    if date_to < date_from:
        return 0
    return (date_to.year - date_from.year) * 12 + (date_to.month - date_from.month) + 1


def _teacher_display_name(teacher):
    if teacher is None:
        return '-'
    full_name = f'{teacher.first_name} {teacher.last_name}'.strip()
    return full_name or teacher.username


def build_teacher_payment_summary(organization_id, date_from, date_to, teacher_id=None, class_kind=None):
    """Agrega el pago por profesor en un periodo, combinando:
    - clases dictadas + asistentes reales (desde GymClass / Attendance),
    - monto acumulado por clase (desde TeacherPaymentRecord),
    - sueldo mensual fijo (desde reglas monthly_fixed, no genera records por clase).

    Filtra SIEMPRE por organizacion y por FECHA DE LA CLASE (no calculated_at).
    Devuelve {'period', 'rows', 'grand_total'}.
    """
    completed = [GymClass.Status.COMPLETED, GymClass.Status.COMPLETED_EARLY]
    rows = {}
    include_normal = class_kind in (None, 'normal')
    include_personalized = class_kind in (None, 'personalized')
    teacher_periods = _teacher_periods_for_request(organization_id, date_from, date_to, teacher_id=teacher_id)
    query_from, query_to = _query_bounds_for_periods(teacher_periods, date_from, date_to)

    def _ensure(tid, teacher_obj=None):
        row = rows.get(tid)
        period = teacher_periods.get(tid, {
            'date_from': date_from,
            'date_to': date_to,
            'cycle_start_day': None,
            'monthly_units': _months_between(date_from, date_to),
        })
        if row is None:
            row = {
                'teacher_id': tid,
                'teacher_name': _teacher_display_name(teacher_obj),
                'period': {
                    'date_from': period['date_from'].isoformat(),
                    'date_to': period['date_to'].isoformat(),
                },
                'payment_cycle_start_day': period['cycle_start_day'],
                'monthly_units': period['monthly_units'],
                'classes_count': 0,
                'normal_classes_count': 0,
                'personalized_classes_count': 0,
                'attendees_total': 0,
                'per_class_total': 0.0,
                'monthly_total': 0.0,
                'modalities': set(),
                'classes': [],
            }
            rows[tid] = row
        elif teacher_obj is not None and row['teacher_name'] == '-':
            row['teacher_name'] = _teacher_display_name(teacher_obj)
        return row

    if include_normal:
        # --- Clases dictadas + asistentes (fuente: GymClass) ---
        classes_qs = (
            GymClass.objects.filter(
                organization_id=organization_id,
                status__in=completed,
                teacher__isnull=False,
                start_datetime__date__gte=query_from,
                start_datetime__date__lte=query_to,
            )
            .select_related('teacher')
            .annotate(present_count=Count('attendances', filter=Q(attendances__status=Attendance.Status.PRESENT)))
        )
        if teacher_id:
            classes_qs = classes_qs.filter(teacher_id=teacher_id)

        # --- Monto por clase (fuente: TeacherPaymentRecord, mismo periodo por fecha de clase) ---
        records_qs = TeacherPaymentRecord.objects.filter(
            class_instance__organization_id=organization_id,
            class_instance__status__in=completed,
            class_instance__start_datetime__date__gte=query_from,
            class_instance__start_datetime__date__lte=query_to,
            is_voided=False,
        ).select_related('rule', 'class_instance')
        if teacher_id:
            records_qs = records_qs.filter(teacher_id=teacher_id)
        record_by_class = {}
        for record in records_qs:
            period = teacher_periods.get(record.teacher_id)
            if period and _period_contains(period, record.class_instance.start_datetime):
                record_by_class[record.class_instance_id] = record

        for gym_class in classes_qs:
            period = teacher_periods.get(gym_class.teacher_id)
            if period is None or not _period_contains(period, gym_class.start_datetime):
                continue
            row = _ensure(gym_class.teacher_id, gym_class.teacher)
            row['classes_count'] += 1
            row['normal_classes_count'] += 1
            row['attendees_total'] += int(gym_class.present_count or 0)
            record = record_by_class.get(gym_class.id)
            amount = round(float(record.total_amount), 2) if record else 0.0
            payment_type = record.rule.payment_type if (record and record.rule_id) else None
            if payment_type:
                row['modalities'].add(payment_type)
            row['per_class_total'] += amount
            row['classes'].append(
                {
                    'id': gym_class.id,
                    'name': gym_class.name,
                    'start': gym_class.start_datetime,
                    'attendees': int(gym_class.present_count or 0),
                    'amount': amount,
                    'payment_type': payment_type,
                    'class_kind': 'normal',
                }
            )

    if include_personalized:
        personalized_qs = (
            PersonalizedClassSession.objects.filter(
                organization_id=organization_id,
                status=PersonalizedClassSession.Status.FINISHED,
                teacher__isnull=False,
                finished_at__date__gte=query_from,
                finished_at__date__lte=query_to,
            )
            .select_related('teacher', 'student', 'discipline', 'class_type')
        )
        if teacher_id:
            personalized_qs = personalized_qs.filter(teacher_id=teacher_id)

        for session in personalized_qs:
            period = teacher_periods.get(session.teacher_id)
            if period is None or not _period_contains(period, session.finished_at):
                continue
            row = _ensure(session.teacher_id, session.teacher)
            row['classes_count'] += 1
            row['personalized_classes_count'] += 1
            row['attendees_total'] += 1 if session.student_id else 0
            row['classes'].append(
                {
                    'id': session.id,
                    'name': 'Clase personalizada',
                    'start': session.finished_at,
                    'attendees': 1 if session.student_id else 0,
                    'amount': 0.0,
                    'payment_type': None,
                    'class_kind': 'personalized',
                    'confirmed_at': session.confirmed_at,
                    'finished_at': session.finished_at,
                    'student_id': session.student_id,
                    'student_name': _teacher_display_name(session.student) if session.student_id else '',
                    'discipline_name': session.discipline.name if session.discipline_id else '',
                    'class_type_name': session.class_type.name if session.class_type_id else '',
                }
            )

    # --- Sueldo mensual fijo (fuente: reglas monthly_fixed activas; NO hay records) ---
    monthly_rules = TeacherPaymentRule.objects.none()
    if class_kind is None:
        monthly_rules = (
            TeacherPaymentRule.objects.filter(
                organization_id=organization_id,
                is_active=True,
                payment_type=TeacherPaymentRule.PaymentType.MONTHLY_FIXED,
            )
            .prefetch_related('teachers')
            .select_related('teacher')
        )
    for rule in monthly_rules:
        assigned_ids = set(rule.teachers.values_list('id', flat=True))
        if rule.teacher_id:
            assigned_ids.add(rule.teacher_id)
        for tid in assigned_ids:
            if teacher_id and str(tid) != str(teacher_id):
                continue
            row = _ensure(tid)
            row['monthly_total'] += float(rule.amount) * row['monthly_units']
            row['modalities'].add(TeacherPaymentRule.PaymentType.MONTHLY_FIXED)

    # Resolver nombres faltantes (profes solo-mensual sin clases en el periodo)
    missing_names = [tid for tid, row in rows.items() if row['teacher_name'] == '-']
    if missing_names:
        from accounts.models import CustomUser

        for teacher in CustomUser.objects.filter(id__in=missing_names):
            rows[teacher.id]['teacher_name'] = _teacher_display_name(teacher)

    result_rows = []
    grand_total = 0.0
    for row in rows.values():
        per_class_total = round(row['per_class_total'], 2)
        monthly_total = round(row['monthly_total'], 2)
        total = round(per_class_total + monthly_total, 2)
        grand_total += total
        row['classes'].sort(key=lambda c: (c['start'] is None, c['start']))
        result_rows.append(
            {
                'teacher_id': row['teacher_id'],
                'teacher_name': row['teacher_name'],
                'period': row['period'],
                'payment_cycle_start_day': row['payment_cycle_start_day'],
                'classes_count': row['classes_count'],
                'normal_classes_count': row['normal_classes_count'],
                'personalized_classes_count': row['personalized_classes_count'],
                'attendees_total': row['attendees_total'],
                'per_class_total': per_class_total,
                'monthly_total': monthly_total,
                'total': total,
                'modalities': sorted(row['modalities']),
                'classes': row['classes'],
            }
        )

    result_rows.sort(key=lambda r: (-r['total'], r['teacher_name'].lower()))

    return {
        'period': {'date_from': date_from.isoformat(), 'date_to': date_to.isoformat()},
        'rows': result_rows,
        'grand_total': round(grand_total, 2),
    }
