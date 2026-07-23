import { useEffect, useRef } from 'react'

// Re-ejecuta `callback` cuando la pestaña/PWA vuelve al foco (visibilitychange →
// visibilityState 'visible'). Pensado para PWA instalada: al volver desde Checkout
// Pro la página sigue montada y su useEffect([]) no re-corre, así que el estado
// quedaría viejo. Este hook cubre SOLO la re-entrada al foco.
//
// No dispara en el montaje: 'visibilitychange' no se emite al montar, de modo que
// el fetch inicial del componente no se duplica. Guarda el callback en un ref para
// usar siempre la versión más reciente sin re-registrar el listener en cada render.
export default function useRefetchOnForeground(callback) {
  const callbackRef = useRef(callback)
  callbackRef.current = callback

  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        callbackRef.current?.()
      }
    }

    document.addEventListener('visibilitychange', handleVisibilityChange)
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange)
  }, [])
}
