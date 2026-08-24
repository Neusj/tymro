import { useEffect, useState } from 'react'
import DashboardHeader from '../components/DashboardHeader'
import EmptyState from '../components/EmptyState'
import { getPlans, paymentsApi } from '../api/client'
import { clp, firstApiError } from '../utils/format'

const PLAN_TYPE_LABEL = {
  monthly: 'Mensual',
  pack: 'Pack',
  single_class: 'Clase suelta',
  personalized: 'Clases personalizadas',
}

// Un plan es "comprable" si es público, activo y no es trial ni giftcard.
// El backend re-valida esta regla en /checkout/; aquí es solo de presentación.
const isPurchasable = (plan) =>
  plan?.is_public && plan?.is_active && !['trial', 'giftcard'].includes(plan?.plan_type)

function planPricing(plan) {
  const price = Number(plan.price) || 0
  const discount = Number(plan.effective_discount_percentage ?? plan.discount_percentage) || 0
  const discountAmount = Number(plan.effective_discount_amount) || 0
  const final = Math.max(0, Math.round(Number(plan.effective_price ?? price * (1 - discount / 100))))
  const source = plan.effective_discount_source || (discount > 0 ? 'plan' : '')
  return { price, discount, discountAmount, final, source }
}

function PlanCard({ plan, onPay, paying }) {
  const { price, discount, discountAmount, final, source } = planPricing(plan)
  const typeLabel = PLAN_TYPE_LABEL[plan.plan_type] || plan.plan_type
  const classesLabel = plan.unlimited_classes ? 'Clases ilimitadas' : `${plan.total_classes} clases`
  const isStudentDiscount = source === 'student_benefit'

  return (
    <article className="relative flex flex-col overflow-hidden rounded-2xl border border-brand-line bg-brand-soft/80 p-5 shadow-soft backdrop-blur-sm transition duration-200 ease-snap hover:-translate-y-0.5 hover:border-brand-orange/50">
      <div className="pointer-events-none absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-brand-orange to-brand-blue" />
      <div className="flex items-start justify-between gap-3">
        <h2 className="font-display text-lg font-semibold text-brand-white">{plan.name}</h2>
        <span className="badge-accent shrink-0">{typeLabel}</span>
      </div>

      <div className="mt-4 space-y-2">
        {discount > 0 ? (
          <div className="mb-1 flex items-center gap-2">
            <span className="text-sm text-brand-dim line-through">{clp(price)}</span>
            <span className="inline-flex items-center rounded-full border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5 text-[11px] font-semibold text-emerald-200">
              {isStudentDiscount ? 'Descuento estudiante' : 'Descuento'} -{discount}%
            </span>
          </div>
        ) : null}
        <p className="font-display text-3xl font-bold leading-none text-brand-white tabular-nums">{clp(final)}</p>
        <div className="rounded-lg border border-brand-line bg-black/20 px-3 py-2 text-xs">
          <div className="flex justify-between gap-3">
            <span className="text-brand-muted">Precio</span>
            <span className="font-medium text-brand-white">{clp(price)}</span>
          </div>
          {isStudentDiscount ? (
            <div className="flex justify-between gap-3">
              <span className="text-brand-muted">Descuento estudiante</span>
              <span className="font-medium text-emerald-200">{discount}% ({clp(discountAmount)})</span>
            </div>
          ) : discount > 0 ? (
            <div className="flex justify-between gap-3">
              <span className="text-brand-muted">Descuento del plan</span>
              <span className="font-medium text-emerald-200">{discount}% ({clp(discountAmount)})</span>
            </div>
          ) : null}
          <div className="mt-1 flex justify-between gap-3 border-t border-brand-line pt-1">
            <span className="text-brand-muted">Total</span>
            <span className="font-semibold text-brand-white">{clp(final)}</span>
          </div>
        </div>
      </div>

      <dl className="mt-4 grid grid-cols-2 gap-2 text-sm">
        <div className="rounded-lg border border-brand-line bg-black/20 px-3 py-2">
          <dt className="text-[11px] uppercase tracking-wide text-brand-dim">Incluye</dt>
          <dd className="mt-0.5 font-medium text-brand-white">{classesLabel}</dd>
        </div>
        <div className="rounded-lg border border-brand-line bg-black/20 px-3 py-2">
          <dt className="text-[11px] uppercase tracking-wide text-brand-dim">Vigencia</dt>
          <dd className="mt-0.5 font-medium text-brand-white">{plan.duration_days} días</dd>
        </div>
      </dl>

      <button
        type="button"
        onClick={() => onPay(plan)}
        disabled={paying}
        className="mt-5 inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-xl bg-brand-blue px-4 py-2 text-sm font-semibold text-white transition hover:brightness-110 active:brightness-95 disabled:cursor-not-allowed disabled:opacity-60"
      >
        {paying ? 'Redirigiendo…' : 'Pagar'}
      </button>
    </article>
  )
}

export default function StudentBuyPlanPage() {
  const [plans, setPlans] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [payingId, setPayingId] = useState(null)

  useEffect(() => {
    let active = true
    const load = async () => {
      setLoading(true)
      setError('')
      try {
        const data = await getPlans()
        if (active) setPlans((Array.isArray(data) ? data : []).filter(isPurchasable))
      } catch (apiError) {
        if (active) setError(firstApiError(apiError?.response?.data, 'No se pudieron cargar los planes.'))
      } finally {
        if (active) setLoading(false)
      }
    }
    load()
    return () => { active = false }
  }, [])

  const handlePay = async (plan) => {
    setPayingId(plan.id)
    setError('')
    try {
      const { redirect_url: url } = await paymentsApi.checkout({ planId: plan.id })
      if (!url) throw new Error('sin url')
      window.location.assign(url)
    } catch (apiError) {
      setPayingId(null)
      const statusCode = apiError?.response?.status
      if (statusCode === 409) {
        setError('El gimnasio aún no habilitó pagos en línea. Escríbeles para activarlo.')
      } else if (statusCode === 400) {
        setError(firstApiError(apiError?.response?.data, 'No se pudo iniciar el pago de este plan.'))
      } else {
        setError(firstApiError(apiError?.response?.data, 'No se pudo iniciar el pago. Inténtalo de nuevo.'))
      }
    }
  }

  return (
    <div className="space-y-6">
      <DashboardHeader
        title="Comprar plan"
        subtitle="Elige un plan y paga en línea con MercadoPago. El pago es seguro y lo procesa MercadoPago."
      />

      {error ? <p className="rounded-lg border border-brand-red/50 bg-brand-red/10 px-3 py-2 text-sm text-red-200">{error}</p> : null}

      {loading ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-56 animate-pulse rounded-2xl border border-brand-line bg-brand-line/30" />
          ))}
        </div>
      ) : plans.length === 0 ? (
        <EmptyState
          title="No hay planes disponibles para comprar"
          description="Por ahora tu gimnasio no tiene planes públicos a la venta. Consúltales por otras opciones."
        />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {plans.map((plan) => (
            <PlanCard key={plan.id} plan={plan} onPay={handlePay} paying={payingId === plan.id} />
          ))}
        </div>
      )}
    </div>
  )
}
