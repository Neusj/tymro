// Registro del Service Worker (vite-plugin-pwa, modo prompt).
//
// `virtual:pwa-register` es un módulo virtual que inyecta el plugin tanto en
// build como en dev (devOptions.enabled). Con registerType: 'prompt', al
// detectar una versión nueva la UI muestra un botón para actualizar.
import { registerSW } from 'virtual:pwa-register'
import {
  checkForPwaUpdate,
  markPwaUpdateReady,
  setPwaRegistration,
  setPwaUpdateHandler,
} from './pwa/updatePrompt'

const updateServiceWorker = registerSW({
  immediate: true,
  onNeedRefresh() {
    markPwaUpdateReady()
  },
  onRegisteredSW(swUrl, registration) {
    setPwaRegistration(registration)
    if (import.meta.env.DEV) console.info('[PWA] Service worker registrado:', swUrl)
  },
  onRegisterError(error) {
    console.error('[PWA] Error registrando el service worker:', error)
  },
})

setPwaUpdateHandler(updateServiceWorker)

if (typeof window !== 'undefined') {
  window.addEventListener('focus', checkForPwaUpdate)
  window.addEventListener('online', checkForPwaUpdate)
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') {
      checkForPwaUpdate()
    }
  })
}
