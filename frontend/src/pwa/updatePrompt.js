let registration = null
let updateServiceWorker = null

const listeners = new Set()
const state = {
  needRefresh: false,
  updating: false,
}

const emit = () => {
  listeners.forEach((listener) => listener({ ...state }))
}

export const getUpdateState = () => ({ ...state })

export const subscribeToPwaUpdates = (listener) => {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export const setPwaRegistration = (nextRegistration) => {
  registration = nextRegistration || null
}

export const setPwaUpdateHandler = (handler) => {
  updateServiceWorker = handler
}

export const markPwaUpdateReady = () => {
  state.needRefresh = true
  emit()
}

export const checkForPwaUpdate = async () => {
  if (!registration || typeof registration.update !== 'function') {
    return
  }
  try {
    await registration.update()
  } catch (error) {
    if (import.meta.env.DEV) {
      console.warn('[PWA] No se pudo comprobar una actualización:', error)
    }
  }
}

const cacheBustedUrl = () => {
  const url = new URL(window.location.href)
  url.searchParams.set('tymro_refresh', String(Date.now()))
  return url.toString()
}

export const hardReloadPwa = async () => {
  if (typeof window === 'undefined') {
    return
  }

  try {
    if ('caches' in window) {
      const names = await window.caches.keys()
      await Promise.all(names.map((name) => window.caches.delete(name)))
    }
  } catch (error) {
    if (import.meta.env.DEV) {
      console.warn('[PWA] No se pudieron limpiar las caches:', error)
    }
  }

  try {
    if ('serviceWorker' in navigator && typeof navigator.serviceWorker.getRegistrations === 'function') {
      const registrations = await navigator.serviceWorker.getRegistrations()
      await Promise.all(registrations.map((item) => item.unregister()))
    }
  } catch (error) {
    if (import.meta.env.DEV) {
      console.warn('[PWA] No se pudieron desregistrar service workers:', error)
    }
  }

  window.location.replace(cacheBustedUrl())
}

export const applyPwaUpdate = async () => {
  if (state.updating) {
    return
  }
  state.updating = true
  emit()
  try {
    await checkForPwaUpdate()
    if (updateServiceWorker) {
      try {
        await updateServiceWorker(true)
      } catch (error) {
        if (import.meta.env.DEV) {
          console.warn('[PWA] No se pudo aplicar updateServiceWorker:', error)
        }
      }
    }
    await hardReloadPwa()
  } finally {
    state.updating = false
    emit()
  }
}
