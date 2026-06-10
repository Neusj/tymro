import { useEffect, useMemo, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import QRCode from 'qrcode'
import { attendanceQrApi } from '../api/client'

const FALLBACK_REFRESH_SECONDS = 10

export default function AttendanceScreenAutoPage() {
  const { code } = useParams()
  const [qrData, setQrData] = useState(null)
  const [qrImage, setQrImage] = useState('')
  const [secondsLeft, setSecondsLeft] = useState(FALLBACK_REFRESH_SECONDS)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const refreshRef = useRef(FALLBACK_REFRESH_SECONDS)

  const loadQr = async () => {
    try {
      const data = await attendanceQrApi.screenAuto(code)
      const image = await QRCode.toDataURL(data.check_in_url, {
        margin: 1,
        width: 560,
        color: { dark: '#05070d', light: '#ffffff' },
      })
      const refresh = Number(data.expires_in_seconds || FALLBACK_REFRESH_SECONDS)
      refreshRef.current = refresh
      setQrData(data)
      setQrImage(image)
      setSecondsLeft(refresh)
      setError('')
    } catch (apiError) {
      setError(
        apiError?.response?.data?.code ||
          apiError?.response?.data?.detail ||
          'No se pudo cargar la pantalla. Verifica el enlace.',
      )
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    setLoading(true)
    loadQr()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [code])

  useEffect(() => {
    const timer = window.setInterval(() => {
      setSecondsLeft((prev) => {
        if (prev <= 1) {
          loadQr()
          return refreshRef.current
        }
        return prev - 1
      })
    }, 1000)
    return () => window.clearInterval(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [code])

  const orgName = useMemo(() => qrData?.organization_name || '', [qrData])

  return (
    <main className="min-h-screen bg-brand-black px-4 py-6 text-brand-white sm:px-6">
      <section className="mx-auto flex min-h-[calc(100vh-3rem)] max-w-3xl flex-col justify-center gap-5">
        <div className="text-center">
          <p className="text-sm font-semibold uppercase tracking-[0.3em] text-brand-orange">TYMRO</p>
          <h1 className="mt-2 text-3xl font-semibold sm:text-4xl">Asistencia</h1>
          {orgName ? <p className="mt-1 text-base text-brand-muted">{orgName}</p> : null}
        </div>

        {loading ? (
          <div className="card-surface p-8 text-center text-sm text-brand-muted">Cargando pantalla…</div>
        ) : error ? (
          <div className="card-surface p-8 text-center">
            <h2 className="font-display text-xl font-semibold text-brand-white">No se pudo mostrar el QR</h2>
            <p className="mt-2 text-sm text-brand-muted">{error}</p>
            <button
              type="button"
              onClick={() => {
                setLoading(true)
                loadQr()
              }}
              className="mt-5 inline-flex min-h-11 items-center rounded-xl border border-brand-line px-4 py-2 text-sm font-semibold text-brand-white transition hover:border-brand-blue"
            >
              Reintentar
            </button>
          </div>
        ) : (
          <section className="card-surface p-5 text-center">
            <div className="mx-auto flex aspect-square w-full max-w-lg items-center justify-center rounded-2xl border border-brand-line bg-white p-4">
              {qrImage ? <img src={qrImage} alt="QR de asistencia" className="h-full w-full object-contain" /> : null}
            </div>
            <p className="mt-4 text-sm text-brand-muted">Escanea el código con tu cuenta para registrar tu asistencia.</p>
          </section>
        )}
      </section>
    </main>
  )
}
