"""8.3 (RED) — `assign` obliga a declarar la via de pago (`free` o `manual`).

Hoy `POST /api/plans/assign/` crea la membresia sin contraparte financiera: el campo
`payment` ni siquiera existe en el serializer, asi que el payload que lo trae se ignora
en silencio y la asignacion sigue devolviendo 201. Este archivo fija el contrato nuevo
— `payment` REQUERIDO, `{'method': 'free'}` o `{'method': 'manual', amount, reference}` —
y por eso todos los tests 1-10 estan escritos para FALLAR contra el codigo actual. El test
11 es la excepcion: ancla una guarda cross-org que ya existe hoy.
"""
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone

from core.models import ManualPayment, Plan, StudentPlan
from core.services.plans import PlanOrganizationMismatch, PlanPaymentStatus, describe_student_plan

pytestmark = pytest.mark.django_db

ASSIGN_URL = '/api/plans/assign/'
TODAY = timezone.localdate()


def _plan(org, *, name='Plan test', price=20000):
    return Plan.objects.create(
        organization=org, name=name, plan_type=Plan.PlanType.MONTHLY,
        total_classes=10, unlimited_classes=False, duration_days=30, price=price,
    )


def _state(membership):
    return describe_student_plan(membership, TODAY)


@pytest.fixture
def world(make_organization, make_user):
    org = make_organization()
    admin = make_user('admin-83', organization=org, role='gym_admin')
    student = make_user('stu-83', organization=org, role='student')
    plan = _plan(org)
    return {'org': org, 'admin': admin, 'student': student, 'plan': plan}


# --------------------------------------------------------------------------------------
# 1. `payment` es requerido
# --------------------------------------------------------------------------------------

def test_payment_missing_is_rejected(api_client, world):
    """El punto central de 8.3: ya no existe el alta sin declaracion financiera."""
    admin, student, plan = world['admin'], world['student'], world['plan']
    api_client.force_authenticate(admin)
    before_sp, before_mp = StudentPlan.objects.count(), ManualPayment.objects.count()

    resp = api_client.post(ASSIGN_URL, {
        'user': student.id, 'plan': plan.id, 'start_date': str(TODAY),
    }, format='json')

    assert resp.status_code == 400, resp.data
    assert StudentPlan.objects.count() == before_sp
    assert ManualPayment.objects.count() == before_mp


# --------------------------------------------------------------------------------------
# 2. Via free
# --------------------------------------------------------------------------------------

def test_free_assign_creates_a_membership_at_zero_price(api_client, world):
    """Free fija el descuento en 100: `final_price` sale en 0 y deriva FREE por la regla
    de 8.1 (0 explicito), sin crear ningun ManualPayment."""
    admin, student, plan = world['admin'], world['student'], world['plan']
    api_client.force_authenticate(admin)

    resp = api_client.post(ASSIGN_URL, {
        'user': student.id, 'plan': plan.id, 'start_date': str(TODAY),
        'payment': {'method': 'free'},
    }, format='json')

    assert resp.status_code == 201, resp.data
    membership = StudentPlan.objects.get(user=student, is_active=True)
    assert membership.final_price == 0.0
    assert _state(membership).payment_status == PlanPaymentStatus.FREE
    assert ManualPayment.objects.count() == 0


# --------------------------------------------------------------------------------------
# 3. Via manual
# --------------------------------------------------------------------------------------

def test_manual_assign_creates_the_membership_and_the_manual_payment(api_client, world):
    admin, student, plan = world['admin'], world['student'], world['plan']
    api_client.force_authenticate(admin)

    resp = api_client.post(ASSIGN_URL, {
        'user': student.id, 'plan': plan.id, 'start_date': str(TODAY),
        'payment': {'method': 'manual', 'amount': '20000.00', 'manual_method': 'cash', 'reference': 'efectivo'},
    }, format='json')

    assert resp.status_code == 201, resp.data
    membership = StudentPlan.objects.get(user=student, is_active=True)
    assert ManualPayment.objects.filter(student_plan=membership).count() == 1
    payment = ManualPayment.objects.filter(student_plan=membership).first()
    assert payment.organization_id == admin.organization_id
    assert payment.amount == Decimal('20000.00')
    assert payment.reference == 'efectivo'
    assert payment.recorded_by_id == admin.id
    assert _state(membership).payment_status == PlanPaymentStatus.PAID


def test_manual_with_zero_amount_is_rejected(api_client, world):
    admin, student, plan = world['admin'], world['student'], world['plan']
    api_client.force_authenticate(admin)
    before_sp, before_mp = StudentPlan.objects.count(), ManualPayment.objects.count()

    resp = api_client.post(ASSIGN_URL, {
        'user': student.id, 'plan': plan.id, 'start_date': str(TODAY),
        'payment': {'method': 'manual', 'amount': '0'},
    }, format='json')

    assert resp.status_code == 400, resp.data
    assert StudentPlan.objects.count() == before_sp
    assert ManualPayment.objects.count() == before_mp


def test_manual_assign_rolls_back_the_membership_if_the_payment_fails(api_client, world,
                                                                       monkeypatch):
    """La membresia y el pago viven en el MISMO atomic: si `record_manual_payment` revienta,
    el INSERT de `activate_student_plan` se tiene que deshacer tambien. Se intercepta el
    nombre modulo-global (`core.views.record_manual_payment`), no un import local."""
    admin, student, plan = world['admin'], world['student'], world['plan']
    api_client.force_authenticate(admin)
    before_sp = StudentPlan.objects.count()

    def _boom(**kwargs):
        raise DjangoValidationError('boom')

    monkeypatch.setattr('core.views.record_manual_payment', _boom)

    resp = api_client.post(ASSIGN_URL, {
        'user': student.id, 'plan': plan.id, 'start_date': str(TODAY),
        'payment': {'method': 'manual', 'amount': '20000.00', 'manual_method': 'cash'},
    }, format='json')

    assert resp.status_code == 400, resp.data
    assert StudentPlan.objects.count() == before_sp


def test_manual_without_amount_is_rejected(api_client, world):
    admin, student, plan = world['admin'], world['student'], world['plan']
    api_client.force_authenticate(admin)
    before_sp, before_mp = StudentPlan.objects.count(), ManualPayment.objects.count()

    resp = api_client.post(ASSIGN_URL, {
        'user': student.id, 'plan': plan.id, 'start_date': str(TODAY),
        'payment': {'method': 'manual'},
    }, format='json')

    assert resp.status_code == 400, resp.data
    assert StudentPlan.objects.count() == before_sp
    assert ManualPayment.objects.count() == before_mp


# --------------------------------------------------------------------------------------
# 4. Reglas cruzadas
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize('extra', [
    {'payment': {'method': 'free', 'amount': '1000.00'}},
    {'payment': {'method': 'free'}, 'discount_percentage': 50},
])
def test_free_rejects_an_incoherent_payload(api_client, world, extra):
    """Free ES beca total: traer `amount` o un descuento explicito es incoherente, no se
    resuelve en silencio."""
    admin, student, plan = world['admin'], world['student'], world['plan']
    api_client.force_authenticate(admin)
    before_sp, before_mp = StudentPlan.objects.count(), ManualPayment.objects.count()

    body = {'user': student.id, 'plan': plan.id, 'start_date': str(TODAY)}
    body.update(extra)

    resp = api_client.post(ASSIGN_URL, body, format='json')

    assert resp.status_code == 400, resp.data
    assert StudentPlan.objects.count() == before_sp
    assert ManualPayment.objects.count() == before_mp


def test_manual_with_full_discount_is_rejected(api_client, world):
    """Invariante `manual ⟹ final_price > 0`: un descuento del 100% deja la venta en 0, y
    un ManualPayment ahi registraria un cobro que la regla de 8.2 lee como FREE."""
    admin, student, plan = world['admin'], world['student'], world['plan']
    api_client.force_authenticate(admin)
    before_sp, before_mp = StudentPlan.objects.count(), ManualPayment.objects.count()

    resp = api_client.post(ASSIGN_URL, {
        'user': student.id, 'plan': plan.id, 'start_date': str(TODAY),
        'discount_percentage': 100,
        'payment': {'method': 'manual', 'amount': '20000.00', 'manual_method': 'cash'},
    }, format='json')

    assert resp.status_code == 400, resp.data
    assert StudentPlan.objects.count() == before_sp
    assert ManualPayment.objects.count() == before_mp


# --------------------------------------------------------------------------------------
# 5. Actor: superadmin no puede estampar organizacion en un pago manual
# --------------------------------------------------------------------------------------

def test_superadmin_manual_needs_an_org_but_free_does_not(api_client, world, make_user):
    """El superadmin no tiene `organization_id` que estampar en un ManualPayment: 400
    explicito, no 403 (mismo argumento que `ManualPaymentCreateView`). Con `free` no hay
    pago que estampar, asi que ahi si puede."""
    super_admin = make_user('super-83', role='superadmin')
    student, plan = world['student'], world['plan']
    api_client.force_authenticate(super_admin)
    before_sp, before_mp = StudentPlan.objects.count(), ManualPayment.objects.count()

    manual_resp = api_client.post(ASSIGN_URL, {
        'user': student.id, 'plan': plan.id, 'start_date': str(TODAY),
        'payment': {'method': 'manual', 'amount': '20000.00', 'manual_method': 'cash'},
    }, format='json')

    assert manual_resp.status_code == 400, manual_resp.data
    assert StudentPlan.objects.count() == before_sp
    assert ManualPayment.objects.count() == before_mp

    free_resp = api_client.post(ASSIGN_URL, {
        'user': student.id, 'plan': plan.id, 'start_date': str(TODAY),
        'payment': {'method': 'free'},
    }, format='json')

    assert free_resp.status_code == 201, free_resp.data
    membership = StudentPlan.objects.get(user=student, is_active=True)
    assert membership.final_price == 0.0


# --------------------------------------------------------------------------------------
# 6. Convivencia con 7.1 (assign no desactiva nada)
# --------------------------------------------------------------------------------------

def test_free_then_manual_assign_coexist_for_the_same_student(api_client, world):
    """7.1: asignar no desactiva nada. La segunda asignacion (de pago) no toca la
    primera (gratis), y el ManualPayment cuelga SOLO de la fila nueva."""
    admin, student, plan = world['admin'], world['student'], world['plan']
    api_client.force_authenticate(admin)

    free_resp = api_client.post(ASSIGN_URL, {
        'user': student.id, 'plan': plan.id, 'start_date': str(TODAY),
        'payment': {'method': 'free'},
    }, format='json')
    assert free_resp.status_code == 201, free_resp.data
    first = StudentPlan.objects.get(id=free_resp.data['id'])

    manual_resp = api_client.post(ASSIGN_URL, {
        'user': student.id, 'plan': plan.id, 'start_date': str(TODAY),
        'payment': {'method': 'manual', 'amount': '15000.00', 'manual_method': 'cash'},
    }, format='json')
    assert manual_resp.status_code == 201, manual_resp.data
    second = StudentPlan.objects.get(id=manual_resp.data['id'])

    first.refresh_from_db()
    assert StudentPlan.objects.filter(user=student, is_active=True).count() == 2
    assert first.is_active is True
    assert second.is_active is True
    assert ManualPayment.objects.filter(student_plan=first).count() == 0
    assert ManualPayment.objects.filter(student_plan=second).count() == 1


# --------------------------------------------------------------------------------------
# 7. Regresion: la guarda cross-org existente ya corta esto hoy
# --------------------------------------------------------------------------------------

def test_cross_org_gym_admin_cannot_assign_with_a_manual_payment(api_client,
                                                                  make_organization,
                                                                  make_user):
    """No es parte de 8.3: ancla que la guarda cross-org de `assign` (`views.py:3457-3462`)
    ya rechaza esto HOY, para que la feature nueva no la afloje sin querer."""
    org_a = make_organization()
    org_b = make_organization()
    admin_a = make_user('admin-83-a', organization=org_a, role='gym_admin')
    student_b = make_user('stu-83-b', organization=org_b, role='student')
    plan_b = _plan(org_b)
    api_client.force_authenticate(admin_a)
    before_sp, before_mp = StudentPlan.objects.count(), ManualPayment.objects.count()

    resp = api_client.post(ASSIGN_URL, {
        'user': student_b.id, 'plan': plan_b.id, 'start_date': str(TODAY),
        'payment': {'method': 'manual', 'amount': '20000.00', 'manual_method': 'cash'},
    }, format='json')

    assert resp.status_code == 403, resp.data
    assert StudentPlan.objects.count() == before_sp
    assert ManualPayment.objects.count() == before_mp


# --------------------------------------------------------------------------------------
# 8. Remediacion del security review (oraculo cross-tenant + red de excepcion + cobertura)
# --------------------------------------------------------------------------------------

def test_manual_cross_org_plan_price_does_not_leak_via_status_code(api_client, make_organization,
                                                                     make_user):
    """HALLAZGO 1: la invariante `manual => final_price > 0` tiene que vivir DESPUES de las
    guardas cross-org, no antes. Viviendo en el serializer (que corre en `is_valid()`, ANTES
    de esas guardas en la view) un plan ajeno con precio 0 daba 400 "la venta queda en $0"
    mientras uno con precio normal daba 403 -el status code delataba el precio de un plan de
    OTRA organizacion, con ids autoincrementales y adivinables-. Las dos requests, contra un
    plan ajeno gratis y uno con precio, tienen que devolver el MISMO codigo y el MISMO
    cuerpo."""
    org_a = make_organization()
    org_b = make_organization()
    admin_a = make_user('admin-83-oracle', organization=org_a, role='gym_admin')
    student_b = make_user('stu-83-oracle', organization=org_b, role='student')
    plan_b_free = _plan(org_b, name='Plan B gratis', price=0)
    plan_b_priced = _plan(org_b, name='Plan B con precio', price=20000)
    api_client.force_authenticate(admin_a)
    before_sp, before_mp = StudentPlan.objects.count(), ManualPayment.objects.count()

    resp_free_plan = api_client.post(ASSIGN_URL, {
        'user': student_b.id, 'plan': plan_b_free.id, 'start_date': str(TODAY),
        'payment': {'method': 'manual', 'amount': '20000.00', 'manual_method': 'cash'},
    }, format='json')
    resp_priced_plan = api_client.post(ASSIGN_URL, {
        'user': student_b.id, 'plan': plan_b_priced.id, 'start_date': str(TODAY),
        'payment': {'method': 'manual', 'amount': '20000.00', 'manual_method': 'cash'},
    }, format='json')

    assert resp_free_plan.status_code == 403, resp_free_plan.data
    assert resp_priced_plan.status_code == 403, resp_priced_plan.data
    assert resp_free_plan.data == resp_priced_plan.data
    assert StudentPlan.objects.count() == before_sp
    assert ManualPayment.objects.count() == before_mp


def test_manual_assign_maps_plan_organization_mismatch_to_403(api_client, world, monkeypatch):
    """HALLAZGO 4: red de excepcion asimetrica. `activate_student_plan` puede levantar
    `PlanOrganizationMismatch` dentro del mismo atomic que `assign`, y antes de este fix no
    habia ningun `except` para esa excepcion -saldria 500 en vez de negar el acceso-. Se
    intercepta parcheando el atributo en `core.services.plans`: `assign` importa
    `activate_student_plan` LOCAL (dentro del metodo), asi que ese import resuelve el nombre
    en CALL TIME contra el modulo, y el monkeypatch sobre el modulo lo alcanza igual."""
    admin, student, plan = world['admin'], world['student'], world['plan']
    api_client.force_authenticate(admin)
    before_sp = StudentPlan.objects.count()

    def _boom(**kwargs):
        raise PlanOrganizationMismatch('boom')

    monkeypatch.setattr('core.services.plans.activate_student_plan', _boom)

    resp = api_client.post(ASSIGN_URL, {
        'user': student.id, 'plan': plan.id, 'start_date': str(TODAY),
        'payment': {'method': 'manual', 'amount': '20000.00', 'manual_method': 'cash'},
    }, format='json')

    assert resp.status_code == 403, resp.data
    assert StudentPlan.objects.count() == before_sp


@pytest.mark.parametrize('role', ['manager', 'monitor', 'teacher', 'student'])
def test_only_superadmin_or_gym_admin_can_assign(api_client, world, make_user, role):
    """HALLAZGO 5a: la matriz de roles de `assign` no tenia un test explicito para
    manager/monitor/teacher/student con un payload de PAGO VALIDO -sin esto, un cambio que
    aflojara el check de rol de arriba podria pasar desapercibido si la suite solo prueba ese
    check con payloads que fallan igual por otro motivo."""
    org, student, plan = world['org'], world['student'], world['plan']
    actor = make_user(f'actor-83-{role}', organization=org, role=role)
    api_client.force_authenticate(actor)
    before_sp, before_mp = StudentPlan.objects.count(), ManualPayment.objects.count()

    resp = api_client.post(ASSIGN_URL, {
        'user': student.id, 'plan': plan.id, 'start_date': str(TODAY),
        'payment': {'method': 'manual', 'amount': '20000.00', 'manual_method': 'cash'},
    }, format='json')

    assert resp.status_code == 403, resp.data
    assert StudentPlan.objects.count() == before_sp
    assert ManualPayment.objects.count() == before_mp


def test_payload_garbage_does_not_override_the_actors_organization(api_client, world,
                                                                     make_organization):
    """HALLAZGO 5b: ni un `organization` top-level ajeno ni basura dentro de `payment`
    (`organization`, `recorded_by`, `student_plan`) pueden alterar quien queda estampado como
    dueno de la membresia o del pago -ninguno de esos campos existe en los serializers de
    este endpoint, asi que DRF los descarta en silencio, y el unico origen de
    organizacion/actor es el request autenticado, nunca el payload."""
    admin, student, plan = world['admin'], world['student'], world['plan']
    other_org = make_organization()
    api_client.force_authenticate(admin)

    resp = api_client.post(ASSIGN_URL, {
        'user': student.id, 'plan': plan.id, 'start_date': str(TODAY),
        'organization': other_org.id,
        'payment': {
            'method': 'manual', 'amount': '20000.00', 'manual_method': 'cash',
            'organization': other_org.id, 'recorded_by': 999999, 'student_plan': 999999,
        },
    }, format='json')

    assert resp.status_code == 201, resp.data
    membership = StudentPlan.objects.get(user=student, is_active=True)
    assert membership.organization_id == admin.organization_id
    payment_row = ManualPayment.objects.get(student_plan=membership)
    assert payment_row.organization_id == admin.organization_id
    assert payment_row.recorded_by_id == admin.id
