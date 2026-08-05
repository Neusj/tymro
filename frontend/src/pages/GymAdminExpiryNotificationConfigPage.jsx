import { useEffect, useState } from 'react'
import DashboardHeader from '../components/DashboardHeader'
import { expiryNotificationConfigApi } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { firstApiError } from '../utils/format'

const MIN_DAY = 1
const MAX_DAY = 365
const MAX_VALUES = 10

// Configura CUÁNDO se avisa que una membresía está por vencer (R5). La MISMA lista de
// días (`reminder_days_before`) maneja dos canales: el correo que manda el backend Y
// el banner que ve el alumno al entrar a "Clases disponibles"
// (show_expiry_banner en /api/plans/my-memberships/ — ver
// components/MembershipExpiryBanner.jsx). No hay configs separadas por canal.
export default function GymAdminExpiryNotificationConfigPage() {
  const { user } = useAuth()
  const orgId = user?.organization

  const [days, setDays] = useState([])
  const [sendExpiredNotice, setSendExpiredNotice] = useState(false)
  const [newDay, setNewDay] = useState('')
  const [dayError, setDayError] = useState('')
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
        const data = await expiryNotificationConfigApi.get(orgId)
        if (!active) return
        setDays(Array.isArray(data.reminder_days_before) ? data.reminder_days_before : [])
        setSendExpiredNotice(Boolean(data.send_expired_notice))
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

  const addDay = () => {
    const value = Number(newDay)
    if (!Number.isInteger(value) || value < MIN_DAY || value > MAX_DAY) {
      setDayError(`Ingresa un número entero entre ${MIN_DAY} y ${MAX_DAY}.`)
      return
    }
    if (days.includes(value)) {
      setDayError('Ese valor ya está en la lista.')
      return
    }
    if (days.length >= MAX_VALUES) {
      setDayError(`Máximo ${MAX_VALUES} valores.`)
      return
    }
    setDayError('')
    setDays((prev) => [...prev, value].sort((a, b) => b - a))
    setNewDay('')
  }

  const removeDay = (value) => {
    setDays((prev) => prev.filter((item) => item !== value))
  }

  const submit = async (event) => {
    event.preventDefault()
    setSaving(true)
    setError('')
    setSuccess('')
    try {
      const data = await expiryNotificationConfigApi.update(orgId, {
        reminder_days_before: days,
        send_expired_notice: sendExpiredNotice,
      })
      setDays(Array.isArray(data.reminder_days_before) ? data.reminder_days_before : days)
      setSendExpiredNotice(Boolean(data.send_expired_notice))
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
        title="Gym Admin · Configuraciones"
        subtitle="Define con cuántos días de anticipación se avisa que una membresía está por vencer."
        back={{ to: '/gym-admin/dashboard', label: 'Dashboard' }}
      />

      <section className="card-surface p-5">
        {loading ? (
          <p className="text-sm text-brand-muted">Cargando configuración…</p>
        ) : (
          <form onSubmit={submit} className="space-y-5">
            <div className="space-y-2">
              <span className="block text-sm font-semibold">Avisar con cuántos días de anticipación</span>
              <p className="text-xs text-brand-muted">
                Estos días controlan el correo de aviso Y el banner que ve el alumno al entrar a
                &quot;Clases disponibles&quot;: es la misma configuración para ambos canales.
              </p>

              <div className="flex flex-wrap gap-2">
                {days.length === 0 ? (
                  <span className="text-xs text-brand-muted">Sin días configurados todavía.</span>
                ) : (
                  days.map((value) => (
                    <span
                      key={value}
                      className="inline-flex items-center gap-2 rounded-full border border-brand-line bg-black/30 px-3 py-1 text-sm"
                    >
                      {value} días
                      <button
                        type="button"
                        onClick={() => removeDay(value)}
                        aria-label={`Quitar ${value} días`}
                        className="text-brand-muted hover:text-red-200"
                      >
                        ×
                      </button>
                    </span>
                  ))
                )}
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <input
                  type="number"
                  min={MIN_DAY}
                  max={MAX_DAY}
                  value={newDay}
                  onChange={(event) => setNewDay(event.target.value)}
                  placeholder="Ej: 10"
                  aria-label="Días de anticipación a agregar"
                  className="w-28 rounded-lg border border-brand-line bg-black/30 px-3 py-2 text-sm"
                />
                <button
                  type="button"
                  onClick={addDay}
                  disabled={days.length >= MAX_VALUES}
                  className="rounded-lg border border-brand-line px-3 py-2 text-xs font-semibold text-brand-white disabled:opacity-60"
                >
                  Agregar
                </button>
                <span className="text-xs text-brand-muted">{days.length}/{MAX_VALUES}</span>
              </div>
              {dayError ? <p className="text-xs text-red-200">{dayError}</p> : null}
            </div>

            <label className="flex items-center gap-3 text-sm">
              <input
                type="checkbox"
                checked={sendExpiredNotice}
                onChange={(event) => setSendExpiredNotice(event.target.checked)}
                className="h-4 w-4 rounded border-brand-line bg-black/30"
              />
              <span>Avisar también cuando la membresía YA venció (no solo antes)</span>
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
