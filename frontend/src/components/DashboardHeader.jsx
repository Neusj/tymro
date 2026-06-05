export default function DashboardHeader({ title, subtitle, extra }) {
  return (
    <div className="relative mb-6 overflow-hidden rounded-2xl border border-brand-line bg-gradient-to-br from-brand-red/15 via-brand-orange/10 to-brand-blue/15 p-5 sm:p-6">
      <div className="pointer-events-none absolute -right-16 -top-16 h-48 w-48 rounded-full bg-brand-orange/10 blur-3xl" />
      <div className="relative flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <div className="min-w-0">
          <h1 className="text-fluid-2xl font-bold leading-tight text-brand-white">{title}</h1>
          {subtitle ? <p className="mt-1.5 max-w-2xl text-sm text-brand-muted">{subtitle}</p> : null}
        </div>
        {extra ? <div className="shrink-0">{extra}</div> : null}
      </div>
    </div>
  )
}
