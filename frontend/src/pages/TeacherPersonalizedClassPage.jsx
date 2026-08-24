import { useCallback, useEffect, useMemo, useState } from 'react'
import QRCode from 'qrcode'
import { personalizedClassesApi } from '../api/client'
import DashboardHeader from '../components/DashboardHeader'
import EmptyState from '../components/EmptyState'
import FormModal from '../components/FormModal'
import { firstApiError, formatDate } from '../utils/format'

function formatSeconds(value) {
  const seconds = Math.max(0, Number(value || 0))
  const minutes = Math.floor(seconds / 60)
  const rest = seconds % 60
  if (minutes > 0) {
    return `${minutes}m ${rest}s`
  }
  return `${rest}s`
}

function formatDateTime(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return `${formatDate(value)} ${date.toLocaleTimeString('es-CL', { hour: '2-digit', minute: '2-digit' })}`
}

function isPendingQrActive(item) {
  if (item?.status !== 'pending' || !item?.qr_expires_at) return false
  return new Date(item.qr_expires_at).getTime() > Date.now()
}

function statusBadge(item) {
  if (item.status === 'finished') {
    return { text: 'Dictada', className: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200' }
  }
  if (item.status === 'confirmed') {
    return { text: 'En curso', className: 'border-brand-orange/50 bg-brand-orange/10 text-amber-200' }
  }
  if (isPendingQrActive(item)) {
    return { text: 'QR activo', className: 'border-brand-blue/50 bg-brand-blue/10 text-blue-100' }
  }
  return { text: 'QR vencido', className: 'border-brand-line bg-brand-soft text-brand-muted' }
}

function SessionCard({ item, onFinish, finishingId }) {
  const badge = statusBadge(item)
  return (
    <article className="rounded-xl border border-brand-line bg-brand-soft/80 p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-semibold text-brand-white">Clase personalizada</h3>
            <span className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${badge.className}`}>
              {badge.text}
            </span>
          </div>
          <dl className="mt-3 grid gap-2 text-sm text-brand-muted sm:grid-cols-2">
            <div>
              <dt className="text-xs uppercase tracking-wide text-brand-muted/80">Alumno</dt>
              <dd className="font-medium text-brand-white">{item.student || 'Esperando alumno'}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wide text-brand-muted/80">Profesor</dt>
              <dd className="font-medium text-brand-white">{item.teacher || '-'}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wide text-brand-muted/80">Inicio</dt>
              <dd>{formatDateTime(item.confirmed_at || item.qr_issued_at)}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wide text-brand-muted/80">Fin</dt>
              <dd>{formatDateTime(item.finished_at)}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wide text-brand-muted/80">Plan</dt>
              <dd>{item.student_plan_name || '-'}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wide text-brand-muted/80">Sede</dt>
              <dd>{item.branch || '-'}</dd>
            </div>
          </dl>
        </div>
        {item.can_finish && item.status === 'confirmed' ? (
          <button
            type="button"
            onClick={() => onFinish(item.id)}
            disabled={finishingId === item.id}
            className="inline-flex min-h-10 shrink-0 items-center justify-center rounded-lg bg-brand-orange px-4 py-2 text-sm font-semibold text-brand-black transition hover:bg-amber-300 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {finishingId === item.id ? 'Finalizando...' : 'Finalizar clase'}
          </button>
        ) : null}
      </div>
    </article>
  )
}

export default function TeacherPersonalizedClassPage() {
  const [sessions, setSessions] = useState([])
  const [qrData, setQrData] = useState(null)
  const [qrImage, setQrImage] = useState('')
  const [secondsLeft, setSecondsLeft] = useState(0)
  const [loading, setLoading] = useState(true)
  const [starting, setStarting] = useState(false)
  const [finishingId, setFinishingId] = useState(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [modalOpen, setModalOpen] = useState(false)

  const loadSessions = useCallback(async () => {
    try {
      const data = await personalizedClassesApi.list()
      setSessions(Array.isArray(data) ? data : [])
      setError('')
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudieron cargar las clases personalizadas.'))
    } finally {
      setLoading(false)
    }
  }, [])

  const startClass = async () => {
    setStarting(true)
    setError('')
    setNotice('')
    try {
      const data = await personalizedClassesApi.createQr()
      const image = await QRCode.toDataURL(data.check_in_url, {
        margin: 1,
        width: 360,
        color: { dark: '#05070d', light: '#ffffff' },
      })
      setQrData(data)
      setQrImage(image)
      setSecondsLeft(Number(data.expires_in_seconds || 0))
      setModalOpen(true)
      setNotice('QR listo. Cuando el alumno lo escanee, la clase quedara en curso.')
      await loadSessions()
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudo comenzar la clase personalizada.'))
      setQrData(null)
      setQrImage('')
      setSecondsLeft(0)
    } finally {
      setStarting(false)
    }
  }

  const finishClass = async (sessionId) => {
    setFinishingId(sessionId)
    setError('')
    setNotice('')
    try {
      await personalizedClassesApi.finish(sessionId)
      setNotice('Clase personalizada finalizada.')
      await loadSessions()
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudo finalizar la clase personalizada.'))
    } finally {
      setFinishingId(null)
    }
  }

  useEffect(() => {
    loadSessions()
  }, [loadSessions])

  useEffect(() => {
    const timer = window.setInterval(() => {
      setSecondsLeft((prev) => Math.max(0, prev - 1))
    }, 1000)
    return () => window.clearInterval(timer)
  }, [])

  useEffect(() => {
    if (!modalOpen) return undefined
    const poll = window.setInterval(loadSessions, 5000)
    return () => window.clearInterval(poll)
  }, [loadSessions, modalOpen])

  const currentSessions = useMemo(
    () => sessions.filter((item) => item.status === 'confirmed' || item.status === 'pending'),
    [sessions],
  )
  const finishedSessions = useMemo(
    () => sessions.filter((item) => item.status === 'finished'),
    [sessions],
  )
  const hasActiveQr = Boolean(qrData?.check_in_url && secondsLeft > 0)

  return (
    <div className="space-y-6">
      <DashboardHeader
        title="Clases personalizadas"
        subtitle="Gestiona sesiones privadas sin horario fijo y deja registro cuando se dictan."
        extra={(
          <button
            type="button"
            onClick={startClass}
            disabled={starting}
            className="inline-flex min-h-11 items-center justify-center rounded-lg bg-brand-orange px-4 py-2 text-sm font-semibold text-brand-black transition hover:bg-amber-300 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {starting ? 'Comenzando...' : 'Comenzar clase'}
          </button>
        )}
      />

      {error ? <p className="rounded-lg border border-brand-red/50 bg-brand-red/10 px-3 py-2 text-sm text-red-200">{error}</p> : null}
      {notice ? <p className="rounded-lg border border-brand-blue/40 bg-brand-blue/10 px-3 py-2 text-sm text-brand-white">{notice}</p> : null}

      <section className="space-y-3">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-lg font-semibold text-brand-white">En curso</h2>
          <button type="button" onClick={loadSessions} className="text-sm font-medium text-brand-orange hover:text-amber-300">
            Actualizar
          </button>
        </div>
        {loading ? <p className="text-sm text-brand-muted">Cargando clases...</p> : null}
        {!loading && currentSessions.length === 0 ? (
          <EmptyState title="Sin clases en curso" description="Usa Comenzar clase para abrir un QR de 3 minutos." />
        ) : (
          <div className="grid gap-3">
            {currentSessions.map((item) => (
              <SessionCard key={item.id} item={item} onFinish={finishClass} finishingId={finishingId} />
            ))}
          </div>
        )}
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-brand-white">Dictadas</h2>
        {!loading && finishedSessions.length === 0 ? (
          <EmptyState title="Sin clases dictadas" description="Las clases finalizadas quedan registradas aqui." />
        ) : (
          <div className="grid gap-3">
            {finishedSessions.map((item) => (
              <SessionCard key={item.id} item={item} onFinish={finishClass} finishingId={finishingId} />
            ))}
          </div>
        )}
      </section>

      <FormModal open={modalOpen} title="QR de clase personalizada" onClose={() => setModalOpen(false)}>
        <div className="space-y-4 text-center">
          <div className="mx-auto flex aspect-square w-full max-w-sm items-center justify-center rounded-xl border border-brand-line bg-white p-4">
            {qrImage ? (
              <img src={qrImage} alt="QR de clase personalizada" className="h-full w-full object-contain" />
            ) : (
              <span className="px-4 text-sm font-medium text-brand-black">Generando QR...</span>
            )}
          </div>
          <span className={`inline-flex rounded-full border px-3 py-1 text-sm font-semibold ${hasActiveQr ? 'border-emerald-500/40 text-emerald-200' : 'border-brand-red/40 text-red-200'}`}>
            {hasActiveQr ? `Vence en ${formatSeconds(secondsLeft)}` : 'QR vencido'}
          </span>
          <p className="text-sm text-brand-muted">
            El alumno escanea este QR para dejar la clase en curso. Luego finalizala desde la lista.
          </p>
        </div>
      </FormModal>
    </div>
  )
}
