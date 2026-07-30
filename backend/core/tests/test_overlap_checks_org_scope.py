"""Los chequeos de SOLAPE no pueden mirar la agenda de otras organizaciones.

Misma familia que `test_recurrence_conflict_org_scope`, en los tres sitios que habían
quedado afuera:

    core/models.py       ClassTemplate.clean()        -> solape de profesor
    core/serializers.py  GymClassSerializer.validate  -> solape de profesor
    core/services/reservations.py + core/serializers.py -> solape de ALUMNO

Todos filtraban por la FK propia (`teacher=` / `student=`) sin comparar la organización.
Como `GymClass.teacher`, `ClassTemplate.teacher` y `Enrollment.student` son SET_NULL/CASCADE
sobre el USUARIO y no sobre la organización, mover a una persona de la org A a la org B le
deja sus clases y reservas de A vivas. Desde B, el chequeo de solape las encontraba y
producía dos daños a la vez:

* **Denegación cruzada**: la org B no puede crear su clase/serie/reserva por un dato de la
  org A que no puede ver ni corregir.
* **Oráculo cross-tenant**: el mensaje de error confirma que en ese horario hay algo en la
  otra organización. Barriendo horarios se reconstruye su agenda, un bit por intento.

Alcanzable por gym_admin/manager y, en el caso del alumno, por el propio alumno.
"""
from datetime import time, timedelta

import pytest
from django.utils import timezone

from core.models import (
    Branch,
    ClassTemplate,
    ClassType,
    Discipline,
    Enrollment,
    GymClass,
    Plan,
    StudentPlan,
)

pytestmark = pytest.mark.django_db

PASSWORD = 'Passw0rd2026'


def _login(api_client, user):
    host = {'HTTP_HOST': f'{user.organization.subdomain}.localhost'} if user.organization_id else {}
    token = api_client.post(
        '/api/login/', {'email': user.email, 'password': PASSWORD}, format='json', **host
    ).json()['token']
    api_client.credentials(HTTP_AUTHORIZATION=f'Token {token}')


def _next_monday():
    today = timezone.localdate()
    return today + timedelta(days=(7 - today.weekday()) % 7 or 7)


def _aware(day, hour):
    return timezone.make_aware(
        timezone.datetime.combine(day, time(hour, 0)), timezone.get_current_timezone(),
    )


@pytest.fixture
def moved_teacher(make_organization, make_user):
    """Profesor con agenda en la org A, hoy en la org B."""
    org_a = make_organization()
    org_b = make_organization()
    monday = _next_monday()

    teacher = make_user('nomade', organization=org_a, role='teacher', email='nomade@x.cl')
    branch_a = Branch.objects.create(organization=org_a, name='Sede A')
    # Agenda AJENA: serie y clase de la org A, lunes 10-11.
    ClassTemplate.objects.create(
        organization=org_a, branch=branch_a, teacher=teacher, name='Serie de A',
        weekday=0, start_time=time(10, 0), end_time=time(11, 0), capacity=10,
        start_date=monday - timedelta(days=30),
    )
    GymClass.objects.create(
        organization=org_a, branch=branch_a, teacher=teacher, name='Clase de A',
        start_datetime=_aware(monday, 10), end_datetime=_aware(monday, 11), capacity=10,
        status=GymClass.Status.SCHEDULED,
    )

    teacher.organization = org_b
    teacher.save(update_fields=['organization'])

    return {
        'org_a': org_a, 'org_b': org_b, 'teacher': teacher, 'monday': monday,
        'branch_b': Branch.objects.create(organization=org_b, name='Sede B'),
        'class_type_b': ClassType.objects.create(organization=org_b, name='T B'),
        'discipline_b': Discipline.objects.create(organization=org_b, name='D B'),
        'admin_b': make_user('admin_b', organization=org_b, role='gym_admin'),
    }


def test_class_template_overlap_ignores_other_orgs(api_client, moved_teacher):
    """`ClassTemplate.clean()`: la serie de la org A no puede bloquear a la org B."""
    _login(api_client, moved_teacher['admin_b'])

    resp = api_client.post('/api/class-templates/', {
        'name': 'Serie de B', 'branch': moved_teacher['branch_b'].id,
        'teacher': moved_teacher['teacher'].id,
        'class_type': moved_teacher['class_type_b'].id,
        'discipline': moved_teacher['discipline_b'].id,
        'weekday': 0, 'start_time': '10:00', 'end_time': '11:00', 'capacity': 10,
        'start_date': str(moved_teacher['monday']),
        'end_date': str(moved_teacher['monday']),
    }, format='json')

    assert resp.status_code == 201, resp.content
    assert ClassTemplate.objects.filter(organization=moved_teacher['org_b']).count() == 1


def test_gym_class_overlap_ignores_other_orgs(api_client, moved_teacher):
    """`GymClassSerializer.validate`: la clase de la org A tampoco."""
    _login(api_client, moved_teacher['admin_b'])

    resp = api_client.post('/api/classes/', {
        'name': 'Clase de B', 'branch': moved_teacher['branch_b'].id,
        'teacher': moved_teacher['teacher'].id,
        'class_type': moved_teacher['class_type_b'].id,
        'discipline': moved_teacher['discipline_b'].id,
        'start_datetime': _aware(moved_teacher['monday'], 10).isoformat(),
        'end_datetime': _aware(moved_teacher['monday'], 11).isoformat(),
        'capacity': 10,
    }, format='json')

    assert resp.status_code == 201, resp.content
    assert GymClass.objects.filter(
        organization=moved_teacher['org_b'], name='Clase de B',
    ).exists()


def test_teacher_overlap_is_still_detected_inside_the_org(api_client, moved_teacher):
    """Regresión: el solape REAL —mismo profe, misma org— sigue rebotando."""
    _login(api_client, moved_teacher['admin_b'])
    payload = {
        'name': 'Clase de B', 'branch': moved_teacher['branch_b'].id,
        'teacher': moved_teacher['teacher'].id,
        'class_type': moved_teacher['class_type_b'].id,
        'discipline': moved_teacher['discipline_b'].id,
        'start_datetime': _aware(moved_teacher['monday'], 10).isoformat(),
        'end_datetime': _aware(moved_teacher['monday'], 11).isoformat(),
        'capacity': 10,
    }
    assert api_client.post('/api/classes/', payload, format='json').status_code == 201

    second = api_client.post('/api/classes/', dict(payload, name='Otra de B'), format='json')

    assert second.status_code == 400, second.content
    assert 'teacher' in second.json(), second.content


@pytest.fixture
def moved_student(make_organization, make_user):
    """Alumno con una reserva activa en la org A, hoy en la org B con plan de B."""
    org_a = make_organization()
    org_b = make_organization()
    monday = _next_monday()

    student = make_user('alu', organization=org_a, role='student', email='alu@x.cl')
    teacher_a = make_user('teach_a', organization=org_a, role='teacher')
    branch_a = Branch.objects.create(organization=org_a, name='Sede A')
    class_a = GymClass.objects.create(
        organization=org_a, branch=branch_a, teacher=teacher_a, name='Clase de A',
        start_datetime=_aware(monday, 10), end_datetime=_aware(monday, 11), capacity=10,
        status=GymClass.Status.SCHEDULED,
    )
    Enrollment.objects.create(gym_class=class_a, student=student, status='active')

    student.organization = org_b
    student.save(update_fields=['organization'])

    teacher_b = make_user('teach_b', organization=org_b, role='teacher')
    branch_b = Branch.objects.create(organization=org_b, name='Sede B')
    class_b = GymClass.objects.create(
        organization=org_b, branch=branch_b, teacher=teacher_b, name='Clase de B',
        start_datetime=_aware(monday, 10), end_datetime=_aware(monday, 11), capacity=10,
        status=GymClass.Status.SCHEDULED,
    )
    today = timezone.localdate()
    plan_b = Plan.objects.create(
        organization=org_b, name='Pack de B', plan_type='pack',
        total_classes=10, duration_days=60, price=30000,
    )
    StudentPlan.objects.create(
        user=student, plan=plan_b, start_date=today - timedelta(days=1),
        organization_id=plan_b.organization_id,
        end_date=today + timedelta(days=60), total_classes=10, classes_used=0,
        final_price=30000, is_active=True,
    )
    return {
        'org_a': org_a, 'org_b': org_b, 'student': student, 'class_b': class_b,
        'admin_b': make_user('admin_b2', organization=org_b, role='gym_admin'),
    }


def test_student_overlap_ignores_reservations_of_other_orgs(api_client, moved_student):
    """El alumno reserva en su org nueva; su reserva vieja en otra org no es un solape."""
    _login(api_client, moved_student['admin_b'])

    resp = api_client.post('/api/enrollments/', {
        'gym_class': moved_student['class_b'].id, 'student': moved_student['student'].id,
    }, format='json')

    assert resp.status_code == 201, resp.content
    assert Enrollment.objects.filter(
        gym_class=moved_student['class_b'], student=moved_student['student'],
        status='active',
    ).exists()


def test_student_overlap_is_still_detected_inside_the_org(api_client, moved_student, make_user):
    """Regresión: dos reservas propias a la misma hora en la MISMA org siguen chocando."""
    otra_b = GymClass.objects.create(
        organization=moved_student['org_b'],
        branch=Branch.objects.get(organization=moved_student['org_b']),
        teacher=make_user('teach_b2', organization=moved_student['org_b'], role='teacher'),
        name='Otra de B',
        start_datetime=moved_student['class_b'].start_datetime,
        end_datetime=moved_student['class_b'].end_datetime,
        capacity=10, status=GymClass.Status.SCHEDULED,
    )
    _login(api_client, moved_student['admin_b'])
    first = api_client.post('/api/enrollments/', {
        'gym_class': moved_student['class_b'].id, 'student': moved_student['student'].id,
    }, format='json')
    assert first.status_code == 201, first.content

    second = api_client.post('/api/enrollments/', {
        'gym_class': otra_b.id, 'student': moved_student['student'].id,
    }, format='json')

    assert second.status_code == 400, second.content
