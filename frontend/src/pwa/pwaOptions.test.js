import { describe, it, expect } from 'vitest'
import { pwaOptions } from './pwaOptions'

// Contrato de actualización in-app. La app mantiene el shell actual completo hasta
// que el usuario acepta la nueva versión desde el botón visible.
describe('pwaOptions - contrato de actualizacion in-app', () => {
  it('mantiene registerType en prompt para mostrar boton de actualizacion', () => {
    expect(pwaOptions.registerType).toBe('prompt')
  })

  it('el service worker nuevo espera para no mezclar versiones del app shell', () => {
    expect(pwaOptions.workbox.skipWaiting).toBe(false)
    expect(pwaOptions.workbox.clientsClaim).toBe(true)
  })

  it('limpia caches viejas para no servir un shell obsoleto', () => {
    expect(pwaOptions.workbox.cleanupOutdatedCaches).toBe(true)
  })

  it('extiende el service worker existente con el manejador push', () => {
    expect(pwaOptions.workbox.importScripts).toContain('push-sw.js')
  })
})
