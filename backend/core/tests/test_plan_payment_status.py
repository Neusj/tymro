"""`payment_status` — EJE ORTOGONAL de pago en la fuente unica (8.1).

`describe_student_plan` ya publicaba la VIGENCIA (active/expired/exhausted/upcoming/
inactive/no_plan). 8.1 le agrega un SEGUNDO eje, independiente: si esa membresia esta
pagada o no. Son dos preguntas distintas sobre la misma fila y no se colapsan: un plan
puede estar `active` Y `unpaid` a la vez, y eso NO lo vuelve inutilizable.

Este archivo fija tres cosas:

1. La derivacion PROVISIONAL de los tres valores (`free` / `paid` / `unpaid`) a partir de lo
   que ya existe hoy en `StudentPlan` —no hay modelo de pago manual todavia, eso es 8.2—.
2. La ORTOGONALIDAD: el eje de pago no toca `is_usable`, `validity_status` ni `reason_code`.
   Deber plata no bloquea (el bloqueo por deuda, si se decide, es otra tarea).
3. La REDACCION: `payment_status` es dato financiero puro, asi que el monitor no lo recibe.
   A diferencia de los cuatro campos de 7.3, aca se oculta SIEMPRE y no solo cuando el plan
   bloquea: si la ausencia del campo dependiera del estado de pago, la ausencia MISMA seria
   el dato.
"""
from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from core.models import (Branch, Enrollment, GymClass,
                         OrganizationExpiryNotificationConfig, PaymentTransaction, Plan,
                         StudentPlan)
from core.serializers import StudentPlanSerializer
from core.services.plans import PlanPaymentStatus, PlanStatus, describe_student_plan

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()


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


def _transaction(membership, *, status='approved', organization=None, amount=30000,
                 plan_amount=None, enrollment_fee_amount=0, user=None):
    """Cobro ligado a `membership` por la FK de salida `student_plan`.

    Es la unica contraparte financiera que existe hoy: la escribe `apply_provider_payment`
    cuando MercadoPago aprueba (`payments.py`). `organization` se deja parametrizable a
    proposito para poder construir el caso cross-tenant, que ninguna constraint impide.
    """
    return PaymentTransaction.objects.create(
        organization=organization or membership.organization,
        user=user or membership.user,
        provider='mercadopago',
        status=status,
        amount=amount,
        plan_amount=amount if plan_amount is None else plan_amount,
        enrollment_fee_amount=enrollment_fee_amount,
        plan=membership.plan,
        student_plan=membership,
    )


def _manual_payment(membership, *, organization=None, amount=30000, reference='',
                    recorded_by=None):
    """Cobro fuera de linea ligado a `membership`. `organization` es parametrizable a
    proposito: ninguna constraint impide la fila cross-tenant y hay que poder construirla."""
    from core.models import ManualPayment
    return ManualPayment.objects.create(
        organization=organization or membership.organization,
        student_plan=membership,
        amount=amount,
        reference=reference,
        recorded_by=recorded_by,
    )


def _state(membership):
    return describe_student_plan(membership, TODAY)


@pytest.fixture
def student_with_plan(make_organization, make_user):
    org = make_organization()
    student = make_user('stu-pay', organization=org, role='student')
    return org, student, _plan(org)


# --------------------------------------------------------------------------------------
# 1. Derivacion provisional de los tres valores
# --------------------------------------------------------------------------------------

def test_membership_sold_at_zero_is_free(student_with_plan):
    """Beca / giftcard: no hay nada que cobrar, asi que no es una deuda ni un cobro."""
    org, student, plan = student_with_plan
    membership = _membership(student, plan, final_price=0)

    assert _state(membership).payment_status == PlanPaymentStatus.FREE


def test_membership_with_an_approved_transaction_is_paid(student_with_plan):
    org, student, plan = student_with_plan
    membership = _membership(student, plan, final_price=30000)
    _transaction(membership, status='approved')

    assert _state(membership).payment_status == PlanPaymentStatus.PAID


def test_membership_with_a_price_and_no_transaction_is_unpaid(student_with_plan):
    """`activate_student_plan` no crea ninguna contraparte financiera por si sola: el eje de
    pago depende SIEMPRE de una transaccion o un `ManualPayment` colgados aparte.

    Desde 8.3, `POST /api/plans/assign/` ya no puede nacer asi -exige declarar `payment`
    (`free` o `manual`) y por eso queda `free` o `paid`-. Este `unpaid` sigue siendo real: lo
    dejan filas legadas, el importador, el admin de Django o un checkout que cobro la
    matricula pero no el plan.
    """
    org, student, plan = student_with_plan
    membership = _membership(student, plan, final_price=30000)

    assert _state(membership).payment_status == PlanPaymentStatus.UNPAID


@pytest.mark.parametrize('status', ['pending', 'in_process', 'rejected', 'cancelled',
                                    'refunded'])
def test_only_an_approved_transaction_counts_as_paid(student_with_plan, status):
    """Un checkout abandonado deja una tx `pending` viva: no es un cobro.

    `refunded` tambien queda fuera: si la plata se devolvio, el plan no esta pagado.
    """
    org, student, plan = student_with_plan
    membership = _membership(student, plan, final_price=30000)
    _transaction(membership, status=status)

    assert _state(membership).payment_status == PlanPaymentStatus.UNPAID


def test_an_approved_transaction_of_another_organization_does_not_count(
        student_with_plan, make_organization, make_user):
    """Aislamiento cross-tenant en la derivacion, no solo en el queryset que la alimenta.

    `PaymentTransaction.student_plan` es una FK PROPIA: nada en el esquema obliga a que la
    organizacion de la transaccion sea la que vendio la membresia. Seguir la FK sin
    intersectar `organization_id` es el agujero multitenant mas repetido del proyecto, y
    aca el efecto seria que un cobro de la org B le declare pagada una deuda a la org A.
    """
    org, student, plan = student_with_plan
    membership = _membership(student, plan, final_price=30000)
    other_org = make_organization()
    _transaction(membership, status='approved', organization=other_org,
                 user=make_user('stu-otra-org', organization=other_org, role='student'))

    assert _state(membership).payment_status == PlanPaymentStatus.UNPAID


def test_membership_without_a_recorded_price_is_not_free(student_with_plan):
    """`final_price` es NULLABLE. Sin precio registrado no se puede afirmar "beca".

    `free` significa que el gimnasio decidio no cobrar; NULL significa que no se sabe cuanto
    se vendio. Colapsarlos haria que una fila sin precio —creada por el admin de Django o
    arrastrada de datos viejos— se declare sola sin deuda.
    """
    org, student, plan = student_with_plan
    membership = _membership(student, plan, final_price=None)

    assert _state(membership).payment_status == PlanPaymentStatus.UNPAID


def test_a_free_membership_stays_free_even_with_a_transaction(student_with_plan):
    """`free` gana sobre `paid`: si no habia nada que cobrar, no hay cobro que reconocer."""
    org, student, plan = student_with_plan
    membership = _membership(student, plan, final_price=0)
    _transaction(membership, status='approved')

    assert _state(membership).payment_status == PlanPaymentStatus.FREE


def test_without_a_membership_there_is_no_payment_axis():
    """Sin membresia no hay nada pagado ni adeudado: el eje no aplica, y eso no es `free`.

    Publicar `free` para "sin plan" convertiria la ausencia de plan en una beca.
    """
    state = describe_student_plan(None, TODAY)

    assert state.status == PlanStatus.NO_PLAN
    assert state.payment_status is None


def test_a_matricula_only_transaction_does_not_pay_the_plan(student_with_plan):
    """DECISION A de 8.2: pagar la matricula no paga el plan.

    Reemplaza el pin `_PROVISIONAL`. `apply_provider_payment` setea `tx.student_plan` en
    los DOS caminos: cuando el cobro compro el plan y cuando solo pago la MATRICULA de una
    membresia ya existente (`payments.py`, rama `target_student_plan`). Esa segunda tx
    tiene `plan_amount == 0`: no pago el plan, pago la matricula. La regla provisional de
    8.1 —"hay una tx aprobada ligada por `student_plan`"— no las distinguia, asi que un
    plan asignado a mano por el admin (impago) cuyo alumno pago su matricula en linea salia
    `paid`. 8.2 filtra por `plan_amount > 0` y esta membresia queda `unpaid`.
    """
    org, student, plan = student_with_plan
    membership = _membership(student, plan, final_price=30000, enrollment_fee=15000,
                             enrollment_fee_paid_at=timezone.now())
    _transaction(membership, status='approved', amount=15000, plan_amount=0,
                 enrollment_fee_amount=15000)

    assert _state(membership).payment_status == PlanPaymentStatus.UNPAID


def test_a_manual_payment_makes_the_membership_paid(student_with_plan):
    """Cobertura minima obligatoria #1: un `ManualPayment` paga la membresia sin que exista
    ninguna transaccion de MercadoPago."""
    org, student, plan = student_with_plan
    membership = _membership(student, plan, final_price=30000)
    _manual_payment(membership)

    assert _state(membership).payment_status == PlanPaymentStatus.PAID


def test_a_manual_payment_of_another_organization_does_not_count(
        student_with_plan, make_organization):
    """Cobertura #3 (mitad derivacion): `ManualPayment.student_plan` es una FK PROPIA.

    Sin intersectar `organization_id`, un cobro registrado por la org B le declararia
    pagada una deuda de la org A.
    """
    org, student, plan = student_with_plan
    membership = _membership(student, plan, final_price=30000)
    other_org = make_organization()
    _manual_payment(membership, organization=other_org)

    assert _state(membership).payment_status == PlanPaymentStatus.UNPAID


def test_a_manual_payment_pays_a_plan_whose_only_transaction_was_the_matricula(
        student_with_plan):
    """Cierra el par con el test anterior: lo que arregla la deuda es el registro del
    cobro, no la transaccion de matricula que ya estaba colgada de la membresia."""
    org, student, plan = student_with_plan
    membership = _membership(student, plan, final_price=30000, enrollment_fee=15000,
                             enrollment_fee_paid_at=timezone.now())
    _transaction(membership, status='approved', amount=15000, plan_amount=0,
                 enrollment_fee_amount=15000)
    _manual_payment(membership)

    assert _state(membership).payment_status == PlanPaymentStatus.PAID


def test_a_free_membership_stays_free_even_with_a_manual_payment(student_with_plan):
    """`FREE` gana sobre todo: registrar un cobro no reescribe la decision comercial de
    no cobrar."""
    org, student, plan = student_with_plan
    membership = _membership(student, plan, final_price=0)
    _manual_payment(membership)

    assert _state(membership).payment_status == PlanPaymentStatus.FREE


def test_a_partial_manual_payment_still_reads_as_paid(student_with_plan):
    """El eje NO tiene estado parcial: `amount` no se compara nunca contra `final_price`,
    asi que un abono menor a la deuda total sigue leyendose `paid`."""
    org, student, plan = student_with_plan
    membership = _membership(student, plan, final_price=30000)
    _manual_payment(membership, amount=10000)

    assert _state(membership).payment_status == PlanPaymentStatus.PAID


def test_a_manual_payment_does_not_pay_a_different_membership(student_with_plan):
    """Guarda contra una derivacion que agrupe por `user` en vez de por `student_plan`: el
    mismo alumno con dos membresias, pagar la A no puede pagar la B."""
    org, student, plan = student_with_plan
    membership_a = _membership(student, plan, final_price=30000)
    other_plan = _plan(org, name='Otro pack')
    membership_b = _membership(student, other_plan, final_price=30000)
    _manual_payment(membership_a)

    assert _state(membership_a).payment_status == PlanPaymentStatus.PAID
    assert _state(membership_b).payment_status == PlanPaymentStatus.UNPAID


@pytest.mark.parametrize(
    'kwargs,expected_status',
    [
        ({'classes_used': 2}, PlanStatus.ACTIVE),
        ({'classes_used': 10}, PlanStatus.EXHAUSTED),
        # La matricula impaga ya no es un estado de vigencia (8.4): deriva ACTIVE igual que
        # la fila sin matricula, y viaja aparte en `enrollment_fee_status`.
        ({'classes_used': 2, 'enrollment_fee': 15000}, PlanStatus.ACTIVE),
        ({'is_active': False}, PlanStatus.INACTIVE),
        ({'start_offset': 3, 'end_offset': 30}, PlanStatus.UPCOMING),
        ({'start_offset': -40, 'end_offset': -10}, PlanStatus.EXPIRED),
    ],
)
def test_a_manual_payment_does_not_change_the_validity_vocabulary(
        student_with_plan, kwargs, expected_status):
    """Cobertura #5: un `ManualPayment` no le agrega un valor nuevo al vocabulario de
    vigencia. Mismos seis estados que `test_the_payment_axis_never_changes_the_validity_vocabulary`,
    ahora con la contraparte financiera nueva."""
    org, student, plan = student_with_plan
    membership = _membership(student, plan, final_price=30000, **kwargs)
    _manual_payment(membership)

    state = _state(membership)

    assert state.status == expected_status
    assert state.label
    assert state.alert_message


def test_paying_manually_does_not_revive_an_expired_membership(student_with_plan):
    """El reverso del anterior con la contraparte manual: pagar no arregla la vigencia."""
    org, student, plan = student_with_plan
    membership = _membership(student, plan, start_offset=-40, end_offset=-10)
    _manual_payment(membership)

    state = _state(membership)

    assert state.payment_status == PlanPaymentStatus.PAID
    assert state.status == PlanStatus.EXPIRED
    assert state.is_usable is False


def test_the_serializer_resolves_the_manual_payment_axis_once_per_membership(
        student_with_plan):
    """Espejo de `test_the_serializer_resolves_the_payment_axis_once_per_membership` para
    la segunda FK inversa: sin memoizar, cada uno de los siete campos derivados del
    serializer recorreria `manual_payments` de nuevo."""
    org, student, plan = student_with_plan
    membership = _membership(student, plan, final_price=30000)
    _manual_payment(membership)

    with CaptureQueriesContext(connection) as queries:
        data = StudentPlanSerializer(membership).data

    assert data['payment_status'] == 'paid'
    payment_queries = [
        query for query in queries.captured_queries
        if 'core_manualpayment' in query['sql'].lower()
    ]
    assert len(payment_queries) == 1, payment_queries


def test_the_roster_does_not_query_manual_payments_once_per_student(api_client, roster,
                                                                    make_user):
    """Mismo N+1 que `test_the_roster_does_not_query_payments_once_per_student`, ahora con
    la FK inversa de `ManualPayment`: se compara el mismo endpoint con un alumno y con tres,
    sembrando `ManualPayment` en vez de `PaymentTransaction`."""
    plan = _plan(roster['org'], name='Pack 10')
    membership = _membership(roster['student'], plan, classes_used=2, final_price=30000)
    _manual_payment(membership)
    api_client.force_authenticate(user=roster['admin'])
    url = f'/api/classes/{roster["gym_class"].id}/enrolled-students/'

    with CaptureQueriesContext(connection) as one_student:
        first = api_client.get(url)
    assert first.status_code == 200
    assert first.json()[0]['plan_payment_status'] == 'paid'

    for index in range(2):
        extra = make_user(f'stu-extra-manualpay-{index}', organization=roster['org'],
                          role='student')
        Enrollment.objects.create(gym_class=roster['gym_class'], student=extra,
                                  status='active')
        extra_membership = _membership(extra, plan, classes_used=2, final_price=30000)
        _manual_payment(extra_membership)

    with CaptureQueriesContext(connection) as three_students:
        second = api_client.get(url)
    assert second.status_code == 200
    assert len(second.json()) == 3

    assert len(three_students) == len(one_student)


def test_the_monitor_never_receives_the_payment_status_of_a_manually_paid_membership(
        api_client, roster):
    """Cobertura #6: la redaccion incondicional del monitor tambien cubre el pago manual,
    no solo la transaccion aprobada de MercadoPago."""
    plan = _plan(roster['org'], name='Pack 10')
    membership = _membership(roster['student'], plan, classes_used=2, final_price=30000)
    _manual_payment(membership)

    row = _roster_row(api_client, roster, actor='monitor')

    assert 'plan_payment_status' not in row


# --------------------------------------------------------------------------------------
# 2. Ortogonalidad: el eje de pago no toca la vigencia
# --------------------------------------------------------------------------------------

def test_an_unpaid_membership_is_still_usable(student_with_plan):
    """LA prueba del eje separado: deber plata no bloquea en 8.1.

    Si `unpaid` tocara `is_usable`, el alumno con un plan asignado a mano quedaria sin poder
    reservar el dia que se publique el campo —y eso es una decision de producto que todavia
    no se tomo—.
    """
    org, student, plan = student_with_plan
    membership = _membership(student, plan, classes_used=2, final_price=30000)

    state = _state(membership)

    assert state.payment_status == PlanPaymentStatus.UNPAID
    assert state.is_usable is True
    assert state.status == PlanStatus.ACTIVE
    assert state.reason_code is None


@pytest.mark.parametrize(
    'kwargs,expected_status',
    [
        ({'classes_used': 2}, PlanStatus.ACTIVE),
        ({'classes_used': 10}, PlanStatus.EXHAUSTED),
        # Idem arriba: matricula impaga ya no es un estado de vigencia (8.4).
        ({'classes_used': 2, 'enrollment_fee': 15000}, PlanStatus.ACTIVE),
        ({'is_active': False}, PlanStatus.INACTIVE),
        ({'start_offset': 3, 'end_offset': 30}, PlanStatus.UPCOMING),
        ({'start_offset': -40, 'end_offset': -10}, PlanStatus.EXPIRED),
    ],
)
@pytest.mark.parametrize('final_price,paid', [(0, False), (30000, False), (30000, True)])
def test_the_payment_axis_never_changes_the_validity_vocabulary(
        student_with_plan, kwargs, expected_status, final_price, paid):
    """Los seis estados de vigencia salen igual con cualquier estado de pago.

    Es la contraprueba de que 8.1 agrego un eje y no un valor nuevo al vocabulario viejo.
    """
    org, student, plan = student_with_plan
    membership = _membership(student, plan, final_price=final_price, **kwargs)
    if paid:
        _transaction(membership, status='approved')

    state = _state(membership)

    assert state.status == expected_status
    assert state.label  # la etiqueta sigue siendo la de vigencia, no la de pago
    assert state.alert_message


def test_paying_does_not_revive_an_expired_membership(student_with_plan):
    """El reverso del anterior: pagar no arregla la vigencia."""
    org, student, plan = student_with_plan
    membership = _membership(student, plan, start_offset=-40, end_offset=-10)
    _transaction(membership, status='approved')

    state = _state(membership)

    assert state.payment_status == PlanPaymentStatus.PAID
    assert state.status == PlanStatus.EXPIRED
    assert state.is_usable is False


# --------------------------------------------------------------------------------------
# 3. Lectura: serializer de membresia
# --------------------------------------------------------------------------------------

def test_serializer_publishes_payment_status_unpaid(student_with_plan):
    org, student, plan = student_with_plan
    membership = _membership(student, plan, final_price=30000)

    data = StudentPlanSerializer(membership).data

    assert data['payment_status'] == 'unpaid'


def test_serializer_publishes_payment_status_paid(student_with_plan):
    org, student, plan = student_with_plan
    membership = _membership(student, plan, final_price=30000)
    _transaction(membership, status='approved')

    data = StudentPlanSerializer(membership).data

    assert data['payment_status'] == 'paid'


def test_serializer_publishes_payment_status_free(student_with_plan):
    org, student, plan = student_with_plan
    membership = _membership(student, plan, final_price=0)

    data = StudentPlanSerializer(membership).data

    assert data['payment_status'] == 'free'


def test_the_serializer_resolves_the_payment_axis_once_per_membership(student_with_plan):
    """El serializer llama a `describe_student_plan` una vez POR CAMPO derivado (son siete).

    Mientras el estado era una funcion pura eso no costaba nada. Con el eje de pago adentro,
    cada llamada recorre la FK inversa, asi que sin memoizar una sola membresia sin prefetch
    —`my-plan`, la respuesta de `assign`— dispara siete consultas para responder lo mismo.
    """
    org, student, plan = student_with_plan
    membership = _membership(student, plan, final_price=30000)
    _transaction(membership, status='approved')

    with CaptureQueriesContext(connection) as queries:
        data = StudentPlanSerializer(membership).data

    assert data['payment_status'] == 'paid'
    payment_queries = [
        query for query in queries.captured_queries
        if 'core_paymenttransaction' in query['sql'].lower()
    ]
    assert len(payment_queries) == 1, payment_queries


def test_serializer_payment_status_is_read_only(student_with_plan):
    """No es un campo escribible: el estado de pago se DERIVA, no se declara.

    Sin esto, el mismo endpoint que lee la membresia serviria para declararla pagada.
    """
    org, student, plan = student_with_plan
    membership = _membership(student, plan, final_price=30000)

    serializer = StudentPlanSerializer(membership, data={'payment_status': 'paid'},
                                       partial=True)

    assert serializer.is_valid(), serializer.errors
    assert 'payment_status' not in serializer.validated_data


# --------------------------------------------------------------------------------------
# 4. Lectura: roster, y redaccion para el monitor
# --------------------------------------------------------------------------------------

@pytest.fixture
def roster(make_organization, make_user):
    org = make_organization()
    branch = Branch.objects.create(organization=org, name='Sede')
    teacher = make_user('prof-pay', organization=org, role='teacher')
    student = make_user('stu-roster-pay', organization=org, role='student')
    candidate = make_user('stu-candidate-pay', organization=org, role='student')
    start = timezone.now() + timedelta(days=1)
    gym_class = GymClass.objects.create(
        organization=org, branch=branch, teacher=teacher, name='Clase',
        start_datetime=start, end_datetime=start + timedelta(hours=1), capacity=50,
        status=GymClass.Status.SCHEDULED,
    )
    Enrollment.objects.create(gym_class=gym_class, student=student, status='active')
    return {
        'org': org, 'student': student, 'candidate': candidate, 'gym_class': gym_class,
        'teacher': teacher,
        'admin': make_user('admin-pay', organization=org, role='gym_admin'),
        'manager': make_user('manager-pay', organization=org, role='manager'),
        'monitor': make_user('monitor-pay', organization=org, role='monitor'),
    }


def _roster_row(api_client, ctx, endpoint='enrolled-students', actor='admin'):
    target = ctx['student'] if endpoint == 'enrolled-students' else ctx['candidate']
    api_client.force_authenticate(user=ctx[actor])
    resp = api_client.get(f'/api/classes/{ctx["gym_class"].id}/{endpoint}/')
    assert resp.status_code == 200, resp.content
    body = resp.json()
    rows = body['results'] if isinstance(body, dict) else body
    key = 'student_id' if endpoint == 'enrolled-students' else 'id'
    matching = [row for row in rows if row[key] == target.id]
    assert matching, f'precondicion: el alumno aparece en {endpoint}'
    return matching[0]


@pytest.mark.parametrize('actor', ['admin', 'manager', 'teacher'])
@pytest.mark.parametrize('endpoint', ['enrolled-students', 'enrollable-students'])
def test_financial_readers_get_the_payment_status(api_client, roster, actor, endpoint):
    """Mismos lectores que reciben el motivo real del bloqueo en 7.3: todos menos monitor."""
    plan = _plan(roster['org'], name='Pack 10')
    target = roster['student'] if endpoint == 'enrolled-students' else roster['candidate']
    _membership(target, plan, classes_used=2, final_price=30000)

    row = _roster_row(api_client, roster, endpoint=endpoint, actor=actor)

    assert row['plan_payment_status'] == 'unpaid'


def test_monitor_never_receives_the_payment_status(api_client, roster):
    """El monitor no puede inscribir, asi que la deuda del alumno no es dato suyo.

    El corte lo hace el check inline `_may_see_plan_reason`, NO `FinancialResourcePermission`
    —esa clase solo excluye al manager y deja leer al monitor—.

    Se OMITE el campo en vez de degradarlo a un balde opaco como hace 7.3 con `plan_status`:
    los tres valores del eje (`paid`/`unpaid`/`free`) son afirmaciones financieras, o sea no
    existe un valor neutro que publicar. La redaccion honesta es la ausencia.
    """
    plan = _plan(roster['org'], name='Pack 10')
    _membership(roster['student'], plan, classes_used=2, final_price=30000)

    row = _roster_row(api_client, roster, actor='monitor')

    assert 'plan_payment_status' not in row


@pytest.mark.parametrize('final_price,paid', [(0, False), (30000, False), (30000, True)])
def test_the_absence_of_the_field_does_not_leak_the_payment_state(api_client, roster,
                                                                  final_price, paid):
    """La omision tiene que ser INCONDICIONAL, si no la ausencia es el dato.

    Si el campo solo se omitiera cuando el alumno debe, el monitor leeria la deuda en el
    hecho de que falta la clave. Se omite siempre, pague o no.
    """
    plan = _plan(roster['org'], name='Pack 10')
    membership = _membership(roster['student'], plan, classes_used=2,
                             final_price=final_price)
    if paid:
        _transaction(membership, status='approved')

    row = _roster_row(api_client, roster, actor='monitor')

    assert 'plan_payment_status' not in row


def test_redacting_the_payment_status_does_not_change_the_rest_of_the_roster(
        api_client, roster):
    """La redaccion del eje nuevo no puede tocar lo que el monitor ya veia en 7.3."""
    plan = _plan(roster['org'], name='Pack 10')
    _membership(roster['student'], plan, classes_used=2, final_price=30000)

    row = _roster_row(api_client, roster, actor='monitor')

    assert row['plan_status'] == 'active'
    assert row['plan_status_label'] == 'Vigente'
    assert row['plan_reason_code'] is None
    assert row['has_available_classes'] is True


def test_the_monitor_redaction_of_7_3_still_holds(api_client, roster):
    """Contraprueba de no-regresion: 8.1 no puede aflojar la redaccion que ya existia.

    Ancla sobre SALDO agotado y no sobre matricula: desde 8.4 la matricula impaga ya no
    bloquea, asi que dejo de ser una de las causas redactadas (la unica que sobrevive es
    el saldo agotado). Usar esa fixture aca daria un falso verde: la fila ya no se redacta
    por matricula, se redactaria (o no) por una razon que este test no busca cubrir.
    """
    plan = _plan(roster['org'], name='Pack 4', total_classes=4)
    _membership(roster['student'], plan, classes_used=4, final_price=30000)

    row = _roster_row(api_client, roster, actor='monitor')

    assert row['plan_status'] == 'unavailable'
    assert row['plan_status_label'] == 'No disponible'
    assert 'plan_payment_status' not in row
    assert 'matr' not in str(row).lower()


def test_a_student_without_membership_reports_no_payment_status(api_client, roster):
    row = _roster_row(api_client, roster)

    assert row['plan_status'] == 'no_plan'
    assert row['plan_payment_status'] is None


@pytest.mark.parametrize('end_offset', [3, -2])   # recordatorio y vencimiento: dos loops
def test_the_expiry_job_does_not_query_payments_once_per_membership(make_organization,
                                                                    make_user, end_offset):
    """El job nocturno recorre TODAS las membresias de la organizacion, en DOS loops.

    `describe_student_plan` es su fuente de estado igual que en el roster, asi que el eje de
    pago le agrega el mismo N+1 —invisible, porque el job no tiene a nadie mirando la
    latencia—. El job no usa `payment_status` para nada; lo paga solo por leer el estado.
    """
    from django.core.management import call_command

    org = make_organization()
    plan = _plan(org, name='Pack 10')
    OrganizationExpiryNotificationConfig.objects.create(
        organization=org, reminder_days_before=[3], send_expired_notice=False,
    )

    def _run():
        with CaptureQueriesContext(connection) as queries:
            call_command('expire_and_notify_plans', '--dry-run', f'--org-id={org.id}')
        return len(queries)

    student = make_user('stu-job-1', organization=org, role='student')
    _membership(student, plan, start_offset=-20, end_offset=end_offset, final_price=30000)
    one_membership = _run()

    for index in range(2):
        extra = make_user(f'stu-job-extra-{index}', organization=org, role='student')
        _membership(extra, plan, start_offset=-20, end_offset=end_offset,
                    final_price=30000)

    assert _run() == one_membership


def test_the_roster_does_not_query_payments_once_per_student(api_client, roster,
                                                             make_user):
    """El eje de pago sale de una FK inversa: leerlo fila por fila es un N+1 en el roster.

    Se compara el MISMO endpoint con un alumno y con tres: si la derivacion consulta por
    alumno, el segundo conteo crece. Es la unica forma de que el guard no dependa del
    numero exacto de queries del endpoint.
    """
    plan = _plan(roster['org'], name='Pack 10')
    membership = _membership(roster['student'], plan, classes_used=2, final_price=30000)
    _transaction(membership, status='approved')
    api_client.force_authenticate(user=roster['admin'])
    url = f'/api/classes/{roster["gym_class"].id}/enrolled-students/'

    with CaptureQueriesContext(connection) as one_student:
        first = api_client.get(url)
    assert first.status_code == 200
    assert first.json()[0]['plan_payment_status'] == 'paid'

    for index in range(2):
        extra = make_user(f'stu-extra-pay-{index}', organization=roster['org'],
                          role='student')
        Enrollment.objects.create(gym_class=roster['gym_class'], student=extra,
                                  status='active')
        extra_membership = _membership(extra, plan, classes_used=2, final_price=30000)
        _transaction(extra_membership, status='approved')

    with CaptureQueriesContext(connection) as three_students:
        second = api_client.get(url)
    assert second.status_code == 200
    assert len(second.json()) == 3

    assert len(three_students) == len(one_student)
