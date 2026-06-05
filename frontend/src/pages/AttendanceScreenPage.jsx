import { useEffect, useMemo, useState } from 'react'
import QRCode from 'qrcode'
import { attendanceQrApi } from '../api/client'

const FALLBACK_REFRESH_SECONDS = 10

export default function AttendanceScreenPage() {
  const [code, setCode] = useState('')
  const [activeCode, setActiveCode] = useState('')
  const [qrData, setQrData] = useState(null)
  const [qrImage, setQrImage] = useState('')
  const [secondsLeft, setSecondsLeft] = useState(FALLBACK_REFRESH_SECONDS)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [sessionExpired, setSessionExpired] = useState(false)

  const refreshSeconds = useMemo(
    () => Number(qrData?.expires_in_seconds || FALLBACK_REFRESH_SECONDS),
    [qrData],
  )

  const loadQr = async (targetCode = activeCode) => {
    const cleanCode = String(targetCode || '').trim()
    if (!cleanCode) {
      setError('Ingresa el codigo temporal de pantalla.')
      return
    }

    setLoading(true)
    setError('')
    setSessionExpired(false)
    try {
      const data = await attendanceQrApi.screen(cleanCode)
      const image = await QRCode.toDataURL(data.check_in_url, {
        margin: 1,
        width: 520,
        color: {
          dark: '#05070d',
          light: '#ffffff',
        },
      })
      setActiveCode(cleanCode)
      setQrData(data)
      setQrImage(image)
      setSecondsLeft(Number(data.expires_in_seconds || FALLBACK_REFRESH_SECONDS))
    } catch (apiError) {
      const message = apiError?.response?.data?.code || apiError?.response?.data?.detail || 'No se pudo validar el codigo temporal.'
      setQrData(null)
      setQrImage('')
      setSessionExpired(message === 'La sesión de pantalla expiró.')
      setError(message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (!activeCode) {
      return undefined
    }

    const timer = window.setInterval(() => {
      setSecondsLeft((prev) => {
        if (prev <= 1) {
          loadQr(activeCode)
          return refreshSeconds
        }
        return prev - 1
      })
    }, 1000)
    return () => window.clearInterval(timer)
  }, [activeCode, refreshSeconds])

  return (
    <main className="min-h-screen bg-brand-black px-4 py-6 text-brand-white sm:px-6">
      <section className="mx-auto flex min-h-[calc(100vh-3rem)] max-w-3xl flex-col justify-center gap-5">
        <div>
          <p className="text-sm font-semibold uppercase tracking-wide text-brand-orange">TYMRO</p>
          <h1 className="mt-2 text-3xl font-semibold sm:text-4xl">Pantalla de Asistencia</h1>
        </div>

        {!qrData ? (
          <form
            className="card-surface space-y-4 p-5"
            onSubmit={(event) => {
              event.preventDefault()
              loadQr(code)
            }}
          >
            <label className="block text-sm font-semibold text-brand-muted" htmlFor="attendance-screen-code">
              Codigo temporal de pantalla
            </label>
            <input
              id="attendance-screen-code"
              value={code}
              onChange={(event) => setCode(event.target.value.toUpperCase())}
              className="w-full rounded-xl border border-brand-line bg-black/40 px-4 py-3 text-lg font-semibold tracking-widest text-brand-white outline-none transition focus:border-brand-blue"
              placeholder="X7P92K"
              autoComplete="off"
            />
            {error ? <p className={`text-sm ${sessionExpired ? 'text-amber-200' : 'text-red-200'}`}>{error}</p> : null}
            <button
              type="submit"
              disabled={loading}
              className="w-full rounded-xl bg-brand-orange px-4 py-3 text-sm font-semibold text-brand-black transition hover:bg-amber-300 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {loading ? 'Validando...' : 'Mostrar QR'}
            </button>
          </form>
        ) : (
          <section className="card-surface p-5 text-center">
            <p className="text-base font-semibold text-brand-muted">{qrData.organization_name}</p>
            <div className="mx-auto mt-4 flex aspect-square w-full max-w-lg items-center justify-center rounded-2xl border border-brand-line bg-white p-4">
              {qrImage ? <img src={qrImage} alt="QR de asistencia" className="h-full w-full object-contain" /> : null}
            </div>
            <div className="mt-4 flex flex-wrap items-center justify-center gap-3">
              <span className="rounded-full border border-brand-orange/40 px-3 py-1 text-sm font-semibold text-amber-200">
                Cambia en {secondsLeft}s
              </span>
              <button
                type="button"
                onClick={() => loadQr(activeCode)}
                className="rounded-xl border border-brand-line px-4 py-2 text-sm font-semibold text-brand-white transition hover:border-brand-blue"
              >
                Actualizar
              </button>
              <button
                type="button"
                onClick={() => {
                  setQrData(null)
                  setQrImage('')
                  setActiveCode('')
                  setSessionExpired(false)
                }}
                className="rounded-xl border border-brand-line px-4 py-2 text-sm font-semibold text-brand-muted transition hover:border-brand-blue hover:text-brand-white"
              >
                Cambiar codigo
              </button>
            </div>
            {error ? <p className="mt-3 text-sm text-red-200">{error}</p> : null}
          </section>
        )}
      </section>
    </main>
  )
}
