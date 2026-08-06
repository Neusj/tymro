// Barra de filtros común a las 3 pantallas de reportería: rango de fechas + sucursal +
// el filtro propio del reporte (método/disciplina) + export CSV/XLSX. Un solo componente
// para no triplicar el mismo bloque de <label>+<input>/<select> en cada página (mismo
// criterio que ya usa el repo para <FilterDropdown>/<MultiSelectDropdown>).
const inputClass =
  'rounded-lg border border-brand-line bg-black/30 px-3 py-2 text-sm text-brand-white focus:border-brand-blue focus:outline-none'

export default function ReportFilterBar({
  dateFrom,
  dateTo,
  onDateFromChange,
  onDateToChange,
  branches = [],
  branchId,
  onBranchChange,
  extraFilter,
  onExport,
  exporting = '',
  exportDisabled = false,
}) {
  return (
    <div className="card-surface flex flex-wrap items-end gap-3 p-4 sm:p-5">
      <label className="flex flex-col gap-1 text-xs text-brand-muted">
        Desde
        <input
          type="date"
          value={dateFrom}
          onChange={(event) => onDateFromChange(event.target.value)}
          className={inputClass}
        />
      </label>
      <label className="flex flex-col gap-1 text-xs text-brand-muted">
        Hasta
        <input
          type="date"
          value={dateTo}
          onChange={(event) => onDateToChange(event.target.value)}
          className={inputClass}
        />
      </label>

      {branches.length > 0 ? (
        <label className="flex flex-col gap-1 text-xs text-brand-muted">
          Sucursal
          <select value={branchId} onChange={(event) => onBranchChange(event.target.value)} className={inputClass}>
            <option value="">Todas las sucursales</option>
            {branches.map((branch) => (
              <option key={branch.id} value={branch.id}>
                {branch.name}
              </option>
            ))}
          </select>
        </label>
      ) : null}

      {extraFilter ? (
        <label className="flex flex-col gap-1 text-xs text-brand-muted">
          {extraFilter.label}
          <select
            value={extraFilter.value}
            onChange={(event) => extraFilter.onChange(event.target.value)}
            className={inputClass}
          >
            <option value="">{extraFilter.allLabel || 'Todos'}</option>
            {extraFilter.options.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      ) : null}

      <div className="ml-auto flex items-center gap-2">
        <button
          type="button"
          disabled={exportDisabled}
          onClick={() => onExport('csv')}
          className="inline-flex items-center gap-1.5 rounded-xl border border-brand-hairline px-3 py-2 text-sm font-semibold text-brand-white transition hover:border-brand-blue disabled:cursor-not-allowed disabled:opacity-50"
        >
          {exporting === 'csv' ? 'Exportando…' : 'CSV'}
        </button>
        <button
          type="button"
          disabled={exportDisabled}
          onClick={() => onExport('xlsx')}
          className="inline-flex items-center gap-1.5 rounded-xl bg-success px-3 py-2 text-sm font-semibold text-black transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {exporting === 'xlsx' ? 'Exportando…' : 'Excel'}
        </button>
      </div>
    </div>
  )
}
