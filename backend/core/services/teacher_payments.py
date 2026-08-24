from django.db.models import Count, Q

from ..models import (
    Attendance,
    ConsumptionLog,
    Enrollment,
    GymClass,
    PersonalizedClassSession,
    TeacherPaymentRecord,
    TeacherPaymentRule,
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


def calculate_teacher_payment(class_instance):
    if not class_instance or not isinstance(class_instance, GymClass):
        return None, False
    if class_instance.status not in {GymClass.Status.COMPLETED, GymClass.Status.COMPLETED_EARLY}:
        return None, False
    if not class_instance.teacher_id:
        return None, False

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
        return None, False

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

    record, created = TeacherPaymentRecord.objects.get_or_create(
        teacher_id=class_instance.teacher_id,
        class_instance=class_instance,
        defaults={
            'rule': rule,
            'total_students': int(total_students),
            'total_amount': round(float(total_amount), 2),
        },
    )
    if not created:
        record.rule = rule
        record.total_students = int(total_students)
        record.total_amount = round(float(total_amount), 2)
        record.save(update_fields=['rule', 'total_students', 'total_amount', 'updated_at'])
    return record, created


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

    def _ensure(tid, teacher_obj=None):
        row = rows.get(tid)
        if row is None:
            row = {
                'teacher_id': tid,
                'teacher_name': _teacher_display_name(teacher_obj),
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
                start_datetime__date__gte=date_from,
                start_datetime__date__lte=date_to,
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
            class_instance__start_datetime__date__gte=date_from,
            class_instance__start_datetime__date__lte=date_to,
        ).select_related('rule')
        if teacher_id:
            records_qs = records_qs.filter(teacher_id=teacher_id)
        record_by_class = {r.class_instance_id: r for r in records_qs}

        for gym_class in classes_qs:
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
                status=PersonalizedClassSession.Status.CONFIRMED,
                teacher__isnull=False,
                confirmed_at__date__gte=date_from,
                confirmed_at__date__lte=date_to,
            )
            .select_related('teacher', 'student', 'discipline', 'class_type')
        )
        if teacher_id:
            personalized_qs = personalized_qs.filter(teacher_id=teacher_id)

        for session in personalized_qs:
            row = _ensure(session.teacher_id, session.teacher)
            row['classes_count'] += 1
            row['personalized_classes_count'] += 1
            row['attendees_total'] += 1 if session.student_id else 0
            row['classes'].append(
                {
                    'id': session.id,
                    'name': 'Clase personalizada',
                    'start': session.confirmed_at,
                    'attendees': 1 if session.student_id else 0,
                    'amount': 0.0,
                    'payment_type': None,
                    'class_kind': 'personalized',
                    'student_id': session.student_id,
                    'student_name': _teacher_display_name(session.student) if session.student_id else '',
                    'discipline_name': session.discipline.name if session.discipline_id else '',
                    'class_type_name': session.class_type.name if session.class_type_id else '',
                }
            )

    # --- Sueldo mensual fijo (fuente: reglas monthly_fixed activas; NO hay records) ---
    months = _months_between(date_from, date_to)
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
            row['monthly_total'] += float(rule.amount) * months
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
