"""El roster describe UNA membresía por alumno, no dos mezcladas (7.2).

`enrolled-students` y `enrollable-students` resolvían el saldo y la etiqueta de estado con
DOS consultas distintas y con criterios de orden distintos:

* `_get_active_student_plan_map` — vigentes, ordenadas por `-start_date` → de ahí salía el
  saldo (`available_classes`, `has_available_classes`, `unlimited_classes`).
* `_get_latest_student_plan_map` — cualquiera, ordenadas por `-end_date` → de ahí salía la
  etiqueta (`plan_status`, `plan_days_to_expiry`, las alertas).

Con una sola membresía coinciden. Con dos —el caso que el modelo declara soportar a
propósito: 4 BJJ + 8 kickboxing— eligen filas DISTINTAS, y el profe ve el saldo de un plan
con el vencimiento del otro.
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from core.models import Branch, Enrollment, GymClass, Plan, StudentPlan

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()


def _plan(org, name, total_classes):
    return Plan.objects.create(
        organization=org, name=name, plan_type='pack', total_classes=total_classes,
        duration_days=30, price=30000,
    )


def _membership(student, plan, *, start_offset, end_offset, classes_used=0, is_active=True):
    return StudentPlan.objects.create(
        user=student, plan=plan, organization_id=plan.organization_id,
        start_date=TODAY + timedelta(days=start_offset),
        end_date=TODAY + timedelta(days=end_offset),
        total_classes=plan.total_classes, classes_used=classes_used,
        final_price=30000, is_active=is_active,
    )


@pytest.fixture
def class_with_student(make_organization, make_user):
    org = make_organization()
    branch = Branch.objects.create(organization=org, name='Sede')
    teacher = make_user('prof-roster', organization=org, role='teacher')
    student = make_user('stu-roster', organization=org, role='student')
    start = timezone.now() + timedelta(days=1)
    gym_class = GymClass.objects.create(
        organization=org, branch=branch, teacher=teacher, name='Clase',
        start_datetime=start, end_datetime=start + timedelta(hours=1), capacity=10,
        status=GymClass.Status.SCHEDULED,
    )
    Enrollment.objects.create(gym_class=gym_class, student=student, status='active')
    return {
        'org': org, 'student': student, 'gym_class': gym_class,
        'admin': make_user('admin-roster', organization=org, role='gym_admin'),
    }


def _row(api_client, ctx, endpoint='enrolled-students'):
    resp = api_client.get(f'/api/classes/{ctx["gym_class"].id}/{endpoint}/')
    assert resp.status_code == 200, resp.content
    body = resp.json()
    rows = body['results'] if isinstance(body, dict) else body
    key = 'student_id' if endpoint == 'enrolled-students' else 'id'
    matching = [r for r in rows if r[key] == ctx['student'].id]
    assert matching, f'precondición: el alumno aparece en {endpoint}'
    return matching[0]


def test_balance_and_label_describe_the_same_membership(api_client, class_with_student):
    """Dos membresías vigentes: la que da el saldo tiene que ser la que da el vencimiento.

    BJJ empieza hoy y vence en 5 días; kickboxing empezó hace 10 y vence en 40. El mapa de
    vigentes (`-start_date`) elegía BJJ y el de "última" (`-end_date`) elegía kickboxing, así
    que el roster mostraba las 4 clases de BJJ con los 40 días de kickboxing.
    """
    ctx = class_with_student
    bjj = _membership(ctx['student'], _plan(ctx['org'], 'BJJ', 4), start_offset=0, end_offset=5)
    _membership(ctx['student'], _plan(ctx['org'], 'Kick', 8), start_offset=-10, end_offset=40)
    api_client.force_authenticate(user=ctx['admin'])

    row = _row(api_client, ctx)

    assert row['available_classes'] == bjj.total_classes == 4, row
    assert row['plan_days_to_expiry'] == 5, row
    assert row['plan_status'] == 'active', row


def test_balance_and_label_describe_the_same_membership_in_enrollable(api_client, class_with_student):
    """El mismo defecto vive en el endpoint hermano, con el mismo par de mapas."""
    ctx = class_with_student
    Enrollment.objects.filter(gym_class=ctx['gym_class'], student=ctx['student']).delete()
    bjj = _membership(ctx['student'], _plan(ctx['org'], 'BJJ', 4), start_offset=0, end_offset=5)
    _membership(ctx['student'], _plan(ctx['org'], 'Kick', 8), start_offset=-10, end_offset=40)
    api_client.force_authenticate(user=ctx['admin'])

    row = _row(api_client, ctx, endpoint='enrollable-students')

    assert row['available_classes'] == bjj.total_classes == 4, row
    assert row['plan_days_to_expiry'] == 5, row
    assert row['plan_status'] == 'active', row


def test_single_valid_membership_is_reported_coherently(api_client, class_with_student):
    """Regresión del caso simple: una sola membresía sigue describiéndose igual."""
    ctx = class_with_student
    _membership(ctx['student'], _plan(ctx['org'], 'Pack', 10), start_offset=-1, end_offset=20,
                classes_used=3)
    api_client.force_authenticate(user=ctx['admin'])

    row = _row(api_client, ctx)

    assert row['available_classes'] == 7, row
    assert row['has_available_classes'] is True, row
    assert row['plan_status'] == 'active', row
    assert row['plan_days_to_expiry'] == 20, row


def test_expired_only_membership_reports_no_balance(api_client, class_with_student):
    """Regresión: con la membresía vencida el roster sigue etiquetando "Vencido" y NO puede
    ofrecer saldo, aunque la fila conserve clases sin usar."""
    ctx = class_with_student
    _membership(ctx['student'], _plan(ctx['org'], 'Viejo', 10), start_offset=-60, end_offset=-1)
    api_client.force_authenticate(user=ctx['admin'])

    row = _row(api_client, ctx)

    assert row['plan_status'] == 'expired', row
    assert row['available_classes'] == 0, row
    assert row['has_available_classes'] is False, row
    assert row['unlimited_classes'] is False, row


def test_student_without_any_membership_reports_no_plan(api_client, class_with_student):
    ctx = class_with_student
    api_client.force_authenticate(user=ctx['admin'])

    row = _row(api_client, ctx)

    assert row['plan_status'] == 'no_plan', row
    assert row['available_classes'] == 0, row
    assert row['has_available_classes'] is False, row


def test_exhausted_membership_is_labelled_but_offers_no_balance(api_client, class_with_student):
    """Vigente y sin clases: el saldo y la etiqueta salen de la misma fila, y el saldo es 0.

    Antes esta fila se reportaba con `plan_status='active'` (la etiqueta solo miraba fechas y
    el flag) y `available_classes=0`, o sea "Vigente" sin poder reservar y sin ninguna señal
    de por qué.
    """
    ctx = class_with_student
    _membership(ctx['student'], _plan(ctx['org'], 'Pack', 4), start_offset=-1, end_offset=20,
                classes_used=4)
    api_client.force_authenticate(user=ctx['admin'])

    row = _row(api_client, ctx)

    assert row['available_classes'] == 0, row
    assert row['has_available_classes'] is False, row
    assert row['plan_days_to_expiry'] == 20, row
