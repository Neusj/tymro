import { useEffect, useMemo, useState } from 'react'
import { branchesApi, downloadReportFile, reportsApi } from '../api/client'
import DashboardHeader from '../components/DashboardHeader'
import StatCard from '../components/StatCard'
import ReportFilterBar from '../components/reports/ReportFilterBar'
import TimeSeriesChart from '../components/charts/TimeSeriesChart'
import DataTable from '../components/ui/DataTable'
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

const prospectTabs = [
  { value: 'all', label: 'Todos' },
  { value: 'converted', label: 'Compraron' },
]

const statusClasses = {
  converted: 'border-success/50 bg-success/10 text-emerald-100',
  pending: 'border-warning-line bg-warning-soft text-amber-100',
  refunded: 'border-info-line bg-info-soft text-blue-100',
  not_converted: 'border-brand-line bg-brand-soft text-brand-muted',
}

function formatDate(value) {
  if (!value) {
    return '-'
  }
  try {
    return new Date(`${value}T00:00:00`).toLocaleDateString('es-CL', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
    })
  } catch {
    return String(value)
  }
}

function formatDateTime(value) {
  if (!value) {
    return '-'
  }
  try {
    return new Date(value).toLocaleString('es-CL', {
      dateStyle: 'short',
      timeStyle: 'short',
    })
  } catch {
    return String(value)
  }
}

function formatMoney(value) {
  if (value === null || value === undefined || value === '') {
    return '-'
  }
  const number = Number(value)
  if (Number.isNaN(number)) {
    return String(value)
  }
  return new Intl.NumberFormat('es-CL', {
    style: 'currency',
    currency: 'CLP',
    maximumFractionDigits: 0,
  }).format(number)
}

function statusBadge(prospect) {
  const status = prospect?.conversion_status || 'not_converted'
  return (
    <span className={`inline-flex rounded-full border px-2 py-0.5 text-xs font-semibold ${statusClasses[status] || statusClasses.not_converted}`}>
      {prospect?.conversion_status_label || 'No compró'}
    </span>
  )
}

function firstTrialClass(prospect) {
  return Array.isArray(prospect?.trial_classes) ? prospect.trial_classes[0] : null
}

function trialClassSummary(prospect) {
  const trialClass = firstTrialClass(prospect)
  if (!trialClass) {
    return '-'
  }
  const pieces = [trialClass.name, trialClass.branch_name, trialClass.start_time].filter(Boolean)
  return pieces.join(' · ')
}

function ProspectDetail({ prospect }) {
  if (!prospect) {
    return (
      <aside className="card-surface flex min-h-[220px] items-center justify-center p-5 text-sm text-brand-muted">
        Selecciona un prospecto para ver el detalle.
      </aside>
    )
  }

  const membership = prospect.membership || null
  return (
    <aside className="card-surface space-y-4 p-4 sm:p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase tracking-wide text-brand-muted">Prospecto</p>
          <h3 className="mt-1 truncate font-display text-xl font-bold text-brand-white">{prospect.name}</h3>
        </div>
        {statusBadge(prospect)}
      </div>

      <div className="grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-brand-dim">Email</p>
          <p className="mt-0.5 break-words text-brand-white">{prospect.email || '-'}</p>
        </div>
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-brand-dim">Telefono</p>
          <p className="mt-0.5 text-brand-white">{prospect.phone || '-'}</p>
        </div>
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-brand-dim">Fecha prueba</p>
          <p className="mt-0.5 text-brand-white">{formatDate(prospect.trial_date)}</p>
        </div>
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-brand-dim">Asistencia</p>
          <p className="mt-0.5 text-brand-white">{prospect.attended ? 'Asistio' : 'Sin asistencia marcada'}</p>
        </div>
      </div>

      <div className="space-y-2 border-t border-brand-line pt-4">
        <p className="text-xs font-semibold uppercase tracking-wide text-brand-dim">Clases de prueba</p>
        {(prospect.trial_classes || []).length ? (
          <div className="space-y-2">
            {prospect.trial_classes.map((trialClass) => (
              <div key={trialClass.id} className="rounded-lg border border-brand-line bg-black/20 px-3 py-2">
                <p className="font-semibold text-brand-white">{trialClass.name || `Clase #${trialClass.id}`}</p>
                <p className="text-xs text-brand-muted">
                  {formatDateTime(trialClass.start_datetime)} · {trialClass.branch_name || 'Sin sede'}
                </p>
                <p className="text-xs text-brand-muted">
                  {trialClass.teacher_name || 'Sin profesor'} · {trialClass.discipline_name || trialClass.class_type_name || 'Sin disciplina'}
                </p>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-brand-muted">Sin clase asociada.</p>
        )}
      </div>

      <div className="grid gap-3 border-t border-brand-line pt-4 text-sm sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-brand-dim">Fecha limite</p>
          <p className="mt-0.5 text-brand-white">{formatDate(prospect.conversion_deadline)}</p>
        </div>
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-brand-dim">Plan comprado</p>
          <p className="mt-0.5 text-brand-white">{membership?.plan_name || '-'}</p>
        </div>
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-brand-dim">Inicio plan</p>
          <p className="mt-0.5 text-brand-white">{formatDate(membership?.start_date)}</p>
        </div>
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-brand-dim">Monto plan</p>
          <p className="mt-0.5 text-brand-white">{formatMoney(membership?.final_price)}</p>
        </div>
      </div>
    </aside>
  )
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
  const [prospectTab, setProspectTab] = useState(null)
  const [selectedProspectId, setSelectedProspectId] = useState(null)

  const buildParams = () => buildReportParams({ dateFrom, dateTo, branchId })

  const openProspects = (tab) => {
    setProspectTab(tab)
    setSelectedProspectId(null)
  }

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

  useEffect(() => {
    setSelectedProspectId(null)
  }, [report])

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
  const prospects = Array.isArray(report?.prospects) ? report.prospects : []
  const convertedProspects = prospects.filter((prospect) => prospect.converted)
  const visibleProspects = prospectTab === 'converted' ? convertedProspects : prospects
  const selectedProspect =
    visibleProspects.find((prospect) => prospect.id === selectedProspectId) || visibleProspects[0] || null
  const filters = report?.filters || {}
  const unbackedFlags = report?.unbacked_trial_flags || null
  const refundedConversions = Number(totals.refunded_conversions) || 0
  const pendingWindow = Number(totals.pending_window) || 0
  const cancelledTrials = Number(totals.cancelled_trials) || 0
  const pendingTrials = Number(totals.pending_trials) || 0
  const unbackedCount = Number(unbackedFlags?.students) || 0

  const prospectColumns = useMemo(
    () => [
      { key: 'name', label: 'Prospecto', render: (row) => row.name || `Alumno #${row.student_id}` },
      { key: 'trial_date', label: 'Prueba', render: (row) => formatDate(row.trial_date) },
      { key: 'trial_class', label: 'Clase', render: trialClassSummary },
      {
        key: 'attended',
        label: 'Asistencia',
        render: (row) => (row.attended ? 'Asistio' : 'Sin marca'),
      },
      {
        key: 'conversion_status',
        label: 'Estado',
        render: statusBadge,
      },
      {
        key: 'plan',
        label: 'Plan',
        render: (row) => row.membership?.plan_name || <span className="text-brand-muted">-</span>,
      },
    ],
    [],
  )

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
          onClick={() => openProspects('all')}
          ariaLabel="Ver todos los prospectos que probaron"
          hint={`${formatDeltaPct(comparison.trials_delta_pct)} vs. período anterior`}
        />
        <StatCard
          title="Compraron"
          value={totals.converted}
          accent="success"
          onClick={() => openProspects('converted')}
          ariaLabel="Ver prospectos que compraron"
          hint={`${formatDeltaPct(comparison.converted_delta_pct)} vs. período anterior`}
        />
      </section>

      {prospectTab ? (
        <section className="space-y-4" aria-label="Detalle de prospectos">
          <div className="flex flex-col gap-3 border-b border-brand-line sm:flex-row sm:items-end sm:justify-between">
            <div className="flex flex-wrap gap-2">
              {prospectTabs.map((tab) => (
                <button
                  key={tab.value}
                  type="button"
                  onClick={() => openProspects(tab.value)}
                  aria-current={prospectTab === tab.value ? 'true' : undefined}
                  className={`min-h-10 border-b-2 px-3 text-sm font-semibold transition ${
                    prospectTab === tab.value
                      ? 'border-brand-orange text-brand-white'
                      : 'border-transparent text-brand-muted hover:text-brand-white'
                  }`}
                >
                  {tab.label}
                </button>
              ))}
            </div>
            <button
              type="button"
              onClick={() => setProspectTab(null)}
              className="mb-2 self-start rounded-lg border border-brand-line px-3 py-1.5 text-xs font-semibold text-brand-white transition hover:border-brand-blue sm:self-auto"
            >
              Cerrar detalle
            </button>
          </div>

          <div className="grid gap-4 xl:grid-cols-[minmax(0,1.45fr)_minmax(320px,0.75fr)]">
            <DataTable
              columns={prospectColumns}
              data={visibleProspects}
              loading={loading}
              defaultSort={{ key: 'trial_date', direction: 'desc' }}
              onRowClick={(row) => setSelectedProspectId(row.id)}
            />
            <ProspectDetail prospect={selectedProspect} />
          </div>
        </section>
      ) : null}

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
