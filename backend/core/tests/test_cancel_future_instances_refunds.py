"""P2 #10.1 — `cancel_future_instances_for_template` (core/services/recurrence.py) no
devolvía el consumo de las inscripciones activas al cancelar en bloque las instancias
futuras de una serie: hacía un `queryset.update()` directo sobre `GymClass` sin tocar
ninguna `Enrollment`. El alumno quedaba `active` sobre una clase ya `CANCELLED` y solo
recuperaba el saldo si cancelaba su reserva a mano (deuda que documentaba `views.py`,
guarda de `ClassTemplateViewSet.destroy`, punto 1 antes de este fix).

Este archivo cubre el reembolso + cancelación de `Enrollment` que el fix agrega,
reutilizando el mismo núcleo (`revert_consumption`, vía `cancel_enrollment_with_refund`)
que ya usan los otros tres llamadores.
"""
from datetime import time, timedelta

import pytest
from django.utils import timezone

from core.models import Branch, ClassTemplate, ConsumptionLog, Enrollment, GymClass, Plan, StudentPlan
from core.services.recurrence import cancel_future_instances_for_template

pytestmark = pytest.mark.django_db


@pytest.fixture
def setup(make_organization, make_user):
    org = make_organization()
    teacher = make_user('teach-cfi', organization=org, role='teacher')
    student = make_user('alu-cfi', organization=org, role='student', email='alu-cfi@gym.cl')
    branch = Branch.objects.create(organization=org, name='Sede')
    return {'org': org, 'teacher': teacher, 'student': student, 'branch': branch}


def _template(setup):
    return ClassTemplate.objects.create(
        organization=setup['org'], branch=setup['branch'], teacher=setup['teacher'],
        name='Serie', weekday=0, start_time=time(10, 0), end_time=time(11, 0),
        capacity=10, start_date=timezone.localdate() - timedelta(days=30),
    )


def _class(setup, template, days, status=GymClass.Status.SCHEDULED):
    start = timezone.now() + timedelta(days=days)
    return GymClass.objects.create(
        organization=setup['org'], branch=setup['branch'], teacher=setup['teacher'],
        class_template=template, name='Instancia', start_datetime=start,
        end_datetime=start + timedelta(hours=1), capacity=10, status=status,
    )


def _plan(setup, classes_used=0):
    today = timezone.localdate()
    plan = Plan.objects.create(
        organization=setup['org'], name='Pack 10', plan_type='pack',
        total_classes=10, duration_days=30, price=30000,
    )
    return StudentPlan.objects.create(
        user=setup['student'], plan=plan, organization_id=plan.organization_id,
        start_date=today - timedelta(days=1), end_date=today + timedelta(days=30),
        total_classes=10, classes_used=classes_used, final_price=30000,
    )


def _consume(setup, gym_class, student_plan, status='active'):
    enrollment = Enrollment.objects.create(
        gym_class=gym_class, student=setup['student'], status=status,
        student_plan=student_plan,
    )
    ConsumptionLog.objects.create(
        user=setup['student'], student_plan=student_plan, class_instance=gym_class,
        branch=gym_class.branch,
    )
    return enrollment


def test_cancelling_future_instances_refunds_and_cancels_active_enrollments(setup):
    template = _template(setup)
    gym_class = _class(setup, template, days=2)
    plan = _plan(setup, classes_used=1)
    enrollment = _consume(setup, gym_class, plan)

    summary = cancel_future_instances_for_template(template)

    gym_class.refresh_from_db()
    enrollment.refresh_from_db()
    plan.refresh_from_db()
    assert gym_class.status == GymClass.Status.CANCELLED
    assert enrollment.status == 'cancelled', 'no puede quedar active sobre una clase cancelada'
    assert plan.classes_used == 0, 'debe devolver el saldo'
    assert not ConsumptionLog.objects.filter(class_instance=gym_class).exists()
    assert summary['updated_count'] == 1
    assert summary['cancelled_enrollments'] == 1


def test_a_past_completed_instance_is_not_touched(setup):
    """Solo las instancias FUTURAS SCHEDULED/IN_PROGRESS entran al bloque; una clase
    ya completada no debe cancelarse ni perder su consumo."""
    template = _template(setup)
    past_class = _class(setup, template, days=-2, status=GymClass.Status.COMPLETED)
    plan = _plan(setup, classes_used=1)
    enrollment = _consume(setup, past_class, plan, status='active')

    summary = cancel_future_instances_for_template(template)

    past_class.refresh_from_db()
    enrollment.refresh_from_db()
    plan.refresh_from_db()
    assert past_class.status == GymClass.Status.COMPLETED
    assert enrollment.status == 'active', 'la instancia pasada no se toca'
    assert plan.classes_used == 1, 'no se le devuelve un consumo que no corresponde'
    assert summary['updated_count'] == 0
    assert summary['cancelled_enrollments'] == 0


def test_refund_goes_to_the_fk_plan_with_two_active_plans(setup):
    """Con dos planes vigentes, el reembolso va al que respalda el FK del enrollment,
    no al otro."""
    template = _template(setup)
    gym_class = _class(setup, template, days=1)
    plan_a = _plan(setup, classes_used=1)
    plan_b = _plan(setup, classes_used=0)
    _consume(setup, gym_class, plan_a)

    cancel_future_instances_for_template(template)

    plan_a.refresh_from_db()
    plan_b.refresh_from_db()
    assert plan_a.classes_used == 0
    assert plan_b.classes_used == 0, 'el plan que no respaldaba el consumo no debe alterarse'


def test_cancelling_twice_does_not_double_refund(setup):
    """Idempotencia: una segunda pasada sobre la misma serie no encuentra instancias
    SCHEDULED/IN_PROGRESS que cancelar de nuevo, así que no puede devolver saldo dos
    veces."""
    template = _template(setup)
    gym_class = _class(setup, template, days=1)
    plan = _plan(setup, classes_used=1)
    _consume(setup, gym_class, plan)

    cancel_future_instances_for_template(template)
    plan.refresh_from_db()
    assert plan.classes_used == 0

    second_summary = cancel_future_instances_for_template(template)

    plan.refresh_from_db()
    assert plan.classes_used == 0, 'no puede devolver saldo dos veces'
    assert second_summary['updated_count'] == 0
    assert second_summary['cancelled_enrollments'] == 0


def test_enrollment_without_consumption_is_still_cancelled(setup):
    """Trial o reserva sin plan: no hay nada que reembolsar, pero la inscripción
    igual debe quedar cancelada (no puede sobrevivir active a una clase CANCELLED)."""
    template = _template(setup)
    gym_class = _class(setup, template, days=1)
    enrollment = Enrollment.objects.create(
        gym_class=gym_class, student=setup['student'], status='active', is_trial=True,
    )

    summary = cancel_future_instances_for_template(template)

    enrollment.refresh_from_db()
    assert enrollment.status == 'cancelled'
    assert summary['cancelled_enrollments'] == 1
