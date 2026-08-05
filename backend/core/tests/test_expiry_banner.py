"""R5 — Banner de "tu plan está por vencer" + API de la config que lo enciende.

Dos piezas, una sola fuente de verdad:

1. `show_expiry_banner` en el payload del alumno (`GET /api/plans/my-memberships/`). El
   BACKEND decide; el front solo lee el bool. Se enciende con el offset MAYOR de
   `reminder_days_before` como umbral, no por coincidencia exacta como los correos: un
   banner que apareciera el día 10, desapareciera el 9 y volviera el 3 sería un bug de cara
   al alumno.
2. `GET`/`PUT /api/organizations/{id}/expiry-notification-config/`, que hasta R5 solo se
   editaba desde el admin de Django.

Lo que estos tests blindan, en orden de importancia:

* **El umbral NO está hardcodeado.** Cambiar la config de la organización mueve el banner.
  Es la razón de ser de la feature: si el número viviera en el código, el gimnasio no lo
  podría cambiar y la config de 7.4 mentiría.
* **La validación de `clean()` corre desde DRF.** `reminder_days_before` es un `JSONField`;
  DRF no invoca `Model.clean()` solo. Sin eso la API acepta `["hola"]` o `[999]` y rompe el
  job de correos, que ya se blinda con un try/except por organización.
* **SOLO EJE FECHA.** Quedarse sin clases no enciende ni apaga el banner.
* **Multitenancy.** El alumno solo ve lo suyo, y la config se lee de la organización que
  VENDIÓ la membresía.
"""
from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from core.models import (
    OrganizationExpiryNotificationConfig,
    Plan,
    StudentPlan,
)
from core.serializers import StudentPlanSerializer

pytestmark = pytest.mark.django_db

PASSWORD = 'Passw0rd2026'
TODAY = timezone.localdate()


def _login(api_client, username):
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.get(username=username)
    host = {'HTTP_HOST': f'{user.organization.subdomain}.localhost'} if user.organization_id else {}
    token = api_client.post(
        '/api/login/', {'email': user.email, 'password': PASSWORD}, format='json', **host
    ).json()['token']
    api_client.credentials(HTTP_AUTHORIZATION=f'Token {token}')


def _plan(org, name='Pack 10', total_classes=10, unlimited=False):
    return Plan.objects.create(
        organization=org, name=name, plan_type='pack',
        total_classes=total_classes, unlimited_classes=unlimited,
        duration_days=30, price=30000,
    )


def _membership(student, plan, *, days_to_expiry=3, classes_used=0, is_active=True):
    return StudentPlan.objects.create(
        user=student, plan=plan, organization_id=plan.organization_id,
        start_date=TODAY - timedelta(days=20),
        end_date=TODAY + timedelta(days=days_to_expiry),
        total_classes=plan.total_classes, unlimited_classes=plan.unlimited_classes,
        classes_used=classes_used, final_price=30000, is_active=is_active,
    )


def _config(org, *, days=(), expired_notice=False):
    return OrganizationExpiryNotificationConfig.objects.create(
        organization=org,
        reminder_days_before=list(days),
        send_expired_notice=expired_notice,
    )


def _config_url(org):
    return f'/api/organizations/{org.id}/expiry-notification-config/'


@pytest.fixture
def gym(make_organization, make_user):
    org = make_organization('Gimnasio Uno')
    student = make_user('maria', organization=org, role='student', email='maria@gym.cl')
    return {'org': org, 'student': student, 'plan': _plan(org)}


def _my_memberships(api_client, username):
    _login(api_client, username)
    resp = api_client.get('/api/plans/my-memberships/')
    assert resp.status_code == 200, resp.content
    return resp.json()


# ---- 1. El banner se enciende dentro del umbral y no fuera ----

def test_banner_on_inside_threshold_and_off_outside(api_client, gym):
    """A 2 días con config [3] prende; a 10 días con la MISMA config no."""
    _config(gym['org'], days=[3])
    membership = _membership(gym['student'], gym['plan'], days_to_expiry=2)

    rows = _my_memberships(api_client, 'maria')

    assert [r['id'] for r in rows] == [membership.id]
    assert rows[0]['days_to_expiry'] == 2
    assert rows[0]['show_expiry_banner'] is True

    membership.end_date = TODAY + timedelta(days=10)
    membership.save(update_fields=['end_date'])

    rows = _my_memberships(api_client, 'maria')

    assert rows[0]['days_to_expiry'] == 10
    assert rows[0]['show_expiry_banner'] is False


def test_banner_stays_on_between_offsets(api_client, gym):
    """Con [10, 3] el banner NO parpadea: el umbral es el offset MAYOR.

    Es la diferencia deliberada con los correos, que sí disparan por coincidencia exacta.
    Si alguien "unificara" las dos semánticas copiando el `not in offsets` del job, este
    test cae.
    """
    _config(gym['org'], days=[10, 3])
    membership = _membership(gym['student'], gym['plan'], days_to_expiry=7)

    rows = _my_memberships(api_client, 'maria')

    assert rows[0]['days_to_expiry'] == 7  # ni 10 ni 3: entre dos offsets
    assert rows[0]['show_expiry_banner'] is True


def test_banner_off_without_config_or_with_empty_list(api_client, gym):
    """La config nace APAGADA (7.4) y puede no existir: en ambos casos, sin banner."""
    membership = _membership(gym['student'], gym['plan'], days_to_expiry=1)
    assert not OrganizationExpiryNotificationConfig.objects.filter(
        organization=gym['org']
    ).exists()

    rows = _my_memberships(api_client, 'maria')

    assert rows[0]['show_expiry_banner'] is False  # sin fila de config: no explota, no prende

    _config(gym['org'], days=[])
    rows = _my_memberships(api_client, 'maria')

    assert rows[0]['show_expiry_banner'] is False  # fila con lista vacía: idem
    assert membership.id == rows[0]['id']


# ---- 2. Multitenancy: el alumno solo ve lo suyo ----

def test_student_does_not_see_another_students_membership(
    api_client, gym, make_organization, make_user,
):
    """`my-memberships` es del actor. Sin esto, el banner de B se le pintaría a A."""
    _config(gym['org'], days=[30])
    mine = _membership(gym['student'], gym['plan'], days_to_expiry=2)

    # Compañero de la MISMA organización, también por vencer.
    other = make_user('pedro', organization=gym['org'], role='student', email='pedro@gym.cl')
    theirs = _membership(other, gym['plan'], days_to_expiry=2)

    # Y un alumno de OTRA organización, con su propia config.
    org_b = make_organization('Gimnasio Dos')
    _config(org_b, days=[30])
    student_b = make_user('ana', organization=org_b, role='student', email='ana@dos.cl')
    theirs_b = _membership(student_b, _plan(org_b), days_to_expiry=2)

    rows = _my_memberships(api_client, 'maria')

    assert [r['id'] for r in rows] == [mine.id]
    assert rows[0]['show_expiry_banner'] is True
    assert theirs.id not in {r['id'] for r in rows}
    assert theirs_b.id not in {r['id'] for r in rows}


def test_banner_reads_the_config_of_the_selling_organization(gym, make_organization):
    """La config sale de `student_plan.organization` (quien VENDIÓ), no de la del usuario.

    Se ejercita el serializer directo y no `my-memberships` a propósito: ese endpoint ya
    filtra por la misma columna, así que nunca podría mostrar el caso. Quien sí serializa
    membresías de varias organizaciones a la vez es el superadmin en
    `/api/plans/{id}/memberships/`, y ahí un alumno mudado de gimnasio recibiría el umbral
    del gimnasio nuevo sobre una membresía del viejo si el campo leyera `user.organization`.
    """
    org_b = make_organization('Gimnasio Dos')
    _config(gym['org'], days=[5])     # la que VENDIÓ: umbral corto
    _config(org_b, days=[60])         # a donde se MUDÓ el alumno: umbral generoso
    membership = _membership(gym['student'], gym['plan'], days_to_expiry=20)

    gym['student'].organization = org_b
    gym['student'].save(update_fields=['organization'])
    membership.refresh_from_db()
    assert membership.organization_id == gym['org'].id

    data = StudentPlanSerializer(membership).data

    assert data['days_to_expiry'] == 20
    assert data['show_expiry_banner'] is False  # manda el [5] de la vendedora, no el [60]


# ---- 3. Solo eje fecha ----

def test_exhausted_membership_does_not_drive_the_banner(api_client, gym):
    """Sin saldo pero con `end_date` lejos: NO hay banner. Y sin saldo y por vencer: SÍ.

    Las dos mitades juntas son la prueba de que no existe una rama por `EXHAUSTED`: el
    saldo no prende el banner ni lo apaga, solo la fecha decide.
    """
    _config(gym['org'], days=[3])
    membership = _membership(gym['student'], gym['plan'], days_to_expiry=30, classes_used=10)

    rows = _my_memberships(api_client, 'maria')

    assert rows[0]['validity_status'] == 'exhausted'   # realmente agotada
    assert rows[0]['remaining_classes'] == 0
    assert rows[0]['show_expiry_banner'] is False      # ...y sin banner: falta el eje fecha

    membership.end_date = TODAY + timedelta(days=2)
    membership.save(update_fields=['end_date'])

    rows = _my_memberships(api_client, 'maria')

    assert rows[0]['validity_status'] == 'exhausted'
    assert rows[0]['show_expiry_banner'] is True       # agotada NO apaga el banner de fecha


def test_expired_membership_gets_no_banner(api_client, gym):
    """"Por vencer" no es "venció": los días negativos quedan afuera del rango.

    El borde de abajo (`0 <=`) es el que importa: vencer HOY sigue siendo "por vencer".
    """
    _config(gym['org'], days=[10])
    expired = _membership(gym['student'], gym['plan'], days_to_expiry=-1)
    today_membership = _membership(
        gym['student'], _plan(gym['org'], name='Pack B'), days_to_expiry=0,
    )

    rows = _my_memberships(api_client, 'maria')

    # La vencida ni siquiera pasa `valid_on`, así que no aparece en el listado del alumno.
    assert [r['id'] for r in rows] == [today_membership.id]
    assert rows[0]['days_to_expiry'] == 0
    assert rows[0]['show_expiry_banner'] is True

    # Y donde SÍ se serializa (assign/memberships del admin), sale apagada.
    expired_data = StudentPlanSerializer(expired).data
    assert expired_data['days_to_expiry'] == -1
    assert expired_data['show_expiry_banner'] is False


# ---- 4. Cambiar la config mueve el umbral (no está hardcodeado) ----

def test_changing_the_config_moves_the_threshold(api_client, gym):
    _config(gym['org'], days=[3])
    _membership(gym['student'], gym['plan'], days_to_expiry=8)

    rows = _my_memberships(api_client, 'maria')
    assert rows[0]['show_expiry_banner'] is False

    config = OrganizationExpiryNotificationConfig.objects.get(organization=gym['org'])
    config.reminder_days_before = [10]
    config.save(update_fields=['reminder_days_before'])

    rows = _my_memberships(api_client, 'maria')
    assert rows[0]['show_expiry_banner'] is True


def test_threshold_moves_through_the_api_end_to_end(api_client, gym, make_user):
    """El mismo movimiento de umbral, pero pasando por el PUT del gym_admin.

    Cierra el circuito completo de R5: lo que el admin guarda por API es lo que el alumno
    ve en su banner.
    """
    _membership(gym['student'], gym['plan'], days_to_expiry=8)
    make_user('admin_a', organization=gym['org'], role='gym_admin')

    assert _my_memberships(api_client, 'maria')[0]['show_expiry_banner'] is False

    api_client.credentials()
    _login(api_client, 'admin_a')
    resp = api_client.put(
        _config_url(gym['org']), {'reminder_days_before': [10]}, format='json',
    )
    assert resp.status_code == 200, resp.content

    api_client.credentials()
    assert _my_memberships(api_client, 'maria')[0]['show_expiry_banner'] is True


# ---- 5. Endpoint de config ----

def test_get_config_autocreates_with_disabled_defaults(api_client, gym, make_user):
    make_user('admin_a', organization=gym['org'], role='gym_admin')
    _login(api_client, 'admin_a')

    resp = api_client.get(_config_url(gym['org']))

    assert resp.status_code == 200, resp.content
    assert resp.json() == {'reminder_days_before': [], 'send_expired_notice': False}
    assert OrganizationExpiryNotificationConfig.objects.filter(
        organization=gym['org']
    ).count() == 1


def test_gym_admin_put_persists_sorted_descending(api_client, gym, make_user):
    make_user('admin_a', organization=gym['org'], role='gym_admin')
    _login(api_client, 'admin_a')

    resp = api_client.put(
        _config_url(gym['org']),
        {'reminder_days_before': [3, 10, 1], 'send_expired_notice': True},
        format='json',
    )

    assert resp.status_code == 200, resp.content
    # Normalizado por `clean()`, igual que el admin de Django: descendente.
    assert resp.json()['reminder_days_before'] == [10, 3, 1]
    assert resp.json()['send_expired_notice'] is True
    config = OrganizationExpiryNotificationConfig.objects.get(organization=gym['org'])
    assert config.reminder_days_before == [10, 3, 1]
    assert config.send_expired_notice is True


def test_put_is_partial(api_client, gym, make_user):
    """PUT parcial: tocar un campo no resetea el otro."""
    _config(gym['org'], days=[7], expired_notice=True)
    make_user('admin_a', organization=gym['org'], role='gym_admin')
    _login(api_client, 'admin_a')

    resp = api_client.put(
        _config_url(gym['org']), {'send_expired_notice': False}, format='json',
    )

    assert resp.status_code == 200, resp.content
    assert resp.json() == {'reminder_days_before': [7], 'send_expired_notice': False}


@pytest.mark.parametrize('payload, label', [
    ([0], 'cero: fuera del rango 1..365'),
    ([-1], 'negativo'),
    ([OrganizationExpiryNotificationConfig.MAX_DAYS_BEFORE + 1], 'sobre el tope de días'),
    (list(range(1, OrganizationExpiryNotificationConfig.MAX_REMINDERS + 2)), 'once avisos'),
    ([5, 5], 'duplicados'),
    (['x'], 'string'),
    ([True], 'bool (subclase de int, no es "1 día")'),
    ([3.5], 'float'),
    ('hola', 'ni siquiera es una lista'),
    ({'dias': [3]}, 'dict'),
])
def test_invalid_reminder_days_are_rejected(payload, label, api_client, gym, make_user):
    """La validación del modelo TIENE que correr desde DRF.

    `reminder_days_before` es un `JSONField`: DRF no invoca `Model.clean()` por su cuenta,
    así que sin el `validate_reminder_days_before` del serializer cada uno de estos casos
    se persiste y rompe el job de correos.
    """
    make_user('admin_a', organization=gym['org'], role='gym_admin')
    _login(api_client, 'admin_a')

    resp = api_client.put(
        _config_url(gym['org']), {'reminder_days_before': payload}, format='json',
    )

    assert resp.status_code == 400, f'{label}: {resp.content}'
    assert 'reminder_days_before' in resp.json(), label
    # Y no quedó escrito nada.
    assert OrganizationExpiryNotificationConfig.objects.get(
        organization=gym['org']
    ).reminder_days_before == []


def test_max_reminders_at_the_cap_is_accepted(api_client, gym, make_user):
    """El tope se rechaza, el borde no: 10 avisos entran."""
    make_user('admin_a', organization=gym['org'], role='gym_admin')
    _login(api_client, 'admin_a')
    days = list(range(1, OrganizationExpiryNotificationConfig.MAX_REMINDERS + 1))

    resp = api_client.put(
        _config_url(gym['org']), {'reminder_days_before': days}, format='json',
    )

    assert resp.status_code == 200, resp.content
    assert resp.json()['reminder_days_before'] == sorted(days, reverse=True)


@pytest.mark.parametrize('role', ['student', 'teacher', 'manager', 'monitor'])
def test_non_org_admin_roles_are_rejected(role, api_client, gym, make_user):
    """`_can_manage_org_resource`, no `_can_manage_operational_resource`: el manager NO entra.

    Si alguien cambiara el check al operativo, el manager pasaría a poder mandar correos a
    todos los alumnos de la organización. Este test es esa barrera.
    """
    make_user('member', organization=gym['org'], role=role, email=f'{role}@gym.cl')
    _login(api_client, 'member')
    url = _config_url(gym['org'])

    resp_get = api_client.get(url)
    resp_put = api_client.put(url, {'reminder_days_before': [5]}, format='json')

    assert resp_get.status_code == 403, resp_get.content
    assert resp_put.status_code == 403, resp_put.content
    assert not OrganizationExpiryNotificationConfig.objects.filter(
        organization=gym['org']
    ).exists()


def test_gym_admin_cannot_touch_another_orgs_config(
    api_client, gym, make_organization, make_user,
):
    org_b = make_organization('Gimnasio Dos')
    make_user('admin_a', organization=gym['org'], role='gym_admin')
    _login(api_client, 'admin_a')

    resp_get = api_client.get(_config_url(org_b))
    resp_put = api_client.put(
        _config_url(org_b), {'reminder_days_before': [5]}, format='json',
    )

    assert resp_get.status_code == 403, resp_get.content
    assert resp_put.status_code == 403, resp_put.content
    # El rechazo ocurre ANTES del get_or_create: no se crea config para la org ajena.
    assert not OrganizationExpiryNotificationConfig.objects.filter(
        organization=org_b
    ).exists()


def test_superadmin_can_manage_any_org(api_client, gym, make_user):
    make_user('root', organization=None, role='superadmin')
    _login(api_client, 'root')

    resp = api_client.put(
        _config_url(gym['org']), {'reminder_days_before': [15]}, format='json',
    )

    assert resp.status_code == 200, resp.content
    assert OrganizationExpiryNotificationConfig.objects.get(
        organization=gym['org']
    ).reminder_days_before == [15]


def test_unknown_organization_is_404_not_403(api_client, gym, make_user):
    """404 vs 403: la org inexistente se distingue de la ajena, igual que el molde."""
    make_user('root', organization=None, role='superadmin')
    _login(api_client, 'root')

    resp = api_client.get('/api/organizations/999999/expiry-notification-config/')

    assert resp.status_code == 404, resp.content


def test_unauthenticated_cannot_access_config(api_client, gym):
    resp = api_client.get(_config_url(gym['org']))

    assert resp.status_code == 401, resp.content


# ---- 6. Sin N+1 ----

def test_banner_does_not_query_the_config_once_per_membership(api_client, gym):
    """El serializer corre sobre una LISTA: la config se resuelve UNA sola vez.

    Se compara el conteo de queries con 1 membresía contra el de 4: tiene que ser el MISMO.
    Un `.first()` por fila haría que la diferencia fuera exactamente 3.
    """
    _config(gym['org'], days=[10])
    _login(api_client, 'maria')
    _membership(gym['student'], gym['plan'], days_to_expiry=5)

    with CaptureQueriesContext(connection) as captured:
        resp = api_client.get('/api/plans/my-memberships/')
        assert resp.status_code == 200, resp.content
    baseline = len(captured)

    for i in range(3):
        _membership(gym['student'], _plan(gym['org'], name=f'Pack {i}'), days_to_expiry=5)

    with CaptureQueriesContext(connection) as captured:
        resp = api_client.get('/api/plans/my-memberships/')
        assert resp.status_code == 200, resp.content

    assert len(resp.json()) == 4
    assert all(row['show_expiry_banner'] is True for row in resp.json())
    assert len(captured) == baseline, [q['sql'] for q in captured.captured_queries]
    # Y explícito, por si el conteo total alguna vez se compensa con otro cambio: la tabla
    # de la config se toca UNA vez para las cuatro membresías.
    config_queries = [
        q['sql'] for q in captured.captured_queries
        if 'core_organizationexpirynotificationconfig' in q['sql'].lower()
    ]
    assert len(config_queries) == 1, config_queries
