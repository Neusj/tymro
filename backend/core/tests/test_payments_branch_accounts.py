"""Cuentas de cobro por sucursal (P3.1).

Reglas que se fijan acá:

* Sin ninguna sede marcada, TODO resuelve a la cuenta principal (el comportamiento que
  tiene producción hoy, que no puede cambiar con el deploy).
* Una sede con cuenta propia CONECTADA cobra en su cuenta; desconectada, vuelve a la
  principal.
* La transacción guarda la sede de la membresía y la cuenta EXACTA que emitió el cobro, y
  el webhook valida el `collector_id` contra esa cuenta (no contra "alguna" de la org).
* (Task 2) La sede viaja FIRMADA en el `state` del OAuth, el callback re-valida que sea de
  la organización antes de escribir la fila, y `connect`/`account`/`disconnect` operan
  sobre UNA cuenta identificada por sede — sin `branch_id`, la principal y solo la
  principal.
"""
from datetime import timedelta
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

import pytest
from django.core import signing
from django.db import IntegrityError, transaction as db_tx
from django.utils import timezone

from core.models import Branch, ManualPayment, PaymentAccount, Plan, StudentPlan
from core.services import payments
from core.services.manual_payments import record_manual_payment
from core.services.providers import get_payment_provider
from core.services.providers.base import PaymentStatus
from core.services.providers.fake import FakePaymentProvider


@pytest.fixture(autouse=True)
def _fake(settings):
    settings.PAYMENTS_PROVIDER = 'fake'
    settings.PAYMENTS_ENCRYPTION_KEY = __import__(
        'core.fields', fromlist=['generate_encryption_key']).generate_encryption_key()
    settings.PAYMENTS_APEX_BASE_URL = 'https://app.tymroapp.com'


@pytest.fixture
def connected_org(make_organization):
    """Organización con su cuenta PRINCIPAL conectada (collector `fake-collector`)."""
    org = make_organization()
    payments.connect_callback(code='C', state=payments._sign_state(org.id))
    return org


def _branch(org, name='Centro'):
    return Branch.objects.create(organization=org, name=name)


def _branch_account(org, branch, *, collector='branch-collector', status=None):
    """Cuenta de sede conectada. Se crea a mano porque el flujo `connect` por sede lo
    agrega la Task 2; acá solo importa la fila y su `provider_user_id`."""
    return PaymentAccount.objects.create(
        organization=org, branch=branch, provider='fake', provider_user_id=collector,
        access_token='branch-access', refresh_token='branch-refresh',
        token_expires_at=timezone.now() + timedelta(days=180),
        status=status or PaymentAccount.STATUS_CONNECTED,
    )


def _plan(org, *, branch=None, name='Mensual', price=30000.0):
    return Plan.objects.create(organization=org, name=name, plan_type='monthly',
                               total_classes=12, unlimited_classes=False, duration_days=30,
                               price=price, discount_percentage=0, branch=branch)


def _main_account(org):
    return PaymentAccount.objects.get(organization=org, branch__isnull=True, provider='fake')


def _state_of(authorization_url):
    """El `state` firmado que viaja en la URL de autorización que se le da al navegador."""
    return parse_qs(urlsplit(authorization_url).query)['state'][0]


# --- resolución de cuenta -----------------------------------------------------------

def test_org_without_branch_accounts_uses_main(connected_org, make_user):
    """Comportamiento de hoy intacto: sin cuentas de sede todo cobra en la principal."""
    org = connected_org
    student = make_user('stu-main', organization=org, role='student')
    plan = _plan(org, branch=_branch(org))

    tx, _ = payments.create_checkout(organization=org, user=student, plan=plan)

    assert tx.payment_account_id == _main_account(org).id
    assert tx.branch_id == plan.branch_id      # la sede queda registrada igual


def test_plan_of_branch_with_own_account_charges_that_account(connected_org, make_user):
    org = connected_org
    branch = _branch(org)
    account = _branch_account(org, branch)
    student = make_user('stu-b', organization=org, role='student')
    plan = _plan(org, branch=branch)

    tx, _ = payments.create_checkout(organization=org, user=student, plan=plan)

    assert tx.payment_account_id == account.id
    assert tx.branch_id == branch.id
    assert tx.payment_account.provider_user_id == 'branch-collector'


def test_plan_of_other_branch_falls_back_to_main(connected_org, make_user):
    org = connected_org
    with_account = _branch(org, 'Con cuenta')
    _branch_account(org, with_account)
    without_account = _branch(org, 'Sin cuenta')
    student = make_user('stu-o', organization=org, role='student')
    plan = _plan(org, branch=without_account)

    tx, _ = payments.create_checkout(organization=org, user=student, plan=plan)

    assert tx.payment_account_id == _main_account(org).id
    assert tx.branch_id == without_account.id


def test_global_plan_uses_main_account(connected_org, make_user):
    org = connected_org
    _branch_account(org, _branch(org))
    student = make_user('stu-g', organization=org, role='student')
    plan = _plan(org, branch=None)          # plan global (todas las sedes)

    tx, _ = payments.create_checkout(organization=org, user=student, plan=plan)

    assert tx.payment_account_id == _main_account(org).id
    assert tx.branch_id is None


def test_enrollment_fee_uses_branch_account_of_membership(connected_org, make_user):
    org = connected_org
    branch = _branch(org)
    account = _branch_account(org, branch)
    student = make_user('stu-e', organization=org, role='student')
    plan = _plan(org, branch=branch, price=1000.0)
    sp = StudentPlan.objects.create(user=student, plan=plan, organization_id=org.id,
                                    branch=branch, start_date='2026-07-01',
                                    end_date='2026-07-30', total_classes=1,
                                    enrollment_fee=Decimal('20000'))

    tx, _ = payments.create_checkout(organization=org, user=student, target_student_plan=sp)

    assert tx.payment_account_id == account.id
    assert tx.branch_id == branch.id
    assert tx.enrollment_fee_amount == Decimal('20000')


def test_disconnected_branch_account_falls_back_to_main(connected_org, make_user):
    """La sede 'dejó de tener cuenta propia' hasta reconectar: el gym sigue cobrando."""
    org = connected_org
    branch = _branch(org)
    _branch_account(org, branch, status=PaymentAccount.STATUS_DISCONNECTED)
    student = make_user('stu-d', organization=org, role='student')
    plan = _plan(org, branch=branch)

    tx, _ = payments.create_checkout(organization=org, user=student, plan=plan)

    assert tx.payment_account_id == _main_account(org).id


def test_branch_account_of_other_org_never_resolves(connected_org, make_organization,
                                                    make_user):
    """Multitenancy: la cuenta de sede de otra organización no puede cobrar acá."""
    org = connected_org
    other = make_organization()
    other_branch = _branch(other, 'Ajena')
    _branch_account(other, other_branch, collector='otro-collector')
    student = make_user('stu-x', organization=org, role='student')
    plan = _plan(org, branch=_branch(org))

    tx, _ = payments.create_checkout(organization=org, user=student, plan=plan)

    assert tx.payment_account_id == _main_account(org).id


def test_resolve_rejects_branch_from_another_org(connected_org, make_organization):
    """Defensa en profundidad: los callers ya validan pertenencia antes de llamar."""
    org = connected_org
    other = make_organization()
    foreign_branch = _branch(other, 'Ajena')

    with pytest.raises(payments.CheckoutError):
        payments.resolve_payment_account(organization=org, branch=foreign_branch)


def test_resolve_without_any_account_returns_none(make_organization):
    org = make_organization()   # sin conectar
    assert payments.resolve_payment_account(organization=org, branch=_branch(org)) is None


def test_checkout_without_any_account_still_raises_not_connected(make_organization, make_user):
    org = make_organization()
    student = make_user('stu-nc', organization=org, role='student')
    plan = _plan(org, branch=_branch(org))
    with pytest.raises(payments.NotConnected):
        payments.create_checkout(organization=org, user=student, plan=plan)


# --- constraints de unicidad --------------------------------------------------------

def test_only_one_main_account_per_org_and_provider(connected_org):
    org = connected_org
    with pytest.raises(IntegrityError):
        with db_tx.atomic():
            PaymentAccount.objects.create(organization=org, provider='fake',
                                          provider_user_id='dup', access_token='a',
                                          refresh_token='b')


def test_main_plus_branch_accounts_coexist(connected_org):
    org = connected_org
    first = _branch(org, 'Sede 1')
    second = _branch(org, 'Sede 2')

    _branch_account(org, first, collector='c1')
    _branch_account(org, second, collector='c2')

    assert PaymentAccount.objects.filter(organization=org, provider='fake').count() == 3


def test_only_one_account_per_branch_and_provider(connected_org):
    org = connected_org
    branch = _branch(org)
    _branch_account(org, branch)
    with pytest.raises(IntegrityError):
        with db_tx.atomic():
            _branch_account(org, branch, collector='otro')


# --- webhook: el collector se valida contra la cuenta del checkout -------------------

def test_webhook_validates_collector_of_branch_account(connected_org, make_user):
    org = connected_org
    branch = _branch(org)
    _branch_account(org, branch)
    student = make_user('stu-w1', organization=org, role='student')
    plan = _plan(org, branch=branch)
    tx, _ = payments.create_checkout(organization=org, user=student, plan=plan)

    get_payment_provider().queue_payment(
        external_reference=str(tx.id), status=PaymentStatus.APPROVED,
        amount=Decimal('30000'), provider_payment_id='PAYB',
        collector_id='branch-collector')

    payments.process_payment_notification(tx_id=str(tx.id), provider_payment_id='PAYB')

    tx.refresh_from_db()
    assert tx.status == 'approved'
    assert tx.processed_at is not None


def test_webhook_rejects_main_collector_on_branch_transaction(connected_org, make_user):
    """El cobro salió por la cuenta de la sede: un pago cobrado por la principal sobre esa
    transacción es una inconsistencia (o una forja), no un pago válido."""
    org = connected_org
    branch = _branch(org)
    _branch_account(org, branch)
    student = make_user('stu-w2', organization=org, role='student')
    plan = _plan(org, branch=branch)
    tx, _ = payments.create_checkout(organization=org, user=student, plan=plan)

    get_payment_provider().queue_payment(
        external_reference=str(tx.id), status=PaymentStatus.APPROVED,
        amount=Decimal('30000'), provider_payment_id='PAYM',
        collector_id='fake-collector')          # el de la cuenta PRINCIPAL

    with pytest.raises(payments.PaymentIntegrityError):
        payments.process_payment_notification(tx_id=str(tx.id), provider_payment_id='PAYM')

    tx.refresh_from_db()
    assert tx.processed_at is None


def test_webhook_legacy_transaction_validates_against_main(connected_org, make_user):
    """Filas anteriores a la migración: `payment_account` NULL → vale la principal."""
    org = connected_org
    student = make_user('stu-w3', organization=org, role='student')
    plan = _plan(org)
    tx, _ = payments.create_checkout(organization=org, user=student, plan=plan)
    tx.payment_account = None                   # como si la hubiera creado el código viejo
    tx.save(update_fields=['payment_account'])
    # Aunque exista una cuenta de sede, el fallback legacy es SOLO la principal.
    _branch_account(org, _branch(org))

    get_payment_provider().queue_payment(
        external_reference=str(tx.id), status=PaymentStatus.APPROVED,
        amount=Decimal('30000'), provider_payment_id='PAYL',
        collector_id='fake-collector')

    payments.process_payment_notification(tx_id=str(tx.id), provider_payment_id='PAYL')

    tx.refresh_from_db()
    assert tx.status == 'approved'
    assert tx.processed_at is not None


def test_webhook_aborts_when_branch_account_was_disconnected(connected_org, make_user):
    """Desconectar la cuenta de la sede después del checkout: se ackea sin consultar a MP
    (con el token de otra cuenta el fetch fallaría). No se cae a la principal."""
    org = connected_org
    branch = _branch(org)
    account = _branch_account(org, branch)
    student = make_user('stu-w4', organization=org, role='student')
    plan = _plan(org, branch=branch)
    tx, _ = payments.create_checkout(organization=org, user=student, plan=plan)
    payments.disconnect_account(account)

    get_payment_provider().queue_payment(
        external_reference=str(tx.id), status=PaymentStatus.APPROVED,
        amount=Decimal('30000'), provider_payment_id='PAYD',
        collector_id='branch-collector')

    assert payments.process_payment_notification(
        tx_id=str(tx.id), provider_payment_id='PAYD') is None
    tx.refresh_from_db()
    assert tx.processed_at is None


def test_the_preference_is_emitted_with_the_token_of_the_branch_account(
        connected_org, make_user, monkeypatch):
    """El cierre del círculo: no alcanza con que la transacción APUNTE a la cuenta de la
    sede, la preference tiene que emitirse con el `access_token` de ESA cuenta. Si se
    emitiera con el de la principal, el cobro entraría en el MercadoPago equivocado y todo
    lo demás (el `payment_account` estampado, la validación de collector) sería decorativo.
    """
    org = connected_org
    branch = _branch(org)
    _branch_account(org, branch)                      # access_token 'branch-access'
    student = make_user('stu-tok', organization=org, role='student')
    plan = _plan(org, branch=branch)
    seen = []
    original = FakePaymentProvider.create_checkout

    def _spy(self, *, access_token, **kwargs):
        seen.append(access_token)
        return original(self, access_token=access_token, **kwargs)

    monkeypatch.setattr(FakePaymentProvider, 'create_checkout', _spy)

    payments.create_checkout(organization=org, user=student, plan=plan)

    assert seen == ['branch-access'], 'la preference se emitió con el token de otra cuenta'


def test_the_preference_of_a_global_plan_uses_the_main_token(connected_org, make_user,
                                                             monkeypatch):
    """La otra mitad del test de arriba: con una cuenta de sede existiendo, un plan global
    sigue emitiéndose con el token de la PRINCIPAL."""
    org = connected_org
    _branch_account(org, _branch(org))
    student = make_user('stu-tok2', organization=org, role='student')
    seen = []
    original = FakePaymentProvider.create_checkout

    def _spy(self, *, access_token, **kwargs):
        seen.append(access_token)
        return original(self, access_token=access_token, **kwargs)

    monkeypatch.setattr(FakePaymentProvider, 'create_checkout', _spy)

    payments.create_checkout(organization=org, user=student, plan=_plan(org, branch=None))

    assert seen == ['fake-access']                    # el de `connect_callback`


# --- el `state` firmado lleva la sede ------------------------------------------------

def test_the_signed_state_round_trips_the_branch(make_organization):
    org = make_organization()
    branch = _branch(org)

    org_id, branch_id = payments._load_state(payments._sign_state(org.id, branch.id))

    assert (org_id, branch_id) == (org.id, branch.id)


def test_a_state_without_the_branch_key_is_still_valid(make_organization):
    """COMPATIBILIDAD DEL DEPLOY: los states emitidos por el código anterior siguen en vuelo
    hasta `STATE_MAX_AGE` después de publicar y no traen la clave `branch`. Tienen que
    seguir valiendo, y significar "cuenta principal", no reventar con KeyError (500) en la
    cara del gym_admin que apretó "conectar" un minuto antes del deploy."""
    org = make_organization()
    legacy = signing.dumps({'org': org.id}, salt=payments.STATE_SALT)   # formato viejo

    org_id, branch_id = payments._load_state(legacy)

    assert (org_id, branch_id) == (org.id, None)
    # Y el callback lo procesa creando/actualizando la cuenta PRINCIPAL.
    account = payments.connect_callback(code='C', state=legacy)
    assert account.branch_id is None


def test_organization_from_state_still_works_with_a_branch_state(make_organization):
    """El callback resuelve la org del state para saber a qué subdominio volver; agregarle
    la sede no puede romper eso."""
    org = make_organization()
    state = payments._sign_state(org.id, _branch(org).id)

    assert payments.organization_from_state(state).id == org.id


def test_build_connect_url_puts_the_branch_in_the_state(make_organization):
    org = make_organization()
    branch = _branch(org)

    url = payments.build_connect_url(organization=org, branch=branch)

    assert payments._load_state(_state_of(url)) == (org.id, branch.id)


def test_build_connect_url_without_branch_means_the_main_account(make_organization):
    org = make_organization()

    url = payments.build_connect_url(organization=org)

    assert payments._load_state(_state_of(url)) == (org.id, None)


# --- callback OAuth: crea la cuenta de la sede (y NO la de otra org) -----------------

def test_the_callback_creates_the_account_of_the_branch_in_the_state(make_organization):
    org = make_organization()
    branch = _branch(org)

    account = payments.connect_callback(
        code='C', state=payments._sign_state(org.id, branch.id))

    assert account.branch_id == branch.id
    assert account.organization_id == org.id
    assert account.status == PaymentAccount.STATUS_CONNECTED
    assert account.access_token == 'fake-access'
    # La principal NO se crea de rebote: conectar una sede no conecta la organización.
    assert not PaymentAccount.objects.filter(organization=org, branch__isnull=True).exists()


def test_reconnecting_the_same_branch_updates_the_row_instead_of_duplicating(
        make_organization):
    org = make_organization()
    branch = _branch(org)
    first = payments.connect_callback(code='C', state=payments._sign_state(org.id, branch.id))
    payments.disconnect_account(first)

    second = payments.connect_callback(code='C', state=payments._sign_state(org.id, branch.id))

    assert second.pk == first.pk
    assert second.status == PaymentAccount.STATUS_CONNECTED
    assert PaymentAccount.objects.filter(organization=org, branch=branch).count() == 1


def test_reconnecting_the_main_account_with_branch_accounts_does_not_explode(connected_org):
    """REGRESIÓN del bloqueante: con `branch` fuera del lookup del `update_or_create`, el
    `get` interno matcheaba TODAS las cuentas de la organización y esto reventaba con
    `MultipleObjectsReturned` (500) en cuanto existiera UNA cuenta de sede. Reconectar la
    principal tiene que seguir siendo un upsert sobre la principal."""
    org = connected_org
    main = _main_account(org)
    branch_account = _branch_account(org, _branch(org))

    again = payments.connect_callback(code='C', state=payments._sign_state(org.id))

    assert again.pk == main.pk
    assert again.branch_id is None
    assert again.status == PaymentAccount.STATUS_CONNECTED
    # La cuenta de la sede quedó intacta: reconectar la principal no la toca.
    branch_account.refresh_from_db()
    assert branch_account.status == PaymentAccount.STATUS_CONNECTED
    assert branch_account.access_token == 'branch-access'
    assert PaymentAccount.objects.filter(organization=org).count() == 2


def test_the_callback_rejects_a_branch_of_another_organization(make_organization):
    """LA guarda del lado escritor: `connect_callback` es el único código que crea filas de
    `PaymentAccount`, y nada a nivel de modelo impide colgar una cuenta de una sede ajena.
    El state se forja acá a nivel servicio (firmado y todo) para probar la guarda sin
    depender del 404 de la view."""
    org = make_organization()
    other = make_organization()
    foreign_branch = _branch(other, 'Ajena')
    forged = payments._sign_state(org.id, foreign_branch.id)

    with pytest.raises(payments.InvalidState):
        payments.connect_callback(code='C', state=forged)

    assert not PaymentAccount.objects.exists()


def test_the_callback_rejects_a_nonexistent_branch(make_organization):
    org = make_organization()

    with pytest.raises(payments.InvalidState):
        payments.connect_callback(code='C', state=payments._sign_state(org.id, 10 ** 9))

    assert not PaymentAccount.objects.exists()


# --- API: POST /api/payments/connect/ -----------------------------------------------

def test_connect_with_an_own_branch_returns_a_url_whose_state_carries_it(
        api_client, connected_org, make_user):
    org = connected_org                      # con la cuenta PRINCIPAL ya conectada
    branch = _branch(org)
    admin = make_user('adm-c1', organization=org, role='gym_admin')
    api_client.force_authenticate(user=admin)

    resp = api_client.post('/api/payments/connect/', {'branch_id': branch.id}, format='json')

    assert resp.status_code == 200, resp.content
    assert payments._load_state(_state_of(resp.data['authorization_url'])) == (org.id, branch.id)


def test_connect_of_a_branch_without_a_main_account_is_a_conflict(api_client,
                                                                 make_organization,
                                                                 make_user):
    """La cuenta principal es el PISO: cobra los planes globales y toda sede sin cuenta
    propia. Si un gimnasio conectara PRIMERO una sede, tendría un MercadoPago vivo y a la vez
    todo lo demás resolviendo a `NotConnected` —alumnos con "el gimnasio no tiene pagos
    habilitados" en una organización recién conectada—. Trampa de onboarding vista en
    producción; el flujo se corta acá, sin dejar nada escrito."""
    org = make_organization()                # SIN cuenta principal
    branch = _branch(org)
    admin = make_user('adm-c7', organization=org, role='gym_admin')
    api_client.force_authenticate(user=admin)

    resp = api_client.post('/api/payments/connect/', {'branch_id': branch.id}, format='json')

    assert resp.status_code == 409, resp.content
    assert 'principal' in resp.data['detail'].lower()
    assert not PaymentAccount.objects.exists()


def test_connect_of_a_branch_with_the_main_account_disconnected_is_a_conflict(
        api_client, connected_org, make_user):
    """Una principal DESCONECTADA (fila conservada, tokens vaciados) no cobra nada: para esta
    guarda es lo mismo que no tenerla."""
    org = connected_org
    payments.disconnect_account(_main_account(org))
    branch = _branch(org)
    admin = make_user('adm-c8', organization=org, role='gym_admin')
    api_client.force_authenticate(user=admin)

    resp = api_client.post('/api/payments/connect/', {'branch_id': branch.id}, format='json')

    assert resp.status_code == 409, resp.content
    # Y no se creó la fila de la sede.
    assert not PaymentAccount.objects.filter(branch=branch).exists()


def test_connect_of_the_main_account_never_hits_the_conflict(api_client, make_organization,
                                                            make_user):
    """La guarda es SOLO para sedes: conectar la principal por primera vez —el caso de
    onboarding de siempre— no puede exigirse a sí misma."""
    org = make_organization()
    admin = make_user('adm-c9', organization=org, role='gym_admin')
    api_client.force_authenticate(user=admin)

    resp = api_client.post('/api/payments/connect/')

    assert resp.status_code == 200, resp.content


def test_the_callback_still_connects_a_branch_if_the_main_was_disconnected_meanwhile(
        connected_org):
    """La guarda vive SOLO en `connect`: un state ya emitido pasó por ella, y re-chequear en
    el callback rompería la reconexión de una sede si la principal se desconectó en el medio
    (el gym_admin ya está en MercadoPago autorizando; volver con un error no le deja salida).
    """
    org = connected_org
    branch = _branch(org)
    state = payments._sign_state(org.id, branch.id)
    payments.disconnect_account(_main_account(org))

    account = payments.connect_callback(code='C', state=state)

    assert account.branch_id == branch.id
    assert account.status == PaymentAccount.STATUS_CONNECTED


def test_connect_without_branch_id_behaves_exactly_like_before(api_client, make_organization,
                                                               make_user):
    org = make_organization()
    admin = make_user('adm-c2', organization=org, role='gym_admin')
    api_client.force_authenticate(user=admin)

    resp = api_client.post('/api/payments/connect/')

    assert resp.status_code == 200
    assert payments._load_state(_state_of(resp.data['authorization_url'])) == (org.id, None)


def test_connect_with_a_branch_of_another_organization_is_not_found(api_client,
                                                                   make_organization,
                                                                   make_user):
    """Anti-oráculo: 404 y no 403, para que una sede ajena sea indistinguible de una que no
    existe (los ids de `Branch` son autoincrementales y adivinables).

    La organización va SIN cuenta principal a propósito: así este test también fija el ORDEN
    —la pertenencia corta con 404 ANTES de la guarda de cuenta principal—, o el 409 pasaría a
    ser un oráculo nuevo ("esta sede sí es tuya") para quien prueba ids ajenos."""
    org = make_organization()
    other = make_organization()
    foreign_branch = _branch(other, 'Ajena')
    admin = make_user('adm-c3', organization=org, role='gym_admin')
    api_client.force_authenticate(user=admin)

    resp = api_client.post('/api/payments/connect/', {'branch_id': foreign_branch.id},
                           format='json')

    assert resp.status_code == 404, resp.content


def test_connect_with_a_nonexistent_branch_is_not_found(api_client, make_organization,
                                                        make_user):
    org = make_organization()
    admin = make_user('adm-c4', organization=org, role='gym_admin')
    api_client.force_authenticate(user=admin)

    resp = api_client.post('/api/payments/connect/', {'branch_id': 10 ** 9}, format='json')

    assert resp.status_code == 404


@pytest.mark.parametrize('raw', ['abc', 2 ** 63, -1, 0, 7.9, True, [1], {'a': 1}])
def test_connect_with_a_malformed_branch_id_is_a_400_not_a_500(api_client, make_organization,
                                                               make_user, raw):
    """Un id no numérico o fuera del rango de bigint revienta el `filter(id=...)` en
    PostgreSQL con un 500 que SQLite no reproduce (lección de `_as_id_list`).

    Los casos `7.9` y `True` son los que un `int()` a mano se tragaba EN SILENCIO —operando
    sobre la sede 7 y sobre la sede 1 respectivamente—: pedir una sede y que el servidor
    configure otra es peor que un error."""
    org = make_organization()
    admin = make_user('adm-c5', organization=org, role='gym_admin')
    api_client.force_authenticate(user=admin)

    resp = api_client.post('/api/payments/connect/', {'branch_id': raw}, format='json')

    assert resp.status_code == 400, resp.content
    assert 'branch_id' in resp.data


@pytest.mark.parametrize('raw', ['abc', 7.9, True])
def test_account_and_disconnect_also_reject_a_malformed_branch_id(api_client, connected_org,
                                                                 make_user, raw):
    """Los tres endpoints comparten la misma coerción: el query param de `account` y el body
    de `disconnect` no pueden ser más permisivos que `connect`."""
    org = connected_org
    admin = make_user('adm-c10', organization=org, role='gym_admin')
    api_client.force_authenticate(user=admin)

    assert api_client.get('/api/payments/account/',
                          {'branch_id': raw}).status_code == 400
    assert api_client.post('/api/payments/disconnect/', {'branch_id': raw},
                           format='json').status_code == 400
    # Nada se apagó por el intento malformado.
    assert _main_account(org).status == PaymentAccount.STATUS_CONNECTED


def test_connect_still_rejects_roles_without_permission_before_looking_at_the_branch(
        api_client, make_organization, make_user):
    """Orden 8.3: el rol se chequea ANTES de resolver la sede, así que un alumno recibe 403
    y no un 404 que le confirmaría qué sedes existen."""
    org = make_organization()
    branch = _branch(org)
    student = make_user('stu-c6', organization=org, role='student')
    api_client.force_authenticate(user=student)

    resp = api_client.post('/api/payments/connect/', {'branch_id': branch.id}, format='json')

    assert resp.status_code == 403


# --- API: GET /api/payments/account/ ------------------------------------------------

def test_account_without_branch_id_returns_the_main_even_with_branch_accounts(
        api_client, connected_org, make_user):
    """El `.first()` sin acotar de antes podía devolver la cuenta de CUALQUIER sede."""
    org = connected_org
    _branch_account(org, _branch(org))
    admin = make_user('adm-a1', organization=org, role='gym_admin')
    api_client.force_authenticate(user=admin)

    resp = api_client.get('/api/payments/account/')

    assert resp.status_code == 200
    assert resp.data['branch'] is None
    assert resp.data['provider_user_id'] == 'fake-collector'


def test_account_with_branch_id_returns_that_branch_account(api_client, connected_org,
                                                            make_user):
    org = connected_org
    branch = _branch(org)
    _branch_account(org, branch)
    admin = make_user('adm-a2', organization=org, role='gym_admin')
    api_client.force_authenticate(user=admin)

    resp = api_client.get('/api/payments/account/', {'branch_id': branch.id})

    assert resp.status_code == 200
    assert resp.data['branch'] == branch.id
    assert resp.data['status'] == 'connected'
    assert resp.data['provider_user_id'] == 'branch-collector'


def test_account_of_a_branch_without_account_is_disconnected_not_the_main(
        api_client, connected_org, make_user):
    """Una sede sin cuenta propia responde `disconnected` aunque la organización tenga la
    principal conectada: la pregunta es por ESA sede. (Qué cuenta COBRA por ella es otra
    cosa: para el cobro cae a la principal, ver `resolve_payment_account`.)"""
    org = connected_org
    branch = _branch(org)
    admin = make_user('adm-a3', organization=org, role='gym_admin')
    api_client.force_authenticate(user=admin)

    resp = api_client.get('/api/payments/account/', {'branch_id': branch.id})

    assert resp.status_code == 200
    assert resp.data['status'] == 'disconnected'
    assert resp.data['branch'] == branch.id


def test_account_with_a_branch_of_another_organization_is_not_found(api_client,
                                                                   connected_org,
                                                                   make_organization,
                                                                   make_user):
    org = connected_org
    other = make_organization()
    foreign_branch = _branch(other, 'Ajena')
    _branch_account(other, foreign_branch, collector='otro-collector')
    admin = make_user('adm-a4', organization=org, role='gym_admin')
    api_client.force_authenticate(user=admin)

    resp = api_client.get('/api/payments/account/', {'branch_id': foreign_branch.id})

    assert resp.status_code == 404, resp.content


# --- API: POST /api/payments/disconnect/ --------------------------------------------

def test_disconnect_without_branch_id_only_turns_off_the_main_account(api_client,
                                                                     connected_org,
                                                                     make_user):
    """Sin `branch_id` el endpoint se comporta EXACTAMENTE como hoy: apaga la principal. Sin
    el filtro `branch IS NULL` podía apagar la cuenta de una sede y dejar viva la principal
    —el admin creería haber cortado el cobro de la organización y no cortó nada—."""
    org = connected_org
    branch = _branch(org)
    branch_account = _branch_account(org, branch)
    admin = make_user('adm-d1', organization=org, role='gym_admin')
    api_client.force_authenticate(user=admin)

    resp = api_client.post('/api/payments/disconnect/')

    assert resp.status_code == 200
    assert resp.data['status'] == 'disconnected'
    assert resp.data['branch'] is None
    assert _main_account(org).status == PaymentAccount.STATUS_DISCONNECTED
    branch_account.refresh_from_db()
    assert branch_account.status == PaymentAccount.STATUS_CONNECTED
    assert branch_account.access_token == 'branch-access'


def test_disconnect_with_branch_id_only_turns_off_that_account(api_client, connected_org,
                                                               make_user):
    org = connected_org
    branch = _branch(org)
    other_branch = _branch(org, 'Sede 2')
    branch_account = _branch_account(org, branch)
    other_account = _branch_account(org, other_branch, collector='c2')
    admin = make_user('adm-d2', organization=org, role='gym_admin')
    api_client.force_authenticate(user=admin)

    resp = api_client.post('/api/payments/disconnect/', {'branch_id': branch.id},
                           format='json')

    assert resp.status_code == 200
    assert resp.data['branch'] == branch.id
    branch_account.refresh_from_db()
    assert branch_account.status == PaymentAccount.STATUS_DISCONNECTED
    assert branch_account.access_token in (None, '')
    # Ni la principal ni la otra sede se tocaron.
    assert _main_account(org).status == PaymentAccount.STATUS_CONNECTED
    other_account.refresh_from_db()
    assert other_account.status == PaymentAccount.STATUS_CONNECTED


def test_disconnect_of_a_branch_without_account_is_idempotent(api_client, connected_org,
                                                              make_user):
    org = connected_org
    branch = _branch(org)
    admin = make_user('adm-d3', organization=org, role='gym_admin')
    api_client.force_authenticate(user=admin)

    resp = api_client.post('/api/payments/disconnect/', {'branch_id': branch.id},
                           format='json')

    assert resp.status_code == 200
    assert resp.data['status'] == 'disconnected'
    # No se cayó a la principal: sigue conectada.
    assert _main_account(org).status == PaymentAccount.STATUS_CONNECTED


def test_disconnect_with_a_branch_of_another_organization_is_not_found_and_changes_nothing(
        api_client, connected_org, make_organization, make_user):
    org = connected_org
    other = make_organization()
    foreign_branch = _branch(other, 'Ajena')
    foreign_account = _branch_account(other, foreign_branch, collector='otro-collector')
    admin = make_user('adm-d4', organization=org, role='gym_admin')
    api_client.force_authenticate(user=admin)

    resp = api_client.post('/api/payments/disconnect/', {'branch_id': foreign_branch.id},
                           format='json')

    assert resp.status_code == 404, resp.content
    foreign_account.refresh_from_db()
    assert foreign_account.status == PaymentAccount.STATUS_CONNECTED
    assert foreign_account.access_token == 'branch-access'
    assert _main_account(org).status == PaymentAccount.STATUS_CONNECTED


# --- cobro manual: la sede se estampa desde la membresía ----------------------------

def _membership(org, student, plan, *, branch=None):
    return StudentPlan.objects.create(
        user=student, plan=plan, organization_id=org.id, branch=branch,
        start_date='2026-07-01', end_date='2026-07-30', total_classes=10,
        final_price=30000,
    )


def test_the_manual_payment_stamps_the_branch_of_the_membership(make_organization, make_user):
    org = make_organization()
    branch = _branch(org)
    student = make_user('stu-mp1', organization=org, role='student')
    membership = _membership(org, student, _plan(org, branch=branch), branch=branch)

    payment = record_manual_payment(
        student_plan=membership, amount=Decimal('30000'), reference='',
        recorded_by=None, organization=org)

    assert payment.branch_id == branch.id


def test_the_manual_payment_of_a_global_membership_has_no_branch(make_organization, make_user):
    org = make_organization()
    student = make_user('stu-mp2', organization=org, role='student')
    membership = _membership(org, student, _plan(org, branch=None))

    payment = record_manual_payment(
        student_plan=membership, amount=Decimal('30000'), reference='',
        recorded_by=None, organization=org)

    assert payment.branch_id is None


def test_deleting_the_branch_keeps_the_manual_payment(make_organization, make_user):
    """`SET_NULL` y no CASCADE: la sucursal es un dato de contexto del cobro, no su razón de
    existir. Perder la sede no puede des-pagar una membresía.

    El plan es GLOBAL a propósito: `Plan.branch` es RESTRICT, así que un plan exclusivo de
    esa sede bloquearía el `delete()` y el test no llegaría a ejercer este `SET_NULL`."""
    org = make_organization()
    branch = _branch(org)
    student = make_user('stu-mp3', organization=org, role='student')
    membership = _membership(org, student, _plan(org, branch=None), branch=branch)
    payment = record_manual_payment(
        student_plan=membership, amount=Decimal('30000'), reference='',
        recorded_by=None, organization=org)

    branch.delete()

    payment.refresh_from_db()
    assert ManualPayment.objects.filter(pk=payment.pk).exists()
    assert payment.branch_id is None
