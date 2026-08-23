import { useEffect, useState } from 'react'
import DashboardHeader from '../components/DashboardHeader'
import { attendanceEditConfigApi } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { firstApiError } from '../utils/format'

export default function GymAdminAttendanceEditConfigPage() {
  const { user } = useAuth()
  const orgId = user?.organization

  const [value, setValue] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [fieldError, setFieldError] = useState('')
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
        const data = await attendanceEditConfigApi.get(orgId)
        if (!active) return
        setValue(String(data?.teacher_attendance_edit_limit_minutes ?? ''))
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
    const numericValue = Number(value)
    if (!Number.isInteger(numericValue) || numericValue < 0 || numericValue > 1440) {
      setFieldError('Ingresa un numero entero entre 0 y 1440.')
      return
    }
    setFieldError('')
    setSaving(true)
    setError('')
    setSuccess('')
    try {
      const data = await attendanceEditConfigApi.update(orgId, {
        teacher_attendance_edit_limit_minutes: numericValue,
      })
      setValue(String(data?.teacher_attendance_edit_limit_minutes ?? numericValue))
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
        subtitle="Define cuanto tiempo tiene un profesor para editar asistencia luego de terminada una clase."
        back={{ to: '/gym-admin/dashboard', label: 'Dashboard' }}
      />

      <section className="card-surface p-5">
        {loading ? (
          <p className="text-sm text-brand-muted">Cargando configuracion...</p>
        ) : (
          <form onSubmit={submit} noValidate className="space-y-5">
            <div className="space-y-2">
              <label className="block text-sm font-semibold" htmlFor="teacher-attendance-edit-limit-minutes">
                Tiempo limite para editar asistencia como profesor
              </label>
              <p className="text-xs text-brand-muted">
                Los administradores pueden editar la asistencia en cualquier momento.
              </p>
              <div className="flex items-center gap-3">
                <input
                  id="teacher-attendance-edit-limit-minutes"
                  type="number"
                  step="1"
                  min="0"
                  max="1440"
                  value={value}
                  onChange={(event) => setValue(event.target.value)}
                  className="w-32 rounded-lg border border-brand-line bg-black/30 px-3 py-2 text-sm"
                />
                <span className="text-sm text-brand-muted">minutos</span>
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
