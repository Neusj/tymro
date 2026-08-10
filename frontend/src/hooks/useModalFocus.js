import { useEffect, useRef } from 'react'

const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'textarea:not([disabled])',
  'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',')

export function getFocusable(container) {
  return Array.from(container?.querySelectorAll(FOCUSABLE_SELECTOR) || []).filter((element) => {
    if (element.hasAttribute('disabled') || element.getAttribute('aria-hidden') === 'true') {
      return false
    }
    return true
  })
}

export default function useModalFocus({
  open,
  containerRef,
  initialFocusRef,
  getInitialFocus,
  onEscape,
  escapeDisabled = false,
}) {
  const previousFocusRef = useRef(null)

  useEffect(() => {
    if (!open || typeof document === 'undefined') {
      return undefined
    }

    previousFocusRef.current = document.activeElement
    window.setTimeout(() => {
      const target = getInitialFocus?.() || initialFocusRef?.current || getFocusable(containerRef.current)[0] || containerRef.current
      target?.focus?.()
    }, 0)

    return () => {
      previousFocusRef.current?.focus?.()
    }
  }, [open])

  useEffect(() => {
    if (!open || typeof document === 'undefined') {
      return undefined
    }

    const handleKeyDown = (event) => {
      if (event.key === 'Escape') {
        if (!escapeDisabled) {
          onEscape?.()
        }
        return
      }

      if (event.key !== 'Tab') {
        return
      }

      const focusable = getFocusable(containerRef.current)
      if (focusable.length === 0) {
        event.preventDefault()
        return
      }

      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
        return
      }
      if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [containerRef, escapeDisabled, onEscape, open])
}
