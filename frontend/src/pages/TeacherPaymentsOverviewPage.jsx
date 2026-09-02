import { useEffect, useMemo, useState } from 'react'
import { organizationsApi, teacherPaymentsApi } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import DashboardHeader from '../components/DashboardHeader'
import FormModal from '../components/FormModal'
import ValueBadge from '../components/ui/ValueBadge'
import PayoutStatus from '../components/ui/PayoutStatus'
import { canManageAdmin } from '../utils/roles'

const MONTH_NAMES = [
  'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
  'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre',
]

const CALC_LABELS = {
  missing: 'Calcular faltantes',
  recalculate_pending: 'Recalcular pendientes',
}

function clp(value) {
  return `$${Math.round(Number(value) || 0).toLocaleString('es-CL', { maximumFractionDigits: 0 })}`
}

function pad2(value) {
  return String(value).padStart(2, '0')
}

function currentMonthValue() {
  const now = new Date()
  return `${now.getFullYear()}-${pad2(now.getMonth() + 1)}`
}

function monthToRange(monthValue) {
  const [year, month] = monthValue.split('-').map(Number)
  const from = `${year}-${pad2(month)}-01`
  const lastDay = new Date(year, month, 0).getDate()
  const to = `${year}-${pad2(month)}-${pad2(lastDay)}`
  return { date_from: from, date_to: to }
}

function periodLabel(monthValue) {
  const [year, month] = monthValue.split('-').map(Number)
  return `${MONTH_NAMES[month - 1]} ${year}`
}

function formatDay(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleDateString('es-CL', { day: '2-digit', month: '2-digit' })
}

function formatDateOnly(value) {
  if (!value) return '-'
  const [year, month, day] = String(value).split('-')
  if (!year || !month || !day) return value
  return `${day}-${month}-${year}`
}

function rowPeriodLabel(row) {
  const period = row?.period || {}
  if (!period.date_from && !period.date_to) return '-'
  return `${formatDateOnly(period.date_from)} a ${formatDateOnly(period.date_to)}`
}

function firstApiError(detail, fallback) {
  if (!detail) return fallback
  if (typeof detail === 'string') return detail
  if (detail.detail) return detail.detail
  const firstValue = Object.values(detail)[0]
  if (Array.isArray(firstValue) && firstValue[0]) return firstValue[0]
  return fallback
}

function StatTile({ label, value, accent }) {
  return (
    <div className="rounded-xl border border-brand-hairline bg-brand-panel/60 p-3">
      <p className="text-[11px] uppercase tracking-wide text-brand-dim">{label}</p>
      <p className={`mt-1 font-display text-lg font-semibold leading-none ${accent || 'text-brand-white'}`}>{value}</p>
    </div>
  )
}


export default function TeacherPaymentsOverviewPage() {
  const { user } = useAuth()
  const isSuperadmin = user?.role === 'superadmin'
  const canMarkPaid = canManageAdmin(user?.role)

  const [month, setMonth] = useState(currentMonthValue())
  const [classKind, setClassKind] = useState('all')
  const [summary, setSummary] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [expanded, setExpanded] = useState(null)
  const [exporting, setExporting] = useState('')
  const [marking, setMarking] = useState(null)
  const [calculationPreview, setCalculationPreview] = useState(null)
  const [calculationLoading, setCalculationLoading] = useState('')
  const [calculationRunning, setCalculationRunning] = useState(false)
  const [voidingBatch, setVoidingBatch] = useState(null)
  const [voidReason, setVoidReason] = useState('')

  const [organizations, setOrganizations] = useState([])
  const [selectedOrganizationId, setSelectedOrganizationId] = useState(user?.organization ? String(user.organization) : '')

  const buildParams = () => {
    const params = { ...monthToRange(month) }
    if (isSuperadmin && selectedOrganizationId) {
      params.organization_id = selectedOrganizationId
    }
    if (classKind !== 'all') {
      params.class_kind = classKind
    }
    return params
  }

  const loadOrganizations = async () => {
    if (!isSuperadmin) return
    try {
      const data = await organizationsApi.list()
      const list = Array.isArray(data) ? data : []
      setOrganizations(list)
      if (!selectedOrganizationId && list.length > 0) {
        setSelectedOrganizationId(String(list[0].id))
      }
    } catch {
      setOrganizations([])
    }
  }

  const loadSummary = async () => {
    if (isSuperadmin && !selectedOrganizationId) {
      setSummary(null)
      setLoading(false)
      return
    }
    setLoading(true)
    setError('')
    try {
      const data = await teacherPaymentsApi.summary(buildParams())
      setSummary(data)
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudo cargar el resumen de pagos.'))
      setSummary(null)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadOrganizations()
  }, [isSuperadmin])

  useEffect(() => {
    loadSummary()
    setExpanded(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [month, classKind, selectedOrganizationId, isSuperadmin])

  const rows = summary?.rows || []
  const grandTotal = summary?.grand_total || 0
  const calculationBatches = summary?.calculation_batches || []

  const totals = useMemo(() => {
    return rows.reduce(
      (acc, row) => {
        acc.classes += row.classes_count || 0
        acc.normal += row.normal_classes_count || 0
        acc.personalized += row.personalized_classes_count || 0
        acc.attendees += row.attendees_total || 0
        return acc
      },
      { classes: 0, normal: 0, personalized: 0, attendees: 0 },
    )
  }, [rows])

  const handleExport = async (format) => {
    if (isSuperadmin && !selectedOrganizationId) return
    setExporting(format)
    setError('')
    try {
      const response = await teacherPaymentsApi.exportSummary({ ...buildParams(), fmt: format })
      const blob = new Blob([response.data], { type: response.headers['content-type'] })
      const url = window.URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `pagos_profesores_${month}.${format === 'xlsx' ? 'xlsx' : 'csv'}`
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
    } catch {
      setError('No se pudo exportar el resumen.')
    } finally {
      setExporting('')
    }
  }

  const openCalculationPreview = async (mode) => {
    if (isSuperadmin && !selectedOrganizationId) return
    if (classKind === 'personalized') {
      setError('El calculo manual aplica solo a clases normales.')
      return
    }
    setCalculationLoading(mode)
    setError('')
    setNotice('')
    try {
      const data = await teacherPaymentsApi.calculationPreview({ ...buildParams(), mode })
      setCalculationPreview(data)
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudo preparar el calculo.'))
    } finally {
      setCalculationLoading('')
    }
  }

  const runCalculation = async () => {
    if (!calculationPreview?.mode) return
    setCalculationRunning(true)
    setError('')
    setNotice('')
    try {
      if (calculationPreview.mode === 'recalculate_pending') {
        await teacherPaymentsApi.recalculatePending(buildParams())
      } else {
        await teacherPaymentsApi.calculateMissing(buildParams())
      }
      setNotice('Calculo registrado.')
      setCalculationPreview(null)
      await loadSummary()
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudo ejecutar el calculo.'))
    } finally {
      setCalculationRunning(false)
    }
  }

  const confirmVoidCalculation = async (event) => {
    event.preventDefault()
    if (!voidingBatch?.id) return
    setCalculationRunning(true)
    setError('')
    setNotice('')
    try {
      const payload = { batch_id: voidingBatch.id, reason: voidReason }
      if (isSuperadmin && selectedOrganizationId) {
        payload.organization_id = selectedOrganizationId
      }
      await teacherPaymentsApi.voidCalculation(payload)
      setNotice('Calculo anulado.')
      setVoidingBatch(null)
      setVoidReason('')
      await loadSummary()
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudo anular el calculo.'))
    } finally {
      setCalculationRunning(false)
    }
  }

  const handleMarkPaid = async (teacherId) => {
    setMarking(teacherId)
    setError('')
    try {
      const [year, mon] = month.split('-').map(Number)
      const payload = { teacher_id: teacherId, year, month: mon }
      if (isSuperadmin && selectedOrganizationId) {
        payload.organization_id = selectedOrganizationId
      }
      await teacherPaymentsApi.markPaid(payload)
      await loadSummary()
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudo marcar el pago.'))
    } finally {
      setMarking(null)
    }
  }

  const exportDisabled = loading || rows.length === 0 || Boolean(exporting)

  return (
    <div className="space-y-5">
      <DashboardHeader
        title="Pagos Profesores · Resumen"
        subtitle="Lo que le debes a cada profesor en el período. Puedes filtrar normales o personalizadas y exportar el detalle."
      />

      {error ? (
        <p className="rounded-lg border border-danger-line bg-danger-soft px-3 py-2 text-sm text-red-200">{error}</p>
      ) : null}
      {notice ? (
        <p className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-200">{notice}</p>
      ) : null}

      {/* Controles de período + export */}
      <section className="card-surface space-y-4 p-4 sm:p-5">
        {isSuperadmin ? (
          <label className="block space-y-1 text-sm">
            <span className="text-brand-muted">Organización</span>
            <select
              value={selectedOrganizationId}
              onChange={(event) => setSelectedOrganizationId(event.target.value)}
              className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
            >
              <option value="">Seleccionar</option>
              {organizations.map((item) => (
                <option key={item.id} value={item.id}>{item.name}</option>
              ))}
            </select>
          </label>
        ) : null}

        <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="space-y-1 text-sm">
              <span className="text-brand-muted">Período</span>
              <input
                type="month"
                value={month}
                onChange={(event) => setMonth(event.target.value || currentMonthValue())}
                className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2 sm:w-52"
              />
            </label>
            <label className="space-y-1 text-sm">
              <span className="text-brand-muted">Tipo de clase</span>
              <select
                value={classKind}
                onChange={(event) => setClassKind(event.target.value)}
                className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2 sm:w-52"
              >
                <option value="all">Todas</option>
                <option value="normal">Normales</option>
                <option value="personalized">Personalizadas</option>
              </select>
            </label>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {canMarkPaid ? (
              <>
                <button
                  type="button"
                  disabled={loading || Boolean(calculationLoading) || calculationRunning || classKind === 'personalized'}
                  onClick={() => openCalculationPreview('missing')}
                  className="inline-flex items-center gap-1.5 rounded-xl border border-brand-orange/50 px-3 py-2 text-sm font-semibold text-brand-orange transition hover:bg-brand-orange/10 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {calculationLoading === 'missing' ? 'Revisando...' : 'Calcular faltantes'}
                </button>
                <button
                  type="button"
                  disabled={loading || Boolean(calculationLoading) || calculationRunning || classKind === 'personalized'}
                  onClick={() => openCalculationPreview('recalculate_pending')}
                  className="inline-flex items-center gap-1.5 rounded-xl border border-brand-blue/50 px-3 py-2 text-sm font-semibold text-brand-blue transition hover:bg-brand-blue/10 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {calculationLoading === 'recalculate_pending' ? 'Revisando...' : 'Recalcular pendientes'}
                </button>
              </>
            ) : null}
            <button
              type="button"
              disabled={exportDisabled}
              onClick={() => handleExport('csv')}
              className="inline-flex items-center gap-1.5 rounded-xl border border-brand-hairline px-3 py-2 text-sm font-semibold text-brand-white transition hover:border-brand-blue disabled:cursor-not-allowed disabled:opacity-50"
            >
              {exporting === 'csv' ? 'Exportando…' : 'CSV'}
            </button>
            <button
              type="button"
              disabled={exportDisabled}
              onClick={() => handleExport('xlsx')}
              className="inline-flex items-center gap-1.5 rounded-xl bg-success px-3 py-2 text-sm font-semibold text-black transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {exporting === 'xlsx' ? 'Exportando…' : 'Excel'}
            </button>
          </div>
        </div>

        {canMarkPaid && calculationBatches.length > 0 ? (
          <div className="space-y-2 border-t border-brand-hairline pt-3">
            <p className="text-[11px] uppercase tracking-wide text-brand-dim">Historial de calculos del periodo</p>
            <div className="space-y-2">
              {calculationBatches.map((batch) => (
                <div key={batch.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-brand-hairline bg-brand-panel/40 px-3 py-2 text-sm">
                  <span className="text-brand-muted">
                    #{batch.id} · {CALC_LABELS[batch.mode] || batch.mode} · {batch.classes_count} clases · {clp(batch.total_amount)}
                    {batch.status === 'voided' ? ' · Anulado' : ''}
                  </span>
                  {batch.status === 'active' ? (
                    <button
                      type="button"
                      disabled={calculationRunning}
                      onClick={() => setVoidingBatch(batch)}
                      className="rounded border border-amber-500/40 px-2 py-1 text-xs font-semibold text-amber-200 transition hover:bg-amber-500/10 disabled:opacity-50"
                    >
                      Anular calculo
                    </button>
                  ) : null}
                </div>
              ))}
            </div>
          </div>
        ) : null}
      </section>

      {/* Hero: gran total + métricas del período */}
      <section className="relative overflow-hidden rounded-2xl border border-brand-hairline bg-gradient-to-br from-brand-orange/15 via-brand-panel to-brand-blue/10 p-5 shadow-soft">
        <div className="pointer-events-none absolute -right-12 -top-12 h-40 w-40 rounded-full bg-brand-orange/15 blur-3xl" />
        <div className="relative">
          <p className="text-[11px] uppercase tracking-[0.18em] text-brand-dim">Total a pagar · {periodLabel(month)}</p>
          <p className="mt-1 font-display text-4xl font-bold leading-none text-brand-white sm:text-5xl">
            {clp(grandTotal)}
          </p>
          <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
            <StatTile label="Profesores" value={rows.length} accent="text-brand-orange" />
            <StatTile label="Normales" value={totals.normal} />
            <StatTile label="Personalizadas" value={totals.personalized} accent="text-brand-blue" />
            <StatTile label="Asistentes" value={totals.attendees} />
          </div>
        </div>
      </section>

      {/* Tabla agregada (filas-tarjeta expandibles) */}
      <section className="space-y-2">
        {/* Encabezado de columnas (sm+) */}
        <div className="hidden grid-cols-[1.4fr_1fr_repeat(3,0.7fr)_auto] items-center gap-3 px-4 text-[11px] uppercase tracking-wide text-brand-dim sm:grid">
          <span>Profesor</span>
          <span>Periodo real</span>
          <span className="text-right">Clases</span>
          <span className="text-right">Asistentes</span>
          <span className="text-right">Total</span>
          <span className="w-5" />
        </div>

        {loading ? (
          <div className="card-surface p-6 text-center text-sm text-brand-muted">Cargando resumen…</div>
        ) : rows.length === 0 ? (
          <div className="card-surface p-6 text-center text-sm text-brand-muted">
            No hay pagos en este período.
          </div>
        ) : (
          rows.map((row, index) => {
            const isOpen = expanded === row.teacher_id
            return (
              <div
                key={row.teacher_id}
                className="card-surface animate-fade-rise overflow-hidden p-0"
                style={{ animationDelay: `${Math.min(index, 8) * 35}ms` }}
              >
                <button
                  type="button"
                  onClick={() => setExpanded(isOpen ? null : row.teacher_id)}
                  className="grid w-full grid-cols-[1fr_auto] items-center gap-3 p-4 text-left transition hover:bg-brand-elevated/40 sm:grid-cols-[1.4fr_1fr_repeat(3,0.7fr)_auto]"
                >
                  {/* Profesor + modalidades */}
                  <div className="min-w-0">
                    <p className="truncate font-medium text-brand-white">{row.teacher_name}</p>
                    <p className="mt-0.5 text-xs text-brand-muted sm:hidden">{rowPeriodLabel(row)}</p>
                    <div className="mt-1 flex flex-wrap items-center gap-1">
                      {row.modalities.length === 0 ? (
                        <span className="text-xs text-brand-dim">Sin modalidad</span>
                      ) : (
                        row.modalities.map((code) => <ValueBadge key={code} kind="payment_type" value={code} />)
                      )}
                      {row.personalized_classes_count ? (
                        <span className="rounded-full border border-brand-blue/30 bg-brand-blue/10 px-2 py-0.5 text-[11px] text-brand-blue">
                          {row.personalized_classes_count} pers.
                        </span>
                      ) : null}
                      <PayoutStatus payout={row.payout} pending={row.pending} />
                    </div>
                    {/* Métricas inline (solo móvil) */}
                    <p className="mt-1.5 text-xs text-brand-muted sm:hidden">
                      {row.classes_count} clases · {row.attendees_total} asistentes
                    </p>
                  </div>

                  {/* Columnas numéricas (sm+) */}
                  <span className="hidden text-sm text-brand-muted sm:block">{rowPeriodLabel(row)}</span>
                  <span className="hidden text-right text-sm tabular-nums text-brand-muted sm:block">{row.classes_count}</span>
                  <span className="hidden text-right text-sm tabular-nums text-brand-muted sm:block">{row.attendees_total}</span>

                  {/* Total + chevron */}
                  <div className="flex items-center justify-end gap-2">
                    <span className="font-display text-base font-semibold tabular-nums text-brand-white">{clp(row.total)}</span>
                    <svg
                      width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"
                      strokeLinecap="round" strokeLinejoin="round"
                      className={`shrink-0 text-brand-dim transition-transform duration-200 ${isOpen ? 'rotate-180' : ''}`}
                      aria-hidden="true"
                    >
                      <path d="M6 9l6 6 6-6" />
                    </svg>
                  </div>
                </button>

                {/* Drill-down */}
                {isOpen ? (
                  <div className="border-t border-brand-hairline bg-brand-ink/40 p-4">
                    {/* Estado de pago del período + acción */}
                    <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                      <PayoutStatus payout={row.payout} pending={row.pending} />
                      {canMarkPaid ? (
                        <button
                          type="button"
                          disabled={marking === row.teacher_id}
                          onClick={() => handleMarkPaid(row.teacher_id)}
                          className="inline-flex items-center gap-1.5 rounded-xl bg-success px-3 py-1.5 text-xs font-semibold text-black transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          {marking === row.teacher_id
                            ? 'Guardando…'
                            : row.payout
                              ? 'Actualizar pago'
                              : 'Marcar como pagado'}
                        </button>
                      ) : null}
                    </div>

                    {/* Desglose sueldo base + por clase = total */}
                    <div className="mb-3 grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
                      <div className="rounded-lg border border-brand-hairline bg-brand-panel/50 p-2.5">
                        <p className="text-[11px] uppercase tracking-wide text-brand-dim">Periodo real</p>
                        <p className="mt-0.5 text-brand-white">{rowPeriodLabel(row)}</p>
                      </div>
                      <div className="rounded-lg border border-brand-hairline bg-brand-panel/50 p-2.5">
                        <p className="text-[11px] uppercase tracking-wide text-brand-dim">Sueldo base</p>
                        <p className="mt-0.5 tabular-nums text-brand-white">{clp(row.monthly_total)}</p>
                      </div>
                      <div className="rounded-lg border border-brand-hairline bg-brand-panel/50 p-2.5">
                        <p className="text-[11px] uppercase tracking-wide text-brand-dim">Por clase</p>
                        <p className="mt-0.5 tabular-nums text-brand-white">{clp(row.per_class_total)}</p>
                      </div>
                      <div className="rounded-lg border border-brand-orange/40 bg-brand-orange/10 p-2.5">
                        <p className="text-[11px] uppercase tracking-wide text-brand-orange/80">Total</p>
                        <p className="mt-0.5 font-semibold tabular-nums text-brand-white">{clp(row.total)}</p>
                      </div>
                    </div>

                    {/* Detalle de clases */}
                    {row.classes.length > 0 ? (
                      <div className="space-y-1.5">
                        <p className="text-[11px] uppercase tracking-wide text-brand-dim">Clases del período</p>
                        {row.classes.map((cls) => (
                          <div
                            key={cls.id}
                            className="flex items-center justify-between gap-3 rounded-lg border border-brand-line/60 bg-brand-panel/40 px-3 py-2 text-sm"
                          >
                            <div className="min-w-0">
                              <p className="truncate text-brand-white">{cls.name || `Clase #${cls.id}`}</p>
                              <p className="text-xs text-brand-dim">
                                {formatDay(cls.start)} · {cls.attendees} asist.
                                {cls.class_kind === 'personalized' && cls.student_name ? ` · ${cls.student_name}` : ''}
                              </p>
                            </div>
                            <div className="flex shrink-0 items-center gap-2">
                              {cls.payment_type ? <ValueBadge kind="payment_type" value={cls.payment_type} /> : null}
                              <span className="tabular-nums text-brand-muted">{clp(cls.amount)}</span>
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : row.monthly_total > 0 ? (
                      <p className="text-xs text-brand-dim">Sueldo mensual fijo. Sin pagos por clase en el período.</p>
                    ) : null}
                  </div>
                ) : null}
              </div>
            )
          })
        )}

        {/* Gran total */}
        {!loading && rows.length > 0 ? (
          <div className="card-surface mt-1 grid grid-cols-[1fr_auto] items-center gap-3 border-brand-orange/30 bg-brand-orange/5 p-4 sm:grid-cols-[1.4fr_1fr_repeat(3,0.7fr)_auto]">
            <span className="font-semibold text-brand-white">Gran total</span>
            <span className="hidden text-sm text-brand-muted sm:block">-</span>
            <span className="hidden text-right text-sm tabular-nums text-brand-muted sm:block">{totals.classes}</span>
            <span className="hidden text-right text-sm tabular-nums text-brand-muted sm:block">{totals.attendees}</span>
            <span className="text-right font-display text-lg font-bold tabular-nums text-brand-orange sm:col-span-1">
              {clp(grandTotal)}
            </span>
            <span className="hidden w-5 sm:block" />
          </div>
        ) : null}
      </section>

      <FormModal
        open={Boolean(calculationPreview)}
        title={calculationPreview ? CALC_LABELS[calculationPreview.mode] || 'Calculo' : 'Calculo'}
        closeDisabled={calculationRunning}
        onClose={() => {
          if (!calculationRunning) {
            setCalculationPreview(null)
          }
        }}
      >
        {calculationPreview ? (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
              <StatTile label="Clases" value={calculationPreview.classes_count || 0} />
              <StatTile label="Crear" value={calculationPreview.records_created_count || 0} />
              <StatTile label="Actualizar" value={calculationPreview.records_updated_count || 0} />
              <StatTile label="Total" value={clp(calculationPreview.total_amount)} accent="text-brand-orange" />
            </div>
            <p className="text-sm text-brand-muted">
              Se aplicara sobre los periodos reales de {periodLabel(month)}. Los profesores ya pagados se saltan automaticamente.
            </p>
            {calculationPreview.skipped_paid_teachers_count ? (
              <p className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-100">
                {calculationPreview.skipped_paid_teachers_count} profesor(es) ya pagados no se tocaran.
              </p>
            ) : null}
            {calculationPreview.skipped_no_rule_count ? (
              <p className="rounded-lg border border-brand-line bg-black/20 px-3 py-2 text-sm text-brand-muted">
                {calculationPreview.skipped_no_rule_count} clase(s) siguen sin regla aplicable.
              </p>
            ) : null}
            <div className="flex items-center justify-end gap-2">
              <button
                type="button"
                disabled={calculationRunning}
                onClick={() => setCalculationPreview(null)}
                className="rounded border border-brand-line px-3 py-1.5 text-sm text-brand-muted transition hover:text-brand-white disabled:opacity-50"
              >
                Cerrar
              </button>
              <button
                type="button"
                disabled={calculationRunning || !calculationPreview.classes_count}
                onClick={runCalculation}
                className="rounded bg-brand-orange px-3 py-1.5 text-sm font-semibold text-black transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {calculationRunning ? 'Guardando...' : 'Confirmar'}
              </button>
            </div>
          </div>
        ) : null}
      </FormModal>

      <FormModal
        open={Boolean(voidingBatch)}
        title={voidingBatch ? `Anular calculo #${voidingBatch.id}` : 'Anular calculo'}
        closeDisabled={calculationRunning}
        onClose={() => {
          if (!calculationRunning) {
            setVoidingBatch(null)
            setVoidReason('')
          }
        }}
      >
        <form onSubmit={confirmVoidCalculation} className="space-y-3">
          <p className="text-sm text-brand-muted">
            Esto anula los pagos calculados por este lote. No se puede anular si algun profesor del lote ya fue pagado.
          </p>
          <label className="block space-y-1 text-sm">
            <span className="text-brand-muted">Motivo</span>
            <textarea
              value={voidReason}
              onChange={(event) => setVoidReason(event.target.value)}
              className="min-h-24 w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
              placeholder="Ej: regla asignada por error"
            />
          </label>
          <div className="flex items-center justify-end gap-2">
            <button
              type="button"
              disabled={calculationRunning}
              onClick={() => {
                setVoidingBatch(null)
                setVoidReason('')
              }}
              className="rounded border border-brand-line px-3 py-1.5 text-sm text-brand-muted transition hover:text-brand-white disabled:opacity-50"
            >
              Cerrar
            </button>
            <button
              type="submit"
              disabled={calculationRunning}
              className="rounded border border-amber-500/40 px-3 py-1.5 text-sm font-semibold text-amber-200 transition hover:bg-amber-500/10 disabled:opacity-50"
            >
              {calculationRunning ? 'Anulando...' : 'Anular'}
            </button>
          </div>
        </form>
      </FormModal>
    </div>
  )
}
