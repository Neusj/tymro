"""El rol `student` tiene que estar acotado por organización, no solo por su identidad.

Es la contracara exacta de `test_teacher_scope_org_boundary`: el profesor se acotaba solo
por `teacher_id` y el alumno solo por `student_id`/`user`:

    queryset.filter(student_id=user.id)        # EnrollmentViewSet / RecurringEnrollmentViewSet
    enrollment.student_id != user.id           # cancel_reservation, perform_destroy
    StudentPlan.objects.filter(user=request.user)   # my-plan / my-memberships

`Enrollment.student`, `RecurringEnrollment.student` y `StudentPlan.user` son CASCADE sobre
el USUARIO, no sobre la organización: si mueven al alumno de la org A a la org B
(`PATCH /api/users/{id}/ {"organization": B}`, que el superadmin puede), todas esas filas
siguen apuntando a la org A. Desde la org B el alumno seguía leyendo sus reservas de A
—con `class_branch_name`, `class_teacher_name`, `class_discipline_name`— y ESCRIBIENDO
sobre ellas.

Y el reverso de consumo que se agregó en `perform_destroy` amplía esa superficie: borrar
una reserva vieja ahora borra el `ConsumptionLog` y decrementa un `StudentPlan` de la
organización que el alumno dejó atrás.
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from core.models import (
    Branch,
    ClassTemplate,
    ConsumptionLog,
    Enrollment,
    GymClass,
    Plan,
    RecurringEnrollment,
    StudentPlan,
)

pytestmark = pytest.mark.django_db

PASSWORD = 'Passw0rd2026'
DENIED = {403, 404}


def _login(api_client, user):
    host = {'HTTP_HOST': f'{user.organization.subdomain}.localhost'} if user.organization_id else {}
    token = api_client.post(
        '/api/login/', {'email': user.email, 'password': PASSWORD}, format='json', **host
    ).json()['token']
    api_client.credentials(HTTP_AUTHORIZATION=f'Token {token}')


@pytest.fixture
def stale_student(make_organization, make_user):
    """Un alumno con historial en la org A al que después mueven a la org B."""
    from datetime import time

    org_a = make_organization()
    org_b = make_organization()
    branch_a = Branch.objects.create(organization=org_a, name='Sede secreta de A')
    teacher_a = make_user('teach_a', organization=org_a, role='teacher', email='teach_a@a.cl')
    student = make_user('nomade', organization=org_a, role='student', email='nomade@x.cl')

    start = timezone.now() + timedelta(days=2)
    class_a = GymClass.objects.create(
        organization=org_a, branch=branch_a, teacher=teacher_a, name='Clase de A',
        start_datetime=start, end_datetime=start + timedelta(hours=1), capacity=10,
        status=GymClass.Status.SCHEDULED,
    )
    today = timezone.localdate()
    plan_a = Plan.objects.create(
        organization=org_a, name='Pack de A', plan_type='pack',
        total_classes=10, duration_days=30, price=30000,
    )
    membership_a = StudentPlan.objects.create(
        user=student, plan=plan_a, start_date=today - timedelta(days=1),
        end_date=today + timedelta(days=30), total_classes=10, classes_used=1,
        final_price=30000, is_active=True,
    )
    enrollment_a = Enrollment.objects.create(
        gym_class=class_a, student=student, status='active',
    )
    ConsumptionLog.objects.create(
        user=student, student_plan=membership_a, class_instance=class_a, branch=branch_a,
    )
    template_a = ClassTemplate.objects.create(
        organization=org_a, branch=branch_a, teacher=teacher_a, name='Serie de A',
        weekday=0, start_time=time(10, 0), end_time=time(11, 0), capacity=10,
        start_date=today,
    )
    recurring_a = RecurringEnrollment.objects.create(
        student=student, class_template=template_a, start_date=today, is_active=True,
    )

    student.organization = org_b
    student.save(update_fields=['organization'])

    return {
        'org_a': org_a, 'org_b': org_b, 'student': student, 'class_a': class_a,
        'enrollment_a': enrollment_a, 'membership_a': membership_a,
        'recurring_a': recurring_a, 'branch_a': branch_a,
    }


def _state(stale_student):
    stale_student['enrollment_a'].refresh_from_db()
    stale_student['membership_a'].refresh_from_db()
    stale_student['recurring_a'].refresh_from_db()
    return (
        stale_student['enrollment_a'].status,
        Enrollment.objects.filter(id=stale_student['enrollment_a'].id).exists(),
        stale_student['membership_a'].classes_used,
        ConsumptionLog.objects.filter(class_instance=stale_student['class_a']).count(),
        stale_student['recurring_a'].is_active,
        RecurringEnrollment.objects.filter(id=stale_student['recurring_a'].id).exists(),
    )


def _rows(response):
    body = response.json()
    return body['results'] if isinstance(body, dict) else body


def test_stale_student_does_not_read_the_other_orgs_reservations(api_client, stale_student):
    """El listado filtraba sede, profe y disciplina de la organización anterior."""
    _login(api_client, stale_student['student'])

    listing = api_client.get('/api/enrollments/')
    mine = api_client.get('/api/enrollments/my/')

    assert listing.status_code == 200, listing.content
    assert mine.status_code == 200, mine.content
    target = stale_student['enrollment_a'].id
    assert not [r for r in _rows(listing) if r['id'] == target], _rows(listing)
    assert not [r for r in _rows(mine) if r['id'] == target], _rows(mine)


def test_stale_student_cannot_cancel_a_reservation_of_the_other_org(api_client, stale_student):
    before = _state(stale_student)
    _login(api_client, stale_student['student'])

    resp = api_client.post(
        f'/api/enrollments/{stale_student["enrollment_a"].id}/cancel/', {}, format='json',
    )

    assert resp.status_code in DENIED, resp.content
    assert _state(stale_student) == before


def test_stale_student_cannot_delete_a_reservation_of_the_other_org(api_client, stale_student):
    """La ruta que el reverso de consumo volvió más peligrosa: borrar acá decrementaría
    un `StudentPlan` de la organización que el alumno dejó."""
    before = _state(stale_student)
    _login(api_client, stale_student['student'])

    resp = api_client.delete(f'/api/enrollments/{stale_student["enrollment_a"].id}/')

    assert resp.status_code in DENIED, resp.content
    assert _state(stale_student) == before


def test_stale_student_does_not_read_the_other_orgs_recurrences(api_client, stale_student):
    _login(api_client, stale_student['student'])

    listing = api_client.get('/api/recurring-enrollments/')
    mine = api_client.get('/api/my-recurring-enrollments/')

    assert listing.status_code == 200, listing.content
    assert mine.status_code == 200, mine.content
    target = stale_student['recurring_a'].id
    assert not [r for r in _rows(listing) if r['id'] == target], _rows(listing)
    assert not [r for r in _rows(mine) if r['id'] == target], _rows(mine)


def test_stale_student_cannot_pause_or_delete_the_other_orgs_recurrence(api_client, stale_student):
    """Pausar y borrar disparan `cancel_future_recurring_enrollments`, que reescribe las
    inscripciones de la organización anterior."""
    before = _state(stale_student)
    _login(api_client, stale_student['student'])

    pause = api_client.patch(
        f'/api/recurring-enrollments/{stale_student["recurring_a"].id}/',
        {'is_active': False}, format='json',
    )
    remove = api_client.delete(f'/api/recurring-enrollments/{stale_student["recurring_a"].id}/')

    assert pause.status_code in DENIED, pause.content
    assert remove.status_code in DENIED, remove.content
    assert _state(stale_student) == before


def test_stale_student_does_not_see_the_other_orgs_membership(api_client, stale_student):
    """`my-plan` y `my-memberships` filtraban solo por usuario: el plan de la org A
    llegaba con su nombre y su precio."""
    _login(api_client, stale_student['student'])

    my_plan = api_client.get('/api/plans/my-plan/')
    my_memberships = api_client.get('/api/plans/my-memberships/')

    assert my_plan.status_code == 200, my_plan.content
    assert my_memberships.status_code == 200, my_memberships.content
    # `Response(None)` de DRF se renderiza como cuerpo VACÍO, no como `null`: por eso se
    # compara el body crudo y no `.json()`, que revienta con contenido vacío.
    assert my_plan.content in (b'', b'null'), my_plan.content
    assert not [
        r for r in _rows(my_memberships) if r['id'] == stale_student['membership_a'].id
    ], _rows(my_memberships)


# ---------------------------------------------------------------------------
# Regresión: el alumno alineado con su organización conserva TODO su acceso
# ---------------------------------------------------------------------------

@pytest.fixture
def aligned_student(make_organization, make_user):
    org = make_organization()
    branch = Branch.objects.create(organization=org, name='Sede')
    teacher = make_user('profe', organization=org, role='teacher', email='profe@gym.cl')
    student = make_user('alu', organization=org, role='student', email='alu@gym.cl')
    start = timezone.now() + timedelta(days=2)
    gym_class = GymClass.objects.create(
        organization=org, branch=branch, teacher=teacher, name='Mi clase',
        start_datetime=start, end_datetime=start + timedelta(hours=1), capacity=10,
        status=GymClass.Status.SCHEDULED,
    )
    today = timezone.localdate()
    plan = Plan.objects.create(
        organization=org, name='Pack 10', plan_type='pack',
        total_classes=10, duration_days=30, price=30000,
    )
    membership = StudentPlan.objects.create(
        user=student, plan=plan, start_date=today - timedelta(days=1),
        end_date=today + timedelta(days=30), total_classes=10, classes_used=1,
        final_price=30000, is_active=True,
    )
    enrollment = Enrollment.objects.create(gym_class=gym_class, student=student, status='active')
    ConsumptionLog.objects.create(
        user=student, student_plan=membership, class_instance=gym_class, branch=branch,
    )
    return {
        'student': student, 'enrollment': enrollment, 'membership': membership,
        'gym_class': gym_class,
    }


def test_aligned_student_keeps_its_reservations_and_membership(api_client, aligned_student):
    """Contra-prueba del acotamiento: el alumno legítimo no pierde nada."""
    _login(api_client, aligned_student['student'])

    listing = api_client.get('/api/enrollments/my/')
    my_plan = api_client.get('/api/plans/my-plan/')
    my_memberships = api_client.get('/api/plans/my-memberships/')

    assert [r for r in _rows(listing) if r['id'] == aligned_student['enrollment'].id], _rows(listing)
    assert my_plan.status_code == 200 and my_plan.json(), my_plan.content
    assert [
        r for r in _rows(my_memberships) if r['id'] == aligned_student['membership'].id
    ], _rows(my_memberships)


def test_aligned_student_can_still_cancel_and_delete_its_reservation(api_client, aligned_student):
    """El camino feliz del alumno: cancelar devuelve el saldo, borrar también."""
    _login(api_client, aligned_student['student'])

    cancel = api_client.post(
        f'/api/enrollments/{aligned_student["enrollment"].id}/cancel/', {}, format='json',
    )

    assert cancel.status_code == 200, cancel.content
    aligned_student['membership'].refresh_from_db()
    assert aligned_student['membership'].classes_used == 0
