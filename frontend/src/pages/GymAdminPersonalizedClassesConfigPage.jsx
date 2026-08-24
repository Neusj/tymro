import { useEffect, useState } from 'react'
import { organizationsApi } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import DashboardHeader from '../components/DashboardHeader'
import { firstApiError } from '../utils/format'

export default function GymAdminPersonalizedClassesConfigPage() {
  const { user, refreshMe } = useAuth()
  const orgId = user?.organization

  const [enabled, setEnabled] = useState(false)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  useEffect(() => {
    let active = true
    const load = async () => {
      if (!orgId) {
        setError('No se pudo determinar tu organizacion.')
        setLoading(false)
        return
      }
      setLoading(true)
      setError('')
      try {
        const data = await organizationsApi.retrieve(orgId)
        if (!active) return
        setEnabled(Boolean(data?.personalized_classes_enabled))
      } catch (apiError) {
        if (!active) return
        setError(firstApiError(apiError?.response?.data, 'No se pudo cargar la configuracion.'))
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
    setSaving(true)
    setError('')
    setSuccess('')
    try {
      const data = await organizationsApi.setPersonalizedClasses(orgId, enabled)
      setEnabled(Boolean(data?.personalized_classes_enabled))
      await refreshMe()
      setSuccess('Configuracion guardada correctamente.')
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudo guardar la configuracion.'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-6">
      <DashboardHeader
        title="Gym Admin - Configuraciones"
        subtitle="Activa el flujo de clases personalizadas para profesores y alumnos."
        back={{ to: '/gym-admin/dashboard', label: 'Dashboard' }}
      />

      <section className="card-surface p-5">
        {loading ? (
          <p className="text-sm text-brand-muted">Cargando configuracion...</p>
        ) : (
          <form onSubmit={submit} className="space-y-5">
            <label className="flex items-start gap-3 rounded-xl border border-brand-line bg-black/20 p-4 text-sm">
              <input
                type="checkbox"
                checked={enabled}
                onChange={(event) => setEnabled(event.target.checked)}
                className="mt-1 h-4 w-4 shrink-0"
              />
              <span>
                <span className="block font-semibold text-brand-white">Habilitar clases personalizadas</span>
                <span className="mt-1 block text-xs text-brand-muted">
                  Muestra el menu Clases personalizadas a profesores y alumnos, y permite registrar sesiones por QR usando planes de tipo Clases personalizadas.
                </span>
              </span>
            </label>

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
