"""Una `StudentPlan` pertenece a la organización que la VENDIÓ (`plan.organization`).

`StudentPlan.user` es CASCADE sobre el usuario, no sobre la organización: mover a un alumno
de la org A a la org B le deja las membresías de A vivas. Tres sitios seguían resolviendo
membresías solo por `user`, cada uno con su consecuencia:

* `_get_active_student_plan_map` / `_get_latest_student_plan_map` (LECTURA): el roster de
  una clase de la org B mostraba el saldo, el vencimiento y las alertas del plan que
  vendió la org A. Además incoherente: el roster decía "9 clases disponibles" y reservar
  fallaba con `plan_unavailable`, porque el flujo de reserva sí acota por organización.
* `activate_student_plan` (ESCRITURA CROSS-TENANT): la invariante "una sola membresía
  activa" se aplicaba sobre TODAS las organizaciones, así que asignar un plan en la org B
  ponía `is_active=False` en la membresía vigente de la org A. Es el caso más grave: un
  actor de un tenant desactiva una membresía vendida por otro. Y el webhook de pagos entra
  por el mismo camino, sin ningún check de organización delante.
* Guarda anti-doble-membresía del importador: bloqueaba una fila legítima por una
  membresía de otra organización que el actor no puede ver ni corregir.
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from core.models import Branch, Enrollment, GymClass, Plan, StudentPlan

pytestmark = pytest.mark.django_db

PASSWORD = 'Passw0rd2026'


def _login(api_client, user):
    host = {'HTTP_HOST': f'{user.organization.subdomain}.localhost'} if user.organization_id else {}
    token = api_client.post(
        '/api/login/', {'email': user.email, 'password': PASSWORD}, format='json', **host
    ).json()['token']
    api_client.credentials(HTTP_AUTHORIZATION=f'Token {token}')


def _plan(org, name, price=30000):
    return Plan.objects.create(
        organization=org, name=name, plan_type='pack',
        total_classes=10, duration_days=30, price=price,
    )


def _membership(student, plan, classes_used=1, active=True):
    today = timezone.localdate()
    return StudentPlan.objects.create(
        user=student, plan=plan, start_date=today - timedelta(days=1),
        organization_id=plan.organization_id,
        end_date=today + timedelta(days=30), total_classes=10,
        classes_used=classes_used, final_price=30000, is_active=active,
    )


@pytest.fixture
def moved_student(make_organization, make_user):
    """Alumno con membresía vigente vendida por la org A, hoy en la org B."""
    org_a = make_organization()
    org_b = make_organization()
    student = make_user('nomade', organization=org_a, role='student', email='nomade@x.cl')
    membership_a = _membership(student, _plan(org_a, 'Pack secreto de A'))

    student.organization = org_b
    student.save(update_fields=['organization'])

    teacher_b = make_user('teach_b', organization=org_b, role='teacher')
    branch_b = Branch.objects.create(organization=org_b, name='Sede B')
    start = timezone.now() + timedelta(days=2)
    class_b = GymClass.objects.create(
        organization=org_b, branch=branch_b, teacher=teacher_b, name='Clase de B',
        start_datetime=start, end_datetime=start + timedelta(hours=1), capacity=10,
        status=GymClass.Status.SCHEDULED,
    )
    return {
        'org_a': org_a, 'org_b': org_b, 'student': student,
        'membership_a': membership_a, 'class_b': class_b, 'branch_b': branch_b,
        'admin_a': make_user('admin_a', organization=org_a, role='gym_admin'),
        'admin_b': make_user('admin_b', organization=org_b, role='gym_admin'),
    }


def _rows(response):
    body = response.json()
    return body['results'] if isinstance(body, dict) else body


# ---------------------------------------------------------------------------
# LECTURA: el roster no puede mostrar el plan de otra organización
# ---------------------------------------------------------------------------

def test_enrollable_students_does_not_expose_a_plan_of_another_org(api_client, moved_student):
    """`enrollable-students` adjuntaba a cada candidato su plan activo sin mirar la org."""
    _login(api_client, moved_student['admin_b'])

    resp = api_client.get(f'/api/classes/{moved_student["class_b"].id}/enrollable-students/')

    assert resp.status_code == 200, resp.content
    rows = [r for r in _rows(resp) if r['id'] == moved_student['student'].id]
    assert rows, 'precondición: el alumno es candidato de la clase de B'
    row = rows[0]
    assert not row.get('has_available_classes'), row
    assert row.get('available_classes') in (None, 0), row
    assert row.get('plan_status') in (None, '', 'sin_plan', 'no_plan'), row


def test_enrolled_students_does_not_expose_a_plan_of_another_org(api_client, moved_student):
    """Mismo mapa por el otro endpoint, con el alumno ya inscrito."""
    Enrollment.objects.create(
        gym_class=moved_student['class_b'], student=moved_student['student'], status='active',
    )
    _login(api_client, moved_student['admin_b'])

    resp = api_client.get(f'/api/classes/{moved_student["class_b"].id}/enrolled-students/')

    assert resp.status_code == 200, resp.content
    rows = [r for r in _rows(resp) if r['student_id'] == moved_student['student'].id]
    assert rows, 'precondición: el alumno está inscrito'
    row = rows[0]
    assert not row.get('has_available_classes'), row
    assert row.get('available_classes') in (None, 0), row


def test_roster_still_shows_the_plan_of_its_own_org(api_client, moved_student):
    """Regresión: la membresía vendida por la PROPIA organización sí se muestra."""
    _membership(moved_student['student'], _plan(moved_student['org_b'], 'Pack de B'), classes_used=2)
    _login(api_client, moved_student['admin_b'])

    resp = api_client.get(f'/api/classes/{moved_student["class_b"].id}/enrollable-students/')

    assert resp.status_code == 200, resp.content
    row = [r for r in _rows(resp) if r['id'] == moved_student['student'].id][0]
    assert row['has_available_classes'] is True, row
    assert row['available_classes'] == 8, row


# ---------------------------------------------------------------------------
# ESCRITURA: asignar en una org no puede desactivar la membresía de otra
# ---------------------------------------------------------------------------

def test_assigning_a_plan_does_not_deactivate_another_orgs_membership(api_client, moved_student):
    """Asignar no puede tocar la membresía que vendió otra organización.

    Cuando `activate_student_plan` desactivaba las vigentes del alumno, esto se sostenía
    acotando ese `update` por organización —sin el filtro, el admin de la org B apagaba la
    membresía de la org A—. Hoy se sostiene por algo más fuerte: no desactiva ninguna."""
    plan_b = _plan(moved_student['org_b'], 'Pack de B')
    _login(api_client, moved_student['admin_b'])

    resp = api_client.post('/api/plans/assign/', {
        'user': moved_student['student'].id, 'plan': plan_b.id,
        'start_date': str(timezone.localdate()),
        'payment': {'method': 'free'},
    }, format='json')

    assert resp.status_code == 201, resp.content
    moved_student['membership_a'].refresh_from_db()
    assert moved_student['membership_a'].is_active is True, (
        'un actor de la org B desactivó la membresía vendida por la org A'
    )


def test_assigning_a_plan_does_not_close_the_previous_membership_of_its_own_org(
    api_client, moved_student,
):
    """Invierte el comportamiento que este test exigía antes.

    Asignar un plan desactivaba las membresías vigentes del alumno en esa organización, y
    este test lo daba por correcto ("la anterior debe cerrarse"). Es un bug: un alumno
    puede tener varios planes contratados a la vez en la misma organización (dos
    disciplinas), así que asignarle uno nuevo no puede apagarle el que está usando.

    La garantía cross-org del test de arriba sigue valiendo, y ahora por una razón más
    simple: asignar no desactiva NADA, ni de la propia org ni de otra.
    """
    plan_b = _plan(moved_student['org_b'], 'Pack de B')
    previous_b = _membership(moved_student['student'], _plan(moved_student['org_b'], 'Pack viejo de B'))
    _login(api_client, moved_student['admin_b'])

    resp = api_client.post('/api/plans/assign/', {
        'user': moved_student['student'].id, 'plan': plan_b.id,
        'start_date': str(timezone.localdate()),
        'payment': {'method': 'free'},
    }, format='json')

    assert resp.status_code == 201, resp.content
    previous_b.refresh_from_db()
    assert previous_b.is_active is True, 'la membresía anterior de la MISMA org sigue vigente'
    assert StudentPlan.objects.get(id=resp.json()['id']).is_active is True
    assert StudentPlan.objects.filter(
        user=moved_student['student'], organization=moved_student['org_b'], is_active=True,
    ).count() == 2


def test_activate_student_plan_refuses_a_plan_of_another_org(moved_student):
    """Guarda explícita: activar un plan de otra organización crearía una membresía que
    ningún endpoint muestra ni consume (el filtro por organización la deja invisible).
    Mejor fallar que persistir una fila inerte —el webhook de pagos entra por acá."""
    from core.services.plans import activate_student_plan

    plan_a = _plan(moved_student['org_a'], 'Otro pack de A')

    with pytest.raises(Exception):
        activate_student_plan(
            student=moved_student['student'], plan=plan_a,
            start_date=timezone.localdate(),
        )
    assert not StudentPlan.objects.filter(plan=plan_a).exists()


def test_activate_student_plan_works_within_the_org(moved_student):
    """Regresión del camino normal, que es el que usan `assign` y el webhook."""
    from core.services.plans import activate_student_plan

    plan_b = _plan(moved_student['org_b'], 'Pack de B')

    assigned = activate_student_plan(
        student=moved_student['student'], plan=plan_b, start_date=timezone.localdate(),
    )

    assert assigned.is_active is True
    assert assigned.plan_id == plan_b.id
