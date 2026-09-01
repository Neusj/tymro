import { useEffect, useState } from 'react'
import DashboardHeader from '../components/DashboardHeader'
import { trialWindowConfigApi } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { firstApiError } from '../utils/format'

export default function GymAdminTrialWindowConfigPage() {
  const { user } = useAuth()
  const orgId = user?.organization

  const [value, setValue] = useState('7')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [fieldError, setFieldError] = useState('')
  const [success, setSuccess] = useState('')

  useEffect(() => {
    let active = true
    const load = async () => {
      if (!orgId) {
        setError('No se pudo determinar tu organización.')
        setLoading(false)
        return
      }
      setLoading(true)
      setError('')
      try {
        const data = await trialWindowConfigApi.get(orgId)
        if (!active) return
        setValue(String(data?.trial_validity_days ?? 7))
      } catch (apiError) {
        if (!active) return
        setError(firstApiError(apiError?.response?.data, 'No se pudo cargar la configuración.'))
      } finally {
        if (active) setLoading(false)
      }
    }
    load()
    return () => {
      active = false
    }
  }, [orgId])

  const submit = async (event) => {
    event.preventDefault()
    const numericValue = Number(value)
    if (!Number.isInteger(numericValue) || numericValue < 1 || numericValue > 366) {
      setFieldError('Ingresa un número entero entre 1 y 366.')
      return
    }
    setFieldError('')
    setSaving(true)
    setError('')
    setSuccess('')
    try {
      const data = await trialWindowConfigApi.update(orgId, {
        trial_validity_days: numericValue,
      })
      setValue(String(data?.trial_validity_days ?? numericValue))
      setSuccess('Configuración guardada correctamente.')
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudo guardar la configuración.'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-6">
      <DashboardHeader
        title="Gym Admin · Ventana de prueba"
        subtitle="Define cuántos días hacia adelante se ofrecen clases para alumnos nuevos."
        back={{ to: '/gym-admin/dashboard', label: 'Dashboard' }}
      />

      <section className="card-surface p-5">
        {loading ? (
          <p className="text-sm text-brand-muted">Cargando configuración...</p>
        ) : (
          <form onSubmit={submit} noValidate className="space-y-5">
            <div className="space-y-2">
              <label className="block text-sm font-semibold" htmlFor="trial-validity-days">
                Días disponibles para reservar prueba
              </label>
              <p className="text-xs text-brand-muted">
                La vista de clase de prueba solo mostrará horarios dentro de esta ventana.
              </p>
              <div className="flex items-center gap-3">
                <input
                  id="trial-validity-days"
                  type="number"
                  step="1"
                  min="1"
                  max="366"
                  value={value}
                  onChange={(event) => setValue(event.target.value)}
                  className="w-32 rounded-lg border border-brand-line bg-black/30 px-3 py-2 text-sm"
                />
                <span className="text-sm text-brand-muted">días</span>
              </div>
              {fieldError ? <p className="text-xs text-red-200">{fieldError}</p> : null}
            </div>

            <div className="flex justify-end">
              <button
                type="submit"
                disabled={saving}
                className="rounded-xl bg-brand-blue px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
              >
                {saving ? 'Guardando...' : 'Guardar'}
              </button>
            </div>
          </form>
        )}

        {error ? (
          <p className="mt-3 rounded-lg border border-brand-red/50 bg-brand-red/10 px-3 py-2 text-sm text-red-200">{error}</p>
        ) : null}
        {success ? (
          <p className="mt-3 rounded-lg border border-success/50 bg-success/10 px-3 py-2 text-sm text-emerald-200">{success}</p>
        ) : null}
      </section>
    </div>
  )
}
