// Registro del Service Worker (vite-plugin-pwa, modo autoUpdate).
//
// `virtual:pwa-register` es un módulo virtual que inyecta el plugin tanto en
// build como en dev (devOptions.enabled). Con registerType: 'autoUpdate', al
// detectar una versión nueva el SW la instala y la app se recarga sola.
import { registerSW } from 'virtual:pwa-register'

registerSW({
  immediate: true,
  onRegisteredSW(swUrl) {
    if (import.meta.env.DEV) console.info('[PWA] Service worker registrado:', swUrl)
  },
  onRegisterError(error) {
    console.error('[PWA] Error registrando el service worker:', error)
  },
})
