import { describe, expect, it, vi } from 'vitest'
import { browserNotificationPermission, isPushSupported, urlBase64ToUint8Array } from './pushNotifications'

describe('pushNotifications helpers', () => {
  it('convierte la public key VAPID base64url a Uint8Array', () => {
    const output = urlBase64ToUint8Array('AQID')
    expect(Array.from(output)).toEqual([1, 2, 3])
  })

  it('detecta soporte de push segun APIs del navegador', () => {
    const originalNotification = window.Notification
    const originalServiceWorker = navigator.serviceWorker
    const originalPushManager = window.PushManager

    Object.defineProperty(window, 'Notification', {
      value: { permission: 'default', requestPermission: vi.fn() },
      configurable: true,
    })
    Object.defineProperty(navigator, 'serviceWorker', { value: {}, configurable: true })
    Object.defineProperty(window, 'PushManager', { value: function PushManager() {}, configurable: true })

    expect(isPushSupported()).toBe(true)
    expect(browserNotificationPermission()).toBe('default')

    Object.defineProperty(window, 'Notification', { value: originalNotification, configurable: true })
    Object.defineProperty(navigator, 'serviceWorker', { value: originalServiceWorker, configurable: true })
    Object.defineProperty(window, 'PushManager', { value: originalPushManager, configurable: true })
  })
})
