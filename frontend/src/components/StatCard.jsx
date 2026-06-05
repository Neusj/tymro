export default function StatCard({ title, value, accent = 'orange', hint }) {
  const accentClasses = {
    orange: 'from-brand-orange/25',
    red: 'from-brand-red/25',
    blue: 'from-brand-blue/25',
    success: 'from-success/25',
  }
  const barClasses = {
    orange: 'bg-brand-orange',
    red: 'bg-brand-red',
    blue: 'bg-brand-blue',
    success: 'bg-success',
  }

  return (
    <div className="card-surface group relative overflow-hidden p-4 transition duration-300 hover:-translate-y-0.5 hover:shadow-float sm:p-5">
      <div className={`absolute inset-0 bg-gradient-to-br to-transparent opacity-80 ${accentClasses[accent] || accentClasses.orange}`} />
      <span className={`absolute left-0 top-0 h-full w-1 ${barClasses[accent] || barClasses.orange}`} />
      <div className="relative z-10">
        <p className="text-xs font-medium uppercase tracking-wide text-brand-muted sm:text-sm">{title}</p>
        <p className="mt-2 font-display text-3xl font-bold leading-none text-brand-white sm:text-4xl">{value}</p>
        {hint ? <p className="mt-2 text-xs text-brand-muted">{hint}</p> : null}
      </div>
    </div>
  )
}
