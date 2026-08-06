"""Reporte de ocupación de clases (P3.4 · Pieza 3) y el RASTRO que lo alimenta.

DOS FUENTES QUE SE SUMAN, UN SOLO DENOMINADOR
---------------------------------------------
El reporte no mide sobre las clases que quedaron en la base: mide sobre la oferta que el
gimnasio DICTÓ en el período. Son dos tablas:

* las `GymClass` VIVAS del rango, con sus inscripciones activas;
* los `ClassOccupancySnapshot` del rango, o sea el rastro de las clases que la poda de la
  ventana rodante ya borró (`rolling_window._prune_past_empty_classes`).

Sin la segunda fuente el porcentaje sería OPTIMISTA y —peor— mejoraría solo por el paso del
tiempo: lo que la poda se lleva son exactamente las clases que nadie tomó, así que el
histórico de un mes cerrado se vería cada vez mejor a medida que se van borrando sus clases
vacías. `totals.pruned_classes` publica cuántas de las clases contadas vinieron del rastro,
para que el administrador sepa qué parte del denominador ya no tiene fila viva detrás.

Este módulo es también el ÚNICO escritor del rastro (`record_occupancy_snapshot`): la poda lo
llama, pero la forma de la fila —qué se copia como texto y por qué— se decide acá, junto al
reporte que la lee.

QUÉ CUENTA COMO OFERTA DICTADA
------------------------------
`scheduled`, `in_progress`, `completed` y `completed_early`. Quedan afuera `cancelled` y
`suspended`: esa clase NO se dictó, así que no es oferta desaprovechada —contarla con 0
inscritos castigaría al gimnasio por haber cancelado bien—. `completed_early` sí entra: la
clase se dictó, alguien la cerró antes de hora.

⚠️ Y NO se filtra por `is_active=True` a secas, aunque la intención de la spec sea "ignorar
las clases dadas de baja". En este modelo `GymClass.is_active` NO es un flag independiente:
lo apaga TODO cierre terminal. `refresh_status_from_schedule` (models.py) pone
`is_active=False` junto con el flip automático a `completed`, y las acciones humanas hacen lo
mismo al cancelar, cerrar anticipadamente y suspender (`views.py`,
`recurrence.cancel_future_instances_for_template`). O sea: `is_active=True` + `completed` es
una combinación que no existe, y un `filter(is_active=True)` dejaría el reporte de cualquier
mes ya terminado en CERO clases. El predicado real está en `DICTATED_Q`: el `is_active` se
exige solo donde todavía significa algo (una clase futura o en curso dada de baja sin pasar
por ningún cierre), y para los estados terminales manda el estado.
"""
from collections import namedtuple

from django.db.models import Count, Q
from django.utils import timezone

from ..models import ClassOccupancySnapshot, GymClass
from .reports_base import bucket_key, bucket_keys

#: Etiqueta del grupo de las clases sin disciplina asignada. Es un grupo REAL (esas clases se
#: dictaron y ocuparon una sala), no un hueco: por eso tiene nombre propio en vez de quedar
#: fuera del `by_discipline`.
NO_DISCIPLINE_LABEL = 'Sin disciplina'

# Oferta que el gimnasio DICTÓ. Ver el docstring del módulo para el porqué de la forma
# partida: `is_active` es derivado del estado en este modelo, así que exigirlo parejo vaciaría
# el reporte de todo período pasado.
DICTATED_Q = (
    Q(status__in=(GymClass.Status.COMPLETED, GymClass.Status.COMPLETED_EARLY))
    | Q(status__in=(GymClass.Status.SCHEDULED, GymClass.Status.IN_PROGRESS), is_active=True)
)

#: Una clase ya normalizada, venga de la tabla viva o del rastro. El reporte agrupa SIEMPRE
#: sobre esta forma: así las dos fuentes se suman sin que cada agregación tenga que recordar
#: de dónde salió cada fila (`pruned` es lo único que las distingue, y solo lo usa el conteo
#: de `pruned_classes`).
_Row = namedtuple('_Row', 'discipline_id discipline_name capacity enrolled local_start pruned')


# --------------------------------------------------------------------------------------
# El rastro. Lo escribe la poda (`rolling_window._prune_past_empty_classes`), dentro de la
# MISMA transacción del borrado.
# --------------------------------------------------------------------------------------

def _teacher_display_name(teacher):
    """Nombre completo del profe, con fallback al username (patrón de la casa, ver
    `seed_demo_data` y `plan_expiry_notifications`). Se guarda como TEXTO porque la cuenta
    del profesor puede borrarse o moverse de organización mucho después de la poda."""
    if teacher is None:
        return ''
    return (teacher.get_full_name() or '').strip() or teacher.username


def record_occupancy_snapshot(gym_class):
    """Deja el rastro de ocupación de `gym_class` y lo devuelve (o `None` si no hay nada que
    rastrear). Ver el docstring de `ClassOccupancySnapshot` para el porqué del modelo.

    IDEMPOTENTE por `get_or_create` sobre (organización, `source_class_id`), que es la clave
    única de la tabla. No es una precaución teórica: la poda atrapa las excepciones POR CLASE
    y el job corre todos los días, así que un reintento sobre la misma clase tiene que
    encontrar su rastro y no escribir un segundo. Un rastro duplicado infla el DENOMINADOR
    del reporte —la misma clase contada dos veces como oferta vacía— y eso no se nota mirando
    el porcentaje, solo lo delata la fila repetida.

    Los `defaults` NO se re-escriben si la fila ya existía: el rastro fotografía el momento
    de la primera poda y no hay un segundo momento que valga más.
    """
    # Sin pk no hay clave por la que deduplicar (y una clase sin guardar no pudo ser podada).
    if gym_class is None or gym_class.pk is None:
        return None

    # Los nombres viajan como TEXTO además de la FK: la clase se borra en esta misma
    # transacción y la sede/disciplina/profe pueden borrarse cualquier día después (las tres
    # FK del snapshot son SET_NULL). Cuando el reporte lea esta fila, el id puede ya no
    # resolver a nada y el texto es lo único que queda para el `by_discipline`.
    snapshot, _created = ClassOccupancySnapshot.objects.get_or_create(
        organization_id=gym_class.organization_id,
        source_class_id=gym_class.pk,
        defaults={
            'source': ClassOccupancySnapshot.SOURCE_PRUNE,
            'branch_id': gym_class.branch_id,
            'branch_name': getattr(gym_class.branch, 'name', '') or '',
            'discipline_id': gym_class.discipline_id,
            'discipline_name': getattr(gym_class.discipline, 'name', '') or '',
            'teacher_id': gym_class.teacher_id,
            'teacher_name': _teacher_display_name(gym_class.teacher),
            'class_name': gym_class.name or '',
            'start_datetime': gym_class.start_datetime,
            'end_datetime': gym_class.end_datetime,
            'capacity': gym_class.capacity or 0,
            # Se CUENTA de verdad, no se hardcodea el 0. Hoy la poda solo alcanza clases con
            # `enrollments__isnull=True`, así que este count es siempre 0; el día que aparezca
            # otra fuente de rastro (una cancelada, un archivado manual) el reporte va a sumar
            # este campo sin que haya que revisar quién lo escribió. `status='active'` porque
            # una inscripción cancelada no es una plaza ocupada — la misma definición de
            # "inscrito" que usa el reporte para las clases vivas.
            'enrolled_count': gym_class.enrollments.filter(status='active').count(),
        },
    )
    return snapshot


# --------------------------------------------------------------------------------------
# Lectura de las dos fuentes. Una query por fuente: nada de un count por clase.
# --------------------------------------------------------------------------------------

def _live_rows(scope, discipline):
    """Las clases VIVAS del rango, ya con su cantidad de inscritos activos.

    UNA sola query. El conteo va como `Count('enrollments', filter=...)` sobre el queryset de
    clases (agrupado por pk), y no con un `.count()` por clase ni recorriendo
    `gym_class.enrollments`: el rango puede ser de dos años (`MAX_PERIOD_DAYS`) y eso serían
    miles de queries en una request sincrónica de gunicorn.

    `.order_by()` limpia el `ordering` del Meta a propósito: en una consulta agrupada, el
    campo de orden se cuela en el GROUP BY y encima obliga a un sort que este reporte no
    necesita (el orden lo deciden las agregaciones de abajo, no la base).
    """
    queryset = GymClass.objects.filter(
        DICTATED_Q,
        organization_id=scope.organization_id,
        start_datetime__date__gte=scope.date_from,
        start_datetime__date__lte=scope.date_to,
    )
    # `scope.branch` ya vino verificada como de esta organización (`views_reports._scoped_id`),
    # así que se filtra por su id y no por el crudo del query string.
    if scope.branch_id is not None:
        queryset = queryset.filter(branch_id=scope.branch_id)
    if discipline is not None:
        queryset = queryset.filter(discipline_id=discipline.id)

    rows = (
        queryset
        .annotate(enrolled=Count('enrollments', filter=Q(enrollments__status='active')))
        .values('capacity', 'enrolled', 'start_datetime', 'discipline_id', 'discipline__name')
        .order_by()
    )
    return [
        _Row(
            discipline_id=item['discipline_id'],
            discipline_name=item['discipline__name'] or NO_DISCIPLINE_LABEL,
            capacity=item['capacity'] or 0,
            enrolled=item['enrolled'] or 0,
            local_start=timezone.localtime(item['start_datetime']),
            pruned=False,
        )
        for item in rows
    ]


def _pruned_rows(scope, discipline):
    """El rastro de las clases que la poda borró, en el rango.

    `enrolled_count` se lee de la columna (hoy siempre 0) en vez de asumirlo: ver
    `record_occupancy_snapshot`. Los filtros de sede y disciplina van por FK, así que un
    snapshot cuya sede o disciplina se borró después (FK a NULL) queda FUERA de una vista
    filtrada por ellas y solo aparece en la vista total. Es la contrapartida aceptada de
    poder filtrar por id: el texto guardado sirve para MOSTRAR el grupo, no para filtrarlo
    (dos disciplinas distintas pueden haberse llamado igual en momentos distintos).
    """
    queryset = ClassOccupancySnapshot.objects.filter(
        organization_id=scope.organization_id,
        start_datetime__date__gte=scope.date_from,
        start_datetime__date__lte=scope.date_to,
    )
    if scope.branch_id is not None:
        queryset = queryset.filter(branch_id=scope.branch_id)
    if discipline is not None:
        queryset = queryset.filter(discipline_id=discipline.id)

    rows = queryset.values(
        'capacity', 'enrolled_count', 'start_datetime',
        'discipline_id', 'discipline__name', 'discipline_name',
    ).order_by()
    return [
        _Row(
            discipline_id=item['discipline_id'],
            # Si la disciplina sigue viva se usa SU nombre actual, para que la fila caiga en
            # el mismo grupo que las clases vivas de esa disciplina. Recién si la FK quedó
            # NULL manda el texto que la poda fotografió.
            discipline_name=(item['discipline__name'] or item['discipline_name']
                             or NO_DISCIPLINE_LABEL),
            capacity=item['capacity'] or 0,
            enrolled=item['enrolled_count'] or 0,
            local_start=timezone.localtime(item['start_datetime']),
            pruned=True,
        )
        for item in rows
    ]


# --------------------------------------------------------------------------------------
# Agregación. Los tres cortes (disciplina, hora, serie) salen del MISMO recorrido.
# --------------------------------------------------------------------------------------

def _empty_group():
    return {
        'classes': 0,
        'capacity': 0,
        'enrolled': 0,
        # Numerador del porcentaje. Se separa de `enrolled` por las clases con cupo 0: ver
        # `_accumulate` y `_rate`.
        'rated_enrolled': 0,
        'full_classes': 0,
        'empty_classes': 0,
    }


def _accumulate(group, row):
    """Suma una clase a un grupo.

    Las clases con `capacity == 0` cuentan en `classes` (se dictaron) pero NO tienen
    denominador: dividir por cero no es una ocupación del 0 % ni del 100 %, es una pregunta
    sin respuesta. Por eso su `enrolled` tampoco entra en `rated_enrolled`: si entrara al
    numerador sin aportar al denominador, el porcentaje podría pasar del 100 % por una clase
    a la que nadie le declaró cupo. `capacity` y `enrolled` que publica el payload siguen
    siendo las sumas COMPLETAS —es lo que el gimnasio ofreció y vendió—, y el único caso en
    que el numerador del porcentaje difiere de `enrolled` es ese: cupo 0 con gente adentro.

    `full_classes` exige `capacity > 0` por lo mismo (con cupo 0, `enrolled >= capacity` es
    verdadero siempre y una clase sin cupo declarado no está "llena"). `empty_classes` no lo
    exige: cero inscritos es cero inscritos, haya cupo declarado o no.
    """
    group['classes'] += 1
    group['capacity'] += row.capacity
    group['enrolled'] += row.enrolled
    if row.capacity > 0:
        group['rated_enrolled'] += row.enrolled
        if row.enrolled >= row.capacity:
            group['full_classes'] += 1
    if row.enrolled == 0:
        group['empty_classes'] += 1


def _rate(group):
    """Ocupación en %, un decimal. Denominador 0 (ninguna clase con cupo declarado) → 0.0 y
    no `None`: acá el 0 no es "no calculable" para el front, es "no hubo cupo que llenar"."""
    if not group['capacity']:
        return 0.0
    return round(group['rated_enrolled'] / group['capacity'] * 100, 1)


def build_occupancy_report(scope, *, discipline=None):
    """Payload del reporte de ocupación del período de `scope`.

    TODO sale filtrado por `scope.organization_id`, que la view estampó desde el ACTOR (ver
    `views_reports._report_scope`): la organización no es un parámetro de este reporte y no
    hay forma de pedir la ocupación de otro gimnasio.

    Un solo recorrido en Python sobre las filas de las dos fuentes alimenta los tres cortes.
    Se agrega acá y no en la base porque los tres cortes salen del mismo universo y con las
    mismas reglas de borde (cupo 0, llenas, vacías): con tres `values().annotate()` esas
    reglas quedarían escritas tres veces en SQL y podrían divergir. Las queries son dos —una
    por fuente— y el volumen está acotado por `MAX_PERIOD_DAYS`.
    """
    rows = _live_rows(scope, discipline) + _pruned_rows(scope, discipline)

    totals = _empty_group()
    by_discipline = {}
    by_hour = {}
    # La serie nace COMPLETA y en cero: un día sin clases es un dato (el gimnasio no ofreció
    # nada), no una ausencia de dato. Ver `bucket_keys`.
    series = {key: _empty_group() for key in bucket_keys(scope)}
    pruned_classes = 0

    for row in rows:
        _accumulate(totals, row)
        if row.pruned:
            pruned_classes += 1

        # La clave del grupo es (id, nombre) y no solo el id: dos snapshots cuya disciplina se
        # borró llegan los dos con id NULL, y mezclarlos entre sí —y con las clases que nunca
        # tuvieron disciplina— borraría la única información que quedó de ellos, el nombre.
        # Con la tupla, una disciplina VIVA junta sus clases vivas y sus snapshots (el mismo
        # id y el mismo nombre actual), y las borradas quedan cada una con su etiqueta.
        group_key = (row.discipline_id, row.discipline_name)
        _accumulate(by_discipline.setdefault(group_key, _empty_group()), row)
        _accumulate(by_hour.setdefault(row.local_start.hour, _empty_group()), row)
        # Indexado directo y no `setdefault`: la clave SIEMPRE está en `series` porque el
        # filtro de la query (`start_datetime__date` entre las dos fechas del scope, resuelto
        # por Postgres en la zona del proyecto) y esta conversión (`timezone.localtime`, misma
        # zona) hablan del mismo día. Un KeyError acá sería un desalineamiento real de zona
        # horaria y tiene que verse, no rellenarse con un bucket fuera de rango.
        _accumulate(series[bucket_key(row.local_start.date(), scope.granularity)], row)

    return {
        'period': scope.period_payload(),
        'filters': scope.filters_payload(
            discipline_id=getattr(discipline, 'id', None),
            discipline_name=getattr(discipline, 'name', None),
        ),
        'totals': {
            'classes': totals['classes'],
            'capacity': totals['capacity'],
            'enrolled': totals['enrolled'],
            'occupancy_rate': _rate(totals),
            'full_classes': totals['full_classes'],
            'empty_classes': totals['empty_classes'],
            # Cuántas de esas `classes` ya no tienen fila viva detrás. Es la medida de cuánto
            # del reporte depende del rastro, o sea de cuánto se habría perdido sin él.
            'pruned_classes': pruned_classes,
        },
        # Orden por volumen y después por nombre: el administrador entra a este corte para ver
        # qué disciplina no llena, y la que tiene más clases es la que más pesa en el total.
        'by_discipline': [
            {
                'discipline_id': key[0],
                'discipline_name': key[1],
                'classes': group['classes'],
                'capacity': group['capacity'],
                'enrolled': group['enrolled'],
                'occupancy_rate': _rate(group),
                'full_classes': group['full_classes'],
                'empty_classes': group['empty_classes'],
            }
            for key, group in sorted(
                by_discipline.items(), key=lambda item: (-item[1]['classes'], item[0][1]),
            )
        ],
        # Solo las horas CON clases, ordenadas: rellenar las 24 con ceros no informaría nada
        # (ningún gimnasio abre a las 4 AM) y ensuciaría el gráfico de barras.
        'by_hour': [
            {
                'hour': hour,
                'label': f'{hour:02d}:00',
                'classes': group['classes'],
                'capacity': group['capacity'],
                'enrolled': group['enrolled'],
                'occupancy_rate': _rate(group),
            }
            for hour, group in sorted(by_hour.items())
        ],
        'series': [
            {
                'bucket': key,
                'classes': series[key]['classes'],
                'capacity': series[key]['capacity'],
                'enrolled': series[key]['enrolled'],
                'occupancy_rate': _rate(series[key]),
            }
            # Se recorre `bucket_keys` y no el dict: el orden del payload es el del período,
            # no el de inserción de las filas que llegaron.
            for key in bucket_keys(scope)
        ],
    }


def occupancy_export_spec(data):
    """Filas del CSV/XLSX: el corte por DISCIPLINA más una fila de totales.

    De los tres cortes es el que se lleva a una planilla: es el accionable ("qué disciplina no
    llena") y el único que trae llenas/vacías. La serie y las horas son gráficos —una columna
    de 731 filas no se lee en Excel mejor que en pantalla—. El export sale de `data`, o sea
    del MISMO payload que devolvió el JSON, así que la planilla no puede divergir de lo que el
    administrador está mirando (ver `_ReportView`).
    """
    totals = data['totals']
    header = ['Disciplina', 'Clases', 'Cupo', 'Inscritos', 'Ocupación %',
              'Clases llenas', 'Clases vacías']
    rows = [
        [
            item['discipline_name'],
            item['classes'],
            item['capacity'],
            item['enrolled'],
            item['occupancy_rate'],
            item['full_classes'],
            item['empty_classes'],
        ]
        for item in data['by_discipline']
    ]
    total_row = [
        'Total',
        totals['classes'],
        totals['capacity'],
        totals['enrolled'],
        totals['occupancy_rate'],
        totals['full_classes'],
        totals['empty_classes'],
    ]
    return {'header': header, 'rows': rows, 'total_row': total_row}
