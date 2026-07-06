import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { registrationApi } from '../api/client'

// Back-compat: los links viejos /{slug}/clase-gratis (servidos en el apex) se
// redirigen al subdominio de la organización, donde vive el registro por subdominio.
export default function TrialLinkRedirect() {
  const { slug } = useParams()
  const [invalid, setInvalid] = useState(false)

  useEffect(() => {
    let active = true
    const go = async () => {
      try {
        const data = await registrationApi.validateInvite({ slug })
        if (data?.public_registration_url) {
          window.location.replace(data.public_registration_url)
        } else if (active) {
          setInvalid(true)
        }
      } catch {
        if (active) setInvalid(true)
      }
    }
    go()
    return () => {
      active = false
    }
  }, [slug])

  if (invalid) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-brand-black p-4 text-center">
        <div className="w-full max-w-md rounded-3xl border border-brand-line bg-brand-soft/95 p-8">
          <h1 className="font-display text-2xl font-bold">Link inválido o expirado</h1>
          <p className="mt-3 text-sm text-brand-muted">Pídele al gimnasio el link actualizado.</p>
          <Link
            to="/login"
            className="mt-6 inline-flex min-h-11 items-center rounded-xl border border-brand-line px-4 py-2 text-sm font-semibold text-brand-white"
          >
            Ir a iniciar sesión
          </Link>
        </div>
      </div>
    )
  }
  return (
    <div className="flex min-h-screen items-center justify-center bg-brand-black text-brand-muted">
      Redirigiéndote al gimnasio…
    </div>
  )
}
