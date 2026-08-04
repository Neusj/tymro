"""Follow-up 2 de recurrencias — auto-reapunte de la serie al renovar el plan.

`RecurringEnrollment.student_plan` (R1, migración 0036) es la elección VIGENTE que
gobierna las reservas futuras de la serie. Renovar crea una fila NUEVA de `StudentPlan`
(regla 7.1: `activate_student_plan` nunca reusa ni muta la anterior), así que sin este
cambio la serie seguía apuntando a la instancia vieja agotada y el loop la skippeaba mudo
con `chosen_plan_unavailable`. Este archivo fija el contrato del reapunte automático que
corre DENTRO de `activate_student_plan`.
"""
from datetime import time, timedelta

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone

from core.models import (
    Branch, ClassTemplate, ConsumptionLog, Enrollment, GymClass, Plan,
    RecurringEnrollment, StudentPlan,
)
from core.services.plans import activate_student_plan
from core.services.recurrence import create_enrollments_for_recurring_subscription

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()
ASSIGN_URL = '/api/plans/assign/'          # test_plan_assign_payment.py:21


@pytest.fixture
def setup(make_organization, make_user):
    """Calco de test_recurring_enrollment_plan_choice.py:73-87."""
    org = make_organization()
    teacher = make_user('teach-rep', organization=org, role='teacher')
    student = make_user('alu-rep', organization=org, role='student', email='alu-rep@gym.cl')
    branch = Branch.objects.create(organization=org, name='Sede')
    template = ClassTemplate.objects.create(
        organization=org, branch=branch, teacher=teacher, name='Serie',
        weekday=0, start_time=time(10, 0), end_time=time(11, 0), capacity=10,
        start_date=TODAY - timedelta(days=30),
    )
    return {'org': org, 'teacher': teacher, 'student': student,
            'branch': branch, 'template': template}


def _catalog_plan(org, name='Pack'):
    """Plan de CATÁLOGO. Clave del archivo: el helper `_student_plan` de los otros tests
    crea un `Plan` nuevo por llamada, así que acá el plan se pasa EXPLÍCITO para poder
    tener vieja y nueva del MISMO linaje."""
    return Plan.objects.create(
        organization=org, name=name, plan_type='pack',
        total_classes=10, duration_days=30, price=30000,
    )


def _membership(plan, student, *, classes_used=0, total_classes=10,
                start_offset=-1, end_offset=30, is_active=True):
    """Instancia de membresía. Agotada = classes_used == total_classes."""
    return StudentPlan.objects.create(
        user=student, plan=plan, organization_id=plan.organization_id,
        branch=plan.branch,
        start_date=TODAY + timedelta(days=start_offset),
        end_date=TODAY + timedelta(days=end_offset),
        total_classes=total_classes, classes_used=classes_used,
        final_price=plan.price, is_active=is_active,
    )


def _future_instance(setup, days=1):
    """Calco de test_recurring_enrollment_plan_choice.py:108-116."""
    start = timezone.now() + timedelta(days=days)
    return GymClass.objects.create(
        organization=setup['org'], branch=setup['branch'], teacher=setup['teacher'],
        class_template=setup['template'], name='Instancia',
        start_datetime=start, end_datetime=start + timedelta(hours=1),
        capacity=10, status=GymClass.Status.SCHEDULED,
    )


def _series(setup, student_plan=None, template=None, **overrides):
    """Serie con la FK ya fijada (lo que el alta de R1b graba)."""
    defaults = dict(
        student=setup['student'], class_template=template or setup['template'],
        start_date=TODAY - timedelta(days=30), student_plan=student_plan,
    )
    defaults.update(overrides)
    return RecurringEnrollment.objects.create(**defaults)


# --------------------------------------------------------------------------------------
# 1. Renovar un plan agotado reapunta la serie y el loop descuenta de la membresía nueva.
# --------------------------------------------------------------------------------------

def test_renewing_an_exhausted_plan_repoints_the_series_and_the_loop_consumes_the_new_one(setup):
    plan = _catalog_plan(setup['org'])
    old = _membership(plan, setup['student'], classes_used=10)     # AGOTADA
    series = _series(setup, student_plan=old)
    gym_class = _future_instance(setup)

    new = activate_student_plan(student=setup['student'], plan=plan, start_date=TODAY)
    # El reapunte es un `.update()` en la fila: el objeto `series` en memoria no lo ve
    # solo. En producción cada caller relee la suscripción antes de correr el loop
    # (`sync_recurring_enrollments_for_generated_instances` hace su propio `.filter(...)`,
    # y los call sites de `views.py` cargan el objeto recién); el `refresh_from_db()` acá
    # simula exactamente eso, no es un ajuste de fixture.
    series.refresh_from_db()
    assert series.student_plan_id == new.id

    summary = create_enrollments_for_recurring_subscription(series, class_instances=[gym_class])

    assert new.id != old.id
    assert summary['created_count'] == 1
    assert summary['skipped'] == []
    old.refresh_from_db()
    assert old.classes_used == 10
    new.refresh_from_db()
    assert new.classes_used == 1
    assert Enrollment.objects.get(gym_class=gym_class, student=setup['student']).student_plan_id == new.id
    assert ConsumptionLog.objects.get(class_instance=gym_class, user=setup['student']).student_plan_id == new.id


# --------------------------------------------------------------------------------------
# 2. Dos linajes: renovar el plan A no toca la serie del plan B (ambas viejas agotadas).
# --------------------------------------------------------------------------------------

def test_renewing_one_plan_does_not_repoint_the_series_of_another_plan(setup):
    plan_a = _catalog_plan(setup['org'], name='Pack A')
    plan_b = _catalog_plan(setup['org'], name='Pack B')
    old_a = _membership(plan_a, setup['student'], classes_used=10)   # agotada
    old_b = _membership(plan_b, setup['student'], classes_used=10)   # agotada TAMBIÉN:
    # si B estuviera vigente el test pasaría igual aunque el implementador se olvidara
    # del filtro por `plan_id` (la usabilidad sola la salvaría). Con las dos agotadas, el
    # único filtro que discrimina es el linaje.
    template_b = ClassTemplate.objects.create(                       # 2ª serie: el
        organization=setup['org'], branch=setup['branch'],           # UniqueConstraint
        teacher=setup['teacher'], name='Serie B', weekday=1,          # (student, template)
        start_time=time(12, 0), end_time=time(13, 0), capacity=10,
        start_date=TODAY - timedelta(days=30),
    )
    series_a = _series(setup, student_plan=old_a)
    series_b = _series(setup, student_plan=old_b, template=template_b)

    new_a = activate_student_plan(student=setup['student'], plan=plan_a, start_date=TODAY)

    series_a.refresh_from_db()
    assert series_a.student_plan_id == new_a.id
    series_b.refresh_from_db()
    assert series_b.student_plan_id == old_b.id
    assert series_b.student_plan_id != new_a.id


# --------------------------------------------------------------------------------------
# 3. Rollback: si la tx del caller revienta, la serie queda intacta apuntando a la vieja.
# --------------------------------------------------------------------------------------

def test_a_rollback_leaves_the_series_pointing_at_the_old_membership(api_client, setup,
                                                                      make_user, monkeypatch):
    admin = make_user('admin-rep', organization=setup['org'], role='gym_admin')
    plan = _catalog_plan(setup['org'])
    old = _membership(plan, setup['student'], classes_used=10)
    series = _series(setup, student_plan=old)
    before_sp = StudentPlan.objects.count()
    api_client.force_authenticate(admin)

    def _boom(**kwargs):
        raise DjangoValidationError('boom')

    # Nombre MÓDULO-GLOBAL: `core.views` lo importa arriba, así que el patch lo intercepta
    # (razonamiento de views.py:3643-3646 y test_plan_assign_payment.py:129).
    monkeypatch.setattr('core.views.record_manual_payment', _boom)

    resp = api_client.post(ASSIGN_URL, {
        'user': setup['student'].id, 'plan': plan.id, 'start_date': str(TODAY),
        'payment': {'method': 'manual', 'amount': '30000.00'},
    }, format='json')

    assert resp.status_code == 400, resp.content
    assert StudentPlan.objects.count() == before_sp
    series.refresh_from_db()
    assert series.student_plan_id == old.id
    assert StudentPlan.objects.filter(pk=series.student_plan_id).exists()


# --------------------------------------------------------------------------------------
# 4. Sin serie colgada (o con FK legacy NULL), renovar no falla ni reapunta nada.
# --------------------------------------------------------------------------------------

def test_renewing_without_any_pinned_series_is_a_no_op(setup):
    plan = _catalog_plan(setup['org'])
    old = _membership(plan, setup['student'], classes_used=10)
    legacy = _series(setup, student_plan=None)          # regla 6: FK NULL, no se toca
    before = RecurringEnrollment.objects.count()

    new = activate_student_plan(student=setup['student'], plan=plan, start_date=TODAY)

    assert new.pk is not None
    assert new.plan_id == plan.id
    legacy.refresh_from_db()
    assert legacy.student_plan_id is None
    assert RecurringEnrollment.objects.count() == before
    assert RecurringEnrollment.objects.filter(student_plan__isnull=False).count() == 0


# --------------------------------------------------------------------------------------
# 5. Invariante cross-tenant (security review, hallazgo BAJO 2): el helper NO puede
#    reapuntar una serie histórica de OTRA organización solo porque coincide el alumno y
#    el `plan_id`. `RecurringEnrollment.student` y `StudentPlan.user` son FKs CASCADE sobre
#    el USUARIO, no sobre el tenant (memoria del repo: "FK propia sin organización"), así
#    que si el alumno se muda de organización, la serie vieja queda alcanzable por
#    `student_id` aunque su `class_template` y su `student_plan.organization_id` —una
#    COPIA fijada al vender, que NO se resiembra sola— sigan en la organización ORIGINAL.
# --------------------------------------------------------------------------------------

def test_a_cross_org_history_does_not_repoint_when_the_student_and_plan_moved_orgs(
        setup, make_organization):
    """Sembrado por ORM (nada en el producto mueve alumnos/planes de organización hoy,
    pero nada en el modelo lo impide tampoco): sin los filtros `student_plan__organization_id`
    y `class_template__organization_id` del helper, este escenario matchearía igual — mismo
    `student_id`, mismo `plan_id`, `student_plan` no NULL — y la serie de la organización
    vieja se pisaría en silencio con una membresía de la organización nueva."""
    org_b = make_organization()
    plan = _catalog_plan(setup['org'])                            # catálogo en org A
    old = _membership(plan, setup['student'], classes_used=10)    # agotada, vendida en org A
    series = _series(setup, student_plan=old)                     # template también en org A

    # El alumno Y el plan de catálogo se mudan de organización. `old.organization_id` y
    # `setup['template'].organization_id` NO siguen ese movimiento: quedan fijos en org A.
    setup['student'].organization = org_b
    setup['student'].save()
    plan.organization = org_b
    plan.save()

    new = activate_student_plan(student=setup['student'], plan=plan, start_date=TODAY)

    assert new.organization_id == org_b.id
    series.refresh_from_db()
    assert series.student_plan_id == old.id, (
        'la serie de org A no puede quedar reapuntada a una membresía de org B'
    )
