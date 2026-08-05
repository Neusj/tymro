"""Integridad: borrar una sucursal NO debe poder corromper el saldo de los planes.

`GymClass.branch` es FK CASCADE, así que un hard delete de Branch arrastra sus
GymClass y, en cascada, Enrollment / Attendance / ConsumptionLog. El daño silencioso
es que los ConsumptionLog desaparecen pero `StudentPlan.classes_used` NO se
decrementa (ese contador solo baja por `rollback_consumption_for_enrollment`, que
la cascada nunca ejecuta): el alumno queda con clases consumidas fantasma y sin
log que las explique.

Regla: si la sucursal tiene clases asociadas se DESACTIVA (is_active=False) en vez
de borrarse; si no tiene ninguna, el hard delete es seguro y se permite.
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from core.models import Branch, ConsumptionLog, Enrollment, GymClass, Plan, StudentPlan

pytestmark = pytest.mark.django_db

PASSWORD = 'Passw0rd2026'


def _login(api_client, username):
    from django.contrib.auth import get_user_model
    user = get_user_model().objects.get(username=username)
    host = {'HTTP_HOST': f'{user.organization.subdomain}.localhost'} if user.organization_id else {}
    token = api_client.post(
        '/api/login/', {'email': user.email, 'password': PASSWORD}, format='json', **host
    ).json()['token']
    api_client.credentials(HTTP_AUTHORIZATION=f'Token {token}')


@pytest.fixture
def setup(make_organization, make_user):
    org = make_organization()
    admin = make_user('admin', organization=org, role='gym_admin')
    teacher = make_user('teach', organization=org, role='teacher')
    student = make_user('alu', organization=org, role='student', email='alu@gym.cl')
    branch = Branch.objects.create(organization=org, name='Sede Centro')
    return {'org': org, 'admin': admin, 'teacher': teacher, 'student': student, 'branch': branch}


def _class_with_consumption(setup):
    """Una clase pasada en la sucursal, con un alumno que ya consumió 1 clase de su plan."""
    start = timezone.now() - timedelta(days=2)
    gym_class = GymClass.objects.create(
        organization=setup['org'], branch=setup['branch'], teacher=setup['teacher'],
        name='Clase', start_datetime=start, end_datetime=start + timedelta(hours=1),
        capacity=10, status=GymClass.Status.COMPLETED,
    )
    today = timezone.localdate()
    plan = Plan.objects.create(
        organization=setup['org'], name='Pack 10', plan_type='pack',
        total_classes=10, duration_days=30, price=30000,
    )
    student_plan = StudentPlan.objects.create(
        user=setup['student'], plan=plan, start_date=today, end_date=today + timedelta(days=30),
        organization_id=plan.organization_id,
        total_classes=10, classes_used=1, final_price=30000,
    )
    Enrollment.objects.create(gym_class=gym_class, student=setup['student'], status='active')
    ConsumptionLog.objects.create(
        user=setup['student'], student_plan=student_plan, class_instance=gym_class,
    )
    return gym_class, student_plan


# --- A. Sucursal CON clases: se desactiva, no se borra --------------------------


def test_delete_branch_with_classes_does_not_hard_delete(api_client, setup):
    gym_class, student_plan = _class_with_consumption(setup)
    _login(api_client, 'admin')

    resp = api_client.delete(f'/api/branches/{setup["branch"].id}/')

    assert resp.status_code == 400, resp.content
    assert Branch.objects.filter(id=setup['branch'].id).exists(), 'la sucursal no debe borrarse'


def test_delete_branch_with_classes_deactivates_it(api_client, setup):
    _class_with_consumption(setup)
    _login(api_client, 'admin')

    api_client.delete(f'/api/branches/{setup["branch"].id}/')

    setup['branch'].refresh_from_db()
    assert setup['branch'].is_active is False, 'la sucursal debe quedar desactivada'


def test_delete_branch_with_classes_preserves_history(api_client, setup):
    gym_class, _ = _class_with_consumption(setup)
    _login(api_client, 'admin')

    api_client.delete(f'/api/branches/{setup["branch"].id}/')

    assert GymClass.objects.filter(id=gym_class.id).exists(), 'las clases deben sobrevivir'
    assert ConsumptionLog.objects.filter(class_instance=gym_class).exists(), \
        'los consumos deben sobrevivir'


def test_delete_branch_with_classes_does_not_corrupt_plan_balance(api_client, setup):
    """El invariante que rompe la cascada: `classes_used` debe seguir respaldado por
    la misma cantidad de ConsumptionLog. Con el hard delete el contador queda en 1
    pero su log desaparece → clase consumida fantasma."""
    _, student_plan = _class_with_consumption(setup)
    _login(api_client, 'admin')

    api_client.delete(f'/api/branches/{setup["branch"].id}/')

    student_plan.refresh_from_db()
    backing_logs = ConsumptionLog.objects.filter(student_plan=student_plan).count()
    assert student_plan.classes_used == 1, 'el saldo del plan no debe alterarse'
    assert student_plan.classes_used == backing_logs, (
        f'saldo fantasma: classes_used={student_plan.classes_used} '
        f'pero solo hay {backing_logs} consumo(s) que lo respalden'
    )


def test_delete_branch_with_classes_explains_why(api_client, setup):
    _class_with_consumption(setup)
    _login(api_client, 'admin')

    resp = api_client.delete(f'/api/branches/{setup["branch"].id}/')

    detail = resp.json()['detail'].lower()
    assert 'desactiv' in detail, f'el mensaje debe explicar que se desactivó: {detail}'
    assert 'historial' in detail, f'el mensaje debe mencionar el historial: {detail}'


# --- B. Sucursal SIN clases: hard delete normal ---------------------------------


def test_delete_branch_without_classes_hard_deletes(api_client, setup):
    _login(api_client, 'admin')

    resp = api_client.delete(f'/api/branches/{setup["branch"].id}/')

    assert resp.status_code == 204, resp.content
    assert not Branch.objects.filter(id=setup['branch'].id).exists()


def test_superadmin_delete_branch_without_classes_hard_deletes(api_client, setup, make_user):
    make_user('root', role='superadmin', organization=None)
    _login(api_client, 'root')

    resp = api_client.delete(f'/api/branches/{setup["branch"].id}/')

    assert resp.status_code == 204, resp.content
    assert not Branch.objects.filter(id=setup['branch'].id).exists()


def test_superadmin_delete_branch_with_classes_deactivates_it(api_client, setup, make_user):
    """La guarda de integridad aplica también al superadmin: la cascada corrompe
    los saldos igual sin importar quién dispare el borrado."""
    gym_class, student_plan = _class_with_consumption(setup)
    make_user('root', role='superadmin', organization=None)
    _login(api_client, 'root')

    resp = api_client.delete(f'/api/branches/{setup["branch"].id}/')

    assert resp.status_code == 400, resp.content
    setup['branch'].refresh_from_db()
    assert setup['branch'].is_active is False
    assert GymClass.objects.filter(id=gym_class.id).exists()
    student_plan.refresh_from_db()
    assert student_plan.classes_used == 1


# --- C. Regresión: el scoping por organización sigue intacto --------------------


def test_gym_admin_cannot_delete_branch_from_another_org(api_client, setup, make_organization, make_user):
    other_org = make_organization(name='Otra Org')
    make_user('intruso', organization=other_org, role='gym_admin')
    _login(api_client, 'intruso')

    resp = api_client.delete(f'/api/branches/{setup["branch"].id}/')

    assert resp.status_code == 404, resp.content
    setup['branch'].refresh_from_db()
    assert setup['branch'].is_active is True, 'no debe desactivar sucursales ajenas'


def test_gym_admin_cannot_deactivate_branch_with_classes_from_another_org(
    api_client, setup, make_organization, make_user,
):
    """El caso peligroso: la sucursal ajena TIENE clases, así que el camino nuevo
    (soft-delete) no debe convertirse en una vía para tocar datos de otra org."""
    _class_with_consumption(setup)
    other_org = make_organization(name='Otra Org')
    make_user('intruso', organization=other_org, role='gym_admin')
    _login(api_client, 'intruso')

    resp = api_client.delete(f'/api/branches/{setup["branch"].id}/')

    assert resp.status_code == 404, resp.content
    setup['branch'].refresh_from_db()
    assert setup['branch'].is_active is True


@pytest.mark.parametrize('role', ['teacher', 'manager', 'monitor', 'student'])
def test_denied_roles_neither_delete_nor_deactivate_branch(api_client, setup, make_user, role):
    """Un rol sin permiso no debe llegar al camino de escritura: ni hard delete ni
    soft delete. `manager` y `monitor` están excluidos a propósito de ADMIN_WRITE_ROLES."""
    _class_with_consumption(setup)  # la sucursal tiene historial → camino de soft-delete
    make_user('sinpermiso', organization=setup['org'], role=role)
    _login(api_client, 'sinpermiso')

    resp = api_client.delete(f'/api/branches/{setup["branch"].id}/')

    assert resp.status_code in (403, 404), resp.content
    setup['branch'].refresh_from_db()
    assert setup['branch'].is_active is True, 'un rol denegado no debe desactivar la sucursal'


# --- D. La guarda cubre TODO lo que cuelga en cascada de Branch ------------------
# Branch tiene 3 FKs entrantes con CASCADE: GymClass.branch, ClassTemplate.branch y
# Holiday.branch. Mirar solo GymClass dejaría a la sucursal como puerta trasera para
# destruir series y recurrencias que `delete_template_safely` sí protege.


def _template_with_recurrence(setup):
    from core.models import ClassTemplate, RecurringEnrollment

    template = ClassTemplate.objects.create(
        organization=setup['org'], branch=setup['branch'], teacher=setup['teacher'],
        name='Serie', weekday=0, start_time='10:00', end_time='11:00',
        capacity=10, start_date=timezone.localdate(),
    )
    recurrence = RecurringEnrollment.objects.create(
        student=setup['student'], class_template=template, start_date=timezone.localdate(),
    )
    return template, recurrence


def test_delete_branch_with_class_templates_does_not_hard_delete(api_client, setup):
    """Sucursal SIN GymClass pero CON una serie: el hard delete arrastraría la serie."""
    template, _ = _template_with_recurrence(setup)
    _login(api_client, 'admin')

    resp = api_client.delete(f'/api/branches/{setup["branch"].id}/')

    from core.models import ClassTemplate
    assert resp.status_code == 400, resp.content
    assert ClassTemplate.objects.filter(id=template.id).exists(), 'la serie debe sobrevivir'
    setup['branch'].refresh_from_db()
    assert setup['branch'].is_active is False


def test_delete_branch_does_not_bypass_the_recurrence_guard(api_client, setup):
    """`delete_template_safely` se NIEGA a borrar una serie con recurrencias de alumnos
    (services/recurrence.py:can_delete_template). Borrar la sucursal no puede ser el
    atajo para lograr exactamente eso."""
    template, recurrence = _template_with_recurrence(setup)
    _login(api_client, 'admin')

    # La vía directa ya está protegida hoy.
    direct = api_client.delete(f'/api/class-templates/{template.id}/')
    assert direct.status_code == 400, direct.content

    api_client.delete(f'/api/branches/{setup["branch"].id}/')

    from core.models import RecurringEnrollment
    assert RecurringEnrollment.objects.filter(id=recurrence.id).exists(), \
        'la recurrencia del alumno no debe desaparecer por la puerta de atrás'


def test_delete_branch_with_holidays_does_not_hard_delete(api_client, setup):
    from core.models import Holiday

    holiday = Holiday.objects.create(
        organization=setup['org'], branch=setup['branch'], date=timezone.localdate(),
        name='Aniversario sede', scope=Holiday.Scope.BRANCH,
    )
    _login(api_client, 'admin')

    resp = api_client.delete(f'/api/branches/{setup["branch"].id}/')

    assert resp.status_code == 400, resp.content
    assert Holiday.objects.filter(id=holiday.id).exists(), 'el feriado de sede debe sobrevivir'


# --- D bis. La FK que NO cascadea: SET_NULL que invierte una semántica ----------
# `TeacherPaymentRule.branch` es SET_NULL, así que el hard delete no borra la regla:
# la deja con branch=NULL. Y en `_match_rule_for_class` una regla sin sucursal es la
# regla COMODÍN que aplica a TODAS las sedes. Borrar la sede convierte una regla
# acotada en una regla global: silencioso, y es plata.


def _scoped_payment_rule(setup, other_branch):
    from core.models import TeacherPaymentRule

    rule = TeacherPaymentRule.objects.create(
        organization=setup['org'], branch=setup['branch'], teacher=setup['teacher'],
        payment_type=TeacherPaymentRule.PaymentType.FIXED_PER_CLASS, amount=50000,
    )
    start = timezone.now() - timedelta(days=1)
    other_class = GymClass.objects.create(
        organization=setup['org'], branch=other_branch, teacher=setup['teacher'],
        name='Clase en la otra sede', start_datetime=start,
        end_datetime=start + timedelta(hours=1), capacity=10,
        status=GymClass.Status.COMPLETED,
    )
    return rule, other_class


def test_delete_branch_with_payment_rules_does_not_hard_delete(api_client, setup, make_organization):
    other_branch = Branch.objects.create(organization=setup['org'], name='Sede Barrio')
    rule, _ = _scoped_payment_rule(setup, other_branch)
    _login(api_client, 'admin')

    resp = api_client.delete(f'/api/branches/{setup["branch"].id}/')

    assert resp.status_code == 400, resp.content
    rule.refresh_from_db()
    assert rule.branch_id == setup['branch'].id, 'la regla no debe perder su alcance de sede'


def test_delete_branch_does_not_turn_scoped_payment_rule_into_wildcard(api_client, setup):
    """El daño concreto: una regla de $50.000/clase acotada a una sede empieza a pagar
    las clases de TODAS las demás sedes."""
    from core.services.teacher_payments import calculate_teacher_payment

    other_branch = Branch.objects.create(organization=setup['org'], name='Sede Barrio')
    _, other_class = _scoped_payment_rule(setup, other_branch)

    before, _ = calculate_teacher_payment(other_class)
    assert before is None, 'precondición: la regla de otra sede no debe aplicar aquí'

    _login(api_client, 'admin')
    api_client.delete(f'/api/branches/{setup["branch"].id}/')

    after, _ = calculate_teacher_payment(other_class)
    assert after is None, (
        'la regla acotada a la sede borrada se volvió comodín y ahora paga clases '
        'de otras sedes'
    )


# --- D ter. La FK PROTECT: la cuenta de cobro propia de la sucursal -------------
# `PaymentAccount.branch` es PROTECT porque ahí `NULL` significa "cuenta PRINCIPAL de la
# organización": un SET_NULL ascendería la cuenta de la sede a principal y desviaría a ese
# MercadoPago el dinero de todas las demás sedes. El endpoint tiene que traducirlo a un 400
# entendible, nunca dejar salir el ProtectedError como 500.


def _branch_payment_account(setup, settings):
    from core.fields import generate_encryption_key
    from core.models import PaymentAccount

    settings.PAYMENTS_ENCRYPTION_KEY = generate_encryption_key()
    return PaymentAccount.objects.create(
        organization=setup['org'], branch=setup['branch'], provider='mercadopago',
        provider_user_id='sede-collector', access_token='AT', refresh_token='RT',
    )


def test_delete_branch_with_payment_account_does_not_hard_delete(api_client, setup, settings):
    account = _branch_payment_account(setup, settings)
    _login(api_client, 'admin')

    resp = api_client.delete(f'/api/branches/{setup["branch"].id}/')

    assert resp.status_code == 400, resp.content
    assert Branch.objects.filter(id=setup['branch'].id).exists()
    setup['branch'].refresh_from_db()
    assert setup['branch'].is_active is False
    account.refresh_from_db()
    assert account.branch_id == setup['branch'].id, \
        'la cuenta de la sede no puede quedar como cuenta principal de la organización'


# --- E. El mensaje no debe prometer lo que el sistema no hace -------------------


def test_error_message_does_not_promise_selector_filtering(api_client, setup):
    """Hoy NADA filtra sucursales inactivas al crear clases (GymClassSerializer.validate
    solo valida existencia y organización). El mensaje no puede afirmar lo contrario."""
    _class_with_consumption(setup)
    _login(api_client, 'admin')

    detail = api_client.delete(f'/api/branches/{setup["branch"].id}/').json()['detail'].lower()

    assert 'no aparecerá al crear' not in detail, 'promesa falsa: el filtro no existe'


def test_payment_account_message_does_not_promise_an_unlink_that_does_not_exist(
        api_client, setup, settings):
    """El mensaje decía "Desvinculá su cuenta de pagos antes de borrarla", pero desconectar
    (`POST /api/payments/disconnect/`) CONSERVA la fila a propósito —histórico y
    reconexión—, así que la FK PROTECT sigue bloqueando y el admin queda en un callejón sin
    salida siguiendo la instrucción. Hoy no existe ninguna acción que libere el bloqueador:
    el texto no puede prometer una."""
    _branch_payment_account(setup, settings)
    _login(api_client, 'admin')

    detail = api_client.delete(f'/api/branches/{setup["branch"].id}/').json()['detail'].lower()

    assert 'desvincul' not in detail, 'promesa falsa: desconectar no borra la fila'
    assert 'antes de borrarla' not in detail, 'no hay ningún paso previo que desbloquee'


def test_inactive_branch_still_accepts_new_classes_today(api_client, setup):
    """Documenta el hueco real detectado en la revisión: desactivar NO impide crear
    clases en esa sucursal. Si algún día se implementa el filtro, este test falla y
    obliga a corregir también el mensaje de la guarda."""
    from core.models import ClassType, Discipline

    setup['branch'].is_active = False
    setup['branch'].save(update_fields=['is_active'])
    class_type = ClassType.objects.create(organization=setup['org'], name='Funcional')
    discipline = Discipline.objects.create(organization=setup['org'], name='Crossfit')
    _login(api_client, 'admin')
    start = timezone.now() + timedelta(days=1)

    resp = api_client.post('/api/classes/', {
        'branch': setup['branch'].id, 'teacher': setup['teacher'].id, 'name': 'Nueva',
        'class_type': class_type.id, 'discipline': discipline.id,
        'start_datetime': start.isoformat(), 'end_datetime': (start + timedelta(hours=1)).isoformat(),
        'capacity': 10,
    }, format='json')

    assert resp.status_code == 201, (
        'Si esto ya no es 201, el filtro de sucursal inactiva se implementó: '
        f'actualizá el mensaje de la guarda en BranchViewSet. Respuesta: {resp.content}'
    )
