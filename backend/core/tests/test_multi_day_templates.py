"""Alta de series recurrentes en VARIOS dias de una sola vez (`weekdays`).

Hasta ahora `POST /api/class-templates/` creaba UNA plantilla por request (`weekday`
singular): armar "lunes, miercoles y viernes a las 10" eran tres altas a mano, con el
riesgo de que se colara un duplicado si el admin reintentaba. Este archivo fija el
contrato del param OPCIONAL `weekdays` (lista de enteros 0=lunes..6=domingo):

* Sin `weekdays` -> camino singular historico, sin un solo cambio de comportamiento
  (respuesta = la plantilla serializada, 201). Cubierto por
  `test_camino_legacy_singular_*` como red de regresion.
* Con `weekdays` -> lote: `{"created": [...], "skipped": [{"weekday": d,
  "existing_id": id}]}`, 201 si creo al menos una y 200 si TODO era duplicado
  (el doble submit es idempotente, no un error).

Dos invariantes que se prueban explicitamente porque son las que duelen:

1. **El dedup es org-scoped** (`test_dedup_no_cruza_organizaciones`): una plantilla
   identica de OTRA organizacion no puede producir `skipped` ni filtrar su `existing_id`
   —seria un oraculo cross-tenant: barriendo horarios se reconstruye la agenda ajena—.
2. **Ninguna clase cae en el pasado** (`test_ningun_dictado_queda_en_el_pasado_...`): con
   `start_date` inferido = hoy, un lote L/M/V dado de alta un MARTES no puede materializar
   el lunes que ya paso. La primera instancia de toda la serie es el miercoles.

Freeze de fechas: NO hay freezegun/time-machine en el venv (ver
`test_advance_class_windows.py:11`), asi que "hoy" se mueve parcheando
`django.utils.timezone.localdate` por monkeypatch. Alcanza porque tanto el serializer
(`ClassTemplateSerializer.validate`, que infiere `start_date`) como el generador
(`generate_instances_for_template_range` / `materialization_window_cap`) lo leen como
atributo de modulo en cada llamada. `timezone.now()` queda real a proposito: el martes
elegido es siempre >= hoy real, asi que las clases generadas caen en el futuro real y no
hay estados de clase incoherentes.
"""
from datetime import time, timedelta

import pytest
from django.utils import timezone

from core.models import (
    Branch,
    ClassTemplate,
    ClassType,
    Discipline,
    GymClass,
    Holiday,
)

pytestmark = pytest.mark.django_db

PASSWORD = 'Passw0rd2026'
URL = '/api/class-templates/'


def _login(api_client, user):
    """Calco de test_rolling_window.py:65-71 (login por email + subdominio de la org)."""
    host = {'HTTP_HOST': f'{user.organization.subdomain}.localhost'} if user.organization_id else {}
    token = api_client.post(
        '/api/login/', {'email': user.email, 'password': PASSWORD}, format='json', **host
    ).json()['token']
    api_client.credentials(HTTP_AUTHORIZATION=f'Token {token}')


def _org_setup(make_organization, make_user, tag):
    """Organizacion autosuficiente: admin, profe, alumno, sede, tipo y disciplina propios."""
    org = make_organization()
    return {
        'org': org,
        'admin': make_user(f'admin-{tag}', organization=org, role='gym_admin'),
        'teacher': make_user(f'teach-{tag}', organization=org, role='teacher'),
        'student': make_user(f'alu-{tag}', organization=org, role='student'),
        'branch': Branch.objects.create(organization=org, name=f'Sede {tag}'),
        'class_type': ClassType.objects.create(organization=org, name=f'Tipo {tag}'),
        'discipline': Discipline.objects.create(organization=org, name=f'Disciplina {tag}'),
    }


@pytest.fixture
def setup(make_organization, make_user):
    return _org_setup(make_organization, make_user, 'mdt')


@pytest.fixture
def other_org(make_organization, make_user):
    """Segunda organizacion, con su propio juego de recursos analogos."""
    return _org_setup(make_organization, make_user, 'ajena')


def _payload(setup, **overrides):
    data = {
        'name': 'Serie multi',
        'branch': setup['branch'].id,
        'teacher': setup['teacher'].id,
        'class_type': setup['class_type'].id,
        'discipline': setup['discipline'].id,
        'start_time': '10:00',
        'end_time': '11:00',
        'capacity': 12,
    }
    data.update(overrides)
    return data


def _instance_dates(template):
    return sorted(
        timezone.localtime(instance.start_datetime).date()
        for instance in GymClass.objects.filter(class_template=template)
    )


def _next_tuesday():
    """El proximo martes (o hoy, si hoy ya es martes): siempre >= hoy real."""
    today = timezone.localdate()
    return today + timedelta(days=(1 - today.weekday()) % 7)


# ==========================================================================================
# A. Camino nuevo: lote multi-dia.
# ==========================================================================================


def test_lote_lunes_miercoles_viernes_sin_fechas_crea_las_tres_series(api_client, setup):
    """Caso central: `weekdays=[0,2,4]` sin `start_date` ni `end_date`. Tres plantillas de
    SU organizacion, cada una con clases ya materializadas, arrancando hoy y sin fin
    (`end_date=None`, la serie abierta que la ventana rodante va extendiendo)."""
    _login(api_client, setup['admin'])
    today = timezone.localdate()

    resp = api_client.post(URL, _payload(setup, weekdays=[0, 2, 4]), format='json')

    assert resp.status_code == 201, resp.content
    body = resp.json()
    assert body['skipped'] == []
    assert [item['weekday'] for item in body['created']] == [0, 2, 4]
    assert {item['start_date'] for item in body['created']} == {str(today)}
    assert {item['end_date'] for item in body['created']} == {None}
    assert {item['organization'] for item in body['created']} == {setup['org'].id}

    templates = ClassTemplate.objects.filter(organization=setup['org']).order_by('weekday')
    assert [template.weekday for template in templates] == [0, 2, 4]
    for template in templates:
        assert template.start_date == today
        assert template.end_date is None
        assert template.created_by_id == setup['admin'].id
        assert template.instances.count() > 0, f'la serie del weekday {template.weekday} no materializo nada'


def test_lote_de_un_solo_dia_funciona_igual(api_client, setup):
    """`weekdays=[2]` (un solo dia) no es un caso especial: misma forma de respuesta de
    lote, una sola plantilla."""
    _login(api_client, setup['admin'])

    resp = api_client.post(URL, _payload(setup, weekdays=[2]), format='json')

    assert resp.status_code == 201, resp.content
    body = resp.json()
    assert body['skipped'] == []
    assert len(body['created']) == 1
    assert body['created'][0]['weekday'] == 2
    assert ClassTemplate.objects.filter(organization=setup['org']).count() == 1


def test_weekday_singular_se_ignora_cuando_llega_weekdays(api_client, setup):
    """El contrato dice que `weekdays` MANDA: si vienen los dos, el singular se descarta
    (no se crea una cuarta serie fantasma con ese dia)."""
    _login(api_client, setup['admin'])

    resp = api_client.post(URL, _payload(setup, weekday=6, weekdays=[0, 2]), format='json')

    assert resp.status_code == 201, resp.content
    assert [item['weekday'] for item in resp.json()['created']] == [0, 2]
    assert not ClassTemplate.objects.filter(organization=setup['org'], weekday=6).exists()


def test_doble_submit_identico_es_idempotente(api_client, setup):
    """Reintento (doble click, request reenviado): el segundo POST no crea nada, no
    duplica y NO es un error -> 200 con `created=[]` y los tres dias en `skipped`
    apuntando a las plantillas que ya existian."""
    _login(api_client, setup['admin'])
    payload = _payload(setup, weekdays=[0, 2, 4])

    first = api_client.post(URL, payload, format='json')
    assert first.status_code == 201, first.content
    created_ids = {item['weekday']: item['id'] for item in first.json()['created']}
    instances_before = GymClass.objects.count()

    second = api_client.post(URL, payload, format='json')

    assert second.status_code == 200, second.content
    body = second.json()
    assert body['created'] == []
    assert body['skipped'] == [
        {'weekday': 0, 'existing_id': created_ids[0]},
        {'weekday': 2, 'existing_id': created_ids[2]},
        {'weekday': 4, 'existing_id': created_ids[4]},
    ]
    assert ClassTemplate.objects.filter(organization=setup['org']).count() == 3
    assert GymClass.objects.count() == instances_before, 'el reintento no puede materializar clases de nuevo'


def test_ningun_dictado_queda_en_el_pasado_dando_de_alta_un_martes(api_client, setup, monkeypatch):
    """Alta de un lote L/M/V un MARTES: el lunes de ESTA semana ya paso y no puede
    materializarse. Con `start_date` inferido = hoy, `effective_from = max(start_date, hoy)`
    garantiza que la primera instancia de TODA la serie sea el miercoles (manana)."""
    _login(api_client, setup['admin'])  # el login corre con el reloj real, antes del freeze
    # Calendario deterministico: sin festivos, ninguna ocurrencia se saltea (la BD de test
    # no siembra festivos, esto es defensa explicita por si alguna vez los siembra).
    Holiday.objects.all().delete()

    tuesday = _next_tuesday()
    monkeypatch.setattr(timezone, 'localdate', lambda *args, **kwargs: tuesday)

    resp = api_client.post(URL, _payload(setup, weekdays=[0, 2, 4]), format='json')

    assert resp.status_code == 201, resp.content
    assert {item['start_date'] for item in resp.json()['created']} == {str(tuesday)}

    dates = sorted(
        timezone.localtime(instance.start_datetime).date()
        for instance in GymClass.objects.all()
    )
    assert dates, 'el lote tiene que haber materializado algo'
    assert all(day >= tuesday for day in dates), f'hay clases anteriores a hoy: {dates[:3]}'
    assert dates[0] == tuesday + timedelta(days=1), 'la primera clase de la serie tiene que ser el miercoles'
    assert dates[0].weekday() == 2
    # Y el lunes de la serie es el de la semana QUE VIENE, no el que ya paso.
    monday_template = ClassTemplate.objects.get(organization=setup['org'], weekday=0)
    assert _instance_dates(monday_template)[0] == tuesday + timedelta(days=6)


def test_patch_a_una_serie_del_lote_no_toca_a_las_hermanas(api_client, setup):
    """Las tres plantillas del lote son independientes: editar una (capacidad) no arrastra
    a las otras dos ni a las clases que ya generaron."""
    _login(api_client, setup['admin'])
    created = api_client.post(URL, _payload(setup, weekdays=[0, 2, 4]), format='json').json()['created']
    target_id = created[0]['id']
    siblings = [item['id'] for item in created[1:]]
    instances_before = {
        template_id: sorted(
            GymClass.objects.filter(class_template_id=template_id).values_list('id', flat=True)
        )
        for template_id in siblings
    }

    resp = api_client.patch(f'{URL}{target_id}/', {'capacity': 30}, format='json')

    assert resp.status_code == 200, resp.content
    assert ClassTemplate.objects.get(pk=target_id).capacity == 30
    for template_id in siblings:
        sibling = ClassTemplate.objects.get(pk=template_id)
        assert sibling.capacity == 12, 'la edicion se filtro a una serie hermana'
        instances = GymClass.objects.filter(class_template=sibling)
        assert sorted(instances.values_list('id', flat=True)) == instances_before[template_id]
        assert set(instances.values_list('capacity', flat=True)) == {12}


def test_dedup_no_cruza_organizaciones(api_client, setup, other_org):
    """Una plantilla IDENTICA en horario/dia de otra organizacion no es un duplicado: el
    actor la crea igual, sin `skipped`, y el id ajeno no aparece en ninguna parte de la
    respuesta (oraculo cross-tenant)."""
    foreign = ClassTemplate.objects.create(
        organization=other_org['org'],
        branch=other_org['branch'],
        teacher=other_org['teacher'],
        class_type=other_org['class_type'],
        discipline=other_org['discipline'],
        name='Serie ajena',
        weekday=2,
        start_time=time(10, 0),
        end_time=time(11, 0),
        capacity=12,
        start_date=timezone.localdate(),
    )
    _login(api_client, setup['admin'])

    resp = api_client.post(URL, _payload(setup, weekdays=[2]), format='json')

    assert resp.status_code == 201, resp.content
    body = resp.json()
    assert body['skipped'] == [], 'una serie de otra org no puede saltear la creacion propia'
    assert len(body['created']) == 1
    assert body['created'][0]['organization'] == setup['org'].id
    # Ni la existencia ni el id de la serie ajena pueden asomar: `existing_id` solo aparece
    # dentro de `skipped`, y `skipped` tiene que estar vacio.
    assert 'existing_id' not in resp.content.decode()
    assert foreign.id not in {item['id'] for item in body['created']}
    assert ClassTemplate.objects.filter(organization=setup['org'], weekday=2).count() == 1
    assert ClassTemplate.objects.filter(organization=other_org['org']).count() == 1


# ==========================================================================================
# B. Guardas: rol, organizacion forzada y forma del param.
# ==========================================================================================


@pytest.mark.parametrize('actor', ['student', 'teacher'])
def test_solo_admin_puede_crear_lotes(api_client, setup, actor):
    """Misma guarda que el camino singular (`perform_create`): alumno y profesor no crean
    series, ni de una ni de varias -> 403 y cero filas."""
    _login(api_client, setup[actor])

    resp = api_client.post(URL, _payload(setup, weekdays=[0, 2, 4]), format='json')

    assert resp.status_code == 403, resp.content
    assert ClassTemplate.objects.count() == 0


def test_organization_del_payload_se_fuerza_a_la_del_actor(api_client, setup, other_org):
    """El `organization` que llega en el body se ignora: el lote queda en la organizacion
    del actor, igual que en el alta singular."""
    _login(api_client, setup['admin'])

    resp = api_client.post(
        URL, _payload(setup, weekdays=[0, 2], organization=other_org['org'].id), format='json',
    )

    assert resp.status_code == 201, resp.content
    assert {item['organization'] for item in resp.json()['created']} == {setup['org'].id}
    assert ClassTemplate.objects.filter(organization=setup['org']).count() == 2
    assert ClassTemplate.objects.filter(organization=other_org['org']).count() == 0


def test_branch_de_otra_org_falla_igual_que_en_el_camino_singular(api_client, setup, other_org):
    """La sede ajena la rechaza `ClassTemplate.clean()` via serializer (400 con la key
    `branch`), exactamente igual que el POST de un solo dia. Todo o nada: ni la primera
    plantilla del lote se crea."""
    _login(api_client, setup['admin'])

    singular = api_client.post(
        URL, _payload(setup, weekday=0, branch=other_org['branch'].id, start_date=str(timezone.localdate())),
        format='json',
    )
    batch = api_client.post(
        URL, _payload(setup, weekdays=[0, 2, 4], branch=other_org['branch'].id), format='json',
    )

    assert singular.status_code == 400, singular.content
    assert batch.status_code == 400, batch.content
    assert 'branch' in batch.json()
    assert batch.json()['branch'] == singular.json()['branch']
    assert ClassTemplate.objects.count() == 0


@pytest.mark.parametrize('raw', [[], [7], [-1], '0,2', 'lunes', ['x'], 0, {'0': True}])
def test_weekdays_invalidos_son_400(api_client, setup, raw):
    """Forma del param: lista NO vacia de enteros 0-6. Cualquier otra cosa -> 400 con la
    key `weekdays` y cero escrituras (ni se cae al camino singular por la ventana)."""
    _login(api_client, setup['admin'])

    resp = api_client.post(URL, _payload(setup, weekdays=raw), format='json')

    assert resp.status_code == 400, resp.content
    assert 'weekdays' in resp.json()
    assert ClassTemplate.objects.count() == 0


def test_weekdays_repetidos_se_deduplican_en_el_input(api_client, setup):
    """`[0, 0, 2]` es "lunes y miercoles", no tres series: el input se deduplica y se
    ordena antes de crear."""
    _login(api_client, setup['admin'])

    resp = api_client.post(URL, _payload(setup, weekdays=[2, 0, 0]), format='json')

    assert resp.status_code == 201, resp.content
    assert [item['weekday'] for item in resp.json()['created']] == [0, 2]
    assert ClassTemplate.objects.filter(organization=setup['org']).count() == 2


# ==========================================================================================
# C. Regresion del camino singular (sin `weekdays` NADA cambia).
# ==========================================================================================


def test_camino_legacy_singular_con_start_date_explicito(api_client, setup):
    """Sin `weekdays`, la respuesta sigue siendo la PLANTILLA serializada (no el sobre
    `created/skipped`) y sigue materializando sus clases."""
    _login(api_client, setup['admin'])
    today = timezone.localdate()

    resp = api_client.post(URL, _payload(setup, weekday=2, start_date=str(today)), format='json')

    assert resp.status_code == 201, resp.content
    body = resp.json()
    assert 'created' not in body and 'skipped' not in body
    assert body['weekday'] == 2
    assert body['start_date'] == str(today)
    assert body['organization'] == setup['org'].id
    template = ClassTemplate.objects.get(pk=body['id'])
    assert template.instances.count() > 0


def test_camino_legacy_singular_sin_start_date_infiere_hoy(api_client, setup):
    """`start_date` opcional tambien en el camino de un solo dia: se infiere hoy sin
    TypeError (antes `generate_instances_for_template_range` recibia `None` y explotaba en
    `max(...)`), y las clases arrancan desde hoy."""
    _login(api_client, setup['admin'])
    today = timezone.localdate()

    resp = api_client.post(URL, _payload(setup, weekday=4), format='json')

    assert resp.status_code == 201, resp.content
    body = resp.json()
    assert body['start_date'] == str(today)
    assert body['end_date'] is None
    template = ClassTemplate.objects.get(pk=body['id'])
    assert template.start_date == today
    dates = _instance_dates(template)
    assert dates, 'la serie sin start_date tiene que materializar igual'
    assert all(day >= today for day in dates)


def test_camino_legacy_sin_weekday_sigue_siendo_400(api_client, setup):
    """`weekday` sigue siendo obligatorio cuando NO se manda `weekdays`: el lote no
    relaja el camino viejo."""
    _login(api_client, setup['admin'])

    resp = api_client.post(URL, _payload(setup), format='json')

    assert resp.status_code == 400, resp.content
    assert 'weekday' in resp.json()
    assert ClassTemplate.objects.count() == 0
