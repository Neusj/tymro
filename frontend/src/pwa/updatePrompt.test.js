import { afterEach, describe, expect, it, vi } from 'vitest'
import { applyPwaUpdate, setPwaUpdateHandler } from './updatePrompt'

afterEach(() => {
  setPwaUpdateHandler(null)
})

describe('applyPwaUpdate', () => {
  it('activa el worker en espera sin borrar caches ni desregistrar workers', async () => {
    const deleteCache = vi.fn()
    const unregister = vi.fn()
    const updateServiceWorker = vi.fn().mockResolvedValue(undefined)
    const originalCaches = window.caches
    const originalServiceWorker = navigator.serviceWorker

    Object.defineProperty(window, 'caches', {
      configurable: true,
      value: { keys: vi.fn(), delete: deleteCache },
    })
    Object.defineProperty(navigator, 'serviceWorker', {
      configurable: true,
      value: { getRegistrations: vi.fn().mockResolvedValue([{ unregister }]) },
    })

    setPwaUpdateHandler(updateServiceWorker)
    await applyPwaUpdate()

    expect(updateServiceWorker).toHaveBeenCalledOnce()
    expect(updateServiceWorker).toHaveBeenCalledWith(true)
    expect(window.caches.keys).not.toHaveBeenCalled()
    expect(deleteCache).not.toHaveBeenCalled()
    expect(navigator.serviceWorker.getRegistrations).not.toHaveBeenCalled()
    expect(unregister).not.toHaveBeenCalled()

    Object.defineProperty(window, 'caches', { configurable: true, value: originalCaches })
    Object.defineProperty(navigator, 'serviceWorker', {
      configurable: true,
      value: originalServiceWorker,
    })
  })
})
