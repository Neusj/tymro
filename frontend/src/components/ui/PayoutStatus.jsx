// Estado de pago de un profesor en un período (profe × mes).
// Hace EXPLÍCITO el caso parcial: si el total vivo creció tras marcar pagado,
// muestra "Pagado $X · fecha · Pendiente $Y" para que el saldo nuevo no quede oculto.
function clp(value) {
  return `$${Math.round(Number(value) || 0).toLocaleString('es-CL', { maximumFractionDigits: 0 })}`
}

function formatFullDate(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleDateString('es-CL', { day: '2-digit', month: '2-digit', year: 'numeric' })
}

const PILL = 'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px] font-semibold'
const PAID = `${PILL} border-emerald-500/40 bg-emerald-500/10 text-emerald-200`
const PENDING = `${PILL} border-amber-500/40 bg-amber-500/10 text-amber-200`

export default function PayoutStatus({ payout, pending = 0 }) {
  const pendingAmount = Number(pending) || 0

  // Sin pago registrado → pendiente (el total ya se muestra en la fila/hero).
  if (!payout) {
    return (
      <span className={PENDING}>
        <span className="h-1.5 w-1.5 rounded-full bg-amber-400" />
        Pendiente
      </span>
    )
  }

  // Pagado pero el total vivo creció después → muestra lo pagado + el saldo nuevo.
  if (pendingAmount > 0) {
    return (
      <span className="inline-flex flex-wrap items-center gap-1.5">
        <span className={PAID}>
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
          Pagado {clp(payout.amount)} · {formatFullDate(payout.paid_at)}
        </span>
        <span className={PENDING}>
          <span className="h-1.5 w-1.5 rounded-full bg-amber-400" />
          Pendiente {clp(pendingAmount)}
        </span>
      </span>
    )
  }

  // Pagado y conciliado.
  return (
    <span className={PAID}>
      <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
      Pagado · {formatFullDate(payout.paid_at)}
    </span>
  )
}
