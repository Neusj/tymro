"""Reporte de INGRESOS (P3.4 · Pieza 1). Plata que entró, plata que se devolvió, y el neto.

TRES NÚMEROS QUE VIAJAN SIEMPRE JUNTOS, EN TODOS LOS NIVELES. No existe en este payload un
campo que sea "el ingreso" a secas: cada nivel —el total, cada método y cada punto de la
serie— publica `gross`, `refunds` y `net` por separado. Un único número que ya trajera la
resta hecha es exactamente lo que hacía que el reporte mintiera cuando había una devolución:
el administrador no podía distinguir "vendí poco" de "vendí y devolví".

POR QUÉ EL BRUTO SE CUENTA POR `collected_at` Y NO POR `status='approved'`
`status` es un valor PISABLE: cuando el proveedor avisa de un reembolso o un contracargo la
fila pasa a `refunded` y el hecho de que ese cobro ENTRÓ desaparece. Un reporte que sumara
`status='approved'` empezaría a mentir HACIA ATRÁS: el ingreso de julio cambiaría en agosto,
solo porque en agosto se devolvió algo. `collected_at` se estampa una vez y no se limpia
nunca (ver el comentario del campo en `models.py`). Tampoco es `processed_at`: ese significa
"además se activó la membresía", y existe el camino real donde la plata entra y la activación
falla (`plan_org_mismatch`). La plata entró igual, así que el ingreso no puede depender de
que la activación haya salido bien.

POR QUÉ LAS DEVOLUCIONES EXIGEN `collected_at__isnull=False`
Nunca se resta plata que no se sumó. Existen filas con devolución registrada y sin cobro
aplicado —el histórico irrecuperable que documenta la migración 0044: cobros devueltos ANTES
de que estos campos existieran, que quedaron sin `collected_at` a propósito—. Restarlas
produciría un neto negativo INVENTADO, plata que nunca entró a la cuenta del gimnasio y que
el reporte estaría descontando de la que sí entró.

BASE CAJA: LA DEVOLUCIÓN SE IMPUTA AL PERÍODO EN QUE OCURRIÓ
El bruto se agrupa por fecha de COBRO y las devoluciones por fecha de DEVOLUCIÓN, así que un
cobro de junio devuelto en julio suma en junio y resta en JULIO —no reabre junio—. Es
deliberado: el número de un período cerrado no puede cambiar después de haberse informado.
La consecuencia visible y correcta es que un período puede cerrar con neto NEGATIVO (se
devolvió más de lo que se cobró en esos días); eso no es un error de cálculo, es el mes en que
salió plata de la caja.

DEVOLUCIONES DE EFECTIVO Y TRANSFERENCIA: SIEMPRE 0, Y EXPLÍCITAS
No existe mecanismo de devolución manual (`ManualPayment` no tiene anulación ni monto
devuelto). Todas las filas de `by_method` publican igual la columna en 0 en vez de omitirla:
el front dibuja la misma resta en todas, y un 0 declarado dice "no hubo", mientras que una
clave ausente dice "no sé".

EL CUARTO MEDIO (`unknown`) NO ES UN CASO BORDE: ES PLATA QUE YA ESTÁ EN PRODUCCIÓN
`ManualPayment.method` nació en P3.2 y su migración NO hizo backfill, así que los cobros
registrados en 8.2/8.3 tienen `method=''` — se sabe que entraron y no se sabe si fueron
efectivo o transferencia. Si el bruto se filtrara solo por `cash`/`transfer`, esa plata
desaparecería del ingreso y el reporte informaría MENOS de lo que el gimnasio facturó: el modo
de fallo exacto que esta reportería existe para evitar. Por eso el medio `unknown` (ver
`reports_base`) se cuenta como bruto igual que los otros y se publica como su propia fila,
también en cero: si el gimnasio ve "Sin método registrado: $0" sabe que no le falta nada, y
si ve un monto sabe que existe y de dónde viene.

FILTRO POR SEDE: LAS FILAS SIN SUCURSAL QUEDAN AFUERA
`PaymentTransaction.branch` y `ManualPayment.branch` son NULL cuando no hay sede registrada
(plan global, o fila anterior a que existieran esas columnas), y ahí NULL significa "sin
dato", no "todas las sedes". Por eso, con `scope.branch` puesto, esas filas NO entran: LOS
TOTALES POR SEDE NO SUMAN EL TOTAL DE LA ORGANIZACIÓN. Es la lectura honesta —repartir una
fila sin sede entre las sedes sería inventar de dónde salió esa plata—, pero hay que saberlo
antes de restar dos reportes.

TODO SALE DE NUESTRA BASE. Ninguna consulta al proveedor de pago: lo que se suma es lo que el
webhook escribió (`services/payments.py`). Un reporte que consultara MercadoPago en vivo
dependería de su disponibilidad y devolvería números distintos en dos corridas seguidas.
"""
from decimal import Decimal

from django.db.models import Count, Sum
from django.db.models.functions import TruncDate, TruncMonth

from ..models import ManualPayment, PaymentTransaction
from .reports_base import (GRANULARITY_MONTH, METHOD_LABELS, METHOD_MERCADOPAGO,
                           REVENUE_METHODS, bucket_key, bucket_keys,
                           manual_method_filter, pct_delta)

#: Etiqueta de las filas del export que no son de un método puntual sino del total.
ALL_METHODS_LABEL = 'Todos los métodos'

_ZERO = (Decimal('0'), 0)


def _trunc(field, granularity):
    """Función de agrupación por bucket. Usa la zona del proyecto (`America/Santiago`),
    igual que el `__date__gte/__date__lte` del filtro de rango, así que un cobro cae en el
    mismo día para el filtro y para la serie."""
    return TruncMonth(field) if granularity == GRANULARITY_MONTH else TruncDate(field)


def _org_scoped(model, scope):
    """Base multitenant de toda consulta del reporte: la organización DEL SCOPE, siempre.

    `scope.organization_id` es la del actor (la estampa `views_reports._report_scope`, nunca
    el request) y `scope.branch`, si viene, es una sucursal ya verificada como de esa
    organización. Acá no se valida nada de eso de nuevo: se aplica.
    """
    queryset = model.objects.filter(organization_id=scope.organization_id)
    if scope.branch is not None:
        queryset = queryset.filter(branch=scope.branch)
    return queryset


def _in_range(queryset, scope, field):
    """Rango por fecha LOCAL sobre una columna `DateTimeField` (ver `reports_base`)."""
    return queryset.filter(**{f'{field}__date__gte': scope.date_from,
                              f'{field}__date__lte': scope.date_to})


def _by_bucket(queryset, *, field, amount, scope):
    """`{clave de bucket: (monto Decimal, cantidad de filas)}`.

    El `.order_by()` vacío descarta el `Meta.ordering` de los dos modelos (`-created_at` y
    `-recorded_at, -id`), que acá no sirve para nada: el resultado se indexa por bucket y el
    orden de la serie lo pone `bucket_keys`. Verificado en Django 5.0.6 que ese ordering ya
    NO entra al GROUP BY (dejó de hacerlo en 3.1; antes agregaba las columnas de orden y
    devolvía una fila por pago en vez de una por bucket, rompiendo la agregación en
    silencio). Se deja explícito para que un `Meta.ordering` nuevo o un ordering heredado de
    un queryset de más arriba no pueda reabrir esa trampa.
    """
    rows = (queryset
            .annotate(bucket=_trunc(field, scope.granularity))
            .values('bucket')
            .annotate(bucket_amount=Sum(amount), bucket_rows=Count('id'))
            .order_by())
    return {
        bucket_key(row['bucket'], scope.granularity):
            (row['bucket_amount'] or Decimal('0'), row['bucket_rows'])
        for row in rows
    }


def _method_data(scope, method):
    """`(fila de by_method, {bucket: {gross, refunds, net}})` para UN método.

    Un único lugar donde se define qué es el bruto y qué las devoluciones de cada método: el
    período anterior y el filtro por método reutilizan esta misma función, así que no pueden
    divergir del período actual (un delta calculado con dos definiciones distintas compararía
    manzanas con peras).
    """
    if method == METHOD_MERCADOPAGO:
        # SIN filtro por `provider`: 'mercadopago' es la etiqueta del cobro EN LÍNEA, y el
        # proveedor es configurable. Si mañana entra otro, su plata es ingreso en línea igual y
        # no puede desaparecer del reporte por no llamarse así.
        base = _org_scoped(PaymentTransaction, scope)
        gross = _by_bucket(_in_range(base, scope, 'collected_at'),
                           field='collected_at', amount='amount', scope=scope)
        # `collected_at__isnull=False`: ver el encabezado del módulo. Sin este filtro el
        # reporte restaría devoluciones de cobros que nunca sumó.
        refunds = _by_bucket(
            _in_range(base.filter(collected_at__isnull=False), scope, 'refunded_at'),
            field='refunded_at', amount='refunded_amount', scope=scope)
    else:
        # `manual_method_filter` traduce el medio del cable al valor de la columna, y el único
        # caso no obvio es `'unknown'` → `''`. NO se puede filtrar solo por `cash`/`transfer`:
        # las filas cobradas antes de P3.2 tienen `method=''` (su migración no hizo backfill
        # porque no se sabe qué fueron) y son plata REAL que ya está en producción. Dejarlas
        # fuera del bruto haría que el reporte informe menos de lo que el gimnasio facturó.
        base = _org_scoped(ManualPayment, scope).filter(
            method=manual_method_filter(method))
        gross = _by_bucket(_in_range(base, scope, 'recorded_at'),
                           field='recorded_at', amount='amount', scope=scope)
        refunds = {}    # no hay devolución manual; se publica en 0, no se omite

    # Redondeo al FINAL y una sola vez, sobre el monto ya sumado por el motor: redondear cada
    # pago y después sumar acumularía el error de cada fila. Y el neto se calcula restando los
    # ENTEROS ya publicados (no los Decimal), para que la resta que muestra el front cuadre
    # exactamente con los dos números de al lado.
    series = {}
    for key in bucket_keys(scope):
        bucket_gross = int(round(gross.get(key, _ZERO)[0]))
        bucket_refunds = int(round(refunds.get(key, _ZERO)[0]))
        series[key] = {
            'gross': bucket_gross,
            'refunds': bucket_refunds,
            'net': bucket_gross - bucket_refunds,
        }

    # El total se suma sobre TODAS las filas que devolvió la consulta y la serie solo sobre
    # los buckets del rango. Coinciden porque el filtro (`__date__gte/lte`) y el `Trunc`
    # convierten a la MISMA zona, así que ningún pago del rango puede caer en un bucket que
    # la serie no tenga. Si alguna vez divergieran, el total sería el completo y a la serie le
    # faltaría un punto: el error se ve en el gráfico y no en la plata.
    total_gross = int(round(sum((amount for amount, _ in gross.values()), Decimal('0'))))
    total_refunds = int(round(sum((amount for amount, _ in refunds.values()), Decimal('0'))))
    row = {
        'method': method,
        'label': METHOD_LABELS[method],
        'gross': total_gross,
        'refunds': total_refunds,
        'net': total_gross - total_refunds,
        'payments_count': sum(rows for _, rows in gross.values()),
        'refunds_count': sum(rows for _, rows in refunds.values()),
    }
    return row, series


def _totals(rows):
    """Suma de las filas por método. Los totales son la suma de lo publicado y no una
    consulta aparte: así las columnas del reporte CUADRAN entre sí, y no puede pasar que el
    total diga una cosa y las tres filas de abajo sumen otra."""
    gross = sum(row['gross'] for row in rows)
    refunds = sum(row['refunds'] for row in rows)
    return {
        'gross': gross,
        'refunds': refunds,
        # El neto se deriva de los dos enteros ya sumados y nunca se acumula aparte: así el
        # total publicado cumple la misma resta que cada fila de arriba.
        'net': gross - refunds,
        'payments_count': sum(row['payments_count'] for row in rows),
        'refunds_count': sum(row['refunds_count'] for row in rows),
    }


def build_revenue_report(scope, *, method=None):
    """Ingresos del período: totales, comparación con el anterior, por método y serie.

    `method=None` publica TODOS los métodos de `REVENUE_METHODS` aunque alguno esté en cero
    (una fila ausente se lee como "no existe ese medio de cobro", que es otra afirmación), y
    eso incluye `unknown`: los totales son la suma de las filas publicadas, así que omitir una
    con movimiento rompería el cuadre del reporte consigo mismo. Con `method` puesto va solo
    esa fila y los totales son los de ese método, no un subtotal dentro del total.
    """
    methods = (method,) if method else REVENUE_METHODS

    by_method, series_by_method = [], []
    for name in methods:
        row, series = _method_data(scope, name)
        by_method.append(row)
        series_by_method.append(series)

    # El período anterior se calcula con LA MISMA función y el MISMO filtro de método: si se
    # comparara contra otra definición de bruto, el delta mediría la diferencia entre las dos
    # consultas y no el movimiento del negocio.
    previous_scope = scope.previous()
    previous_totals = _totals([_method_data(previous_scope, name)[0] for name in methods])
    totals = _totals(by_method)

    series = []
    for key in bucket_keys(scope):
        bucket_gross = sum(item[key]['gross'] for item in series_by_method)
        bucket_refunds = sum(item[key]['refunds'] for item in series_by_method)
        series.append({
            'bucket': key,
            'gross': bucket_gross,
            'refunds': bucket_refunds,
            'net': bucket_gross - bucket_refunds,
        })

    return {
        'period': scope.period_payload(),
        'filters': scope.filters_payload(
            method=method,
            method_label=METHOD_LABELS[method] if method else None,
        ),
        'totals': totals,
        'previous': {
            'period': previous_scope.period_payload(),
            'totals': previous_totals,
        },
        'comparison': {
            'net_delta': totals['net'] - previous_totals['net'],
            # `pct_delta` devuelve None si el período anterior fue 0: no hay porcentaje de
            # crecimiento sobre una base inexistente, y un 100 % ahí sería inventado.
            'net_delta_pct': pct_delta(totals['net'], previous_totals['net']),
            'gross_delta': totals['gross'] - previous_totals['gross'],
            'gross_delta_pct': pct_delta(totals['gross'], previous_totals['gross']),
        },
        'by_method': by_method,
        'series': series,
    }


def revenue_export_spec(data):
    """Filas del CSV/XLSX: bruto, devoluciones y neto en COLUMNAS SEPARADAS.

    El export muestra la misma resta que el JSON. Un CSV con una sola columna de "ingresos"
    sería el único lugar del reporte donde la devolución queda escondida, y es justo el
    archivo que después alguien pega en una planilla y suma.

    Dos bloques con GRANO DISTINTO, y la columna `Período` es la que los distingue: primero
    una fila por método (período completo), después una fila por bucket de la serie. Por eso
    la columna no se puede sumar de punta a punta —contaría dos veces la misma plata—; la
    fila TOTAL final es el total del período y también el del bloque de la serie que la
    precede.

    Las filas de la serie dejan VACÍAS las dos columnas de cantidad: la serie no publica
    contadores, y rellenarlas con 0 diría "ese día no hubo cobros" al lado de un bruto
    positivo, que es una contradicción escrita en el archivo.
    """
    header = ['Período', 'Método', 'Bruto', 'Devoluciones', 'Neto', 'Cobros',
              'Devoluciones (n)']
    period = data['period']
    period_label = f"{period['date_from']} a {period['date_to']}"
    # Con filtro de método, la serie es de ESE método y decir "todos" sería falso.
    series_label = data['filters'].get('method_label') or ALL_METHODS_LABEL

    rows = [
        [period_label, row['label'], row['gross'], row['refunds'], row['net'],
         row['payments_count'], row['refunds_count']]
        for row in data['by_method']
    ]
    rows += [
        [point['bucket'], series_label, point['gross'], point['refunds'], point['net'],
         '', '']
        for point in data['series']
    ]

    totals = data['totals']
    total_row = ['TOTAL', series_label, totals['gross'], totals['refunds'], totals['net'],
                 totals['payments_count'], totals['refunds_count']]
    return {'header': header, 'rows': rows, 'total_row': total_row}
