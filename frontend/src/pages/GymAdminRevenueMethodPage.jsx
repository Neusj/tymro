import { useEffect, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { branchesApi, downloadReportFile, reportsApi } from '../api/client'
import DashboardHeader from '../components/DashboardHeader'
import StatCard from '../components/StatCard'
import ReportFilterBar from '../components/reports/ReportFilterBar'
import { clp, firstApiError } from '../utils/format'
import { buildReportParams, defaultReportPeriod } from '../utils/reportFilters'

// Mismo diccionario que METHOD_OPTIONS en GymAdminRevenueReportPage (capa 1) — acá solo
// hace falta la etiqueta, no la lista completa de opciones, porque esta pantalla no tiene
// selector de método (el método YA está fijado por la ruta). Sirve de respaldo mientras
// carga o si falla la llamada: el backend manda `filters.method_label` una vez que
// responde, pero el título no puede quedar en blanco antes de eso.
const METHOD_LABELS = {
  mercadopago: 'MercadoPago',
  cash: 'Efectivo',
  transfer: 'Transferencia',
  unknown: 'Sin método registrado',
}

// Los únicos métodos con devolución real son los de pasarela (MercadoPago). Un cobro en
// efectivo o transferencia no tiene flujo de reembolso en el sistema — por eso el backend
// siempre manda `refund_rows: []` para estos, y esta pantalla lo explicita en vez de
// esconder la sección (un [] vacío dice "no hubo"; una sección ausente diría "no sé").
const MANUAL_METHODS = new Set(['cash', 'transfer', 'unknown'])

function formatDateTime(value) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString('es-CL', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}

function formatDateShort(value) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleDateString('es-CL', { day: 'numeric', month: 'short' })
}

// Una fila de cobro o de devolución (misma forma en ambas listas: kind/id/occurred_at/
// amount/student_name/plan_name/branch_name). `extraNote`, si viene, se pinta debajo de
// la fecha — lo usa la lista de devoluciones para el rótulo "cobrado el 22/06 — fuera del
// período" cuando `collected_in_period` es false.
function PaymentRow({ row, href, extraNote }) {
  const label = `Ver detalle del pago de ${row.student_name || 'alumno'} por ${clp(row.amount)}`
  return (
    <Link
      to={href}
      aria-label={label}
      className="grid grid-cols-1 gap-1 rounded-lg border border-brand-line/50 px-3 py-2.5 text-sm transition hover:border-brand-orange hover:bg-black/20 sm:grid-cols-[140px_1fr_1fr_110px] sm:items-center sm:gap-3"
    >
      <span className="text-brand-muted">
        {formatDateTime(row.occurred_at)}
        {extraNote ? <span className="mt-0.5 block text-[11px] text-brand-orange">{extraNote}</span> : null}
      </span>
      <span className="text-brand-white">{row.student_name || '—'}</span>
      <span className="text-brand-muted">{row.plan_name || '—'} {row.branch_name ? `· ${row.branch_name}` : ''}</span>
      <span className="text-right font-medium text-brand-white">{clp(row.amount)}</span>
    </Link>
  )
}

export default function GymAdminRevenueMethodPage() {
  const { method } = useParams()
  const [searchParams, setSearchParams] = useSearchParams()
  const defaults = defaultReportPeriod()
  const dateFrom = searchParams.get('date_from') || defaults.dateFrom
  const dateTo = searchParams.get('date_to') || defaults.dateTo
  const branchId = searchParams.get('branch_id') || ''

  const [branches, setBranches] = useState([])
  const [report, setReport] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [exporting, setExporting] = useState('')

  const setFilter = (key, value) => {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        if (value) next.set(key, value)
        else next.delete(key)
        return next
      },
      { replace: true },
    )
  }

  const buildParams = () => buildReportParams({ dateFrom, dateTo, branchId, extra: { method } })

  useEffect(() => {
    let active = true
    branchesApi
      .list()
      .then((data) => {
        if (active) setBranches(Array.isArray(data) ? data : [])
      })
      .catch(() => {
        if (active) setBranches([])
      })
    return () => {
      active = false
    }
  }, [])

  useEffect(() => {
    let active = true
    const load = async () => {
      setLoading(true)
      setError('')
      try {
        const data = await reportsApi.revenuePayments(buildParams())
        if (active) setReport(data)
      } catch (apiError) {
        if (active) {
          setError(firstApiError(apiError?.response?.data, 'No se pudo cargar el detalle de este método de pago.'))
          setReport(null)
        }
      } finally {
        if (active) setLoading(false)
      }
    }
    load()
    return () => {
      active = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dateFrom, dateTo, branchId, method])

  const handleExport = async (format) => {
    setExporting(format)
    setError('')
    try {
      const response = await reportsApi.exportRevenuePayments(buildParams(), format)
      downloadReportFile(response, `ingresos_${method}_${dateFrom}_${dateTo}.${format === 'xlsx' ? 'xlsx' : 'csv'}`)
    } catch {
      setError('No se pudo exportar el reporte.')
    } finally {
      setExporting('')
    }
  }

  const totals = report?.totals || { gross: 0, refunds: 0, net: 0, payments_count: 0, refunds_count: 0 }
  const filters = report?.filters || {}
  const rows = Array.isArray(report?.rows) ? report.rows : []
  const refundRows = Array.isArray(report?.refund_rows) ? report.refund_rows : []
  const truncated = Boolean(report?.truncated)
  const refundsTruncated = Boolean(report?.refunds_truncated)
  const methodLabel = filters.method_label || METHOD_LABELS[method] || method
  const isManualMethod = MANUAL_METHODS.has(method)

  // El período/sucursal viajan de vuelta a la capa 1 (y a la capa 3, en cada fila) — el
  // método NO va en la query porque en esta pantalla ya no es un filtro, es el path.
  const carryQuery = new URLSearchParams()
  if (dateFrom) carryQuery.set('date_from', dateFrom)
  if (dateTo) carryQuery.set('date_to', dateTo)
  if (branchId) carryQuery.set('branch_id', branchId)
  const carryQueryString = carryQuery.toString()
  const backHref = `/gym-admin/reports/revenue${carryQueryString ? `?${carryQueryString}` : ''}`
  const detailHref = (row) => `/gym-admin/reports/revenue/${row.kind}/${row.id}${carryQueryString ? `?${carryQueryString}` : ''}`

  return (
    <div className="space-y-5">
      <DashboardHeader
        title={`Ingresos — ${methodLabel}`}
        subtitle="Cobros y devoluciones de este método, uno por uno. Tocá una fila para ver el detalle completo del pago."
        back={{ to: backHref, label: 'Ingresos' }}
      />

      {error ? (
        <p className="rounded-lg border border-danger-line bg-danger-soft px-3 py-2 text-sm text-red-200">{error}</p>
      ) : null}

      <ReportFilterBar
        dateFrom={dateFrom}
        dateTo={dateTo}
        onDateFromChange={(value) => setFilter('date_from', value)}
        onDateToChange={(value) => setFilter('date_to', value)}
        branches={branches}
        branchId={branchId}
        onBranchChange={(value) => setFilter('branch_id', value)}
        onExport={handleExport}
        exporting={exporting}
        exportDisabled={loading || Boolean(exporting)}
      />

      <p className="text-xs text-brand-muted">
        {report?.period?.date_from || dateFrom} al {report?.period?.date_to || dateTo} ·{' '}
        {filters.branch_name || 'Todas las sucursales'} · {methodLabel}
      </p>

      {/* Misma ecuación que la capa 1 (Bruto − Devoluciones = Neto), pero acotada a este
          único método — así el admin puede verificar que el desglose de la capa 1 suma
          correcto sin tener que hacer la resta a mano. */}
      <section className="card-surface space-y-4 p-4 sm:p-5">
        <div>
          <p className="text-[11px] uppercase tracking-wide text-brand-dim">Bruto − Devoluciones = Neto</p>
          <p className="mt-1 flex flex-wrap items-baseline gap-2 font-display text-2xl font-bold sm:text-3xl">
            <span className="text-brand-blue">{clp(totals.gross)}</span>
            <span className="text-brand-dim">−</span>
            <span className="text-brand-red">{clp(totals.refunds)}</span>
            <span className="text-brand-dim">=</span>
            <span className="text-success">{clp(totals.net)}</span>
          </p>
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <StatCard title="Bruto" value={clp(totals.gross)} accent="blue" hint={`${totals.payments_count} cobros`} />
          <StatCard title="Devoluciones" value={clp(totals.refunds)} accent="red" hint={`${totals.refunds_count} devoluciones`} />
          <StatCard title="Neto" value={clp(totals.net)} accent="success" />
        </div>
      </section>

      <section className="card-surface space-y-3 p-4 sm:p-5">
        <h2 className="text-sm font-semibold text-brand-white">Cobros</h2>
        {truncated ? (
          <p className="rounded-lg border border-warning-line bg-warning-soft px-3 py-2 text-sm text-amber-200">
            Esta lista muestra solo los primeros {report?.row_limit ?? rows.length} cobros. Los totales de arriba SÍ
            son del período completo: la única cosa recortada es esta lista.
          </p>
        ) : null}
        {loading ? (
          <p className="py-6 text-center text-sm text-brand-muted">Cargando…</p>
        ) : rows.length === 0 ? (
          <p className="py-6 text-center text-sm text-brand-muted">Sin cobros de este método en el período.</p>
        ) : (
          <div className="space-y-2">
            {rows.map((row) => (
              <PaymentRow key={`${row.kind}-${row.id}`} row={row} href={detailHref(row)} />
            ))}
          </div>
        )}
      </section>

      <section className="card-surface space-y-3 p-4 sm:p-5">
        <h2 className="text-sm font-semibold text-brand-white">Devoluciones</h2>
        {isManualMethod ? (
          <p className="rounded-lg border border-brand-line bg-black/20 px-3 py-2 text-sm text-brand-muted">
            Los cobros en efectivo, transferencia o sin método registrado no tienen devolución en el sistema: ese
            flujo solo existe para pagos por MercadoPago. Por eso esta lista está vacía a propósito.
          </p>
        ) : (
          <>
            {refundsTruncated ? (
              <p className="rounded-lg border border-warning-line bg-warning-soft px-3 py-2 text-sm text-amber-200">
                Esta lista muestra solo las primeras {report?.row_limit ?? refundRows.length} devoluciones. Los
                totales de arriba SÍ son del período completo.
              </p>
            ) : null}
            {loading ? (
              <p className="py-6 text-center text-sm text-brand-muted">Cargando…</p>
            ) : refundRows.length === 0 ? (
              <p className="py-6 text-center text-sm text-brand-muted">Sin devoluciones de este método en el período.</p>
            ) : (
              <div className="space-y-2">
                {refundRows.map((row) => (
                  <PaymentRow
                    key={`${row.kind}-${row.id}`}
                    row={row}
                    href={detailHref(row)}
                    extraNote={
                      row.collected_in_period === false
                        ? `cobrado el ${formatDateShort(row.collected_at)} — fuera del período`
                        : null
                    }
                  />
                ))}
              </div>
            )}
          </>
        )}
      </section>
    </div>
  )
}
