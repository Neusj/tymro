export default function EmptyState({ title, description }) {
  return (
    <div className="rounded-2xl border border-dashed border-brand-line bg-brand-soft/70 p-6 text-center">
      <p className="text-sm font-semibold text-brand-white">{title}</p>
      {description ? <p className="mt-1 text-sm text-brand-muted">{description}</p> : null}
    </div>
  )
}
