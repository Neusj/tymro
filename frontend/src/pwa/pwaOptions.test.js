import { describe, it, expect } from 'vitest'
import { pwaOptions } from './pwaOptions'

// Contrato de actualización in-app. Una versión nueva queda esperando y la app
// muestra un botón "Actualizar"; al pulsarlo el SW toma control y recarga.
describe('pwaOptions - contrato de actualizacion in-app', () => {
  it('mantiene registerType en prompt para mostrar boton de actualizacion', () => {
    expect(pwaOptions.registerType).toBe('prompt')
  })

  it('el service worker espera al boton y luego puede tomar control', () => {
    expect(pwaOptions.workbox.skipWaiting).toBe(false)
    expect(pwaOptions.workbox.clientsClaim).toBe(true)
  })

  it('limpia caches viejas para no servir un shell obsoleto', () => {
    expect(pwaOptions.workbox.cleanupOutdatedCaches).toBe(true)
  })
})
