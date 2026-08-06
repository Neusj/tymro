"""`ManualPayment` — cobro registrado a mano por el gimnasio (8.2).

`test_plan_payment_status.py` ya fija que la EXISTENCIA de una fila de `ManualPayment`
paga la membresia. Este archivo cubre lo que ese no cubre: las reglas propias del modelo
(coherencia de organizacion, monto positivo), el servicio `record_manual_payment` que es
la unica puerta de escritura, el admin de solo lectura, y el endpoint nuevo
`POST /api/manual-payments/` de punta a punta (rol, aislamiento cross-tenant, forma de la
respuesta y los 400/403/404 del contrato).

Todo lo de aca depende del modelo/servicio/endpoint nuevos, asi que en RED el archivo
entero falla en COLECCION por import inexistente — es lo esperado.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.utils import timezone

from core.admin import ManualPaymentAdmin
from core.models import ManualPayment, Plan, StudentPlan
from core.services.manual_payments import (ManualPaymentOrganizationMismatch,
                                            record_manual_payment)
from core.services.plans import describe_student_plan

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()
URL = '/api/manual-payments/'
# Segunda puerta de escritura hacia `record_manual_payment` (sección C): el instrumento de
# cobro (P3.2) también viaja por acá, bajo `payment.manual_method`.
ASSIGN_URL = '/api/plans/assign/'


def _plan(org, name='Pack', total_classes=10, unlimited=False, price=30000):
    return Plan.objects.create(
        organization=org, name=name, plan_type='pack',
        total_classes=total_classes, unlimited_classes=unlimited,
        duration_days=30, price=price,
    )


def _membership(student, plan, *, start_offset=-1, end_offset=20, classes_used=0,
                is_active=True, enrollment_fee=0, enrollment_fee_paid_at=None,
                final_price=30000):
    return StudentPlan.objects.create(
        user=student, plan=plan, organization_id=plan.organization_id,
        start_date=TODAY + timedelta(days=start_offset),
        end_date=TODAY + timedelta(days=end_offset),
        total_classes=plan.total_classes, unlimited_classes=plan.unlimited_classes,
        classes_used=classes_used, final_price=final_price, is_active=is_active,
        enrollment_fee=enrollment_fee, enrollment_fee_paid_at=enrollment_fee_paid_at,
    )


# --------------------------------------------------------------------------------------
# A. Modelo y servicio
# --------------------------------------------------------------------------------------

def test_the_model_rejects_a_payment_whose_membership_is_from_another_organization(
        make_organization, make_user):
    """Espejo de `StudentPlan.clean()`: la organizacion de la fila tiene que ser la misma
    que la de la membresia, o un cobro de la org B le declararia pagada una deuda de la
    org A."""
    org_a = make_organization()
    org_b = make_organization()
    student = make_user('stu-a', organization=org_a, role='student')
    membership_a = _membership(student, _plan(org_a))
    payment = ManualPayment(organization=org_b, student_plan=membership_a, amount=1000)

    with pytest.raises(ValidationError) as excinfo:
        payment.full_clean()

    assert 'organization' in excinfo.value.message_dict


@pytest.mark.parametrize('amount', [0, -1])
def test_the_model_rejects_a_non_positive_amount(make_organization, make_user, amount):
    """`amount` tiene que ser mayor a cero: un cobro de 0 o negativo no es un cobro."""
    org = make_organization()
    student = make_user('stu-b', organization=org, role='student')
    membership = _membership(student, _plan(org))
    payment = ManualPayment(organization=org, student_plan=membership, amount=amount)

    with pytest.raises(ValidationError) as excinfo:
        payment.full_clean()

    assert 'amount' in excinfo.value.message_dict


def test_the_service_refuses_a_cross_organization_record(make_organization, make_user):
    """El servicio vuelve a exigir la coherencia de organizacion aunque el llamador ya la
    haya validado: es LA puerta de escritura y va a tener mas de un llamador."""
    org_a = make_organization()
    org_b = make_organization()
    student = make_user('stu-c', organization=org_a, role='student')
    membership = _membership(student, _plan(org_a))

    with pytest.raises(ManualPaymentOrganizationMismatch):
        record_manual_payment(
            student_plan=membership, amount=Decimal('1000'), method=ManualPayment.METHOD_CASH,
            reference='', recorded_by=None, organization=org_b,
        )

    assert ManualPayment.objects.count() == 0


def test_the_service_stamps_the_actor_and_the_organization(make_organization, make_user):
    org = make_organization()
    student = make_user('stu-d', organization=org, role='student')
    admin_user = make_user('admin-d', organization=org, role='gym_admin')
    membership = _membership(student, _plan(org))

    payment = record_manual_payment(
        student_plan=membership, amount=Decimal('1000'), method=ManualPayment.METHOD_TRANSFER,
        reference='TRX-1', recorded_by=admin_user, organization=org,
    )

    assert payment.organization_id == org.id
    assert payment.recorded_by_id == admin_user.id
    assert payment.recorded_at is not None


def test_recording_with_an_empty_method_is_rejected(make_organization, make_user):
    """Cierra el hallazgo BAJO de P3.2: el kwarg `method` de `record_manual_payment` es
    REQUERIDO, pero eso solo fuerza a PASAR algo, no a pasar algo VÁLIDO. `method=''` no lo
    frena `clean_fields()` porque el campo es `blank=True` (necesario para las filas legacy
    de 8.2/8.3), así que sin el corte de `ManualPayment.clean()` esta llamada crearía una
    fila NUEVA indistinguible de esas filas viejas. El corte tiene que ser `ValidationError`
    -el mismo tipo que ya usan `amount` y `organization`- y la fila no debe quedar creada."""
    org = make_organization()
    student = make_user('stu-method-empty', organization=org, role='student')
    membership = _membership(student, _plan(org))

    with pytest.raises(ValidationError) as excinfo:
        record_manual_payment(
            student_plan=membership, amount=Decimal('1000'), method='',
            reference='', recorded_by=None, organization=org,
        )

    assert 'method' in excinfo.value.message_dict
    assert ManualPayment.objects.count() == 0


def test_recording_with_a_none_method_is_rejected_not_a_500(make_organization, make_user):
    """Mismo agujero que el test anterior pero por el lado de `None`: sin la guarda en
    `clean()`, `method=None` ni siquiera llega a `ValidationError` -pasa de largo
    `clean_fields()` igual que `''` y revienta en el INSERT como `IntegrityError` (la
    columna es `NOT NULL` en la base), es decir un 500 en vez de un 400 si algún caller
    futuro (la carga histórica de CSV, p.ej.) no valida antes de llamar al servicio."""
    org = make_organization()
    student = make_user('stu-method-none', organization=org, role='student')
    membership = _membership(student, _plan(org))

    with pytest.raises(ValidationError) as excinfo:
        record_manual_payment(
            student_plan=membership, amount=Decimal('1000'), method=None,
            reference='', recorded_by=None, organization=org,
        )

    assert 'method' in excinfo.value.message_dict
    assert ManualPayment.objects.count() == 0


def test_a_legacy_row_with_an_empty_method_can_still_be_saved(make_organization, make_user):
    """ES el test que protege producción: las filas de 8.2/8.3 ya viven en la base con
    `method=''` y tienen que poder pasar por `full_clean()` de nuevo -una corrección de
    `reference`, por ejemplo- sin que la guarda nueva las rompa. Se simula la fila legacy
    con un `.update()` (saltea `clean()`/`save()` a propósito, como haría una fila que ya
    estaba ahí antes de este código) y se recarga con `.get()` para que
    `self._state.adding` sea `False`, igual que cualquier fila leída de la base."""
    org = make_organization()
    student = make_user('stu-method-legacy', organization=org, role='student')
    membership = _membership(student, _plan(org))
    payment = record_manual_payment(
        student_plan=membership, amount=Decimal('1000'), method=ManualPayment.METHOD_CASH,
        reference='', recorded_by=None, organization=org,
    )
    ManualPayment.objects.filter(pk=payment.pk).update(method='')
    legacy_payment = ManualPayment.objects.get(pk=payment.pk)

    legacy_payment.full_clean()  # no debe levantar ValidationError

    assert legacy_payment.method == ''


def test_deleting_the_recorder_keeps_the_payment_and_the_paid_status(make_organization,
                                                                     make_user):
    """ES el test de la decision `SET_NULL`: con CASCADE, borrar al administrador que
    registro el cobro des-pagaria la membresia en silencio."""
    org = make_organization()
    student = make_user('stu-e', organization=org, role='student')
    admin_user = make_user('admin-e', organization=org, role='gym_admin')
    membership = _membership(student, _plan(org), final_price=30000)
    payment = record_manual_payment(
        student_plan=membership, amount=Decimal('30000'), method=ManualPayment.METHOD_CASH,
        reference='', recorded_by=admin_user, organization=org,
    )

    admin_user.delete()

    payment.refresh_from_db()
    assert ManualPayment.objects.filter(pk=payment.pk).exists()
    assert payment.recorded_by is None
    assert describe_student_plan(membership, TODAY).payment_status == 'paid'


def test_several_manual_payments_can_coexist_on_one_membership(make_organization,
                                                                make_user):
    """Sin unicidad a proposito: un gimnasio puede recibir dos abonos por la misma
    membresia y ninguno desplaza al otro."""
    org = make_organization()
    student = make_user('stu-f', organization=org, role='student')
    membership = _membership(student, _plan(org))

    record_manual_payment(student_plan=membership, amount=Decimal('10000'),
                          method=ManualPayment.METHOD_CASH, reference='',
                          recorded_by=None, organization=org)
    record_manual_payment(student_plan=membership, amount=Decimal('20000'),
                          method=ManualPayment.METHOD_TRANSFER, reference='',
                          recorded_by=None, organization=org)

    assert ManualPayment.objects.filter(student_plan=membership).count() == 2


def test_the_admin_is_read_only():
    """Los tres permisos de escritura del admin quedan cerrados: la unica escritura
    valida es el endpoint."""
    admin_instance = ManualPaymentAdmin(ManualPayment, admin.site)

    assert admin_instance.has_add_permission(None) is False
    assert admin_instance.has_change_permission(None) is False
    assert admin_instance.has_delete_permission(None) is False


# --------------------------------------------------------------------------------------
# B. Endpoint POST /api/manual-payments/
# --------------------------------------------------------------------------------------

def test_gym_admin_records_a_manual_payment(api_client, make_organization, make_user):
    """Cobertura #1 (mitad endpoint): el camino feliz completo."""
    org = make_organization()
    student = make_user('stu-g', organization=org, role='student')
    gym_admin = make_user('admin-g', organization=org, role='gym_admin')
    membership = _membership(student, _plan(org))
    api_client.force_authenticate(user=gym_admin)

    resp = api_client.post(URL, {
        'student_plan': membership.id, 'amount': '30000', 'method': 'cash',
        'reference': 'TRX-1',
    }, format='json')

    assert resp.status_code == 201, resp.content
    payment = ManualPayment.objects.get()
    assert payment.organization_id == org.id
    assert payment.recorded_by_id == gym_admin.id
    assert payment.amount == Decimal('30000.00')
    assert payment.method == 'cash'
    assert payment.reference == 'TRX-1'


def test_recording_a_manual_payment_flips_the_membership_to_paid(api_client,
                                                                  make_organization,
                                                                  make_user):
    """Cobertura #1: amarra endpoint y derivacion de punta a punta."""
    org = make_organization()
    student = make_user('stu-h', organization=org, role='student')
    gym_admin = make_user('admin-h', organization=org, role='gym_admin')
    plan = _plan(org)
    membership = _membership(student, plan)
    api_client.force_authenticate(user=gym_admin)

    post_resp = api_client.post(URL, {
        'student_plan': membership.id, 'amount': '30000', 'method': 'cash',
    }, format='json')
    assert post_resp.status_code == 201, post_resp.content

    memberships_resp = api_client.get(f'/api/plans/{plan.id}/memberships/')

    assert memberships_resp.status_code == 200, memberships_resp.content
    rows = [r for r in memberships_resp.json() if r['id'] == membership.id]
    assert rows, 'precondicion: la membresia aparece en el listado'
    assert rows[0]['payment_status'] == 'paid'


def test_the_response_is_minimal_and_hides_the_payment_axis(api_client, make_organization,
                                                             make_user):
    """La respuesta no publica `payment_status` ni anida el serializer de la membresia:
    quien registro el pago ya sabe que registro."""
    org = make_organization()
    student = make_user('stu-i', organization=org, role='student')
    gym_admin = make_user('admin-i', organization=org, role='gym_admin')
    membership = _membership(student, _plan(org))
    api_client.force_authenticate(user=gym_admin)

    resp = api_client.post(URL, {
        'student_plan': membership.id, 'amount': '30000', 'method': 'cash',
    }, format='json')

    assert resp.status_code == 201, resp.content
    assert set(resp.json()) == {
        'id', 'student_plan', 'amount', 'method', 'reference', 'recorded_at',
    }


def test_the_organization_and_the_recorder_never_come_from_the_payload(
        api_client, make_organization, make_user):
    """`organization`, `recorded_by` y `recorded_at` no son campos del serializer de
    entrada: cualquier valor que el payload mande para esas claves se ignora."""
    org = make_organization()
    other_org = make_organization()
    student = make_user('stu-j', organization=org, role='student')
    gym_admin = make_user('admin-j', organization=org, role='gym_admin')
    other_user = make_user('other-j', organization=other_org, role='gym_admin')
    membership = _membership(student, _plan(org))
    api_client.force_authenticate(user=gym_admin)

    resp = api_client.post(URL, {
        'student_plan': membership.id, 'amount': '30000', 'method': 'cash',
        'organization': other_org.id, 'recorded_by': other_user.id,
        'recorded_at': '2000-01-01T00:00:00Z',
    }, format='json')

    assert resp.status_code == 201, resp.content
    payment = ManualPayment.objects.get()
    assert payment.organization_id == org.id
    assert payment.recorded_by_id == gym_admin.id
    assert timezone.localtime(payment.recorded_at).date() == timezone.localdate()


def test_registering_on_a_membership_of_another_organization_is_not_found(
        api_client, make_organization, make_user):
    """Cobertura #3 (mitad endpoint): la membresia de otra organizacion es invisible."""
    org_a = make_organization()
    org_b = make_organization()
    student_b = make_user('stu-k', organization=org_b, role='student')
    gym_admin_a = make_user('admin-k', organization=org_a, role='gym_admin')
    membership_b = _membership(student_b, _plan(org_b))
    api_client.force_authenticate(user=gym_admin_a)

    resp = api_client.post(URL, {
        'student_plan': membership_b.id, 'amount': '30000', 'method': 'cash',
    }, format='json')

    assert resp.status_code == 404, resp.content
    assert ManualPayment.objects.count() == 0


def test_a_foreign_membership_and_a_nonexistent_one_are_indistinguishable(
        api_client, make_organization, make_user):
    """Guarda del oraculo: no puede haber una diferencia observable entre "existe pero no
    es tuya" y "no existe", o un `curl` por id mapea membresias ajenas."""
    org_a = make_organization()
    org_b = make_organization()
    student_b = make_user('stu-l', organization=org_b, role='student')
    gym_admin_a = make_user('admin-l', organization=org_a, role='gym_admin')
    membership_b = _membership(student_b, _plan(org_b))
    api_client.force_authenticate(user=gym_admin_a)

    foreign_resp = api_client.post(URL, {
        'student_plan': membership_b.id, 'amount': '30000', 'method': 'cash',
    }, format='json')
    nonexistent_resp = api_client.post(URL, {
        'student_plan': membership_b.id + 10_000, 'amount': '30000', 'method': 'cash',
    }, format='json')

    assert foreign_resp.status_code == nonexistent_resp.status_code == 404
    assert foreign_resp.json() == nonexistent_resp.json()


@pytest.mark.parametrize('role', ['manager', 'monitor', 'teacher', 'student'])
def test_only_gym_admin_can_record(api_client, make_organization, make_user, role):
    """Cobertura #4: ningun otro rol de la organizacion puede registrar un cobro manual."""
    org = make_organization()
    student = make_user('stu-m', organization=org, role='student')
    actor = make_user(f'actor-m-{role}', organization=org, role=role)
    membership = _membership(student, _plan(org))
    api_client.force_authenticate(user=actor)

    resp = api_client.post(URL, {
        'student_plan': membership.id, 'amount': '30000', 'method': 'cash',
    }, format='json')

    assert resp.status_code == 403
    assert ManualPayment.objects.count() == 0


def test_superadmin_cannot_record(api_client, make_organization, make_user):
    """El `superadmin` es rol de PLATAFORMA sin organizacion: no hay org que estampar sin
    creerle al payload, y derivarla de la membresia volveria tautologica la unica guarda
    cross-tenant del endpoint. Denegar es reversible; abrir no."""
    org = make_organization()
    student = make_user('stu-n', organization=org, role='student')
    superadmin = make_user('super-n', organization=None, role='superadmin')
    membership = _membership(student, _plan(org))
    api_client.force_authenticate(user=superadmin)

    resp = api_client.post(URL, {
        'student_plan': membership.id, 'amount': '30000', 'method': 'cash',
    }, format='json')

    assert resp.status_code == 403
    assert ManualPayment.objects.count() == 0


def test_a_gym_admin_without_organization_is_rejected(api_client, make_organization,
                                                       make_user):
    """El check exige el ROL y el ANCLA: sin `organization_id` no hay organizacion que
    estampar en la fila."""
    org = make_organization()
    student = make_user('stu-o', organization=org, role='student')
    membership = _membership(student, _plan(org))
    orgless_admin = make_user('admin-o', organization=None, role='gym_admin')
    api_client.force_authenticate(user=orgless_admin)

    resp = api_client.post(URL, {
        'student_plan': membership.id, 'amount': '30000', 'method': 'cash',
    }, format='json')

    assert resp.status_code == 403
    assert ManualPayment.objects.count() == 0


def test_an_anonymous_request_is_rejected(api_client, make_organization, make_user):
    org = make_organization()
    student = make_user('stu-p', organization=org, role='student')
    membership = _membership(student, _plan(org))

    resp = api_client.post(URL, {
        'student_plan': membership.id, 'amount': '30000', 'method': 'cash',
    }, format='json')

    assert resp.status_code in (401, 403)
    assert ManualPayment.objects.count() == 0


@pytest.mark.parametrize('amount', ['0', '-1', '-0.01'])
def test_a_non_positive_amount_is_rejected(api_client, make_organization, make_user,
                                           amount):
    """Cobertura #2 del endpoint: el serializer de entrada exige `min_value=0.01`."""
    org = make_organization()
    student = make_user('stu-q', organization=org, role='student')
    gym_admin = make_user('admin-q', organization=org, role='gym_admin')
    membership = _membership(student, _plan(org))
    api_client.force_authenticate(user=gym_admin)

    resp = api_client.post(URL, {
        'student_plan': membership.id, 'amount': amount, 'method': 'cash',
    }, format='json')

    assert resp.status_code == 400
    assert 'amount' in resp.json()
    assert ManualPayment.objects.count() == 0


def test_a_non_numeric_membership_id_is_a_400(api_client, make_organization, make_user):
    org = make_organization()
    gym_admin = make_user('admin-r', organization=org, role='gym_admin')
    api_client.force_authenticate(user=gym_admin)

    resp = api_client.post(URL, {
        'student_plan': 'abc', 'amount': '30000', 'method': 'cash',
    }, format='json')

    assert resp.status_code == 400


def test_an_out_of_range_membership_id_is_a_400_not_a_500(api_client, make_organization,
                                                           make_user):
    """Misma leccion que `_as_id_list` (views.py:189-193): fuera del rango de bigint,
    `filter(pk=...)` revienta en PostgreSQL con un 500 que SQLite no reproduce."""
    org = make_organization()
    gym_admin = make_user('admin-s', organization=org, role='gym_admin')
    api_client.force_authenticate(user=gym_admin)

    resp = api_client.post(URL, {
        'student_plan': 2 ** 63, 'amount': '30000', 'method': 'cash',
    }, format='json')

    assert resp.status_code == 400


def test_the_reference_is_optional(api_client, make_organization, make_user):
    org = make_organization()
    student = make_user('stu-t', organization=org, role='student')
    gym_admin = make_user('admin-t', organization=org, role='gym_admin')
    membership = _membership(student, _plan(org))
    api_client.force_authenticate(user=gym_admin)

    resp = api_client.post(URL, {
        'student_plan': membership.id, 'amount': '30000', 'method': 'cash',
    }, format='json')

    assert resp.status_code == 201, resp.content
    assert resp.json()['reference'] == ''
    assert ManualPayment.objects.get().reference == ''


def test_two_payments_on_the_same_membership_are_both_accepted(api_client,
                                                                make_organization,
                                                                make_user):
    org = make_organization()
    student = make_user('stu-u', organization=org, role='student')
    gym_admin = make_user('admin-u', organization=org, role='gym_admin')
    membership = _membership(student, _plan(org), final_price=30000)
    api_client.force_authenticate(user=gym_admin)

    first = api_client.post(URL, {
        'student_plan': membership.id, 'amount': '10000', 'method': 'cash',
    }, format='json')
    second = api_client.post(URL, {
        'student_plan': membership.id, 'amount': '20000', 'method': 'transfer',
    }, format='json')

    assert first.status_code == second.status_code == 201
    assert ManualPayment.objects.filter(student_plan=membership).count() == 2
    assert describe_student_plan(membership, TODAY).payment_status == 'paid'


def test_the_endpoint_has_no_read_surface(api_client, make_organization, make_user):
    """Guarda contra que alguien agregue despues un listado que le entregue importes
    cobrados al monitor por otra puerta."""
    org = make_organization()
    gym_admin = make_user('admin-v', organization=org, role='gym_admin')
    api_client.force_authenticate(user=gym_admin)

    resp = api_client.get(URL)

    assert resp.status_code == 405


# --------------------------------------------------------------------------------------
# B.2 `method` (P3.2): instrumento del cobro, efectivo o transferencia
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize('method', ['cash', 'transfer'])
def test_the_method_is_persisted_on_the_row(api_client, make_organization, make_user, method):
    """Cobertura central de P3.2: la fila persiste EXACTAMENTE el valor declarado, sin
    normalizarlo ni inferirlo de `reference`."""
    org = make_organization()
    student = make_user(f'stu-method-{method}', organization=org, role='student')
    gym_admin = make_user(f'admin-method-{method}', organization=org, role='gym_admin')
    membership = _membership(student, _plan(org))
    api_client.force_authenticate(user=gym_admin)

    resp = api_client.post(URL, {
        'student_plan': membership.id, 'amount': '30000', 'method': method,
    }, format='json')

    assert resp.status_code == 201, resp.content
    assert resp.json()['method'] == method
    assert ManualPayment.objects.get().method == method


def test_method_missing_is_rejected(api_client, make_organization, make_user):
    """`method` es REQUERIDO y sin default (a diferencia de `reference`): el `''` que admite
    el modelo existe solo para filas legacy anteriores a P3.2, no es una opción que este
    endpoint ofrezca."""
    org = make_organization()
    student = make_user('stu-method-missing', organization=org, role='student')
    gym_admin = make_user('admin-method-missing', organization=org, role='gym_admin')
    membership = _membership(student, _plan(org))
    api_client.force_authenticate(user=gym_admin)

    resp = api_client.post(URL, {
        'student_plan': membership.id, 'amount': '30000',
    }, format='json')

    assert resp.status_code == 400
    assert 'method' in resp.json()
    assert ManualPayment.objects.count() == 0


def test_method_with_an_invalid_value_is_rejected(api_client, make_organization, make_user):
    """`ChoiceField`: solo `cash`/`transfer` son valores válidos, ninguna otra palabra."""
    org = make_organization()
    student = make_user('stu-method-bogus', organization=org, role='student')
    gym_admin = make_user('admin-method-bogus', organization=org, role='gym_admin')
    membership = _membership(student, _plan(org))
    api_client.force_authenticate(user=gym_admin)

    resp = api_client.post(URL, {
        'student_plan': membership.id, 'amount': '30000', 'method': 'bogus',
    }, format='json')

    assert resp.status_code == 400
    assert 'method' in resp.json()
    assert ManualPayment.objects.count() == 0


def test_recorded_by_and_method_both_land_on_the_same_row(api_client, make_organization,
                                                           make_user):
    """`recorded_by` ya funcionaba desde 8.2; esto prueba que agregar `method` (P3.2) no lo
    hizo regresar: las dos columnas se leen de la MISMA fila que devolvió el POST."""
    org = make_organization()
    student = make_user('stu-method-recorder', organization=org, role='student')
    gym_admin = make_user('admin-method-recorder', organization=org, role='gym_admin')
    membership = _membership(student, _plan(org))
    api_client.force_authenticate(user=gym_admin)

    resp = api_client.post(URL, {
        'student_plan': membership.id, 'amount': '30000', 'method': 'transfer',
    }, format='json')

    assert resp.status_code == 201, resp.content
    payment = ManualPayment.objects.get(pk=resp.json()['id'])
    assert payment.recorded_by_id == gym_admin.id
    assert payment.method == 'transfer'


# --------------------------------------------------------------------------------------
# C. Integración con `assign` (P3.2): `payment.manual_method` llega hasta esta misma fila
# --------------------------------------------------------------------------------------

def test_assign_with_a_manual_payment_persists_the_manual_method(api_client, make_organization,
                                                                  make_user):
    """`payment.manual_method` es el mismo instrumento que la sección B.2 prueba en el
    endpoint directo, pero llegado por la OTRA puerta de escritura
    (`StudentPlanViewSet.assign`, views.py:3950-3963):
    `record_manual_payment(method=payment['manual_method'])`, NUNCA `payment['method']` -ese
    ya significa la vía de venta (`free`/`manual`), no el instrumento del cobro."""
    org = make_organization()
    student = make_user('stu-assign-method', organization=org, role='student')
    gym_admin = make_user('admin-assign-method', organization=org, role='gym_admin')
    plan = _plan(org)
    api_client.force_authenticate(user=gym_admin)

    resp = api_client.post(ASSIGN_URL, {
        'user': student.id, 'plan': plan.id, 'start_date': str(TODAY),
        'payment': {'method': 'manual', 'amount': '30000.00', 'manual_method': 'transfer'},
    }, format='json')

    assert resp.status_code == 201, resp.content
    membership = StudentPlan.objects.get(id=resp.data['id'])
    payment = ManualPayment.objects.get(student_plan=membership)
    assert payment.method == 'transfer'


def test_assign_with_a_manual_payment_without_manual_method_is_rejected(api_client,
                                                                         make_organization,
                                                                         make_user):
    """Mismo criterio que `amount` en `StudentPlanAssignPaymentSerializer.validate()`:
    `manual_method` es obligatorio para declarar la vía manual, y el 400 se corta ANTES de
    tocar la base -ni membresía ni `ManualPayment` quedan creados a medias."""
    org = make_organization()
    student = make_user('stu-assign-method-missing', organization=org, role='student')
    gym_admin = make_user('admin-assign-method-missing', organization=org, role='gym_admin')
    plan = _plan(org)
    api_client.force_authenticate(user=gym_admin)
    before_sp, before_mp = StudentPlan.objects.count(), ManualPayment.objects.count()

    resp = api_client.post(ASSIGN_URL, {
        'user': student.id, 'plan': plan.id, 'start_date': str(TODAY),
        'payment': {'method': 'manual', 'amount': '30000.00'},
    }, format='json')

    assert resp.status_code == 400, resp.content
    assert 'manual_method' in resp.json().get('payment', {})
    assert StudentPlan.objects.count() == before_sp
    assert ManualPayment.objects.count() == before_mp


def test_assign_free_with_a_manual_method_is_rejected(api_client, make_organization, make_user):
    """Espejo de `amount`/`reference`/`line_items` en la vía free: una beca total no tiene
    instrumento de cobro (efectivo/transferencia) que declarar."""
    org = make_organization()
    student = make_user('stu-assign-free-method', organization=org, role='student')
    gym_admin = make_user('admin-assign-free-method', organization=org, role='gym_admin')
    plan = _plan(org)
    api_client.force_authenticate(user=gym_admin)
    before_sp, before_mp = StudentPlan.objects.count(), ManualPayment.objects.count()

    resp = api_client.post(ASSIGN_URL, {
        'user': student.id, 'plan': plan.id, 'start_date': str(TODAY),
        'payment': {'method': 'free', 'manual_method': 'cash'},
    }, format='json')

    assert resp.status_code == 400, resp.content
    assert 'manual_method' in resp.json().get('payment', {})
    assert StudentPlan.objects.count() == before_sp
    assert ManualPayment.objects.count() == before_mp
