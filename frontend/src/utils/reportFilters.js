// Helpers compartidos por las 3 pantallas de reportería (P3.4: ingresos, pagos manuales,
// ocupación). Los tres endpoints comparten el MISMO contrato de query params (date_from,
// date_to, branch_id, granularity, export) + un filtro propio (method | discipline_id),
// así que el default de período y el armado de params se centralizan acá en vez de
// triplicarse en cada página — mismo espíritu que utils/format.js.
import { todayLocalISO } from './format'

// "Mes en curso hasta hoy": mismo default que ya aplica el backend si no se manda nada,
// pero los inputs de fecha son controlados y necesitan un valor inicial para mostrarse
// prellenados (y para que el export tenga un rango explícito incluso antes de tocar nada).
export const defaultReportPeriod = () => {
  const today = todayLocalISO()
  const dateFrom = `${today.slice(0, 7)}-01`
  return { dateFrom, dateTo: today }
}

// Arma los query params comunes + los propios de cada reporte. `extra` es un objeto tipo
// { method: 'cash' } u { discipline_id: 3 } — se mergea tal cual, omitiendo valores vacíos.
export const buildReportParams = ({ dateFrom, dateTo, branchId, extra = {} } = {}) => {
  const params = {}
  if (dateFrom) params.date_from = dateFrom
  if (dateTo) params.date_to = dateTo
  if (branchId) params.branch_id = branchId
  Object.entries(extra).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      params[key] = value
    }
  })
  return params
}

// Etiqueta legible para un bucket de serie temporal ("YYYY-MM-DD" o "YYYY-MM"), sin el bug
// de interpretar un DateField como UTC (mismo problema que formatDate en utils/format.js).
export const formatBucketLabel = (bucket) => {
  if (!bucket) return '-'
  if (/^\d{4}-\d{2}$/.test(bucket)) {
    const [year, month] = bucket.split('-').map(Number)
    const date = new Date(year, month - 1, 1)
    return date.toLocaleDateString('es-CL', { month: 'short', year: '2-digit' })
  }
  if (/^\d{4}-\d{2}-\d{2}$/.test(bucket)) {
    const date = new Date(`${bucket}T00:00:00`)
    return date.toLocaleDateString('es-CL', { day: '2-digit', month: 'short' })
  }
  return bucket
}
