import { describe, it, expect } from 'vitest'
import { pwaOptions } from './pwaOptions'

// Contrato de actualización in-app. La app mantiene el shell actual completo hasta
// que el usuario acepta la nueva versión desde el botón visible.
describe('pwaOptions - contrato de actualizacion in-app', () => {
  it('publica solamente los iconos PWA versionados actuales', () => {
    expect(pwaOptions.manifest.icons).toEqual([
      { src: 'pwa-192x192-v3.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
      { src: 'pwa-512x512-v3.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
      { src: 'pwa-maskable-512x512-v3.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
    ])
    expect(pwaOptions.includeAssets).toContain('apple-touch-icon-v3.png')
    expect(pwaOptions.workbox.globIgnores).toEqual(expect.arrayContaining([
      'apple-touch-icon.png',
      'apple-touch-icon-v2.png',
      'pwa-192x192.png',
      'pwa-192x192-v2.png',
      'pwa-512x512.png',
      'pwa-512x512-v2.png',
      'pwa-maskable-512x512.png',
      'pwa-maskable-512x512-v2.png',
    ]))
  })

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
