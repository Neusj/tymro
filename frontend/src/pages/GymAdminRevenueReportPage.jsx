import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { branchesApi, downloadReportFile, reportsApi } from '../api/client'
import DashboardHeader from '../components/DashboardHeader'
import StatCard from '../components/StatCard'
import ReportFilterBar from '../components/reports/ReportFilterBar'
import TimeSeriesChart from '../components/charts/TimeSeriesChart'
import HorizontalBarChart from '../components/charts/HorizontalBarChart'
import { clp, firstApiError } from '../utils/format'
import { buildReportParams, defaultReportPeriod, formatBucketLabel } from '../utils/reportFilters'

// El backend puede sumar métodos nuevos (ver `unknown`: cobros manuales de antes de P3.2,
// sin backfill de `method`). Esta lista es SOLO el filtro; el desglose de abajo (by_method)
// nunca asume "como máximo 3" — se recorre genérico por lo que mande el backend.
const METHOD_OPTIONS = [
  { value: 'mercadopago', label: 'MercadoPago' },
  { value: 'cash', label: 'Efectivo' },
  { value: 'transfer', label: 'Transferencia' },
  { value: 'card', label: 'Tarjeta' },
  { value: 'check', label: 'Cheque' },
  { value: 'unknown', label: 'Sin método registrado' },
]

// null explícito (no hay período anterior con datos, o no se pudo calcular %) se lee como
// guion — NUNCA como "0%": un 0% real (sin variación) es un dato; null es la AUSENCIA de
// dato, y confundirlos le mentiría al gym_admin sobre si el ingreso se mantuvo igual o si
// simplemente no hay con qué comparar.
function formatDeltaPct(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return '—'
  }
  const num = Number(value)
  const sign = num > 0 ? '+' : ''
  return `${sign}${num.toFixed(1)}%`
}

export default function GymAdminRevenueReportPage() {
  // Filtros en la URL (P3.5), no en useState suelto: la capa 2 (detalle de un método) es
  // un nivel más adentro de ESTA misma pantalla, y el botón "atrás" del navegador tiene
  // que devolver al admin al mismo período/sucursal que tenía, no resetear al mes en
  // curso. `replace: true` al escribir para no ensuciar el historial con una entrada por
  // cada tecla tipeada en un <input type="date">.
  const [searchParams, setSearchParams] = useSearchParams()
  const defaults = defaultReportPeriod()
  const dateFrom = searchParams.get('date_from') || defaults.dateFrom
  const dateTo = searchParams.get('date_to') || defaults.dateTo
  const branchId = searchParams.get('branch_id') || ''
  const method = searchParams.get('method') || ''

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
        const data = await reportsApi.revenue(buildParams())
        if (active) setReport(data)
      } catch (apiError) {
        if (active) {
          setError(firstApiError(apiError?.response?.data, 'No se pudo cargar el reporte de ingresos.'))
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
      const response = await reportsApi.exportRevenue(buildParams(), format)
      downloadReportFile(response, `ingresos_${dateFrom}_${dateTo}.${format === 'xlsx' ? 'xlsx' : 'csv'}`)
    } catch {
      setError('No se pudo exportar el reporte.')
    } finally {
      setExporting('')
    }
  }

  const totals = report?.totals || { gross: 0, refunds: 0, net: 0, payments_count: 0, refunds_count: 0 }
  const byMethod = Array.isArray(report?.by_method) ? report.by_method : []
  const series = Array.isArray(report?.series) ? report.series : []
  const filters = report?.filters || {}
  const netDeltaPct = report?.comparison?.net_delta_pct

  // Los mismos date_from/date_to/branch_id que esta pantalla tiene puestos viajan a la
  // capa 2 (el método va en el PATH, no en la query — ahí ya no es un filtro, es la
  // pantalla). Sin esto, entrar al detalle de un método y volver perdería el filtro.
  const carryQuery = new URLSearchParams()
  if (dateFrom) carryQuery.set('date_from', dateFrom)
  if (dateTo) carryQuery.set('date_to', dateTo)
  if (branchId) carryQuery.set('branch_id', branchId)
  const carryQueryString = carryQuery.toString()

  const barItems = byMethod.map((row) => ({
    key: row.method,
    label: row.label || row.method,
    value: Number(row.net) || 0,
    hint: `Bruto ${clp(row.gross)} · Devoluciones ${clp(row.refunds)}`,
    // Fila clickeable → capa 2 (detalle de ESE método). HorizontalBarChart la renderiza
    // como <Link> real (foco de teclado + aria-label) en vez del <div> decorativo de
    // siempre; el resto de los consumidores del componente (Ocupación) no pasan `href`
    // y no cambian en nada.
    href: `/gym-admin/reports/revenue/${row.method}${carryQueryString ? `?${carryQueryString}` : ''}`,
  }))

  return (
    <div className="space-y-5">
      <DashboardHeader
        title="Ingresos"
        subtitle="Bruto, devoluciones y neto del período, con comparación contra el período anterior y desglose por método de pago."
        back={{ to: '/gym-admin/dashboard', label: 'Dashboard' }}
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
        extraFilter={{
          label: 'Método',
          value: method,
          onChange: (value) => setFilter('method', value),
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

      {/* Regla dura: bruto, devoluciones y neto SIEMPRE como 3 números separados. Nunca un
          solo total que se coma la resta — la ecuación se lee literal antes de las tarjetas. */}
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
          <StatCard title="Bruto" value={clp(totals.gross)} accent="blue" hint={`${totals.payments_count} pagos`} />
          <StatCard title="Devoluciones" value={clp(totals.refunds)} accent="red" hint={`${totals.refunds_count} devoluciones`} />
          <StatCard
            title="Neto"
            value={clp(totals.net)}
            accent="success"
            hint={`${formatDeltaPct(netDeltaPct)} vs. período anterior`}
          />
        </div>
      </section>

      <section className="card-surface space-y-3 p-4 sm:p-5">
        <h2 className="text-sm font-semibold text-brand-white">Evolución en el período</h2>
        <TimeSeriesChart
          data={series}
          series={[
            { key: 'gross', label: 'Bruto', tone: 'info' },
            { key: 'refunds', label: 'Devoluciones', tone: 'danger' },
            { key: 'net', label: 'Neto', tone: 'success' },
          ]}
          formatValue={clp}
          formatBucket={formatBucketLabel}
          title="Evolución de ingresos"
        />
      </section>

      <section className="card-surface space-y-3 p-4 sm:p-5">
        <h2 className="text-sm font-semibold text-brand-white">Por método de pago</h2>
        <p className="text-xs text-brand-muted">Tocá un método para ver sus cobros y devoluciones uno por uno.</p>
        {loading ? (
          <p className="py-6 text-center text-sm text-brand-muted">Cargando…</p>
        ) : (
          <HorizontalBarChart items={barItems} formatValue={clp} emptyLabel="Sin pagos en el período." />
        )}
      </section>
    </div>
  )
}
