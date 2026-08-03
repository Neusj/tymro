"""`RecurringEnrollment.student_plan` (10.x): con qué membresía se re-imputan las
instancias futuras de una recurrencia, poblado por el backfill de la migración 0036
(`backfill_recurring_enrollment_student_plan`) con los MISMOS criterios org-scopeados
de `resolve_student_plan_for_reservation` (core/services/reservations.py:59-120):
planes del alumno intersectados con la organización de la SUSCRIPCIÓN
(`class_template.organization_id`, no `student.organization_id`), vigentes hoy y
usables.

Solo 1 candidato → se puebla con ese plan. 0 o 2+ candidatos → queda NULL: no hay de
dónde inferir uno solo de forma defendible. Un plan de OTRA organización nunca puebla
la FK, aunque sea el único que tiene el alumno — mismo anti-cross-tenant que el resto
del proyecto. Tampoco se puebla una serie YA TERMINADA (`end_date` pasado): no gobierna
ninguna reserva futura, así que fijarle una membresía solo agregaría un candado muerto.

La segunda mitad del archivo cubre el RADIO DE BORRADO de la FK (`on_delete=RESTRICT`),
que es la otra cara del mismo campo: qué borrados bloquea y cuáles NO.
"""
from datetime import timedelta
from importlib import import_module

import pytest
from django.apps import apps as global_apps
from django.db.models import RestrictedError
from django.utils import timezone

from core.models import Branch, ClassTemplate, Plan, RecurringEnrollment, StudentPlan

pytestmark = pytest.mark.django_db

PASSWORD = 'Passw0rd2026'
TODAY = timezone.localdate()


def _login(api_client, user):
    host = {'HTTP_HOST': f'{user.organization.subdomain}.localhost'} if user.organization_id else {}
    token = api_client.post(
        '/api/login/', {'email': user.email, 'password': PASSWORD}, format='json', **host
    ).json()['token']
    api_client.credentials(HTTP_AUTHORIZATION=f'Token {token}')

migration_module = import_module('core.migrations.0036_recurringenrollment_student_plan')
backfill_recurring_enrollment_student_plan = migration_module.backfill_recurring_enrollment_student_plan


@pytest.fixture
def setup(make_organization, make_user):
    org = make_organization()
    other_org = make_organization()
    student = make_user('alu-recur-plan', organization=org, role='student', email='alu-recur-plan@gym.cl')
    branch = Branch.objects.create(organization=org, name='Sede')
    class_template = ClassTemplate.objects.create(
        organization=org, branch=branch, weekday=0,
        start_time=timezone.datetime(2020, 1, 1, 8, 0).time(),
        end_time=timezone.datetime(2020, 1, 1, 9, 0).time(),
        capacity=10, start_date=TODAY - timedelta(days=60),
    )
    return {
        'org': org, 'other_org': other_org, 'student': student,
        'branch': branch, 'class_template': class_template,
    }


def _plan(organization, **overrides):
    defaults = dict(
        organization=organization, name='Pack 10', plan_type='pack',
        total_classes=10, duration_days=30, price=30000,
    )
    defaults.update(overrides)
    return Plan.objects.create(**defaults)


def _usable_student_plan(organization, student, **overrides):
    plan = _plan(organization)
    defaults = dict(
        user=student, plan=plan, organization_id=organization.id,
        start_date=TODAY - timedelta(days=1), end_date=TODAY + timedelta(days=30),
        total_classes=10, classes_used=0, final_price=30000, is_active=True,
    )
    defaults.update(overrides)
    return StudentPlan.objects.create(**defaults)


def _recurring_enrollment(setup, **overrides):
    defaults = dict(
        student=setup['student'], class_template=setup['class_template'],
        start_date=TODAY - timedelta(days=30),
    )
    defaults.update(overrides)
    return RecurringEnrollment.objects.create(**defaults)


def test_backfill_populates_fk_with_the_single_usable_candidate(setup):
    """Exactamente 1 candidato usable (misma organización, vigente hoy, con saldo) →
    la FK se puebla con ese plan."""
    recurring = _recurring_enrollment(setup)
    student_plan = _usable_student_plan(setup['org'], setup['student'])

    backfill_recurring_enrollment_student_plan(global_apps, None)

    recurring.refresh_from_db()
    assert recurring.student_plan_id == student_plan.id


def test_backfill_leaves_null_with_two_or_more_candidates(setup):
    """2+ candidatos vigentes y usables a la vez (dos disciplinas, p. ej.) → ambigüedad,
    la FK queda NULL: no hay forma defendible de elegir uno solo."""
    recurring = _recurring_enrollment(setup)
    _usable_student_plan(setup['org'], setup['student'])
    _usable_student_plan(setup['org'], setup['student'])

    backfill_recurring_enrollment_student_plan(global_apps, None)

    recurring.refresh_from_db()
    assert recurring.student_plan_id is None


def test_backfill_leaves_null_with_zero_candidates(setup):
    """Sin ningún plan (o ninguno usable) → NULL, el comportamiento actual se mantiene."""
    recurring = _recurring_enrollment(setup)

    backfill_recurring_enrollment_student_plan(global_apps, None)

    recurring.refresh_from_db()
    assert recurring.student_plan_id is None


def test_backfill_ignores_exhausted_or_expired_plans_when_counting_candidates(setup):
    """Un plan agotado (classes_used >= total_classes) o vencido no es 'usable': si es el
    ÚNICO que tiene el alumno, el conteo de candidatos usables es CERO y la FK queda
    NULL, no apuntando a un plan sin saldo."""
    recurring = _recurring_enrollment(setup)
    _usable_student_plan(setup['org'], setup['student'], classes_used=10, total_classes=10)
    _usable_student_plan(
        setup['org'], setup['student'],
        start_date=TODAY - timedelta(days=60), end_date=TODAY - timedelta(days=1),
    )

    backfill_recurring_enrollment_student_plan(global_apps, None)

    recurring.refresh_from_db()
    assert recurring.student_plan_id is None


def test_backfill_never_populates_with_a_plan_from_another_organization(setup):
    """El alumno tiene 1 plan usable, pero es de OTRA organización que la de la
    suscripción (`class_template.organization_id`) → la FK queda NULL. Cross-org nunca
    debe poblar, aunque sea el único candidato disponible."""
    recurring = _recurring_enrollment(setup)
    cross_org_plan = _usable_student_plan(setup['other_org'], setup['student'])

    backfill_recurring_enrollment_student_plan(global_apps, None)

    recurring.refresh_from_db()
    assert recurring.student_plan_id is None
    assert recurring.student_plan_id != cross_org_plan.id


def test_backfill_is_scoped_by_class_template_organization_not_student_organization(setup):
    """La organización que manda es la de la PLANTILLA (`class_template.organization_id`),
    no `student.organization_id` — el alumno pudo moverse de tenant DESPUÉS de crear la
    recurrencia (el agujero multitenant recurrente del proyecto: FKs propias sin
    intersectar organización). Un plan de la organización ACTUAL del alumno, distinta a
    la de la plantilla, tampoco puebla la FK."""
    recurring = _recurring_enrollment(setup)
    setup['student'].organization = setup['other_org']
    setup['student'].save(update_fields=['organization'])
    plan_from_students_new_org = _usable_student_plan(setup['other_org'], setup['student'])

    backfill_recurring_enrollment_student_plan(global_apps, None)

    recurring.refresh_from_db()
    assert recurring.student_plan_id is None
    assert recurring.student_plan_id != plan_from_students_new_org.id


def test_backfill_skips_series_that_already_ended(setup):
    """Serie TERMINADA (`end_date` pasado): la FK queda NULL aunque haya exactamente 1
    candidato usable. Esa recurrencia no va a materializar ninguna instancia más, así que
    fijarle una membresía no cambia ninguna imputación futura y sí deja un `RESTRICT`
    colgando sobre un plan que el gimnasio podría querer quitar."""
    recurring = _recurring_enrollment(
        setup, start_date=TODAY - timedelta(days=50), end_date=TODAY - timedelta(days=30),
    )
    _usable_student_plan(setup['org'], setup['student'])

    backfill_recurring_enrollment_student_plan(global_apps, None)

    recurring.refresh_from_db()
    assert recurring.student_plan_id is None


def test_backfill_populates_a_paused_series_without_a_past_end_date(setup):
    """PAUSADA no es TERMINADA: `is_active=False` sin `end_date` vencido es reactivable
    (el alumno la reactiva desde "Mis recurrencias" y vuelve a materializar), así que sí
    se le fija la membresía. El corte es la FECHA, no el flag."""
    recurring = _recurring_enrollment(setup, is_active=False)
    student_plan = _usable_student_plan(setup['org'], setup['student'])

    backfill_recurring_enrollment_student_plan(global_apps, None)

    recurring.refresh_from_db()
    assert recurring.student_plan_id == student_plan.id


# --------------------------------------------------------------------------------------
# Radio de borrado de la FK (`on_delete=RESTRICT`).
#
# RESTRICT y no PROTECT: los dos bloquean el borrado DIRECTO de la membresía, pero PROTECT
# también revienta cuando la `RecurringEnrollment` que protege cae en la MISMA cascada
# —`RecurringEnrollment.student` y `StudentPlan.user` son ambos CASCADE sobre el alumno—,
# y ahí no hay nada que proteger: se borra todo junto. Con PROTECT, borrar un alumno con
# recurrencia daba `ProtectedError` → 500 en `DELETE /api/users/{id}/`.
# --------------------------------------------------------------------------------------

def test_restrict_blocks_deleting_a_student_plan_referenced_by_a_recurring_enrollment(setup):
    """Borrar un `StudentPlan` que una `RecurringEnrollment` tiene como imputación vigente
    tiene que levantar `RestrictedError`, no borrarlo en cascada ni dejar la FK en NULL en
    silencio."""
    student_plan = _usable_student_plan(setup['org'], setup['student'])
    _recurring_enrollment(setup, student_plan=student_plan)

    with pytest.raises(RestrictedError):
        student_plan.delete()


def test_deleting_the_student_takes_everything_with_it_without_restricting(setup):
    """La cascada del MISMO borrado no se bloquea: al borrar al alumno, la recurrencia que
    apunta a la membresía se va en la misma operación (`student` es CASCADE en las dos
    tablas), así que RESTRICT no tiene a quién proteger."""
    student_plan = _usable_student_plan(setup['org'], setup['student'])
    recurring = _recurring_enrollment(setup, student_plan=student_plan)

    setup['student'].delete()

    assert not RecurringEnrollment.objects.filter(id=recurring.id).exists()
    assert not StudentPlan.objects.filter(id=student_plan.id).exists()


def test_api_delete_student_with_a_pinned_recurrence_does_not_explode(api_client, setup, make_user):
    """`UserViewSet.perform_destroy` (views.py:1938-1940) hace `instance.delete()` a secas.
    Con PROTECT esto era un 500 (`ProtectedError` sin capturar) para cualquier alumno con
    recurrencia y membresía; con RESTRICT vuelve a ser un borrado normal."""
    admin = make_user('admin-del-rp', organization=setup['org'], role='gym_admin')
    student_plan = _usable_student_plan(setup['org'], setup['student'])
    recurring = _recurring_enrollment(setup, student_plan=student_plan)
    _login(api_client, admin)

    resp = api_client.delete(f'/api/users/{setup["student"].id}/')

    assert resp.status_code == 204, resp.content
    assert not RecurringEnrollment.objects.filter(id=recurring.id).exists()
    assert not StudentPlan.objects.filter(id=student_plan.id).exists()


def test_api_remove_membership_pinned_to_a_recurrence_is_400_and_keeps_the_plan(
        api_client, setup, make_user):
    """`remove_membership` hacía `membership.delete()` directo: con la FK apuntándole, eso
    era un 500. Ahora es un 400 accionable —hay que sacar la recurrencia primero— y la
    membresía sigue viva."""
    admin = make_user('admin-rm-rp', organization=setup['org'], role='gym_admin')
    student_plan = _usable_student_plan(setup['org'], setup['student'])
    _recurring_enrollment(setup, student_plan=student_plan)
    _login(api_client, admin)

    resp = api_client.delete(
        f'/api/plans/{student_plan.plan_id}/memberships/{student_plan.id}/'
    )

    assert resp.status_code == 400, resp.content
    assert 'recurrente' in resp.json()['detail'].lower()
    assert StudentPlan.objects.filter(id=student_plan.id).exists()


def test_api_remove_membership_works_again_once_the_recurrence_is_gone(
        api_client, setup, make_user):
    """El 400 de arriba es una precondición accionable, no un callejón: borrada la
    recurrencia (endpoint que ya existe, `RecurringEnrollmentViewSet.destroy`), la
    membresía se quita normalmente."""
    admin = make_user('admin-rm2-rp', organization=setup['org'], role='gym_admin')
    student_plan = _usable_student_plan(setup['org'], setup['student'])
    recurring = _recurring_enrollment(setup, student_plan=student_plan)
    _login(api_client, admin)

    removed_recurrence = api_client.delete(f'/api/recurring-enrollments/{recurring.id}/')
    resp = api_client.delete(
        f'/api/plans/{student_plan.plan_id}/memberships/{student_plan.id}/'
    )

    assert removed_recurrence.status_code == 204, removed_recurrence.content
    assert resp.status_code == 204, resp.content
    assert not StudentPlan.objects.filter(id=student_plan.id).exists()
