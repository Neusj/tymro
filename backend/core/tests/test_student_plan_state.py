"""`describe_student_plan(plan, on_date)` — estado derivado único de una membresía (7.2).

Reemplaza a los dos bloques de lógica Python que etiquetaban el estado por separado
—`StudentPlanSerializer.get_validity_status` y `_plan_status_payload` del roster— y les
suma las dos mitades que hasta ahora solo existían dentro del validador de reservas: el
SALDO (`unlimited_classes` / `classes_used` vs `total_classes`) y la MATRÍCULA
(`enrollment_fee` impaga).

Que las cinco copias produzcan el mismo estado es el punto de la tarea. Que el estado no
dependa del sentido que cada escritor le dio a `is_active` es el otro: el flag significa
"no fue reemplazada" cuando lo escribe `activate_student_plan` y "está vigente" cuando lo
deriva el importador, así que dos membresías en el mismo estado real tienen el flag
distinto según quién las creó.
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from core.models import Plan, StudentPlan
from core.services.plans import (
    EXPIRY_SOON_DAYS,
    EXPIRY_WARNING_DAYS,
    PlanStatus,
    describe_student_plan,
)

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()


def _plan(org, total_classes=10, unlimited=False):
    return Plan.objects.create(
        organization=org, name=f'Plan {total_classes}', plan_type='pack',
        total_classes=total_classes, unlimited_classes=unlimited,
        duration_days=30, price=30000,
    )


def _membership(student, plan, *, start_offset=-1, end_offset=30, classes_used=0,
                is_active=True, enrollment_fee=0, enrollment_fee_paid_at=None):
    return StudentPlan.objects.create(
        user=student, plan=plan, organization_id=plan.organization_id,
        start_date=TODAY + timedelta(days=start_offset),
        end_date=TODAY + timedelta(days=end_offset),
        total_classes=plan.total_classes, unlimited_classes=plan.unlimited_classes,
        classes_used=classes_used, final_price=30000, is_active=is_active,
        enrollment_fee=enrollment_fee, enrollment_fee_paid_at=enrollment_fee_paid_at,
    )


@pytest.fixture
def student_with_plan(make_organization, make_user):
    org = make_organization()
    student = make_user('stu-state', organization=org, role='student')
    return org, student, _plan(org)


# --------------------------------------------------------------------------------------
# Los cinco estados que la tarea exige distinguir
# --------------------------------------------------------------------------------------

def test_valid_membership_with_balance_is_active(student_with_plan):
    _, student, plan = student_with_plan
    state = describe_student_plan(_membership(student, plan, classes_used=2), TODAY)
    assert state.status == PlanStatus.ACTIVE
    assert state.label == 'Vigente'
    assert state.reason_code is None
    assert state.is_usable is True
    assert state.remaining_classes == 8


def test_valid_membership_without_balance_is_exhausted(student_with_plan):
    """La mitad de saldo, que hoy solo vive dentro del validador de reservas."""
    _, student, plan = student_with_plan
    state = describe_student_plan(_membership(student, plan, classes_used=10), TODAY)
    assert state.status == PlanStatus.EXHAUSTED
    assert state.label == 'Sin clases disponibles'
    assert state.is_usable is False
    assert state.remaining_classes == 0


def test_membership_past_its_end_date_is_expired(student_with_plan):
    _, student, plan = student_with_plan
    state = describe_student_plan(
        _membership(student, plan, start_offset=-60, end_offset=-1), TODAY
    )
    assert state.status == PlanStatus.EXPIRED
    assert state.label == 'Vencido'
    assert state.is_usable is False


def test_membership_that_has_not_started_is_upcoming(student_with_plan):
    _, student, plan = student_with_plan
    state = describe_student_plan(_membership(student, plan, start_offset=3), TODAY)
    assert state.status == PlanStatus.UPCOMING
    assert state.label == 'Por iniciar'
    assert state.is_usable is False


def test_valid_membership_with_unpaid_enrollment_fee_is_blocked(student_with_plan):
    """La otra mitad que solo vivía en el validador de reservas."""
    _, student, plan = student_with_plan
    state = describe_student_plan(
        _membership(student, plan, enrollment_fee=15000, enrollment_fee_paid_at=None), TODAY
    )
    assert state.status == PlanStatus.ENROLLMENT_FEE_UNPAID
    assert state.label == 'Matrícula impaga'
    assert state.reason_code == 'enrollment_fee_unpaid'
    assert state.is_usable is False


# --------------------------------------------------------------------------------------
# La ambigüedad de is_active
# --------------------------------------------------------------------------------------

def test_expired_membership_has_the_same_state_regardless_of_the_flag(student_with_plan, make_user):
    """MATA LA AMBIGÜEDAD.

    `activate_student_plan` deja `is_active=True` para siempre (nadie lo apaga al vencer:
    no hay cron de vencimiento) y el importador lo deriva de `end_date >= hoy`. Resultado:
    dos membresías vencidas idénticas con el flag distinto según quién las creó. El estado
    derivado no puede depender de eso.
    """
    org, student, plan = student_with_plan
    other = make_user('stu-flag', organization=org, role='student')
    still_flagged = _membership(student, plan, start_offset=-60, end_offset=-1, is_active=True)
    flag_cleared = _membership(other, plan, start_offset=-60, end_offset=-1, is_active=False)

    assert (
        describe_student_plan(still_flagged, TODAY).status
        == describe_student_plan(flag_cleared, TODAY).status
        == PlanStatus.EXPIRED
    )


def test_cleared_flag_inside_the_window_is_inactive(student_with_plan):
    """Dentro de la ventana el flag sí manda: "dada de baja" es el único sentido que le
    queda una vez que las fechas deciden la vigencia."""
    _, student, plan = student_with_plan
    state = describe_student_plan(_membership(student, plan, is_active=False), TODAY)
    assert state.status == PlanStatus.INACTIVE
    assert state.is_usable is False


# --------------------------------------------------------------------------------------
# Saldo ilimitado, sin plan, fecha, umbrales
# --------------------------------------------------------------------------------------

def test_unlimited_membership_is_active_over_its_class_count(make_organization, make_user):
    """Ilimitado ignora el saldo: `classes_used >= total_classes` no lo agota."""
    org = make_organization()
    student = make_user('stu-unlimited', organization=org, role='student')
    plan = _plan(org, total_classes=0, unlimited=True)
    state = describe_student_plan(_membership(student, plan, classes_used=99), TODAY)
    assert state.status == PlanStatus.ACTIVE
    assert state.is_usable is True
    assert state.remaining_classes is None


def test_paid_enrollment_fee_does_not_block(student_with_plan):
    _, student, plan = student_with_plan
    state = describe_student_plan(
        _membership(student, plan, enrollment_fee=15000,
                    enrollment_fee_paid_at=timezone.now()),
        TODAY,
    )
    assert state.status == PlanStatus.ACTIVE
    assert state.is_usable is True


def test_none_is_no_plan(student_with_plan):
    state = describe_student_plan(None, TODAY)
    assert state.status == PlanStatus.NO_PLAN
    assert state.label == 'Sin plan'
    assert state.is_usable is False
    assert state.remaining_classes is None
    assert state.days_to_expiry is None


def test_days_to_expiry_is_measured_against_the_given_date(student_with_plan):
    _, student, plan = student_with_plan
    membership = _membership(student, plan, end_offset=7)
    assert describe_student_plan(membership, TODAY).days_to_expiry == 7
    assert describe_student_plan(membership, TODAY + timedelta(days=5)).days_to_expiry == 2


def test_state_is_evaluated_against_the_date_it_receives(student_with_plan):
    """La misma fila es `active` ayer y `expired` hoy: el estado es función de la fecha."""
    _, student, plan = student_with_plan
    membership = _membership(student, plan, start_offset=-30, end_offset=-1)
    assert describe_student_plan(membership, TODAY - timedelta(days=1)).status == PlanStatus.ACTIVE
    assert describe_student_plan(membership, TODAY).status == PlanStatus.EXPIRED


def test_describe_requires_the_date_argument(student_with_plan):
    _, student, plan = student_with_plan
    with pytest.raises(TypeError):
        describe_student_plan(_membership(student, plan))


def test_expiry_thresholds_are_a_single_documented_constant():
    """Los umbrales 5/12 estaban duplicados como literales en el serializer y en el payload
    del roster, y por eso podían divergir. Fuente única, igual que
    `Plan.NOT_PURCHASABLE_ONLINE`."""
    assert EXPIRY_SOON_DAYS == 5
    assert EXPIRY_WARNING_DAYS == 12
    assert EXPIRY_SOON_DAYS < EXPIRY_WARNING_DAYS
