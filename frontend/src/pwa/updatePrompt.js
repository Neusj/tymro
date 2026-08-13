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

export const applyPwaUpdate = async () => {
  if (!updateServiceWorker || state.updating) {
    return
  }
  state.updating = true
  emit()
  try {
    await updateServiceWorker(true)
  } finally {
    state.updating = false
    emit()
  }
}

