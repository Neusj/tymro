"""`get_enrollment_student_plan` (core/services/reservations.py) tiene que ser SIMÉTRICO
con el backfill de `Enrollment.student_plan` (migración 0033): ambos resuelven el mismo
`ConsumptionLog` (mismo match `user`/`class_instance`, mismo desempate `-consumed_at,
-id`), pero el backfill exige además que el `student_plan` del log sea de la MISMA
organización que la clase (`student_plan__organization_id=F('class_instance__organization_id')`).

Sin ese filtro, un `ConsumptionLog` histórico —de antes del fix de scoping multitenant—
cuyo `student_plan` es de OTRA organización (mismo alumno/clase por coincidencia, plan
ajeno) hacía que el helper devolviera, y el reverso de consumo
(`rollback_consumption_for_enrollment`) le reembolsara saldo a, un plan que no es de esta
organización. `None` es el mismo veredicto que ya usa 0033 para ese caso: no hay de dónde
imputar de forma defendible, así que no se inventa un plan ni se toca uno ajeno.
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from core.models import Branch, ConsumptionLog, Enrollment, GymClass, Plan, StudentPlan
from core.services.reservations import get_enrollment_student_plan

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()


@pytest.fixture
def setup(make_organization, make_user):
    org = make_organization()
    other_org = make_organization()
    teacher = make_user('teach-xorg', organization=org, role='teacher')
    student = make_user('alu-xorg', organization=org, role='student', email='alu-xorg@gym.cl')
    branch = Branch.objects.create(organization=org, name='Sede')
    return {'org': org, 'other_org': other_org, 'teacher': teacher, 'student': student, 'branch': branch}


def _class(setup):
    start = timezone.now() + timedelta(hours=48)
    return GymClass.objects.create(
        organization=setup['org'], branch=setup['branch'], teacher=setup['teacher'],
        name='Clase', start_datetime=start, end_datetime=start + timedelta(hours=1),
        capacity=10, status=GymClass.Status.SCHEDULED,
    )


def _student_plan(organization, student):
    plan = Plan.objects.create(
        organization=organization, name='Pack 10', plan_type='pack',
        total_classes=10, duration_days=30, price=30000,
    )
    return StudentPlan.objects.create(
        user=student, plan=plan, organization_id=organization.id,
        start_date=TODAY - timedelta(days=1), end_date=TODAY + timedelta(days=30),
        total_classes=10, classes_used=1, final_price=30000,
    )


def test_returns_the_plan_when_the_log_is_same_org(setup):
    """Caso base: el log matchea y su `student_plan` es de la MISMA organización que la
    clase → el helper lo devuelve (la FK del enrollment sigue NULL, como la deja el
    backfill best-effort; el helper resuelve en caliente)."""
    gym_class = _class(setup)
    enrollment = Enrollment.objects.create(gym_class=gym_class, student=setup['student'])
    student_plan = _student_plan(setup['org'], setup['student'])
    ConsumptionLog.objects.create(
        user=setup['student'], student_plan=student_plan, class_instance=gym_class,
        branch=setup['branch'],
    )

    assert enrollment.student_plan_id is None
    assert get_enrollment_student_plan(enrollment) == student_plan


def test_returns_none_when_the_only_matching_log_is_cross_org(setup):
    """El log matchea por `user`/`class_instance`, pero su `student_plan` es de OTRA
    organización (el escenario que 0033 descarta) → el helper NO puede devolver ese plan
    ajeno; se comporta como si no hubiera log."""
    gym_class = _class(setup)
    enrollment = Enrollment.objects.create(gym_class=gym_class, student=setup['student'])
    cross_org_plan = _student_plan(setup['other_org'], setup['student'])
    ConsumptionLog.objects.create(
        user=setup['student'], student_plan=cross_org_plan, class_instance=gym_class,
        branch=setup['branch'],
    )

    assert get_enrollment_student_plan(enrollment) is None
