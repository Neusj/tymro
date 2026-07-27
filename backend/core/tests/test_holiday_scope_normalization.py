"""La normalización de `Holiday.clean()` tiene que PERSISTIR, no quedarse en el aire.

`HolidaySerializer.validate` construye un `Holiday(...)` temporal, le llama `clean()` y
devuelve `attrs` **sin** las mutaciones. `clean()` es quien normaliza el alcance —global ⇒
sin organización ni sucursal; por organización ⇒ sin sucursal— y quien valida branch↔org,
pero ese último check solo corre en la rama `scope=BRANCH`. Como `save()` usa
`validated_data`, la normalización se perdía y quedaban dos filas imposibles:

* `scope=global` **con** `organization`: `HolidayViewSet.get_queryset` expone
  `Q(scope=GLOBAL)` SIN filtro de organización, así que el `organization_name` de ese
  tenant se serializaba a TODAS las organizaciones.
* `scope=organization` con una `branch` de OTRA org: FK cross-tenant escrita. Y como
  `Holiday.branch` es CASCADE y `BranchViewSet._cascade_blocker` consulta
  `branch.holidays.exists()`, ese feriado ajeno además le bloquea a la otra organización
  el borrado de su propia sucursal, con una causa que no puede ver ni eliminar.

El disparador es el superadmin (a los org-admin ya los frena el propio serializer), pero
es rol de plataforma, no una excepción a la regla #1: escribir un `branch_id` de otra
organización no puede pasar por ninguna puerta.
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from core.models import Branch, Holiday

pytestmark = pytest.mark.django_db

PASSWORD = 'Passw0rd2026'


def _login(api_client, user):
    host = {'HTTP_HOST': f'{user.organization.subdomain}.localhost'} if user.organization_id else {}
    token = api_client.post(
        '/api/login/', {'email': user.email, 'password': PASSWORD}, format='json', **host
    ).json()['token']
    api_client.credentials(HTTP_AUTHORIZATION=f'Token {token}')


@pytest.fixture
def setup(make_organization, make_user):
    org_a = make_organization()
    org_b = make_organization()
    return {
        'a': org_a,
        'b': org_b,
        'branch_a': Branch.objects.create(organization=org_a, name='Sede A'),
        'branch_b': Branch.objects.create(organization=org_b, name='Sede B privada'),
        'root': make_user('root', organization=None, role='superadmin', email='root@tymro.cl'),
        'admin_a': make_user('admin_a', organization=org_a, role='gym_admin'),
    }


def _date(days=15):
    return str(timezone.localdate() + timedelta(days=days))


def test_global_holiday_is_stored_without_an_organization(api_client, setup):
    """Un feriado global no puede quedarse con la organización del payload: el listado
    lo muestra a todos los tenants y filtraría el nombre de esa organización."""
    _login(api_client, setup['root'])

    resp = api_client.post('/api/holidays/', {
        'name': 'Feriado nacional', 'date': _date(), 'scope': 'global',
        'organization': setup['b'].id,
    }, format='json')

    assert resp.status_code in {201, 400}, resp.content
    if resp.status_code == 201:
        holiday = Holiday.objects.get(id=resp.json()['id'])
        assert holiday.organization_id is None, (
            'un feriado global quedó atado a una organización y se filtra a todas'
        )
        assert holiday.branch_id is None


def test_a_global_holiday_does_not_leak_another_orgs_name(api_client, setup):
    """La contracara observable: el gym_admin de A no puede ver el nombre de la org B
    en su propio listado de feriados."""
    _login(api_client, setup['root'])
    api_client.post('/api/holidays/', {
        'name': 'Feriado nacional', 'date': _date(), 'scope': 'global',
        'organization': setup['b'].id,
    }, format='json')

    api_client.credentials()
    _login(api_client, setup['admin_a'])
    listing = api_client.get('/api/holidays/')

    assert listing.status_code == 200, listing.content
    rows = listing.json()
    rows = rows['results'] if isinstance(rows, dict) else rows
    leaked = [
        row for row in rows
        if row.get('organization_name') and row['organization_name'] != setup['a'].name
    ]
    assert not leaked, f'el listado de la org A expone otra organización: {leaked}'


def test_organization_scoped_holiday_drops_a_foreign_branch(api_client, setup):
    """`scope=organization` con una sucursal ajena: la rama de branch↔org de `clean()`
    no corre para este scope, así que la FK cross-tenant entraba sin más."""
    _login(api_client, setup['root'])

    resp = api_client.post('/api/holidays/', {
        'name': 'Aniversario', 'date': _date(), 'scope': 'organization',
        'organization': setup['a'].id, 'branch': setup['branch_b'].id,
    }, format='json')

    assert resp.status_code in {201, 400}, resp.content
    if resp.status_code == 201:
        holiday = Holiday.objects.get(id=resp.json()['id'])
        assert holiday.branch_id is None, (
            'un feriado de la org A quedó colgado de una sucursal de la org B'
        )
    assert not Holiday.objects.filter(branch=setup['branch_b']).exclude(
        organization=setup['b']
    ).exists()


def test_branch_scoped_holiday_still_rejects_a_foreign_branch(api_client, setup):
    """Anclaje: la rama que sí validaba sigue validando."""
    _login(api_client, setup['root'])

    resp = api_client.post('/api/holidays/', {
        'name': 'Aniversario', 'date': _date(), 'scope': 'branch',
        'organization': setup['a'].id, 'branch': setup['branch_b'].id,
    }, format='json')

    assert resp.status_code == 400, resp.content
    assert 'branch' in resp.json(), resp.content


def test_a_foreign_holiday_never_blocks_deleting_your_own_branch(api_client, setup):
    """El efecto colateral: si un feriado de otra org se cuelga de tu sucursal,
    `_cascade_blocker` te impide borrarla por una causa que no podés ver."""
    _login(api_client, setup['root'])
    api_client.post('/api/holidays/', {
        'name': 'Aniversario', 'date': _date(), 'scope': 'organization',
        'organization': setup['a'].id, 'branch': setup['branch_b'].id,
    }, format='json')

    resp = api_client.delete(f'/api/branches/{setup["branch_b"].id}/')

    assert resp.status_code == 204, resp.content


def test_legit_holidays_of_each_scope_still_work(api_client, setup):
    """Regresión: los tres alcances legítimos siguen creándose."""
    _login(api_client, setup['root'])

    glob = api_client.post('/api/holidays/', {
        'name': 'Nacional', 'date': _date(1), 'scope': 'global',
    }, format='json')
    org = api_client.post('/api/holidays/', {
        'name': 'Aniversario org', 'date': _date(2), 'scope': 'organization',
        'organization': setup['a'].id,
    }, format='json')
    branch = api_client.post('/api/holidays/', {
        'name': 'Aniversario sede', 'date': _date(3), 'scope': 'branch',
        'organization': setup['a'].id, 'branch': setup['branch_a'].id,
    }, format='json')

    assert glob.status_code == 201, glob.content
    assert org.status_code == 201, org.content
    assert branch.status_code == 201, branch.content
    assert Holiday.objects.get(id=branch.json()['id']).branch_id == setup['branch_a'].id
    assert Holiday.objects.get(id=org.json()['id']).organization_id == setup['a'].id


def test_gym_admin_branch_holiday_of_its_own_org_still_works(api_client, setup):
    """Regresión del camino del gym_admin, que es el que usa la UI."""
    _login(api_client, setup['admin_a'])

    resp = api_client.post('/api/holidays/', {
        'name': 'Aniversario sede', 'date': _date(4), 'scope': 'branch',
        'branch': setup['branch_a'].id,
    }, format='json')

    assert resp.status_code == 201, resp.content
    holiday = Holiday.objects.get(id=resp.json()['id'])
    assert holiday.organization_id == setup['a'].id
    assert holiday.branch_id == setup['branch_a'].id
