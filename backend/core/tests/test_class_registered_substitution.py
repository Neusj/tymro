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
    host = {'HTTP_HOST': f'{user.organization.subdomain}.localhost'} if user.organization_id else {}
    token = api_client.post(
        '/api/login/', {'email': user.email, 'password': PASSWORD}, format='json', **host
    ).json()['token']
    api_client.credentials(HTTP_AUTHORIZATION=f'Token {token}')


def _org_setup(make_organization, make_user, tag):
    org = make_organization()
    return {
        'org': org,
        'admin': make_user(f'admin-reg-sub-{tag}', organization=org, role='gym_admin'),
        'teacher': make_user(f'teacher-reg-sub-{tag}', organization=org, role='teacher'),
        'substitute': make_user(f'substitute-reg-sub-{tag}', organization=org, role='teacher'),
        'branch': Branch.objects.create(organization=org, name=f'Sede {tag}'),
        'class_type': ClassType.objects.create(organization=org, name=f'Tipo {tag}'),
        'discipline': Discipline.objects.create(organization=org, name=f'Disciplina {tag}'),
    }


@pytest.fixture
def setup(make_organization, make_user):
    return _org_setup(make_organization, make_user, 'own')


@pytest.fixture
def other_org(make_organization, make_user):
    return _org_setup(make_organization, make_user, 'other')


def _class_payload(setup, **overrides):
    start = overrides.pop('start', timezone.now() + timedelta(days=1))
    data = {
        'name': 'Clase suplencia registrada',
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


def _make_class(setup, **overrides):
    start = overrides.pop('start', timezone.now() + timedelta(days=1))
    defaults = {
        'organization': setup['org'],
        'branch': setup['branch'],
        'teacher': setup['teacher'],
        'class_type': setup['class_type'],
        'discipline': setup['discipline'],
        'name': 'Clase',
        'start_datetime': start,
        'end_datetime': start + timedelta(hours=1),
        'status': GymClass.Status.SCHEDULED,
    }
    defaults.update(overrides)
    return GymClass.objects.create(**defaults)


def test_admin_asigna_profesor_registrado_como_suplente(api_client, setup):
    _login(api_client, setup['admin'])

    resp = api_client.post(
        CLASSES_URL,
        _class_payload(
            setup,
            has_substitute=True,
            substitute_teacher=setup['substitute'].id,
        ),
        format='json',
    )

    assert resp.status_code == 201, resp.content
    body = resp.json()
    assert body['has_substitute'] is True
    assert body['substitute_teacher'] == setup['substitute'].id
    assert body['substitute_name'] == ''
    assert body['substitute_kind'] == 'registered'
    assert body['effective_substitution_source'] == GymClass.SubstitutionSource.ADMIN_ASSIGNED
    gym_class = GymClass.objects.get(pk=body['id'])
    assert gym_class.teacher_id == setup['teacher'].id
    assert gym_class.substitute_teacher_id == setup['substitute'].id


def test_admin_cambia_registrado_por_externo_y_externo_por_registrado(api_client, setup):
    _login(api_client, setup['admin'])
    created = api_client.post(
        CLASSES_URL,
        _class_payload(setup, has_substitute=True, substitute_teacher=setup['substitute'].id),
        format='json',
    ).json()

    external = api_client.patch(
        f"{CLASSES_URL}{created['id']}/",
        {'has_substitute': True, 'substitute_teacher': None, 'substitute_name': 'Marcela Rios'},
        format='json',
    )
    assert external.status_code == 200, external.content
    assert external.json()['substitute_teacher'] is None
    assert external.json()['substitute_name'] == 'Marcela Rios'
    assert external.json()['substitute_kind'] == 'external'
    assert external.json()['effective_substitution_source'] == GymClass.SubstitutionSource.EXTERNAL_ADMIN

    registered = api_client.patch(
        f"{CLASSES_URL}{created['id']}/",
        {'has_substitute': True, 'substitute_teacher': setup['substitute'].id},
        format='json',
    )
    assert registered.status_code == 200, registered.content
    assert registered.json()['substitute_teacher'] == setup['substitute'].id
    assert registered.json()['substitute_name'] == ''
    assert registered.json()['substitute_kind'] == 'registered'


def test_admin_elimina_suplencia_registrada(api_client, setup):
    _login(api_client, setup['admin'])
    created = api_client.post(
        CLASSES_URL,
        _class_payload(setup, has_substitute=True, substitute_teacher=setup['substitute'].id),
        format='json',
    ).json()

    resp = api_client.patch(f"{CLASSES_URL}{created['id']}/", {'has_substitute': False}, format='json')

    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body['has_substitute'] is False
    assert body['substitute_teacher'] is None
    assert body['substitute_name'] == ''
    assert body['effective_substitution_source'] == ''


def test_admin_no_puede_asignar_suplente_titular_inactivo_o_otra_org(api_client, setup, other_org):
    inactive = setup['substitute']
    inactive.is_active = False
    inactive.save(update_fields=['is_active'])
    _login(api_client, setup['admin'])

    own = api_client.post(
        CLASSES_URL,
        _class_payload(setup, has_substitute=True, substitute_teacher=setup['teacher'].id),
        format='json',
    )
    inactive_resp = api_client.post(
        CLASSES_URL,
        _class_payload(setup, name='Inactivo', has_substitute=True, substitute_teacher=inactive.id),
        format='json',
    )
    foreign = api_client.post(
        CLASSES_URL,
        _class_payload(setup, name='Ajeno', has_substitute=True, substitute_teacher=other_org['substitute'].id),
        format='json',
    )

    assert own.status_code == 400
    assert inactive_resp.status_code == 400
    assert foreign.status_code == 400
    assert 'substitute_teacher' in own.json()
    assert 'substitute_teacher' in inactive_resp.json()
    assert 'substitute_teacher' in foreign.json()


def test_profesor_toma_clase_de_otro_profesor(api_client, setup):
    gym_class = _make_class(setup)
    _login(api_client, setup['substitute'])

    resp = api_client.post(f"{CLASSES_URL}{gym_class.id}/claim-substitution/", format='json')

    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body['has_substitute'] is True
    assert body['substitute_teacher'] == setup['substitute'].id
    assert body['substitute_name'] == ''
    assert body['effective_substitution_source'] == GymClass.SubstitutionSource.TEACHER_CLAIMED
    gym_class.refresh_from_db()
    assert gym_class.teacher_id == setup['teacher'].id
    assert gym_class.substitute_teacher_id == setup['substitute'].id
    assert gym_class.substitution_assigned_by_id == setup['substitute'].id
    assert gym_class.substitution_assigned_at is not None


def test_profesor_suelta_suplencia_tomada_por_el(api_client, setup):
    gym_class = _make_class(setup)
    _login(api_client, setup['substitute'])
    claim = api_client.post(f"{CLASSES_URL}{gym_class.id}/claim-substitution/", format='json')
    assert claim.status_code == 200, claim.content

    resp = api_client.post(f"{CLASSES_URL}{gym_class.id}/release-substitution/", format='json')

    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body['has_substitute'] is False
    assert body['substitute_teacher'] is None
    assert body['substitute_name'] == ''
    assert body['effective_substitution_source'] == ''
    gym_class.refresh_from_db()
    assert gym_class.has_substitute is False
    assert gym_class.substitute_teacher_id is None
    assert gym_class.substitution_source == ''
    assert gym_class.substitution_assigned_by_id is None
    assert gym_class.substitution_assigned_at is None


def test_profesor_suelta_suplencia_registrada_asignada_a_el(api_client, setup):
    gym_class = _make_class(
        setup,
        has_substitute=True,
        substitute_teacher=setup['substitute'],
        substitution_source=GymClass.SubstitutionSource.ADMIN_ASSIGNED,
        substitution_assigned_by=setup['admin'],
        substitution_assigned_at=timezone.now(),
    )
    _login(api_client, setup['substitute'])

    resp = api_client.post(f"{CLASSES_URL}{gym_class.id}/release-substitution/", format='json')

    assert resp.status_code == 200, resp.content
    gym_class.refresh_from_db()
    assert gym_class.has_substitute is False
    assert gym_class.substitute_teacher_id is None
    assert gym_class.substitution_source == ''


def test_profesor_no_suelta_suplencia_de_otro(api_client, setup, make_user):
    gym_class = _make_class(setup)
    another = make_user('another-release-sub', organization=setup['org'], role='teacher')
    _login(api_client, setup['substitute'])
    claim = api_client.post(f"{CLASSES_URL}{gym_class.id}/claim-substitution/", format='json')
    assert claim.status_code == 200, claim.content
    _login(api_client, another)

    resp = api_client.post(f"{CLASSES_URL}{gym_class.id}/release-substitution/", format='json')

    assert resp.status_code == 400, resp.content
    gym_class.refresh_from_db()
    assert gym_class.substitute_teacher_id == setup['substitute'].id


def test_profesor_no_toma_propia_ajena_inactiva_pasada_ni_ya_suplida(api_client, setup, other_org):
    own = _make_class(setup, teacher=setup['substitute'])
    foreign = _make_class(other_org)
    past = _make_class(setup, start=timezone.now() - timedelta(days=1))
    covered = _make_class(setup, has_substitute=True, substitute_name='Marcela Rios')
    _login(api_client, setup['substitute'])

    assert api_client.post(f"{CLASSES_URL}{own.id}/claim-substitution/").status_code == 400
    assert api_client.post(f"{CLASSES_URL}{foreign.id}/claim-substitution/").status_code == 404
    assert api_client.post(f"{CLASSES_URL}{past.id}/claim-substitution/").status_code == 400
    assert api_client.post(f"{CLASSES_URL}{covered.id}/claim-substitution/").status_code == 400

    inactive = setup['substitute']
    inactive.is_active = False
    inactive.save(update_fields=['is_active'])
    api_client.force_authenticate(user=inactive)
    assert api_client.post(f"{CLASSES_URL}{_make_class(setup).id}/claim-substitution/").status_code == 403


def test_profesor_no_toma_suplencia_con_conflicto_horario(api_client, setup):
    start = timezone.now() + timedelta(days=1)
    target = _make_class(setup, start=start)
    _make_class(setup, teacher=setup['substitute'], start=start + timedelta(minutes=15), name='Conflicto')
    _login(api_client, setup['substitute'])

    resp = api_client.post(f"{CLASSES_URL}{target.id}/claim-substitution/")

    assert resp.status_code == 400, resp.content
    assert 'horario' in resp.json()['detail']


def test_dos_profesores_no_sobrescriben_la_misma_suplencia(api_client, setup, make_user):
    gym_class = _make_class(setup)
    another = make_user('another-reg-sub', organization=setup['org'], role='teacher')
    _login(api_client, setup['substitute'])
    first = api_client.post(f"{CLASSES_URL}{gym_class.id}/claim-substitution/")
    _login(api_client, another)
    second = api_client.post(f"{CLASSES_URL}{gym_class.id}/claim-substitution/")

    assert first.status_code == 200, first.content
    assert second.status_code == 400, second.content
    gym_class.refresh_from_db()
    assert gym_class.substitute_teacher_id == setup['substitute'].id


def test_suplencia_puntual_no_modifica_template_ni_futuras_clases(api_client, setup):
    today = timezone.localdate() + timedelta(days=1)
    template = ClassTemplate.objects.create(
        organization=setup['org'],
        branch=setup['branch'],
        teacher=setup['teacher'],
        class_type=setup['class_type'],
        discipline=setup['discipline'],
        name='Serie',
        weekday=today.weekday(),
        start_time='10:00',
        end_time='11:00',
        capacity=10,
        start_date=today,
    )
    claimed = _make_class(setup, class_template=template, start=timezone.now() + timedelta(days=1))
    future = _make_class(setup, class_template=template, start=timezone.now() + timedelta(days=8))
    _login(api_client, setup['substitute'])

    resp = api_client.post(f"{CLASSES_URL}{claimed.id}/claim-substitution/")

    assert resp.status_code == 200, resp.content
    template.refresh_from_db()
    future.refresh_from_db()
    assert template.has_substitute is False
    assert template.substitute_teacher_id is None
    assert future.has_substitute is False
    assert future.substitute_teacher_id is None


def test_template_admin_registrado_se_materializa_en_instancias_nuevas(api_client, setup):
    _login(api_client, setup['admin'])
    tomorrow = timezone.localdate() + timedelta(days=1)

    resp = api_client.post(
        TEMPLATES_URL,
        {
            'name': 'Serie suplente registrado',
            'branch': setup['branch'].id,
            'teacher': setup['teacher'].id,
            'class_type': setup['class_type'].id,
            'discipline': setup['discipline'].id,
            'weekday': tomorrow.weekday(),
            'start_time': '10:00',
            'end_time': '11:00',
            'capacity': 10,
            'has_substitute': True,
            'substitute_teacher': setup['substitute'].id,
        },
        format='json',
    )

    assert resp.status_code == 201, resp.content
    template = ClassTemplate.objects.get(pk=resp.json()['id'])
    assert template.substitute_teacher_id == setup['substitute'].id
    instances = GymClass.objects.filter(class_template=template)
    assert instances.exists()
    assert set(instances.values_list('substitute_teacher_id', flat=True)) == {setup['substitute'].id}
    assert set(instances.values_list('substitution_source', flat=True)) == {GymClass.SubstitutionSource.ADMIN_ASSIGNED}


def test_pago_sigue_asociado_al_titular_con_suplente_registrado(setup):
    rule = TeacherPaymentRule.objects.create(
        organization=setup['org'],
        payment_type=TeacherPaymentRule.PaymentType.FIXED_PER_CLASS,
        amount=5000,
        is_active=True,
    )
    rule.teachers.add(setup['teacher'])
    gym_class = _make_class(
        setup,
        start=timezone.now() - timedelta(hours=2),
        status=GymClass.Status.COMPLETED,
        has_substitute=True,
        substitute_teacher=setup['substitute'],
        substitution_source=GymClass.SubstitutionSource.ADMIN_ASSIGNED,
    )

    record, _created = calculate_teacher_payment(gym_class)

    assert record is not None
    assert record.teacher_id == setup['teacher'].id
    assert record.teacher_id != setup['substitute'].id

