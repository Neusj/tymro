import { useEffect, useState } from 'react'

/**
 * Indicador simple de estado offline. Aparece como una barra fija abajo cuando
 * el navegador pierde conexión y desaparece al reconectar. Mientras está offline,
 * el service worker sigue sirviendo el shell de la app y los últimos datos
 * cacheados (clases, usuario, etc.).
 */
export default function OfflineBanner() {
  const getOnline = () =>
    typeof navigator === 'undefined' ? true : navigator.onLine
  const [online, setOnline] = useState(getOnline)

  useEffect(() => {
    const goOnline = () => setOnline(true)
    const goOffline = () => setOnline(false)
    window.addEventListener('online', goOnline)
    window.addEventListener('offline', goOffline)
    return () => {
      window.removeEventListener('online', goOnline)
      window.removeEventListener('offline', goOffline)
    }
  }, [])

  if (online) return null

  return (
    <div
      role="status"
      aria-live="polite"
      className="fixed inset-x-0 bottom-0 z-[100] border-t border-warning-line bg-brand-soft/95 px-4 py-2 text-center text-sm text-warning backdrop-blur"
      style={{ paddingBottom: 'calc(0.5rem + env(safe-area-inset-bottom))' }}
    >
      <span className="inline-flex items-center gap-2">
        <span className="h-2 w-2 rounded-full bg-warning" aria-hidden="true" />
        Sin conexión — mostrando datos guardados
      </span>
    </div>
  )
}
