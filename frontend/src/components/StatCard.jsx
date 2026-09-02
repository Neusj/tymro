import { Link } from 'react-router-dom'

export default function StatCard({ title, value, accent = 'orange', hint, to, onClick, ariaLabel }) {
  const accentClasses = {
    orange: 'from-brand-orange/25',
    red: 'from-brand-red/25',
    blue: 'from-brand-blue/25',
    success: 'from-success/25',
    // Neutro a propósito: para valores que no son ni un logro (success) ni un problema
    // (red) — ej. reportería, subtotal "sin método registrado" (P3.4).
    muted: 'from-brand-dim/20',
  }
  const barClasses = {
    orange: 'bg-brand-orange',
    red: 'bg-brand-red',
    blue: 'bg-brand-blue',
    success: 'bg-success',
    muted: 'bg-brand-dim',
  }

  const isInteractive = Boolean(to || onClick)
  const className = `card-surface group relative block overflow-hidden p-4 text-left transition duration-300 hover:-translate-y-0.5 hover:shadow-float ${
    isInteractive ? 'cursor-pointer hover:border-brand-orange' : ''
  }`

  const content = (
    <>
      <div className={`absolute inset-0 bg-gradient-to-br to-transparent opacity-80 ${accentClasses[accent] || accentClasses.orange}`} />
      <span className={`absolute left-0 top-0 h-full w-1 ${barClasses[accent] || barClasses.orange}`} />
      <div className="relative z-10 flex items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="text-xs font-medium uppercase tracking-wide text-brand-muted">{title}</p>
          <p className="mt-1 font-display text-2xl font-bold leading-none text-brand-white sm:text-3xl">{value}</p>
          {hint ? <p className="mt-1.5 text-xs text-brand-muted">{hint}</p> : null}
        </div>
        {isInteractive ? (
          <svg
            width="18"
            height="18"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
            className="shrink-0 text-brand-muted transition group-hover:translate-x-0.5 group-hover:text-brand-orange"
          >
            <path d="M5 12h14M12 5l7 7-7 7" />
          </svg>
        ) : null}
      </div>
    </>
  )

  if (to) {
    return (
      <Link to={to} className={className}>
        {content}
      </Link>
    )
  }

  if (onClick) {
    return (
      <button type="button" onClick={onClick} aria-label={ariaLabel || title} className={`w-full ${className}`}>
        {content}
      </button>
    )
  }

  return <div className={className}>{content}</div>
}
