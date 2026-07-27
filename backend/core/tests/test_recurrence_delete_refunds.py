"""Los borrados de clases que hace el módulo de series también deben devolver el saldo.

`GymClassViewSet.perform_destroy` ya revierte el consumo antes de borrar, pero
`core/services/recurrence.py` borra instancias por su cuenta (al reencuadrar una serie
y al eliminarla) y esos caminos cascadeaban el `ConsumptionLog` sin tocar
`StudentPlan.classes_used`: el mismo saldo fantasma, por la puerta de la serie.

Las guardas de esos caminos miran `Enrollment`, no `ConsumptionLog`, así que el estado
peligroso es un consumo sin inscripción activa — alcanzable hoy con
`DELETE /api/enrollments/{id}/`, que borra la inscripción y deja el log vivo.
"""
from datetime import time, timedelta

import pytest
from django.utils import timezone

from core.models import Branch, ClassTemplate, ConsumptionLog, GymClass, Plan, StudentPlan

pytestmark = pytest.mark.django_db


@pytest.fixture
def setup(make_organization, make_user):
    org = make_organization()
    teacher = make_user('teach', organization=org, role='teacher')
    student = make_user('alu', organization=org, role='student', email='alu@gym.cl')
    branch = Branch.objects.create(organization=org, name='Sede')
    return {'org': org, 'teacher': teacher, 'student': student, 'branch': branch}


def _template(setup, weekday):
    return ClassTemplate.objects.create(
        organization=setup['org'], branch=setup['branch'], teacher=setup['teacher'],
        name='Serie', weekday=weekday, start_time=time(10, 0), end_time=time(11, 0),
        capacity=10, start_date=timezone.localdate() - timedelta(days=30),
    )


def _orphan_consumption(setup, gym_class):
    """Un consumo SIN inscripción activa: el estado que ciega las guardas de series.
    Lo produce hoy `DELETE /api/enrollments/{id}/`, que no toca el ConsumptionLog."""
    today = timezone.localdate()
    plan = Plan.objects.create(
        organization=setup['org'], name='Pack 10', plan_type='pack',
        total_classes=10, duration_days=30, price=30000,
    )
    student_plan = StudentPlan.objects.create(
        user=setup['student'], plan=plan, start_date=today - timedelta(days=1),
        end_date=today + timedelta(days=30), total_classes=10, classes_used=1,
        final_price=30000,
    )
    ConsumptionLog.objects.create(
        user=setup['student'], student_plan=student_plan, class_instance=gym_class,
        branch=gym_class.branch,
    )
    return student_plan


def _assert_no_phantom(student_plan):
    student_plan.refresh_from_db()
    backing = ConsumptionLog.objects.filter(student_plan=student_plan).count()
    assert student_plan.classes_used == backing, (
        f'saldo fantasma: classes_used={student_plan.classes_used} pero hay '
        f'{backing} consumo(s) que lo respalden'
    )


def test_reframing_a_series_refunds_deleted_instances(setup):
    """Al mover la serie a otro día, las instancias que ya no encajan se borran: su
    consumo tiene que volver al saldo del alumno."""
    from core.services.recurrence import apply_template_updates_to_future_instances

    template = _template(setup, weekday=0)
    start = timezone.now() + timedelta(days=2)
    gym_class = GymClass.objects.create(
        organization=setup['org'], branch=setup['branch'], teacher=setup['teacher'],
        class_template=template, name='Instancia', start_datetime=start,
        end_datetime=start + timedelta(hours=1), capacity=10,
    )
    student_plan = _orphan_consumption(setup, gym_class)

    # La plantilla pasa a un weekday que la instancia no cumple → se borra.
    template.weekday = (timezone.localtime(start).weekday() + 1) % 7
    template.save(update_fields=['weekday'])
    apply_template_updates_to_future_instances(template)

    assert not GymClass.objects.filter(id=gym_class.id).exists(), 'precondición: se borró'
    student_plan.refresh_from_db()
    assert student_plan.classes_used == 0
    _assert_no_phantom(student_plan)


def test_deleting_a_series_refunds_its_instances(setup):
    """`delete_template_safely` borra las instancias en bloque; su guarda mira
    Enrollment, así que un consumo huérfano pasaba y se perdía el saldo."""
    from core.services.recurrence import delete_template_safely

    template = _template(setup, weekday=0)
    start = timezone.now() + timedelta(days=2)
    gym_class = GymClass.objects.create(
        organization=setup['org'], branch=setup['branch'], teacher=setup['teacher'],
        class_template=template, name='Instancia', start_datetime=start,
        end_datetime=start + timedelta(hours=1), capacity=10,
    )
    student_plan = _orphan_consumption(setup, gym_class)

    result = delete_template_safely(template)

    assert result['deleted'] is True, result
    assert not GymClass.objects.filter(id=gym_class.id).exists()
    student_plan.refresh_from_db()
    assert student_plan.classes_used == 0
    _assert_no_phantom(student_plan)
