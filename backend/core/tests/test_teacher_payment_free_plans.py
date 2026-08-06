"""Pago al profe cuando el plan del alumno es GRATIS (build teacher-payment-free-plans).

Contexto: `per_plan_price` y `revenue_share` calculan el pago al profesor como
`StudentPlan.final_price / total_classes`. Un plan gratis (`discount_percentage == 100`)
tiene `final_price == 0` y el profe cobraría $0, lo cual es incorrecto. Se agrega
`Organization.free_class_teacher_payment_value`: el valor de UNA clase de plan gratis,
que se usa DIRECTO (sin dividir por `total_classes`) cuando el plan es gratis.

Cubre:
1. Plan gratis de N clases, config > 0 -> cobra el % sobre el valor de config, SIN
   dividir por total_classes. En per_plan_price Y en revenue_share.
2. CENTINELA DE REGRESIÓN: descuento parcial (20%) -> pago IDÉNTICO al de hoy.
3. Precio normal (discount_percentage=0) -> idéntico a hoy.
4. Plan gratis ILIMITADO -> sigue aportando 0 (unlimited_classes va primero).
5. POST /api/plans/ con discount_percentage=100 y config <= 0 -> 400, no se crea.
6. Mismo POST con config > 0 -> 201, se crea.
7. Cross-org: la config usada es la de la org del StudentPlan, no la de otra.
8. Endpoint de config: GET/PUT propio org, 403 org ajena, 404 org inexistente.
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from core.models import (
    Attendance,
    Branch,
    ConsumptionLog,
    Enrollment,
    GymClass,
    Plan,
    StudentPlan,
    TeacherPaymentRule,
)
from core.services.teacher_payments import calculate_teacher_payment

pytestmark = pytest.mark.django_db

PASSWORD = 'Passw0rd2026'
PPP = TeacherPaymentRule.PaymentType.PER_PLAN_PRICE
REVENUE_SHARE = TeacherPaymentRule.PaymentType.REVENUE_SHARE
ACTIVE = TeacherPaymentRule.PerPlanPriceBase.ACTIVE_ENROLLMENTS
PLANS_URL = '/api/plans/'


def _login(api_client, username):
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.get(username=username)
    host = {'HTTP_HOST': f'{user.organization.subdomain}.localhost'} if user.organization_id else {}
    token = api_client.post(
        '/api/login/', {'email': user.email, 'password': PASSWORD}, format='json', **host
    ).json()['token']
    api_client.credentials(HTTP_AUTHORIZATION=f'Token {token}')


def _config_url(org):
    return f'/api/organizations/{org.id}/teacher-payment-config/'


@pytest.fixture
def setup(make_organization, make_user):
    org = make_organization()
    admin = make_user('admin', organization=org, role='gym_admin')
    teacher = make_user('teach', organization=org, role='teacher', first_name='Ana')
    s1 = make_user('s1', organization=org, role='student')
    s2 = make_user('s2', organization=org, role='student')
    branch = Branch.objects.create(organization=org, name='Sede')
    return {'org': org, 'admin': admin, 'teacher': teacher, 's1': s1, 's2': s2, 'branch': branch}


def _completed_class(org, branch, teacher):
    start = timezone.now() - timedelta(hours=2)
    return GymClass.objects.create(
        organization=org, branch=branch, teacher=teacher, name='Clase',
        start_datetime=start, end_datetime=start + timedelta(hours=1),
        status=GymClass.Status.COMPLETED,
    )


def _give_plan(org, user, total, price, discount_percentage=0, unlimited=False):
    today = timezone.localdate()
    final_price = price * (1 - discount_percentage / 100.0)
    plan = Plan.objects.create(
        organization=org, name=f'Plan-{user.username}-{total}-{discount_percentage}',
        plan_type='pack', total_classes=total, unlimited_classes=unlimited, duration_days=30,
        price=price, discount_percentage=discount_percentage,
    )
    return StudentPlan.objects.create(
        user=user, plan=plan, start_date=today, end_date=today + timedelta(days=30),
        organization_id=plan.organization_id,
        total_classes=total, unlimited_classes=unlimited, classes_used=0,
        final_price=final_price, discount_percentage=discount_percentage,
    )


def _enroll(gym_class, student, student_plan=None, present=True):
    Enrollment.objects.create(gym_class=gym_class, student=student, status='active')
    if student_plan:
        ConsumptionLog.objects.create(user=student, student_plan=student_plan, class_instance=gym_class)
    if present:
        Attendance.objects.create(gym_class=gym_class, student=student, status=Attendance.Status.PRESENT)


def _rule_ppp(org, teacher, amount, base=ACTIVE):
    rule = TeacherPaymentRule.objects.create(
        organization=org, payment_type=PPP, amount=amount, per_plan_price_base=base, is_active=True,
    )
    rule.teachers.add(teacher)
    return rule


def _rule_revenue_share(org, teacher, amount):
    rule = TeacherPaymentRule.objects.create(
        organization=org, payment_type=REVENUE_SHARE, amount=amount, is_active=True,
    )
    rule.teachers.add(teacher)
    return rule


# ---- 1. Plan gratis, config > 0 -> cobra sobre el valor de config, sin dividir ----

def test_free_plan_uses_config_value_directly_per_plan_price(setup):
    org, branch, teacher = setup['org'], setup['branch'], setup['teacher']
    org.free_class_teacher_payment_value = 5000
    org.save(update_fields=['free_class_teacher_payment_value'])

    gym_class = _completed_class(org, branch, teacher)
    # Plan gratis de 10 clases: si se dividiera por total_classes, 5000/10 = 500.
    # Directo (sin dividir) y con 20% de regla: 5000 * 0.20 = 1000.
    _enroll(gym_class, setup['s1'], _give_plan(org, setup['s1'], 10, 30000, discount_percentage=100))
    _rule_ppp(org, teacher, amount=20)

    record, _ = calculate_teacher_payment(gym_class)
    assert record.total_amount == 1000.0


def test_free_plan_uses_config_value_directly_revenue_share(setup):
    org, branch, teacher = setup['org'], setup['branch'], setup['teacher']
    org.free_class_teacher_payment_value = 5000
    org.save(update_fields=['free_class_teacher_payment_value'])

    gym_class = _completed_class(org, branch, teacher)
    _enroll(gym_class, setup['s1'], _give_plan(org, setup['s1'], 10, 30000, discount_percentage=100))
    _rule_revenue_share(org, teacher, amount=20)

    record, _ = calculate_teacher_payment(gym_class)
    assert record.total_amount == 1000.0


# ---- 2. CENTINELA DE REGRESIÓN: descuento parcial (20%) igual que hoy ----

def test_partial_discount_matches_today_exactly_per_plan_price(setup):
    org, branch, teacher = setup['org'], setup['branch'], setup['teacher']
    org.free_class_teacher_payment_value = 5000  # config presente pero IRRELEVANTE acá
    org.save(update_fields=['free_class_teacher_payment_value'])

    gym_class = _completed_class(org, branch, teacher)
    # price=30000, 20% descuento -> final_price=24000, total_classes=8 -> 3000/clase.
    _enroll(gym_class, setup['s1'], _give_plan(org, setup['s1'], 8, 30000, discount_percentage=20))
    _rule_ppp(org, teacher, amount=20)

    record, _ = calculate_teacher_payment(gym_class)
    # price*0.8/total_classes*pct = 30000*0.8/8*0.20 = 3000*0.20 = 600.0 (idéntico a hoy)
    assert record.total_amount == 600.0


def test_partial_discount_matches_today_exactly_revenue_share(setup):
    org, branch, teacher = setup['org'], setup['branch'], setup['teacher']
    gym_class = _completed_class(org, branch, teacher)
    _enroll(gym_class, setup['s1'], _give_plan(org, setup['s1'], 8, 30000, discount_percentage=20))
    _rule_revenue_share(org, teacher, amount=20)

    record, _ = calculate_teacher_payment(gym_class)
    assert record.total_amount == 600.0


# ---- 3. Precio normal (discount_percentage=0) -> idéntico a hoy ----

def test_normal_price_unaffected_per_plan_price(setup):
    org, branch, teacher = setup['org'], setup['branch'], setup['teacher']
    gym_class = _completed_class(org, branch, teacher)
    _enroll(gym_class, setup['s1'], _give_plan(org, setup['s1'], 4, 15000, discount_percentage=0))
    _rule_ppp(org, teacher, amount=20)

    record, _ = calculate_teacher_payment(gym_class)
    assert record.total_amount == 750.0  # 15000/4 * 0.20 = 3750*0.20


def test_normal_price_unaffected_revenue_share(setup):
    org, branch, teacher = setup['org'], setup['branch'], setup['teacher']
    gym_class = _completed_class(org, branch, teacher)
    _enroll(gym_class, setup['s1'], _give_plan(org, setup['s1'], 4, 15000, discount_percentage=0))
    _rule_revenue_share(org, teacher, amount=20)

    record, _ = calculate_teacher_payment(gym_class)
    assert record.total_amount == 750.0


# ---- 4. Plan gratis ILIMITADO sigue aportando 0 ----

def test_free_unlimited_plan_still_contributes_zero_per_plan_price(setup):
    org, branch, teacher = setup['org'], setup['branch'], setup['teacher']
    org.free_class_teacher_payment_value = 5000
    org.save(update_fields=['free_class_teacher_payment_value'])

    gym_class = _completed_class(org, branch, teacher)
    _enroll(
        gym_class, setup['s1'],
        _give_plan(org, setup['s1'], 0, 30000, discount_percentage=100, unlimited=True),
    )
    _rule_ppp(org, teacher, amount=20)

    record, _ = calculate_teacher_payment(gym_class)
    assert record.total_amount == 0.0


def test_free_unlimited_plan_still_contributes_zero_revenue_share(setup):
    org, branch, teacher = setup['org'], setup['branch'], setup['teacher']
    org.free_class_teacher_payment_value = 5000
    org.save(update_fields=['free_class_teacher_payment_value'])

    gym_class = _completed_class(org, branch, teacher)
    _enroll(
        gym_class, setup['s1'],
        _give_plan(org, setup['s1'], 0, 30000, discount_percentage=100, unlimited=True),
    )
    _rule_revenue_share(org, teacher, amount=20)

    record, _ = calculate_teacher_payment(gym_class)
    assert record.total_amount == 0.0


# ---- 5/6. POST /api/plans/ con discount_percentage=100 ----

def test_create_free_plan_without_config_is_400_and_not_created(api_client, setup):
    org = setup['org']
    assert org.free_class_teacher_payment_value == 0
    _login(api_client, 'admin')

    # price != 0 a propósito: el criterio de "gratis" es discount_percentage == 100,
    # NO price == 0 (decisión congelada del contrato).
    resp = api_client.post(PLANS_URL, {
        'name': 'Plan Gratis', 'plan_type': 'pack', 'total_classes': 8,
        'duration_days': 30, 'price': 20000, 'discount_percentage': 100,
    }, format='json')

    assert resp.status_code == 400, resp.content
    assert 'discount_percentage' in resp.json()
    assert not Plan.objects.filter(organization=org, name='Plan Gratis').exists()


def test_create_free_plan_with_config_is_201_and_created(api_client, setup):
    org = setup['org']
    org.free_class_teacher_payment_value = 3000
    org.save(update_fields=['free_class_teacher_payment_value'])
    _login(api_client, 'admin')

    resp = api_client.post(PLANS_URL, {
        'name': 'Plan Gratis OK', 'plan_type': 'pack', 'total_classes': 8,
        'duration_days': 30, 'price': 20000, 'discount_percentage': 100,
    }, format='json')

    assert resp.status_code == 201, resp.content
    assert Plan.objects.filter(organization=org, name='Plan Gratis OK').exists()


def test_update_to_free_plan_without_config_is_400(api_client, setup):
    org = setup['org']
    plan = Plan.objects.create(
        organization=org, name='Plan Normal', plan_type='pack', total_classes=8,
        duration_days=30, price=20000, discount_percentage=0,
    )
    _login(api_client, 'admin')

    resp = api_client.patch(
        f'{PLANS_URL}{plan.id}/', {'discount_percentage': 100}, format='json',
    )

    assert resp.status_code == 400, resp.content
    plan.refresh_from_db()
    assert plan.discount_percentage == 0


def test_partial_update_keeps_effective_discount_when_not_sent(api_client, setup):
    """Un PATCH que NO toca discount_percentage no debe gatillar la validación de
    plan gratis (el valor efectivo es el que ya tenía la instancia)."""
    org = setup['org']
    assert org.free_class_teacher_payment_value == 0
    plan = Plan.objects.create(
        organization=org, name='Plan Normal 2', plan_type='pack', total_classes=8,
        duration_days=30, price=20000, discount_percentage=0,
    )
    _login(api_client, 'admin')

    resp = api_client.patch(f'{PLANS_URL}{plan.id}/', {'price': 25000}, format='json')

    assert resp.status_code == 200, resp.content
    plan.refresh_from_db()
    assert plan.price == 25000


# ---- 7. Cross-org: usa la config de la org DEL StudentPlan, no de otra ----

def test_cross_org_uses_student_plan_organization_config(setup, make_organization, make_user):
    """Ancla real de la config cross-org.

    La GymClass y su TeacherPaymentRule son de org1; el StudentPlan gratuito (la
    MEMBRESÍA) es de org2, con valores de config bien distintos en cada org. El código
    lee `student_plan.organization.free_class_teacher_payment_value` (ver
    `_calculate_plan_price_revenue_for_class`), así que el monto esperado sale del valor
    de ORG2, no de org1 (la org de la clase/regla).

    Sin este armado, un test que solo "crea org2 y le pone otro valor" sin que ningún
    objeto real apunte a org2 pasa igual aunque el código anclara mal (p.ej. si leyera
    `class_instance.organization` en lugar de `student_plan.organization`) — es
    precisamente el bug que este test fija.

    Nota conceptual: el ancla del valor es la organización de la MEMBRESÍA
    (`StudentPlan.organization`), mientras que la de la regla de pago es la de la CLASE
    (`GymClass.organization` / `TeacherPaymentRule.organization`). Hoy ambas NO divergen
    por construcción (un StudentPlan siempre pertenece a la misma org que las clases que
    puede reservar), pero este test deja explícito cuál gana si algún día divergen.
    """
    org1, branch, teacher = setup['org'], setup['branch'], setup['teacher']
    org1.free_class_teacher_payment_value = 1000
    org1.save(update_fields=['free_class_teacher_payment_value'])

    org2 = make_organization()
    org2.free_class_teacher_payment_value = 7777
    org2.save(update_fields=['free_class_teacher_payment_value'])

    # Clase y regla de pago: org1.
    gym_class = _completed_class(org1, branch, teacher)
    _rule_ppp(org1, teacher, amount=50)

    # StudentPlan (la membresía consumida): org2, a propósito distinta de la de la clase.
    student_plan = _give_plan(org2, setup['s1'], 8, 30000, discount_percentage=100)
    _enroll(gym_class, setup['s1'], student_plan)

    record, _ = calculate_teacher_payment(gym_class)
    assert record.total_amount == 3888.5  # 7777 * 0.50, la config de ORG2 (StudentPlan)


# ---- 8. Endpoint /api/organizations/{id}/teacher-payment-config/ ----

def test_gym_admin_can_get_and_put_own_org_config(api_client, setup):
    org = setup['org']
    _login(api_client, 'admin')

    resp = api_client.get(_config_url(org))
    assert resp.status_code == 200, resp.content
    assert resp.json()['free_class_teacher_payment_value'] == 0

    resp = api_client.put(_config_url(org), {'free_class_teacher_payment_value': 4500}, format='json')
    assert resp.status_code == 200, resp.content
    assert resp.json()['free_class_teacher_payment_value'] == 4500

    org.refresh_from_db()
    assert org.free_class_teacher_payment_value == 4500


def test_gym_admin_of_other_org_gets_403(api_client, setup, make_organization, make_user):
    org = setup['org']
    other_org = make_organization()
    make_user('otheradmin', organization=other_org, role='gym_admin')
    _login(api_client, 'otheradmin')

    resp = api_client.get(_config_url(org))
    assert resp.status_code == 403, resp.content

    resp = api_client.put(_config_url(org), {'free_class_teacher_payment_value': 100}, format='json')
    assert resp.status_code == 403, resp.content


def test_nonexistent_org_is_404(api_client, setup):
    _login(api_client, 'admin')
    resp = api_client.get('/api/organizations/999999/teacher-payment-config/')
    assert resp.status_code == 404, resp.content


def test_superadmin_can_manage_any_org_config(api_client, setup, make_user):
    org = setup['org']
    make_user('root', organization=None, role='superadmin')
    _login(api_client, 'root')

    resp = api_client.put(_config_url(org), {'free_class_teacher_payment_value': 777}, format='json')
    assert resp.status_code == 200, resp.content
    org.refresh_from_db()
    assert org.free_class_teacher_payment_value == 777


def test_manager_cannot_read_or_write_config(api_client, setup, make_user):
    """El endpoint usa `_can_manage_org_resource` (deja fuera al manager) y NO
    `_can_manage_operational_resource` (que sí lo dejaría entrar) — ver el docstring de
    `teacher_payment_config` en views.py. Sin este test, un cambio futuro que cambiara
    un helper por el otro pasaría en silencio."""
    org = setup['org']
    make_user('manager1', organization=org, role='manager')
    _login(api_client, 'manager1')

    resp = api_client.get(_config_url(org))
    assert resp.status_code == 403, resp.content

    resp = api_client.put(_config_url(org), {'free_class_teacher_payment_value': 100}, format='json')
    assert resp.status_code == 403, resp.content


@pytest.mark.parametrize('bad_value', ['nan', 'inf', '-inf'])
def test_config_put_rejects_non_finite_values(api_client, setup, bad_value):
    """Red del FIX de NaN/Infinity: `MinValueValidator(0)` del modelo no los frena
    (`nan < 0` es False) y DRF acepta 'nan'/'inf' como FloatField válido. Sin la guarda de
    `validate_free_class_teacher_payment_value`, esto persistiría y tumbaría el login de
    toda la organización en el próximo request que serialice `Organization` (STRICT_JSON)."""
    org = setup['org']
    _login(api_client, 'admin')

    resp = api_client.put(_config_url(org), {'free_class_teacher_payment_value': bad_value}, format='json')
    assert resp.status_code == 400, resp.content
    assert 'free_class_teacher_payment_value' in resp.json()

    org.refresh_from_db()
    assert org.free_class_teacher_payment_value == 0
