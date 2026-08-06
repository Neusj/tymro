"""APIViews de reportería (P3.4). Split de views.py por tamaño, igual que `views_payments.py`.

TRES REPORTES, UN SOLO CAMINO DE ENTRADA. Todos entran por `_report_scope`, que es el único
lugar donde se resuelve QUIÉN pregunta y SOBRE QUÉ, en este orden (orden 8.3):

1. `ReportPermission` — solo `gym_admin` con organización. Cualquier otro rol: 403.
2. `_report_scope` — estampa `organization_id` DEL ACTOR (jamás del request), valida el rango
   de fechas y resuelve la sucursal contra las sucursales de ESA organización.
3. Recién ahí corre la consulta del reporte, ya acotada.

NINGÚN REPORTE PUEDE CRUZAR ORGANIZACIÓN porque la organización no es un parámetro: no hay
`organization_id` en el query string de ninguno de estos endpoints. Una sede ajena da 404
(anti-oráculo, mismo criterio que `views_payments._branch_scope`) y por lo tanto tampoco es
un camino para leer datos de otro tenant.

TODA la plata sale de NUESTRA base. Ningún reporte consulta al proveedor de pago en vivo: lo
que el reporte suma es lo que el webhook escribió (ver `services/payments.py`).
"""
from datetime import date, datetime

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .models import Branch, Discipline
from .permissions import ReportPermission
from .services import reports_base
from .services.reports_base import (MANUAL_METHODS, MAX_PERIOD_DAYS, REVENUE_METHODS,
                                    ReportScope, export_response)
from .services.reports_manual import (build_manual_payments_report,
                                      manual_payments_export_spec)
from .services.reports_occupancy import build_occupancy_report, occupancy_export_spec
from .services.reports_revenue import build_revenue_report, revenue_export_spec

# Misma validación de FORMA que `views_payments._branch_scope` y por los mismos motivos
# (`int()` acepta floats y bools en silencio; fuera del rango de bigint el `filter(id=...)`
# revienta con 500 en PostgreSQL y SQLite no lo reproduce).
_id_field = serializers.IntegerField(min_value=1, max_value=2 ** 63 - 1)

#: Fecha más antigua que un reporte acepta. Ver el porqué en `_report_scope`.
MIN_REPORT_DATE = date(2000, 1, 1)

# Los medios de cobro (`REVENUE_METHODS`, `MANUAL_METHODS`, etiquetas) viven en
# `services/reports_base.py` y se importan de ahí: son la MISMA lista que usa el cálculo. Con
# una copia local, agregar un medio en un lado y no en el otro dejaría el filtro aceptando un
# valor que el reporte ignora en silencio (o rechazando uno que sí sabe calcular).


def _parse_date(value, field):
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        raise DRFValidationError({field: 'Formato de fecha inválido (usa YYYY-MM-DD).'})


def _scoped_id(user, raw_value, model, field):
    """Objeto de `model` con ese id Y de la organización del ACTOR, o None si no vino.

    404 y no 403 cuando el id existe pero es de otro gimnasio: los ids son autoincrementales
    y adivinables, y un 403 confirmaría "existe, pero no es tuyo" — delataría la topología de
    sedes o el catálogo de disciplinas de otro tenant (mismo criterio y misma lección que
    `views_payments._branch_scope`).
    """
    if raw_value is None or raw_value == '':
        return None
    try:
        object_id = _id_field.run_validation(raw_value)
    except serializers.ValidationError as exc:
        # 400 y no 404: el valor es malformado, no ajeno, y este camino no revela nada.
        raise DRFValidationError({field: exc.detail})
    return get_object_or_404(model, id=object_id, organization_id=user.organization_id)


def _report_scope(request):
    """`ReportScope` validado. ÚNICO origen de la organización y del rango de todo reporte.

    Defaults: si no se pide rango, el MES EN CURSO hasta hoy. Es el reporte que un
    administrador quiere ver al entrar, y evita que la falta de parámetros produzca un
    barrido del histórico completo.
    """
    user = request.user
    params = request.query_params

    raw_from = params.get('date_from')
    raw_to = params.get('date_to')
    # `localdate()` y no `date.today()`: "hoy" es el día del gimnasio (`America/Santiago`),
    # que a la noche NO es el día UTC del servidor. Con `date.today()` el default del reporte
    # se adelantaría un día durante las últimas horas de cada jornada.
    today = timezone.localdate()
    date_to = _parse_date(raw_to, 'date_to') if raw_to else today
    date_from = _parse_date(raw_from, 'date_from') if raw_from else date_to.replace(day=1)

    if date_from > date_to:
        raise DRFValidationError({'date_from': 'La fecha inicial no puede ser posterior a la final.'})
    # PISO de fecha. No es cosmético: `ReportScope.previous()` hace `date_from - 1 día` para
    # armar el período de comparación, y con `date_from=0001-01-01` esa resta levanta
    # `OverflowError` —que DRF no traduce— o sea un 500 en un endpoint de dinero. El año 2000
    # es un piso holgado: este SaaS no tiene histórico anterior y un reporte de esas fechas no
    # es un pedido legítimo. Va acá y no en `previous()` para que el error diga QUÉ está mal.
    if date_from < MIN_REPORT_DATE:
        raise DRFValidationError(
            {'date_from': f'La fecha inicial no puede ser anterior a '
                          f'{MIN_REPORT_DATE.isoformat()}.'})
    if (date_to - date_from).days + 1 > MAX_PERIOD_DAYS:
        raise DRFValidationError(
            {'date_to': f'El rango no puede superar {MAX_PERIOD_DAYS} días.'})

    # `granularity` inválida da 400 y NO cae a `auto` en silencio: un cliente que pide
    # semanas y recibe meses sin enterarse dibuja un gráfico con la escala equivocada y
    # nadie lo nota. Ausente o 'auto' sí resuelve por el largo del rango.
    raw_granularity = (params.get('granularity') or 'auto').lower()
    if raw_granularity not in reports_base.GRANULARITIES + ('auto',):
        raise DRFValidationError(
            {'granularity': 'Valor inválido. Opciones: day, month, auto.'})
    granularity = reports_base.resolve_granularity(raw_granularity, date_from, date_to)
    branch = _scoped_id(user, params.get('branch_id'), Branch, 'branch_id')

    return ReportScope(
        organization_id=user.organization_id,
        date_from=date_from,
        date_to=date_to,
        granularity=granularity,
        branch=branch,
    )


def _method_param(request, allowed):
    method = request.query_params.get('method')
    if method is None or method == '':
        return None
    if method not in allowed:
        raise DRFValidationError(
            {'method': f'Método inválido. Opciones: {", ".join(allowed)}.'})
    return method


class _ReportView(APIView):
    """Plomería compartida: permiso, alcance, y el `?export=csv|xlsx` de cualquier reporte.

    El export NO es un endpoint aparte: usa EXACTAMENTE el mismo `_report_scope` y los mismos
    datos que el JSON. Si fueran dos caminos, el CSV podría divergir del gráfico que el
    administrador está mirando —y un CSV de plata que no cuadra con la pantalla es peor que
    no tener CSV—. `?export=` ausente devuelve JSON.
    """
    permission_classes = [ReportPermission]
    # FRENO DE VOLUMEN, no cupo de negocio (mismo criterio y mismo comentario que
    # `AdvanceClassWindowsView`). Un reporte es una lectura agregada sobre varias tablas dentro
    # de una request SÍNCRONA de gunicorn (workers sync, `--timeout 30`) y con el tope de rango
    # en 731 días el peor caso recorre dos años de pagos o de clases de un tenant. Sin scope
    # propio, el único límite era el `user: 1000/day` global, o sea suficiente para que un solo
    # gimnasio martillando F5 degrade la latencia de todos los demás en un single-service.
    # Con LocMemCache el conteo es POR WORKER (~×3 en prod): freno, no garantía.
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'reports'

    #: nombre base del archivo exportado y de la hoja del xlsx
    export_filename = 'reporte'
    export_sheet_title = 'Reporte'

    def build(self, request, scope):          # pragma: no cover - contrato
        raise NotImplementedError

    def export_spec(self, data):             # pragma: no cover - contrato
        raise NotImplementedError

    def get(self, request):
        scope = _report_scope(request)
        data = self.build(request, scope)
        # OJO: el parámetro es `export`, no `format`: DRF reserva `format` para negociación de
        # contenido (misma trampa documentada en `summary_export`). Su valor elige csv/xlsx.
        export_fmt = request.query_params.get('export')
        if export_fmt:
            # Un valor desconocido da 400 en vez de caer a CSV: pedir `pdf` y recibir un csv
            # llamado `.csv` con 200 es un fallo silencioso, y acá el archivo que baja es
            # plata que alguien va a pegar en una planilla.
            if export_fmt.lower() not in ('csv', 'xlsx'):
                raise DRFValidationError({'export': 'Formato inválido. Opciones: csv, xlsx.'})
            spec = self.export_spec(data)
            filename = (f'{self.export_filename}_{scope.date_from.isoformat()}'
                        f'_{scope.date_to.isoformat()}')
            return export_response(
                fmt=export_fmt,
                filename=filename,
                sheet_title=self.export_sheet_title,
                header=spec['header'],
                rows=spec['rows'],
                total_row=spec.get('total_row'),
            )
        return Response(data)


class RevenueReportView(_ReportView):
    """`GET /api/reports/revenue/` — ingresos del período: bruto, devoluciones y neto.

    Los tres números viajan SIEMPRE por separado y en todos los niveles del payload (total,
    por método, y cada punto de la serie). No existe ningún campo que sea "el ingreso" a
    secas: esconder la resta es justamente lo que hacía que el número mintiera cuando había
    una devolución.
    """
    export_filename = 'ingresos'
    export_sheet_title = 'Ingresos'

    def build(self, request, scope):
        return build_revenue_report(
            scope, method=_method_param(request, REVENUE_METHODS))

    def export_spec(self, data):
        return revenue_export_spec(data)


class ManualPaymentsReportView(_ReportView):
    """`GET /api/reports/manual-payments/` — cobros en efectivo y por transferencia.

    Primera lectura que existe de `ManualPayment`: hasta P3.4 el modelo era solo-POST, o sea
    el gimnasio registraba cobros en recepción y no tenía dónde verlos. Publica quién los
    registró y cuándo, que es el punto de control interno del reporte.
    """
    export_filename = 'pagos_manuales'
    export_sheet_title = 'Pagos manuales'

    def build(self, request, scope):
        return build_manual_payments_report(
            scope, method=_method_param(request, MANUAL_METHODS))

    def export_spec(self, data):
        return manual_payments_export_spec(data)


class OccupancyReportView(_ReportView):
    """`GET /api/reports/occupancy/` — cuánto se llenaron las clases del período.

    Suma las clases VIVAS más el rastro de las que la poda de la ventana rodante ya borró
    (`ClassOccupancySnapshot`): sin ese rastro el porcentaje sería optimista y mejoraría solo
    por el paso del tiempo, porque lo que la poda se lleva son exactamente las clases que
    nadie tomó.
    """
    export_filename = 'ocupacion'
    export_sheet_title = 'Ocupación'

    def build(self, request, scope):
        discipline = _scoped_id(request.user, request.query_params.get('discipline_id'),
                                Discipline, 'discipline_id')
        return build_occupancy_report(scope, discipline=discipline)

    def export_spec(self, data):
        return occupancy_export_spec(data)
