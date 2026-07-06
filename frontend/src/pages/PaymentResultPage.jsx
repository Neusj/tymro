import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import DashboardHeader from '../components/DashboardHeader'
import { paymentsApi } from '../api/client'
import { clp, firstApiError } from '../utils/format'

const TERMINAL = new Set(['approved', 'rejected', 'cancelled', 'refunded'])
const MAX_POLLS = 8
const POLL_MS = 3000

// Estado normalizado del backend → presentación.
const STATUS_UI = {
  approved: { tone: 'success', title: '¡Pago aprobado!', message: 'Tu plan quedará activo en instantes.' },
  pending: { tone: 'pending', title: 'Pago en proceso', message: 'Estamos esperando la confirmación de MercadoPago. Esto puede tardar unos minutos.' },
  in_process: { tone: 'pending', title: 'Pago en proceso', message: 'MercadoPago está revisando tu pago. Te avisaremos apenas se confirme.' },
  rejected: { tone: 'error', title: 'Pago rechazado', message: 'Tu pago no se pudo procesar. No se realizó ningún cobro.' },
  cancelled: { tone: 'error', title: 'Pago cancelado', message: 'El pago fue cancelado antes de completarse.' },
  refunded: { tone: 'info', title: 'Pago reembolsado', message: 'Este pago fue reembolsado.' },
}

const TONE = {
  success: { ring: 'border-emerald-500/30 from-emerald-500/12', glow: 'bg-emerald-500/15', chip: 'bg-emerald-500/20 text-emerald-300' },
  pending: { ring: 'border-amber-500/30 from-amber-500/12', glow: 'bg-amber-500/15', chip: 'bg-amber-500/20 text-amber-200' },
  error: { ring: 'border-brand-red/40 from-brand-red/12', glow: 'bg-brand-red/15', chip: 'bg-brand-red/20 text-red-200' },
  info: { ring: 'border-brand-blue/30 from-brand-blue/12', glow: 'bg-brand-blue/15', chip: 'bg-brand-blue/20 text-blue-200' },
}

function ToneIcon({ tone }) {
  const common = { width: 24, height: 24, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 2.5, strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': true }
  if (tone === 'success') return <svg {...common}><path d="M20 6 9 17l-5-5" /></svg>
  if (tone === 'error') return <svg {...common}><path d="M18 6 6 18M6 6l12 12" /></svg>
  if (tone === 'info') return <svg {...common}><path d="M12 16v-4M12 8h.01" /><circle cx="12" cy="12" r="9" /></svg>
  return <svg {...common}><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></svg> // pending: reloj
}

export default function PaymentResultPage() {
  const [params] = useSearchParams()
  const tx = params.get('tx')
  const [txData, setTxData] = useState(null)
  const [loading, setLoading] = useState(true)   // solo la primera carga (card completa)
  const [error, setError] = useState('')
  const [polling, setPolling] = useState(false)  // hay un poll agendado (ventana de auto-verificación)
  const [refreshing, setRefreshing] = useState(false) // hay una consulta en curso (poll o manual)
  const timerRef = useRef(null)
  const pollsRef = useRef(0)
  const mountedRef = useRef(true)

  // mode: 'initial' (primera carga) | 'poll' (auto) | 'manual' (botón Actualizar)
  const fetchStatus = useCallback(async (mode = 'initial') => {
    if (!tx) return
    if (mode === 'initial') setLoading(true)
    else setRefreshing(true)
    setError('')
    try {
      const data = await paymentsApi.transactionStatus(tx)
      if (!mountedRef.current) return
      setTxData(data)
      if (!TERMINAL.has(data.status) && pollsRef.current < MAX_POLLS) {
        pollsRef.current += 1
        setPolling(true)
        timerRef.current = setTimeout(() => fetchStatus('poll'), POLL_MS)
      } else {
        setPolling(false)
      }
    } catch (apiError) {
      if (!mountedRef.current) return
      setPolling(false)
      if (apiError?.response?.status === 404) {
        setError('No encontramos este pago, o no te pertenece.')
      } else {
        setError(firstApiError(apiError?.response?.data, 'No se pudo consultar el estado del pago.'))
      }
    } finally {
      if (!mountedRef.current) return
      if (mode === 'initial') setLoading(false)
      else setRefreshing(false)
    }
  }, [tx])

  useEffect(() => {
    mountedRef.current = true
    if (!tx) { setLoading(false); return undefined }
    fetchStatus('initial')
    return () => {
      mountedRef.current = false
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [tx, fetchStatus])

  const handleRefresh = () => {
    if (timerRef.current) clearTimeout(timerRef.current)
    pollsRef.current = 0 // nueva ventana de polling
    fetchStatus('manual')
  }

  const ui = txData ? (STATUS_UI[txData.status] || { tone: 'info', title: 'Estado del pago', message: `Estado: ${txData.status}` }) : null
  const tone = ui ? TONE[ui.tone] : TONE.info

  return (
    <div className="space-y-6">
      <DashboardHeader title="Resultado del pago" subtitle="Estado de tu pago con MercadoPago." />

      <div className="mx-auto w-full max-w-lg">
        {loading ? (
          <div className="card-surface p-6 text-center text-sm text-brand-muted">Consultando el estado de tu pago…</div>
        ) : !tx || (error && !txData) ? (
          <section className="card-surface p-6 text-center">
            <p className="font-display text-lg font-semibold text-brand-white">
              {!tx ? 'No encontramos la referencia del pago' : 'No pudimos mostrar el pago'}
            </p>
            <p className="mt-2 text-sm text-brand-muted">{!tx ? 'El enlace no incluye una transacción válida.' : error}</p>
            <div className="mt-5 flex flex-wrap justify-center gap-3">
              <Link to="/student/plans" className="rounded-xl border border-brand-line px-4 py-2 text-sm font-semibold text-brand-white transition hover:border-brand-orange hover:bg-brand-soft">Ver mis planes</Link>
              <Link to="/student/plans/comprar" className="rounded-xl bg-brand-blue px-4 py-2 text-sm font-semibold text-white transition hover:brightness-110">Comprar plan</Link>
            </div>
          </section>
        ) : (
          <section className={`relative overflow-hidden rounded-2xl border bg-gradient-to-br via-brand-panel to-transparent p-6 shadow-soft ${tone.ring}`}>
            <div className={`pointer-events-none absolute -right-12 -top-12 h-40 w-40 rounded-full blur-3xl ${tone.glow}`} />
            <div className="relative text-center">
              <span className={`inline-flex h-14 w-14 items-center justify-center rounded-full ${tone.chip}`}>
                <ToneIcon tone={ui.tone} />
              </span>
              <h2 className="mt-4 font-display text-2xl font-bold text-brand-white">{ui.title}</h2>
              <p className="mt-2 text-sm text-brand-muted">{ui.message}</p>

              {txData?.amount != null ? (
                <p className="mt-4 font-display text-3xl font-bold text-brand-white tabular-nums">{clp(txData.amount)}</p>
              ) : null}
              {txData?.status === 'rejected' && txData?.status_detail ? (
                <p className="mt-2 text-xs text-red-200/80">Motivo: {txData.status_detail}</p>
              ) : null}

              {polling || refreshing ? (
                <p className="mt-4 inline-flex items-center gap-2 text-xs text-brand-muted">
                  <span className="h-2 w-2 animate-pulse rounded-full bg-amber-400" />
                  Verificando la confirmación…
                </p>
              ) : null}

              <div className="mt-6 flex flex-wrap justify-center gap-3">
                {txData?.status === 'approved' || txData?.status === 'refunded' ? (
                  <Link to="/student/plans" className="rounded-xl bg-brand-blue px-4 py-2 text-sm font-semibold text-white transition hover:brightness-110">Ver mis planes</Link>
                ) : null}
                {txData?.status === 'pending' || txData?.status === 'in_process' ? (
                  <>
                    <button type="button" onClick={handleRefresh} disabled={refreshing} className="rounded-xl bg-brand-blue px-4 py-2 text-sm font-semibold text-white transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-60">
                      {refreshing ? 'Verificando…' : 'Actualizar'}
                    </button>
                    <Link to="/student/plans" className="rounded-xl border border-brand-line px-4 py-2 text-sm font-semibold text-brand-white transition hover:border-brand-orange hover:bg-brand-soft">Ver mis planes</Link>
                  </>
                ) : null}
                {txData?.status === 'rejected' || txData?.status === 'cancelled' ? (
                  <Link to="/student/plans/comprar" className="rounded-xl bg-brand-blue px-4 py-2 text-sm font-semibold text-white transition hover:brightness-110">Volver a intentar</Link>
                ) : null}
              </div>

              {error && txData ? <p className="mt-4 text-xs text-red-200/80">{error}</p> : null}

              <p className="mt-6 border-t border-brand-line pt-4 text-xs text-brand-dim">
                La activación de tu plan la confirma MercadoPago mediante una notificación automática (webhook), no esta pantalla.
              </p>
            </div>
          </section>
        )}
      </div>
    </div>
  )
}
