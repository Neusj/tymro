from datetime import date, datetime, timezone as dt_timezone

import pytest

from core.models import PaymentTransaction, Plan, StudentPlan

URL = '/api/payments/transactions/'


@pytest.fixture
def org_a(make_organization):
    return make_organization('Gym A')


@pytest.fixture
def org_b(make_organization):
    return make_organization('Gym B')


def _plan(org, name='Mensual'):
    return Plan.objects.create(organization=org, name=name, plan_type='monthly',
                               total_classes=8, unlimited_classes=False, duration_days=30,
                               price=20000.0)


def _tx(org, user, **kwargs):
    defaults = dict(organization=org, user=user, amount=1000, currency='CLP', status='pending')
    defaults.update(kwargs)
    return PaymentTransaction.objects.create(**defaults)


def _set_created(tx, dt):
    # created_at es auto_now_add: hay que forzarlo con update() para bypassear.
    PaymentTransaction.objects.filter(id=tx.id).update(created_at=dt)


def test_requiere_autenticacion(api_client):
    resp = api_client.get(URL)
    assert resp.status_code == 401


@pytest.mark.parametrize('role', ['superadmin', 'manager', 'monitor', 'teacher', 'student'])
def test_roles_no_gym_admin_reciben_403(api_client, org_a, make_user, role):
    org = None if role == 'superadmin' else org_a
    user = make_user('u', organization=org, role=role)
    api_client.force_authenticate(user=user)
    resp = api_client.get(URL)
    assert resp.status_code == 403


def test_gym_admin_ve_solo_su_organizacion(api_client, org_a, org_b, make_user):
    stu_a = make_user('sa', organization=org_a, role='student')
    stu_b = make_user('sb', organization=org_b, role='student')
    _tx(org_a, stu_a)
    _tx(org_a, stu_a)
    _tx(org_b, stu_b)   # de otra org: no debe verse
    admin_a = make_user('adminA', organization=org_a, role='gym_admin')
    api_client.force_authenticate(user=admin_a)

    resp = api_client.get(URL)

    assert resp.status_code == 200
    assert resp.data['count'] == 2
    orgs = {row['id'] for row in resp.data['results']}
    assert len(orgs) == 2


def test_admin_de_b_no_ve_tx_de_a(api_client, org_a, org_b, make_user):
    stu_a = make_user('sa2', organization=org_a, role='student')
    _tx(org_a, stu_a)
    admin_b = make_user('adminB', organization=org_b, role='gym_admin')
    api_client.force_authenticate(user=admin_b)

    resp = api_client.get(URL)

    assert resp.status_code == 200
    assert resp.data['count'] == 0


def test_orden_por_fecha_desc(api_client, org_a, make_user):
    stu = make_user('s', organization=org_a, role='student')
    old = _tx(org_a, stu, status='approved')
    new = _tx(org_a, stu, status='rejected')
    _set_created(old, datetime(2026, 1, 1, tzinfo=dt_timezone.utc))
    _set_created(new, datetime(2026, 6, 1, tzinfo=dt_timezone.utc))
    admin = make_user('adm', organization=org_a, role='gym_admin')
    api_client.force_authenticate(user=admin)

    resp = api_client.get(URL)

    assert [r['id'] for r in resp.data['results']] == [str(new.id), str(old.id)]


def test_paginacion(api_client, org_a, make_user):
    stu = make_user('s3', organization=org_a, role='student')
    for _ in range(30):
        _tx(org_a, stu)
    admin = make_user('adm3', organization=org_a, role='gym_admin')
    api_client.force_authenticate(user=admin)

    page1 = api_client.get(URL, {'page_size': 10})
    assert page1.data['count'] == 30
    assert len(page1.data['results']) == 10
    assert page1.data['next'] is not None

    page3 = api_client.get(URL, {'page_size': 10, 'page': 3})
    assert len(page3.data['results']) == 10
    assert page3.data['next'] is None


def test_filtro_por_status(api_client, org_a, make_user):
    stu = make_user('s4', organization=org_a, role='student')
    _tx(org_a, stu, status='approved')
    _tx(org_a, stu, status='rejected')
    admin = make_user('adm4', organization=org_a, role='gym_admin')
    api_client.force_authenticate(user=admin)

    resp = api_client.get(URL, {'status': 'approved'})

    assert resp.data['count'] == 1
    assert resp.data['results'][0]['status'] == 'approved'


def test_status_invalido_devuelve_400(api_client, org_a, make_user):
    admin = make_user('adm5', organization=org_a, role='gym_admin')
    api_client.force_authenticate(user=admin)
    resp = api_client.get(URL, {'status': 'noexiste'})
    assert resp.status_code == 400


def test_filtro_por_rango_de_fechas(api_client, org_a, make_user):
    stu = make_user('s6', organization=org_a, role='student')
    jan = _tx(org_a, stu)
    jun = _tx(org_a, stu)
    _set_created(jan, datetime(2026, 1, 15, tzinfo=dt_timezone.utc))
    _set_created(jun, datetime(2026, 6, 15, tzinfo=dt_timezone.utc))
    admin = make_user('adm6', organization=org_a, role='gym_admin')
    api_client.force_authenticate(user=admin)

    resp = api_client.get(URL, {'date_from': '2026-06-01', 'date_to': '2026-06-30'})

    assert resp.data['count'] == 1
    assert resp.data['results'][0]['id'] == str(jun.id)


def test_fecha_invalida_devuelve_400(api_client, org_a, make_user):
    admin = make_user('adm7', organization=org_a, role='gym_admin')
    api_client.force_authenticate(user=admin)
    resp = api_client.get(URL, {'date_from': '01-06-2026'})
    assert resp.status_code == 400


def test_branch_name_trae_la_sede_y_null_cuando_no_hay(api_client, org_a, make_user):
    """`branch_name` con VALOR, no solo el camino NULL: `source='branch.name'` + `allow_null`
    es fácil de romper en las dos direcciones (sin `allow_null` la fila sin sede sale 500;
    con un `source` mal escrito la fila CON sede sale siempre vacía y nadie se entera).

    Es dónde se VENDIÓ la membresía, no a qué cuenta entró la plata: una sede sin cuenta
    propia cobra en la principal y aparece igual acá."""
    from core.models import Branch

    stu = make_user('s8', organization=org_a, role='student')
    branch = Branch.objects.create(organization=org_a, name='Sede Centro')
    with_branch = _tx(org_a, stu, branch=branch)
    without_branch = _tx(org_a, stu)          # plan global o fila vieja
    admin = make_user('adm8', organization=org_a, role='gym_admin')
    api_client.force_authenticate(user=admin)

    resp = api_client.get(URL)

    assert resp.status_code == 200
    by_id = {row['id']: row['branch_name'] for row in resp.data['results']}
    assert by_id[str(with_branch.id)] == 'Sede Centro'
    assert by_id[str(without_branch.id)] is None
