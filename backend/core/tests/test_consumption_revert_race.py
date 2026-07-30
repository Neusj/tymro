"""El reverso del consumo no puede devolver el saldo dos veces por el mismo log.

`_revert_consumption_logs` materializa (id, student_plan_id) en un snapshot y después
decrementa `classes_used`. Si el decremento sale del snapshot y no de lo que el DELETE
realmente borró, dos reversos concurrentes sobre el mismo consumo lo devuelven DOS veces:

    A: SELECT -> [log1]      B: SELECT -> [log1]   (READ COMMITTED, A no comiteó)
    A: DELETE log1 (1 fila)  B: DELETE log1 -> espera el lock; al liberarse borra 0
    A: classes_used -= 1     B: classes_used -= 1  <- de un consumo que ya no existe

`Greatest(..., 0)` solo tapa el caso `classes_used == 1`; con 2 o más el alumno se queda
con clases gratis. Es alcanzable con un doble click en `DELETE /api/enrollments/{id}/`
(rol `student` sobre su propia reserva) o en `DELETE /api/classes/{id}/`.

La carrera real necesita dos conexiones y SQLite serializa las escrituras, así que acá se
pinta el escenario del PERDEDOR de forma determinista: un queryset cuyo SELECT devuelve un
log que, cuando llega el DELETE, ya no está. El invariante que se pide es que el saldo
salga de las filas efectivamente borradas.
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from core.models import Branch, ConsumptionLog, GymClass, Plan, StudentPlan
from core.services.reservations import _revert_consumption_logs

pytestmark = pytest.mark.django_db


class _StaleQuerySet:
    """El perdedor de la carrera: su SELECT vio los logs, pero cuando llega al DELETE
    otra transacción ya se los llevó. Reproduce el snapshot obsoleto sin necesitar dos
    conexiones."""

    def __init__(self, rows):
        self._rows = rows

    def select_for_update(self, *args, **kwargs):
        return self

    def values_list(self, *fields):
        assert fields == ('id', 'student_plan_id'), fields
        return self._rows


@pytest.fixture
def consumed(make_organization, make_user):
    org = make_organization()
    teacher = make_user('teach', organization=org, role='teacher')
    student = make_user('alu', organization=org, role='student', email='alu@gym.cl')
    branch = Branch.objects.create(organization=org, name='Sede')
    start = timezone.now() + timedelta(days=1)
    gym_class = GymClass.objects.create(
        organization=org, branch=branch, teacher=teacher, name='Clase',
        start_datetime=start, end_datetime=start + timedelta(hours=1), capacity=10,
    )
    today = timezone.localdate()
    plan = Plan.objects.create(
        organization=org, name='Pack 10', plan_type='pack',
        total_classes=10, duration_days=30, price=30000,
    )
    # classes_used=3 a propósito: con 1 el Greatest(...,0) tapa el doble decremento y el
    # bug pasa desapercibido.
    student_plan = StudentPlan.objects.create(
        user=student, plan=plan, start_date=today - timedelta(days=1),
        organization_id=plan.organization_id,
        end_date=today + timedelta(days=30), total_classes=10, classes_used=3,
        final_price=30000,
    )
    log = ConsumptionLog.objects.create(
        user=student, student_plan=student_plan, class_instance=gym_class,
        branch=branch,
    )
    return {'student_plan': student_plan, 'log': log, 'gym_class': gym_class}


def test_stale_snapshot_does_not_refund_an_already_deleted_log(consumed):
    """El perdedor de la carrera no debe tocar el saldo: su DELETE borró 0 filas."""
    student_plan = consumed['student_plan']
    stale = _StaleQuerySet([(consumed['log'].id, student_plan.id)])
    consumed['log'].delete()  # el ganador de la carrera ya se lo llevó

    reverted = _revert_consumption_logs(stale)

    assert reverted == 0, 'no se revirtió ningún consumo: el log ya no existía'
    student_plan.refresh_from_db()
    assert student_plan.classes_used == 3, 'el saldo no puede devolverse dos veces'


def test_partially_stale_snapshot_refunds_only_what_it_deleted(consumed):
    """Snapshot con dos logs del mismo plan, uno ya borrado: se devuelve UNO."""
    student_plan = consumed['student_plan']
    segundo = ConsumptionLog.objects.create(
        user=student_plan.user, student_plan=student_plan,
        class_instance=consumed['gym_class'], branch=consumed['gym_class'].branch,
    )
    stale = _StaleQuerySet([
        (consumed['log'].id, student_plan.id),
        (segundo.id, student_plan.id),
    ])
    consumed['log'].delete()

    reverted = _revert_consumption_logs(stale)

    assert reverted == 1
    student_plan.refresh_from_db()
    assert student_plan.classes_used == 2, 'solo baja por el log que sí se borró'


def test_revert_still_refunds_every_log_it_deletes(consumed):
    """Regresión: dos consumos vivos del mismo plan se devuelven los dos."""
    student_plan = consumed['student_plan']
    ConsumptionLog.objects.create(
        user=student_plan.user, student_plan=student_plan,
        class_instance=consumed['gym_class'], branch=consumed['gym_class'].branch,
    )

    reverted = _revert_consumption_logs(
        ConsumptionLog.objects.filter(class_instance=consumed['gym_class'])
    )

    assert reverted == 2
    student_plan.refresh_from_db()
    assert student_plan.classes_used == 1
