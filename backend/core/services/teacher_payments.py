from django.db.models import Q

from ..models import Attendance, ConsumptionLog, Enrollment, GymClass, TeacherPaymentRecord, TeacherPaymentRule


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
    if rule.calculation_base == TeacherPaymentRule.CalculationBase.ENROLLMENT:
        return Enrollment.objects.filter(gym_class=class_instance, status='active').count()
    return Attendance.objects.filter(gym_class=class_instance, status=Attendance.Status.PRESENT).count()


def _calculate_revenue_for_class(class_instance):
    logs = ConsumptionLog.objects.select_related('student_plan').filter(class_instance=class_instance)
    total_revenue = 0.0
    for log in logs:
        student_plan = getattr(log, 'student_plan', None)
        if not student_plan:
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
