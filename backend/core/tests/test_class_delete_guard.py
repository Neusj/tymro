"""Integridad: borrar una GymClass debe devolver el consumo al saldo del alumno.

`ConsumptionLog.class_instance` es CASCADE, así que el hard delete de una clase borra
sus consumos SIN decrementar `StudentPlan.classes_used` (ese contador solo baja por
`rollback_consumption_for_enrollment`, que la cascada nunca ejecuta). Resultado: el
alumno queda con clases consumidas fantasma. Es el mismo daño que ya cubre la guarda
de borrado de sucursal, pero por la puerta chica: borrando las clases una por una.

El invariante que se testea es `classes_used == count(ConsumptionLog)`, no
`classes_used == N`: lo segundo pasa incluso con el bug presente.
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
    branch = Branch.objects.create(organization=org, name='Sede')
    return {'org': org, 'admin': admin, 'teacher': teacher, 'student': student, 'branch': branch}


def _past_class(setup, offset_days=2):
    start = timezone.now() - timedelta(days=offset_days)
    return GymClass.objects.create(
        organization=setup['org'], branch=setup['branch'], teacher=setup['teacher'],
        name=f'Clase -{offset_days}d', start_datetime=start,
        end_datetime=start + timedelta(hours=1), capacity=10,
        status=GymClass.Status.COMPLETED,
    )


def _plan_with_consumptions(setup, gym_classes):
    """Un StudentPlan cuyo `classes_used` refleja exactamente los consumos creados."""
    today = timezone.localdate()
    plan = Plan.objects.create(
        organization=setup['org'], name='Pack 10', plan_type='pack',
        total_classes=10, duration_days=30, price=30000,
    )
    student_plan = StudentPlan.objects.create(
        user=setup['student'], plan=plan, start_date=today - timedelta(days=5),
        end_date=today + timedelta(days=30), total_classes=10,
        classes_used=len(gym_classes), final_price=30000,
    )
    for gym_class in gym_classes:
        Enrollment.objects.create(gym_class=gym_class, student=setup['student'], status='active')
        ConsumptionLog.objects.create(
            user=setup['student'], student_plan=student_plan, class_instance=gym_class,
        )
    return student_plan


def _assert_balance_matches_logs(student_plan):
    student_plan.refresh_from_db()
    backing = ConsumptionLog.objects.filter(student_plan=student_plan).count()
    assert student_plan.classes_used == backing, (
        f'saldo fantasma: classes_used={student_plan.classes_used} pero solo hay '
        f'{backing} consumo(s) que lo respalden'
    )


# --- A. Borrar clase CON consumo devuelve el saldo -------------------------------


def test_delete_class_with_consumption_refunds_the_balance(api_client, setup):
    gym_class = _past_class(setup)
    student_plan = _plan_with_consumptions(setup, [gym_class])
    _login(api_client, 'admin')

    resp = api_client.delete(f'/api/classes/{gym_class.id}/')

    assert resp.status_code == 204, resp.content
    student_plan.refresh_from_db()
    assert student_plan.classes_used == 0, 'el consumo de la clase borrada debe devolverse'


def test_delete_class_leaves_no_phantom_balance(api_client, setup):
    gym_class = _past_class(setup)
    student_plan = _plan_with_consumptions(setup, [gym_class])
    _login(api_client, 'admin')

    api_client.delete(f'/api/classes/{gym_class.id}/')

    _assert_balance_matches_logs(student_plan)


def test_delete_class_removes_its_consumption_logs(api_client, setup):
    gym_class = _past_class(setup)
    _plan_with_consumptions(setup, [gym_class])
    _login(api_client, 'admin')

    api_client.delete(f'/api/classes/{gym_class.id}/')

    assert not ConsumptionLog.objects.filter(class_instance_id=gym_class.id).exists()
    assert not GymClass.objects.filter(id=gym_class.id).exists()


def test_delete_one_of_two_classes_only_refunds_that_one(api_client, setup):
    """El saldo debe bajar exactamente 1, no resetearse ni quedarse quieto."""
    kept = _past_class(setup, offset_days=3)
    removed = _past_class(setup, offset_days=2)
    student_plan = _plan_with_consumptions(setup, [kept, removed])
    assert student_plan.classes_used == 2
    _login(api_client, 'admin')

    api_client.delete(f'/api/classes/{removed.id}/')

    student_plan.refresh_from_db()
    assert student_plan.classes_used == 1
    _assert_balance_matches_logs(student_plan)
    assert ConsumptionLog.objects.filter(class_instance_id=kept.id).exists(), \
        'el consumo de la clase que sobrevive no debe tocarse'


def test_delete_future_class_with_consumption_also_refunds(api_client, setup):
    """La clase futura ya la cubría la política de cancelación; el borrado debe
    devolver el saldo igual, sin depender de la fecha."""
    start = timezone.now() + timedelta(days=1)
    gym_class = GymClass.objects.create(
        organization=setup['org'], branch=setup['branch'], teacher=setup['teacher'],
        name='Futura', start_datetime=start, end_datetime=start + timedelta(hours=1),
        capacity=10, status=GymClass.Status.SCHEDULED,
    )
    student_plan = _plan_with_consumptions(setup, [gym_class])
    _login(api_client, 'admin')

    api_client.delete(f'/api/classes/{gym_class.id}/')

    student_plan.refresh_from_db()
    assert student_plan.classes_used == 0
    _assert_balance_matches_logs(student_plan)


def test_delete_class_does_not_touch_other_students_plans(api_client, setup, make_user):
    """Dos alumnos en la misma clase: ambos deben recuperar su propia clase, y el
    saldo de uno no puede descontarse del otro."""
    gym_class = _past_class(setup)
    plan_a = _plan_with_consumptions(setup, [gym_class])

    other = make_user('alu2', organization=setup['org'], role='student', email='alu2@gym.cl')
    today = timezone.localdate()
    plan_b = StudentPlan.objects.create(
        user=other, plan=plan_a.plan, start_date=today - timedelta(days=5),
        end_date=today + timedelta(days=30), total_classes=10, classes_used=1,
        final_price=30000,
    )
    Enrollment.objects.create(gym_class=gym_class, student=other, status='active')
    ConsumptionLog.objects.create(user=other, student_plan=plan_b, class_instance=gym_class)

    _login(api_client, 'admin')
    api_client.delete(f'/api/classes/{gym_class.id}/')

    plan_a.refresh_from_db()
    plan_b.refresh_from_db()
    assert plan_a.classes_used == 0
    assert plan_b.classes_used == 0


# --- B. Borrar clase SIN consumo: borrado normal ---------------------------------


def test_delete_class_without_consumption_deletes_normally(api_client, setup):
    gym_class = _past_class(setup)
    _login(api_client, 'admin')

    resp = api_client.delete(f'/api/classes/{gym_class.id}/')

    assert resp.status_code == 204, resp.content
    assert not GymClass.objects.filter(id=gym_class.id).exists()


def test_delete_class_with_enrollment_but_no_consumption(api_client, setup):
    """Inscripción sin ConsumptionLog (p. ej. clase de prueba): no hay nada que
    devolver y el borrado debe seguir funcionando."""
    gym_class = _past_class(setup)
    Enrollment.objects.create(
        gym_class=gym_class, student=setup['student'], status='active', is_trial=True,
    )
    _login(api_client, 'admin')

    resp = api_client.delete(f'/api/classes/{gym_class.id}/')

    assert resp.status_code == 204, resp.content
    assert not GymClass.objects.filter(id=gym_class.id).exists()


# --- C. Scoping por organización y permisos -------------------------------------


def test_gym_admin_cannot_delete_class_from_another_org(api_client, setup, make_organization, make_user):
    gym_class = _past_class(setup)
    student_plan = _plan_with_consumptions(setup, [gym_class])
    other_org = make_organization(name='Otra Org')
    make_user('intruso', organization=other_org, role='gym_admin')
    _login(api_client, 'intruso')

    resp = api_client.delete(f'/api/classes/{gym_class.id}/')

    assert resp.status_code == 404, resp.content
    assert GymClass.objects.filter(id=gym_class.id).exists()
    student_plan.refresh_from_db()
    assert student_plan.classes_used == 1, 'no debe tocar saldos de otra organización'


def test_manager_can_delete_class_and_consumption_is_reverted(api_client, setup, make_user):
    """`roles.is_org_admin` incluye manager, así que manager llega a este borrado:
    la reversión del consumo debe aplicar igual."""
    gym_class = _past_class(setup)
    student_plan = _plan_with_consumptions(setup, [gym_class])
    make_user('gerente', organization=setup['org'], role='manager')
    _login(api_client, 'gerente')

    resp = api_client.delete(f'/api/classes/{gym_class.id}/')

    assert resp.status_code == 204, resp.content
    student_plan.refresh_from_db()
    assert student_plan.classes_used == 0
    _assert_balance_matches_logs(student_plan)


@pytest.mark.parametrize('role', ['teacher', 'monitor', 'student'])
def test_denied_roles_cannot_delete_class(api_client, setup, make_user, role):
    gym_class = _past_class(setup)
    student_plan = _plan_with_consumptions(setup, [gym_class])
    if role == 'teacher':
        # El profesor dueño de la clase SÍ la ve en su queryset: el 403 debe venir
        # del check de permisos, no de un 404 accidental.
        gym_class.teacher = make_user('otroprofe', organization=setup['org'], role='teacher')
        gym_class.save(update_fields=['teacher'])
        _login(api_client, 'otroprofe')
    else:
        make_user('sinpermiso', organization=setup['org'], role=role)
        _login(api_client, 'sinpermiso')

    resp = api_client.delete(f'/api/classes/{gym_class.id}/')

    assert resp.status_code in (403, 404), resp.content
    assert GymClass.objects.filter(id=gym_class.id).exists()
    student_plan.refresh_from_db()
    assert student_plan.classes_used == 1, 'un rol denegado no debe alterar saldos'
