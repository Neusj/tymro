import { useId } from 'react'

export default function TablePagination({
  page,
  totalPages,
  pageSize,
  pageSizeOptions = [],
  startItem = 0,
  endItem = 0,
  totalItems = 0,
  onPrevious,
  onNext,
  onPageSizeChange,
}) {
  const selectId = useId()

  return (
    <div className="mt-4 flex flex-col gap-3 border-t border-brand-line pt-4 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-center gap-2">
        <label htmlFor={selectId} className="text-xs text-brand-muted">
          Filas por pagina
        </label>
        <select
          id={selectId}
          value={pageSize}
          onChange={(event) => onPageSizeChange(Number(event.target.value))}
          className="rounded-lg border border-brand-line bg-black/30 px-2 py-1.5 text-sm text-brand-white focus:border-brand-blue focus:outline-none"
        >
          {pageSizeOptions.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      </div>
      <div className="text-xs text-brand-muted">
        {startItem}-{endItem} de {totalItems}
      </div>
      <div className="flex items-center justify-end gap-3 sm:ml-auto">
        <button
          type="button"
          onClick={onPrevious}
          disabled={page <= 1}
          className="min-h-10 rounded-lg border border-brand-line px-4 py-2 text-sm text-brand-white transition hover:border-brand-orange disabled:cursor-not-allowed disabled:opacity-50"
        >
          Anterior
        </button>
        <span className="text-xs text-brand-muted">
          Pagina {page} de {totalPages}
        </span>
        <button
          type="button"
          onClick={onNext}
          disabled={page >= totalPages}
          className="min-h-10 rounded-lg border border-brand-line px-4 py-2 text-sm text-brand-white transition hover:border-brand-blue disabled:cursor-not-allowed disabled:opacity-50"
        >
          Siguiente
        </button>
      </div>
    </div>
  )
}
