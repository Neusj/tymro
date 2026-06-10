import { useEffect, useState } from 'react'

/**
 * Botón flotante "subir". Solo móvil/tablet (lg:hidden).
 * Aparece cuando el contenedor scrollable supera el umbral.
 *
 * Props:
 *  - scrollRef: ref al contenedor con overflow-y-auto (el <main> de AppLayout).
 *  - threshold: px de scroll antes de mostrarse (default 320).
 */
export default function ScrollToTopButton({ scrollRef, threshold = 320 }) {
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    const node = scrollRef?.current
    if (!node) {
      return undefined
    }
    const handleScroll = () => setVisible(node.scrollTop > threshold)
    handleScroll()
    node.addEventListener('scroll', handleScroll, { passive: true })
    return () => node.removeEventListener('scroll', handleScroll)
  }, [scrollRef, threshold])

  const scrollToTop = () => {
    scrollRef?.current?.scrollTo({ top: 0, behavior: 'smooth' })
  }

  if (!visible) {
    return null
  }

  return (
    <button
      type="button"
      onClick={scrollToTop}
      aria-label="Subir al inicio"
      className="animate-scale-in fixed bottom-5 right-5 z-30 inline-flex h-12 w-12 items-center justify-center rounded-full border border-brand-line bg-brand-orange text-brand-black shadow-float transition hover:brightness-110 active:brightness-95 lg:hidden"
      style={{ marginBottom: 'env(safe-area-inset-bottom)' }}
    >
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M12 19V5M5 12l7-7 7 7" />
      </svg>
    </button>
  )
}
