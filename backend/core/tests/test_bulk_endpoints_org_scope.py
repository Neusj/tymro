"""Los endpoints bulk no pueden revelar qué ids existen en otras organizaciones.

`bulk-close` y `bulk-action` reciben los ids en el body —`get_object()` no protege— y
construían el queryset sin acotar por organización:

    GymClass.objects.filter(id__in=class_ids)          # bulk-close
    ClassTemplate.objects.filter(id__in=template_ids)  # bulk-action

El aislamiento quedaba delegado por completo al helper por objeto (`_can_close_or_cancel` /
`_can_manage_operational_resource`), que sí niega la escritura. Pero la respuesta delata la
diferencia: un id AJENO aparece en `skipped` con motivo "Sin permisos", y un id INEXISTENTE
simplemente no aparece. Con eso cualquier autenticado —incluido un alumno— barre el espacio
global de ids de `GymClass` y `ClassTemplate` de todos los tenants.

El arreglo acota el queryset ANTES del bucle (el helper por objeto queda como segunda capa)
y unifica el motivo, para que "ajeno" e "inexistente" sean indistinguibles.
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


@pytest.fixture
def two_orgs(make_organization, make_user):
    org_a = make_organization()
    org_b = make_organization()
    teacher_b = make_user('teach_b', organization=org_b, role='teacher')
    branch_b = Branch.objects.create(organization=org_b, name='Sede B')
    start = timezone.now() + timedelta(days=2)
    class_b = GymClass.objects.create(
        organization=org_b, branch=branch_b, teacher=teacher_b, name='Clase de B',
        start_datetime=start, end_datetime=start + timedelta(hours=1), capacity=10,
        status=GymClass.Status.SCHEDULED,
    )
    template_b = ClassTemplate.objects.create(
        organization=org_b, branch=branch_b, teacher=teacher_b,
        class_type=ClassType.objects.create(organization=org_b, name='T B'),
        discipline=Discipline.objects.create(organization=org_b, name='D B'),
        name='Serie de B', weekday=0, start_time=time(10, 0), end_time=time(11, 0),
        capacity=10, start_date=timezone.localdate(),
    )
    return {
        'org_a': org_a, 'org_b': org_b,
        'class_b': class_b, 'template_b': template_b,
        'admin_a': make_user('admin_a', organization=org_a, role='gym_admin'),
        'manager_a': make_user('gerente_a', organization=org_a, role='manager'),
        'monitor_a': make_user('monitor_a', organization=org_a, role='monitor'),
        'teacher_a': make_user('teach_a', organization=org_a, role='teacher'),
        'student_a': make_user('alu_a', organization=org_a, role='student', email='alu_a@a.cl'),
    }


def _missing_class_id(two_orgs):
    return (GymClass.objects.order_by('-id').first().id) + 1000


def _missing_template_id(two_orgs):
    return (ClassTemplate.objects.order_by('-id').first().id) + 1000


@pytest.mark.parametrize('actor', ['admin_a', 'manager_a', 'monitor_a', 'teacher_a', 'student_a'])
def test_bulk_close_does_not_reveal_foreign_class_ids(api_client, two_orgs, actor):
    """El id ajeno tiene que ser indistinguible de uno inexistente."""
    _login(api_client, two_orgs[actor])
    foreign = two_orgs['class_b'].id
    missing = _missing_class_id(two_orgs)

    resp = api_client.post('/api/classes/bulk-close/', {
        'class_ids': [foreign, missing], 'action': 'cancel', 'comment': 'sonda',
    }, format='json')

    assert resp.status_code in {200, 403}, resp.content
    if resp.status_code == 200:
        body = resp.json()
        assert body['updated_ids'] == [], body
        reported = {item['id']: item.get('reason') for item in body['skipped']}
        assert reported.get(foreign) == reported.get(missing), (
            f'la respuesta distingue el id ajeno del inexistente: {reported}'
        )
    two_orgs['class_b'].refresh_from_db()
    assert two_orgs['class_b'].status == GymClass.Status.SCHEDULED


@pytest.mark.parametrize('actor', ['admin_a', 'manager_a', 'monitor_a', 'teacher_a', 'student_a'])
def test_bulk_action_does_not_reveal_foreign_template_ids(api_client, two_orgs, actor):
    _login(api_client, two_orgs[actor])
    foreign = two_orgs['template_b'].id
    missing = _missing_template_id(two_orgs)

    resp = api_client.post('/api/class-templates/bulk-action/', {
        'action': 'deactivate', 'template_ids': [foreign, missing],
    }, format='json')

    assert resp.status_code in {200, 403}, resp.content
    if resp.status_code == 200:
        body = resp.json()
        assert body['updated_ids'] == [], body
        reported = {item['id']: item.get('reason') for item in body['skipped']}
        assert reported.get(foreign) == reported.get(missing), (
            f'la respuesta distingue el id ajeno del inexistente: {reported}'
        )
    two_orgs['template_b'].refresh_from_db()
    assert two_orgs['template_b'].is_active is True


def test_bulk_endpoints_reject_non_numeric_ids(api_client, two_orgs):
    """Los ids sólo se validaban como "lista no vacía": `filter(id__in=['abc'])` reventaba
    con ValueError → 500 sin manejar."""
    _login(api_client, two_orgs['admin_a'])

    close = api_client.post('/api/classes/bulk-close/', {
        'class_ids': ['abc'], 'action': 'cancel', 'comment': 'sonda',
    }, format='json')
    action = api_client.post('/api/class-templates/bulk-action/', {
        'action': 'deactivate', 'template_ids': ['abc'],
    }, format='json')

    assert close.status_code == 400, close.content
    assert action.status_code == 400, action.content


# ---------------------------------------------------------------------------
# Regresión: el bulk sobre la PROPIA organización sigue funcionando
# ---------------------------------------------------------------------------

@pytest.fixture
def own_org(make_organization, make_user):
    org = make_organization()
    branch = Branch.objects.create(organization=org, name='Sede')
    teacher = make_user('profe', organization=org, role='teacher', email='profe@gym.cl')
    start = timezone.now() + timedelta(days=2)
    gym_class = GymClass.objects.create(
        organization=org, branch=branch, teacher=teacher, name='Mi clase',
        start_datetime=start, end_datetime=start + timedelta(hours=1), capacity=10,
        status=GymClass.Status.SCHEDULED,
    )
    template = ClassTemplate.objects.create(
        organization=org, branch=branch, teacher=teacher,
        class_type=ClassType.objects.create(organization=org, name='T'),
        discipline=Discipline.objects.create(organization=org, name='D'),
        name='Mi serie', weekday=0, start_time=time(10, 0), end_time=time(11, 0),
        capacity=10, start_date=timezone.localdate(),
    )
    return {
        'org': org, 'gym_class': gym_class, 'template': template,
        'admin': make_user('admin', organization=org, role='gym_admin'),
    }


def test_bulk_close_still_works_in_your_own_org(api_client, own_org):
    _login(api_client, own_org['admin'])

    resp = api_client.post('/api/classes/bulk-close/', {
        'class_ids': [own_org['gym_class'].id], 'action': 'cancel', 'comment': 'lluvia',
    }, format='json')

    assert resp.status_code == 200, resp.content
    assert resp.json()['updated_ids'] == [own_org['gym_class'].id], resp.content
    own_org['gym_class'].refresh_from_db()
    assert own_org['gym_class'].status == GymClass.Status.CANCELLED


def test_bulk_action_still_works_in_your_own_org(api_client, own_org):
    _login(api_client, own_org['admin'])

    resp = api_client.post('/api/class-templates/bulk-action/', {
        'action': 'deactivate', 'template_ids': [own_org['template'].id],
    }, format='json')

    assert resp.status_code == 200, resp.content
    assert resp.json()['updated_ids'] == [own_org['template'].id], resp.content
    own_org['template'].refresh_from_db()
    assert own_org['template'].is_active is False


def test_bulk_action_delete_reports_the_id_it_deleted(api_client, own_org):
    """`deleted_ids` se llenaba DESPUÉS del delete, y Django deja el pk en None: la
    respuesta decía `[None]` y no había forma de saber qué se borró."""
    _login(api_client, own_org['admin'])
    template_id = own_org['template'].id

    resp = api_client.post('/api/class-templates/bulk-action/', {
        'action': 'delete', 'template_ids': [template_id],
    }, format='json')

    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body['deleted_ids'] == [template_id], body
    assert not ClassTemplate.objects.filter(id=template_id).exists()
