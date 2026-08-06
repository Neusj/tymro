"""Drill-down del reporte de INGRESOS: el listado de un método (capa 2) y el detalle de un
pago (capa 3).

Las tres capas son la misma pregunta con distinto zoom. La capa 1 (`reports_revenue.py`)
responde "cuánto entró y por qué medio"; acá se responde "de qué cobros salió ese número" y
"qué fue exactamente ese cobro". El administrador llega por CLIC, así que el número de arriba
tiene que seguir siendo el mismo en las tres pantallas.

EL CUADRE CON LA CAPA 1 NO SE VERIFICA, SE HEREDA
Este módulo NO arma sus propias consultas de plata: pide los dos querysets a
`reports_revenue.method_querysets` y los totales a `reports_revenue.method_totals`. Es la
diferencia entre "los dos cálculos coinciden hoy" y "no hay dos cálculos". Lo único que agrega
acá es el LISTADO de esas mismas filas y su formato. Si alguna vez hace falta cambiar qué
cuenta como bruto —o el redondeo—, se cambia en `reports_revenue.py` y las tres capas se mueven
juntas o ninguna.

POR QUÉ SON DOS LISTAS Y NO UNA
La capa 1 es BASE CAJA: un cobro de junio devuelto en julio suma bruto en junio y resta
devolución en JULIO. En el período de julio ese pago NO fue cobrado pero SÍ fue devuelto, así
que no puede estar en la lista de cobros del período; y si no estuviera en ninguna, el
administrador vería `refunds: 35.000` arriba y ni una fila que lo explique abajo. Por eso hay
`rows` (los COBROS del período, por su fecha de cobro) y `refund_rows` (las DEVOLUCIONES del
período, por su fecha de devolución), cada una sumando su propio total publicado. Una sola
lista obligaría a elegir cuál de los dos números miente.

`refund_rows` va SIEMPRE presente, aunque sea `[]`: para efectivo/transferencia no existe
mecanismo de devolución manual, y una lista vacía declarada dice "no hubo" mientras que una
clave ausente diría "no sé". Mismo criterio que la columna `refunds: 0` de la capa 1.

EL TOPE DE FILAS (`MAX_ROWS`) CORTA LAS LISTAS, NUNCA LOS TOTALES
`totals` sale de `method_totals`, que agrega en la base sobre TODAS las filas del período. El
corte se declara siempre (`row_limit`, `truncated`, `refunds_truncated`) y también DENTRO del
archivo exportado: la pantalla puede avisar del recorte, pero el CSV viaja solo.

QUÉ SE ABSORBIÓ DEL REPORTE DE PAGOS MANUALES (borrado en esta misma entrega)
`reports_manual.py` era la única lectura que existía de `ManualPayment` y su formateador de
filas es exactamente lo que la capa 2 necesita para los cobros de recepción. Vino con su
decisión sobre los nombres de personas (ver `_manual_row`) y con el aviso de truncado dentro
del export. Lo que NO se tocó es la ESCRITURA: `record_manual_payment` y su endpoint POST
siguen intactos: se borró una pantalla de lectura, no la capacidad de cobrar.
"""
import uuid

from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone

from ..models import ManualPayment, PaymentTransaction
from .reports_base import METHOD_LABELS, METHOD_MERCADOPAGO, manual_method_wire
from .reports_revenue import (REFUNDS_DATE_FIELD, gross_date_field, method_querysets,
                              method_totals)

# Mismo freno y mismo motivo que `MAX_PERIOD_DAYS` en `reports_base.py`: esto corre en una
# request SÍNCRONA de gunicorn (`--timeout 30`) y con el rango tope de 731 días un gimnasio
# grande puede tener decenas de miles de cobros en el período. Vive como global de módulo (no
# como default de parámetro) para que un test lo pueda bajar con
# `monkeypatch.setattr(reports_revenue_detail, 'MAX_ROWS', N)` sin fabricar miles de filas.
# Aplica a CADA lista por separado: `rows` y `refund_rows` son dos consultas distintas.
MAX_ROWS = 2000

#: Los dos tipos de fila del drill-down. NO son medios de cobro sino MODELOS: `mercadopago` es
#: una `PaymentTransaction` y `manual` es un `ManualPayment`, que es lo que decide qué campos
#: tiene el detalle y cómo se parsea el id. Los tres medios manuales (efectivo, transferencia y
#: el `unknown` de las filas legacy) comparten tipo porque comparten tabla.
KIND_MERCADOPAGO = METHOD_MERCADOPAGO
KIND_MANUAL = 'manual'
PAYMENT_KINDS = (KIND_MERCADOPAGO, KIND_MANUAL)

# `recorded_by` es SET_NULL (ver models.py: borrar al administrador que cobró no puede
# des-pagar la membresía). NULL es entonces un estado legítimo y no puede reventar el
# reporte ni aparecer como una celda vacía indistinguible de un dato faltante por error: se
# declara con un texto explícito.
RECORDED_BY_DELETED_LABEL = 'Usuario eliminado'


def _full_name(user):
    """Nombre completo, con fallback al username si la persona no declaró nombre.

    `get_full_name()` (`AbstractUser`) devuelve `''` cuando `first_name`/`last_name` están
    vacíos -son opcionales en el alta-, y una celda vacía en un reporte de plata es peor que
    el username: al menos identifica a quién sin ambigüedad.
    """
    full_name = user.get_full_name().strip()
    return full_name or user.username


def _recorded_by_name(user):
    if user is None:
        return RECORDED_BY_DELETED_LABEL
    return _full_name(user)


def _to_int(amount):
    """CLP no tiene decimales en este proyecto (mismo criterio que el resto de `reports_*`):
    se redondea, no se trunca, para no descartar el peso que el truncado se comería."""
    return int(round(amount)) if amount is not None else 0


def _iso(value):
    """`None` sobrevive como `None`: una fecha ausente es un dato del pago (una transacción
    que no se procesó, una que no se devolvió), no un error que haya que tapar con ''."""
    return value.isoformat() if value is not None else None


def _own_or_none(related, organization_id):
    """`related` solo si es de ESTA organización; `None` si es de otra o si no hay.

    ⚠️ EL CORTE NO ES REDUNDANTE, y la diferencia con los NOMBRES DE PERSONAS es la razón de
    ser de esta función. Seguir `plan` / `student_plan` / `target_student_plan` desde el pago
    confía en la invariante `pago.organization == destino.organization`, que hoy cumplen los
    dos caminos de escritura pero que NO garantiza ninguna constraint: un `superadmin` puede
    mover un `Plan` de organización con un `PATCH /api/plans/{id}/` (`PlanSerializer.validate`
    solo pisa la organización cuando el actor es `gym_admin`), y ni `StudentPlan.organization`
    ni `ManualPayment.organization` se re-sincronizan. Es el patrón "FK propia sin
    organización" documentado en `backend/CLAUDE.md`, y es EXACTAMENTE el mismo corte que hace
    `PaymentTransactionAdminSerializer.get_line_items` (`serializers.py`) sobre este mismo
    modelo, en este mismo camino de lectura.

    Rota la invariante, lo que viajaría no es un residuo de privacidad sino DATO DE NEGOCIO de
    otro tenant: el NOMBRE DE UN PLAN y el PK de una membresía ajena. Por eso acá se falla
    CERRADO —`None`, igual que un plan borrado del catálogo— mientras que los nombres de
    PERSONAS sí se publican tal cual (ver la decisión consciente en `_manual_row`): un nombre
    cambiado es alguien que ese gimnasio ya conocía; el catálogo de otro gimnasio, no.

    El objeto viene por `select_related` en los dos builders, así que comparar no agrega
    queries.
    """
    if related is None or related.organization_id != organization_id:
        return None
    return related


def _manual_plan_name(payment):
    """Nombre del plan de la membresía que se cobró, o `None` ante cualquier incoherencia de
    organización (ver `_own_or_none`). Se chequean los DOS saltos —el pago a la membresía y la
    membresía al plan—: cortar solo el primero dejaría pasar el nombre de un plan que se mudó
    de gimnasio por debajo de una membresía que se quedó."""
    membership = _own_or_none(payment.student_plan, payment.organization_id)
    if membership is None:
        return None
    plan = _own_or_none(membership.plan, payment.organization_id)
    return plan.name if plan is not None else None


# --------------------------------------------------------------------------------------
# Capa 2 · el listado de un método
# --------------------------------------------------------------------------------------

def _slice(queryset, limit):
    """`(lista, truncada)`. El `.count()` corre ANTES del slice a propósito: es la única
    forma de saber si la lista real era más larga que el tope sin traer esas filas."""
    total_count = queryset.count()
    return list(queryset[:limit]), total_count > limit


def _manual_row(payment):
    """Fila publicada de un cobro registrado a mano. Absorbida de `reports_manual._row_payload`.

    ⚠️ DECISIÓN CONSCIENTE sobre los nombres de personas que ya NO son de esta organización.
    `student_plan__user` y `recorded_by` son FK propias que este payload sigue SIN intersectar
    `organization_id` —el agujero recurrente del repo—, así que si alguien mueve a ese alumno
    (o al administrador que cobró) a otra organización, la fila sigue apareciendo en el reporte
    de la organización que VENDIÓ (correcto: `StudentPlan.organization` es quien vendió, y esa
    membresía sigue viva) y muestra el nombre que la persona tiene HOY en la otra.
    NO se reemplaza por una etiqueta neutra, y el motivo es que el remedio es peor: este es el
    registro contable del gimnasio de un cobro en efectivo que RECIBIÓ de una persona que ya
    conocía por su nombre. Tapar la identidad le rompe su propio libro de caja para proteger un
    dato que ese gimnasio ya tenía. Lo único que puede quedar expuesto es un nombre CAMBIADO
    después de la mudanza, que es un residuo de privacidad, no una fuga de datos de negocio de
    otro tenant (ninguna FILA de otra organización entra: eso lo corta `method_querysets`).
    Si alguna vez importa de verdad, la solución correcta NO es la etiqueta: es congelar nombre
    y apellido en la fila al momento del cobro (columna nueva + migración), como ya hace
    `ClassOccupancySnapshot` con la sede y la disciplina.

    ⚠️ ESA TOLERANCIA LLEGA HASTA LOS NOMBRES DE PERSONAS Y NI UN CAMPO MÁS. `plan_name` NO
    sale de `student_plan.plan.name` a secas: pasa por `_manual_plan_name`, que corta por
    organización. El nombre de un PLAN es catálogo de otro gimnasio, no alguien que este
    gimnasio ya conocía, y ahí la misma FK sin intersectar deja de ser un residuo de
    privacidad y pasa a ser una fuga de negocio.

    `reference` y `recorded_by_name` viajan en la fila y no solo en el detalle: son dos de las
    ocho columnas del export que este listado hereda del reporte borrado, y el CSV se arma
    desde estas filas justamente para que no pueda decir algo distinto de la pantalla.
    """
    student_plan = payment.student_plan
    student = student_plan.user
    return {
        'kind': KIND_MANUAL,
        'id': payment.id,
        'occurred_at': payment.recorded_at.isoformat(),
        'amount': _to_int(payment.amount),
        'student_id': student.id,
        'student_name': _full_name(student),
        'plan_name': _manual_plan_name(payment),
        'branch_id': payment.branch_id,
        'branch_name': payment.branch.name if payment.branch_id else None,
        # Al cable va `unknown`, nunca `''`: ver `manual_method_wire`. Se publica el medio de
        # la FILA y no el del filtro aunque hoy sean el mismo, para que la tabla del front no
        # dependa de qué se pidió.
        'method': manual_method_wire(payment.method),
        'method_label': METHOD_LABELS[manual_method_wire(payment.method)],
        'reference': payment.reference,
        'recorded_by_id': payment.recorded_by_id,
        'recorded_by_name': _recorded_by_name(payment.recorded_by),
    }


def _mp_row(transaction, *, occurred_at, amount, scope, refund=False):
    """Fila publicada de un cobro en línea, o de su devolución.

    `occurred_at` y `amount` son los del EVENTO que la fila representa, no los del pago: en un
    cobro son `collected_at` y `amount`; en una devolución son `refunded_at` y
    `refunded_amount`. Es lo que hace que las dos listas se puedan dibujar con la misma tabla y
    que cada una sume su propio total.

    Solo en las devoluciones viajan `collected_at` y `collected_in_period`: sin ellas, la fila
    de una devolución de julio sobre un cobro de junio se lee como si el cobro también fuera de
    julio, y el administrador buscaría en la lista de arriba una fila que no está. `collected_at`
    nunca es null ahí porque el queryset de devoluciones ya exige `collected_at__isnull=False`.

    ⚠️ `transaction.user` es una FK propia que este payload NO intersecta con `organization_id`:
    la MISMA decisión consciente documentada en `_manual_row`, y por los mismos motivos. La FILA
    está acotada por `PaymentTransaction.organization` (la organización que cobró), así que no
    entra ninguna de otro tenant; lo único que puede quedar expuesto es el nombre que esa
    persona tiene HOY si se mudó de gimnasio. Vale igual para `_mercadopago_detail`.
    """
    student = transaction.user
    membership = _mp_membership(transaction)
    row = {
        'kind': KIND_MERCADOPAGO,
        # `str()` y no el UUID crudo: DRF lo serializaría igual, pero el id viaja al front para
        # volver como segmento de URL en la capa 3 y tiene que ser el MISMO texto de ida y de
        # vuelta.
        'id': str(transaction.id),
        'occurred_at': occurred_at.isoformat(),
        'amount': _to_int(amount),
        'student_id': student.id,
        'student_name': _full_name(student),
        'plan_name': _mp_plan_name(transaction, membership),
        'branch_id': transaction.branch_id,
        'branch_name': transaction.branch.name if transaction.branch_id else None,
        'method': METHOD_MERCADOPAGO,
        'method_label': METHOD_LABELS[METHOD_MERCADOPAGO],
        # Dos columnas del export de este método (`Estado`, `ID de transacción`) y el dato con
        # el que el gimnasio concilia contra su panel de MercadoPago.
        'status': transaction.status,
        'provider_payment_id': transaction.provider_payment_id,
    }
    if refund:
        row['collected_at'] = transaction.collected_at.isoformat()
        # Fecha LOCAL, igual que el filtro del período (`__date__gte/lte` con `USE_TZ=True`):
        # con la fecha UTC un cobro del último día del mes a las 21:00 caería fuera del propio
        # período que lo contiene.
        collected_date = timezone.localtime(transaction.collected_at).date()
        row['collected_in_period'] = scope.date_from <= collected_date <= scope.date_to
    return row


def build_revenue_payments_report(scope, method):
    """Capa 2: los cobros y las devoluciones de UN método dentro del período.

    `method` es obligatorio y ya viene validado contra `REVENUE_METHODS` por la view: este
    listado existe para explicar UNA fila de `by_method`, y "todos los métodos" no es una fila.

    Los `totals` son los de esa fila, calculados por `method_totals` sobre los mismos
    querysets que se listan acá. No hay una segunda suma que pueda decir otra cosa.
    """
    gross_queryset, refunds_queryset = method_querysets(scope, method)
    totals = method_totals(gross_queryset, refunds_queryset)

    if method == METHOD_MERCADOPAGO:
        # `-collected_at, -id`: lo más reciente arriba, que es donde el administrador busca.
        # El desempate por `id` no es cosmético: sin él, dos cobros del mismo instante pueden
        # salir en distinto orden en dos requests y el recorte por `MAX_ROWS` traería filas
        # distintas cada vez.
        collected = gross_queryset.select_related(
            'user', 'plan', 'student_plan__plan', 'target_student_plan__plan', 'branch',
        ).order_by(f'-{gross_date_field(method)}', '-id')
        refunded = refunds_queryset.select_related(
            'user', 'plan', 'student_plan__plan', 'target_student_plan__plan', 'branch',
        ).order_by(f'-{REFUNDS_DATE_FIELD}', '-id')

        collected, truncated = _slice(collected, MAX_ROWS)
        refunded, refunds_truncated = _slice(refunded, MAX_ROWS)
        rows = [_mp_row(tx, occurred_at=tx.collected_at, amount=tx.amount, scope=scope)
                for tx in collected]
        refund_rows = [_mp_row(tx, occurred_at=tx.refunded_at, amount=tx.refunded_amount,
                               scope=scope, refund=True)
                       for tx in refunded]
    else:
        payments = gross_queryset.select_related(
            'student_plan__user', 'student_plan__plan', 'recorded_by', 'branch',
        ).order_by(f'-{gross_date_field(method)}', '-id')
        payments, truncated = _slice(payments, MAX_ROWS)
        rows = [_manual_row(payment) for payment in payments]
        # Sin mecanismo de devolución manual: lista vacía DECLARADA y `refunds_truncated` en
        # False. Ver el encabezado del módulo.
        refund_rows, refunds_truncated = [], False

    return {
        'period': scope.period_payload(),
        'filters': scope.filters_payload(method=method,
                                         method_label=METHOD_LABELS[method]),
        'totals': totals,
        'rows': rows,
        'refund_rows': refund_rows,
        'row_limit': MAX_ROWS,
        'truncated': truncated,
        'refunds_truncated': refunds_truncated,
    }


# --------------------------------------------------------------------------------------
# Capa 2 · export. Las columnas dependen del método porque el archivo ya está filtrado por
# uno: mostrar `Referencia` y `Registrado por` en un export de MercadoPago sería mostrar dos
# columnas vacías, y mostrar `Estado` en uno de efectivo sería inventar un dato.
# --------------------------------------------------------------------------------------

def _truncation_notice(*, limit, total, noun, width):
    """EL CORTE SE DECLARA DENTRO DEL ARCHIVO, no solo en el JSON.

    Las listas vienen recortadas a `MAX_ROWS` y la fila TOTAL sale de `totals`, que se agrega
    sobre el período COMPLETO. Las dos cosas son correctas por separado —el total no puede
    mentir por un límite de la lista— pero juntas producen una planilla donde sumar la columna
    `Monto` NO da el TOTAL. Sin esta línea, ese descuadre es MUDO: el que abre el CSV concluye
    que el reporte está roto, o peor, corrige el total a mano. La pantalla ya lo avisa; el
    archivo viaja solo y tiene que avisarlo también.
    """
    text = (f'— Lista recortada a {limit} de {total} {noun}. '
            f'El TOTAL de abajo es del período completo. —')
    return [text] + [''] * (width - 1)


def _manual_export_spec(data):
    """EXACTAMENTE las columnas del reporte de pagos manuales que este listado reemplaza.

    No es nostalgia: es el libro de caja que el gimnasio baja todos los meses y pega en su
    planilla. Cambiarle las columnas al absorberlo le rompería las fórmulas de una planilla que
    no controlamos.
    """
    header = ['Fecha', 'Alumno', 'Plan', 'Sede', 'Método', 'Referencia', 'Registrado por',
              'Monto']
    rows = [
        [row['occurred_at'], row['student_name'], row['plan_name'],
         row['branch_name'] or '', row['method_label'], row['reference'],
         row['recorded_by_name'], row['amount']]
        for row in data['rows']
    ]
    if data['truncated']:
        rows.append(_truncation_notice(limit=data['row_limit'],
                                       total=data['totals']['payments_count'],
                                       noun='cobros', width=len(header)))
    return {'header': header, 'rows': rows, 'total_row': _total_row(data, len(header))}


def _mercadopago_export_spec(data):
    """Cobros y devoluciones en el MISMO archivo, distinguidos por la columna `Tipo`.

    Las devoluciones van con el monto en NEGATIVO. Es lo que hace que sumar la columna `Monto`
    dé el NETO publicado: con la devolución en positivo, la suma daría bruto + devoluciones, un
    número que no existe en ninguna pantalla y que además INFLA el ingreso justo en los períodos
    donde salió plata de la caja.
    """
    header = ['Tipo', 'Fecha', 'Alumno', 'Plan', 'Sede', 'ID de transacción', 'Estado',
              'Monto']

    def _row(row, *, kind_label, sign):
        return [kind_label, row['occurred_at'], row['student_name'], row['plan_name'] or '',
                row['branch_name'] or '',
                # El id del PROVEEDOR y no nuestro UUID: esta columna existe para conciliar
                # contra el panel de MercadoPago, donde nuestro id no significa nada. Vacío
                # solo si el proveedor nunca mandó uno.
                row['provider_payment_id'] or '',
                row['status'], sign * row['amount']]

    rows = [_row(row, kind_label='Cobro', sign=1) for row in data['rows']]
    if data['truncated']:
        rows.append(_truncation_notice(limit=data['row_limit'],
                                       total=data['totals']['payments_count'],
                                       noun='cobros', width=len(header)))
    rows += [_row(row, kind_label='Devolución', sign=-1) for row in data['refund_rows']]
    if data['refunds_truncated']:
        rows.append(_truncation_notice(limit=data['row_limit'],
                                       total=data['totals']['refunds_count'],
                                       noun='devoluciones', width=len(header)))
    return {'header': header, 'rows': rows, 'total_row': _total_row(data, len(header))}


def _total_row(data, width):
    """Fila TOTAL con el NETO del período.

    Mismo layout que el resto de los exports (`TeacherPaymentRecordViewSet._summary_total_row`):
    el texto en la primera celda y el monto en la última, alineado con la columna `Monto`.

    El neto y no el bruto, en los dos métodos: es el único número que cuadra con la suma de la
    columna cuando el archivo trae devoluciones (van en negativo), y en efectivo/transferencia
    coincide con el bruto porque ahí las devoluciones son siempre 0. Un TOTAL distinto según el
    método sería justo la clase de detalle que nadie mira antes de pegar el archivo en una
    planilla.
    """
    return ['TOTAL'] + [''] * (width - 2) + [data['totals']['net']]


def revenue_payments_export_spec(data):
    if data['filters']['method'] == METHOD_MERCADOPAGO:
        return _mercadopago_export_spec(data)
    return _manual_export_spec(data)


# --------------------------------------------------------------------------------------
# Capa 3 · el detalle de un pago
# --------------------------------------------------------------------------------------

def _mp_membership(transaction):
    """Membresía a la que apunta un cobro en línea, o `None`.

    TRES FKs candidatas en `PaymentTransaction` y NO son intercambiables:

    * `plan` es el plan del CATÁLOGO que se compró, no una membresía. Es `SET_NULL`, así que
      queda en NULL si el gimnasio borra el plan de su catálogo.
    * `target_student_plan` es la membresía a la que se le cobró la MATRÍCULA. Se estampa en el
      checkout, antes de que entre la plata.
    * `student_plan` es la membresía que el cobro terminó afectando, y la escribe
      `apply_provider_payment` al activar — en los DOS caminos: la membresía recién creada en
      una compra de plan, y la misma `target_student_plan` en un cobro de matrícula.

    Se prefiere `student_plan` porque es el resultado real, y se cae a `target_student_plan`
    para el caso legítimo en que la plata entró y la activación no llegó a correr. Cuando las
    dos son NULL la respuesta es NULL y eso es un dato, no un error: es el cobro que entró sin
    activar nada (el `plan_org_mismatch` documentado en `models.PaymentTransaction`), y taparlo
    con la membresía "más parecida" inventaría un vínculo que no existe.

    ⚠️ Las dos candidatas pasan por `_own_or_none`: una membresía cuya organización ya no es
    la del cobro se descarta como si fuera NULL. Sin ese corte, el payload publicaría el PK de
    una `StudentPlan` ajena —y su `plan.name` detrás—, que es dato de negocio de otro tenant.
    Se descarta CADA candidata por separado (no se aborta al primer descarte): si la membresía
    activada se mudó pero la `target_student_plan` del cobro de matrícula sigue siendo de este
    gimnasio, esa última es un vínculo legítimo y no hay razón para esconderlo.
    """
    for candidate in (transaction.student_plan, transaction.target_student_plan):
        membership = _own_or_none(candidate, transaction.organization_id)
        if membership is not None:
            return membership
    return None


def _mp_plan_name(transaction, membership):
    """Nombre del plan involucrado en un cobro en línea, o `None`.

    Primero el plan COMPRADO (`transaction.plan`), que es lo que la plata pagó. En un cobro de
    matrícula ese campo es NULL por construcción —no se compró ningún plan— y ahí el nombre
    útil es el del plan de la membresía a la que se le cobró: sin él, la fila del reporte diría
    solo "Ana Pérez" y el administrador no sabría de qué membresía le hablan.

    Puede quedar en `None`: `PaymentTransaction.plan` es `SET_NULL` (plan borrado del catálogo)
    y la membresía puede no existir. Se publica null y no un texto inventado.

    ⚠️ Un plan que ya NO es de esta organización se trata EXACTAMENTE como un plan borrado
    (ver `_own_or_none`): devuelve `None`. Y cuando el plan comprado existe pero es ajeno NO se
    cae a la membresía: caer sería buscar un segundo camino hacia el mismo nombre después de
    haber decidido que el primero no se publica. `membership` ya viene cortada por
    `_mp_membership`, pero su `plan` se vuelve a chequear porque son dos saltos distintos y el
    plan puede haberse mudado sin que la membresía lo hiciera.
    """
    plan = _own_or_none(transaction.plan, transaction.organization_id)
    if plan is not None:
        return plan.name
    if transaction.plan_id:
        return None
    if membership is None:
        return None
    membership_plan = _own_or_none(membership.plan, transaction.organization_id)
    return membership_plan.name if membership_plan is not None else None


def _manual_detail(organization_id, payment_id):
    payment = get_object_or_404(
        ManualPayment.objects.select_related(
            'student_plan__user', 'student_plan__plan', 'recorded_by', 'branch'),
        id=payment_id, organization_id=organization_id)
    student_plan = payment.student_plan
    student = student_plan.user
    method = manual_method_wire(payment.method)
    # SIN ninguna clave de MercadoPago, ni siquiera en null: un `status` o un
    # `provider_payment_id` vacíos en un cobro de recepción no son "sin dato", son una pregunta
    # que no existe. El front decide qué mostrar por PRESENCIA de clave.
    return {
        'kind': KIND_MANUAL,
        'id': payment.id,
        'amount': _to_int(payment.amount),
        'recorded_at': payment.recorded_at.isoformat(),
        'method': method,
        'method_label': METHOD_LABELS[method],
        'reference': payment.reference,
        'student_id': student.id,
        'student_name': _full_name(student),
        # Membresía y plan cortados por organización (`_own_or_none`): ante la incoherencia
        # viajan en null, nunca el PK ni el nombre del catálogo de otro gimnasio. El NOMBRE del
        # alumno de acá arriba sí viaja siempre — ver la decisión consciente en `_manual_row`.
        'student_plan_id': getattr(_own_or_none(student_plan, payment.organization_id),
                                   'id', None),
        'plan_name': _manual_plan_name(payment),
        'branch_id': payment.branch_id,
        'branch_name': payment.branch.name if payment.branch_id else None,
        # El punto de control interno de este reporte: quién anotó el cobro. Solo existe acá —
        # un cobro en línea lo registró el webhook, no una persona.
        'recorded_by_id': payment.recorded_by_id,
        'recorded_by_name': _recorded_by_name(payment.recorded_by),
    }


def _mercadopago_detail(organization_id, transaction_id):
    transaction = get_object_or_404(
        PaymentTransaction.objects.select_related(
            'user', 'plan', 'student_plan__plan', 'target_student_plan__plan', 'branch'),
        id=transaction_id, organization_id=organization_id)
    membership = _mp_membership(transaction)
    student = transaction.user
    # SIN `recorded_by_*`: este cobro lo escribió el webhook del proveedor
    # (`services/payments.py`), no un administrador. Publicar la clave en null diría "no se
    # sabe quién lo registró", y sí se sabe: nadie, es automático.
    return {
        'kind': KIND_MERCADOPAGO,
        'id': str(transaction.id),
        'amount': _to_int(transaction.amount),
        'currency': transaction.currency,
        'method': METHOD_MERCADOPAGO,
        'method_label': METHOD_LABELS[METHOD_MERCADOPAGO],
        # `collected_at` es el instante del COBRO y el eje del reporte; `processed_at` es el de
        # la ACTIVACIÓN de la membresía. Viajan los dos porque la diferencia entre ellos es el
        # caso que hay que poder diagnosticar desde acá: plata que entró y membresía que no se
        # activó (ver el comentario de los campos en `models.py`).
        'collected_at': _iso(transaction.collected_at),
        'status': transaction.status,
        'status_detail': transaction.status_detail,
        'provider': transaction.provider,
        'provider_payment_id': transaction.provider_payment_id,
        'processed_at': _iso(transaction.processed_at),
        'refunded_at': _iso(transaction.refunded_at),
        'refunded_amount': _to_int(transaction.refunded_amount),
        # Desglose del cobro: cuánto fue plan y cuánto matrícula. Suman `amount`.
        'plan_amount': _to_int(transaction.plan_amount),
        'enrollment_fee_amount': _to_int(transaction.enrollment_fee_amount),
        'student_id': student.id,
        'student_name': _full_name(student),
        'student_plan_id': membership.id if membership is not None else None,
        'plan_name': _mp_plan_name(transaction, membership),
        'branch_id': transaction.branch_id,
        'branch_name': transaction.branch.name if transaction.branch_id else None,
    }


#: Constructor de detalle por tipo. Ver el porqué del dict en `build_payment_detail`.
_DETAIL_BUILDERS = {
    KIND_MERCADOPAGO: _mercadopago_detail,
    KIND_MANUAL: _manual_detail,
}


def build_payment_detail(*, organization_id, kind, payment_id):
    """Capa 3: un pago, con los campos que SU tipo tiene y sin los que no.

    ⚠️ EL ALCANCE ES SOLO LA ORGANIZACIÓN, A PROPÓSITO. Sin período, sin sede y sin exigir
    `collected_at__isnull=False`. Un detalle no es un reporte: es la ficha de una fila que ya
    es del gimnasio que pregunta. Filtrar acá por lo mismo que filtra la capa 2 haría que el
    404 apareciera por sorpresa —la misma URL funcionaría o no según el rango que el usuario
    tuviera seleccionado cuando copió el link— y no protegería nada: una transacción `pending`
    o `rejected` de la propia organización es dato propio del gimnasio, y el único riesgo real
    (leer un pago ajeno) ya lo cierra `organization_id`.

    `organization_id` es la del ACTOR y nunca llega del request (regla 1 de backend/CLAUDE.md,
    orden 8.3). Un id ajeno o inexistente da 404 y no 403: los ids son adivinables, y un 403
    confirmaría "existe, pero no es tuyo".

    El despacho es un dict SIN rama por defecto, y no un `if/else`: con un `else` que cayera a
    `manual`, agregar mañana un tercer tipo a `PAYMENT_KINDS` y olvidarse de esta función lo
    haría buscar el id en la tabla equivocada —404 en el mejor caso, 500 si el id es de otro
    tipo, y un filtro de organización sobre la columna equivocada en el peor—. Un `KeyError`
    traducido a 404 falla ruidosamente en su lugar. Es también la red para cualquier caller que
    no sea la view (un comando, un endpoint futuro): el id ya tiene que venir tipado.
    """
    try:
        builder = _DETAIL_BUILDERS[kind]
    except KeyError:
        raise Http404(f'Tipo de pago desconocido: {kind}')
    return builder(organization_id, payment_id)


def parse_transaction_id(raw_value):
    """UUID de una `PaymentTransaction`, o `None` si el texto no tiene esa forma.

    `PaymentTransaction.id` es un `UUIDField`: un string cualquiera dentro de un
    `filter(id=...)` levanta `ValidationError` desde el conversor del campo, que DRF no traduce
    — o sea un **500** en un endpoint de plata. Se valida la FORMA antes de tocar la base.

    `None` para que la view traduzca a **400** (malformado, no revela nada), deliberadamente
    distinto del **404** de un id ajeno (anti-oráculo: los ids de la otra mitad del drill-down
    son adivinables y un 403 confirmaría "existe, pero no es tuyo"). El equivalente para
    `ManualPayment.id` —que es un entero y revienta con 500 en PostgreSQL fuera del rango de
    bigint— es el `_id_field` de `views_reports`, que ya existía por el mismo motivo.
    """
    try:
        return uuid.UUID(str(raw_value))
    except (ValueError, AttributeError, TypeError):
        return None
