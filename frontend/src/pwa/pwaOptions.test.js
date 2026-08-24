import { describe, it, expect } from 'vitest'
import { pwaOptions } from './pwaOptions'

// Contrato de actualizacion in-app. La app mantiene el boton visible cuando detecta
// una version nueva, pero el SW puede tomar control sin quedar esperando al viejo.
describe('pwaOptions - contrato de actualizacion in-app', () => {
  it('mantiene registerType en prompt para mostrar boton de actualizacion', () => {
    expect(pwaOptions.registerType).toBe('prompt')
  })

  it('el service worker nuevo puede tomar control sin quedar pegado al viejo', () => {
    expect(pwaOptions.workbox.skipWaiting).toBe(true)
    expect(pwaOptions.workbox.clientsClaim).toBe(true)
  })

  it('limpia caches viejas para no servir un shell obsoleto', () => {
    expect(pwaOptions.workbox.cleanupOutdatedCaches).toBe(true)
  })

  it('extiende el service worker existente con el manejador push', () => {
    expect(pwaOptions.workbox.importScripts).toContain('push-sw.js')
  })
})
