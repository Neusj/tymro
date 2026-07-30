"""`GET /api/plans/` no puede exponerle al alumno planes que no están a la venta.

`Plan` tiene dos banderas de visibilidad —`is_public` (visible para alumnos) e
`is_active`— y el filtro vivía SOLO en el frontend (`StudentBuyPlanPage.jsx`, en JS).
El backend devolvía la lista completa a cualquier alumno autenticado: precios internos,
convenios, planes de prueba y planes ya retirados, todo a un `curl` de distancia.

Viola la regla del proyecto (CLAUDE.md): el control de acceso del frontend es cosmético,
toda restricción tiene que tener su check equivalente en el backend. El checkout ya
validaba (`views_payments.py` filtra `is_active=True, is_public=True`), así que la COMPRA
estaba cerrada; lo que estaba abierto era la LECTURA.

`gym_admin`/`superadmin` siguen viendo todo: lo necesitan para administrar. `manager`
recibe 403 en todo lo financiero (`FinancialResourcePermission`) y nunca llega acá.
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from core.models import Plan, StudentPlan

pytestmark = pytest.mark.django_db

PASSWORD = 'Passw0rd2026'


def _login(api_client, username):
    from django.contrib.auth import get_user_model
    user = get_user_model().objects.get(username=username)
    host = {'HTTP_HOST': f'{user.organization.subdomain}.localhost'} if user.organization_id else {}
    token = api_client.post(
        '/api/login/', {'email': user.email, 'password': PASSWORD}, format='json', **host
    ).json()['token']
    api_client.credentials(HTTP_AUTHORIZATION=f'Token {token}')


def _ids(payload):
    rows = payload['results'] if isinstance(payload, dict) and 'results' in payload else payload
    return {row['id'] for row in rows}


def _plan(org, name, plan_type='pack', **flags):
    return Plan.objects.create(
        organization=org, name=name, plan_type=plan_type, total_classes=10,
        duration_days=30, price=30000, **flags,
    )


@pytest.fixture
def setup(make_organization, make_user):
    org = make_organization()
    admin = make_user('admin', organization=org, role='gym_admin')
    student = make_user('alu', organization=org, role='student', email='alu@gym.cl')
    return {
        'org': org,
        'admin': admin,
        'student': student,
        'public': _plan(org, 'A la venta'),
        'hidden': _plan(org, 'Convenio interno', is_public=False),
        'retired': _plan(org, 'Retirado', is_active=False),
        'hidden_and_retired': _plan(org, 'Viejo interno', is_public=False, is_active=False),
        'trial': _plan(org, 'Clase de prueba', plan_type='trial'),
        'giftcard': _plan(org, 'Giftcard', plan_type='giftcard'),
    }


# --- A. El alumno solo ve lo que está a la venta ---------------------------------


def test_student_does_not_see_non_public_plans(api_client, setup):
    _login(api_client, 'alu')

    resp = api_client.get('/api/plans/')

    assert resp.status_code == 200, resp.content
    assert setup['hidden'].id not in _ids(resp.json()), \
        'un plan con is_public=False no puede llegarle al alumno'


def test_student_does_not_see_inactive_plans(api_client, setup):
    _login(api_client, 'alu')

    resp = api_client.get('/api/plans/')

    assert setup['retired'].id not in _ids(resp.json()), \
        'un plan retirado (is_active=False) no puede llegarle al alumno'


def test_student_sees_exactly_the_plans_on_sale(api_client, setup):
    _login(api_client, 'alu')

    resp = api_client.get('/api/plans/')

    assert _ids(resp.json()) == {setup['public'].id}


def test_student_cannot_retrieve_a_hidden_plan_by_id(api_client, setup):
    """El listado filtrado no sirve de nada si el detalle sigue abierto: el id es
    adivinable (autoincremental)."""
    _login(api_client, 'alu')

    hidden = api_client.get(f'/api/plans/{setup["hidden"].id}/')
    retired = api_client.get(f'/api/plans/{setup["retired"].id}/')

    assert hidden.status_code == 404, hidden.content
    assert retired.status_code == 404, retired.content


def test_student_still_sees_the_plan_on_sale_in_detail(api_client, setup):
    """Contra-prueba: el filtro no puede cerrarle al alumno lo que sí puede comprar."""
    _login(api_client, 'alu')

    resp = api_client.get(f'/api/plans/{setup["public"].id}/')

    assert resp.status_code == 200, resp.content
    assert resp.json()['id'] == setup['public'].id


@pytest.mark.parametrize('plan_key', ['trial', 'giftcard'])
def test_student_does_not_see_plans_that_cannot_be_bought_online(api_client, setup, plan_key):
    """La tercera condición del filtro del front: `!['trial','giftcard'].includes(plan_type)`.
    Estos planes llegan con `is_public=True` (el default del modelo), así que replicar solo
    `is_public`/`is_active` los dejaba en la vitrina con su precio.

    Lo que ya estaba cerrado es la COMPRA: `create_checkout` los rechaza
    ('Este plan no se puede comprar en línea'). Acá se cierra la LECTURA, para que el
    catálogo del backend diga lo mismo que el del frontend."""
    _login(api_client, 'alu')

    listing = api_client.get('/api/plans/')
    detail = api_client.get(f'/api/plans/{setup[plan_key].id}/')

    assert setup[plan_key].id not in _ids(listing.json()), \
        f'un plan {plan_key} no se puede comprar en línea: no va en la vitrina'
    assert detail.status_code == 404, detail.content


def test_gym_admin_still_sees_trial_and_giftcard_plans(api_client, setup):
    """Contra-prueba: son planes reales que el gimnasio asigna a mano y administra."""
    _login(api_client, 'admin')

    ids = _ids(api_client.get('/api/plans/').json())

    assert setup['trial'].id in ids
    assert setup['giftcard'].id in ids


# --- B. La visibilidad no puede romper el historial del alumno -------------------


def test_student_keeps_seeing_a_membership_bought_on_a_now_hidden_plan(api_client, setup):
    """Un plan se retira DESPUÉS de venderse. La membresía es historia del alumno y
    tiene que seguir visible: `my-memberships` va por `StudentPlan`, no por el listado."""
    today = timezone.localdate()
    StudentPlan.objects.create(
        user=setup['student'], plan=setup['retired'], start_date=today,
        organization_id=setup['retired'].organization_id,
        end_date=today + timedelta(days=30), total_classes=10, final_price=30000,
    )
    _login(api_client, 'alu')

    resp = api_client.get('/api/plans/my-memberships/')

    assert resp.status_code == 200, resp.content
    assert [row['plan'] for row in resp.json()] == [setup['retired'].id], (
        'el alumno perdió de vista la membresía que pagó porque el plan se retiró'
    )


@pytest.mark.parametrize('plan_key', ['trial', 'giftcard'])
def test_a_membership_assigned_by_hand_stays_visible_to_its_owner(api_client, setup, plan_key):
    """Los planes trial y giftcard salen de la vitrina pero se asignan a mano: el alumno que
    tiene uno TIENE que seguir viéndolo. Es la condición nueva del filtro, y `my-plan` /
    `my-memberships` no pasan por `get_queryset()` justamente para eso."""
    today = timezone.localdate()
    StudentPlan.objects.create(
        user=setup['student'], plan=setup[plan_key], start_date=today,
        organization_id=setup[plan_key].organization_id,
        end_date=today + timedelta(days=30), total_classes=10, final_price=30000,
    )
    _login(api_client, 'alu')

    my_plan = api_client.get('/api/plans/my-plan/')
    my_memberships = api_client.get('/api/plans/my-memberships/')

    assert my_plan.status_code == 200, my_plan.content
    assert my_plan.json()['plan'] == setup[plan_key].id
    assert [row['plan'] for row in my_memberships.json()] == [setup[plan_key].id]


def test_my_plan_still_resolves_when_the_plan_was_retired(api_client, setup):
    """`my-plan` no pasa por `get_queryset()` —va por `StudentPlan`— y eso es lo correcto:
    el alumno tiene que poder ver el plan con el que reserva incluso si ya se retiró del
    catálogo."""
    today = timezone.localdate()
    StudentPlan.objects.create(
        user=setup['student'], plan=setup['retired'], start_date=today,
        organization_id=setup['retired'].organization_id,
        end_date=today + timedelta(days=30), total_classes=10, final_price=30000,
    )
    _login(api_client, 'alu')

    resp = api_client.get('/api/plans/my-plan/')

    assert resp.status_code == 200, resp.content
    assert resp.json()['plan'] == setup['retired'].id


# --- C. Quien administra sigue viendo todo --------------------------------------


def test_gym_admin_still_sees_hidden_and_inactive_plans(api_client, setup):
    _login(api_client, 'admin')

    resp = api_client.get('/api/plans/')

    assert resp.status_code == 200, resp.content
    ids = _ids(resp.json())
    for key in ('public', 'hidden', 'retired', 'hidden_and_retired'):
        assert setup[key].id in ids, f'gym_admin debe seguir viendo {key} para administrarlo'


def test_gym_admin_still_retrieves_a_hidden_plan(api_client, setup):
    _login(api_client, 'admin')

    resp = api_client.get(f'/api/plans/{setup["hidden"].id}/')

    assert resp.status_code == 200, resp.content


def test_superadmin_still_sees_hidden_plans(api_client, setup, make_user):
    make_user('root', role='superadmin', organization=None)
    _login(api_client, 'root')

    resp = api_client.get('/api/plans/')

    assert setup['hidden'].id in _ids(resp.json())


# --- D. El scoping por organización sigue intacto -------------------------------


def test_a_non_numeric_organization_filter_is_a_400_not_a_500(api_client, setup, make_user):
    """`?organization_id=` (solo superadmin) iba crudo al `filter()`: un valor no numérico
    levantaba `ValueError` fuera del manejo de DRF y respondía 500. Mismo criterio que
    `_as_id_list` con los ids del body."""
    make_user('root', role='superadmin', organization=None)
    _login(api_client, 'root')

    resp = api_client.get('/api/plans/?organization_id=abc')

    assert resp.status_code == 400, resp.content


def test_the_organization_filter_only_narrows_never_widens(api_client, setup, make_organization):
    """Contra-prueba del param: un `gym_admin` que lo pase no alcanza la otra org."""
    other_org = make_organization(name='Otra Org')
    foreign = _plan(other_org, 'Ajeno')
    _login(api_client, 'admin')

    resp = api_client.get(f'/api/plans/?organization_id={other_org.id}')

    assert resp.status_code == 200, resp.content
    assert foreign.id not in _ids(resp.json())


def test_student_never_sees_a_public_plan_from_another_org(
    api_client, setup, make_organization,
):
    """El filtro de visibilidad no puede reemplazar al de organización: un plan público
    de OTRO gimnasio sigue siendo invisible."""
    other_org = make_organization(name='Otra Org')
    foreign = _plan(other_org, 'Público ajeno')
    _login(api_client, 'alu')

    listing = api_client.get('/api/plans/')
    detail = api_client.get(f'/api/plans/{foreign.id}/')

    assert foreign.id not in _ids(listing.json())
    assert detail.status_code == 404, detail.content
