import { useEffect, useMemo, useState } from 'react'
import QRCode from 'qrcode'
import { personalizedClassesApi } from '../api/client'
import DashboardHeader from '../components/DashboardHeader'

function formatSeconds(value) {
  const seconds = Math.max(0, Number(value || 0))
  const minutes = Math.floor(seconds / 60)
  const rest = seconds % 60
  if (minutes > 0) {
    return `${minutes}m ${rest}s`
  }
  return `${rest}s`
}

export default function TeacherPersonalizedClassPage() {
  const [qrData, setQrData] = useState(null)
  const [qrImage, setQrImage] = useState('')
  const [secondsLeft, setSecondsLeft] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const checkInUrl = useMemo(() => qrData?.check_in_url || '', [qrData])
  const session = qrData?.session
  const hasActiveQr = Boolean(checkInUrl && secondsLeft > 0)

  const generateQr = async () => {
    setLoading(true)
    setError('')
    setNotice('')
    try {
      const data = await personalizedClassesApi.createQr()
      const image = await QRCode.toDataURL(data.check_in_url, {
        margin: 1,
        width: 360,
        color: {
          dark: '#05070d',
          light: '#ffffff',
        },
      })
      setQrData(data)
      setQrImage(image)
      setSecondsLeft(Number(data.expires_in_seconds || 0))
      setNotice('QR listo para que el alumno lo escanee.')
    } catch (apiError) {
      setError(apiError?.response?.data?.detail || 'No se pudo iniciar la clase personalizada.')
      setQrData(null)
      setQrImage('')
      setSecondsLeft(0)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    const timer = window.setInterval(() => {
      setSecondsLeft((prev) => Math.max(0, prev - 1))
    }, 1000)
    return () => window.clearInterval(timer)
  }, [])

  return (
    <div className="space-y-6">
      <DashboardHeader title="Clase personalizada" subtitle="Genera un QR temporal para una sesión privada." />

      {error ? <p className="rounded-lg border border-brand-red/50 bg-brand-red/10 px-3 py-2 text-sm text-red-200">{error}</p> : null}
      {notice ? <p className="rounded-lg border border-brand-blue/40 bg-brand-blue/10 px-3 py-2 text-sm text-brand-white">{notice}</p> : null}

      <section className="card-surface mx-auto max-w-md p-5 text-center">
        <button
          type="button"
          onClick={generateQr}
          disabled={loading}
          className="w-full rounded-xl bg-brand-orange px-4 py-3 text-sm font-semibold text-brand-black transition hover:bg-amber-300 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {loading ? 'Generando...' : hasActiveQr ? 'Generar nuevo QR' : 'Generar QR'}
        </button>

        <div className="mt-5 flex aspect-square w-full items-center justify-center rounded-2xl border border-brand-line bg-white p-4">
          {qrImage ? (
            <img src={qrImage} alt="QR de clase personalizada" className="h-full w-full object-contain" />
          ) : (
            <span className="px-4 text-sm font-medium text-brand-black">Pulsa generar QR al iniciar la sesión.</span>
          )}
        </div>

        {qrImage ? (
          <div className="mt-4 space-y-3">
            <span className={`inline-flex rounded-full border px-3 py-1 text-sm font-semibold ${hasActiveQr ? 'border-emerald-500/40 text-emerald-200' : 'border-brand-red/40 text-red-200'}`}>
              {hasActiveQr ? `Vence en ${formatSeconds(secondsLeft)}` : 'QR vencido'}
            </span>
            <dl className="divide-y divide-brand-line text-left text-sm">
              <div className="flex justify-between gap-3 py-2">
                <dt className="text-brand-muted">Profesor</dt>
                <dd className="text-right font-medium">{session?.teacher || '-'}</dd>
              </div>
              <div className="flex justify-between gap-3 py-2">
                <dt className="text-brand-muted">Sesión</dt>
                <dd className="text-right font-medium">Clase personalizada</dd>
              </div>
            </dl>
            <p className="break-all text-xs text-brand-muted">{checkInUrl}</p>
          </div>
        ) : null}
      </section>
    </div>
  )
}
