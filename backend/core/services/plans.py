"""Activación/renovación de StudentPlan. Fuente única de verdad usada por la
acción admin `assign` y por el webhook de pagos."""
from datetime import timedelta

from django.db import transaction

from core.models import StudentPlan


def activate_student_plan(*, student, plan, start_date, discount_percentage=None):
    discount = discount_percentage if discount_percentage is not None else (plan.discount_percentage or 0)
    end_date = start_date + timedelta(days=max(plan.duration_days - 1, 0))
    final_price = max(float(plan.price) * (1 - (discount / 100)), 0)
    with transaction.atomic():
        StudentPlan.objects.filter(user=student, is_active=True).update(is_active=False)
        return StudentPlan.objects.create(
            user=student, plan=plan,
            start_date=start_date, end_date=end_date,
            total_classes=plan.total_classes,
            unlimited_classes=plan.unlimited_classes,
            discount_percentage=discount,
            final_price=final_price,
            is_active=True,
        )
