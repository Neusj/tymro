"""P2 #10.1 — reverso de consumo unificado: un núcleo (`revert_consumption`), cuatro
llamadores. Este archivo cubre el núcleo nuevo directamente; los cuatro llamadores ya
tienen su propia cobertura de integración:

- `rollback_consumption_for_enrollment` (cancelar) -> `test_class_cancel_refund.py`.
- `revert_consumption_for_enrollment` (DELETE enrollment) -> `test_enrollment_destroy_refunds.py`.
- `revert_consumption_for_class` (DELETE clase) -> `test_class_delete_guard.py` /
  `test_branch_delete_guard.py` / `test_recurrence_delete_refunds.py`.
- `cancel_future_instances_for_template` -> `test_cancel_future_instances_refunds.py`.

`revert_consumption` resuelve QUÉ `StudentPlan` respalda una inscripción con la misma
prioridad que consolidó #9: el FK `Enrollment.student_plan` manda; el helper
`get_enrollment_student_plan` (inferencia por `ConsumptionLog`, cross-org-safe) es
SOLO fallback cuando el FK es NULL.
"""
from datetime import timedelta

import pytest
from django.db.models.query import QuerySet
from django.utils import timezone

from core.models import Branch, ConsumptionLog, Enrollment, GymClass, Plan, StudentPlan
from core.services import reservations as reservations_service
from core.services.reservations import revert_consumption

pytestmark = pytest.mark.django_db


@pytest.fixture
def setup(make_organization, make_user):
    org = make_organization()
    other_org = make_organization()
    teacher = make_user('teach-rc', organization=org, role='teacher')
    student = make_user('alu-rc', organization=org, role='student', email='alu-rc@gym.cl')
    branch = Branch.objects.create(organization=org, name='Sede')
    return {'org': org, 'other_org': other_org, 'teacher': teacher, 'student': student, 'branch': branch}


def _future_class(setup, days=1):
    start = timezone.now() + timedelta(days=days)
    return GymClass.objects.create(
        organization=setup['org'], branch=setup['branch'], teacher=setup['teacher'],
        name='Clase', start_datetime=start, end_datetime=start + timedelta(hours=1),
        capacity=10, status=GymClass.Status.SCHEDULED,
    )


def _plan(setup, organization=None, classes_used=0):
    today = timezone.localdate()
    org = organization or setup['org']
    plan = Plan.objects.create(
        organization=org, name='Pack 10', plan_type='pack',
        total_classes=10, duration_days=30, price=30000,
    )
    return StudentPlan.objects.create(
        user=setup['student'], plan=plan, organization_id=org.id,
        start_date=today - timedelta(days=1), end_date=today + timedelta(days=30),
        total_classes=10, classes_used=classes_used, final_price=30000,
    )


def _consume(setup, gym_class, student_plan):
    """Inscripción con su consumo ya registrado y el FK de imputación seteado, como
    la deja `reserve_student_in_class` (#9)."""
    enrollment = Enrollment.objects.create(
        gym_class=gym_class, student=setup['student'], status='active',
        student_plan=student_plan,
    )
    ConsumptionLog.objects.create(
        user=setup['student'], student_plan=student_plan, class_instance=gym_class,
        branch=gym_class.branch,
    )
    return enrollment


def test_refund_goes_to_the_fk_plan_not_the_other_active_plan(setup, monkeypatch):
    """Alumno con DOS planes vigentes: el consumo real fue contra el plan A (FK +
    log). El reverso debe bajar A y no tocar B — y ni siquiera debe consultar el
    fallback (`get_enrollment_student_plan`), porque el FK ya resuelve."""
    gym_class = _future_class(setup)
    plan_a = _plan(setup, classes_used=1)
    plan_b = _plan(setup, classes_used=0)  # segundo plan vigente, sin consumo
    enrollment = _consume(setup, gym_class, plan_a)
    assert enrollment.student_plan_id == plan_a.id

    def _fail_if_called(_enrollment):
        raise AssertionError('no debe consultarse el fallback cuando el FK ya resuelve')

    monkeypatch.setattr(reservations_service, 'get_enrollment_student_plan', _fail_if_called)

    reverted = revert_consumption(enrollment)

    assert reverted == 1
    plan_a.refresh_from_db()
    plan_b.refresh_from_db()
    assert plan_a.classes_used == 0, 'se devuelve al plan del FK'
    assert plan_b.classes_used == 0, 'el otro plan vigente no se toca'


def test_falls_back_to_helper_when_fk_is_null(setup):
    """Fila anterior al backfill (#9): FK NULL. El reverso debe caer al helper
    `get_enrollment_student_plan`, que infiere por el `ConsumptionLog`."""
    gym_class = _future_class(setup)
    plan = _plan(setup, classes_used=1)
    enrollment = Enrollment.objects.create(gym_class=gym_class, student=setup['student'], status='active')
    ConsumptionLog.objects.create(
        user=setup['student'], student_plan=plan, class_instance=gym_class, branch=gym_class.branch,
    )
    assert enrollment.student_plan_id is None

    reverted = revert_consumption(enrollment)

    assert reverted == 1
    plan.refresh_from_db()
    assert plan.classes_used == 0


def test_cross_org_log_with_null_fk_is_not_refunded(setup):
    """FK NULL y el único log que matchea (alumno, clase) es de OTRA organización: el
    helper devuelve `None` (ver `test_get_enrollment_student_plan_cross_org.py`) y el
    núcleo no debe inventar ni tocar un plan ajeno."""
    gym_class = _future_class(setup)
    cross_org_plan = _plan(setup, organization=setup['other_org'], classes_used=1)
    enrollment = Enrollment.objects.create(gym_class=gym_class, student=setup['student'], status='active')
    ConsumptionLog.objects.create(
        user=setup['student'], student_plan=cross_org_plan, class_instance=gym_class,
        branch=gym_class.branch,
    )

    reverted = revert_consumption(enrollment)

    assert reverted == 0
    cross_org_plan.refresh_from_db()
    assert cross_org_plan.classes_used == 1, 'no se toca el plan de otra organización'


def test_fk_pointing_to_a_cross_org_plan_is_not_refunded(setup):
    """Defensa en profundidad: si el FK `enrollment.student_plan` llegara a apuntar a
    un plan de OTRA organización -- invariante que hoy sostienen todos los escritores
    del FK (la resolución de #9 y el backfill org-scopeado de la migración 0033), pero
    que un escritor futuro podría romper en silencio-- el núcleo NO debe reembolsar
    cross-org. El escenario se fuerza con un `.update()` directo (bypassea `save()` y
    cualquier validación de modelo) para probar la RED del filtro
    (`student_plan__organization_id=F('class_instance__organization_id')`), no la
    invariante que ya sostienen los escritores reales."""
    gym_class = _future_class(setup)
    cross_org_plan = _plan(setup, organization=setup['other_org'], classes_used=1)
    enrollment = Enrollment.objects.create(gym_class=gym_class, student=setup['student'], status='active')
    Enrollment.objects.filter(id=enrollment.id).update(student_plan=cross_org_plan)
    enrollment.refresh_from_db()
    ConsumptionLog.objects.create(
        user=setup['student'], student_plan=cross_org_plan, class_instance=gym_class,
        branch=gym_class.branch,
    )
    assert enrollment.student_plan_id == cross_org_plan.id, 'precondición: FK roto a propósito'

    reverted = revert_consumption(enrollment)

    assert reverted == 0, 'el filtro org-scopeado no debe matchear el log cross-org'
    cross_org_plan.refresh_from_db()
    assert cross_org_plan.classes_used == 1, 'no se toca el plan de otra organización'


def test_no_plan_no_log_is_a_noop(setup):
    """Reserva sin plan (`require_plan=False`) o trial: FK NULL y sin log. No hay
    nada que revertir."""
    gym_class = _future_class(setup)
    enrollment = Enrollment.objects.create(gym_class=gym_class, student=setup['student'], status='active')

    assert revert_consumption(enrollment) == 0


def test_revert_consumption_is_idempotent(setup):
    """Revertir dos veces el mismo consumo (p. ej. cancelar y volver a intentar el
    reverso) devuelve el saldo UNA sola vez."""
    gym_class = _future_class(setup)
    plan = _plan(setup, classes_used=1)
    enrollment = _consume(setup, gym_class, plan)

    first = revert_consumption(enrollment)
    second = revert_consumption(enrollment)

    assert first == 1
    assert second == 0, 'el segundo reverso no encuentra log: no puede devolver saldo de nuevo'
    plan.refresh_from_db()
    assert plan.classes_used == 0


def test_explicit_student_plan_overrides_the_fk(setup):
    """El parámetro `student_plan`, si el llamador lo pasa, pisa tanto al FK como al
    fallback -- para el llamador que ya lo tiene resuelto en memoria."""
    gym_class = _future_class(setup)
    plan_a = _plan(setup, classes_used=1)
    plan_b = _plan(setup, classes_used=1)
    enrollment = Enrollment.objects.create(
        gym_class=gym_class, student=setup['student'], status='active', student_plan=plan_a,
    )
    # Log real contra B (caso sintético: lo que importa es que el parámetro explícito
    # dirige el reverso, no que el escenario sea uno de producción).
    ConsumptionLog.objects.create(
        user=setup['student'], student_plan=plan_b, class_instance=gym_class, branch=gym_class.branch,
    )

    reverted = revert_consumption(enrollment, student_plan=plan_b)

    assert reverted == 1
    plan_a.refresh_from_db()
    plan_b.refresh_from_db()
    assert plan_a.classes_used == 1, 'el FK no se usa cuando el llamador pasa el plan explícito'
    assert plan_b.classes_used == 0


def test_revert_consumption_locks_the_consumption_log_rows(setup, monkeypatch):
    """Mecanismo de concurrencia: `revert_consumption` delega en `_revert_consumption_logs`
    (mismo núcleo que ya prueba `test_consumption_revert_race.py`), que toma
    `select_for_update` sobre los `ConsumptionLog` antes de borrarlos. La carrera real
    (dos conexiones, dos reversos concurrentes del mismo consumo) no es reproducible
    en SQLite -- la propia suite la simula con un snapshot obsoleto a nivel de
    `_revert_consumption_logs`, y acá se asegura que este núcleo nuevo pasa por ese
    mismo camino en vez de reimplementar un read-modify-write."""
    gym_class = _future_class(setup)
    plan = _plan(setup, classes_used=1)
    enrollment = _consume(setup, gym_class, plan)

    original_select_for_update = QuerySet.select_for_update
    locked_models = []

    def _spy(self, *args, **kwargs):
        locked_models.append(self.model)
        return original_select_for_update(self, *args, **kwargs)

    monkeypatch.setattr(QuerySet, 'select_for_update', _spy)

    revert_consumption(enrollment)

    assert ConsumptionLog in locked_models, 'debe lockear los ConsumptionLog antes de borrarlos'
