import { useEffect, useState } from 'react'
import DashboardHeader from '../components/DashboardHeader'
import TablePagination from '../components/ui/TablePagination'
import { paymentsApi } from '../api/client'
import { firstApiError } from '../utils/format'

const PAGE_SIZE = 25
const PAGE_SIZE_OPTIONS = [10, 25, 50, 100]

const STATUS_OPTIONS = [
  { value: '', label: 'Todos los estados' },
  { value: 'pending', label: 'Pendiente' },
  { value: 'in_process', label: 'En proceso' },
  { value: 'approved', label: 'Aprobado' },
  { value: 'rejected', label: 'Rechazado' },
  { value: 'cancelled', label: 'Cancelado' },
  { value: 'refunded', label: 'Reembolsado' },
]

const STATUS_STYLES = {
  approved: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200',
  rejected: 'border-brand-red/50 bg-brand-red/10 text-red-200',
  cancelled: 'border-brand-red/50 bg-brand-red/10 text-red-200',
  pending: 'border-amber-500/40 bg-amber-500/10 text-amber-200',
  in_process: 'border-amber-500/40 bg-amber-500/10 text-amber-200',
  refunded: 'border-brand-line bg-black/30 text-brand-muted',
}

function formatDateTime(value) {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString('es-CL', {
    day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

function formatMoney(amount, currency) {
  const n = Number(amount)
  if (Number.isNaN(n)) return '—'
  try {
    return n.toLocaleString('es-CL', { style: 'currency', currency: currency || 'CLP', maximumFractionDigits: 0 })
  } catch {
    return `${n} ${currency || ''}`.trim()
  }
}

function StatusBadge({ status }) {
  const style = STATUS_STYLES[status] || 'border-brand-line bg-black/30 text-brand-muted'
  return (
    <span className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-[11px] font-semibold ${style}`}>
      {status}
    </span>
  )
}

export default function GymAdminPaymentsTransactionsPage() {
  const [rows, setRows] = useState([])
  const [count, setCount] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(PAGE_SIZE)
  const [status, setStatus] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    const load = async () => {
      setLoading(true)
      setError('')
      try {
        const data = await paymentsApi.listTransactions({ page, pageSize, status, dateFrom, dateTo })
        if (!active) return
        setRows(Array.isArray(data?.results) ? data.results : [])
        setCount(Number(data?.count) || 0)
      } catch (apiError) {
        if (active) setError(firstApiError(apiError?.response?.data, 'No se pudieron cargar las transacciones.'))
      } finally {
        if (active) setLoading(false)
      }
    }
    load()
    return () => { active = false }
  }, [page, pageSize, status, dateFrom, dateTo])

  const totalPages = Math.max(1, Math.ceil(count / pageSize))
  const startItem = count === 0 ? 0 : (page - 1) * pageSize + 1
  const endItem = Math.min(page * pageSize, count)

  const onFilterChange = (setter) => (event) => {
    setPage(1)
    setter(event.target.value)
  }

  return (
    <div className="space-y-6">
      <DashboardHeader
        title="Transacciones"
        subtitle="Pagos de tus alumnos: fecha, alumno, concepto, monto y estado. Solo lectura."
        back={{ to: '/gym-admin/dashboard', label: 'Dashboard' }}
      />

      {error ? <p className="rounded-lg border border-brand-red/50 bg-brand-red/10 px-3 py-2 text-sm text-red-200">{error}</p> : null}

      <div className="card-surface p-4 sm:p-6">
        <div className="mb-4 flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1 text-xs text-brand-muted">
            Estado
            <select
              value={status}
              onChange={onFilterChange(setStatus)}
              className="rounded-lg border border-brand-line bg-black/30 px-2 py-1.5 text-sm text-brand-white focus:border-brand-blue focus:outline-none"
            >
              {STATUS_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs text-brand-muted">
            Desde
            <input type="date" value={dateFrom} onChange={onFilterChange(setDateFrom)}
              className="rounded-lg border border-brand-line bg-black/30 px-2 py-1.5 text-sm text-brand-white focus:border-brand-blue focus:outline-none" />
          </label>
          <label className="flex flex-col gap-1 text-xs text-brand-muted">
            Hasta
            <input type="date" value={dateTo} onChange={onFilterChange(setDateTo)}
              className="rounded-lg border border-brand-line bg-black/30 px-2 py-1.5 text-sm text-brand-white focus:border-brand-blue focus:outline-none" />
          </label>
        </div>

        {loading ? (
          <p className="py-8 text-center text-sm text-brand-muted">Cargando transacciones…</p>
        ) : rows.length === 0 ? (
          <p className="py-8 text-center text-sm text-brand-muted">Sin transacciones para los filtros actuales.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-left text-sm">
              <thead className="text-[11px] uppercase tracking-wide text-brand-dim">
                <tr className="border-b border-brand-line">
                  <th className="py-2 pr-3 font-semibold">Fecha</th>
                  <th className="py-2 pr-3 font-semibold">Alumno</th>
                  <th className="py-2 pr-3 font-semibold">Concepto</th>
                  <th className="py-2 pr-3 font-semibold text-right">Monto</th>
                  <th className="py-2 pr-3 font-semibold">Estado</th>
                  <th className="py-2 pr-3 font-semibold">Activó plan</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((tx) => (
                  <tr key={tx.id} className="border-b border-brand-line/50">
                    <td className="py-2 pr-3 text-brand-muted">{formatDateTime(tx.created_at)}</td>
                    <td className="py-2 pr-3">
                      <div className="font-medium text-brand-white">{tx.student_name}</div>
                      <div className="text-xs text-brand-muted">{tx.student_email || tx.student_phone || '—'}</div>
                    </td>
                    <td className="py-2 pr-3 text-brand-white">{tx.concept}</td>
                    <td className="py-2 pr-3 text-right font-medium text-brand-white">{formatMoney(tx.amount, tx.currency)}</td>
                    <td className="py-2 pr-3"><StatusBadge status={tx.status} /></td>
                    <td className="py-2 pr-3 text-brand-muted">{tx.activated_student_plan ? 'Sí' : 'No'}</td>
                  </tr>
                ))}
              </tbody>
            </table>

            <TablePagination
              page={page}
              totalPages={totalPages}
              pageSize={pageSize}
              pageSizeOptions={PAGE_SIZE_OPTIONS}
              startItem={startItem}
              endItem={endItem}
              totalItems={count}
              onPrevious={() => setPage((p) => Math.max(1, p - 1))}
              onNext={() => setPage((p) => Math.min(totalPages, p + 1))}
              onPageSizeChange={(size) => { setPage(1); setPageSize(size) }}
            />
          </div>
        )}
      </div>
    </div>
  )
}
