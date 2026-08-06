import { useEffect, useState } from 'react'
import { branchesApi, downloadReportFile, reportsApi } from '../api/client'
import DashboardHeader from '../components/DashboardHeader'
import StatCard from '../components/StatCard'
import ReportFilterBar from '../components/reports/ReportFilterBar'
import TimeSeriesChart from '../components/charts/TimeSeriesChart'
import { firstApiError } from '../utils/format'
import { buildReportParams, defaultReportPeriod, formatBucketLabel } from '../utils/reportFilters'

// null (sin período anterior con datos, o denominador vacío) se lee como guion — NUNCA
// como "0%": mismo criterio que formatDeltaPct en GymAdminRevenueReportPage. La escala ya
// viene en 0-100 desde el backend (igual que occupancy_rate).
function formatRate(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return '—'
  }
  return `${Number(value).toFixed(1)}%`
}

// conversion_rate_delta_pp viene en PUNTOS PORCENTUALES, no en variación relativa.
function formatDeltaPp(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return '—'
  }
  const num = Number(value)
  const sign = num > 0 ? '+' : ''
  return `${sign}${num.toFixed(1)} pp`
}

// trials_delta_pct / converted_delta_pct SÍ son variación relativa (como net_delta_pct en
// Revenue) — distinto animal del *_delta_pp de arriba.
function formatDeltaPct(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return '—'
  }
  const num = Number(value)
  const sign = num > 0 ? '+' : ''
  return `${sign}${num.toFixed(1)}%`
}

export default function GymAdminTrialConversionReportPage() {
  const [dateFrom, setDateFrom] = useState(() => defaultReportPeriod().dateFrom)
  const [dateTo, setDateTo] = useState(() => defaultReportPeriod().dateTo)
  const [branchId, setBranchId] = useState('')
  const [branches, setBranches] = useState([])

  const [report, setReport] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [exporting, setExporting] = useState('')

  const buildParams = () => buildReportParams({ dateFrom, dateTo, branchId })

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
        const data = await reportsApi.trialConversion(buildParams())
        if (active) setReport(data)
      } catch (apiError) {
        if (active) {
          setError(firstApiError(apiError?.response?.data, 'No se pudo cargar el reporte de conversión de prueba.'))
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
  }, [dateFrom, dateTo, branchId])

  const handleExport = async (format) => {
    setExporting(format)
    setError('')
    try {
      const response = await reportsApi.exportTrialConversion(buildParams(), format)
      downloadReportFile(response, `conversion_prueba_${dateFrom}_${dateTo}.${format === 'xlsx' ? 'xlsx' : 'csv'}`)
    } catch {
      setError('No se pudo exportar el reporte.')
    } finally {
      setExporting('')
    }
  }

  const totals = report?.totals || {
    trials: 0,
    converted: 0,
    conversion_rate: null,
    attended: 0,
    converted_attended: 0,
    attended_conversion_rate: null,
    refunded_conversions: 0,
    pending_window: 0,
    cancelled_trials: 0,
    pending_trials: 0,
  }
  const comparison = report?.comparison || {}
  const series = Array.isArray(report?.series) ? report.series : []
  const filters = report?.filters || {}
  const unbackedFlags = report?.unbacked_trial_flags || null
  const refundedConversions = Number(totals.refunded_conversions) || 0
  const pendingWindow = Number(totals.pending_window) || 0
  const cancelledTrials = Number(totals.cancelled_trials) || 0
  const pendingTrials = Number(totals.pending_trials) || 0
  const unbackedCount = Number(unbackedFlags?.students) || 0

  return (
    <div className="space-y-5">
      <DashboardHeader
        title="Conversión de clase gratis"
        subtitle="Cuántos probaron una clase gratis y cuántos terminaron comprando, dentro de la ventana de conversión."
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
        onExport={handleExport}
        exporting={exporting}
        exportDisabled={loading || Boolean(exporting)}
      />

      <p className="text-xs text-brand-muted">
        {report?.period?.date_from || dateFrom} al {report?.period?.date_to || dateTo} ·{' '}
        {filters.branch_name || 'Todas las sucursales'} · ventana de conversión:{' '}
        {filters.conversion_window_days ?? 60} días
      </p>

      {pendingWindow > 0 ? (
        <p className="rounded-lg border border-warning-line bg-warning-soft px-3 py-2 text-sm text-amber-200">
          {pendingWindow} alumnos probaron hace poco y todavía están dentro de la ventana de{' '}
          {filters.conversion_window_days ?? 60} días para comprar: su veredicto está abierto y la tasa de conversión
          puede subir.
        </p>
      ) : null}

      {refundedConversions > 0 ? (
        <p className="rounded-lg border border-info-line bg-info-soft px-3 py-2 text-sm text-blue-200">
          {refundedConversions} compras posteriores a la clase de prueba se devolvieron: por eso ya NO cuentan como
          conversión en la tasa de arriba.
        </p>
      ) : null}

      {/* Portada: las tres cifras principales bien visibles, la tasa como número grande. */}
      <section className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <StatCard
          title="Tasa de conversión"
          value={formatRate(totals.conversion_rate)}
          accent="success"
          hint={`${formatDeltaPp(comparison.conversion_rate_delta_pp)} vs. período anterior`}
        />
        <StatCard
          title="Probaron"
          value={totals.trials}
          accent="blue"
          hint={`${formatDeltaPct(comparison.trials_delta_pct)} vs. período anterior`}
        />
        <StatCard
          title="Compraron"
          value={totals.converted}
          accent="success"
          hint={`${formatDeltaPct(comparison.converted_delta_pct)} vs. período anterior`}
        />
      </section>

      {/* Dato COMPLEMENTARIO, no el principal: cuenta solo a los que efectivamente
          asistieron. Un gimnasio que no pasa lista marca a todos como ausentes, así que
          esta tasa se ve deliberadamente más chica/secundaria que la de arriba. */}
      <section className="card-surface space-y-3 p-4 sm:p-5">
        <div>
          <h2 className="text-sm font-semibold text-brand-white">Dato complementario: solo alumnos que asistieron</h2>
          <p className="text-xs text-brand-muted">
            Cuenta solo a quienes efectivamente marcaron asistencia en su clase de prueba. Un gimnasio que no pasa
            lista marca a todos como ausentes, por eso esta tasa NO es la tasa principal de portada.
          </p>
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <StatCard title="Asistieron" value={totals.attended} accent="muted" />
          <StatCard title="Asistieron y compraron" value={totals.converted_attended} accent="muted" />
          <StatCard
            title="Tasa (solo asistieron)"
            value={formatRate(totals.attended_conversion_rate)}
            accent="muted"
          />
        </div>
      </section>

      <section className="card-surface space-y-3 p-4 sm:p-5">
        <h2 className="text-sm font-semibold text-brand-white">Evolución en el período</h2>
        <TimeSeriesChart
          data={series}
          series={[
            { key: 'trials', label: 'Probaron', tone: 'info' },
            { key: 'converted', label: 'Compraron', tone: 'success' },
          ]}
          formatBucket={formatBucketLabel}
          title="Evolución de pruebas y conversiones"
        />
      </section>

      {/* Notas al pie: fuera del denominador a propósito, así que van como texto chico, no
          como alerta — no son un problema, son datos excluidos del cálculo por diseño. */}
      <p className="text-xs text-brand-muted">
        {cancelledTrials} clases de prueba canceladas y {pendingTrials} todavía no se dictan (clase futura): ambas
        quedan fuera de la tasa de conversión, no se cuentan ni como probaron ni como perdidas.
        {unbackedCount > 0
          ? ` Además, ${unbackedCount} alumnos (a nivel organización, no solo esta sucursal/período) están marcados como "usó su prueba" pero sin una reserva de prueba registrada en la base — son invisibles para esta tasa.`
          : null}
      </p>
    </div>
  )
}
