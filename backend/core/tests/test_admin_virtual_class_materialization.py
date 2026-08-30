"""Inscripcion del ADMIN sobre una clase proyectada.

El alumno ya tenia el camino on-demand: `POST /api/enrollments/` con `class_template_id` +
`date` materializa la clase Y lo inscribe en un solo acto, de modo que el consumo del plan
ocurre exactamente cuando hay una inscripcion. El admin no tenia equivalente porque su modal
exige PK real para armar el roster.

La regla de diseno que fija este archivo: **abrir el picker no crea nada**. Materializar es
efecto de la INSCRIPCION, no de mirar. Lo contrario dejaba clases creadas por un clic
arrepentido, y creadas ademas sin el ciclo que corre la generacion por lote.

El rango es UNO SOLO y es el que ya obedece el alumno: `max_reservation_window_days`.
"""
from datetime import time, timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import Branch, ClassTemplate, Enrollment, GymClass, Plan, StudentPlan

pytestmark = pytest.mark.django_db

ENROLLMENTS = '/api/enrollments/'


def _roster(template_id):
    return f'/api/class-templates/{template_id}/enrollable-students/'


@pytest.fixture
def world(make_organization, make_user):
    org = make_organization('Org Admin Virtual')
    org.max_reservation_window_days = 7
    org.save(update_fields=['max_reservation_window_days'])
    return {
        'org': org,
        'admin': make_user('admin-virtual', organization=org, role='gym_admin'),
        'teacher': make_user('teacher-admin-virtual', organization=org, role='teacher'),
        'student': make_user('student-admin-virtual', organization=org, role='student'),
        'branch': Branch.objects.create(organization=org, name='Sede'),
    }


def _student_plan(org, student, *, total_classes=20, classes_used=0):
    plan = Plan.objects.create(
        organization=org,
        name=f'Pack {student.id}',
        plan_type='pack',
        total_classes=total_classes,
        duration_days=60,
        price=30000,
    )
    return StudentPlan.objects.create(
        user=student,
        plan=plan,
        organization_id=org.id,
        start_date=timezone.localdate() - timedelta(days=1),
        end_date=timezone.localdate() + timedelta(days=60),
        total_classes=total_classes,
        classes_used=classes_used,
        final_price=plan.price,
    )


def _template(world, target_date, *, is_active=True):
    return ClassTemplate.objects.create(
        organization=world['org'],
        branch=world['branch'],
        teacher=world['teacher'],
        name='Serie proyectada',
        weekday=target_date.weekday(),
        start_time=time(10, 0),
        end_time=time(11, 0),
        capacity=10,
        start_date=target_date - timedelta(days=30),
        is_active=is_active,
    )


def _client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _tomorrow():
    return timezone.localdate() + timedelta(days=1)


def _enroll_payload(template, target_date, student):
    return {
        'class_template_id': template.id,
        'date': target_date.isoformat(),
        'student': student.id,
    }


# ---------------------------------------------------------------- roster (picker)

def test_admin_lists_enrollable_students_of_a_projected_series(world):
    target_date = _tomorrow()
    template = _template(world, target_date)
    _student_plan(world['org'], world['student'])

    response = _client(world['admin']).get(_roster(template.id))

    assert response.status_code == 200, response.data
    returned = [item['id'] for item in response.data]
    assert world['student'].id in returned
    # El propio gym_admin tambien es sujeto inscribible (P4), asi que aparece: la lista no es
    # solo de alumnos. Lo que importa es que el saldo viaje para decidir la inscripcion.
    entry = next(item for item in response.data if item['id'] == world['student'].id)
    assert entry['available_classes'] == 20
    assert entry['has_available_classes'] is True


def test_opening_the_roster_does_not_create_the_class(world):
    """La regla del diseno: mirar no materializa. Un clic arrepentido no deja clase."""
    target_date = _tomorrow()
    template = _template(world, target_date)
    _student_plan(world['org'], world['student'])

    response = _client(world['admin']).get(_roster(template.id))

    assert response.status_code == 200, response.data
    assert not GymClass.objects.filter(class_template=template).exists()


def test_roster_excludes_the_teacher_of_the_series(world):
    target_date = _tomorrow()
    template = _template(world, target_date)
    _student_plan(world['org'], world['teacher'])
    _student_plan(world['org'], world['student'])

    response = _client(world['admin']).get(_roster(template.id))

    assert response.status_code == 200, response.data
    assert world['teacher'].id not in [item['id'] for item in response.data]


def test_roster_of_another_organization_gets_404(world, make_organization, make_user):
    template = _template(world, _tomorrow())
    other_org = make_organization('Org Ajena')
    intruder = make_user('admin-ajeno', organization=other_org, role='gym_admin')

    response = _client(intruder).get(_roster(template.id))

    # 404 y no 403: un 403 confirmaria que esa plantilla existe en otro tenant.
    assert response.status_code == 404, response.data


def test_roster_never_leaks_students_of_another_organization(world, make_organization, make_user):
    template = _template(world, _tomorrow())
    _student_plan(world['org'], world['student'])
    other_org = make_organization('Org Vecina')
    outsider = make_user('alumno-ajeno', organization=other_org, role='student')
    _student_plan(other_org, outsider)

    response = _client(world['admin']).get(_roster(template.id))

    assert response.status_code == 200, response.data
    returned = [item['id'] for item in response.data]
    # No vacuo: el alumno ajeno EXISTE y es inscribible en su propia org.
    assert outsider.id not in returned
    assert world['student'].id in returned


@pytest.mark.parametrize('actor_key', ['teacher', 'student'])
def test_non_admin_roles_cannot_read_the_roster(world, actor_key):
    template = _template(world, _tomorrow())

    response = _client(world[actor_key]).get(_roster(template.id))

    assert response.status_code == 403, response.data


# ---------------------------------------------------------------- inscripcion

def test_enrolling_materializes_the_class_and_consumes_the_plan(world):
    target_date = _tomorrow()
    template = _template(world, target_date)
    student_plan = _student_plan(world['org'], world['student'])
    assert not GymClass.objects.filter(class_template=template).exists()

    response = _client(world['admin']).post(
        ENROLLMENTS, _enroll_payload(template, target_date, world['student']), format='json'
    )

    assert response.status_code == 201, response.data
    gym_class = GymClass.objects.get(class_template=template)
    assert timezone.localtime(gym_class.start_datetime).date() == target_date
    assert Enrollment.objects.filter(gym_class=gym_class, student=world['student'], status='active').exists()
    student_plan.refresh_from_db()
    assert student_plan.classes_used == 1


def test_enrolling_twice_reuses_the_same_class(world, make_user):
    target_date = _tomorrow()
    template = _template(world, target_date)
    second = make_user('otro-alumno', organization=world['org'], role='student')
    _student_plan(world['org'], world['student'])
    _student_plan(world['org'], second)
    client = _client(world['admin'])

    first = client.post(ENROLLMENTS, _enroll_payload(template, target_date, world['student']), format='json')
    again = client.post(ENROLLMENTS, _enroll_payload(template, target_date, second), format='json')

    assert first.status_code == 201, first.data
    assert again.status_code == 201, again.data
    assert GymClass.objects.filter(class_template=template, start_datetime__date=target_date).count() == 1


@pytest.mark.parametrize(
    'shift_days, expect_weekday_match',
    [
        (30, True),   # fuera de max_reservation_window_days (la org configuro 7)
        (-1, True),   # fecha pasada
    ],
)
def test_enrolling_out_of_range_creates_nothing(world, shift_days, expect_weekday_match):
    target_date = timezone.localdate() + timedelta(days=shift_days)
    template = _template(world, target_date)
    _student_plan(world['org'], world['student'])

    response = _client(world['admin']).post(
        ENROLLMENTS, _enroll_payload(template, target_date, world['student']), format='json'
    )

    assert response.status_code == 400, response.data
    assert not GymClass.objects.filter(class_template=template).exists()


def test_enrolling_on_a_date_that_is_not_the_series_weekday_creates_nothing(world):
    target_date = _tomorrow()
    template = _template(world, target_date)
    _student_plan(world['org'], world['student'])

    response = _client(world['admin']).post(
        ENROLLMENTS,
        _enroll_payload(template, target_date + timedelta(days=1), world['student']),
        format='json',
    )

    assert response.status_code == 400, response.data
    assert not GymClass.objects.filter(class_template=template).exists()


def test_enrolling_on_an_inactive_series_creates_nothing(world):
    target_date = _tomorrow()
    template = _template(world, target_date, is_active=False)
    _student_plan(world['org'], world['student'])

    response = _client(world['admin']).post(
        ENROLLMENTS, _enroll_payload(template, target_date, world['student']), format='json'
    )

    assert response.status_code == 400, response.data
    assert not GymClass.objects.filter(class_template=template).exists()


def test_admin_of_another_organization_cannot_enroll_into_a_projected_class(world, make_organization, make_user):
    target_date = _tomorrow()
    template = _template(world, target_date)
    other_org = make_organization('Org Ajena')
    intruder = make_user('admin-ajeno-2', organization=other_org, role='gym_admin')
    victim = make_user('victima', organization=world['org'], role='student')
    _student_plan(world['org'], victim)

    response = _client(intruder).post(
        ENROLLMENTS, _enroll_payload(template, target_date, victim), format='json'
    )

    assert response.status_code == 404, response.data
    assert not GymClass.objects.filter(class_template=template).exists()
