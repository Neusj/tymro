"""Tarea 11.A: el mismo profesor puede tener clases solapadas en el horario.

El producto decidió permitirlo (caso real: el profesor dicta MMA y boxeo en paralelo y
el alumno elige a cuál ir). Esto relaja el bloqueo de solape profesor+horario en sus 3
puntos:

    core/serializers.py           GymClassSerializer.validate()   (chequeo eliminado)
    core/models.py                ClassTemplate.clean()            (chequeo eliminado)
    core/services/recurrence.py   _has_teacher_conflict + sus 3 call sites (función
                                   eliminada; las instancias ya no se saltean)

Estos tests cubren el nuevo comportamiento (solape permitido) y, como contra-prueba,
verifican que el resto de las validaciones —organización cruzada, capacidad, fechas—
siguen intactas: la tarea NO debe tocarlas.
"""
from datetime import time, timedelta

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from core.models import Branch, ClassTemplate, ClassType, Discipline, GymClass

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


def _aware(day, hour, minute=0):
    return timezone.make_aware(
        timezone.datetime.combine(day, time(hour, minute)), timezone.get_current_timezone(),
    )


@pytest.fixture
def setup(make_organization, make_user):
    org = make_organization()
    other_org = make_organization()
    branch = Branch.objects.create(organization=org, name='Sede')
    other_branch = Branch.objects.create(organization=other_org, name='Sede ajena')
    class_type = ClassType.objects.create(organization=org, name='Funcional')
    discipline_mma = Discipline.objects.create(organization=org, name='MMA')
    discipline_boxeo = Discipline.objects.create(organization=org, name='Boxeo')
    teacher = make_user('jonathan', organization=org, role='teacher', email='jonathan@x.cl')
    other_teacher = make_user('otro_prof', organization=other_org, role='teacher', email='otro@y.cl')
    admin = make_user('admin', organization=org, role='gym_admin')
    return {
        'org': org, 'other_org': other_org, 'branch': branch, 'other_branch': other_branch,
        'class_type': class_type, 'discipline_mma': discipline_mma, 'discipline_boxeo': discipline_boxeo,
        'teacher': teacher, 'other_teacher': other_teacher, 'admin': admin, 'monday': _next_monday(),
    }


# ---------------------------------------------------------------------------
# 1. GymClassSerializer: el mismo profe puede tener 2 clases solapadas.
# ---------------------------------------------------------------------------

def test_gym_class_serializer_allows_teacher_overlap(api_client, setup):
    """Jonathan dicta MMA y Boxeo a la misma hora: ambas clases se crean OK (antes la
    segunda daba 400 con 'El profesor ya está asignado a otra clase en ese horario.')."""
    _login(api_client, setup['admin'])
    start = _aware(setup['monday'], 18)
    end = _aware(setup['monday'], 19)

    first = api_client.post('/api/classes/', {
        'name': 'MMA', 'branch': setup['branch'].id, 'teacher': setup['teacher'].id,
        'class_type': setup['class_type'].id, 'discipline': setup['discipline_mma'].id,
        'start_datetime': start.isoformat(), 'end_datetime': end.isoformat(), 'capacity': 10,
    }, format='json')
    assert first.status_code == 201, first.content

    second = api_client.post('/api/classes/', {
        'name': 'Boxeo', 'branch': setup['branch'].id, 'teacher': setup['teacher'].id,
        'class_type': setup['class_type'].id, 'discipline': setup['discipline_boxeo'].id,
        'start_datetime': start.isoformat(), 'end_datetime': end.isoformat(), 'capacity': 10,
    }, format='json')
    assert second.status_code == 201, second.content

    assert GymClass.objects.filter(
        organization=setup['org'], teacher=setup['teacher'], start_datetime=start,
    ).count() == 2


def test_gym_class_serializer_still_rejects_teacher_from_another_org(api_client, setup):
    """Contra-prueba: el chequeo cross-org de teacher no se tocó."""
    _login(api_client, setup['admin'])
    start = _aware(setup['monday'], 10)
    end = _aware(setup['monday'], 11)
    resp = api_client.post('/api/classes/', {
        'name': 'Ajena', 'branch': setup['branch'].id, 'teacher': setup['other_teacher'].id,
        'class_type': setup['class_type'].id, 'discipline': setup['discipline_mma'].id,
        'start_datetime': start.isoformat(), 'end_datetime': end.isoformat(), 'capacity': 10,
    }, format='json')
    assert resp.status_code == 400, resp.content
    assert 'teacher' in resp.json()


def test_gym_class_serializer_still_rejects_branch_from_another_org(api_client, setup):
    """Contra-prueba: el chequeo cross-org de branch no se tocó."""
    _login(api_client, setup['admin'])
    start = _aware(setup['monday'], 10)
    end = _aware(setup['monday'], 11)
    resp = api_client.post('/api/classes/', {
        'name': 'Ajena', 'branch': setup['other_branch'].id, 'teacher': setup['teacher'].id,
        'class_type': setup['class_type'].id, 'discipline': setup['discipline_mma'].id,
        'start_datetime': start.isoformat(), 'end_datetime': end.isoformat(), 'capacity': 10,
    }, format='json')
    assert resp.status_code == 400, resp.content
    assert 'branch' in resp.json()


def test_gym_class_serializer_still_rejects_end_before_start(api_client, setup):
    """Contra-prueba: fin <= inicio sigue rebotando."""
    _login(api_client, setup['admin'])
    start = _aware(setup['monday'], 10)
    end = start - timedelta(hours=1)
    resp = api_client.post('/api/classes/', {
        'name': 'Mal', 'branch': setup['branch'].id, 'teacher': setup['teacher'].id,
        'class_type': setup['class_type'].id, 'discipline': setup['discipline_mma'].id,
        'start_datetime': start.isoformat(), 'end_datetime': end.isoformat(), 'capacity': 10,
    }, format='json')
    assert resp.status_code == 400, resp.content
    assert 'end_datetime' in resp.json()


def test_gym_class_serializer_still_rejects_zero_capacity(api_client, setup):
    """Contra-prueba: capacidad <= 0 sigue rebotando."""
    _login(api_client, setup['admin'])
    start = _aware(setup['monday'], 10)
    end = _aware(setup['monday'], 11)
    resp = api_client.post('/api/classes/', {
        'name': 'Mal', 'branch': setup['branch'].id, 'teacher': setup['teacher'].id,
        'class_type': setup['class_type'].id, 'discipline': setup['discipline_mma'].id,
        'start_datetime': start.isoformat(), 'end_datetime': end.isoformat(), 'capacity': 0,
    }, format='json')
    assert resp.status_code == 400, resp.content
    assert 'capacity' in resp.json()


# ---------------------------------------------------------------------------
# 2. ClassTemplate.clean(): el mismo profe puede tener 2 plantillas/clases
#    solapadas en el mismo weekday.
# ---------------------------------------------------------------------------

def test_class_template_clean_allows_teacher_overlap_between_templates(setup):
    """Dos plantillas activas del mismo profe, mismo weekday, horario solapado:
    full_clean() pasa en ambas (antes la 2da lanzaba 'ya tiene otra plantilla activa
    en ese horario.')."""
    first = ClassTemplate(
        organization=setup['org'], branch=setup['branch'], teacher=setup['teacher'],
        class_type=setup['class_type'], discipline=setup['discipline_mma'],
        name='MMA', weekday=0, start_time=time(18, 0), end_time=time(19, 0),
        capacity=10, start_date=setup['monday'],
    )
    first.full_clean()
    first.save()

    second = ClassTemplate(
        organization=setup['org'], branch=setup['branch'], teacher=setup['teacher'],
        class_type=setup['class_type'], discipline=setup['discipline_boxeo'],
        name='Boxeo', weekday=0, start_time=time(18, 30), end_time=time(19, 30),
        capacity=10, start_date=setup['monday'],
    )
    second.full_clean()
    second.save()

    assert ClassTemplate.objects.filter(organization=setup['org'], teacher=setup['teacher']).count() == 2


def test_class_template_clean_allows_overlap_with_existing_gym_class(setup):
    """El profe ya tiene una clase EN EL CALENDARIO que se cruza: la plantilla nueva
    pasa igual (antes lanzaba 'ya tiene clases creadas que se cruzan con esta
    plantilla.')."""
    start = _aware(setup['monday'], 18)
    GymClass.objects.create(
        organization=setup['org'], branch=setup['branch'], teacher=setup['teacher'],
        name='Ya en calendario', start_datetime=start, end_datetime=start + timedelta(hours=1),
        capacity=10, status=GymClass.Status.SCHEDULED,
    )
    template = ClassTemplate(
        organization=setup['org'], branch=setup['branch'], teacher=setup['teacher'],
        class_type=setup['class_type'], discipline=setup['discipline_boxeo'],
        name='Boxeo', weekday=setup['monday'].weekday(), start_time=time(18, 30), end_time=time(19, 30),
        capacity=10, start_date=setup['monday'],
    )
    template.full_clean()


def test_class_template_clean_still_rejects_teacher_from_another_org(setup):
    """Contra-prueba: el chequeo cross-org de teacher no se tocó."""
    template = ClassTemplate(
        organization=setup['org'], branch=setup['branch'], teacher=setup['other_teacher'],
        class_type=setup['class_type'], discipline=setup['discipline_mma'],
        name='Ajena', weekday=0, start_time=time(10, 0), end_time=time(11, 0),
        capacity=10, start_date=setup['monday'],
    )
    with pytest.raises(ValidationError):
        template.full_clean()


def test_class_template_clean_still_rejects_branch_from_another_org(setup):
    """Contra-prueba: el chequeo cross-org de branch no se tocó."""
    template = ClassTemplate(
        organization=setup['org'], branch=setup['other_branch'], teacher=setup['teacher'],
        class_type=setup['class_type'], discipline=setup['discipline_mma'],
        name='Ajena', weekday=0, start_time=time(10, 0), end_time=time(11, 0),
        capacity=10, start_date=setup['monday'],
    )
    with pytest.raises(ValidationError):
        template.full_clean()


def test_class_template_clean_still_rejects_zero_capacity(setup):
    """Contra-prueba: capacidad <= 0 sigue rebotando."""
    template = ClassTemplate(
        organization=setup['org'], branch=setup['branch'], teacher=setup['teacher'],
        class_type=setup['class_type'], discipline=setup['discipline_mma'],
        name='Mal', weekday=0, start_time=time(10, 0), end_time=time(11, 0),
        capacity=0, start_date=setup['monday'],
    )
    with pytest.raises(ValidationError):
        template.full_clean()


def test_class_template_clean_still_rejects_end_before_start(setup):
    """Contra-prueba: fin <= inicio sigue rebotando."""
    template = ClassTemplate(
        organization=setup['org'], branch=setup['branch'], teacher=setup['teacher'],
        class_type=setup['class_type'], discipline=setup['discipline_mma'],
        name='Mal', weekday=0, start_time=time(11, 0), end_time=time(10, 0),
        capacity=10, start_date=setup['monday'],
    )
    with pytest.raises(ValidationError):
        template.full_clean()


# ---------------------------------------------------------------------------
# 3. core/services/recurrence.py: los 3 call sites de _has_teacher_conflict ya
#    no salteen instancias por solape de profesor.
# ---------------------------------------------------------------------------

def test_generate_instances_creates_instance_despite_teacher_overlap(api_client, setup):
    """generate_instances_for_template_range (call site ~211): la instancia se crea
    aunque el profe ya tenga otra clase solapada (antes: skipped/teacher_conflict)."""
    monday = setup['monday']
    start = _aware(monday, 18)
    GymClass.objects.create(
        organization=setup['org'], branch=setup['branch'], teacher=setup['teacher'],
        name='Ya ocupada', start_datetime=start, end_datetime=start + timedelta(hours=1),
        capacity=10, status=GymClass.Status.SCHEDULED,
    )
    template = ClassTemplate.objects.create(
        organization=setup['org'], branch=setup['branch'], teacher=setup['teacher'],
        class_type=setup['class_type'], discipline=setup['discipline_boxeo'],
        name='Boxeo', weekday=0, start_time=time(18, 0), end_time=time(19, 0),
        capacity=10, start_date=monday, end_date=monday,
    )
    _login(api_client, setup['admin'])

    resp = api_client.post(f'/api/class-templates/{template.id}/generate/', {
        'from_date': str(monday), 'until_date': str(monday),
    }, format='json')

    assert resp.status_code == 200, resp.content
    body = resp.json()
    conflicts = [s for s in body['skipped'] if s.get('reason') == 'teacher_conflict']
    assert not conflicts, body
    assert body['created_count'] == 1, body
    assert GymClass.objects.filter(class_template=template).exists()


def test_apply_template_updates_does_not_protect_on_teacher_overlap(setup):
    """apply_template_updates_to_future_instances (call site ~281): la instancia se
    actualiza igual aunque la nueva franja choque con otra clase del mismo profe
    (antes: quedaba en protected_count/protected_ids)."""
    from core.services.recurrence import apply_template_updates_to_future_instances

    monday = setup['monday']
    template = ClassTemplate.objects.create(
        organization=setup['org'], branch=setup['branch'], teacher=setup['teacher'],
        class_type=setup['class_type'], discipline=setup['discipline_mma'],
        name='Serie', weekday=0, start_time=time(18, 0), end_time=time(19, 0),
        capacity=10, start_date=monday - timedelta(days=30),
    )
    start = _aware(monday, 18)
    instance = GymClass.objects.create(
        organization=setup['org'], branch=setup['branch'], teacher=setup['teacher'],
        class_template=template, name='Instancia', start_datetime=start,
        end_datetime=start + timedelta(hours=1), capacity=10, status=GymClass.Status.SCHEDULED,
    )
    # Otra clase del MISMO profe que se solapa con la franja de la instancia.
    GymClass.objects.create(
        organization=setup['org'], branch=setup['branch'], teacher=setup['teacher'],
        name='Choca', start_datetime=start, end_datetime=start + timedelta(hours=1),
        capacity=10, status=GymClass.Status.SCHEDULED,
    )

    template.name = 'Serie renombrada'
    template.save(update_fields=['name'])
    summary = apply_template_updates_to_future_instances(template)

    assert summary['protected_count'] == 0, summary
    assert summary['updated_count'] == 1, summary
    instance.refresh_from_db()
    assert instance.name == 'Serie renombrada'


def test_reactivate_future_cancelled_does_not_skip_on_teacher_overlap(setup):
    """reactivate_future_cancelled_instances_for_template (call site ~434): la
    instancia cancelada se reactiva aunque choque con otra clase del mismo profe
    (antes: skipped/teacher_conflict)."""
    from core.services.recurrence import reactivate_future_cancelled_instances_for_template

    monday = setup['monday']
    template = ClassTemplate.objects.create(
        organization=setup['org'], branch=setup['branch'], teacher=setup['teacher'],
        class_type=setup['class_type'], discipline=setup['discipline_mma'],
        name='Serie', weekday=0, start_time=time(18, 0), end_time=time(19, 0),
        capacity=10, start_date=monday - timedelta(days=30),
    )
    start = _aware(monday, 18)
    cancelled = GymClass.objects.create(
        organization=setup['org'], branch=setup['branch'], teacher=setup['teacher'],
        class_template=template, name='Cancelada', start_datetime=start,
        end_datetime=start + timedelta(hours=1), capacity=10, status=GymClass.Status.CANCELLED,
        is_active=False,
    )
    GymClass.objects.create(
        organization=setup['org'], branch=setup['branch'], teacher=setup['teacher'],
        name='Choca', start_datetime=start, end_datetime=start + timedelta(hours=1),
        capacity=10, status=GymClass.Status.SCHEDULED,
    )

    summary = reactivate_future_cancelled_instances_for_template(template)

    assert summary['reactivated_count'] == 1, summary
    assert not [s for s in summary['skipped'] if s.get('reason') == 'teacher_conflict'], summary
    cancelled.refresh_from_db()
    assert cancelled.status == GymClass.Status.SCHEDULED
