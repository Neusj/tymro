import { useEffect, useRef, useState } from 'react'
import InstallAppButton from '../InstallAppButton'
import RutReminderBanner from '../RutReminderBanner'
import ScrollToTopButton from '../ScrollToTopButton'
import TrialClassBanner from '../TrialClassBanner'
import Sidebar from './Sidebar'

export default function AppLayout({ user, onLogout, children }) {
  const [isOpen, setIsOpen] = useState(false)
  const mainRef = useRef(null)
  const [isMobile, setIsMobile] = useState(() => {
    if (typeof window === 'undefined') {
      return false
    }
    return window.matchMedia('(max-width: 767px)').matches
  })

  useEffect(() => {
    if (typeof window === 'undefined') {
      return undefined
    }

    const mediaQuery = window.matchMedia('(max-width: 767px)')
    const handleMediaChange = (event) => {
      setIsMobile(event.matches)
      setIsOpen(false)
    }

    mediaQuery.addEventListener('change', handleMediaChange)
    return () => mediaQuery.removeEventListener('change', handleMediaChange)
  }, [])

  const handleToggleSidebar = () => setIsOpen((prev) => !prev)
  const handleCloseSidebar = () => setIsOpen(false)

  const orgName = user?.organization_detail?.name || 'TYMRO'
  const primary = user?.organization_detail?.primary_color || '#dc2626'
  const secondary = user?.organization_detail?.secondary_color || '#2563eb'

  // Identidad del usuario: "Nombre Apellido — {rol legible}". role_display viene del
  // backend (get_role_display, única fuente). Si falta el nombre, mostramos solo el
  // rol (sin em-dash colgando); si falta el rol, solo el nombre.
  const fullName = [user?.first_name, user?.last_name].filter(Boolean).join(' ').trim()
  const roleDisplay = user?.role_display || ''
  const identity = fullName && roleDisplay ? `${fullName} — ${roleDisplay}` : fullName || roleDisplay

  return (
    <div
      className="relative flex h-screen-dvh overflow-hidden bg-brand-black text-brand-white"
      style={{
        '--dynamic-primary': primary,
        '--dynamic-secondary': secondary,
      }}
    >
      <Sidebar isOpen={isOpen} isMobile={isMobile} onNavigate={handleCloseSidebar} onRequestOpen={() => setIsOpen(true)} user={user} />

      {isMobile && isOpen ? (
        <button
          type="button"
          aria-label="Cerrar menú"
          onClick={handleCloseSidebar}
          className="fixed inset-0 z-30 bg-black/60 transition-opacity duration-300"
        />
      ) : null}

      <div className="relative z-10 flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
        <header className="pt-safe-top sticky top-0 z-20 shrink-0 border-b border-brand-line bg-brand-black/80 backdrop-blur-md">
          <div className="flex h-16 items-center justify-between px-4 md:px-6">
          <div className="flex min-w-0 items-center gap-3">
            <button
              type="button"
              onClick={handleToggleSidebar}
              aria-label={isOpen ? 'Cerrar menú' : 'Abrir menú'}
              className="inline-flex h-11 w-11 items-center justify-center rounded-xl border border-brand-line bg-brand-soft text-brand-white transition hover:border-brand-orange hover:text-brand-orange"
            >
              <span className="text-lg leading-none">☰</span>
            </button>
            <div className="min-w-0">
              <p className="font-display text-xs font-bold uppercase tracking-[0.35em] text-brand-orange">TYMRO</p>
              <p className="truncate text-xs text-brand-muted md:text-sm">{orgName}</p>
            </div>
          </div>

          <div className="flex items-center gap-2 sm:gap-3">
            {identity ? (
              <span
                className="hidden max-w-[16rem] truncate text-sm font-medium text-brand-white sm:inline-block"
                title={identity}
              >
                {identity}
              </span>
            ) : null}
            <InstallAppButton variant="header" />
            <button
              type="button"
              onClick={onLogout}
              className="inline-flex min-h-11 items-center rounded-xl border border-brand-line bg-brand-soft px-3 py-2 text-sm font-medium text-brand-white transition hover:border-brand-red hover:text-brand-red"
            >
              <span className="hidden sm:inline">Cerrar sesión</span>
              <span className="sm:hidden" aria-hidden="true">⏻</span>
              <span className="sr-only sm:hidden">Cerrar sesión</span>
            </button>
          </div>
          </div>
        </header>

        <main ref={mainRef} className="min-h-0 flex-1 overflow-y-auto overscroll-y-contain px-4 py-5 sm:px-6 sm:py-7 lg:px-8 lg:py-9 3xl:px-12">
          <div className="app-container animate-fade-rise">
            <RutReminderBanner />
            <TrialClassBanner />
            {children}
          </div>
        </main>
      </div>

      <ScrollToTopButton scrollRef={mainRef} />
    </div>
  )
}
