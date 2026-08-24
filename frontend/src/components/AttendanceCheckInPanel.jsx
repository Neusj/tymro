import { useEffect, useMemo, useState } from 'react'
import { attendanceQrApi } from '../api/client'
import ValueBadge from './ui/ValueBadge'

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

// Panel de previsualización + confirmación de asistencia a partir de un token de QR.
// Es agnóstico de cómo se obtuvo el token: lo usa tanto la página de redirección
// (token en la URL) como el escáner in-app (token leído de la cámara).
// `onRescan`, si se provee, muestra un botón para volver a escanear (reabrir cámara).
export default function AttendanceCheckInPanel({ token, onRescan }) {
  const [preview, setPreview] = useState(null)
  const [loading, setLoading] = useState(true)
  const [working, setWorking] = useState(false)
  const [error, setError] = useState('')
  // Mensaje calmado para cuando el token del QR ya rotó: no es un error del alumno,
  // solo debe volver a escanear el código vigente de la pantalla.
  const [rescanHint, setRescanHint] = useState('')
  // Permiso de un solo uso emitido por el preview; con él se confirma la asistencia
  // (en vez del token del QR), así no puede vencerse entre ver la clase y confirmar.
  const [grant, setGrant] = useState('')

  const gymClass = preview?.class
  const nextClass = preview?.next_class
  const isPersonalized = gymClass?.kind === 'personalized'
  const canMark = preview?.status === 'ready' && gymClass && Boolean(grant)

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
      return isPersonalized ? 'Clase personalizada registrada correctamente.' : 'Tu asistencia fue registrada correctamente.'
    }
    return ''
  }, [preview, isPersonalized])

  const loadPreview = async () => {
    if (!token) {
      setRescanHint('Vuelve a escanear el código de la pantalla para continuar.')
      setLoading(false)
      return
    }
    setLoading(true)
    setError('')
    setRescanHint('')
    try {
      const data = await attendanceQrApi.preview(token)
      setPreview(data)
      setGrant(data?.checkin_grant || '')
    } catch (apiError) {
      const data = apiError?.response?.data
      setGrant('')
      // El campo `token` lo devuelve el backend cuando el QR ya rotó o es inválido.
      // No lo mostramos como error rojo: pedimos reescanear con un mensaje calmado.
      if (data?.token) {
        setRescanHint('Vuelve a escanear el código de la pantalla para continuar.')
      } else {
        setError(data?.detail || 'No se pudo validar el QR.')
      }
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadPreview()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token])

  const markAttendance = async () => {
    if (!grant) {
      setError('No se pudo registrar la asistencia.')
      return
    }
    setWorking(true)
    setError('')
    try {
      // Confirmamos con el grant emitido en el preview; el token del QR ya no interviene,
      // así que aquí NO mostramos el mensaje de reescaneo.
      const data = await attendanceQrApi.checkIn(grant)
      setPreview(data)
      setGrant('')
    } catch (apiError) {
      const data = apiError?.response?.data
      setError(data?.detail || data?.grant || 'No se pudo registrar la asistencia.')
    } finally {
      setWorking(false)
    }
  }

  return (
    <div className="space-y-4">
      {loading ? <p className="rounded-xl border border-brand-line bg-brand-soft p-4 text-sm text-brand-muted">Validando QR...</p> : null}
      {error ? <p className="rounded-xl border border-brand-red/50 bg-brand-red/10 p-4 text-sm text-red-200">{error}</p> : null}
      {!loading && rescanHint ? (
        <div className="rounded-xl border border-amber-400/40 bg-amber-400/10 p-4 text-sm text-amber-100">
          <p className="font-medium">{rescanHint}</p>
          {onRescan ? (
            <button
              type="button"
              onClick={onRescan}
              className="mt-3 rounded-lg border border-amber-300/50 px-3 py-2 text-xs font-semibold text-amber-100"
            >
              Escanear de nuevo
            </button>
          ) : (
            <button
              type="button"
              onClick={loadPreview}
              className="mt-3 rounded-lg border border-amber-300/50 px-3 py-2 text-xs font-semibold text-amber-100"
            >
              Reintentar
            </button>
          )}
        </div>
      ) : null}

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
            {isPersonalized ? (
              <>
                <div className="flex justify-between gap-3">
                  <dt className="text-brand-muted">Plan</dt>
                  <dd className="text-right font-medium">{gymClass.student_plan_name || '-'}</dd>
                </div>
                <div className="flex justify-between gap-3">
                  <dt className="text-brand-muted">Sesiones restantes</dt>
                  <dd className="text-right font-medium">
                    {gymClass.remaining_classes === null || gymClass.remaining_classes === undefined ? 'Ilimitado' : gymClass.remaining_classes}
                  </dd>
                </div>
              </>
            ) : null}
          </dl>
          <button
            type="button"
            disabled={!canMark || working}
            onClick={markAttendance}
            className="mt-5 w-full rounded-xl bg-brand-blue px-4 py-3 text-sm font-semibold text-white disabled:opacity-60"
          >
            {working ? 'Registrando...' : preview?.status === 'registered' ? 'Registrado' : isPersonalized ? 'Registrar clase personalizada' : 'Marcar asistencia'}
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
    </div>
  )
}
