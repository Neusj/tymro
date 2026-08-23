import { Link } from 'react-router-dom'

export default function DashboardHeader({ title, subtitle, extra, back }) {
  return (
    <div className="relative mb-6 overflow-hidden rounded-2xl border border-brand-line bg-gradient-to-br from-brand-red/15 via-brand-orange/10 to-brand-blue/15 p-5 sm:p-6">
      <div className="pointer-events-none absolute -right-16 -top-16 h-48 w-48 rounded-full bg-brand-orange/10 blur-3xl" />
      <div className="relative flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <div className="min-w-0">
          {back ? (
            <Link
              to={back.to}
              state={back.state}
              aria-label={back.label || 'Volver'}
              className="mb-2 inline-flex min-h-9 items-center gap-1.5 rounded-lg text-sm font-medium text-brand-muted transition hover:text-brand-orange"
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M19 12H5M12 19l-7-7 7-7" />
              </svg>
              {back.label ? <span>{back.label}</span> : <span className="sr-only">Volver</span>}
            </Link>
          ) : null}
          <h1 className="text-fluid-2xl font-bold leading-tight text-brand-white">{title}</h1>
          {subtitle ? <p className="mt-1.5 max-w-2xl text-sm text-brand-muted">{subtitle}</p> : null}
        </div>
        {extra ? <div className="shrink-0">{extra}</div> : null}
      </div>
    </div>
  )
}
