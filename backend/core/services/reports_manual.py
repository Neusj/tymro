"""Reporte de pagos manuales (P3.4 · Pieza 2): cobros en efectivo y transferencia.

PRIMERA LECTURA que existe de `ManualPayment` (ver su docstring en `models.py`): hasta P3.4
el modelo era solo-POST -el gimnasio anotaba el cobro en recepción y no tenía dónde volver a
verlo-. Este módulo NO agrega ninguna regla de negocio nueva sobre el pago -esa vive en
`services/manual_payments.py`, la única puerta de escritura-, solo lo agrega y lo lista.

DOS DECISIONES QUE ESTE MÓDULO FIJA Y VALE LA PENA CONOCER ANTES DE TOCARLO:

1. **Las filas legacy con `method=''` (anteriores a P3.2, ver el comentario del campo
   `ManualPayment.method` en `models.py`) ENTRAN al reporte, con su propio instrumento
   `unknown`.** Son cobros REALES que ya viven en producción: el gimnasio los recibió y lo
   único que no quedó anotado es si fueron efectivo o transferencia. Dejarlas afuera haría
   que este reporte —la única lectura que existe de `ManualPayment`— escondiera plata que el
   gimnasio cobró, que es el peor defecto posible acá.
   La identidad que el frontend usa para la barra apilada sigue valiendo, con el tercer
   término: **`total == cash + transfer + unknown`**, y `count` los cuenta a los tres.

2. **`method`, si viene, filtra el reporte ENTERO -serie, totales y filas-, no solo la
   lista.** Mismo criterio que el filtro de método del reporte de ingresos: pedir "el
   reporte de efectivo" es pedir eso, no una lista recortada debajo de tarjetas que sigan
   mostrando el total mixto. La consecuencia práctica es que filtrar por `cash` deja
   `totals.transfer` en cero: es el comportamiento esperado, no un caso a corregir.
   `method=unknown` es un valor válido y sirve justo para aislar esas filas históricas.

SOBRE EL TOPE DE FILAS (`MAX_ROWS`): corta SOLO `rows`. `totals` y `series` se calculan
agregando en la base de datos sobre TODAS las filas del período (antes del `[:MAX_ROWS]`),
así que el número que el admin ve arriba de la pantalla nunca miente aunque la lista de abajo
esté recortada. Un tope silencioso -que no se declara en la respuesta- es lo que este módulo
evita publicando siempre `row_limit` y `truncated`.
"""
from django.db.models import Count, DateField, Q, Sum
from django.db.models.functions import TruncDate, TruncMonth

from ..models import ManualPayment
from .reports_base import (GRANULARITY_MONTH, MANUAL_METHODS, METHOD_CASH, METHOD_LABELS,
                           METHOD_TRANSFER, METHOD_UNKNOWN, UNKNOWN_DB_METHOD, bucket_key,
                           bucket_keys, manual_method_filter, manual_method_wire)

# Ver la nota de "SOBRE EL TOPE DE FILAS" arriba. No es un límite técnico: es el mismo freno
# que MAX_PERIOD_DAYS en reports_base.py, pensado para el mismo peor caso (gunicorn sync,
# `--timeout 30`). Vive como global de módulo (no como default de parámetro) para que un
# test pueda bajarlo con `monkeypatch.setattr(reports_manual, 'MAX_ROWS', N)` sin fabricar
# miles de filas.
MAX_ROWS = 2000

# Las etiquetas y la lista de instrumentos vienen de `reports_base`: son las MISMAS que valida
# la view y las que usa el reporte de ingresos. Una copia local acá fue exactamente lo que
# dejó fuera del cálculo a las filas con `method=''`.

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


def _base_queryset(scope, method):
    qs = ManualPayment.objects.filter(
        organization_id=scope.organization_id,
        recorded_at__date__gte=scope.date_from,
        recorded_at__date__lte=scope.date_to,
        # Decisión 1 del docstring del módulo: las filas legacy sin método declarado (`''`)
        # ENTRAN, bajo el instrumento `unknown`. La lista se deriva de `MANUAL_METHODS` para
        # que agregar un instrumento nuevo no requiera acordarse de este filtro.
        method__in=[manual_method_filter(name) for name in MANUAL_METHODS],
    )
    if scope.branch is not None:
        # Las filas con `branch` NULL (membresía global, o fila anterior a esa columna)
        # quedan FUERA de este filtro: no hay forma de saber si "sin sede" significa "todas"
        # o "ninguna", y mostrarlas bajo cualquier sede inventaría el dato.
        qs = qs.filter(branch=scope.branch)
    if method is not None:
        # Decisión 2 del docstring del módulo: filtra TODO lo que sigue, no solo `rows`.
        # `manual_method_filter` traduce `'unknown'` → `''` (el valor real de la columna).
        qs = qs.filter(method=manual_method_filter(method))
    return qs


def build_manual_payments_report(scope, *, method=None):
    qs = _base_queryset(scope, method)

    rows, truncated = _rows(qs)

    return {
        'period': scope.period_payload(),
        'filters': scope.filters_payload(
            method=method,
            method_label=METHOD_LABELS[method] if method else None,
        ),
        'totals': _totals(qs),
        'rows': rows,
        'row_limit': MAX_ROWS,
        'truncated': truncated,
        'series': _series(qs, scope),
    }


def _totals(qs):
    """Agregación sobre TODAS las filas del período (ver la nota de módulo sobre el tope):
    esta consulta no lleva `[:MAX_ROWS]`, así que el corte de la lista no le afecta."""
    agg = qs.aggregate(
        cash_sum=Sum('amount', filter=Q(method=ManualPayment.METHOD_CASH)),
        cash_count=Count('id', filter=Q(method=ManualPayment.METHOD_CASH)),
        transfer_sum=Sum('amount', filter=Q(method=ManualPayment.METHOD_TRANSFER)),
        transfer_count=Count('id', filter=Q(method=ManualPayment.METHOD_TRANSFER)),
        # Las filas históricas sin instrumento declarado: su propio subtotal, no un descarte.
        unknown_sum=Sum('amount', filter=Q(method=UNKNOWN_DB_METHOD)),
        unknown_count=Count('id', filter=Q(method=UNKNOWN_DB_METHOD)),
    )
    cash = _to_int(agg['cash_sum'])
    transfer = _to_int(agg['transfer_sum'])
    unknown = _to_int(agg['unknown_sum'])
    return {
        'cash': cash,
        'transfer': transfer,
        'unknown': unknown,
        # `total == cash + transfer + unknown` es la identidad que sostiene la barra apilada
        # del frontend, y también la garantía de que ninguna plata cobrada se cae del reporte.
        'total': cash + transfer + unknown,
        'count': agg['cash_count'] + agg['transfer_count'] + agg['unknown_count'],
        'cash_count': agg['cash_count'],
        'transfer_count': agg['transfer_count'],
        'unknown_count': agg['unknown_count'],
    }


def _series(qs, scope):
    """Un punto por bucket de `reports_base.bucket_keys(scope)`, RELLENADO CON CEROS.

    Igual que `_totals`, agrega sobre el queryset completo (no el recortado a `MAX_ROWS`):
    la serie tiene que sumar lo mismo que las tarjetas de arriba, no lo mismo que la tabla
    de abajo.
    """
    # `output_field=DateField()`: sin esto Django infiere el tipo del campo de origen
    # (`DateTimeField`) y el truncado devuelve un datetime con hora 00:00, que igual
    # funciona con `bucket_key()` pero arrastra un tzinfo innecesario a la comparación de
    # claves. Con `DateField()` el resultado es un `date` limpio, igual al que devuelven
    # `scope.date_from`/`date_to`.
    trunc = (TruncMonth('recorded_at', output_field=DateField())
             if scope.granularity == GRANULARITY_MONTH
             else TruncDate('recorded_at', output_field=DateField()))
    grouped = (
        qs.annotate(_bucket=trunc)
          .values('_bucket', 'method')
          .annotate(amount_sum=Sum('amount'))
          .order_by()
    )

    buckets = {key: {name: 0 for name in MANUAL_METHODS} for key in bucket_keys(scope)}
    for row in grouped:
        key = bucket_key(row['_bucket'], scope.granularity)
        if key not in buckets:
            # No debería pasar -el filtro de fecha ya acota al rango del scope-, pero ante
            # un desfase de huso horario es mejor ignorar el punto que reventar el reporte.
            continue
        # `manual_method_wire`: la columna guarda `''` y la serie publica `unknown`.
        buckets[key][manual_method_wire(row['method'])] = _to_int(row['amount_sum'])

    return [
        {'bucket': key,
         'cash': totals[METHOD_CASH],
         'transfer': totals[METHOD_TRANSFER],
         'unknown': totals[METHOD_UNKNOWN],
         # Misma identidad que en `_totals`, bucket por bucket.
         'total': totals[METHOD_CASH] + totals[METHOD_TRANSFER] + totals[METHOD_UNKNOWN]}
        for key, totals in buckets.items()
    ]


def _rows(qs):
    """`(rows, truncated)`. El `.count()` corre ANTES del `[:MAX_ROWS]` a propósito: es la
    única forma de saber si la lista real era más larga que el tope sin traer esas filas."""
    ordered = qs.select_related(
        'student_plan__user', 'student_plan__plan', 'recorded_by', 'branch',
    ).order_by('-recorded_at', '-id')
    total_count = ordered.count()
    payments = list(ordered[:MAX_ROWS])
    return [_row_payload(payment) for payment in payments], total_count > MAX_ROWS


def _row_payload(payment):
    """Fila publicada de un cobro.

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
    otro tenant (ninguna FILA de otra organización entra: eso lo corta `_base_queryset`).
    Si alguna vez importa de verdad, la solución correcta NO es la etiqueta: es congelar nombre
    y apellido en la fila al momento del cobro (columna nueva + migración), como ya hace
    `ClassOccupancySnapshot` con la sede y la disciplina.
    """
    student_plan = payment.student_plan
    student = student_plan.user
    return {
        'id': payment.id,
        'recorded_at': payment.recorded_at.isoformat(),
        'amount': _to_int(payment.amount),
        # Al cable va `unknown`, nunca `''`: ver `manual_method_wire`.
        'method': manual_method_wire(payment.method),
        'method_label': METHOD_LABELS[manual_method_wire(payment.method)],
        'reference': payment.reference,
        'student_id': student.id,
        'student_name': _full_name(student),
        'student_plan_id': student_plan.id,
        'plan_name': student_plan.plan.name,
        'branch_id': payment.branch_id,
        'branch_name': payment.branch.name if payment.branch_id else None,
        'recorded_by_id': payment.recorded_by_id,
        'recorded_by_name': _recorded_by_name(payment.recorded_by),
    }


def manual_payments_export_spec(data):
    """`{'header', 'rows', 'total_row'}` para `reports_base.export_response`.

    Mismo layout que `TeacherPaymentRecordViewSet._summary_total_row` (views.py): la
    columna de texto de la fila TOTAL queda en la primera celda y el monto agregado en la
    última, alineado con la columna `Monto` del resto de las filas.
    """
    header = ['Fecha', 'Alumno', 'Plan', 'Sede', 'Método', 'Referencia', 'Registrado por',
              'Monto']
    rows = [
        [
            row['recorded_at'], row['student_name'], row['plan_name'],
            row['branch_name'] or '', row['method_label'], row['reference'],
            row['recorded_by_name'], row['amount'],
        ]
        for row in data['rows']
    ]
    if data['truncated']:
        # EL CORTE SE DECLARA DENTRO DEL ARCHIVO, no solo en el JSON.
        # `rows` viene recortado a `MAX_ROWS` y la fila TOTAL sale de `data['totals']`, que se
        # agrega sobre el período COMPLETO. Las dos cosas son correctas por separado —el total
        # no puede mentir por un límite de la lista— pero juntas producen una planilla donde
        # sumar la columna `Monto` NO da el TOTAL. Sin esta línea, ese descuadre es MUDO: el
        # que abre el CSV concluye que el reporte está roto, o peor, corrige el total a mano.
        # La pantalla ya lo avisa; el archivo viaja solo y tiene que avisarlo también.
        rows.append([
            f'— Lista recortada a {data["row_limit"]} de {data["totals"]["count"]} cobros. '
            f'El TOTAL de abajo es del período completo. —',
            '', '', '', '', '', '', '',
        ])
    total_row = ['TOTAL', '', '', '', '', '', '', data['totals']['total']]
    return {'header': header, 'rows': rows, 'total_row': total_row}
