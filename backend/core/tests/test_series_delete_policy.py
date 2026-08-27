"""Borrar una serie tiene UNA sola política: gym_admin (y superadmin). El manager no.

Antes convivían TRES políticas contradictorias sobre el mismo `ClassTemplateViewSet`:

* `destroy` usaba `_can_manage_org_resource` → gym_admin/superadmin. Le NEGABA al manager.
* `bulk-action` con `action='delete'` usaba `_can_manage_operational_resource` → org-admin,
  que incluye a `manager`. Por ahí el manager SÍ borraba series, y era la vía que usa el
  frontend para la selección múltiple.
* `perform_destroy` declaraba una tercera variante y era código MUERTO: `destroy` está
  sobreescrito y nunca lo invoca, así que leerlo daba una idea equivocada de la regla.

La decisión de producto es la más restrictiva: borrar una serie destruye historial
(`delete_template_safely` arrastra las clases generadas), así que queda en manos de
gym_admin. El manager conserva todo lo demás —desactivar, cancelar futuras, regenerar—
que es reversible.
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from core.models import Branch, ClassTemplate, GymClass, RecurringEnrollment

pytestmark = pytest.mark.django_db

PASSWORD = 'Passw0rd2026'
BULK_URL = '/api/class-templates/bulk-action/'


def _login(api_client, username):
    from django.contrib.auth import get_user_model
    user = get_user_model().objects.get(username=username)
    host = {'HTTP_HOST': f'{user.organization.subdomain}.localhost'} if user.organization_id else {}
    token = api_client.post(
        '/api/login/', {'email': user.email, 'password': PASSWORD}, format='json', **host
    ).json()['token']
    api_client.credentials(HTTP_AUTHORIZATION=f'Token {token}')


def _template(org, branch, teacher, name='Serie'):
    """Una serie borrable: sin recurrencias, sin inscripciones y sin historial."""
    today = timezone.localdate()
    return ClassTemplate.objects.create(
        organization=org, branch=branch, teacher=teacher, name=name, weekday=0,
        start_time='10:00', end_time='11:00', capacity=10,
        start_date=today, end_date=today + timedelta(days=60),
    )


@pytest.fixture
def setup(make_organization, make_user):
    org = make_organization()
    branch = Branch.objects.create(organization=org, name='Sede Centro')
    admin = make_user('admin', organization=org, role='gym_admin')
    manager = make_user('gerente', organization=org, role='manager')
    teacher = make_user('teach', organization=org, role='teacher')
    student = make_user('alu', organization=org, role='student', email='alu@gym.cl')
    return {
        'org': org, 'branch': branch, 'admin': admin, 'manager': manager,
        'teacher': teacher, 'student': student,
        'template': _template(org, branch, teacher),
    }


# --- A. El manager no borra series por NINGUNA vía -------------------------------


def test_manager_cannot_delete_a_series_via_destroy(api_client, setup):
    _login(api_client, 'gerente')

    resp = api_client.delete(f'/api/class-templates/{setup["template"].id}/')

    assert resp.status_code == 403, resp.content
    assert ClassTemplate.objects.filter(id=setup['template'].id).exists()


def test_manager_cannot_delete_a_series_via_bulk_action(api_client, setup):
    """La vía que estaba abierta: el frontend borra la selección múltiple por acá."""
    _login(api_client, 'gerente')

    resp = api_client.post(BULK_URL, {
        'action': 'delete', 'template_ids': [setup['template'].id],
    }, format='json')

    assert resp.status_code == 403, resp.content
    assert ClassTemplate.objects.filter(id=setup['template'].id).exists(), \
        'el manager borró la serie por la puerta de atrás'


def test_manager_bulk_delete_is_rejected_as_a_whole(api_client, setup):
    """El rechazo es de la petición completa y no fila por fila: un `skipped` por id
    delataría qué ids existen, y el manager tampoco tiene por qué sondear eso."""
    _login(api_client, 'gerente')

    resp = api_client.post(BULK_URL, {
        'action': 'delete', 'template_ids': [setup['template'].id, 999999],
    }, format='json')

    assert resp.status_code == 403, resp.content
    assert 'deleted_ids' not in resp.json(), 'no debe devolver un resumen por fila'


def test_manager_bulk_delete_does_not_delete_even_a_deletable_series(api_client, setup):
    """Doble red: la serie del fixture es perfectamente borrable (sin historial), así que
    si la política se relajara este test lo detecta de inmediato."""
    other = _template(setup['org'], setup['branch'], setup['teacher'], name='Otra serie')
    _login(api_client, 'gerente')

    api_client.post(BULK_URL, {
        'action': 'delete', 'template_ids': [setup['template'].id, other.id],
    }, format='json')

    assert ClassTemplate.objects.filter(id=setup['template'].id).exists()
    assert ClassTemplate.objects.filter(id=other.id).exists()


@pytest.mark.parametrize('role', ['monitor', 'teacher', 'student'])
def test_other_non_admin_roles_cannot_delete_a_series_either(api_client, setup, make_user, role):
    make_user('otro', organization=setup['org'], role=role, email=f'{role}@gym.cl')
    _login(api_client, 'otro')

    direct = api_client.delete(f'/api/class-templates/{setup["template"].id}/')
    bulk = api_client.post(BULK_URL, {
        'action': 'delete', 'template_ids': [setup['template'].id],
    }, format='json')

    assert direct.status_code in (403, 404), direct.content
    # 403 exacto y no "200 + skipped": aceptar el 200 dejaría pasar el comportamiento
    # viejo, en que el rechazo era fila por fila y por lo tanto delataba qué ids existen.
    assert bulk.status_code == 403, bulk.content
    assert ClassTemplate.objects.filter(id=setup['template'].id).exists()


def test_the_role_gate_runs_before_the_payload_is_even_validated(api_client, setup):
    """El orden importa: si el gate por rol corriera DESPUÉS de validar `template_ids`, un
    manager podría distinguir un payload bien formado de uno mal formado y usar eso para
    sondear. Sin ids, o con ids basura, la respuesta al manager sigue siendo 403."""
    _login(api_client, 'gerente')

    no_ids = api_client.post(BULK_URL, {'action': 'delete'}, format='json')
    garbage = api_client.post(BULK_URL, {
        'action': 'delete', 'template_ids': ['abc'],
    }, format='json')

    assert no_ids.status_code == 403, no_ids.content
    assert garbage.status_code == 403, garbage.content


def test_an_invalid_action_is_still_a_400_for_the_manager(api_client, setup):
    """El gate es solo para `delete`: una acción inexistente sigue siendo un 400 de forma,
    no un 403 de permisos."""
    _login(api_client, 'gerente')

    resp = api_client.post(BULK_URL, {
        'action': 'destruir_todo', 'template_ids': [setup['template'].id],
    }, format='json')

    assert resp.status_code == 400, resp.content


# --- B. El gym_admin sí borra, por las dos vías ----------------------------------


def test_gym_admin_deletes_a_series_via_destroy(api_client, setup):
    _login(api_client, 'admin')

    resp = api_client.delete(f'/api/class-templates/{setup["template"].id}/')

    assert resp.status_code == 204, resp.content
    assert not ClassTemplate.objects.filter(id=setup['template'].id).exists()


def test_gym_admin_deletes_a_series_via_bulk_action(api_client, setup):
    _login(api_client, 'admin')

    resp = api_client.post(BULK_URL, {
        'action': 'delete', 'template_ids': [setup['template'].id],
    }, format='json')

    assert resp.status_code == 200, resp.content
    assert resp.json()['deleted_ids'] == [setup['template'].id], resp.content
    assert not ClassTemplate.objects.filter(id=setup['template'].id).exists()


def test_superadmin_deletes_a_series_by_both_routes(api_client, setup, make_user):
    other = _template(setup['org'], setup['branch'], setup['teacher'], name='Otra serie')
    make_user('root', role='superadmin', organization=None)
    _login(api_client, 'root')

    direct = api_client.delete(f'/api/class-templates/{setup["template"].id}/')
    bulk = api_client.post(BULK_URL, {'action': 'delete', 'template_ids': [other.id]},
                           format='json')

    assert direct.status_code == 204, direct.content
    assert bulk.status_code == 200, bulk.content
    assert not ClassTemplate.objects.filter(id__in=[setup['template'].id, other.id]).exists()


# --- C. Al manager no se le quita nada más --------------------------------------


@pytest.mark.parametrize('action_name', [
    'deactivate', 'activate', 'cancel_future_instances',
    'reactivate_future_cancelled', 'generate_pending',
])
def test_manager_keeps_every_other_bulk_action(api_client, setup, action_name):
    """La restricción es SOLO el borrado. Todo lo reversible sigue siendo del manager."""
    _login(api_client, 'gerente')

    resp = api_client.post(BULK_URL, {
        'action': action_name, 'template_ids': [setup['template'].id], 'comment': 'ok',
    }, format='json')

    assert resp.status_code == 200, resp.content
    assert resp.json()['updated_ids'] == [setup['template'].id], resp.content


def test_manager_can_still_deactivate_a_series_it_cannot_delete(api_client, setup):
    """El camino que le queda al manager para "sacar" una serie: desactivarla."""
    _login(api_client, 'gerente')

    resp = api_client.post(BULK_URL, {
        'action': 'deactivate', 'template_ids': [setup['template'].id],
    }, format='json')

    assert resp.status_code == 200, resp.content
    setup['template'].refresh_from_db()
    assert setup['template'].is_active is False


# --- D. Una sola política: la guarda de integridad sigue viva --------------------


def test_the_only_delete_policy_lives_in_destroy(api_client, setup):
    """`perform_destroy` era una TERCERA política, y muerta: `destroy` está sobreescrito
    y nunca la invoca. Que no vuelva a existir un camino que declare otra regla."""
    from core.views import ClassTemplateViewSet

    assert 'perform_destroy' not in ClassTemplateViewSet.__dict__, (
        'ClassTemplateViewSet volvió a declarar perform_destroy: `destroy` está '
        'sobreescrito, así que ese método es código muerto que contradice la política'
    )


def test_the_per_object_check_would_stop_the_manager_even_without_the_role_gate(
    api_client, setup, monkeypatch,
):
    """El bucle de `bulk_action` elige el predicado según la acción, y para `delete` usa el
    estrecho. Hoy es inalcanzable —el gate por rol corta antes— así que se verifica
    neutralizando el gate: es la segunda capa, y sin este test el comentario que promete
    "si ese gate se toca, el bucle sigue siendo correcto" no lo respalda nada."""
    from accounts import roles

    monkeypatch.setattr(roles, 'can_manage_admin', lambda user: True)
    _login(api_client, 'gerente')

    resp = api_client.post(BULK_URL, {
        'action': 'delete', 'template_ids': [setup['template'].id],
    }, format='json')

    assert resp.status_code == 200, resp.content
    assert resp.json()['deleted_ids'] == [], resp.content
    assert resp.json()['skipped'] == [{'id': setup['template'].id, 'reason': 'Sin permisos'}]
    assert ClassTemplate.objects.filter(id=setup['template'].id).exists()


def test_gym_admin_still_cannot_delete_a_series_with_history(api_client, setup):
    """La política de ROL no reemplaza a la de INTEGRIDAD: `can_delete_template` sigue
    negando el borrado de una serie con recurrencias, y el gym_admin no la evade."""
    RecurringEnrollment.objects.create(
        student=setup['student'], class_template=setup['template'],
        start_date=timezone.localdate(),
    )
    _login(api_client, 'admin')

    resp = api_client.delete(f'/api/class-templates/{setup["template"].id}/')

    assert resp.status_code == 400, resp.content
    assert ClassTemplate.objects.filter(id=setup['template'].id).exists()


def test_class_template_list_exposes_delete_guard_reason(api_client, setup):
    RecurringEnrollment.objects.create(
        student=setup['student'], class_template=setup['template'],
        start_date=timezone.localdate(),
    )
    _login(api_client, 'admin')

    resp = api_client.get('/api/class-templates/')

    assert resp.status_code == 200, resp.content
    item = next(row for row in resp.json() if row['id'] == setup['template'].id)
    assert item['can_delete'] is False
    assert item['delete_block_reason'] == 'La serie tiene recurrencias de alumnos asociadas.'


def test_classes_list_filters_instances_by_class_template(api_client, setup):
    other = _template(setup['org'], setup['branch'], setup['teacher'], name='Otra serie')
    start = timezone.now() - timedelta(days=7)
    target_class = GymClass.objects.create(
        organization=setup['org'], branch=setup['branch'], teacher=setup['teacher'],
        class_template=setup['template'], name='Clase del historial',
        start_datetime=start, end_datetime=start + timedelta(hours=1), capacity=10,
        status=GymClass.Status.COMPLETED,
    )
    GymClass.objects.create(
        organization=setup['org'], branch=setup['branch'], teacher=setup['teacher'],
        class_template=other, name='Clase de otra serie',
        start_datetime=start, end_datetime=start + timedelta(hours=1), capacity=10,
        status=GymClass.Status.COMPLETED,
    )
    _login(api_client, 'admin')

    resp = api_client.get(f'/api/classes/?class_template={setup["template"].id}')

    assert resp.status_code == 200, resp.content
    assert [row['id'] for row in resp.json()] == [target_class.id]


def test_bulk_delete_still_skips_a_series_with_history(api_client, setup):
    """Misma guarda por la vía masiva: se reporta en `skipped`, no se borra."""
    start = timezone.now() - timedelta(days=2)
    GymClass.objects.create(
        organization=setup['org'], branch=setup['branch'], teacher=setup['teacher'],
        class_template=setup['template'], name='Clase pasada', start_datetime=start,
        end_datetime=start + timedelta(hours=1), capacity=10,
        status=GymClass.Status.COMPLETED,
    )
    _login(api_client, 'admin')

    resp = api_client.post(BULK_URL, {
        'action': 'delete', 'template_ids': [setup['template'].id],
    }, format='json')

    assert resp.status_code == 200, resp.content
    assert resp.json()['deleted_ids'] == [], resp.content
    assert resp.json()['skipped'], 'debe explicar por qué no se borró'
    assert ClassTemplate.objects.filter(id=setup['template'].id).exists()


# --- E. El scoping por organización sigue intacto -------------------------------


def test_gym_admin_cannot_delete_a_series_from_another_org(
    api_client, setup, make_organization, make_user,
):
    other_org = make_organization(name='Otra Org')
    make_user('intruso', organization=other_org, role='gym_admin')
    _login(api_client, 'intruso')

    direct = api_client.delete(f'/api/class-templates/{setup["template"].id}/')
    bulk = api_client.post(BULK_URL, {
        'action': 'delete', 'template_ids': [setup['template'].id],
    }, format='json')

    assert direct.status_code == 404, direct.content
    assert bulk.status_code == 200, bulk.content
    assert bulk.json()['deleted_ids'] == [], bulk.content
    assert ClassTemplate.objects.filter(id=setup['template'].id).exists()


def test_manager_from_another_org_gets_the_same_403_and_learns_nothing(
    api_client, setup, make_organization, make_user,
):
    """El 403 del manager es por ROL, así que llega antes de mirar los ids: un manager
    ajeno recibe exactamente la misma respuesta que uno propio y no distingue si el id
    existe."""
    other_org = make_organization(name='Otra Org')
    make_user('gerente_b', organization=other_org, role='manager')
    _login(api_client, 'gerente_b')

    foreign = api_client.post(BULK_URL, {
        'action': 'delete', 'template_ids': [setup['template'].id],
    }, format='json')
    missing = api_client.post(BULK_URL, {
        'action': 'delete', 'template_ids': [999999],
    }, format='json')

    assert foreign.status_code == 403, foreign.content
    assert foreign.content == missing.content, 'la respuesta distingue el id ajeno del inexistente'
    assert ClassTemplate.objects.filter(id=setup['template'].id).exists()
