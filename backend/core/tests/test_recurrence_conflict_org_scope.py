"""El chequeo de solape de profesor no puede mirar las clases de otras organizaciones.

`generate_instances_for_template_range` filtraba el conflicto así:

    GymClass.objects.filter(teacher=template.teacher, ...)   # sin organization_id

Con un profesor asignado el aislamiento salía por casualidad —el profe es de la org del
actor—, pero `ClassTemplate.teacher` es NULLABLE (y el importador declara la columna
profesor como opcional). Con `teacher=None` el filtro se convierte en `teacher_id IS NULL`
sobre TODA la plataforma: "¿hay alguna clase sin profesor, en cualquier organización, que
solape este horario?".

Dos efectos, ambos alcanzables por gym_admin/manager (no hace falta superadmin):

* **Oráculo cross-tenant**: `generate` DEVUELVE el summary al cliente, con
  `skipped: [{date, reason: 'teacher_conflict'}]`. Barriendo horarios se reconstruye la
  agenda de otro gimnasio, un bit y una fecha por intento.
* **Denegación cruzada**: las clases propias NO se crean por un dato ajeno que el actor no
  puede ver ni corregir.

`ClassTemplate.clean()` ya trata el caso bien (`if not self.teacher: return`, y sus checks
de solape corren solo con profesor); la generación se había quedado atrás.

Tarea 11.A (2026-08): el producto decidió PERMITIR que un mismo profesor tenga clases
solapadas. `_has_teacher_conflict` y sus 3 call sites se eliminaron de
`core/services/recurrence.py`: el reason `'teacher_conflict'` ya no existe en ningún
`summary['skipped']`. Los tests de este archivo que verificaban "no es oráculo cross-org"
siguen siendo válidos (nunca hubo, ni hay, conflicto por datos de otra organización); el
que verificaba la detección real del conflicto INTRA-org se invirtió: ver
`test_generate_still_allows_teacher_overlap_inside_the_org` y
`test_teacher_overlap_relaxed.py` para la cobertura directa del nuevo comportamiento.
"""
from datetime import time, timedelta

import pytest
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


@pytest.fixture
def setup(make_organization, make_user):
    org_a = make_organization()
    org_b = make_organization()
    branch_a = Branch.objects.create(organization=org_a, name='Sede A')
    branch_b = Branch.objects.create(organization=org_b, name='Sede B')
    teacher_b = make_user('teach_b', organization=org_b, role='teacher')

    # La clase AJENA: org B, lunes 18:00-19:00, SIN profesor.
    monday = _next_monday()
    start_b = timezone.make_aware(
        timezone.datetime.combine(monday, time(18, 0)),
        timezone.get_current_timezone(),
    )
    foreign_class = GymClass.objects.create(
        organization=org_b, branch=branch_b, teacher=None, name='Clase privada de B',
        start_datetime=start_b, end_datetime=start_b + timedelta(hours=1), capacity=10,
        status=GymClass.Status.SCHEDULED,
    )

    # La serie PROPIA: org A, lunes 18:30-19:30, también sin profesor → solapa con la de B.
    template_a = ClassTemplate.objects.create(
        organization=org_a, branch=branch_a, teacher=None,
        class_type=ClassType.objects.create(organization=org_a, name='Funcional A'),
        discipline=Discipline.objects.create(organization=org_a, name='Yoga A'),
        name='Serie A', weekday=0, start_time=time(18, 30), end_time=time(19, 30),
        capacity=10, start_date=monday, end_date=monday,
    )

    return {
        'org_a': org_a, 'org_b': org_b, 'monday': monday,
        'foreign_class': foreign_class, 'template_a': template_a, 'teacher_b': teacher_b,
        'admin_a': make_user('admin_a', organization=org_a, role='gym_admin'),
        'branch_a': branch_a,
    }


def test_generate_ignores_teacherless_classes_of_other_orgs(api_client, setup):
    """La serie de la org A tiene que generar su instancia: la clase sin profesor de la
    org B no es un conflicto suyo."""
    _login(api_client, setup['admin_a'])

    resp = api_client.post(f'/api/class-templates/{setup["template_a"].id}/generate/', {
        'from_date': str(setup['monday']), 'until_date': str(setup['monday']),
    }, format='json')

    assert resp.status_code == 200, resp.content
    body = resp.json()
    conflicts = [s for s in body['skipped'] if s.get('reason') == 'teacher_conflict']
    assert not conflicts, (
        'la agenda de otra organización se filtró como teacher_conflict: '
        f'{conflicts}'
    )
    assert body['created_count'] == 1, body
    assert GymClass.objects.filter(
        class_template=setup['template_a'], organization=setup['org_a'],
    ).count() == 1


def test_generate_still_allows_teacher_overlap_inside_the_org(api_client, setup):
    """Tarea 11.A: el conflicto intra-org —mismo profesor, misma org— YA NO se saltea:
    la instancia se crea igual (antes: created_count=0, skipped=['teacher_conflict'])."""
    teacher_a = setup['admin_a'].organization.users.filter(role='teacher').first()
    if teacher_a is None:
        from django.contrib.auth import get_user_model
        teacher_a = get_user_model().objects.create_user(
            username='teach_a', password=PASSWORD, organization=setup['org_a'],
            role='teacher', email='teach_a@a.cl',
        )
    template = setup['template_a']
    template.teacher = teacher_a
    template.save(update_fields=['teacher'])

    start = timezone.make_aware(
        timezone.datetime.combine(setup['monday'], time(18, 45)),
        timezone.get_current_timezone(),
    )
    GymClass.objects.create(
        organization=setup['org_a'], branch=setup['branch_a'], teacher=teacher_a,
        name='Ya ocupada', start_datetime=start, end_datetime=start + timedelta(hours=1),
        capacity=10, status=GymClass.Status.SCHEDULED,
    )

    _login(api_client, setup['admin_a'])
    resp = api_client.post(f'/api/class-templates/{template.id}/generate/', {
        'from_date': str(setup['monday']), 'until_date': str(setup['monday']),
    }, format='json')

    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body['created_count'] == 1, body
    assert not [s for s in body['skipped'] if s.get('reason') == 'teacher_conflict'], body


def test_deleting_a_teacher_does_not_expose_the_series_to_other_orgs(api_client, setup):
    """El estado `teacher=None` es alcanzable con SOLO la API: `ClassTemplate.teacher` y
    `GymClass.teacher` son ambos SET_NULL, así que borrar un profesor deja sus series y
    sus clases sin profesor. Desde ahí, cada organización que genere empieza a chocar con
    las clases sin profesor de todas las demás.

    (El importador es la otra puerta: declara la columna profesor como opcional.)
    """
    from django.contrib.auth import get_user_model
    teacher_a = get_user_model().objects.create_user(
        username='teach_a_tmp', password=PASSWORD, organization=setup['org_a'],
        role='teacher', email='teach_a_tmp@a.cl',
    )
    template = setup['template_a']
    template.teacher = teacher_a
    template.save(update_fields=['teacher'])

    _login(api_client, setup['admin_a'])
    assert api_client.delete(f'/api/users/{teacher_a.id}/').status_code == 204

    template.refresh_from_db()
    assert template.teacher_id is None, 'precondición: el SET_NULL dejó la serie sin profe'

    resp = api_client.post(f'/api/class-templates/{template.id}/generate/', {
        'from_date': str(setup['monday']), 'until_date': str(setup['monday']),
    }, format='json')

    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert not [s for s in body['skipped'] if s.get('reason') == 'teacher_conflict'], body
    assert body['created_count'] == 1, body


def test_the_other_orgs_class_is_never_touched(api_client, setup):
    """La generación de A no puede escribir sobre la clase de B."""
    before = (
        setup['foreign_class'].name,
        setup['foreign_class'].status,
        setup['foreign_class'].class_template_id,
    )
    _login(api_client, setup['admin_a'])

    api_client.post(f'/api/class-templates/{setup["template_a"].id}/generate/', {
        'from_date': str(setup['monday']), 'until_date': str(setup['monday']),
    }, format='json')

    setup['foreign_class'].refresh_from_db()
    assert (
        setup['foreign_class'].name,
        setup['foreign_class'].status,
        setup['foreign_class'].class_template_id,
    ) == before
