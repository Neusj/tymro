// Singleton global de captura del evento de instalación PWA.
//
// `beforeinstallprompt` es un evento one-shot que el navegador (Chromium) dispara
// una sola vez cuando la app es instalable. En esta SPA el header se REMONTA en
// cada navegación (cada ruta envuelve su propio AppLayout), así que un listener
// atado al montaje de un componente perdería el evento. Por eso lo capturamos y
// bufferizamos a nivel de módulo: cualquier montaje posterior lee el buffer.
let deferredPrompt = null
let installed = false
let initialized = false
const listeners = new Set()

function emit() {
  for (const listener of listeners) {
    listener()
  }
}

// Idempotente: se llama al importar el módulo (main.jsx lo importa temprano).
export function initInstallPromptCapture() {
  if (initialized || typeof window === 'undefined') {
    return
  }
  initialized = true

  window.addEventListener('beforeinstallprompt', (event) => {
    // Evita el mini-infobar automático de Chrome; el prompt lo disparamos nosotros.
    event.preventDefault()
    deferredPrompt = event
    emit()
  })

  window.addEventListener('appinstalled', () => {
    installed = true
    deferredPrompt = null
    emit()
  })
}

export function getInstallState() {
  return { deferredPrompt, installed }
}

export function clearDeferredPrompt() {
  deferredPrompt = null
  emit()
}

export function subscribe(listener) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

// Solo para tests: limpia el estado y los suscriptores entre casos. No re-arma
// los listeners de window (se atan una vez al importar), así que no los reinicia.
export function resetInstallState() {
  deferredPrompt = null
  installed = false
  listeners.clear()
}

// Auto-inicializa al importarse para arrancar la captura cuanto antes.
initInstallPromptCapture()
