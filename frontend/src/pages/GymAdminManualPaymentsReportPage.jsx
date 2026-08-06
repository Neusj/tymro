import { useEffect, useState } from 'react'
import { branchesApi, downloadReportFile, reportsApi } from '../api/client'
import DashboardHeader from '../components/DashboardHeader'
import StatCard from '../components/StatCard'
import ReportFilterBar from '../components/reports/ReportFilterBar'
import TimeSeriesChart from '../components/charts/TimeSeriesChart'
import HorizontalBarChart from '../components/charts/HorizontalBarChart'
import { clp, firstApiError } from '../utils/format'
import { buildReportParams, defaultReportPeriod, formatBucketLabel } from '../utils/reportFilters'

// 'unknown' = cobros manuales registrados ANTES de P3.2: esa migración no hizo backfill de
// `method`, así que quedaron con method='' en producción. Es plata real que el gimnasio
// recibió; el backend los agrupa acá para no perderlos del total. NO es un error.
const METHOD_OPTIONS = [
  { value: 'cash', label: 'Efectivo' },
  { value: 'transfer', label: 'Transferencia' },
  { value: 'unknown', label: 'Sin método registrado' },
]

// Mismo par cash=naranja / transfer=azul en la tarjeta, el gráfico de evolución y el
// desglose: la identidad de cada método se mantiene consistente en toda la pantalla.
// 'unknown' es gris neutro a propósito (tono `neutral` de chartTones): no es una alarma.
const METHOD_BADGE = {
  cash: 'border-brand-orange/40 bg-brand-orange/10 text-brand-orange',
  transfer: 'border-brand-blue/40 bg-brand-blue/10 text-brand-blue',
  unknown: 'border-brand-line bg-black/30 text-brand-muted',
}

function formatDateTime(value) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString('es-CL', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}

function MethodBadge({ method, label }) {
  const style = METHOD_BADGE[method] || 'border-brand-line bg-black/30 text-brand-muted'
  return (
    <span className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-[11px] font-semibold ${style}`}>
      {label || method}
    </span>
  )
}

export default function GymAdminManualPaymentsReportPage() {
  const [dateFrom, setDateFrom] = useState(() => defaultReportPeriod().dateFrom)
  const [dateTo, setDateTo] = useState(() => defaultReportPeriod().dateTo)
  const [branchId, setBranchId] = useState('')
  const [method, setMethod] = useState('')
  const [branches, setBranches] = useState([])

  const [report, setReport] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [exporting, setExporting] = useState('')

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
        const data = await reportsApi.manualPayments(buildParams())
        if (active) setReport(data)
      } catch (apiError) {
        if (active) {
          setError(firstApiError(apiError?.response?.data, 'No se pudo cargar el reporte de pagos manuales.'))
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
      const response = await reportsApi.exportManualPayments(buildParams(), format)
      downloadReportFile(response, `pagos_manuales_${dateFrom}_${dateTo}.${format === 'xlsx' ? 'xlsx' : 'csv'}`)
    } catch {
      setError('No se pudo exportar el reporte.')
    } finally {
      setExporting('')
    }
  }

  const totals = report?.totals || {
    cash: 0,
    transfer: 0,
    unknown: 0,
    total: 0,
    count: 0,
    cash_count: 0,
    transfer_count: 0,
    unknown_count: 0,
  }
  const rows = Array.isArray(report?.rows) ? report.rows : []
  const series = Array.isArray(report?.series) ? report.series : []
  const filters = report?.filters || {}
  const truncated = Boolean(report?.truncated)
  // Gimnasio nuevo (o sin cobros pre-P3.2 sin backfill): unknown siempre es 0. Mostrar ese
  // subtotal siempre sería ruido permanente — aparece SOLO si hay algo real que mostrar.
  const hasUnknown = (Number(totals.unknown) || 0) > 0 || (Number(totals.unknown_count) || 0) > 0

  const barItems = [
    { key: 'cash', label: 'Efectivo', value: Number(totals.cash) || 0, hint: `${totals.cash_count} cobros`, tone: 'orange' },
    { key: 'transfer', label: 'Transferencia', value: Number(totals.transfer) || 0, hint: `${totals.transfer_count} cobros`, tone: 'blue' },
    ...(hasUnknown
      ? [
          {
            key: 'unknown',
            label: 'Sin método registrado',
            value: Number(totals.unknown) || 0,
            hint: `${totals.unknown_count} cobros históricos sin instrumento declarado`,
            tone: 'neutral',
          },
        ]
      : []),
  ]

  const timeSeries = [
    { key: 'cash', label: 'Efectivo', tone: 'orange' },
    { key: 'transfer', label: 'Transferencia', tone: 'blue' },
    ...(hasUnknown ? [{ key: 'unknown', label: 'Sin método registrado', tone: 'neutral' }] : []),
  ]

  return (
    <div className="space-y-5">
      <DashboardHeader
        title="Pagos manuales"
        subtitle="Cobros registrados a mano: cuánto entró por cada medio y quién lo registró."
        back={{ to: '/gym-admin/dashboard', label: 'Dashboard' }}
      />

      {error ? (
        <p className="rounded-lg border border-danger-line bg-danger-soft px-3 py-2 text-sm text-red-200">{error}</p>
      ) : null}

      <ReportFilterBar
        dateFrom={dateFrom}
        dateTo={dateTo}
        onDateFromChange={setDateFrom}
        onDateToChange={setDateTo}
        branches={branches}
        branchId={branchId}
        onBranchChange={setBranchId}
        extraFilter={{
          label: 'Método',
          value: method,
          onChange: setMethod,
          options: METHOD_OPTIONS,
          allLabel: 'Todos los métodos',
        }}
        onExport={handleExport}
        exporting={exporting}
        exportDisabled={loading || Boolean(exporting)}
      />

      <p className="text-xs text-brand-muted">
        {report?.period?.date_from || dateFrom} al {report?.period?.date_to || dateTo} ·{' '}
        {filters.branch_name || 'Todas las sucursales'} · {filters.method_label || 'Todos los métodos'}
      </p>

      {truncated ? (
        <p className="rounded-lg border border-warning-line bg-warning-soft px-3 py-2 text-sm text-amber-200">
          Esta lista muestra solo los primeros {report?.row_limit ?? rows.length} registros. Los totales y gráficos de
          arriba SÍ son del período completo: la única cosa recortada es la tabla de detalle.
        </p>
      ) : null}

      <section className={`grid grid-cols-1 gap-3 sm:grid-cols-2 ${hasUnknown ? 'lg:grid-cols-4' : 'lg:grid-cols-3'}`}>
        <StatCard title="Efectivo" value={clp(totals.cash)} accent="orange" hint={`${totals.cash_count} cobros`} />
        <StatCard title="Transferencia" value={clp(totals.transfer)} accent="blue" hint={`${totals.transfer_count} cobros`} />
        {hasUnknown ? (
          <StatCard
            title="Sin método registrado"
            value={clp(totals.unknown)}
            accent="muted"
            hint={`${totals.unknown_count} cobros históricos sin instrumento declarado`}
          />
        ) : null}
        <StatCard title="Total cobrado" value={clp(totals.total)} accent="success" hint={`${totals.count} cobros en total`} />
      </section>

      <section className="card-surface space-y-3 p-4 sm:p-5">
        <h2 className="text-sm font-semibold text-brand-white">Evolución en el período</h2>
        <TimeSeriesChart
          data={series}
          series={timeSeries}
          formatValue={clp}
          formatBucket={formatBucketLabel}
          title="Evolución de pagos manuales"
        />
      </section>

      <section className="card-surface space-y-3 p-4 sm:p-5">
        <h2 className="text-sm font-semibold text-brand-white">Efectivo vs. transferencia</h2>
        <HorizontalBarChart items={barItems} formatValue={clp} emptyLabel="Sin pagos manuales en el período." />
      </section>

      <section className="card-surface space-y-3 p-4 sm:p-5">
        <h2 className="text-sm font-semibold text-brand-white">Detalle de cobros</h2>
        {loading ? (
          <p className="py-8 text-center text-sm text-brand-muted">Cargando pagos manuales…</p>
        ) : rows.length === 0 ? (
          <p className="py-8 text-center text-sm text-brand-muted">Sin pagos manuales para los filtros actuales.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[820px] text-left text-sm">
              <thead className="text-[11px] uppercase tracking-wide text-brand-dim">
                <tr className="border-b border-brand-line">
                  <th className="py-2 pr-3 font-semibold">Fecha</th>
                  <th className="py-2 pr-3 font-semibold">Alumno</th>
                  <th className="py-2 pr-3 font-semibold">Plan</th>
                  <th className="py-2 pr-3 font-semibold">Método</th>
                  <th className="py-2 pr-3 font-semibold text-right">Monto</th>
                  <th className="py-2 pr-3 font-semibold">Referencia</th>
                  <th className="py-2 pr-3 font-semibold">Sucursal</th>
                  <th className="py-2 pr-3 font-semibold">Registrado por</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id} className="border-b border-brand-line/50">
                    <td className="py-2 pr-3 text-brand-muted">{formatDateTime(row.recorded_at)}</td>
                    <td className="py-2 pr-3 text-brand-white">{row.student_name || '—'}</td>
                    <td className="py-2 pr-3 text-brand-muted">{row.plan_name || '—'}</td>
                    <td className="py-2 pr-3">
                      <MethodBadge method={row.method} label={row.method_label} />
                    </td>
                    <td className="py-2 pr-3 text-right font-medium text-brand-white">{clp(row.amount)}</td>
                    <td className="py-2 pr-3 text-brand-muted">{row.reference || '—'}</td>
                    <td className="py-2 pr-3 text-brand-muted">{row.branch_name || '—'}</td>
                    <td className="py-2 pr-3 text-brand-muted">{row.recorded_by_name || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}
