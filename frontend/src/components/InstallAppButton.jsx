import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import useBodyScrollLock from '../hooks/useBodyScrollLock'
import usePwaInstall from '../pwa/usePwaInstall'

// Ícono "instalar en el dispositivo" (flecha hacia una bandeja).
function InstallIcon({ className = '' }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden="true">
      <path d="M12 3v11" />
      <path d="m8 10 4 4 4-4" />
      <path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" />
    </svg>
  )
}

// Glifo de "Compartir" de iOS (caja con flecha hacia arriba).
function ShareIcon({ className = '' }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden="true">
      <path d="M12 15V4" />
      <path d="m8 8 4-4 4 4" />
      <path d="M8 11H6a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-6a2 2 0 0 0-2-2h-2" />
    </svg>
  )
}

// Glifo de "Agregar a pantalla de inicio" (más dentro de un cuadro).
function AddToHomeIcon({ className = '' }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden="true">
      <rect x="3" y="3" width="18" height="18" rx="5" />
      <path d="M12 8.5v7M8.5 12h7" />
    </svg>
  )
}

const IOS_STEPS = [
  { key: 'share', icon: ShareIcon, before: 'Toca ', strong: 'Compartir', after: ' en la barra de Safari.' },
  { key: 'add', icon: AddToHomeIcon, before: 'Elige ', strong: 'Agregar a pantalla de inicio', after: '.' },
  { key: 'confirm', icon: InstallIcon, before: 'Confirma tocando ', strong: 'Agregar', after: ' arriba a la derecha.' },
]

// Instructivo manual para iOS (Safari no dispara beforeinstallprompt). Sigue el
// patrón de modal de la app: portal + bloqueo de scroll + cierre con Escape.
function IosInstructions({ onClose }) {
  useBodyScrollLock(true)

  useEffect(() => {
    const onKeyDown = (event) => {
      if (event.key === 'Escape') {
        onClose()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  if (typeof document === 'undefined') {
    return null
  }

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto bg-black/80 p-4"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-labelledby="ios-install-title"
    >
      <div
        className="flex max-h-[90vh] w-full max-w-sm flex-col overflow-hidden rounded-2xl border border-brand-line bg-brand-soft shadow-glow animate-scale-in"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3 border-b border-brand-line p-5">
          <div className="flex items-center gap-3">
            <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-brand-red via-brand-orange to-brand-blue text-white shadow-soft">
              <InstallIcon className="h-5 w-5" />
            </span>
            <div className="min-w-0">
              <h3 id="ios-install-title" className="font-display text-lg font-semibold leading-tight text-brand-white">
                Instala TYMRO en tu iPhone
              </h3>
              <p className="mt-0.5 text-xs text-brand-muted">Tenla como una app en tu pantalla de inicio.</p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Cerrar"
            className="-m-1 inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-brand-muted transition hover:bg-brand-elevated hover:text-brand-white"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5" aria-hidden="true">
              <path d="M18 6 6 18M6 6l12 12" />
            </svg>
          </button>
        </div>

        <ol className="flex flex-col gap-3 p-5">
          {IOS_STEPS.map((step, index) => {
            const StepIcon = step.icon
            return (
              <li key={step.key} className="flex items-center gap-3 rounded-xl border border-brand-line bg-black/25 p-3">
                <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full border border-brand-hairline bg-brand-elevated text-xs font-bold text-brand-orange">
                  {index + 1}
                </span>
                <p className="min-w-0 flex-1 text-sm text-brand-muted">
                  {step.before}
                  <strong className="font-semibold text-brand-white">{step.strong}</strong>
                  {step.after}
                </p>
                <StepIcon className="h-5 w-5 shrink-0 text-brand-dim" />
              </li>
            )
          })}
        </ol>

        <div className="border-t border-brand-line p-4">
          <button type="button" onClick={onClose} className="btn-accent w-full">
            Entendido
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}

// Botón "Instalar app" con doble camino:
//  - Android/escritorio (Chromium): dispara el prompt nativo capturado.
//  - iOS: abre el instructivo manual.
// Se auto-oculta si la app ya corre instalada (standalone) o si no hay forma de
// instalar (navegador que no ofreció el prompt y no es iOS).
export default function InstallAppButton({ variant = 'header' }) {
  const { canInstall, installed, isStandalone, isIOS, promptInstall } = usePwaInstall()
  const [showIos, setShowIos] = useState(false)

  if (isStandalone || installed || (!canInstall && !isIOS)) {
    return null
  }

  const handleClick = () => {
    if (canInstall) {
      promptInstall().catch(() => {})
      return
    }
    if (isIOS) {
      setShowIos(true)
    }
  }

  const button =
    variant === 'landing' ? (
      <button
        type="button"
        onClick={handleClick}
        aria-label="Instalar app"
        className="group mt-6 inline-flex w-full items-center justify-center gap-3 rounded-xl border border-brand-hairline bg-white/[0.03] px-4 py-3 text-left font-semibold text-brand-white transition duration-200 ease-snap animate-fade-rise hover:-translate-y-px hover:border-brand-orange/60 hover:bg-white/[0.06]"
      >
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-gradient-to-br from-brand-red via-brand-orange to-brand-blue text-white shadow-soft">
          <InstallIcon className="h-4 w-4 transition-transform duration-200 ease-snap group-hover:translate-y-0.5" />
        </span>
        <span className="flex flex-col leading-tight">
          <span className="text-sm">Instalar app</span>
          <span className="text-xs font-normal text-brand-muted">Acceso directo, sin abrir el navegador</span>
        </span>
      </button>
    ) : (
      <button
        type="button"
        onClick={handleClick}
        aria-label="Instalar app"
        className="group inline-flex min-h-11 items-center gap-2 rounded-xl border border-brand-line bg-brand-soft px-3 py-2 text-sm font-medium text-brand-white transition duration-200 ease-snap animate-fade-rise hover:-translate-y-px hover:border-brand-orange hover:text-brand-orange"
      >
        <InstallIcon className="h-4 w-4 shrink-0 text-brand-orange transition-transform duration-200 ease-snap group-hover:translate-y-0.5" />
        <span className="hidden sm:inline">Instalar app</span>
      </button>
    )

  return (
    <>
      {button}
      {showIos ? <IosInstructions onClose={() => setShowIos(false)} /> : null}
    </>
  )
}
