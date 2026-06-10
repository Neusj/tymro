import { useCallback, useState } from 'react'
import { Link } from 'react-router-dom'
import QrCameraScanner from '../components/QrCameraScanner'
import AttendanceCheckInPanel from '../components/AttendanceCheckInPanel'

// Extrae el token del contenido del QR. El QR codifica una URL completa del tipo
// `https://.../attendance/check-in?token=<token>`; con fallback por si llegara sólo el token.
function extractToken(text) {
  if (!text) {
    return ''
  }
  try {
    const url = new URL(text)
    const token = url.searchParams.get('token')
    if (token) {
      return token
    }
  } catch {
    /* no es una URL: intentamos el fallback */
  }
  const match = text.match(/token=([^&\s]+)/)
  if (match) {
    return match[1]
  }
  // Si el contenido no parece una URL ni un token reconocible, no lo aceptamos.
  return ''
}

export default function StudentAttendanceScanPage() {
  const [scannedToken, setScannedToken] = useState('')
  const [invalid, setInvalid] = useState('')

  const handleDecode = useCallback((text) => {
    const token = extractToken(text)
    if (!token) {
      setInvalid('Ese código no es un QR de asistencia válido. Apunta al código de la pantalla.')
      // Reabrimos el escáner para que pueda volver a intentar.
      setScannedToken('')
      return
    }
    setInvalid('')
    setScannedToken(token)
  }, [])

  const rescan = useCallback(() => {
    setScannedToken('')
    setInvalid('')
  }, [])

  const scanning = !scannedToken

  return (
    <main className="px-4 py-6 text-brand-white">
      <section className="mx-auto max-w-md space-y-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.3em] text-brand-orange">Asistencia</p>
          <h1 className="mt-2 text-2xl font-bold">Marcar asistencia</h1>
          <p className="mt-1 text-sm text-brand-muted">
            Apunta la cámara al código QR que aparece en la pantalla del gimnasio.
          </p>
        </div>

        {scanning ? (
          <>
            <QrCameraScanner onDecode={handleDecode} paused={!scanning} />
            {invalid ? (
              <p className="rounded-xl border border-amber-400/40 bg-amber-400/10 p-4 text-sm text-amber-100">{invalid}</p>
            ) : null}
          </>
        ) : (
          <>
            <AttendanceCheckInPanel token={scannedToken} onRescan={rescan} />
            <button
              type="button"
              onClick={rescan}
              className="w-full rounded-xl border border-brand-line px-4 py-3 text-center text-sm font-semibold text-brand-white"
            >
              Escanear otro código
            </button>
          </>
        )}

        <Link to="/student/classes/reservations" className="block rounded-xl border border-brand-line px-4 py-3 text-center text-sm font-semibold text-brand-white">
          Ver mis reservas
        </Link>
      </section>
    </main>
  )
}
