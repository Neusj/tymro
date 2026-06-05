import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { attendanceQrApi } from '../api/client'
import ValueBadge from '../components/ui/ValueBadge'

function formatDateTime(value) {
  if (!value) {
    return '-'
  }
  return new Intl.DateTimeFormat('es-CL', {
    weekday: 'short',
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

export default function StudentQrCheckInPage() {
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token') || ''
  const [preview, setPreview] = useState(null)
  const [loading, setLoading] = useState(true)
  const [working, setWorking] = useState(false)
  const [error, setError] = useState('')

  const gymClass = preview?.class
  const nextClass = preview?.next_class
  const canMark = preview?.status === 'ready' && gymClass

  const statusMessage = useMemo(() => {
    if (!preview) {
      return ''
    }
    if (preview.detail) {
      return preview.detail
    }
    if (preview.status === 'ready') {
      return 'Confirma tu asistencia para esta clase.'
    }
    if (preview.status === 'registered') {
      return 'Tu asistencia fue registrada correctamente.'
    }
    return ''
  }, [preview])

  const loadPreview = async () => {
    if (!token) {
      setError('El enlace QR no incluye token.')
      setLoading(false)
      return
    }
    setError('')
    try {
      const data = await attendanceQrApi.preview(token)
      setPreview(data)
    } catch (apiError) {
      setError(apiError?.response?.data?.token || apiError?.response?.data?.detail || 'No se pudo validar el QR.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadPreview()
  }, [token])

  const markAttendance = async () => {
    setWorking(true)
    setError('')
    try {
      const data = await attendanceQrApi.checkIn(token)
      setPreview(data)
    } catch (apiError) {
      setError(apiError?.response?.data?.detail || apiError?.response?.data?.token || 'No se pudo registrar la asistencia.')
    } finally {
      setWorking(false)
    }
  }

  return (
    <main className="min-h-screen bg-brand-black px-4 py-6 text-brand-white">
      <section className="mx-auto max-w-md space-y-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.3em] text-brand-orange">TYMRO</p>
          <h1 className="mt-2 text-2xl font-bold">Registrar asistencia</h1>
        </div>

        {loading ? <p className="rounded-xl border border-brand-line bg-brand-soft p-4 text-sm text-brand-muted">Validando QR...</p> : null}
        {error ? <p className="rounded-xl border border-brand-red/50 bg-brand-red/10 p-4 text-sm text-red-200">{error}</p> : null}

        {!loading && statusMessage ? (
          <p className="rounded-xl border border-brand-line bg-brand-soft p-4 text-sm text-brand-muted">{statusMessage}</p>
        ) : null}

        {gymClass ? (
          <article className="rounded-2xl border border-brand-line bg-brand-soft p-5">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="text-xl font-semibold">{gymClass.name}</h2>
                <p className="mt-1 text-sm text-brand-muted">{gymClass.discipline || gymClass.class_type || '-'}</p>
              </div>
              {preview?.attendance_status ? <ValueBadge kind="attendance_status" value={preview.attendance_status} /> : null}
            </div>
            <dl className="mt-4 space-y-3 text-sm">
              <div className="flex justify-between gap-3">
                <dt className="text-brand-muted">Profesor</dt>
                <dd className="text-right font-medium">{gymClass.teacher || '-'}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-brand-muted">Hora</dt>
                <dd className="text-right font-medium">{formatDateTime(gymClass.start_datetime)}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-brand-muted">Sucursal</dt>
                <dd className="text-right font-medium">{gymClass.branch || '-'}</dd>
              </div>
            </dl>
            <button
              type="button"
              disabled={!canMark || working}
              onClick={markAttendance}
              className="mt-5 w-full rounded-xl bg-brand-blue px-4 py-3 text-sm font-semibold text-white disabled:opacity-60"
            >
              {working ? 'Registrando...' : preview?.status === 'registered' ? 'Asistencia registrada' : 'Marcar asistencia'}
            </button>
          </article>
        ) : null}

        {!gymClass && nextClass ? (
          <article className="rounded-2xl border border-brand-line bg-brand-soft p-5 text-sm">
            <p className="text-brand-muted">Tu próxima clase de hoy:</p>
            <p className="mt-2 font-semibold">{nextClass.name}</p>
            <p className="text-brand-muted">{formatDateTime(nextClass.start_datetime)}</p>
            {preview?.next_check_in_at ? <p className="mt-3 text-amber-200">Podrás marcar desde {formatDateTime(preview.next_check_in_at)}.</p> : null}
          </article>
        ) : null}

        <Link to="/student/classes/reservations" className="block rounded-xl border border-brand-line px-4 py-3 text-center text-sm font-semibold text-brand-white">
          Ver mis reservas
        </Link>
      </section>
    </main>
  )
}
