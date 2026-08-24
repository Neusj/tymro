import { useEffect, useMemo, useState } from 'react'
import { pushApi } from '../api/client'
import { browserNotificationPermission, enablePushNotifications, isPushSupported } from '../pwa/pushNotifications'
import { useAuth } from '../auth/AuthContext'

const platformRoles = ['superadmin']

export default function PushPermissionPrompt() {
  const { user } = useAuth()
  const [preferences, setPreferences] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const supported = useMemo(() => isPushSupported(), [])

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      if (!user || platformRoles.includes(user.role) || !supported) {
        return
      }
      try {
        const data = await pushApi.getPreferences()
        if (!cancelled) {
          setPreferences(data)
          if (browserNotificationPermission() === 'denied' && data.prompt_status !== 'blocked') {
            await pushApi.updatePreferences({ prompt_status: 'blocked', push_enabled: false })
          }
        }
      } catch {
        if (!cancelled) setError('')
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [supported, user])

  if (!user || platformRoles.includes(user.role) || !supported || !preferences) {
    return null
  }
  if (preferences.push_enabled || preferences.prompt_status !== 'undecided') {
    return null
  }
  if (!preferences.vapid_public_key) {
    return null
  }
  if (browserNotificationPermission() === 'denied') {
    return null
  }

  const activate = async () => {
    setLoading(true)
    setError('')
    try {
      const result = await enablePushNotifications(preferences.vapid_public_key)
      if (result.ok) {
        setPreferences(result.preferences)
      } else if (result.reason === 'not_configured') {
        setError('Las notificaciones push no estan disponibles por ahora.')
      } else {
        const data = await pushApi.getPreferences()
        setPreferences(data)
      }
    } catch {
      setError('No se pudieron activar las notificaciones.')
    } finally {
      setLoading(false)
    }
  }

  const dismiss = async () => {
    setLoading(true)
    try {
      const data = await pushApi.updatePreferences({ prompt_status: 'dismissed' })
      setPreferences(data)
    } finally {
      setLoading(false)
    }
  }

  return (
    <section className="mb-4 rounded-lg border border-brand-line bg-brand-soft px-4 py-3 shadow-sm">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-brand-white">Activa las notificaciones</p>
          <p className="mt-1 text-sm text-brand-muted">
            Activa las notificaciones para enterarte de cancelaciones de clases y avisos importantes.
          </p>
          {error ? <p className="mt-2 text-xs text-brand-red">{error}</p> : null}
        </div>
        <div className="flex shrink-0 gap-2">
          <button
            type="button"
            onClick={dismiss}
            disabled={loading}
            className="min-h-10 rounded-lg border border-brand-line px-3 text-sm font-medium text-brand-muted transition hover:border-brand-muted hover:text-brand-white disabled:opacity-60"
          >
            Ahora no
          </button>
          <button
            type="button"
            onClick={activate}
            disabled={loading}
            className="min-h-10 rounded-lg bg-brand-orange px-3 text-sm font-semibold text-brand-black transition hover:bg-brand-orange/90 disabled:opacity-60"
          >
            {loading ? 'Activando...' : 'Activar notificaciones'}
          </button>
        </div>
      </div>
    </section>
  )
}
