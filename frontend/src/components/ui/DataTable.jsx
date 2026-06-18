import { useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import TablePagination from './TablePagination'
import TableSearch from './TableSearch'
import RowActionsDropdown from './RowActionsDropdown'
import useBodyScrollLock from '../../hooks/useBodyScrollLock'

const PAGE_SIZE_OPTIONS = [5, 10, 15, 25]
const CARD_PAGE_SIZE_OPTIONS = [6, 12, 24]
const STATUS_KEY_PATTERN = /(status|estado|state|kind|modalidad)/i

function flattenValue(value) {
  if (value === null || value === undefined) {
    return ''
  }
  if (typeof value === 'string' || typeof value === 'number') {
    return String(value)
  }
  if (typeof value === 'boolean') {
    return value ? 'true' : 'false'
  }
  if (Array.isArray(value)) {
    return value.map(flattenValue).join(' ')
  }
  if (typeof value === 'object') {
    return Object.values(value).map(flattenValue).join(' ')
  }
  return ''
}

function formatCellValue(value) {
  if (value === null || value === undefined || value === '') {
    return <span className="text-brand-muted">-</span>
  }
  return value
}

function isActionsColumn(column) {
  const key = String(column?.key || '').toLowerCase()
  const label = String(column?.label || '').trim().toLowerCase()
  return key === 'actions' || label === 'acciones'
}

function getRowId(row, rowIdKey) {
  return row?.[rowIdKey]
}

function isSortableColumn(column) {
  if (isActionsColumn(column)) {
    return false
  }
  return column.sortable !== false
}

function getSortValue(column, row) {
  if (column.sortAccessor) {
    return column.sortAccessor(row)
  }
  const key = column.sortKey || column.key
  return row?.[key]
}

function compareSort(a, b) {
  if (a === b) return 0
  if (a === null || a === undefined) return 1
  if (b === null || b === undefined) return -1

  const aDate = typeof a === 'string' ? Date.parse(a) : NaN
  const bDate = typeof b === 'string' ? Date.parse(b) : NaN
  if (!Number.isNaN(aDate) && !Number.isNaN(bDate)) {
    return aDate - bDate
  }

  if (typeof a === 'number' && typeof b === 'number') {
    return a - b
  }

  return String(a).localeCompare(String(b), 'es', { sensitivity: 'base' })
}

// Decide where a column lands in the mobile card.
// Pages can override with `column.mobile` ('title' | 'meta' | 'secondary' | 'hidden').
// Otherwise a heuristic keeps the card compact and relevant:
//  - first column -> title
//  - status/kind-like columns -> meta chip next to the title
//  - the next two columns -> labeled secondary lines
//  - everything else -> only inside "Ver detalle"
function resolveMobileZone(column, index) {
  if (column.mobile) {
    return column.mobile
  }
  if (index === 0) {
    return 'title'
  }
  if (STATUS_KEY_PATTERN.test(String(column.key || ''))) {
    return 'meta'
  }
  if (index <= 2) {
    return 'secondary'
  }
  return 'hidden'
}

export default function DataTable({
  columns = [],
  data = [],
  loading = false,
  onEdit,
  onDelete,
  selectableRows = false,
  selectedRowIds = [],
  onSelectedRowIdsChange,
  rowIdKey = 'id',
  defaultSort = null,
  selectAllScope = 'page',
  maxBodyHeight,            // ej: '28rem' | '480px' | '60vh'; undefined = comportamiento actual
}) {
  const [query, setQuery] = useState('')
  const [debouncedQuery, setDebouncedQuery] = useState('')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [isCardView, setIsCardView] = useState(false)
  const [selectedDetailRow, setSelectedDetailRow] = useState(null)
  useBodyScrollLock(Boolean(selectedDetailRow))
  const [sortState, setSortState] = useState(() => {
    if (!defaultSort?.key) {
      return { key: null, direction: 'asc' }
    }
    return { key: defaultSort.key, direction: defaultSort.direction === 'desc' ? 'desc' : 'asc' }
  })

  const hasCallbacks = Boolean(onEdit || onDelete)
  const hasInlineActionsColumn = columns.some((column) => isActionsColumn(column))
  const detailColumns = columns.filter((column) => !isActionsColumn(column))
  const actionColumn = columns.find((column) => isActionsColumn(column))

  // Pre-compute the mobile card zones once per column set.
  const mobileZones = useMemo(() => {
    const withZone = detailColumns.map((column, index) => ({ column, zone: resolveMobileZone(column, index) }))
    const bySort = (a, b) => (a.column.mobilePriority ?? 99) - (b.column.mobilePriority ?? 99)
    return {
      title: withZone.find((item) => item.zone === 'title')?.column || detailColumns[0] || null,
      meta: withZone.filter((item) => item.zone === 'meta').sort(bySort).map((item) => item.column),
      secondary: withZone.filter((item) => item.zone === 'secondary').sort(bySort).map((item) => item.column),
    }
  }, [detailColumns])

  const filteredData = useMemo(() => {
    const normalizedQuery = debouncedQuery.trim().toLowerCase()
    if (!normalizedQuery) {
      return data
    }
    return data.filter((row) => flattenValue(row).toLowerCase().includes(normalizedQuery))
  }, [data, debouncedQuery])

  const sortedData = useMemo(() => {
    if (!sortState.key) {
      return filteredData
    }
    const column = columns.find((item) => item.key === sortState.key)
    if (!column) {
      return filteredData
    }

    const multiplier = sortState.direction === 'desc' ? -1 : 1
    return [...filteredData].sort((left, right) => multiplier * compareSort(getSortValue(column, left), getSortValue(column, right)))
  }, [columns, filteredData, sortState])

  const effectivePageSizeOptions = isCardView ? CARD_PAGE_SIZE_OPTIONS : PAGE_SIZE_OPTIONS
  const effectivePageSize = effectivePageSizeOptions.includes(pageSize) ? pageSize : effectivePageSizeOptions[0]
  const totalPages = Math.max(1, Math.ceil(sortedData.length / effectivePageSize))
  const safePage = Math.min(page, totalPages)
  const paginatedData = sortedData.slice((safePage - 1) * effectivePageSize, safePage * effectivePageSize)
  const pageRowIds = paginatedData.map((row) => getRowId(row, rowIdKey)).filter((id) => id !== undefined && id !== null)
  const filteredRowIds = sortedData.map((row) => getRowId(row, rowIdKey)).filter((id) => id !== undefined && id !== null)
  const targetRowIds = selectAllScope === 'filtered' ? filteredRowIds : pageRowIds

  const allVisibleChecked = selectableRows && targetRowIds.length > 0 && targetRowIds.every((id) => selectedRowIds.includes(id))
  const someVisibleChecked = selectableRows && targetRowIds.some((id) => selectedRowIds.includes(id))

  useEffect(() => {
    setPage(1)
  }, [debouncedQuery, data, effectivePageSize])

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedQuery(query), 300)
    return () => window.clearTimeout(timer)
  }, [query])

  useEffect(() => {
    // Cards on phones AND tablets (< lg); full table only on laptops/desktops/TV.
    const mediaQuery = window.matchMedia('(max-width: 1023px)')
    const updateCardState = () => setIsCardView(mediaQuery.matches)
    updateCardState()
    mediaQuery.addEventListener('change', updateCardState)
    return () => mediaQuery.removeEventListener('change', updateCardState)
  }, [])

  const handleColumnSort = (column) => {
    if (!isSortableColumn(column)) {
      return
    }
    setSortState((prev) => {
      if (prev.key !== column.key) {
        return { key: column.key, direction: 'asc' }
      }
      if (prev.direction === 'asc') {
        return { key: column.key, direction: 'desc' }
      }
      return { key: column.key, direction: 'asc' }
    })
  }

  const toggleAllVisible = (checked) => {
    if (!onSelectedRowIdsChange) {
      return
    }
    if (checked) {
      const merged = Array.from(new Set([...selectedRowIds, ...targetRowIds]))
      onSelectedRowIdsChange(merged)
      return
    }
    const reduced = selectedRowIds.filter((id) => !targetRowIds.includes(id))
    onSelectedRowIdsChange(reduced)
  }

  const toggleSingle = (rowId, checked) => {
    if (!onSelectedRowIdsChange) {
      return
    }
    if (checked) {
      onSelectedRowIdsChange(selectedRowIds.includes(rowId) ? selectedRowIds : [...selectedRowIds, rowId])
      return
    }
    onSelectedRowIdsChange(selectedRowIds.filter((id) => id !== rowId))
  }

  const renderDefaultActions = (row) => {
    if (!hasCallbacks || hasInlineActionsColumn) {
      return null
    }
    return (
      <>
        {onEdit ? (
          <button
            type="button"
            onClick={() => onEdit(row)}
            className="w-full rounded-lg border border-brand-line px-2.5 py-2 text-left text-xs text-brand-white transition hover:border-brand-blue"
          >
            Editar
          </button>
        ) : null}
        {onDelete ? (
          <button
            type="button"
            onClick={() => onDelete(row)}
            className="w-full rounded-lg border border-brand-red/40 px-2.5 py-2 text-left text-xs text-red-200 transition hover:bg-brand-red/10"
          >
            Eliminar
          </button>
        ) : null}
      </>
    )
  }

  // Content for the actions menu (gear) — inline actions column, or the default Edit/Delete.
  const renderMenuActions = (row) => {
    if (actionColumn) {
      return actionColumn.render?.(row)
    }
    return renderDefaultActions(row)
  }

  const hasMenuActions = Boolean(actionColumn) || (hasCallbacks && !hasInlineActionsColumn)

  const renderTableCell = (column, row) => {
    const cellContent = column.render ? column.render(row) : formatCellValue(row[column.key])
    if (isActionsColumn(column)) {
      return <RowActionsDropdown>{cellContent}</RowActionsDropdown>
    }
    return cellContent
  }

  const renderPlainCell = (column, row) => {
    if (column.mobileRender) {
      return column.mobileRender(row)
    }
    return column.render ? column.render(row) : formatCellValue(row[column.key])
  }

  const renderSortIndicator = (column) => {
    if (!isSortableColumn(column)) {
      return null
    }
    if (sortState.key !== column.key) {
      return <span className="text-brand-muted">↕</span>
    }
    return <span className="text-brand-blue">{sortState.direction === 'asc' ? '↑' : '↓'}</span>
  }

  const startItem = sortedData.length === 0 ? 0 : (safePage - 1) * effectivePageSize + 1
  const endItem = sortedData.length === 0 ? 0 : Math.min(safePage * effectivePageSize, sortedData.length)
  const selectedDetailRowId = selectedDetailRow ? getRowId(selectedDetailRow, rowIdKey) : null
  const scrollStyle = maxBodyHeight ? { maxHeight: maxBodyHeight } : undefined

  return (
    <div className="overflow-hidden rounded-2xl border border-brand-line bg-brand-soft/40 p-3 sm:p-4">
      <TableSearch value={query} onChange={setQuery} />

      {loading ? (
        <div className="space-y-2">
          <div className="h-12 animate-pulse rounded-xl bg-brand-line/60" />
          <div className="h-12 animate-pulse rounded-xl bg-brand-line/40" />
          <div className="h-12 animate-pulse rounded-xl bg-brand-line/30" />
        </div>
      ) : (
        <>
          {/* ---------- Desktop / TV: full table (lg and up) ---------- */}
          <div
            className={`hidden overflow-x-auto lg:block ${maxBodyHeight ? 'overflow-y-auto' : ''}`}
            style={scrollStyle}
          >
            <table className="min-w-full border-separate border-spacing-0">
              <thead>
                <tr>
                  {selectableRows ? (
                    <th className="sticky top-0 z-10 border-b border-brand-line bg-brand-panel/95 px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-brand-muted backdrop-blur">
                      <input
                        type="checkbox"
                        className="h-4 w-4 accent-brand-blue"
                        checked={allVisibleChecked}
                        ref={(input) => {
                          if (input) {
                            input.indeterminate = !allVisibleChecked && someVisibleChecked
                          }
                        }}
                        onChange={(event) => toggleAllVisible(event.target.checked)}
                      />
                    </th>
                  ) : null}
                  {columns.map((column) => (
                    <th key={column.key} className="sticky top-0 z-10 border-b border-brand-line bg-brand-panel/95 px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-brand-muted backdrop-blur">
                      <button
                        type="button"
                        onClick={() => handleColumnSort(column)}
                        className={`inline-flex items-center gap-2 ${isSortableColumn(column) ? 'hover:text-brand-white' : 'cursor-default'}`}
                      >
                        <span>{column.label}</span>
                        {renderSortIndicator(column)}
                      </button>
                    </th>
                  ))}
                  {hasCallbacks && !hasInlineActionsColumn ? (
                    <th className="sticky top-0 z-10 border-b border-brand-line bg-brand-panel/95 px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-brand-muted backdrop-blur">Acciones</th>
                  ) : null}
                </tr>
              </thead>
              <tbody>
                {paginatedData.length === 0 ? (
                  <tr>
                    <td colSpan={columns.length + (hasCallbacks && !hasInlineActionsColumn ? 1 : 0) + (selectableRows ? 1 : 0)} className="px-4 py-10 text-center text-sm text-brand-muted">
                      No hay datos
                    </td>
                  </tr>
                ) : null}

                {paginatedData.map((row, index) => {
                  const rowId = getRowId(row, rowIdKey)
                  return (
                    <tr key={rowId || `${index}-${row?.name || 'row'}`} className="transition-colors hover:bg-brand-soft/50">
                      {selectableRows ? (
                        <td className="border-b border-brand-line/60 px-4 py-3 text-sm text-brand-white">
                          <input type="checkbox" className="h-4 w-4 accent-brand-blue" checked={selectedRowIds.includes(rowId)} onChange={(event) => toggleSingle(rowId, event.target.checked)} />
                        </td>
                      ) : null}
                      {columns.map((column) => (
                        <td key={`${column.key}-${rowId || index}`} className="border-b border-brand-line/60 px-4 py-3 text-sm text-brand-white">
                          {renderTableCell(column, row)}
                        </td>
                      ))}
                      {hasCallbacks && !hasInlineActionsColumn ? <td className="border-b border-brand-line/60 px-4 py-3"><RowActionsDropdown>{renderDefaultActions(row)}</RowActionsDropdown></td> : null}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          {/* ---------- Phone / Tablet: relevant cards (below lg) ---------- */}
          <div
            className={`grid grid-cols-1 gap-3 sm:grid-cols-2 lg:hidden ${maxBodyHeight ? 'overflow-y-auto' : ''}`}
            style={scrollStyle}
          >
            {paginatedData.length === 0 ? <p className="rounded-xl border border-brand-line bg-black/20 p-4 text-center text-sm text-brand-muted sm:col-span-2">No hay datos</p> : null}

            {paginatedData.map((row, index) => {
              const rowId = getRowId(row, rowIdKey)
              const titleColumn = mobileZones.title
              const isSelected = selectableRows && selectedRowIds.includes(rowId)
              const primaryAction = actionColumn?.mobilePrimary?.(row)
              return (
                <article
                  key={rowId || `${index}-${row?.name || 'card'}`}
                  className={`flex flex-col rounded-xl border bg-brand-panel/70 p-3.5 transition ${isSelected ? 'border-brand-blue/70 ring-1 ring-brand-blue/40' : 'border-brand-line'}`}
                >
                  {/* Title row: name + status chips + (optional) select */}
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0 flex-1">
                      <div className="truncate font-display text-[15px] font-semibold leading-tight text-brand-white">
                        {titleColumn ? renderPlainCell(titleColumn, row) : '-'}
                      </div>
                    </div>
                    {selectableRows ? (
                      <input
                        type="checkbox"
                        aria-label="Seleccionar fila"
                        className="mt-0.5 h-5 w-5 shrink-0 accent-brand-blue"
                        checked={isSelected}
                        onChange={(event) => toggleSingle(rowId, event.target.checked)}
                      />
                    ) : null}
                  </div>

                  {mobileZones.meta.length ? (
                    <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                      {mobileZones.meta.map((column) => (
                        <span key={`${column.key}-${rowId || index}-meta`}>{renderPlainCell(column, row)}</span>
                      ))}
                    </div>
                  ) : null}

                  {/* Secondary: labeled, compact */}
                  {mobileZones.secondary.length ? (
                    <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2">
                      {mobileZones.secondary.map((column) => (
                        <div key={`${column.key}-${rowId || index}-sec`} className="min-w-0">
                          <dt className="truncate text-[10px] font-semibold uppercase tracking-wide text-brand-dim">{column.mobileLabel || column.label}</dt>
                          <dd className="mt-0.5 truncate text-[13px] text-brand-white">{renderPlainCell(column, row)}</dd>
                        </div>
                      ))}
                    </dl>
                  ) : null}

                  {/* Footer: primary action + detail + overflow menu */}
                  <div className="mt-3.5 flex items-center gap-2 border-t border-brand-line pt-3">
                    {primaryAction ? <div className="flex-1 [&_button]:min-h-11 [&_button]:w-full">{primaryAction}</div> : null}
                    <button
                      type="button"
                      onClick={() => setSelectedDetailRow(row)}
                      className={`min-h-11 rounded-lg border border-brand-line px-3 py-2 text-xs font-semibold text-brand-white transition hover:border-brand-blue ${primaryAction ? 'shrink-0' : 'flex-1'}`}
                    >
                      Ver detalle
                    </button>
                    {hasMenuActions && !primaryAction ? (
                      <div className="shrink-0 [&_button]:min-h-9 [&_button]:text-xs">
                        <RowActionsDropdown align="left">{renderMenuActions(row)}</RowActionsDropdown>
                      </div>
                    ) : null}
                  </div>
                </article>
              )
            })}
          </div>

          <TablePagination
            page={safePage}
            totalPages={totalPages}
            pageSize={effectivePageSize}
            pageSizeOptions={effectivePageSizeOptions}
            startItem={startItem}
            endItem={endItem}
            totalItems={sortedData.length}
            onPageSizeChange={setPageSize}
            onPrevious={() => setPage((prev) => Math.max(1, prev - 1))}
            onNext={() => setPage((prev) => Math.min(totalPages, prev + 1))}
          />

          {selectedDetailRow ? createPortal(
            <div className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto bg-black/70 p-4 backdrop-blur-sm" onClick={() => setSelectedDetailRow(null)}>
              <div
                className="max-h-[85vh] w-full overflow-y-auto rounded-2xl border border-brand-line bg-brand-soft p-4 shadow-float animate-scale-in sm:max-w-lg"
                onClick={(event) => event.stopPropagation()}
              >
                <div className="sticky top-0 -mx-4 -mt-4 mb-2 flex items-center justify-between gap-3 border-b border-brand-line bg-brand-soft/95 px-4 py-3 backdrop-blur">
                  <h2 className="font-display text-base font-semibold text-brand-white">
                    {mobileZones.title ? renderPlainCell(mobileZones.title, selectedDetailRow) : 'Detalle'}
                  </h2>
                  <button
                    type="button"
                    onClick={() => setSelectedDetailRow(null)}
                    aria-label="Cerrar detalle"
                    className="inline-flex min-h-9 items-center rounded-lg border border-brand-line px-3 py-1.5 text-sm font-semibold text-brand-white transition hover:border-brand-blue"
                  >
                    Cerrar
                  </button>
                </div>
                <div className="divide-y divide-brand-line">
                  {detailColumns.map((column) => (
                    <div key={`${column.key}-${selectedDetailRowId || 'detail'}`} className="flex items-start justify-between gap-4 py-2.5">
                      <p className="shrink-0 text-xs font-semibold uppercase tracking-wide text-brand-dim">{column.label}</p>
                      <div className="min-w-0 text-right text-sm text-brand-white">{renderPlainCell(column, selectedDetailRow)}</div>
                    </div>
                  ))}
                </div>
                {hasMenuActions ? (
                  <div className="mt-4 space-y-2 border-t border-brand-line pt-4">
                    <p className="text-xs font-semibold uppercase tracking-wide text-brand-dim">Acciones</p>
                    {renderMenuActions(selectedDetailRow)}
                  </div>
                ) : null}
              </div>
            </div>,
            document.body,
          ) : null}
        </>
      )}
    </div>
  )
}
