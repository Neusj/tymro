"""Cimiento común de la reportería (P3.4 · Pieza 0).

Acá vive lo que los tres reportes —ingresos, pagos manuales, ocupación— comparten: el
alcance ya validado (`ReportScope`), la aritmética de períodos y buckets, y los escritores
de export CSV/XLSX. NO hay ninguna consulta de negocio en este módulo: cada reporte arma la
suya en su propio `reports_*.py`.

DOS INVARIANTES QUE ESTE MÓDULO SOSTIENE Y NINGÚN REPORTE DEBE SALTARSE:

1. **`ReportScope.organization_id` es la organización DEL ACTOR, no un parámetro.** La
   construye `views_reports._report_scope` después de las guardas de rol, y todo reporte
   filtra por ella. No hay forma de pedir el reporte de otro gimnasio porque la organización
   nunca viaja en el request (regla 1 de backend/CLAUDE.md y orden 8.3).

2. **`ReportScope.branch`, si viene, es una sucursal YA VERIFICADA como de esa
   organización.** El filtro de sede se aplica sobre un objeto validado, nunca sobre el id
   crudo del query string, así que no puede seleccionar datos de otro tenant.

Sobre las FECHAS: los rangos son fechas LOCALES (`America/Santiago`) y se comparan contra
columnas `DateTimeField` con lookups `__date__gte/__date__lte`. Con `USE_TZ=True` Postgres
hace la conversión a la zona del proyecto, así que "el 3 de julio" significa el día que
vivió el gimnasio, no una ventana UTC corrida en 4 horas.
"""
import csv
from dataclasses import dataclass
from datetime import date, timedelta

from django.http import HttpResponse

# Tope de ventana. No es una limitación técnica sino un freno: un reporte de 10 años recorre
# todo el histórico de pagos del tenant en una request sincrónica de gunicorn (workers sync,
# `--timeout 30`). Dos años cubre "comparar con el año pasado" y deja el peor caso acotado.
MAX_PERIOD_DAYS = 731

# Por encima de este largo el reporte agrupa por MES en vez de por día: una serie de 365
# puntos no se lee en un gráfico y multiplica por 12 el payload. 92 días ≈ un trimestre, que
# sigue siendo legible día por día.
AUTO_MONTH_THRESHOLD_DAYS = 92

GRANULARITY_DAY = 'day'
GRANULARITY_MONTH = 'month'
GRANULARITIES = (GRANULARITY_DAY, GRANULARITY_MONTH)

# --------------------------------------------------------------------------------------
# Medios de cobro. FUENTE ÚNICA para los dos reportes de plata y para la validación del
# parámetro `method` en la view: si cada uno tuviera su propia lista, agregar un medio en un
# lado y no en el otro haría que el filtro aceptara un valor que el cálculo ignora.
# --------------------------------------------------------------------------------------
METHOD_MERCADOPAGO = 'mercadopago'          # cobro en línea (una sola etiqueta, aunque el
                                            # proveedor concreto sea configurable)
METHOD_CASH = 'cash'                        # espeja ManualPayment.METHOD_CASH
METHOD_TRANSFER = 'transfer'                # espeja ManualPayment.METHOD_TRANSFER

# ⚠️ EL CUARTO MEDIO NO ES OPCIONAL, ES PLATA REAL QUE YA ESTÁ EN PRODUCCIÓN.
# `ManualPayment.method` nació en P3.2 con `blank=True, default=''` y su migración NO hizo
# backfill a propósito: las filas cobradas en 8.2/8.3 quedaron en `''` porque literalmente no
# se sabe si fueron efectivo o transferencia. Son cobros REALES que el gimnasio recibió.
# Si el reporte filtrara solo por `cash`/`transfer`, esa plata desaparecería del ingreso
# bruto y el neto quedaría por debajo de lo que el gimnasio facturó — el modo de fallo exacto
# que esta reportería existe para evitar. Así que hay un medio explícito para el vacío.
# `'unknown'` es el valor de CABLE; en la base la fila tiene `method=''`.
METHOD_UNKNOWN = 'unknown'
UNKNOWN_DB_METHOD = ''

METHOD_LABELS = {
    METHOD_MERCADOPAGO: 'MercadoPago',
    METHOD_CASH: 'Efectivo',
    METHOD_TRANSFER: 'Transferencia',
    METHOD_UNKNOWN: 'Sin método registrado',
}

#: medios que puede tener un ingreso (reporte de ingresos)
REVENUE_METHODS = (METHOD_MERCADOPAGO, METHOD_CASH, METHOD_TRANSFER, METHOD_UNKNOWN)
#: medios de un cobro registrado a mano (reporte de pagos manuales)
MANUAL_METHODS = (METHOD_CASH, METHOD_TRANSFER, METHOD_UNKNOWN)


def manual_method_filter(method):
    """Valor de `ManualPayment.method` que corresponde a un medio del cable.

    Existe para que ningún reporte escriba `filter(method='')` a mano: la traducción
    `'unknown'` → `''` es la única parte no obvia del mapeo y tiene que estar en un solo
    lugar.
    """
    return UNKNOWN_DB_METHOD if method == METHOD_UNKNOWN else method


def manual_method_wire(db_value):
    """Inversa de `manual_method_filter`: valor de la columna → medio del cable.

    El vacío NO se publica como `''`. Una celda vacía en un reporte de plata es
    indistinguible de un dato que se perdió en el camino, y esto es lo contrario: se sabe
    exactamente que el cobro entró y que el instrumento no quedó anotado.
    """
    return METHOD_UNKNOWN if db_value == UNKNOWN_DB_METHOD else db_value


@dataclass(frozen=True)
class ReportScope:
    """Alcance ya validado de un reporte. Inmutable a propósito: se construye una vez en la
    view, después de las guardas, y ninguna capa de abajo puede ensancharlo."""

    organization_id: int
    date_from: date
    date_to: date
    granularity: str
    branch: object = None          # `core.models.Branch` o None = todas las sedes de la org

    @property
    def branch_id(self):
        return getattr(self.branch, 'id', None)

    @property
    def branch_name(self):
        return getattr(self.branch, 'name', None)

    @property
    def days(self):
        return (self.date_to - self.date_from).days + 1

    def previous(self):
        """Período INMEDIATAMENTE anterior, del mismo largo en días.

        Mismo largo y no "el mes anterior": la comparación tiene que ser contra una ventana
        del mismo tamaño o el delta mide la diferencia de días, no de negocio. Un rango de 10
        días compara contra los 10 días previos; uno de un mes de 31 días contra los 31 días
        previos (que puede cruzar el límite de mes, y está bien: es lo que hace que el
        porcentaje signifique algo).
        """
        length = self.days
        previous_to = self.date_from - timedelta(days=1)
        return ReportScope(
            organization_id=self.organization_id,
            date_from=previous_to - timedelta(days=length - 1),
            date_to=previous_to,
            granularity=self.granularity,
            branch=self.branch,
        )

    def period_payload(self):
        return {
            'date_from': self.date_from.isoformat(),
            'date_to': self.date_to.isoformat(),
            'days': self.days,
            'granularity': self.granularity,
        }

    def filters_payload(self, **extra):
        payload = {'branch_id': self.branch_id, 'branch_name': self.branch_name}
        payload.update(extra)
        return payload


def resolve_granularity(requested, date_from, date_to):
    """`day`/`month` explícito, o `auto` → por el largo del rango."""
    if requested in GRANULARITIES:
        return requested
    span = (date_to - date_from).days + 1
    return GRANULARITY_DAY if span <= AUTO_MONTH_THRESHOLD_DAYS else GRANULARITY_MONTH


def bucket_key(value, granularity):
    """Clave del bucket al que cae una fecha local: `2026-07-03` o `2026-07`."""
    if granularity == GRANULARITY_MONTH:
        return f'{value.year:04d}-{value.month:02d}'
    return value.isoformat()


def bucket_keys(scope):
    """TODAS las claves del rango, en orden y SIN huecos.

    Existe para que las series de los gráficos se rellenen con ceros en vez de saltear los
    días sin movimiento: una línea que une el 3 con el 9 dibuja una pendiente que nadie
    facturó, y un día de ingreso cero es un dato, no una ausencia de dato.
    """
    keys = []
    if scope.granularity == GRANULARITY_MONTH:
        year, month = scope.date_from.year, scope.date_from.month
        while (year, month) <= (scope.date_to.year, scope.date_to.month):
            keys.append(f'{year:04d}-{month:02d}')
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)
        return keys
    current = scope.date_from
    while current <= scope.date_to:
        keys.append(current.isoformat())
        current += timedelta(days=1)
    return keys


def pct_delta(current, previous):
    """Variación porcentual contra el período anterior, o ``None`` si no es calculable.

    `None` y NO 0 ni 100 cuando el período anterior fue cero: "creció infinito" no es un
    número que se pueda mostrar, y devolver 100 % haría que la UI dibuje un crecimiento
    inventado sobre una base inexistente. El front muestra un guion.
    """
    if not previous:
        return None
    return round((current - previous) / previous * 100, 1)


def rate_pct(numerator, denominator):
    """Tasa en % con un decimal, o ``None`` si el denominador es 0.

    FUENTE ÚNICA de las tasas de los reportes de RETENCIÓN y CONVERSIÓN (P3.4 parte 2), que
    la necesitan idéntica: cada uno con su copia es como divergen dos mitades de la misma
    feature sin que nada lo detecte.

    ``None`` y NO ``0.0`` cuando no hay denominador. "0 % de renovación" sobre cero
    vencimientos —o "0 % de conversión" sobre cero pruebas— es una afirmación FALSA: el
    gimnasio no falló, no hubo universo. Mismo criterio que `pct_delta`, y deliberadamente
    DISTINTO del `_rate` de `reports_occupancy`: allá el 0 sí significa algo ("no hubo cupo
    que llenar", una oferta real sin plazas declaradas).
    """
    if not denominator:
        return None
    return round(numerator / denominator * 100, 1)


def points_delta(current, previous):
    """Diferencia en PUNTOS PORCENTUALES entre dos tasas, o ``None`` si falta alguna.

    Para comparar TASAS entre períodos no se usa `pct_delta`: la variación porcentual de un
    porcentaje ("la conversión creció 12 %" cuando pasó de 50 % a 56 %) es un número que
    nadie lee bien y que se confunde con la tasa misma. Para los CONTEOS sí se usa
    `pct_delta`, donde el % significa lo que parece.
    """
    if current is None or previous is None:
        return None
    return round(current - previous, 1)


# --------------------------------------------------------------------------------------
# Export. Mismo patrón que `TeacherPaymentRecordViewSet.summary_export` (views.py): el
# formato viaja en `fmt` y NUNCA en `format`, que DRF reserva para negociación de contenido.
# --------------------------------------------------------------------------------------

def csv_response(*, filename, header, rows, total_row=None):
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{filename}.csv"'
    response.write('﻿')   # BOM para que Excel respete acentos
    writer = csv.writer(response)
    writer.writerow(header)
    for row in rows:
        writer.writerow(row)
    if total_row is not None:
        writer.writerow(total_row)
    return response


def xlsx_response(*, filename, sheet_title, header, rows, total_row=None):
    # Import perezoso, igual que en `_export_summary_xlsx`: openpyxl solo se necesita en este
    # camino y cargarlo al importar el módulo lo pone en el arranque de todos los workers.
    from openpyxl import Workbook
    from openpyxl.styles import Font

    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = sheet_title[:31]   # límite de Excel para el nombre de la hoja
    worksheet.append(list(header))
    for cell in worksheet[1]:
        cell.font = Font(bold=True)
    for row in rows:
        worksheet.append(list(row))
    if total_row is not None:
        worksheet.append(list(total_row))
        for cell in worksheet[worksheet.max_row]:
            cell.font = Font(bold=True)

    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f'attachment; filename="{filename}.xlsx"'
    workbook.save(response)
    return response


def export_response(*, fmt, filename, sheet_title, header, rows, total_row=None):
    if (fmt or 'csv').lower() == 'xlsx':
        return xlsx_response(filename=filename, sheet_title=sheet_title, header=header,
                             rows=rows, total_row=total_row)
    return csv_response(filename=filename, header=header, rows=rows, total_row=total_row)
