import { useEffect, useMemo, useState } from 'react'
import QRCode from 'qrcode'
import { attendanceQrApi } from '../api/client'
import DashboardHeader from '../components/DashboardHeader'

const REFRESH_SECONDS = 10

function formatDuration(totalSeconds) {
  const safeSeconds = Math.max(0, Number(totalSeconds || 0))
  const hours = Math.floor(safeSeconds / 3600)
  const minutes = Math.floor((safeSeconds % 3600) / 60)
  const seconds = safeSeconds % 60
  if (hours > 0) {
    return `${hours}h ${minutes}m`
  }
  if (minutes > 0) {
    return `${minutes}m ${seconds}s`
  }
  return `${seconds}s`
}

export default function GymAdminAttendanceQrPage() {
  const [qrData, setQrData] = useState(null)
  const [qrImage, setQrImage] = useState('')
  const [secondsLeft, setSecondsLeft] = useState(REFRESH_SECONDS)
  const [sessionSecondsLeft, setSessionSecondsLeft] = useState(0)
  const [loading, setLoading] = useState(true)
  const [startingSession, setStartingSession] = useState(false)
  const [regeneratingPermanent, setRegeneratingPermanent] = useState(false)
  const [copyMessage, setCopyMessage] = useState('')
  const [error, setError] = useState('')

  const displayUrl = useMemo(() => qrData?.check_in_url || '', [qrData])
  const attendanceScreenUrl = useMemo(() => qrData?.attendance_screen_url || `${window.location.origin}/attendance/screen`, [qrData])
  const hasActiveSession = Boolean(qrData?.attendance_screen_session_code && sessionSecondsLeft > 0)

  const mergeQrData = (data) => {
    setQrData((prev) => ({ ...(prev || {}), ...data }))
    setSessionSecondsLeft(Number(data.attendance_screen_session_expires_in_seconds || 0))
  }

  const loadQr = async () => {
    setError('')
    try {
      const data = await attendanceQrApi.current()
      mergeQrData(data)
      setSecondsLeft(Number(data.expires_in_seconds || REFRESH_SECONDS))
      const image = await QRCode.toDataURL(data.check_in_url, {
        margin: 1,
        width: 360,
        color: {
          dark: '#05070d',
          light: '#ffffff',
        },
      })
      setQrImage(image)
    } catch (apiError) {
      setError(apiError?.response?.data?.detail || 'No se pudo generar el QR de asistencia.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadQr()
  }, [])

  useEffect(() => {
    const timer = window.setInterval(() => {
      setSecondsLeft((prev) => {
        if (prev <= 1) {
          loadQr()
          return REFRESH_SECONDS
        }
        return prev - 1
      })
    }, 1000)
    return () => window.clearInterval(timer)
  }, [])

  useEffect(() => {
    const timer = window.setInterval(() => {
      setSessionSecondsLeft((prev) => Math.max(0, prev - 1))
    }, 1000)
    return () => window.clearInterval(timer)
  }, [])

  const copyText = async (value, message) => {
    try {
      await navigator.clipboard.writeText(value)
      setCopyMessage(message)
      window.setTimeout(() => setCopyMessage(''), 1800)
    } catch {
      setError('No se pudo copiar al portapapeles.')
    }
  }

  const startScreenSession = async () => {
    setStartingSession(true)
    setError('')
    try {
      const data = await attendanceQrApi.startScreenSession()
      mergeQrData(data)
      setCopyMessage('Sesion temporal iniciada.')
      window.setTimeout(() => setCopyMessage(''), 1800)
    } catch (apiError) {
      setError(apiError?.response?.data?.detail || 'No se pudo iniciar la pantalla de recepcion.')
    } finally {
      setStartingSession(false)
    }
  }

  const regeneratePermanentCode = async () => {
    setRegeneratingPermanent(true)
    setError('')
    try {
      const data = await attendanceQrApi.regenerateScreenCode()
      mergeQrData(data)
      setCopyMessage('Codigo permanente regenerado.')
      window.setTimeout(() => setCopyMessage(''), 1800)
    } catch (apiError) {
      setError(apiError?.response?.data?.detail || 'No se pudo regenerar el codigo permanente.')
    } finally {
      setRegeneratingPermanent(false)
    }
  }

  return (
    <div className="space-y-6">
      <DashboardHeader title="QR de asistencia" subtitle="Codigo dinamico para recepcion del gimnasio." />

      {error ? <p className="rounded-lg border border-brand-red/50 bg-brand-red/10 px-3 py-2 text-sm text-red-200">{error}</p> : null}
      {copyMessage ? <p className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-200">{copyMessage}</p> : null}

      <section className="card-surface mx-auto max-w-xl p-5 text-center">
        <div className="mx-auto flex aspect-square w-full max-w-sm items-center justify-center rounded-2xl border border-brand-line bg-white p-4">
          {loading ? <span className="text-sm text-brand-black">Generando QR...</span> : null}
          {!loading && qrImage ? <img src={qrImage} alt="QR de asistencia" className="h-full w-full object-contain" /> : null}
        </div>

        <div className="mt-4 flex items-center justify-center gap-2">
          <span className="rounded-full border border-brand-orange/40 px-3 py-1 text-sm font-semibold text-amber-200">
            Cambia en {secondsLeft}s
          </span>
          <button
            type="button"
            onClick={loadQr}
            className="rounded-xl border border-brand-line px-4 py-2 text-sm font-semibold text-brand-white transition hover:border-brand-blue"
          >
            Actualizar
          </button>
        </div>

        {displayUrl ? <p className="mt-4 break-all text-xs text-brand-muted">{displayUrl}</p> : null}
      </section>

      <section className="card-surface mx-auto max-w-xl p-5">
        <h2 className="panel-title">Pantalla publica de recepcion</h2>
        <p className="mt-2 text-sm text-brand-muted">
          Abre el enlace en una TV, tablet o computador compartido. La recepcion debe ingresar el codigo temporal.
        </p>

        <div className="mt-4 rounded-xl border border-brand-line bg-black/20 p-4">
          <p className="text-xs font-semibold uppercase tracking-wide text-brand-muted">Codigo permanente del gimnasio</p>
          <div className="mt-2 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <span className="break-all font-mono text-xl font-semibold tracking-widest text-brand-white">
              {qrData?.attendance_screen_code || '-'}
            </span>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => copyText(qrData?.attendance_screen_code || '', 'Codigo permanente copiado.')}
                disabled={!qrData?.attendance_screen_code}
                className="rounded-xl border border-brand-line px-3 py-2 text-sm font-semibold text-brand-white transition hover:border-brand-blue disabled:cursor-not-allowed disabled:opacity-50"
              >
                Copiar codigo
              </button>
              <button
                type="button"
                onClick={regeneratePermanentCode}
                disabled={regeneratingPermanent}
                className="rounded-xl border border-brand-line px-3 py-2 text-sm font-semibold text-brand-muted transition hover:border-brand-blue hover:text-brand-white disabled:cursor-not-allowed disabled:opacity-50"
              >
                {regeneratingPermanent ? 'Regenerando...' : 'Regenerar permanente'}
              </button>
            </div>
          </div>
        </div>

        <div className="mt-4 rounded-xl border border-brand-line bg-black/20 p-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-brand-muted">Codigo temporal de pantalla</p>
              <p className="mt-2 font-mono text-2xl font-semibold tracking-widest text-brand-white">
                {qrData?.attendance_screen_session_code || '-'}
              </p>
              <p className={`mt-1 text-sm ${hasActiveSession ? 'text-emerald-200' : 'text-brand-muted'}`}>
                {hasActiveSession ? `Tiempo restante: ${formatDuration(sessionSecondsLeft)}` : 'Sin sesion activa'}
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={startScreenSession}
                disabled={startingSession}
                className="rounded-xl bg-brand-orange px-3 py-2 text-sm font-semibold text-brand-black transition hover:bg-amber-300 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {startingSession ? 'Iniciando...' : 'Iniciar pantalla de recepcion'}
              </button>
              <button
                type="button"
                onClick={() => copyText(qrData?.attendance_screen_session_code || '', 'Codigo temporal copiado.')}
                disabled={!qrData?.attendance_screen_session_code}
                className="rounded-xl border border-brand-line px-3 py-2 text-sm font-semibold text-brand-white transition hover:border-brand-blue disabled:cursor-not-allowed disabled:opacity-50"
              >
                Copiar temporal
              </button>
            </div>
          </div>
        </div>

        <div className="mt-4 rounded-xl border border-brand-line bg-black/20 p-4">
          <p className="text-xs font-semibold uppercase tracking-wide text-brand-muted">Enlace publico</p>
          <p className="mt-2 break-all text-sm text-brand-white">{attendanceScreenUrl}</p>
          <button
            type="button"
            onClick={() => copyText(attendanceScreenUrl, 'Enlace copiado.')}
            className="mt-3 rounded-xl border border-brand-line px-3 py-2 text-sm font-semibold text-brand-white transition hover:border-brand-blue"
          >
            Copiar enlace
          </button>
        </div>
      </section>
    </div>
  )
}
