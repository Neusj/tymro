import { useState } from 'react'
import { authApi } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { platformRoles } from '../utils/roles'
import { formatRut, toCanonical } from '../utils/rut'

// Alerta in-app para que el PROPIO usuario complete su RUT (self-service). El
// registro público no exige RUT: esta es la vía por la que el cliente carga sus
// datos (ej. antes de pagar un plan). Solo aparece para usuarios de organización
// sin RUT; los roles de plataforma (superadmin) no lo requieren.
export default function RutReminderBanner() {
  const { user, refreshMe } = useAuth()
  const [rut, setRut] = useState('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  if (!user || user.rut || platformRoles.includes(user.role)) {
    return null
  }

  const submit = async (event) => {
    event.preventDefault()
    const canonical = toCanonical(rut)
    if (!canonical) {
      setError('RUT inválido. Revisa el número y el dígito verificador.')
      return
    }
    setSaving(true)
    try {
      await authApi.updateMe({ rut: canonical })
      await refreshMe()
      setError('')
    } catch {
      setError('No se pudo guardar el RUT. Puede que ya esté registrado en tu gimnasio.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <form onSubmit={submit} className="mb-5 rounded-xl border border-brand-orange/50 bg-brand-orange/10 px-4 py-3">
      <p className="text-sm font-semibold text-brand-white">Completa tu RUT</p>
      <p className="mt-1 text-xs text-brand-muted">
        Necesitamos tu RUT para completar tu ficha y poder pagar planes. Es un dato tuyo: cárgalo aquí.
      </p>
      {error ? <p className="mt-2 text-xs text-red-200">{error}</p> : null}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <input
          value={rut}
          onChange={(event) => setRut(formatRut(event.target.value))}
          placeholder="12.345.678-5"
          aria-label="RUT"
          className="rounded-lg border border-brand-line bg-black/30 px-3 py-2 text-sm"
        />
        <button
          type="submit"
          disabled={saving}
          className="rounded-lg bg-brand-orange px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
        >
          {saving ? 'Guardando…' : 'Guardar RUT'}
        </button>
      </div>
    </form>
  )
}
