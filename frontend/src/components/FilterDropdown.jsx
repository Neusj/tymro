import { useMemo, useState } from 'react'

export default function FilterDropdown({ label, value, options = [], onChange }) {
  const [open, setOpen] = useState(false)
  const currentLabel = useMemo(() => options.find((item) => item.value === value)?.label || 'Todos', [options, value])

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        className="inline-flex min-w-[180px] items-center justify-between gap-2 rounded-lg border border-brand-line bg-black/30 px-3 py-2 text-sm text-brand-white"
      >
        <span className="text-brand-muted">{label}:</span>
        <span>{currentLabel}</span>
      </button>
      {open ? (
        <div className="absolute z-30 mt-2 w-full min-w-[220px] rounded-lg border border-brand-line bg-brand-soft p-2 shadow-glow">
          <div className="space-y-1">
            {options.map((option) => {
              const active = value === option.value
              return (
                <button
                  key={`${label}-${option.value || 'all'}`}
                  type="button"
                  onClick={() => {
                    onChange(option.value)
                    setOpen(false)
                  }}
                  className={`w-full rounded-md px-2 py-1.5 text-left text-sm transition ${
                    active ? 'border border-brand-blue bg-brand-blue/20 text-brand-white' : 'border border-transparent text-brand-muted hover:border-brand-line hover:text-brand-white'
                  }`}
                >
                  {option.label}
                </button>
              )
            })}
          </div>
        </div>
      ) : null}
    </div>
  )
}
