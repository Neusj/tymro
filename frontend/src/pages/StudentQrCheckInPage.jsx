import { Link, useSearchParams } from 'react-router-dom'
import AttendanceCheckInPanel from '../components/AttendanceCheckInPanel'

// Flujo por redirección: el alumno escanea el QR con la cámara nativa del teléfono,
// que lo trae aquí con el token en la URL. La validación/confirmación vive en el panel
// compartido (reutilizado también por el escáner in-app).
export default function StudentQrCheckInPage() {
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token') || ''

  return (
    <main className="min-h-screen bg-brand-black px-4 py-6 text-brand-white">
      <section className="mx-auto max-w-md space-y-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.3em] text-brand-orange">TYMRO</p>
          <h1 className="mt-2 text-2xl font-bold">Registrar asistencia</h1>
        </div>

        <AttendanceCheckInPanel token={token} />

        <Link to="/student/classes/reservations" className="block rounded-xl border border-brand-line px-4 py-3 text-center text-sm font-semibold text-brand-white">
          Ver mis reservas
        </Link>
      </section>
    </main>
  )
}
