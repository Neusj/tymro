import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import usePwaInstall, { detectStandalone, detectIOS } from './usePwaInstall'
import { resetInstallState } from './installPrompt'

const ORIGINAL_UA = window.navigator.userAgent

function setUserAgent(ua) {
  Object.defineProperty(window.navigator, 'userAgent', { value: ua, configurable: true })
}

function fireBeforeInstallPrompt() {
  const event = new Event('beforeinstallprompt')
  event.prompt = vi.fn()
  event.userChoice = Promise.resolve({ outcome: 'accepted' })
  const preventDefault = vi.spyOn(event, 'preventDefault')
  act(() => {
    window.dispatchEvent(event)
  })
  return { event, preventDefault }
}

beforeEach(() => {
  resetInstallState()
})

afterEach(() => {
  setUserAgent(ORIGINAL_UA)
  delete window.matchMedia
  delete window.navigator.standalone
})

describe('usePwaInstall — captura del evento de instalación', () => {
  it('empieza sin poder instalar y captura beforeinstallprompt previniendo el default', () => {
    const { result } = renderHook(() => usePwaInstall())
    expect(result.current.canInstall).toBe(false)

    const { preventDefault } = fireBeforeInstallPrompt()

    expect(preventDefault).toHaveBeenCalled()
    expect(result.current.canInstall).toBe(true)
  })

  it('appinstalled marca instalada y deshabilita el botón', () => {
    const { result } = renderHook(() => usePwaInstall())
    fireBeforeInstallPrompt()
    expect(result.current.canInstall).toBe(true)

    act(() => {
      window.dispatchEvent(new Event('appinstalled'))
    })

    expect(result.current.installed).toBe(true)
    expect(result.current.canInstall).toBe(false)
  })

  it('promptInstall dispara el prompt nativo y consume el evento diferido', async () => {
    const { result } = renderHook(() => usePwaInstall())
    const { event } = fireBeforeInstallPrompt()

    await act(async () => {
      await result.current.promptInstall()
    })

    expect(event.prompt).toHaveBeenCalledTimes(1)
    // El evento diferido solo puede usarse una vez: tras usarlo, canInstall vuelve a false.
    expect(result.current.canInstall).toBe(false)
  })
})

describe('detectStandalone', () => {
  it('true cuando el display-mode es standalone (Android/escritorio instalado)', () => {
    window.matchMedia = (query) => ({
      matches: query.includes('standalone'),
      media: query,
      addEventListener() {},
      removeEventListener() {},
    })
    expect(detectStandalone()).toBe(true)
  })

  it('true cuando navigator.standalone es true (iOS instalado)', () => {
    window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} })
    Object.defineProperty(window.navigator, 'standalone', { value: true, configurable: true })
    expect(detectStandalone()).toBe(true)
  })

  it('false cuando corre en el navegador (no instalada)', () => {
    window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} })
    expect(detectStandalone()).toBe(false)
  })
})

describe('detectIOS', () => {
  it('true para iPhone', () => {
    setUserAgent('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15')
    expect(detectIOS()).toBe(true)
  })

  it('false para Android', () => {
    setUserAgent('Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36')
    expect(detectIOS()).toBe(false)
  })
})
