import { useEffect, useState } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { reportsApi } from '../api/client'
import DashboardHeader from '../components/DashboardHeader'
import { clp, firstApiError } from '../utils/format'

function formatDateTime(value) {
  if (!value) return null
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return null
  return date.toLocaleString('es-CL', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}

// Campos de un pago MANUAL (efectivo/transferencia/tarjeta/cheque/registrado a mano). `show` por default
// es "el valor no es null/undefined/''" — regla dura del pedido: nunca una etiqueta con
// "—" ni "N/A" colgando, si el backend no manda el dato la fila entera no se dibuja.
const MANUAL_FIELDS = [
  { key: 'amount', label: 'Monto', format: (value) => clp(value) },
  { key: 'plan_amount', label: 'Monto del plan', format: (value) => clp(value), show: (value) => Number(value) > 0 },
  { key: 'enrollment_fee_amount', label: 'Matricula', format: (value) => clp(value), show: (value) => Number(value) > 0 },
  { key: 'recorded_at', label: 'Fecha de registro', format: formatDateTime },
  { key: 'method_label', label: 'Método' },
  { key: 'reference', label: 'Referencia' },
  { key: 'student_name', label: 'Alumno' },
  { key: 'plan_name', label: 'Plan' },
  { key: 'branch_name', label: 'Sede' },
  // Sí lleva "Registrado por": a un pago manual lo tipeó una persona de recepción/admin.
  { key: 'recorded_by_name', label: 'Registrado por' },
]

// Campos de un pago de MERCADOPAGO. A propósito NO incluye recorded_by_*: a este pago lo
// registró el webhook de MercadoPago al confirmar el cobro, no una persona del gimnasio —
// mostrar "Registrado por" inventaría un humano donde no lo hay. Mismo criterio inverso
// que en MANUAL_FIELDS: cada tipo muestra SOLO lo que le corresponde a su origen.
const MERCADOPAGO_FIELDS = [
  { key: 'amount', label: 'Monto', format: (value) => clp(value) },
  { key: 'currency', label: 'Moneda' },
  { key: 'collected_at', label: 'Fecha de cobro', format: formatDateTime },
  {
    key: 'status',
    label: 'Estado',
    format: (value, detail) => (detail.status_detail ? `${value} (${detail.status_detail})` : value),
  },
  { key: 'provider', label: 'Proveedor' },
  { key: 'provider_payment_id', label: 'ID de transacción' },
  { key: 'processed_at', label: 'Procesado el', format: formatDateTime },
  { key: 'refunded_at', label: 'Devuelto el', format: formatDateTime },
  // Solo si > 0: refunded_amount=0 es el caso normal (nunca se devolvió nada) y mostrarlo
  // siempre sería ruido permanente en la inmensa mayoría de los pagos.
  { key: 'refunded_amount', label: 'Monto devuelto', format: (value) => clp(value), show: (value) => Number(value) > 0 },
  { key: 'plan_amount', label: 'Monto del plan', format: (value) => clp(value) },
  { key: 'enrollment_fee_amount', label: 'Matrícula', format: (value) => clp(value), show: (value) => Number(value) > 0 },
  { key: 'student_name', label: 'Alumno' },
  { key: 'plan_name', label: 'Plan' },
  { key: 'branch_name', label: 'Sede' },
]

function FieldRow({ label, value }) {
  return (
    <div className="flex flex-col gap-0.5 border-b border-brand-line/40 py-2.5 last:border-b-0 sm:flex-row sm:items-baseline sm:justify-between sm:gap-4">
      <span className="text-xs uppercase tracking-wide text-brand-dim">{label}</span>
      <span className="text-sm font-medium text-brand-white sm:text-right">{value}</span>
    </div>
  )
}

export default function GymAdminPaymentDetailPage() {
  const { kind, id } = useParams()
  const [searchParams] = useSearchParams()
  const [detail, setDetail] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    const load = async () => {
      setLoading(true)
      setError('')
      try {
        const data = await reportsApi.revenuePaymentDetail(kind, id)
        if (active) setDetail(data)
      } catch (apiError) {
        if (active) {
          // 404 (pago de otra organización, o que no existe): mensaje sobrio y genérico.
          // NO se usa el detail que mande el backend para este caso — cualquier texto más
          // específico ("no pertenece a tu organización", "id inválido") le confirmaría a
          // alguien que está adivinando IDs que casi encontró algo.
          if (apiError?.response?.status === 404) {
            setError('No se encontró ese pago.')
          } else {
            setError(firstApiError(apiError?.response?.data, 'No se pudo cargar el detalle de este pago.'))
          }
          setDetail(null)
        }
      } finally {
        if (active) setLoading(false)
      }
    }
    load()
    return () => {
      active = false
    }
  }, [kind, id])

  // Mismo período/sucursal con los que se entró, para que "volver" no resetee el filtro.
  const carryQuery = new URLSearchParams()
  ;['date_from', 'date_to', 'branch_id'].forEach((key) => {
    const value = searchParams.get(key)
    if (value) carryQuery.set(key, value)
  })
  const carryQueryString = carryQuery.toString()

  // El "método" de la capa 2 a la que hay que volver (mercadopago | cash | transfer |
  // unknown) solo se sabe con certeza una vez que cargó el detalle — para un pago manual,
  // `kind` es siempre 'manual' sin importar si fue efectivo/transferencia/sin registrar,
  // así que no se puede derivar de la URL sola. Antes de que cargue, "volver" apunta un
  // nivel más arriba (capa 1), que siempre es una respuesta válida.
  const backHref = detail?.method
    ? `/gym-admin/reports/revenue/${detail.method}${carryQueryString ? `?${carryQueryString}` : ''}`
    : `/gym-admin/reports/revenue${carryQueryString ? `?${carryQueryString}` : ''}`

  const fields = kind === 'mercadopago' ? MERCADOPAGO_FIELDS : MANUAL_FIELDS
  const title = detail
    ? `Pago — ${detail.method_label || (kind === 'mercadopago' ? 'MercadoPago' : 'Manual')}`
    : 'Detalle del pago'

  return (
    <div className="space-y-5">
      <DashboardHeader
        title={title}
        subtitle="Toda la información registrada de este pago puntual."
        back={{ to: backHref, label: 'Volver' }}
      />

      {error ? (
        <p className="rounded-lg border border-danger-line bg-danger-soft px-3 py-2 text-sm text-red-200">{error}</p>
      ) : null}

      <section className="card-surface p-4 sm:p-5">
        {loading ? (
          <p className="py-8 text-center text-sm text-brand-muted">Cargando…</p>
        ) : !detail ? null : (
          <div>
            {fields.map((field) => {
              const rawValue = detail[field.key]
              const visible = field.show
                ? field.show(rawValue, detail)
                : rawValue !== null && rawValue !== undefined && rawValue !== ''
              if (!visible) return null
              const displayValue = field.format ? field.format(rawValue, detail) : rawValue
              if (displayValue === null || displayValue === undefined || displayValue === '') return null
              return <FieldRow key={field.key} label={field.label} value={displayValue} />
            })}
          </div>
        )}
      </section>
    </div>
  )
}
