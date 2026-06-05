import { useId } from 'react'

export default function TableSearch({ value, onChange, placeholder = 'Buscar...' }) {
  const inputId = useId()

  return (
    <div className="mb-4">
      <label className="sr-only" htmlFor={inputId}>
        Buscar
      </label>
      <input
        id={inputId}
        type="text"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        className="min-h-11 w-full rounded-xl border border-brand-line bg-black/30 px-3 py-2 text-sm text-brand-white placeholder:text-brand-muted focus:border-brand-blue focus:outline-none"
      />
    </div>
  )
}
