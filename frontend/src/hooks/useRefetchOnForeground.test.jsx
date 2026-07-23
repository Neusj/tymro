import { describe, it, expect, afterEach, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import useRefetchOnForeground from './useRefetchOnForeground'

// jsdom expone document.visibilityState como getter en el prototipo; lo sombreamos
// en la instancia y disparamos el evento real para simular el cambio de foco.
function setVisibility(state) {
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => state })
  act(() => {
    document.dispatchEvent(new Event('visibilitychange'))
  })
}

afterEach(() => {
  // Restaura el estado por defecto de jsdom entre tests.
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'visible' })
})

describe('useRefetchOnForeground', () => {
  it('NO invoca el callback al montar (el mount ya hace su fetch inicial)', () => {
    const cb = vi.fn()
    renderHook(() => useRefetchOnForeground(cb))
    expect(cb).not.toHaveBeenCalled()
  })

  it('invoca el callback cuando el documento vuelve a "visible"', () => {
    const cb = vi.fn()
    renderHook(() => useRefetchOnForeground(cb))

    setVisibility('visible')

    expect(cb).toHaveBeenCalledTimes(1)
  })

  it('NO invoca el callback cuando el documento pasa a "hidden"', () => {
    const cb = vi.fn()
    renderHook(() => useRefetchOnForeground(cb))

    setVisibility('hidden')

    expect(cb).not.toHaveBeenCalled()
  })

  it('limpia el listener al desmontar (no invoca tras unmount)', () => {
    const cb = vi.fn()
    const { unmount } = renderHook(() => useRefetchOnForeground(cb))

    unmount()
    setVisibility('visible')

    expect(cb).not.toHaveBeenCalled()
  })

  it('usa el callback más reciente sin re-registrar en cada render', () => {
    const first = vi.fn()
    const second = vi.fn()
    const { rerender } = renderHook(({ cb }) => useRefetchOnForeground(cb), {
      initialProps: { cb: first },
    })

    rerender({ cb: second })
    setVisibility('visible')

    expect(first).not.toHaveBeenCalled()
    expect(second).toHaveBeenCalledTimes(1)
  })
})
