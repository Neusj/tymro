import { useEffect, useState } from 'react'
import { branchesApi, downloadReportFile, getPlans, reportsApi } from '../api/client'
import DashboardHeader from '../components/DashboardHeader'
import StatCard from '../components/StatCard'
import ReportFilterBar from '../components/reports/ReportFilterBar'
import TimeSeriesChart from '../components/charts/TimeSeriesChart'
import { firstApiError } from '../utils/format'
import { buildReportParams, defaultReportPeriod, formatBucketLabel } from '../utils/reportFilters'

// Tasa/delta `null` (sin período anterior con datos, o denominador vacío en el propio
// período) se lee como guion — NUNCA como "0%": mismo criterio que formatDeltaPct en
// GymAdminRevenueReportPage. Acá además la escala YA viene en 0-100 desde el backend
// (igual que occupancy_rate), así que no hay que dividir ni multiplicar, solo formatear.
function formatRate(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return '—'
  }
  return `${Number(value).toFixed(1)}%`
}

// Los deltas de TASA vienen en PUNTOS PORCENTUALES (renewal_rate_delta_pp /
// retention_rate_delta_pp), no en variación relativa: rotularlos "%" mentiría sobre la
// magnitud (una tasa que pasa de 40% a 44% es "+4 pp", no "+4%" ni "+10%").
function formatDeltaPp(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return '—'
  }
  const num = Number(value)
  const sign = num > 0 ? '+' : ''
  return `${sign}${num.toFixed(1)} pp`
}

// expired_delta_pct / renewed_delta_pct SÍ son variación relativa (como net_delta_pct en
// Revenue) — distinto animal de los *_delta_pp de arriba, por eso un formatter separado.
function formatDeltaPct(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return '—'
  }
  const num = Number(value)
  const sign = num > 0 ? '+' : ''
  return `${sign}${num.toFixed(1)}%`
}

export default function GymAdminRetentionReportPage() {
  const [dateFrom, setDateFrom] = useState(() => defaultReportPeriod().dateFrom)
  const [dateTo, setDateTo] = useState(() => defaultReportPeriod().dateTo)
  const [branchId, setBranchId] = useState('')
  const [planId, setPlanId] = useState('')
  const [branches, setBranches] = useState([])
  const [plans, setPlans] = useState([])

  const [report, setReport] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [exporting, setExporting] = useState('')

  const buildParams = () => buildReportParams({ dateFrom, dateTo, branchId, extra: { plan_id: planId } })

  useEffect(() => {
    let active = true
    Promise.all([branchesApi.list(), getPlans()])
      .then(([branchData, planData]) => {
        if (!active) return
        setBranches(Array.isArray(branchData) ? branchData : [])
        setPlans((Array.isArray(planData) ? planData : []).filter((item) => item.is_active !== false))
      })
      .catch(() => {
        if (active) {
          setBranches([])
          setPlans([])
        }
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
        const data = await reportsApi.retention(buildParams())
        if (active) setReport(data)
      } catch (apiError) {
        if (active) {
          setError(firstApiError(apiError?.response?.data, 'No se pudo cargar el reporte de retención.'))
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
  }, [dateFrom, dateTo, branchId, planId])

  const handleExport = async (format) => {
    setExporting(format)
    setError('')
    try {
      const response = await reportsApi.exportRetention(buildParams(), format)
      downloadReportFile(response, `retencion_${dateFrom}_${dateTo}.${format === 'xlsx' ? 'xlsx' : 'csv'}`)
    } catch {
      setError('No se pudo exportar el reporte.')
    } finally {
      setExporting('')
    }
  }

  const totals = report?.totals || {
    expired: 0,
    renewed: 0,
    lost: 0,
    switched_plan: 0,
    churned: 0,
    pending_grace: 0,
    global_plan_memberships: 0,
    renewal_rate: null,
    retention_rate: null,
  }
  const comparison = report?.comparison || {}
  const upcoming = report?.upcoming || null
  const byPlan = Array.isArray(report?.by_plan) ? report.by_plan : []
  const series = Array.isArray(report?.series) ? report.series : []
  const filters = report?.filters || {}
  const pendingGrace = Number(totals.pending_grace) || 0
  const globalMemberships = Number(totals.global_plan_memberships) || 0
  const hasBranchFilter = Boolean(filters.branch_id)

  return (
    <div className="space-y-5">
      <DashboardHeader
        title="Retención"
        subtitle="Quién venció, quién volvió a comprar el mismo plan y quién se perdió — con la tasa de renovación y la de retención por separado."
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
          label: 'Plan',
          value: planId,
          onChange: setPlanId,
          options: plans.map((plan) => ({ value: plan.id, label: plan.name })),
          allLabel: 'Todos los planes',
        }}
        onExport={handleExport}
        exporting={exporting}
        exportDisabled={loading || Boolean(exporting)}
      />

      <p className="text-xs text-brand-muted">
        {report?.period?.date_from || dateFrom} al {report?.period?.date_to || dateTo} ·{' '}
        {filters.branch_name || 'Todas las sucursales'} · {filters.plan_name || 'Todos los planes'}
      </p>

      {hasBranchFilter ? (
        <p className="rounded-lg border border-info-line bg-info-soft px-3 py-2 text-sm text-blue-200">
          Sucursal seleccionada: este reporte incluye a propósito {globalMemberships} membresías de planes globales
          (sin sede, valen para todas las sucursales). Por eso los reportes por sede NO suman el total de la
          organización — las membresías globales aparecen en el reporte de cada sede.
        </p>
      ) : null}

      {pendingGrace > 0 ? (
        <p className="rounded-lg border border-warning-line bg-warning-soft px-3 py-2 text-sm text-amber-200">
          {pendingGrace} vencimientos todavía están dentro de la ventana de gracia de{' '}
          {filters.renewal_grace_days ?? 30} días: su veredicto (renovó, cambió de plan o se perdió) puede cambiar.
          Las tasas de abajo son provisorias, no definitivas.
        </p>
      ) : null}

      {/* Misma idea que "Bruto − Devoluciones = Neto" en Ingresos: la resta se lee literal
          antes de las tarjetas, y "perdidos" se desglosa en cambió de plan / no compró nada
          para no mezclar "se fue del gimnasio" con "sigue pero en otro plan". */}
      <section className="card-surface space-y-4 p-4 sm:p-5">
        <div>
          <p className="text-[11px] uppercase tracking-wide text-brand-dim">
            Vencieron − Renovaron (mismo plan) = Perdidos
          </p>
          <p className="mt-1 flex flex-wrap items-baseline gap-2 font-display text-2xl font-bold sm:text-3xl">
            <span className="text-brand-blue">{totals.expired}</span>
            <span className="text-brand-dim">−</span>
            <span className="text-success">{totals.renewed}</span>
            <span className="text-brand-dim">=</span>
            <span className="text-brand-red">{totals.lost}</span>
          </p>
          <p className="mt-1 text-xs text-brand-muted">
            De los perdidos: {totals.switched_plan} cambiaron a otro plan (se quedaron en el gimnasio) ·{' '}
            {totals.churned} no volvieron a comprar nada.
          </p>
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <StatCard
            title="Vencieron"
            value={totals.expired}
            accent="blue"
            hint={`${formatDeltaPct(comparison.expired_delta_pct)} vs. período anterior`}
          />
          <StatCard
            title="Renovaron (mismo plan)"
            value={totals.renewed}
            accent="success"
            hint={`${formatDeltaPct(comparison.renewed_delta_pct)} vs. período anterior`}
          />
          <StatCard
            title="Perdidos"
            value={totals.lost}
            accent="red"
            hint={`${totals.switched_plan} cambiaron de plan · ${totals.churned} se fueron`}
          />
        </div>
      </section>

      {/* Las DOS tasas, una junto a la otra y con hints que dicen explícitamente qué mide
          cada una — el pedido explícito es "mostrá las dos y que se entienda la diferencia,
          no las mezcles ni muestres una sola". */}
      <section className="card-surface space-y-3 p-4 sm:p-5">
        <h2 className="text-sm font-semibold text-brand-white">Dos tasas distintas, no una sola</h2>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <StatCard
            title="Tasa de renovación"
            value={formatRate(totals.renewal_rate)}
            accent="blue"
            hint={`Volvió a comprar el MISMO plan · ${formatDeltaPp(comparison.renewal_rate_delta_pp)} vs. período anterior`}
          />
          <StatCard
            title="Tasa de retención"
            value={formatRate(totals.retention_rate)}
            accent="success"
            hint={`Se quedó en el gimnasio, mismo plan u otro · ${formatDeltaPp(comparison.retention_rate_delta_pp)} vs. período anterior`}
          />
        </div>
      </section>

      {/* KPI "por vencer": ANCLADO EN HOY (as_of), no en el período filtrado arriba. Rótulo
          explícito para que nadie lo lea como parte del período consultado — un forward-looking
          KPI sin este cartel al lado de un reporte histórico se confunde con dato del período. */}
      {upcoming ? (
        <section className="card-surface space-y-3 border-brand-orange/30 p-4 sm:p-5">
          <div>
            <h2 className="text-sm font-semibold text-brand-white">
              Por vencer — próximos {upcoming.window_days} días desde HOY
            </h2>
            <p className="text-xs text-brand-muted">
              Anclado en hoy ({upcoming.as_of}), no en el período consultado arriba
              {upcoming.overlaps_period ? ' (se superpone parcialmente con ese período)' : ' (ese período ya terminó)'}
              .
            </p>
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <StatCard title="Por vencer" value={upcoming.expiring} accent="orange" hint="En los próximos días desde hoy" />
            <StatCard title="Ya renovaron" value={upcoming.already_renewed} accent="success" hint="Antes de vencer" />
            <StatCard title="En riesgo" value={upcoming.at_risk} accent="red" hint="Todavía no renovaron" />
          </div>
        </section>
      ) : null}

      <section className="card-surface space-y-3 p-4 sm:p-5">
        <h2 className="text-sm font-semibold text-brand-white">Evolución en el período</h2>
        <TimeSeriesChart
          data={series}
          series={[
            { key: 'expired', label: 'Vencieron', tone: 'info' },
            { key: 'renewed', label: 'Renovaron', tone: 'success' },
          ]}
          formatBucket={formatBucketLabel}
          title="Evolución de vencimientos y renovaciones"
        />
      </section>

      <section className="card-surface space-y-3 p-4 sm:p-5">
        <h2 className="text-sm font-semibold text-brand-white">Por plan</h2>
        {loading ? (
          <p className="py-6 text-center text-sm text-brand-muted">Cargando…</p>
        ) : byPlan.length === 0 ? (
          <p className="py-6 text-center text-sm text-brand-muted">Sin vencimientos en el período.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-left text-sm">
              <thead className="text-[11px] uppercase tracking-wide text-brand-dim">
                <tr className="border-b border-brand-line">
                  <th className="py-2 pr-3 font-semibold">Plan</th>
                  <th className="py-2 pr-3 font-semibold text-right">Vencieron</th>
                  <th className="py-2 pr-3 font-semibold text-right">Renovaron</th>
                  <th className="py-2 pr-3 font-semibold text-right">Cambiaron de plan</th>
                  <th className="py-2 pr-3 font-semibold text-right">Se fueron</th>
                  <th className="py-2 pr-3 font-semibold text-right">Tasa renovación</th>
                  <th className="py-2 pr-3 font-semibold text-right">Tasa retención</th>
                </tr>
              </thead>
              <tbody>
                {byPlan.map((row) => (
                  <tr key={row.plan_id ?? row.plan_name} className="border-b border-brand-line/50">
                    <td className="py-2 pr-3 text-brand-white">{row.plan_name || 'Sin plan'}</td>
                    <td className="py-2 pr-3 text-right text-brand-muted">{row.expired}</td>
                    <td className="py-2 pr-3 text-right text-brand-muted">{row.renewed}</td>
                    <td className="py-2 pr-3 text-right text-brand-muted">{row.switched_plan}</td>
                    <td className="py-2 pr-3 text-right text-brand-muted">{row.churned}</td>
                    <td className="py-2 pr-3 text-right font-medium text-brand-white">{formatRate(row.renewal_rate)}</td>
                    <td className="py-2 pr-3 text-right font-medium text-brand-white">{formatRate(row.retention_rate)}</td>
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
