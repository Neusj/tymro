"""Integridad: borrar un Plan NO debe poder corromper membresías ni saldos.

`StudentPlan.plan` es FK CASCADE, así que un hard delete de `Plan` arrastra todas las
membresías vendidas y, en cascada, sus `ConsumptionLog`. Los daños son tres y ninguno
deja rastro:

1. **Historial de consumo destruido**: el alumno pagó y usó clases, y no queda registro.
2. **Inscripciones huérfanas**: `Enrollment` cuelga de `GymClass` + `student`, NO del plan.
   Sobreviven en estado `active` respaldadas por una membresía que ya no existe.
3. **Se salta la guarda de `remove_membership`**, que se niega explícitamente a quitar una
   membresía con `classes_used > 0` ("Define una politica de devolucion primero").
   Borrar el plan entero lograba exactamente eso, en bloque y para todos los alumnos.

Regla: si el plan tiene membresías se DESACTIVA (`is_active=False`) en vez de borrarse;
si no tiene ninguna, el hard delete es seguro y se permite.

El patrón —y el motivo de devolver `Response` en vez de `raise`— es el mismo de
`BranchViewSet.destroy`: ver el comentario ahí.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from core.models import (
    Branch,
    ConsumptionLog,
    Enrollment,
    GymClass,
    PaymentTransaction,
    Plan,
    StudentPlan,
)

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
    branch = Branch.objects.create(organization=org, name='Sede Centro')
    admin = make_user('admin', organization=org, role='gym_admin')
    teacher = make_user('teach', organization=org, role='teacher')
    student = make_user('alu', organization=org, role='student', email='alu@gym.cl')
    plan = Plan.objects.create(
        organization=org, name='Pack 10', plan_type='pack', total_classes=10,
        duration_days=30, price=30000,
    )
    return {
        'org': org, 'branch': branch, 'admin': admin, 'teacher': teacher,
        'student': student, 'plan': plan,
    }


def _sold_membership(setup):
    """Una membresía vendida con una clase ya consumida y su inscripción activa."""
    today = timezone.localdate()
    student_plan = StudentPlan.objects.create(
        user=setup['student'], plan=setup['plan'], start_date=today,
        organization_id=setup['plan'].organization_id,
        end_date=today + timedelta(days=30), total_classes=10, classes_used=1,
        final_price=30000,
    )
    start = timezone.now() - timedelta(days=2)
    gym_class = GymClass.objects.create(
        organization=setup['org'], branch=setup['branch'], teacher=setup['teacher'],
        name='Clase', start_datetime=start, end_datetime=start + timedelta(hours=1),
        capacity=10, status=GymClass.Status.COMPLETED,
    )
    enrollment = Enrollment.objects.create(
        gym_class=gym_class, student=setup['student'], status='active',
    )
    log = ConsumptionLog.objects.create(
        user=setup['student'], student_plan=student_plan, class_instance=gym_class,
    )
    return {'student_plan': student_plan, 'enrollment': enrollment, 'log': log}


# --- A. Plan CON membresías: se desactiva, no se borra ---------------------------


def test_delete_plan_with_memberships_does_not_hard_delete(api_client, setup):
    _sold_membership(setup)
    _login(api_client, 'admin')

    resp = api_client.delete(f'/api/plans/{setup["plan"].id}/')

    assert resp.status_code == 400, resp.content
    assert Plan.objects.filter(id=setup['plan'].id).exists(), 'el plan no debe borrarse'


def test_delete_plan_with_memberships_deactivates_it(api_client, setup):
    _sold_membership(setup)
    _login(api_client, 'admin')

    api_client.delete(f'/api/plans/{setup["plan"].id}/')

    setup['plan'].refresh_from_db()
    assert setup['plan'].is_active is False, 'el plan debe quedar desactivado'


def test_delete_plan_with_memberships_preserves_the_membership(api_client, setup):
    sold = _sold_membership(setup)
    _login(api_client, 'admin')

    api_client.delete(f'/api/plans/{setup["plan"].id}/')

    assert StudentPlan.objects.filter(id=sold['student_plan'].id).exists(), \
        'la membresía del alumno debe sobrevivir'


def test_delete_plan_with_memberships_preserves_the_consumption_history(api_client, setup):
    sold = _sold_membership(setup)
    _login(api_client, 'admin')

    api_client.delete(f'/api/plans/{setup["plan"].id}/')

    assert ConsumptionLog.objects.filter(id=sold['log'].id).exists(), \
        'los consumos deben sobrevivir'


def test_delete_plan_does_not_alter_any_classes_used(api_client, setup):
    """El invariante: `classes_used` sigue respaldado por la misma cantidad de
    ConsumptionLog. Con el hard delete desaparecían AMBOS lados —membresía y log— y
    el alumno perdía la prueba de lo que pagó y usó."""
    sold = _sold_membership(setup)
    _login(api_client, 'admin')

    api_client.delete(f'/api/plans/{setup["plan"].id}/')

    student_plan = StudentPlan.objects.get(id=sold['student_plan'].id)
    backing_logs = ConsumptionLog.objects.filter(student_plan=student_plan).count()
    assert student_plan.classes_used == 1, 'el saldo del plan no debe alterarse'
    assert student_plan.classes_used == backing_logs, (
        f'saldo sin respaldo: classes_used={student_plan.classes_used} '
        f'pero hay {backing_logs} consumo(s)'
    )


def test_delete_plan_does_not_orphan_active_enrollments(api_client, setup):
    """`Enrollment` no cuelga del plan: sobrevive a la cascada. Sin la guarda quedaba
    una inscripción `active` respaldada por una membresía inexistente."""
    sold = _sold_membership(setup)
    _login(api_client, 'admin')

    api_client.delete(f'/api/plans/{setup["plan"].id}/')

    enrollment = Enrollment.objects.get(id=sold['enrollment'].id)
    assert enrollment.status == 'active'
    assert StudentPlan.objects.filter(id=sold['student_plan'].id).exists(), (
        'la inscripción quedó viva pero su membresía se borró: exactamente el estado '
        'inconsistente que la guarda debe impedir'
    )


def test_delete_plan_does_not_bypass_the_remove_membership_guard(api_client, setup):
    """`remove_membership` se NIEGA a quitar una membresía con clases usadas. Borrar el
    plan entero no puede ser el atajo para lograr eso mismo en bloque."""
    sold = _sold_membership(setup)
    _login(api_client, 'admin')

    direct = api_client.delete(
        f'/api/plans/{setup["plan"].id}/memberships/{sold["student_plan"].id}/'
    )
    assert direct.status_code == 400, direct.content  # la vía directa ya está protegida

    api_client.delete(f'/api/plans/{setup["plan"].id}/')

    assert StudentPlan.objects.filter(id=sold['student_plan'].id).exists(), \
        'la membresía con clases usadas desapareció por la puerta de atrás'


def test_delete_plan_with_memberships_explains_why(api_client, setup):
    _sold_membership(setup)
    _login(api_client, 'admin')

    resp = api_client.delete(f'/api/plans/{setup["plan"].id}/')

    detail = resp.json()['detail'].lower()
    assert 'desactiv' in detail, f'el mensaje debe explicar que se desactivó: {detail}'
    assert 'historial' in detail, f'el mensaje debe mencionar el historial: {detail}'


def test_deleting_an_already_inactive_plan_with_memberships_stays_blocked(api_client, setup):
    """Segundo intento: el plan ya está inactivo, pero el hard delete sigue corrompiendo
    el historial. Desactivar no puede convertirse en el paso previo para borrar."""
    sold = _sold_membership(setup)
    setup['plan'].is_active = False
    setup['plan'].save(update_fields=['is_active'])
    _login(api_client, 'admin')

    resp = api_client.delete(f'/api/plans/{setup["plan"].id}/')

    assert resp.status_code == 400, resp.content
    assert Plan.objects.filter(id=setup['plan'].id).exists()
    assert StudentPlan.objects.filter(id=sold['student_plan'].id).exists()


def test_superadmin_delete_plan_with_memberships_deactivates_it(api_client, setup, make_user):
    """La guarda de integridad aplica también al superadmin: la cascada corrompe el
    historial igual sin importar quién dispare el borrado."""
    sold = _sold_membership(setup)
    make_user('root', role='superadmin', organization=None)
    _login(api_client, 'root')

    resp = api_client.delete(f'/api/plans/{setup["plan"].id}/')

    assert resp.status_code == 400, resp.content
    setup['plan'].refresh_from_db()
    assert setup['plan'].is_active is False
    assert StudentPlan.objects.filter(id=sold['student_plan'].id).exists()


# --- B. Plan SIN membresías: hard delete normal ----------------------------------


def test_delete_plan_without_memberships_hard_deletes(api_client, setup):
    _login(api_client, 'admin')

    resp = api_client.delete(f'/api/plans/{setup["plan"].id}/')

    assert resp.status_code == 204, resp.content
    assert not Plan.objects.filter(id=setup['plan'].id).exists()


def test_superadmin_delete_plan_without_memberships_hard_deletes(api_client, setup, make_user):
    make_user('root', role='superadmin', organization=None)
    _login(api_client, 'root')

    resp = api_client.delete(f'/api/plans/{setup["plan"].id}/')

    assert resp.status_code == 204, resp.content
    assert not Plan.objects.filter(id=setup['plan'].id).exists()


def test_an_abandoned_checkout_does_not_pin_the_plan_forever(api_client, setup):
    """Un carrito abandonado (`pending`, sin `provider_payment_id`) no movió plata: no
    debe bloquear el borrado de un plan que nunca se vendió."""
    PaymentTransaction.objects.create(
        organization=setup['org'], user=setup['student'], plan=setup['plan'],
        amount=Decimal('30000'), plan_amount=Decimal('30000'), status='pending',
    )
    _login(api_client, 'admin')

    resp = api_client.delete(f'/api/plans/{setup["plan"].id}/')

    assert resp.status_code == 204, resp.content
    assert not Plan.objects.filter(id=setup['plan'].id).exists()


def test_a_charged_payment_pins_the_plan_even_without_a_membership(api_client, setup):
    """`PaymentTransaction.plan` es SET_NULL: borrar el plan no borra el cobro, lo deja
    sin decir QUÉ se compró. Normalmente un pago aprobado ya activó una membresía y la
    guarda anterior alcanza; el hueco es el pago cobrado-sin-activar
    (`test_payment_plan_org_mismatch.py`), que es justo el que hay que poder auditar."""
    tx = PaymentTransaction.objects.create(
        organization=setup['org'], user=setup['student'], plan=setup['plan'],
        amount=Decimal('30000'), plan_amount=Decimal('30000'), status='approved',
        provider_payment_id='PAY-1',
    )
    _login(api_client, 'admin')

    resp = api_client.delete(f'/api/plans/{setup["plan"].id}/')

    assert resp.status_code == 400, resp.content
    tx.refresh_from_db()
    assert tx.plan_id == setup['plan'].id, 'el cobro no puede perder a qué plan corresponde'
    setup['plan'].refresh_from_db()
    assert setup['plan'].is_active is False


# --- B bis. La guarda se libera por el camino legítimo, y NO por el otro ---------


def test_removing_every_membership_frees_the_plan_for_deletion(api_client, setup):
    """El camino legítimo: quitar las membresías una por una (`remove_membership`, que
    valida cada caso) y recién entonces borrar el plan. La guarda no es una cárcel."""
    today = timezone.localdate()
    membership = StudentPlan.objects.create(
        user=setup['student'], plan=setup['plan'], start_date=today,
        organization_id=setup['plan'].organization_id,
        end_date=today + timedelta(days=30), total_classes=10, classes_used=0,
        final_price=30000,
    )
    _login(api_client, 'admin')

    blocked = api_client.delete(f'/api/plans/{setup["plan"].id}/')
    assert blocked.status_code == 400, blocked.content

    removed = api_client.delete(
        f'/api/plans/{setup["plan"].id}/memberships/{membership.id}/'
    )
    assert removed.status_code == 204, removed.content

    freed = api_client.delete(f'/api/plans/{setup["plan"].id}/')
    assert freed.status_code == 204, freed.content
    assert not Plan.objects.filter(id=setup['plan'].id).exists()


def test_remove_membership_is_blocked_by_the_logs_not_just_the_counter(api_client, setup):
    """El bypass de dos pasos: `remove_membership` miraba `classes_used`, y ese contador
    es ESCRIBIBLE (el importador lo declara `updatable`, y una re-importación con las
    'Clases restantes' mal puestas lo baja a 0). Con el contador en 0 y los
    `ConsumptionLog` vivos, quitar la membresía pasaba la guarda, cascadeaba los logs y
    dejaba el plan borrable: la guarda nueva quedaba anulada sin un solo 400.

    El invariante manda sobre el contador: si hay historial de consumo, no se quita.
    """
    sold = _sold_membership(setup)
    StudentPlan.objects.filter(id=sold['student_plan'].id).update(classes_used=0)
    _login(api_client, 'admin')

    resp = api_client.delete(
        f'/api/plans/{setup["plan"].id}/memberships/{sold["student_plan"].id}/'
    )

    assert resp.status_code == 400, resp.content
    assert StudentPlan.objects.filter(id=sold['student_plan'].id).exists()
    assert ConsumptionLog.objects.filter(id=sold['log'].id).exists(), \
        'el historial de consumo se borró en cascada con la membresía'


def test_the_two_step_bypass_no_longer_reaches_the_hard_delete(api_client, setup):
    """La cadena completa, extremo a extremo: contador a 0 → quitar membresía → borrar
    plan. Tiene que romperse en el primer eslabón."""
    sold = _sold_membership(setup)
    StudentPlan.objects.filter(id=sold['student_plan'].id).update(classes_used=0)
    _login(api_client, 'admin')

    api_client.delete(f'/api/plans/{setup["plan"].id}/memberships/{sold["student_plan"].id}/')
    resp = api_client.delete(f'/api/plans/{setup["plan"].id}/')

    assert resp.status_code == 400, resp.content
    assert Plan.objects.filter(id=setup['plan'].id).exists()
    assert ConsumptionLog.objects.filter(id=sold['log'].id).exists()


def test_an_imported_membership_with_carried_balance_stays_protected(api_client, setup):
    """No-regresión de la guarda vieja: una membresía onboardeada por importador tiene
    `classes_used` arrastrado y CERO logs a propósito (el consumo es anterior al sistema).
    El contador sigue bloqueando ahí; la comprobación nueva se SUMA, no reemplaza."""
    today = timezone.localdate()
    imported = StudentPlan.objects.create(
        user=setup['student'], plan=setup['plan'], start_date=today,
        organization_id=setup['plan'].organization_id,
        end_date=today + timedelta(days=30), total_classes=10, classes_used=3,
        final_price=30000,
    )
    assert not ConsumptionLog.objects.filter(student_plan=imported).exists()
    _login(api_client, 'admin')

    resp = api_client.delete(f'/api/plans/{setup["plan"].id}/memberships/{imported.id}/')

    assert resp.status_code == 400, resp.content
    assert StudentPlan.objects.filter(id=imported.id).exists()


# --- B ter. El soft-delete no puede perjudicar a quien ya pagó -------------------


def test_a_student_who_paid_can_still_reserve_on_a_soft_deleted_plan(api_client, setup):
    """La garantía central del soft-delete: `get_active_student_plan` filtra por
    `StudentPlan.is_active`, NO por `plan__is_active`. Retirar un plan del catálogo no
    puede dejar sin reservar al alumno que ya lo compró."""
    from core.models import ClassType

    today = timezone.localdate()
    StudentPlan.objects.create(
        user=setup['student'], plan=setup['plan'], start_date=today,
        organization_id=setup['plan'].organization_id,
        end_date=today + timedelta(days=30), total_classes=10, classes_used=0,
        final_price=30000,
    )
    start = timezone.now() + timedelta(days=2)
    gym_class = GymClass.objects.create(
        organization=setup['org'], branch=setup['branch'], teacher=setup['teacher'],
        class_type=ClassType.objects.create(organization=setup['org'], name='Funcional'),
        name='Futura', start_datetime=start, end_datetime=start + timedelta(hours=1),
        capacity=10,
    )

    _login(api_client, 'admin')
    api_client.delete(f'/api/plans/{setup["plan"].id}/')  # queda desactivado
    setup['plan'].refresh_from_db()
    assert setup['plan'].is_active is False  # precondición

    _login(api_client, 'alu')
    resp = api_client.post('/api/enrollments/', {
        'gym_class': gym_class.id, 'student': setup['student'].id, 'status': 'active',
    }, format='json')

    assert resp.status_code == 201, (
        f'el alumno que pagó perdió la capacidad de reservar al retirarse el plan: {resp.content}'
    )


def test_a_soft_deleted_plan_leaves_the_students_catalog(api_client, setup):
    """El otro lado: retirado sí desaparece de la vitrina. Es la interacción entre la
    guarda de borrado y el filtro de visibilidad del alumno."""
    _sold_membership(setup)
    _login(api_client, 'admin')
    api_client.delete(f'/api/plans/{setup["plan"].id}/')

    _login(api_client, 'alu')
    listing = api_client.get('/api/plans/')

    rows = listing.json()
    assert setup['plan'].id not in {row['id'] for row in rows}, \
        'el plan retirado sigue ofreciéndose al alumno'


def test_a_rejected_payment_also_pins_the_plan_on_purpose(api_client, setup):
    """Declaración de intención: el criterio es "llegó al proveedor", no "terminó aprobada".
    Un rechazo también es historial de cobro, y el plan es lo único que dice qué se intentó
    cobrar (`PaymentTransaction.plan` es SET_NULL). La consecuencia es leve —el plan se
    desactiva en vez de borrarse— así que se prefiere el criterio simple."""
    PaymentTransaction.objects.create(
        organization=setup['org'], user=setup['student'], plan=setup['plan'],
        amount=Decimal('30000'), plan_amount=Decimal('30000'), status='rejected',
        provider_payment_id='PAY-NO',
    )
    _login(api_client, 'admin')

    resp = api_client.delete(f'/api/plans/{setup["plan"].id}/')

    assert resp.status_code == 400, resp.content
    assert Plan.objects.filter(id=setup['plan'].id).exists()


# --- C. El scoping por organización sigue intacto -------------------------------


def test_gym_admin_cannot_delete_plan_from_another_org(
    api_client, setup, make_organization, make_user,
):
    other_org = make_organization(name='Otra Org')
    make_user('intruso', organization=other_org, role='gym_admin')
    _login(api_client, 'intruso')

    resp = api_client.delete(f'/api/plans/{setup["plan"].id}/')

    assert resp.status_code == 404, resp.content
    setup['plan'].refresh_from_db()
    assert setup['plan'].is_active is True, 'no debe desactivar planes ajenos'


def test_gym_admin_cannot_deactivate_plan_with_memberships_from_another_org(
    api_client, setup, make_organization, make_user,
):
    """El caso peligroso: el plan ajeno TIENE membresías, así que el camino nuevo
    (soft-delete) no debe convertirse en una vía para escribir en otra org."""
    _sold_membership(setup)
    other_org = make_organization(name='Otra Org')
    make_user('intruso', organization=other_org, role='gym_admin')
    _login(api_client, 'intruso')

    resp = api_client.delete(f'/api/plans/{setup["plan"].id}/')

    assert resp.status_code == 404, resp.content
    setup['plan'].refresh_from_db()
    assert setup['plan'].is_active is True


@pytest.mark.parametrize('role', ['teacher', 'manager', 'monitor', 'student'])
def test_denied_roles_neither_delete_nor_deactivate_plan(api_client, setup, make_user, role):
    """Un rol sin permiso no llega al camino de escritura: ni hard delete ni soft delete.
    `manager` está excluido de todo lo financiero (`FinancialResourcePermission`)."""
    _sold_membership(setup)
    make_user('sinpermiso', organization=setup['org'], role=role, email=f'{role}@gym.cl')
    _login(api_client, 'sinpermiso')

    resp = api_client.delete(f'/api/plans/{setup["plan"].id}/')

    assert resp.status_code in (403, 404), resp.content
    setup['plan'].refresh_from_db()
    assert setup['plan'].is_active is True, 'un rol denegado no debe desactivar el plan'
