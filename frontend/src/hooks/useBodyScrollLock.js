import { useEffect } from 'react'

/**
 * Bloquea el scroll del <body> mientras `locked` sea true y lo restaura al cerrar.
 * Compensa el ancho de la scrollbar para evitar el "salto" de layout.
 * Usa un contador para soportar varios modales abiertos a la vez.
 */
let lockCount = 0
let previousOverflow = ''
let previousPaddingRight = ''

export default function useBodyScrollLock(locked) {
  useEffect(() => {
    if (!locked || typeof document === 'undefined') {
      return undefined
    }

    if (lockCount === 0) {
      const { body } = document
      const scrollbarWidth = window.innerWidth - document.documentElement.clientWidth
      previousOverflow = body.style.overflow
      previousPaddingRight = body.style.paddingRight
      body.style.overflow = 'hidden'
      if (scrollbarWidth > 0) {
        body.style.paddingRight = `${scrollbarWidth}px`
      }
    }
    lockCount += 1

    return () => {
      lockCount -= 1
      if (lockCount === 0) {
        const { body } = document
        body.style.overflow = previousOverflow
        body.style.paddingRight = previousPaddingRight
      }
    }
  }, [locked])
}
