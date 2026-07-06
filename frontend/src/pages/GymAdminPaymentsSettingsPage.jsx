import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import DashboardHeader from '../components/DashboardHeader'
import { paymentsApi } from '../api/client'
import { firstApiError } from '../utils/format'

// Fecha larga es-CL (ej. "5 de julio de 2026, 14:30").
function formatDateTime(value) {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString('es-CL', {
    day: 'numeric', month: 'long', year: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

// Banner que devuelve el callback OAuth del backend vía query params.
function bannerFromQuery(connected, error) {
  if (connected === '1') {
    return { kind: 'notice', text: 'Cuenta de MercadoPago conectada correctamente.' }
  }
  if (connected === '0') {
    if (error === 'state') {
      return { kind: 'error', text: 'El enlace de conexión expiró o no es válido. Vuelve a intentarlo.' }
    }
    if (error === 'exchange') {
      return { kind: 'error', text: 'No se pudo completar la conexión con MercadoPago. Inténtalo de nuevo.' }
    }
    return { kind: 'error', text: 'No se pudo conectar la cuenta de MercadoPago.' }
  }
  return null
}

function MpCheck() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M20 6 9 17l-5-5" />
    </svg>
  )
}

export default function GymAdminPaymentsSettingsPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [account, setAccount] = useState(null)
  const [loading, setLoading] = useState(true)
  const [connecting, setConnecting] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  // 1) Procesar el resultado del callback OAuth (?connected=1|0&error=...) y limpiar la URL.
  useEffect(() => {
    const banner = bannerFromQuery(searchParams.get('connected'), searchParams.get('error'))
    if (!banner) return
    if (banner.kind === 'notice') setNotice(banner.text)
    else setError(banner.text)
    // Quita los params para que un refresh no repita el banner.
    const next = new URLSearchParams(searchParams)
    next.delete('connected')
    next.delete('error')
    setSearchParams(next, { replace: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 2) Cargar el estado de la conexión.
  useEffect(() => {
    let active = true
    const load = async () => {
      setLoading(true)
      try {
        const data = await paymentsApi.getAccount()
        if (active) setAccount(data)
      } catch (apiError) {
        if (active) setError(firstApiError(apiError?.response?.data, 'No se pudo cargar el estado de la conexión.'))
      } finally {
        if (active) setLoading(false)
      }
    }
    load()
    return () => { active = false }
  }, [])

  const connected = account?.status === 'connected'

  const handleConnect = async () => {
    setConnecting(true)
    setError('')
    try {
      const { authorization_url: url } = await paymentsApi.connect()
      if (!url) throw new Error('sin url')
      // Redirige a MercadoPago para autorizar la cuenta del gimnasio.
      window.location.assign(url)
    } catch (apiError) {
      setConnecting(false)
      setError(firstApiError(apiError?.response?.data, 'No se pudo iniciar la conexión con MercadoPago.'))
    }
    // Si el assign tiene éxito no reseteamos connecting: la página se descarga.
  }

  return (
    <div className="space-y-6">
      <DashboardHeader
        title="Pagos con MercadoPago"
        subtitle="Conecta la cuenta de MercadoPago de tu gimnasio para cobrar planes en línea. El dinero va directo a tu cuenta; TYMRO no participa del cobro."
        back={{ to: '/gym-admin/dashboard', label: 'Dashboard' }}
      />

      {error ? <p className="rounded-lg border border-brand-red/50 bg-brand-red/10 px-3 py-2 text-sm text-red-200">{error}</p> : null}
      {notice ? <p className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-200">{notice}</p> : null}

      {loading ? (
        <div className="card-surface p-6 text-center text-sm text-brand-muted">Cargando estado de la conexión…</div>
      ) : connected ? (
        <section className="relative overflow-hidden rounded-2xl border border-emerald-500/30 bg-gradient-to-br from-emerald-500/12 via-brand-panel to-brand-blue/10 p-5 shadow-soft sm:p-6">
          <div className="pointer-events-none absolute -right-12 -top-12 h-40 w-40 rounded-full bg-emerald-500/15 blur-3xl" />
          <div className="relative">
            <div className="flex items-center gap-2">
              <span className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-emerald-500/20 text-emerald-300">
                <MpCheck />
              </span>
              <div>
                <h2 className="panel-title">Cuenta conectada</h2>
                <p className="text-sm text-brand-muted">Tu gimnasio ya puede recibir pagos por MercadoPago.</p>
              </div>
              {account?.is_sandbox ? (
                <span className="ml-auto inline-flex items-center gap-1 rounded-full border border-amber-500/40 bg-amber-500/10 px-2.5 py-0.5 text-[11px] font-semibold text-amber-200">
                  Modo prueba
                </span>
              ) : null}
            </div>

            <dl className="mt-5 grid gap-3 sm:grid-cols-3">
              <div className="rounded-xl border border-brand-line bg-black/25 p-3">
                <dt className="text-[11px] uppercase tracking-wide text-brand-dim">Cuenta cobradora</dt>
                <dd className="mt-1 font-display text-sm font-semibold text-brand-white break-all">{account?.provider_user_id || '—'}</dd>
              </div>
              <div className="rounded-xl border border-brand-line bg-black/25 p-3">
                <dt className="text-[11px] uppercase tracking-wide text-brand-dim">Conectada el</dt>
                <dd className="mt-1 text-sm font-semibold text-brand-white">{formatDateTime(account?.connected_at)}</dd>
              </div>
              <div className="rounded-xl border border-brand-line bg-black/25 p-3">
                <dt className="text-[11px] uppercase tracking-wide text-brand-dim">Token válido hasta</dt>
                <dd className="mt-1 text-sm font-semibold text-brand-white">{formatDateTime(account?.token_expires_at)}</dd>
              </div>
            </dl>

            <div className="mt-5 flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={handleConnect}
                disabled={connecting}
                className="rounded-xl border border-brand-line bg-transparent px-4 py-2 text-sm font-semibold text-brand-white transition hover:border-brand-orange hover:bg-brand-soft disabled:cursor-not-allowed disabled:opacity-60"
              >
                {connecting ? 'Redirigiendo…' : 'Reconectar cuenta'}
              </button>
              <p className="text-xs text-brand-muted">El token se renueva solo; reconecta únicamente si aparece un error de cobro.</p>
            </div>
          </div>
        </section>
      ) : (
        <section className="card-surface p-5 sm:p-6">
          <h2 className="panel-title">Aún no conectas MercadoPago</h2>
          <p className="mt-2 max-w-2xl text-sm text-brand-muted">
            Al conectar, tus alumnos podrán comprar y renovar planes en línea con tarjeta, débito o
            transferencia. Los pagos llegan directamente a la cuenta de MercadoPago de tu gimnasio.
          </p>
          <ul className="mt-4 space-y-2 text-sm text-brand-muted">
            <li className="flex items-start gap-2"><span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-brand-orange" />Necesitas una cuenta de MercadoPago (o una cuenta de prueba para el sandbox).</li>
            <li className="flex items-start gap-2"><span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-brand-orange" />Se abrirá MercadoPago para que autorices a TYMRO a crear cobros a tu nombre.</li>
            <li className="flex items-start gap-2"><span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-brand-orange" />La activación del plan del alumno se confirma automáticamente tras el pago.</li>
          </ul>
          <div className="mt-6">
            <button
              type="button"
              onClick={handleConnect}
              disabled={connecting}
              className="inline-flex min-h-11 items-center justify-center gap-2 rounded-xl bg-[#00b1ea] px-5 py-2.5 text-sm font-semibold text-white shadow-soft transition hover:brightness-110 active:brightness-95 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {connecting ? 'Redirigiendo a MercadoPago…' : 'Conectar con MercadoPago'}
            </button>
          </div>
        </section>
      )}
    </div>
  )
}
