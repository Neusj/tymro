import TablePagination from './ui/TablePagination'
import TableSearch from './ui/TableSearch'
import { formatDate } from '../utils/format'

function formatDateTime(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return `${formatDate(value)} ${date.toLocaleTimeString('es-CL', { hour: '2-digit', minute: '2-digit' })}`
}

function statusBadge(status) {
  if (status === 'finished') {
    return { text: 'Dictada', className: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200' }
  }
  if (status === 'cancelled') {
    return { text: 'Anulada', className: 'border-brand-red/50 bg-brand-red/10 text-red-200' }
  }
  return { text: 'En curso', className: 'border-brand-orange/50 bg-brand-orange/10 text-amber-200' }
}

function StatusChip({ status }) {
  const badge = statusBadge(status)
  return (
    <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold ${badge.className}`}>
      {badge.text}
    </span>
  )
}

function sessionEndAt(item) {
  return item.finished_at || item.cancelled_at
}

function MobileRow({ item, showStudent, showTeacher, onFinish, onCancel, finishingId, cancellingId }) {
  return (
    <article className="rounded-xl border border-brand-line bg-brand-panel/70 p-3.5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-display text-[15px] font-semibold leading-tight text-brand-white">
            {showStudent ? item.student || '-' : item.teacher || '-'}
          </p>
          <p className="mt-1 text-xs text-brand-muted">{item.student_plan_name || 'Sin plan'}</p>
        </div>
        <StatusChip status={item.status} />
      </div>
      <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2 text-sm">
        {showTeacher ? (
          <div className="min-w-0">
            <dt className="text-[10px] font-semibold uppercase tracking-wide text-brand-dim">Profesor</dt>
            <dd className="truncate text-brand-white">{item.teacher || '-'}</dd>
          </div>
        ) : null}
        {showStudent ? (
          <div className="min-w-0">
            <dt className="text-[10px] font-semibold uppercase tracking-wide text-brand-dim">Alumno</dt>
            <dd className="truncate text-brand-white">{item.student || '-'}</dd>
          </div>
        ) : null}
        <div>
          <dt className="text-[10px] font-semibold uppercase tracking-wide text-brand-dim">Inicio</dt>
          <dd className="text-brand-white">{formatDateTime(item.confirmed_at)}</dd>
        </div>
        <div>
          <dt className="text-[10px] font-semibold uppercase tracking-wide text-brand-dim">Fin</dt>
          <dd className="text-brand-white">{formatDateTime(sessionEndAt(item))}</dd>
        </div>
        <div className="min-w-0">
          <dt className="text-[10px] font-semibold uppercase tracking-wide text-brand-dim">Sede</dt>
          <dd className="truncate text-brand-white">{item.branch || '-'}</dd>
        </div>
        <div className="min-w-0">
          <dt className="text-[10px] font-semibold uppercase tracking-wide text-brand-dim">Disciplina</dt>
          <dd className="truncate text-brand-white">{item.discipline || item.class_type || '-'}</dd>
        </div>
      </dl>
      {(onFinish || onCancel) ? (
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          {onFinish && item.can_finish && item.status === 'confirmed' ? (
            <button
              type="button"
              onClick={() => onFinish(item.id)}
              disabled={finishingId === item.id}
              className="min-h-11 w-full rounded-lg bg-brand-orange px-4 py-2 text-sm font-semibold text-brand-black transition hover:bg-amber-300 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {finishingId === item.id ? 'Finalizando...' : 'Finalizar clase'}
            </button>
          ) : null}
          {onCancel && item.can_cancel ? (
            <button
              type="button"
              onClick={() => onCancel(item)}
              disabled={cancellingId === item.id}
              className="min-h-11 w-full rounded-lg border border-brand-red/60 px-4 py-2 text-sm font-semibold text-red-200 transition hover:bg-brand-red/10 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {cancellingId === item.id ? 'Anulando...' : 'Anular clase'}
            </button>
          ) : null}
        </div>
      ) : null}
    </article>
  )
}

export default function PersonalizedClassesTable({
  items = [],
  loading = false,
  search = '',
  status = 'all',
  pagination,
  showStudent = true,
  showTeacher = true,
  onSearchChange,
  onStatusChange,
  onPageChange,
  onPageSizeChange,
  onFinish,
  onCancel,
  finishingId,
  cancellingId,
}) {
  const count = Number(pagination?.count || 0)
  const page = Number(pagination?.page || 1)
  const pageSize = Number(pagination?.page_size || 10)
  const totalPages = Number(pagination?.total_pages || 1)
  const startItem = count === 0 ? 0 : (page - 1) * pageSize + 1
  const endItem = count === 0 ? 0 : Math.min(page * pageSize, count)
  const hasActions = Boolean(onFinish || onCancel)
  const columnCount = 5 + (showStudent ? 1 : 0) + (showTeacher ? 1 : 0) + (hasActions ? 1 : 0)

  return (
    <div className="overflow-hidden rounded-2xl border border-brand-line bg-brand-soft/40 p-3 sm:p-4">
      <div className="grid gap-3 lg:grid-cols-[1fr_220px]">
        <TableSearch value={search} onChange={onSearchChange} />
        <label className="mb-4 block">
          <span className="sr-only">Estado</span>
          <select
            value={status}
            onChange={(event) => onStatusChange(event.target.value)}
            className="min-h-11 w-full rounded-xl border border-brand-line bg-black/30 px-3 py-2 text-sm text-brand-white focus:border-brand-blue focus:outline-none"
          >
            <option value="all">Todos los estados</option>
            <option value="confirmed">En curso</option>
            <option value="finished">Dictadas</option>
            <option value="cancelled">Anuladas</option>
          </select>
        </label>
      </div>

      {loading ? (
        <div className="space-y-2">
          <div className="h-12 animate-pulse rounded-xl bg-brand-line/60" />
          <div className="h-12 animate-pulse rounded-xl bg-brand-line/40" />
          <div className="h-12 animate-pulse rounded-xl bg-brand-line/30" />
        </div>
      ) : (
        <>
          <div className="hidden overflow-x-auto lg:block">
            <table className="min-w-full border-separate border-spacing-0">
              <thead>
                <tr>
                  <th className="border-b border-brand-line bg-brand-panel/95 px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-brand-muted">Estado</th>
                  {showStudent ? <th className="border-b border-brand-line bg-brand-panel/95 px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-brand-muted">Alumno</th> : null}
                  {showTeacher ? <th className="border-b border-brand-line bg-brand-panel/95 px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-brand-muted">Profesor</th> : null}
                  <th className="border-b border-brand-line bg-brand-panel/95 px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-brand-muted">Plan</th>
                  <th className="border-b border-brand-line bg-brand-panel/95 px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-brand-muted">Inicio</th>
                  <th className="border-b border-brand-line bg-brand-panel/95 px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-brand-muted">Fin</th>
                  <th className="border-b border-brand-line bg-brand-panel/95 px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-brand-muted">Sede</th>
                  {hasActions ? <th className="border-b border-brand-line bg-brand-panel/95 px-4 py-3 text-right text-xs font-semibold uppercase tracking-wide text-brand-muted">Acciones</th> : null}
                </tr>
              </thead>
              <tbody>
                {items.length === 0 ? (
                  <tr>
                    <td colSpan={columnCount} className="px-4 py-10 text-center text-sm text-brand-muted">No hay clases personalizadas</td>
                  </tr>
                ) : null}
                {items.map((item) => (
                  <tr key={item.id} className="transition-colors hover:bg-brand-soft/50">
                    <td className="border-b border-brand-line/60 px-4 py-3 text-sm"><StatusChip status={item.status} /></td>
                    {showStudent ? <td className="border-b border-brand-line/60 px-4 py-3 text-sm font-medium text-brand-white">{item.student || '-'}</td> : null}
                    {showTeacher ? <td className="border-b border-brand-line/60 px-4 py-3 text-sm text-brand-white">{item.teacher || '-'}</td> : null}
                    <td className="border-b border-brand-line/60 px-4 py-3 text-sm text-brand-white">{item.student_plan_name || '-'}</td>
                    <td className="border-b border-brand-line/60 px-4 py-3 text-sm text-brand-muted">{formatDateTime(item.confirmed_at)}</td>
                    <td className="border-b border-brand-line/60 px-4 py-3 text-sm text-brand-muted">{formatDateTime(sessionEndAt(item))}</td>
                    <td className="border-b border-brand-line/60 px-4 py-3 text-sm text-brand-muted">{item.branch || '-'}</td>
                    {hasActions ? (
                      <td className="border-b border-brand-line/60 px-4 py-3 text-right">
                        <div className="flex justify-end gap-2">
                          {onFinish && item.can_finish && item.status === 'confirmed' ? (
                            <button
                              type="button"
                              onClick={() => onFinish(item.id)}
                              disabled={finishingId === item.id}
                              className="min-h-10 rounded-lg bg-brand-orange px-3 py-2 text-xs font-semibold text-brand-black transition hover:bg-amber-300 disabled:cursor-not-allowed disabled:opacity-60"
                            >
                              {finishingId === item.id ? 'Finalizando...' : 'Finalizar clase'}
                            </button>
                          ) : null}
                          {onCancel && item.can_cancel ? (
                            <button
                              type="button"
                              onClick={() => onCancel(item)}
                              disabled={cancellingId === item.id}
                              className="min-h-10 rounded-lg border border-brand-red/60 px-3 py-2 text-xs font-semibold text-red-200 transition hover:bg-brand-red/10 disabled:cursor-not-allowed disabled:opacity-60"
                            >
                              {cancellingId === item.id ? 'Anulando...' : 'Anular clase'}
                            </button>
                          ) : null}
                        </div>
                      </td>
                    ) : null}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:hidden">
            {items.length === 0 ? <p className="rounded-xl border border-brand-line bg-black/20 p-4 text-center text-sm text-brand-muted sm:col-span-2">No hay clases personalizadas</p> : null}
            {items.map((item) => (
              <MobileRow
                key={item.id}
                item={item}
                showStudent={showStudent}
                showTeacher={showTeacher}
                onFinish={onFinish}
                onCancel={onCancel}
                finishingId={finishingId}
                cancellingId={cancellingId}
              />
            ))}
          </div>

          <TablePagination
            page={page}
            totalPages={totalPages}
            pageSize={pageSize}
            pageSizeOptions={[10, 25, 50, 100]}
            startItem={startItem}
            endItem={endItem}
            totalItems={count}
            onPageSizeChange={onPageSizeChange}
            onPrevious={() => onPageChange(Math.max(1, page - 1))}
            onNext={() => onPageChange(Math.min(totalPages, page + 1))}
          />
        </>
      )}
    </div>
  )
}
