"""Clase con suplente (P4 #A): registro/visualizacion PURO de quien dio la clase de
verdad. Decision de negocio #11, congelada: la plataforma paga SIEMPRE al profesor
asignado (`GymClass.teacher`, FK singular); el suplente es texto libre (puede no
existir en el sistema) y NO cambia a quien se le paga -- el arreglo economico con el
suplente ocurre FUERA de la plataforma. Este archivo cubre:

1. Alta y edicion vía API persisten check + nombre.
2. Centinela de pago: `calculate_teacher_payment` da el MISMO resultado con
   `has_substitute=True` y con `has_substitute=False` -- el corazon de la feature,
   prueba que el suplente no desvia plata.
3. Filtro `?has_substitute=true|false` sobre `GET /api/classes/`.
4. Cross-org: un `gym_admin` de otra organizacion no puede leer NI setear el
   suplente de una clase ajena (404 sin oraculo -- mismo `get_queryset` filtrado por
   organizacion de siempre, sin rama especial para estos dos campos).
5. Normalizacion determinista sobre el estado RESULTANTE (PATCH parcial):
   `has_substitute=False` fuerza `substitute_name=''`; `has_substitute=True` con
   nombre vacio -> 400.
6. Herencia serie -> instancia (`services/recurrence.py`): la plantilla materializa
   la instancia con su propio default de suplente.

Estilo y fixtures calcados de `test_multi_day_templates.py` (login por email +
subdominio, `_org_setup` autosuficiente por organizacion) y de
`test_teacher_payments.py` (`_make_completed_class` para el centinela de pago).
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from core.models import (
    Branch,
    ClassTemplate,
    ClassType,
    Discipline,
    GymClass,
    TeacherPaymentRule,
)
from core.services.teacher_payments import calculate_teacher_payment

pytestmark = pytest.mark.django_db

PASSWORD = 'Passw0rd2026'
CLASSES_URL = '/api/classes/'
TEMPLATES_URL = '/api/class-templates/'


def _login(api_client, user):
    """Calco de test_multi_day_templates.py:53-59 (login por email + subdominio de la org)."""
    host = {'HTTP_HOST': f'{user.organization.subdomain}.localhost'} if user.organization_id else {}
    token = api_client.post(
        '/api/login/', {'email': user.email, 'password': PASSWORD}, format='json', **host
    ).json()['token']
    api_client.credentials(HTTP_AUTHORIZATION=f'Token {token}')


def _org_setup(make_organization, make_user, tag):
    """Organizacion autosuficiente: admin, profe, sede, tipo y disciplina propios."""
    org = make_organization()
    return {
        'org': org,
        'admin': make_user(f'admin-{tag}', organization=org, role='gym_admin'),
        'teacher': make_user(f'teach-{tag}', organization=org, role='teacher'),
        'branch': Branch.objects.create(organization=org, name=f'Sede {tag}'),
        'class_type': ClassType.objects.create(organization=org, name=f'Tipo {tag}'),
        'discipline': Discipline.objects.create(organization=org, name=f'Disciplina {tag}'),
    }


@pytest.fixture
def setup(make_organization, make_user):
    return _org_setup(make_organization, make_user, 'sub')


@pytest.fixture
def other_org(make_organization, make_user):
    return _org_setup(make_organization, make_user, 'ajena')


def _class_payload(setup, **overrides):
    start = timezone.now() + timedelta(days=1)
    data = {
        'name': 'Clase con suplente',
        'branch': setup['branch'].id,
        'teacher': setup['teacher'].id,
        'class_type': setup['class_type'].id,
        'discipline': setup['discipline'].id,
        'start_datetime': start.isoformat(),
        'end_datetime': (start + timedelta(hours=1)).isoformat(),
        'capacity': 10,
    }
    data.update(overrides)
    return data


def _make_completed_class(org, branch, teacher, **overrides):
    """Calco de test_teacher_payments.py:43-53, con overrides para setear el suplente."""
    start = timezone.now() - timedelta(hours=2)
    defaults = dict(
        organization=org,
        branch=branch,
        teacher=teacher,
        name='Clase',
        start_datetime=start,
        end_datetime=start + timedelta(hours=1),
        status=GymClass.Status.COMPLETED,
    )
    defaults.update(overrides)
    return GymClass.objects.create(**defaults)


# ==========================================================================================
# A. Alta y edicion: check + nombre persisten.
# ==========================================================================================


def test_crear_clase_con_suplente_persiste_check_y_nombre(api_client, setup):
    _login(api_client, setup['admin'])

    resp = api_client.post(
        CLASSES_URL,
        _class_payload(setup, has_substitute=True, substitute_name='Marcela Rios'),
        format='json',
    )

    assert resp.status_code == 201, resp.content
    body = resp.json()
    assert body['has_substitute'] is True
    assert body['substitute_name'] == 'Marcela Rios'
    gym_class = GymClass.objects.get(pk=body['id'])
    assert gym_class.has_substitute is True
    assert gym_class.substitute_name == 'Marcela Rios'
    # El titular sigue siendo el profesor asignado: el suplente no lo reemplaza.
    assert gym_class.teacher_id == setup['teacher'].id


def test_editar_clase_para_agregar_suplente_persiste(api_client, setup):
    _login(api_client, setup['admin'])
    created = api_client.post(CLASSES_URL, _class_payload(setup), format='json').json()
    assert created['has_substitute'] is False  # default sin suplente

    resp = api_client.patch(
        f"{CLASSES_URL}{created['id']}/",
        {'has_substitute': True, 'substitute_name': 'Pedro Lucero'},
        format='json',
    )

    assert resp.status_code == 200, resp.content
    assert resp.json()['substitute_name'] == 'Pedro Lucero'
    gym_class = GymClass.objects.get(pk=created['id'])
    assert gym_class.has_substitute is True
    assert gym_class.substitute_name == 'Pedro Lucero'


# ==========================================================================================
# B. Centinela de pago: el suplente NO desvia plata.
# ==========================================================================================


def test_centinela_pago_identico_con_o_sin_suplente(setup):
    """El corazon de la feature. Mismo profesor, misma regla activa, UNICA diferencia
    entre las dos clases es has_substitute/substitute_name -> `calculate_teacher_payment`
    tiene que devolver el mismo total_amount y total_students en los dos casos."""
    org, branch, teacher = setup['org'], setup['branch'], setup['teacher']
    rule = TeacherPaymentRule.objects.create(
        organization=org,
        payment_type=TeacherPaymentRule.PaymentType.FIXED_PER_CLASS,
        amount=5000,
        is_active=True,
    )
    rule.teachers.add(teacher)

    without_substitute = _make_completed_class(
        org, branch, teacher, has_substitute=False, substitute_name='',
    )
    with_substitute = _make_completed_class(
        org, branch, teacher, has_substitute=True, substitute_name='Marcela Rios',
    )

    record_without, _ = calculate_teacher_payment(without_substitute)
    record_with, _ = calculate_teacher_payment(with_substitute)

    assert record_without is not None and record_with is not None
    assert record_without.total_amount == record_with.total_amount == 5000
    assert record_without.total_students == record_with.total_students
    # Y el pago sigue acreditado al TITULAR, nunca al suplente (que ni tiene FK).
    assert record_without.teacher_id == teacher.id
    assert record_with.teacher_id == teacher.id


# ==========================================================================================
# C. Filtro ?has_substitute=.
# ==========================================================================================


def test_filtro_has_substitute_devuelve_solo_las_marcadas(api_client, setup):
    _login(api_client, setup['admin'])
    marked = api_client.post(
        CLASSES_URL,
        _class_payload(setup, has_substitute=True, substitute_name='Marcela Rios'),
        format='json',
    ).json()
    unmarked = api_client.post(
        CLASSES_URL, _class_payload(setup, name='Otra clase'), format='json',
    ).json()

    resp_true = api_client.get(CLASSES_URL, {'has_substitute': 'true'})
    resp_false = api_client.get(CLASSES_URL, {'has_substitute': 'false'})

    assert resp_true.status_code == 200, resp_true.content
    assert resp_false.status_code == 200, resp_false.content
    assert {item['id'] for item in resp_true.json()} == {marked['id']}
    assert {item['id'] for item in resp_false.json()} == {unmarked['id']}


# ==========================================================================================
# D. Cross-org: sin oraculo.
# ==========================================================================================


def test_cross_org_no_lee_ni_setea_suplente_ajeno(api_client, setup, other_org):
    _login(api_client, setup['admin'])
    created = api_client.post(CLASSES_URL, _class_payload(setup), format='json').json()

    _login(api_client, other_org['admin'])
    get_resp = api_client.get(f"{CLASSES_URL}{created['id']}/")
    patch_resp = api_client.patch(
        f"{CLASSES_URL}{created['id']}/",
        {'has_substitute': True, 'substitute_name': 'Intruso'},
        format='json',
    )

    assert get_resp.status_code == 404, get_resp.content
    assert patch_resp.status_code == 404, patch_resp.content
    gym_class = GymClass.objects.get(pk=created['id'])
    assert gym_class.has_substitute is False
    assert gym_class.substitute_name == ''


# ==========================================================================================
# E. Normalizacion determinista.
# ==========================================================================================


def test_normalizacion_has_substitute_false_limpia_el_nombre(api_client, setup):
    _login(api_client, setup['admin'])
    created = api_client.post(
        CLASSES_URL,
        _class_payload(setup, has_substitute=True, substitute_name='Marcela Rios'),
        format='json',
    ).json()
    assert created['substitute_name'] == 'Marcela Rios'

    resp = api_client.patch(
        f"{CLASSES_URL}{created['id']}/", {'has_substitute': False}, format='json',
    )

    assert resp.status_code == 200, resp.content
    assert resp.json()['substitute_name'] == ''
    gym_class = GymClass.objects.get(pk=created['id'])
    assert gym_class.substitute_name == '', 'no puede quedar un nombre huerfano de un check apagado'


def test_normalizacion_has_substitute_true_sin_nombre_es_400(api_client, setup):
    _login(api_client, setup['admin'])

    resp = api_client.post(
        CLASSES_URL, _class_payload(setup, has_substitute=True), format='json',
    )

    assert resp.status_code == 400, resp.content
    assert 'substitute_name' in resp.json()
    assert not GymClass.objects.exists()


def test_normalizacion_has_substitute_true_con_nombre_en_blanco_es_400(api_client, setup):
    """Mismo caso que arriba pero con substitute_name presente y solo espacios: el
    `.strip()` de la normalizacion no lo deja pasar como si tuviera contenido."""
    _login(api_client, setup['admin'])

    resp = api_client.post(
        CLASSES_URL,
        _class_payload(setup, has_substitute=True, substitute_name='   '),
        format='json',
    )

    assert resp.status_code == 400, resp.content
    assert 'substitute_name' in resp.json()


# ==========================================================================================
# F. Herencia serie -> instancia.
# ==========================================================================================


def test_herencia_serie_instancia_hereda_el_suplente_default(api_client, setup):
    """La instancia que la serie materializa hereda has_substitute/substitute_name del
    default de la plantilla (services/recurrence.py); no hace falta marcarlo clase por
    clase."""
    _login(api_client, setup['admin'])
    today = timezone.localdate()

    resp = api_client.post(
        TEMPLATES_URL,
        {
            'name': 'Serie con suplente',
            'branch': setup['branch'].id,
            'teacher': setup['teacher'].id,
            'class_type': setup['class_type'].id,
            'discipline': setup['discipline'].id,
            'weekday': today.weekday(),
            'start_time': '10:00',
            'end_time': '11:00',
            'capacity': 10,
            'has_substitute': True,
            'substitute_name': 'Marcela Rios',
        },
        format='json',
    )

    assert resp.status_code == 201, resp.content
    template = ClassTemplate.objects.get(pk=resp.json()['id'])
    assert template.has_substitute is True
    assert template.substitute_name == 'Marcela Rios'
    instances = GymClass.objects.filter(class_template=template)
    assert instances.exists(), 'la serie tiene que haber materializado al menos una instancia'
    assert set(instances.values_list('has_substitute', flat=True)) == {True}
    assert set(instances.values_list('substitute_name', flat=True)) == {'Marcela Rios'}


def test_editar_serie_no_toca_el_suplente_de_una_instancia_con_inscritos(api_client, setup):
    """Mismo contrato que el resto de los campos de plantilla (is_trial_eligible,
    capacity, etc.): `apply_template_updates_to_future_instances` protege las
    instancias futuras con inscritos activos, así que el suplente tampoco se les
    reescribe ahí."""
    from core.models import Enrollment

    _login(api_client, setup['admin'])
    # Mañana (no hoy): así la instancia queda inequívocamente en el futuro respecto de
    # "now" sin importar a qué hora del día corra el test, que es justo lo que exige el
    # filtro `start_datetime__gt=now` de `apply_template_updates_to_future_instances`.
    tomorrow = timezone.localdate() + timedelta(days=1)
    created = api_client.post(
        TEMPLATES_URL,
        {
            'name': 'Serie sin suplente',
            'branch': setup['branch'].id,
            'teacher': setup['teacher'].id,
            'class_type': setup['class_type'].id,
            'discipline': setup['discipline'].id,
            'weekday': tomorrow.weekday(),
            'start_time': '10:00',
            'end_time': '11:00',
            'capacity': 10,
        },
        format='json',
    ).json()
    template_id = created['id']
    instance = GymClass.objects.filter(class_template_id=template_id).order_by('start_datetime').first()
    assert instance is not None
    student = setup['admin']  # cualquier usuario de la org alcanza para forzar la proteccion
    Enrollment.objects.create(gym_class=instance, student=student, status='active')

    resp = api_client.patch(
        f"{TEMPLATES_URL}{template_id}/",
        {'has_substitute': True, 'substitute_name': 'Marcela Rios', 'apply_to_future_instances': True},
        format='json',
    )

    assert resp.status_code == 200, resp.content
    instance.refresh_from_db()
    assert instance.has_substitute is False, 'la instancia con inscritos activos queda protegida, igual que el resto de los campos'
    assert instance.substitute_name == ''
