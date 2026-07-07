import { describe, it, expect } from 'vitest'
import { pwaOptions } from './pwaOptions'

// Contrato de auto-update silencioso. Estos flags juntos = una versión nueva del
// service worker se instala, toma control y la app se recarga limpia SIN toast ni
// UI de "actualizar". Si alguien los cambia (p.ej. autoUpdate -> prompt), este
// test falla a propósito: rompería la actualización automática.
describe('pwaOptions — contrato de auto-update', () => {
  it('mantiene registerType en autoUpdate (recarga silenciosa, no "prompt")', () => {
    expect(pwaOptions.registerType).toBe('autoUpdate')
  })

  it('el service worker toma control de inmediato (skipWaiting + clientsClaim)', () => {
    expect(pwaOptions.workbox.skipWaiting).toBe(true)
    expect(pwaOptions.workbox.clientsClaim).toBe(true)
  })

  it('limpia cachés viejas para no servir un shell obsoleto', () => {
    expect(pwaOptions.workbox.cleanupOutdatedCaches).toBe(true)
  })
})
