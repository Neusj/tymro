import { useCallback, useEffect, useMemo, useState } from 'react'
import { clearDeferredPrompt, getInstallState, subscribe } from './installPrompt'

// ¿La app ya corre instalada? Android/escritorio exponen display-mode: standalone;
// iOS Safari usa navigator.standalone cuando se abre desde la pantalla de inicio.
export function detectStandalone() {
  if (typeof window === 'undefined') {
    return false
  }
  const mql = window.matchMedia && window.matchMedia('(display-mode: standalone)')
  return Boolean((mql && mql.matches) || window.navigator?.standalone === true)
}

// iOS no dispara beforeinstallprompt: hay que detectarlo para mostrar el instructivo
// manual. iPadOS 13+ se reporta como "Macintosh"; se distingue por el touch.
export function detectIOS() {
  if (typeof navigator === 'undefined') {
    return false
  }
  const ua = navigator.userAgent || ''
  const isAppleMobile = /iphone|ipad|ipod/i.test(ua)
  const isIpadOsAsMac = /Macintosh/.test(ua) && (navigator.maxTouchPoints || 0) > 1
  return isAppleMobile || isIpadOsAsMac
}

// Estado de instalación PWA para la UI. `canInstall` refleja el evento diferido ya
// capturado (Android/escritorio); `isIOS` decide el camino del instructivo manual.
export default function usePwaInstall() {
  const [state, setState] = useState(getInstallState)

  useEffect(() => {
    // Re-sincroniza por si el evento llegó entre el snapshot inicial y el efecto.
    setState(getInstallState())
    return subscribe(() => setState(getInstallState()))
  }, [])

  const isStandalone = useMemo(detectStandalone, [])
  const isIOS = useMemo(detectIOS, [])

  const promptInstall = useCallback(async () => {
    const event = state.deferredPrompt
    if (!event) {
      return null
    }
    event.prompt()
    try {
      const choice = await event.userChoice
      return choice?.outcome ?? null
    } finally {
      // El evento diferido solo puede usarse una vez.
      clearDeferredPrompt()
    }
  }, [state.deferredPrompt])

  return {
    canInstall: Boolean(state.deferredPrompt),
    installed: state.installed,
    isStandalone,
    isIOS,
    promptInstall,
  }
}
