import { useEffect, useState } from 'react'
import DashboardHeader from '../components/DashboardHeader'
import { trialFollowupConfigApi } from '../api/client'
import { useAuth } from '../auth/AuthContext'

const emptyConfig = {
  is_enabled: true,
  delay_minutes: 30,
  email_subject: '',
  email_body: '',
}

// Configura el email de seguimiento que se envía tras una clase de prueba.
// El backend expone is_enabled / delay_minutes / email_subject / email_body.
export default function GymAdminTrialFollowupPage() {
  const { user } = useAuth()
  const orgId = user?.organization

  const [form, setForm] = useState(emptyConfig)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
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
        const data = await trialFollowupConfigApi.get(orgId)
        if (!active) return
        setForm({
          is_enabled: data.is_enabled,
          delay_minutes: data.delay_minutes,
          email_subject: data.email_subject,
          email_body: data.email_body,
        })
      } catch (apiError) {
        if (!active) return
        const detail = apiError?.response?.data
        setError(detail?.detail || 'No se pudo cargar la configuración.')
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
      const payload = {
        is_enabled: form.is_enabled,
        delay_minutes: Number(form.delay_minutes),
        email_subject: form.email_subject,
        email_body: form.email_body,
      }
      const data = await trialFollowupConfigApi.update(orgId, payload)
      setForm({
        is_enabled: data.is_enabled,
        delay_minutes: data.delay_minutes,
        email_subject: data.email_subject,
        email_body: data.email_body,
      })
      setSuccess('Configuración guardada correctamente.')
    } catch (apiError) {
      const detail = apiError?.response?.data
      const firstFieldError = detail && typeof detail === 'object' ? Object.values(detail)?.[0] : null
      setError(
        detail?.detail ||
          (Array.isArray(firstFieldError) ? firstFieldError[0] : firstFieldError) ||
          'No se pudo guardar la configuración.',
      )
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-6">
      <DashboardHeader
        title="Gym Admin · Configuraciones"
        subtitle="Personaliza el email de seguimiento que se envía tras una clase de prueba."
        back={{ to: '/gym-admin/dashboard', label: 'Dashboard' }}
      />

      <section className="card-surface p-5">
        {loading ? (
          <p className="text-sm text-brand-muted">Cargando configuración…</p>
        ) : (
          <form onSubmit={submit} className="space-y-4">
            <label className="flex items-center gap-3 text-sm">
              <input
                type="checkbox"
                checked={form.is_enabled}
                onChange={(event) => setForm((prev) => ({ ...prev, is_enabled: event.target.checked }))}
                className="h-4 w-4 rounded border-brand-line bg-black/30"
              />
              <span>¿Enviar emails de seguimiento de clases de prueba?</span>
            </label>

            <label className="block max-w-xs space-y-1 text-sm">
              <span>Delay en minutos tras el fin de la clase</span>
              <input
                type="number"
                min="0"
                value={form.delay_minutes}
                onChange={(event) => setForm((prev) => ({ ...prev, delay_minutes: event.target.value }))}
                className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
              />
            </label>

            <label className="block space-y-1 text-sm">
              <span>Asunto del email</span>
              <input
                type="text"
                value={form.email_subject}
                onChange={(event) => setForm((prev) => ({ ...prev, email_subject: event.target.value }))}
                className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
              />
              <span className="block text-xs text-brand-muted">Variables: {'{org_name}'}, {'{student_name}'}</span>
            </label>

            <label className="block space-y-1 text-sm">
              <span>Cuerpo del email</span>
              <textarea
                rows={8}
                value={form.email_body}
                onChange={(event) => setForm((prev) => ({ ...prev, email_body: event.target.value }))}
                className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
              />
              <span className="block text-xs text-brand-muted">
                Variables: {'{org_name}'}, {'{student_name}'}, {'{class_name}'}, {'{teacher_name}'}, {'{signup_link}'}
              </span>
            </label>

            <div className="flex justify-end">
              <button
                type="submit"
                disabled={saving}
                className="rounded-xl bg-brand-blue px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
              >
                {saving ? 'Guardando…' : 'Guardar'}
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
