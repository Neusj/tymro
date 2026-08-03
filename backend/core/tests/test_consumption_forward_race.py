"""9.3 — lock en la IDA del consumo (simétrico a `test_consumption_revert_race.py`).

`consume_student_plan_for_enrollment` hacía read-modify-write en memoria
(`student_plan.classes_used += 1; student_plan.save(...)`). Dos reservas "concurrentes"
que consumen el MISMO plan (dos pestañas del mismo alumno, o dos alumnos con planes
distintos comparten técnica) cada una parte de su PROPIA instancia en memoria —el
snapshot que cargó ANTES de que la otra transacción escribiera:

    A: fetch student_plan (classes_used=0)   B: fetch student_plan (classes_used=0)
    A: classes_used = 0+1 = 1; save()        B: classes_used = 0+1 = 1; save()  <- pisa a A

El segundo `save()` pisa al primero con su copia vieja y el alumno se queda con una clase
gratis. El fix reemplaza el read-modify-write por un `UPDATE ... SET classes_used =
classes_used + 1` (expresión `F()`, igual que ya hace `_revert_consumption_logs` para el
reverso) más un lock de fila (`select_for_update`) que serializa a los competidores. La
carrera real necesita dos conexiones y SQLite serializa las escrituras, así que acá se
simula el escenario determinísticamente: dos instancias Python del MISMO `StudentPlan`,
cada una con su propio snapshot en memoria, para probar que el UPDATE final no sale de
ninguno de los dos snapshots sino de la base.
"""
from datetime import timedelta

import pytest
from django.db.models.query import QuerySet
from django.utils import timezone

from core.models import Branch, Enrollment, GymClass, Plan, StudentPlan
from core.services.reservations import consume_student_plan_for_enrollment

pytestmark = pytest.mark.django_db


@pytest.fixture
def two_enrollments_same_plan(make_organization, make_user):
    """Un alumno, UN plan, y dos inscripciones activas a clases distintas -- el escenario
    mínimo donde dos consumos "concurrentes" compiten por el mismo `StudentPlan`. Dos
    clases distintas (no la misma) porque `ConsumptionLog` es `get_or_create` por
    (user, class_instance, student_plan): la misma clase dos veces sería un duplicado, no
    una carrera sobre el saldo."""
    org = make_organization()
    teacher = make_user('teach-fwd', organization=org, role='teacher')
    student = make_user('alu-fwd', organization=org, role='student', email='alu-fwd@gym.cl')
    branch = Branch.objects.create(organization=org, name='Sede')
    today = timezone.localdate()
    plan = Plan.objects.create(
        organization=org, name='Pack 10', plan_type='pack',
        total_classes=10, duration_days=30, price=30000,
    )
    student_plan = StudentPlan.objects.create(
        user=student, plan=plan, organization_id=plan.organization_id,
        start_date=today - timedelta(days=1), end_date=today + timedelta(days=30),
        total_classes=10, classes_used=0, final_price=30000,
    )

    def _future_class(days):
        start = timezone.now() + timedelta(days=days)
        return GymClass.objects.create(
            organization=org, branch=branch, teacher=teacher, name='Clase',
            start_datetime=start, end_datetime=start + timedelta(hours=1), capacity=10,
        )

    enrollment_a = Enrollment.objects.create(gym_class=_future_class(1), student=student, status='active')
    enrollment_b = Enrollment.objects.create(gym_class=_future_class(2), student=student, status='active')

    return {
        'student_plan': student_plan,
        'enrollment_a': enrollment_a,
        'enrollment_b': enrollment_b,
    }


def test_two_concurrent_consumptions_on_the_same_plan_do_not_lose_a_count(two_enrollments_same_plan):
    """Dos snapshots en memoria del MISMO `StudentPlan` (el que cada transacción "concurrente"
    cargó antes de que la otra escribiera), consumidos en secuencia: el `+1` de la primera
    no puede perderse cuando llega la segunda. Con el read-modify-write viejo, la segunda
    pisaba con su copia vieja (`classes_used` terminaba en 1, no en 2)."""
    plan_snapshot_1 = StudentPlan.objects.get(pk=two_enrollments_same_plan['student_plan'].pk)
    plan_snapshot_2 = StudentPlan.objects.get(pk=two_enrollments_same_plan['student_plan'].pk)
    assert plan_snapshot_1.classes_used == plan_snapshot_2.classes_used == 0

    assert consume_student_plan_for_enrollment(two_enrollments_same_plan['enrollment_a'], plan_snapshot_1)
    assert consume_student_plan_for_enrollment(two_enrollments_same_plan['enrollment_b'], plan_snapshot_2)

    two_enrollments_same_plan['student_plan'].refresh_from_db()
    assert two_enrollments_same_plan['student_plan'].classes_used == 2, 'ningún +1 se puede perder'
    # El snapshot en memoria de cada llamador tampoco puede quedar mintiendo tras el
    # refresh que hace la propia función.
    assert plan_snapshot_1.classes_used == 1
    assert plan_snapshot_2.classes_used == 2


def test_consume_takes_a_lock_on_the_chosen_student_plan(two_enrollments_same_plan, monkeypatch):
    """El camino del consumo pide `select_for_update` sobre el `StudentPlan` elegido --
    el mismo patrón que `_revert_consumption_logs` ya usa para serializar a los
    competidores en el reverso."""
    original_select_for_update = QuerySet.select_for_update
    locked_models = []

    def _spy(self, *args, **kwargs):
        locked_models.append(self.model)
        return original_select_for_update(self, *args, **kwargs)

    monkeypatch.setattr(QuerySet, 'select_for_update', _spy)

    consume_student_plan_for_enrollment(
        two_enrollments_same_plan['enrollment_a'], two_enrollments_same_plan['student_plan']
    )

    assert StudentPlan in locked_models, 'debe lockear el StudentPlan elegido antes de sumar el consumo'
