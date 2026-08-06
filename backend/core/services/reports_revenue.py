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

ESTE MÓDULO ES LA CAPA 1 DE UN DRILL-DOWN DE TRES
La capa 2 (el listado de los pagos de UN método) y la capa 3 (el detalle de un pago) viven en
`reports_revenue_detail.py`, y consumen de acá `method_querysets` y `method_totals`. Esas dos
funciones son públicas justo por eso: son la ÚNICA definición de qué es el bruto y qué son las
devoluciones de cada método, y de cómo se agregan. El listado que abre el administrador al
hacer clic sobre una fila de `by_method` tiene que sumar exactamente esa fila; si cada capa
armara su propio queryset, el día que alguien cambie la definición del bruto una de las dos se
quedaría atrás y el drill-down mostraría un total distinto al de la pantalla anterior.
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

#: Columna por la que se data una DEVOLUCIÓN. Una sola, y solo la tienen los cobros en línea.
REFUNDS_DATE_FIELD = 'refunded_at'

_ZERO = (Decimal('0'), 0)


def gross_date_field(method):
    """Columna por la que se DATA el cobro de cada método.

    Existe como función y no como literal repetido porque tres cosas distintas tienen que
    usar la misma: el filtro de rango, el `Trunc` de la serie y el orden del listado de la
    capa 2. Si el listado ordenara por otra columna que la que lo filtra, la primera página
    no sería la de los cobros más recientes del período.
    """
    return 'collected_at' if method == METHOD_MERCADOPAGO else 'recorded_at'


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


def method_querysets(scope, method):
    """`(bruto, devoluciones)` de UN método: los dos querysets que DEFINEN su plata.

    FUENTE ÚNICA de esa definición, y por eso es pública. La consume la capa 1 de acá abajo
    (`_method_data`, que agrupa por bucket) y también el drill-down de
    `reports_revenue_detail.py` (que lista las filas una por una). Con un queryset por capa,
    cambiar mañana qué cuenta como bruto arreglaría una pantalla y dejaría la otra informando
    otro número — y las dos están a un clic de distancia.

    Los dos vienen YA acotados por organización, por sede y por el rango del período, cada uno
    por SU columna de fecha: el bruto por la del cobro (`gross_date_field`) y las devoluciones
    por `refunded_at`. Base caja, ver el encabezado del módulo.

    `refunds` es **None** —no un queryset vacío— para los métodos manuales: no existe
    mecanismo de devolución manual (`ManualPayment` no tiene anulación ni monto devuelto), así
    que ahí no hay "cero devoluciones encontradas" sino "esta pregunta no aplica". El caller
    publica igual la columna en 0; lo que no puede hacer es simular una consulta que no
    existe.
    """
    if method == METHOD_MERCADOPAGO:
        # SIN filtro por `provider`: 'mercadopago' es la etiqueta del cobro EN LÍNEA, y el
        # proveedor es configurable. Si mañana entra otro, su plata es ingreso en línea igual y
        # no puede desaparecer del reporte por no llamarse así.
        base = _org_scoped(PaymentTransaction, scope)
        gross = _in_range(base, scope, gross_date_field(method))
        # `collected_at__isnull=False`: ver el encabezado del módulo. Sin este filtro el
        # reporte restaría devoluciones de cobros que nunca sumó.
        refunds = _in_range(base.filter(collected_at__isnull=False), scope,
                            REFUNDS_DATE_FIELD)
        return gross, refunds

    # `manual_method_filter` traduce el medio del cable al valor de la columna, y el único
    # caso no obvio es `'unknown'` → `''`. NO se puede filtrar solo por `cash`/`transfer`:
    # las filas cobradas antes de P3.2 tienen `method=''` (su migración no hizo backfill
    # porque no se sabe qué fueron) y son plata REAL que ya está en producción. Dejarlas
    # fuera del bruto haría que el reporte informe menos de lo que el gimnasio facturó.
    base = _org_scoped(ManualPayment, scope).filter(method=manual_method_filter(method))
    return _in_range(base, scope, gross_date_field(method)), None


def _aggregate(queryset, amount_field):
    """`(monto entero, cantidad de filas)` de un queryset entero, o `(0, 0)` si es None.

    UN SOLO redondeo, al final, sobre el monto que ya sumó el motor: redondear cada pago y
    después sumar acumularía el error de cada fila.
    """
    if queryset is None:
        return 0, 0
    agg = queryset.aggregate(total=Sum(amount_field), rows=Count('id'))
    return int(round(agg['total'] or Decimal('0'))), agg['rows']


def method_totals(gross_queryset, refunds_queryset):
    """Los cinco números publicados de un método, a partir de sus dos querysets.

    Pública y compartida por el MISMO motivo que `method_querysets`: la fila de `by_method`
    (capa 1) y los `totals` del listado (capa 2) salen literalmente de esta función, así que
    no pueden diferir ni por la definición ni por el redondeo. Es la garantía de que el total
    del drill-down es el mismo número sobre el que el administrador hizo clic.

    El neto se calcula restando los ENTEROS ya publicados (no los Decimal), para que la resta
    que muestra el front cuadre exactamente con los dos números de al lado.
    """
    gross, payments_count = _aggregate(gross_queryset, 'amount')
    refunds, refunds_count = _aggregate(refunds_queryset, 'refunded_amount')
    return {
        'gross': gross,
        'refunds': refunds,
        'net': gross - refunds,
        'payments_count': payments_count,
        'refunds_count': refunds_count,
    }


def _method_data(scope, method):
    """`(fila de by_method, {bucket: {gross, refunds, net}})` para UN método.

    El período anterior y el filtro por método reutilizan esta misma función, así que no
    pueden divergir del período actual (un delta calculado con dos definiciones distintas
    compararía manzanas con peras).
    """
    gross_queryset, refunds_queryset = method_querysets(scope, method)
    gross = _by_bucket(gross_queryset, field=gross_date_field(method), amount='amount',
                       scope=scope)
    # `refunds_queryset is None` = método sin mecanismo de devolución: la serie publica 0 en
    # todos los buckets, no omite la columna.
    refunds = ({} if refunds_queryset is None
               else _by_bucket(refunds_queryset, field=REFUNDS_DATE_FIELD,
                               amount='refunded_amount', scope=scope))

    # Mismo redondeo que `method_totals` y por el mismo motivo: una vez, al final, sobre el
    # monto ya sumado por el motor.
    series = {}
    for key in bucket_keys(scope):
        bucket_gross = int(round(gross.get(key, _ZERO)[0]))
        bucket_refunds = int(round(refunds.get(key, _ZERO)[0]))
        series[key] = {
            'gross': bucket_gross,
            'refunds': bucket_refunds,
            'net': bucket_gross - bucket_refunds,
        }

    # Los totales NO se suman desde los buckets de acá arriba aunque el resultado sea el mismo:
    # salen de `method_totals`, la función que también usa la capa 2. Cuesta dos agregaciones
    # más por método —consultas indexadas por (organización, fecha)— y a cambio hace
    # ESTRUCTURALMENTE imposible que la fila de `by_method` y el listado que se abre al
    # clickearla publiquen totales distintos. La serie sigue saliendo de los buckets, y suma lo
    # mismo porque el filtro (`__date__gte/lte`) y el `Trunc` convierten a la MISMA zona: ningún
    # pago del rango puede caer en un bucket que la serie no tenga.
    row = {'method': method, 'label': METHOD_LABELS[method]}
    row.update(method_totals(gross_queryset, refunds_queryset))
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
