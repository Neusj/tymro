import { useEffect, useState } from 'react'
import { teacherPaymentsApi } from '../api/client'
import DashboardHeader from '../components/DashboardHeader'
import ValueBadge from '../components/ui/ValueBadge'
import PayoutStatus from '../components/ui/PayoutStatus'

const MONTH_NAMES = [
  'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
  'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre',
]

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

export default function TeacherPaymentsPage() {
  const [month, setMonth] = useState(currentMonthValue())
  const [classKind, setClassKind] = useState('all')
  const [row, setRow] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [exporting, setExporting] = useState('')

  const loadSummary = async () => {
    setLoading(true)
    setError('')
    try {
      // El backend auto-scopea summary al teacher_id del usuario: rows trae a lo más su propia fila.
      const params = { ...monthToRange(month) }
      if (classKind !== 'all') {
        params.class_kind = classKind
      }
      const data = await teacherPaymentsApi.summary(params)
      const myRow = Array.isArray(data?.rows) ? data.rows[0] || null : null
      setRow(myRow)
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudieron cargar tus pagos.'))
      setRow(null)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadSummary()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [month, classKind])

  const handleExport = async (format) => {
    setExporting(format)
    setError('')
    try {
      // exportSummary usa el mismo scope: el profe sólo exporta lo suyo.
      const params = { ...monthToRange(month), fmt: format }
      if (classKind !== 'all') {
        params.class_kind = classKind
      }
      const response = await teacherPaymentsApi.exportSummary(params)
      const blob = new Blob([response.data], { type: response.headers['content-type'] })
      const url = window.URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `mis_pagos_${month}.${format === 'xlsx' ? 'xlsx' : 'csv'}`
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
    } catch {
      setError('No se pudo exportar tus pagos.')
    } finally {
      setExporting('')
    }
  }

  const total = row?.total || 0
  const modalities = row?.modalities || []
  const classes = row?.classes || []
  const exportDisabled = loading || !row || Boolean(exporting)

  return (
    <div className="space-y-5">
      <DashboardHeader
        title="Mis pagos"
        subtitle="Lo que ganas en el período, calculado desde tus clases dictadas y la asistencia real."
      />

      {error ? (
        <p className="rounded-lg border border-danger-line bg-danger-soft px-3 py-2 text-sm text-red-200">{error}</p>
      ) : null}

      {/* Controles de período + export */}
      <section className="card-surface space-y-4 p-4 sm:p-5">
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

          <div className="flex items-center gap-2">
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
      </section>

      {/* Hero: total del período + métricas */}
      <section className="relative overflow-hidden rounded-2xl border border-brand-hairline bg-gradient-to-br from-brand-orange/15 via-brand-panel to-brand-blue/10 p-5 shadow-soft">
        <div className="pointer-events-none absolute -right-12 -top-12 h-40 w-40 rounded-full bg-brand-orange/15 blur-3xl" />
        <div className="relative">
          <p className="text-[11px] uppercase tracking-[0.18em] text-brand-dim">Total del período · {periodLabel(month)}</p>
          <p className="mt-1 font-display text-4xl font-bold leading-none text-brand-white sm:text-5xl">
            {clp(total)}
          </p>

          {/* Estado de pago del período */}
          {!loading && row ? (
            <div className="mt-2">
              <PayoutStatus payout={row.payout} pending={row.pending} />
            </div>
          ) : null}

          {/* Modalidades */}
          <div className="mt-3 flex flex-wrap gap-1">
            {modalities.length === 0 ? (
              <span className="text-xs text-brand-dim">Sin modalidad asignada</span>
            ) : (
              modalities.map((code) => <ValueBadge key={code} kind="payment_type" value={code} />)
            )}
          </div>

          <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-2">
            <StatTile label="Clases" value={row?.classes_count || 0} accent="text-brand-orange" />
            <StatTile label="Asistentes" value={row?.attendees_total || 0} />
          </div>
        </div>
      </section>

      {loading ? (
        <div className="card-surface p-6 text-center text-sm text-brand-muted">Cargando tus pagos…</div>
      ) : !row ? (
        <div className="card-surface p-6 text-center text-sm text-brand-muted">
          No tienes pagos registrados en este período.
        </div>
      ) : (
        <>
          {/* Desglose sueldo base + por clase = total */}
          <section className="card-surface space-y-3 p-4 sm:p-5">
            <p className="text-[11px] uppercase tracking-wide text-brand-dim">Desglose</p>
            <div className="grid grid-cols-3 gap-2 text-sm">
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
          </section>

          {/* Detalle de clases */}
          <section className="card-surface space-y-2 p-4 sm:p-5">
            <p className="text-[11px] uppercase tracking-wide text-brand-dim">Clases del período</p>
            {classes.length > 0 ? (
              <div className="space-y-1.5">
                {classes.map((cls) => (
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
            ) : (
              <p className="text-xs text-brand-dim">No hay clases registradas en el período.</p>
            )}
          </section>
        </>
      )}
    </div>
  )
}
