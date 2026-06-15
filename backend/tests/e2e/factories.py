"""Factories ORM para los E2E.

Crean el estado de dominio (planes, clases, inscripciones, reglas de pago, etc.)
directamente por ORM. Como los E2E corren con ``@pytest.mark.django_db(transaction=True)``,
estos datos quedan COMMITeados y son visibles para el hilo del ``live_server``.

El flujo *observable* (login, reservar, suspender, asistencia, importar, ver pagos)
se ejerce SIEMPRE por HTTP contra el servidor real; las factories solo arman las
precondiciones que en producción ya existirían.
"""
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from core.models import (
    Attendance,
    Branch,
    ConsumptionLog,
    Enrollment,
    GymClass,
    Plan,
    StudentPlan,
    TeacherPaymentRule,
    TrialFollowupConfiguration,
)


def make_branch(org, name='Sede Central'):
    return Branch.objects.create(organization=org, name=name)


def make_plan(org, total_classes, price, unlimited=False, name=None):
    return Plan.objects.create(
        organization=org,
        name=name or f'Plan {total_classes}x{price}',
        plan_type='pack',
        total_classes=total_classes,
        unlimited_classes=unlimited,
        duration_days=30,
        price=price,
    )


def give_student_plan(user, plan, total_classes, price, fee=0, paid=False,
                      unlimited=False, classes_used=0):
    today = timezone.localdate()
    sp = StudentPlan(
        user=user,
        plan=plan,
        start_date=today,
        end_date=today + timedelta(days=30),
        total_classes=total_classes,
        unlimited_classes=unlimited,
        classes_used=classes_used,
        final_price=price,
        enrollment_fee=Decimal(str(fee)),
        is_active=True,
    )
    if paid and fee:
        sp.enrollment_fee_paid_at = timezone.now()
    sp.save()
    return sp


def make_class(org, branch, teacher, *, start, end, status=GymClass.Status.SCHEDULED,
               capacity=10, is_trial_eligible=False, name='Clase'):
    return GymClass.objects.create(
        organization=org,
        branch=branch,
        teacher=teacher,
        name=name,
        start_datetime=start,
        end_datetime=end,
        capacity=capacity,
        status=status,
        is_trial_eligible=is_trial_eligible,
    )


def enroll(gym_class, student, is_trial=False):
    return Enrollment.objects.create(
        gym_class=gym_class, student=student, status='active', is_trial=is_trial,
    )


def consume(student, student_plan, gym_class):
    return ConsumptionLog.objects.create(
        user=student, student_plan=student_plan, class_instance=gym_class,
    )


def make_rule(org, payment_type, amount, teacher, per_plan_price_base=None):
    kwargs = dict(
        organization=org,
        payment_type=payment_type,
        amount=amount,
        is_active=True,
    )
    # per_plan_price_base es NOT NULL con default; solo lo seteamos si aplica
    # (per_plan_price). Para otros tipos dejamos el default del modelo.
    if per_plan_price_base is not None:
        kwargs['per_plan_price_base'] = per_plan_price_base
    rule = TeacherPaymentRule.objects.create(**kwargs)
    rule.teachers.add(teacher)
    return rule


def mark_attendance(gym_class, student, status):
    return Attendance.objects.create(gym_class=gym_class, student=student, status=status)


def trial_config(org, **kwargs):
    return TrialFollowupConfiguration.objects.create(organization=org, **kwargs)


def now():
    return timezone.now()
