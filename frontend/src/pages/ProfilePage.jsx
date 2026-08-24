import { useEffect, useState } from 'react'
import { pushApi } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { browserNotificationPermission, disablePushNotifications, enablePushNotifications, isPushSupported } from '../pwa/pushNotifications'

function permissionLabel(value) {
  if (value === 'granted') return 'Permitidas en este navegador'
  if (value === 'denied') return 'Bloqueadas en este navegador'
  if (value === 'default') return 'Sin decidir en este navegador'
  return 'No disponibles en este navegador'
}

export default function ProfilePage() {
  const { user } = useAuth()
  const [preferences, setPreferences] = useState(null)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const supported = isPushSupported()

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        const data = await pushApi.getPreferences()
        if (!cancelled) setPreferences(data)
      } catch {
        if (!cancelled) setError('No se pudo cargar la configuracion de notificaciones.')
      }
    }
    if (user?.organization) load()
    return () => {
      cancelled = true
    }
  }, [user])

  const activate = async () => {
    setLoading(true)
    setMessage('')
    setError('')
    try {
      const result = await enablePushNotifications(preferences?.vapid_public_key)
      if (result.ok) {
        setPreferences(result.preferences)
        setMessage('Notificaciones activadas en este dispositivo.')
      } else if (result.reason === 'not_configured') {
        const data = await pushApi.getPreferences()
        setPreferences(data)
        setError('Las notificaciones todavia no estan configuradas en el servidor.')
      } else {
        const data = await pushApi.getPreferences()
        setPreferences(data)
        setError('No se activaron las notificaciones en este navegador.')
      }
    } catch {
      setError('No se pudieron activar las notificaciones.')
    } finally {
      setLoading(false)
    }
  }

  const deactivate = async () => {
    setLoading(true)
    setMessage('')
    setError('')
    try {
      await disablePushNotifications()
      const data = await pushApi.getPreferences()
      setPreferences(data)
      setMessage('Notificaciones desactivadas para este dispositivo.')
    } catch {
      setError('No se pudieron desactivar las notificaciones.')
    } finally {
      setLoading(false)
    }
  }

  const browserPermission = browserNotificationPermission()
  const activeCount = preferences?.active_subscriptions_count || 0
  const serverConfigured = Boolean(preferences?.vapid_public_key)
  const activationDisabled = loading || !supported || browserPermission === 'denied' || !serverConfigured

  return (
    <section className="max-w-3xl">
      <div className="mb-6">
        <h1 className="text-2xl font-display font-semibold text-brand-white">Perfil</h1>
        <p className="mt-1 text-sm text-brand-muted">{user?.email}</p>
      </div>

      <div className="rounded-lg border border-brand-line bg-brand-soft p-5">
        <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
          <div>
            <h2 className="text-lg font-semibold text-brand-white">Notificaciones push</h2>
            <dl className="mt-4 space-y-2 text-sm">
              <div className="flex gap-2">
                <dt className="w-36 shrink-0 text-brand-muted">Estado</dt>
                <dd className="text-brand-white">{preferences?.push_enabled ? 'Activadas' : 'Desactivadas'}</dd>
              </div>
              <div className="flex gap-2">
                <dt className="w-36 shrink-0 text-brand-muted">Dispositivos</dt>
                <dd className="text-brand-white">{activeCount}</dd>
              </div>
              <div className="flex gap-2">
                <dt className="w-36 shrink-0 text-brand-muted">Navegador</dt>
                <dd className="text-brand-white">{permissionLabel(browserPermission)}</dd>
              </div>
              <div className="flex gap-2">
                <dt className="w-36 shrink-0 text-brand-muted">Servidor</dt>
                <dd className="text-brand-white">{serverConfigured ? 'Configurado' : 'Configuracion pendiente'}</dd>
              </div>
            </dl>
            {preferences && !serverConfigured ? (
              <p className="mt-4 text-sm text-brand-muted">
                Falta configurar la llave VAPID de push en produccion.
              </p>
            ) : null}
            {message ? <p className="mt-4 text-sm text-emerald-300">{message}</p> : null}
            {error ? <p className="mt-4 text-sm text-brand-red">{error}</p> : null}
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={activate}
              disabled={activationDisabled}
              className="min-h-10 rounded-lg bg-brand-orange px-3 text-sm font-semibold text-brand-black transition hover:bg-brand-orange/90 disabled:opacity-60"
            >
              Activar
            </button>
            <button
              type="button"
              onClick={deactivate}
              disabled={loading || !supported || !preferences?.push_enabled}
              className="min-h-10 rounded-lg border border-brand-line px-3 text-sm font-medium text-brand-white transition hover:border-brand-red hover:text-brand-red disabled:opacity-60"
            >
              Desactivar
            </button>
          </div>
        </div>
      </div>
    </section>
  )
}
