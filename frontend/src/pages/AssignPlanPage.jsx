import { useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { assignPlanToUser, getPlans, quotePlanAssignment, usersApi } from '../api/client'
import DashboardHeader from '../components/DashboardHeader'
import { useAuth } from '../auth/AuthContext'
import { clp, todayLocalISO } from '../utils/format'
import { studentSubjectRoleParam } from '../utils/roles'

function firstApiError(detail, fallback) {
  if (!detail) {
    return fallback
  }
  if (typeof detail === 'string') {
    return detail
  }
  if (detail.detail) {
    return detail.detail
  }
  const firstValue = Object.values(detail)[0]
  if (Array.isArray(firstValue) && firstValue[0]) {
    return firstValue[0]
  }
  if (typeof firstValue === 'string') {
    return firstValue
  }
  // El serializer de `payment` anida errores un nivel más (ej. {payment: {amount: [...]}}):
  // se baja recursivamente hasta encontrar el string o la lista real.
  if (firstValue && typeof firstValue === 'object') {
    return firstApiError(firstValue, fallback)
  }
  return fallback
}

function toList(data) {
  if (Array.isArray(data)) {
    return data
  }
  if (Array.isArray(data?.results)) {
    return data.results
  }
  if (Array.isArray(data?.data)) {
    return data.data
  }
  return []
}

const MANUAL_METHOD_OPTIONS = [
  { value: 'cash', label: 'Efectivo' },
  { value: 'transfer', label: 'Transferencia' },
  { value: 'card', label: 'Tarjeta' },
  { value: 'check', label: 'Cheque' },
]

export default function AssignPlanPage() {
  const { user } = useAuth()
  // Solo el admin del gimnasio puede declarar un pago manual: el backend lo rechaza (400)
  // si un superadmin lo intenta, asi que ni se le muestra la opcion (UX, no la restriccion real).
  const isSuperadmin = user?.role === 'superadmin'
  const [searchParams] = useSearchParams()
  const [students, setStudents] = useState([])
  const [plans, setPlans] = useState([])
  const [loading, setLoading] = useState(true)
  const [working, setWorking] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [quote, setQuote] = useState(null)
  const [quoteLoading, setQuoteLoading] = useState(false)
  // Vía por la que se declara el plan: "manual" es el caso comun de venta, por eso es el
  // default para gym_admin. Para superadmin la unica vía posible es "free".
  const [paymentMethod, setPaymentMethod] = useState(isSuperadmin ? 'free' : 'manual')
  const [amount, setAmount] = useState('')
  // Instrumento del cobro manual (P3.2): efectivo o transferencia. Default "cash" porque es
  // el caso mas comun en la recepcion de un gimnasio, asi que el campo nunca viaja vacio aun
  // si el admin no lo toca. El backend lo exige SIEMPRE que method sea "manual" (400 si
  // falta) y lo rechaza si method es "free" (una beca total no tiene instrumento de cobro).
  const [manualMethod, setManualMethod] = useState('cash')
  const [reference, setReference] = useState('')
  // Conceptos adicionales (#12): solo tienen sentido en la vía manual — el backend rechaza
  // (400) `line_items` junto a un pago free, la misma incoherencia que `amount`/`reference`.
  const [lineItems, setLineItems] = useState([])
  const lineItemKeyRef = useRef(0)

  const [form, setForm] = useState({
    user: '',
    plan: '',
    // Fecha LOCAL: `toISOString()` normaliza a UTC y despues de las 20:00 hora de Chile
    // proponia el dia siguiente. El backend deriva `end_date` de este valor, asi que la
    // ventana completa de la membresia se corria un dia.
    start_date: todayLocalISO(),
    discount_percentage: '',
  })

  const paymentVia = isSuperadmin ? 'free' : paymentMethod

  const selectVia = (via) => {
    setPaymentMethod(via)
    // Cambiar de via invalida el error mostrado (ej. "ingresa un monto" de la via pago
    // no tiene sentido si se pasa a gratis).
    setError('')
    if (via === 'free') {
      // Free es beca total: el backend rechaza (400) si viaja algún line_item, así que las
      // filas cargadas se descartan al cambiar de vía (no solo se ocultan).
      setLineItems([])
    }
  }

  const addLineItem = () => {
    lineItemKeyRef.current += 1
    setLineItems((prev) => [...prev, { key: lineItemKeyRef.current, concept: '', amount: '' }])
  }

  const updateLineItem = (key, field, value) => {
    setLineItems((prev) => prev.map((item) => (item.key === key ? { ...item, [field]: value } : item)))
  }

  const removeLineItem = (key) => {
    setLineItems((prev) => prev.filter((item) => item.key !== key))
  }

  const selectedPlan = useMemo(() => plans.find((item) => String(item.id) === String(form.plan)), [plans, form.plan])
  const isUnlimited = Boolean(selectedPlan?.unlimited_classes)
  const totalClasses = Number(selectedPlan?.total_classes || 0)
  const discount = form.discount_percentage !== '' ? Number(form.discount_percentage) : Number(selectedPlan?.discount_percentage || 0)
  const basePrice = Number(selectedPlan?.price || 0)
  // Via gratis = beca total: el backend fija el descuento en 100 y el precio final es $0,
  // sin importar el % que haya quedado cargado en el input (que ademas queda oculto).
  const finalEstimate = paymentVia === 'free' ? 0 : Math.max(basePrice * (1 - discount / 100), 0)

  const normalizedLineItems = () => {
    const valid = []
    let hasInvalid = false
    lineItems.forEach((item) => {
      const conceptTrimmed = item.concept.trim()
      const itemAmountNumber = Number(item.amount)
      const isItemAmountValid = item.amount !== '' && Number.isFinite(itemAmountNumber) && itemAmountNumber > 0
      if (!conceptTrimmed && !isItemAmountValid) {
        return
      }
      if (!conceptTrimmed || !isItemAmountValid) {
        hasInvalid = true
        return
      }
      valid.push({ concept: conceptTrimmed, amount: String(item.amount).trim() })
    })
    return { valid, hasInvalid }
  }

  const loadData = async () => {
    setLoading(true)
    setError('')
    try {
      const organizationId = searchParams.get('organization_id') || ''
      const preselectedUserId = searchParams.get('user_id') || ''
      const params = {}
      if (organizationId) {
        params.organization_id = organizationId
      }
      const [usersData, plansData] = await Promise.all([usersApi.list({ ...params, role: studentSubjectRoleParam }), getPlans()])
      const userList = toList(usersData)
      const planList = toList(plansData)
      setStudents(userList)
      setPlans(planList.filter((item) => item.is_active))
      if (preselectedUserId && userList.some((item) => String(item.id) === String(preselectedUserId))) {
        setForm((prev) => ({ ...prev, user: String(preselectedUserId) }))
      }
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudieron cargar alumnos o planes.'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [searchParams.toString()])

  useEffect(() => {
    let active = true
    const loadQuote = async () => {
      if (!form.user || !form.plan) {
        setQuote(null)
        return
      }
      const { valid, hasInvalid } = normalizedLineItems()
      if (hasInvalid) {
        setQuote(null)
        return
      }
      setQuoteLoading(true)
      try {
        const payload = {
          user: Number(form.user),
          plan: Number(form.plan),
          start_date: form.start_date,
          discount_percentage: paymentVia === 'free' ? 100 : discount,
        }
        if (paymentVia === 'manual' && valid.length > 0) {
          payload.line_items = valid
        }
        const data = await quotePlanAssignment(payload)
        if (!active) return
        setQuote(data)
      } catch {
        if (active) setQuote(null)
      } finally {
        if (active) setQuoteLoading(false)
      }
    }
    loadQuote()
    return () => {
      active = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.user, form.plan, form.start_date, form.discount_percentage, paymentVia, JSON.stringify(lineItems)])

  const submit = async (event) => {
    event.preventDefault()
    if (!form.user || !form.plan) {
      setError('Selecciona usuario y plan.')
      return
    }
    // Validacion de UX solamente: el 400 real (monto/reference/discount invalidos para la
    // via elegida) lo valida el backend y se muestra tal cual llega en el catch.
    let validLineItems = []
    if (paymentVia === 'manual') {
      const amountNumber = Number(amount)
      if (amount === '' || !Number.isFinite(amountNumber) || amountNumber <= 0) {
        setError('Ingresa un monto válido, mayor a $0.')
        return
      }
      // Filas completamente vacías (ej. una fila agregada y no usada) se ignoran en
      // silencio; una fila con SOLO uno de los dos campos cargado es un dato a medio
      // llenar y bloquea el envío igual que el monto principal arriba.
      const normalized = normalizedLineItems()
      validLineItems = normalized.valid
      const hasInvalidLineItem = normalized.hasInvalid
      if (hasInvalidLineItem) {
        setError('Cada concepto adicional necesita un texto y un monto mayor a $0.')
        return
      }
      if (quote && Number(amount) !== Number(quote.total)) {
        setError(`El monto cobrado debe coincidir con el total calculado (${clp(quote.total)}).`)
        return
      }
    }
    setWorking(true)
    setError('')
    setNotice('')
    try {
      const payload = {
        user: Number(form.user),
        plan: Number(form.plan),
        start_date: form.start_date,
      }
      if (paymentVia === 'free') {
        // El backend rechaza (400) un pago free que traiga discount_percentage, amount o
        // reference: por eso ninguna de esas claves se agrega al payload en esta via.
        payload.payment = { method: 'free' }
      } else {
        payload.discount_percentage = discount
        payload.payment = {
          method: 'manual',
          amount: String(amount).trim(),
          // Nombre `manual_method`, no `method`: dentro de este mismo objeto `method` ya
          // significa la via de venta ("manual"), y el backend distingue los dos por el
          // nombre de la clave, no por la posicion.
          manual_method: manualMethod,
          reference: reference.trim(),
        }
        if (validLineItems.length > 0) {
          payload.payment.line_items = validLineItems
        }
      }
      await assignPlanToUser(payload)
      setNotice('Plan asignado correctamente.')
      setForm((prev) => ({ ...prev, user: '' }))
      setLineItems([])
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudo asignar el plan.'))
    } finally {
      setWorking(false)
    }
  }

  return (
    <div className="space-y-6">
      <DashboardHeader title="Asignar plan" subtitle="Asigna un plan activo a un alumno y revisa el precio final estimado." />

      {error ? <p className="rounded-lg border border-brand-red/50 bg-brand-red/10 px-3 py-2 text-sm text-red-200">{error}</p> : null}
      {notice ? <p className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-200">{notice}</p> : null}

      <section className="card-surface p-5">
        <p className="text-sm font-semibold text-brand-white">Vía de pago</p>
        <p className="mt-1 text-xs text-brand-muted">Elegí cómo se registra este plan para el alumno.</p>
        {/* Mobile-first: una columna, dos en pantallas mas anchas. Para superadmin la
            tarjeta de "Registrar pago" ni se renderiza (el backend igual la rechaza con 400,
            pero acá evitamos ofrecer una opción que sabemos que va a fallar). */}
        <div className={`mt-3 grid grid-cols-1 gap-3 ${isSuperadmin ? '' : 'sm:grid-cols-2'}`}>
          <button
            type="button"
            disabled={working}
            onClick={() => selectVia('free')}
            aria-pressed={paymentVia === 'free'}
            // aria-label fija el nombre accesible: sin esto, el <p> de descripcion se suma
            // al texto del boton y "Gratis (beca / cortesía)" deja de matchear exacto.
            aria-label="Gratis (beca / cortesía)"
            className={`rounded-xl border p-3 text-left text-sm transition ${
              paymentVia === 'free' ? 'border-brand-blue bg-brand-blue/10' : 'border-brand-line bg-black/20'
            }`}
          >
            <p className="font-semibold text-brand-white">Gratis (beca / cortesía)</p>
            <p className="text-xs text-brand-muted">Sin cobro: el plan queda 100% bonificado.</p>
          </button>
          {!isSuperadmin ? (
            <button
              type="button"
              disabled={working}
              onClick={() => selectVia('manual')}
              aria-pressed={paymentVia === 'manual'}
              aria-label="Registrar pago"
              className={`rounded-xl border p-3 text-left text-sm transition ${
                paymentVia === 'manual' ? 'border-brand-blue bg-brand-blue/10' : 'border-brand-line bg-black/20'
              }`}
            >
              <p className="font-semibold text-brand-white">Registrar pago</p>
              <p className="text-xs text-brand-muted">Venta con cobro manual (transferencia, efectivo, etc.).</p>
            </button>
          ) : null}
        </div>
      </section>

      <section className="card-surface p-5">
        <form onSubmit={submit} className="grid gap-3 md:grid-cols-2">
          <label className="space-y-1 text-sm md:col-span-2">
            <span>Alumno</span>
            <select
              required
              disabled={loading || working}
              value={form.user}
              onChange={(event) => setForm((prev) => ({ ...prev, user: event.target.value }))}
              className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
            >
              <option value="">Seleccionar alumno</option>
              {students.map((item) => (
                <option key={item.id} value={item.id}>
                  {`${item.first_name || ''} ${item.last_name || ''}`.trim() || item.username}
                </option>
              ))}
            </select>
          </label>
          <label className="space-y-1 text-sm md:col-span-2">
            <span>Plan</span>
            <select
              required
              disabled={loading || working}
              value={form.plan}
              onChange={(event) => setForm((prev) => ({ ...prev, plan: event.target.value }))}
              className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
            >
              <option value="">Seleccionar plan</option>
              {plans.map((plan) => (
                <option key={plan.id} value={plan.id}>
                  {plan.name}
                </option>
              ))}
            </select>
          </label>
          <label className="space-y-1 text-sm">
            <span>Fecha inicio</span>
            <input
              required
              type="date"
              disabled={working}
              value={form.start_date}
              onChange={(event) => setForm((prev) => ({ ...prev, start_date: event.target.value }))}
              className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
            />
          </label>
          <div className="rounded-lg border border-brand-line bg-black/20 px-3 py-2 text-sm">
            <p className="text-brand-muted">Clases del plan</p>
            <p className="text-base font-semibold">{selectedPlan ? (isUnlimited ? 'Ilimitado' : totalClasses) : 'Segun plan'}</p>
            <p className="text-xs text-brand-muted">Definidas por el plan (no editable)</p>
          </div>
          {paymentVia === 'manual' ? (
            <>
              {/* Descuento %, monto y referencia solo tienen sentido en la vía pago: en la
                  vía gratis el backend fija el descuento en 100 y rechaza (400) si alguno
                  de estos campos viaja en el payload. */}
              <label className="space-y-1 text-sm">
                <span>Descuento %</span>
                <input
                  type="number"
                  min="0"
                  max="100"
                  step="0.01"
                  disabled={working}
                  value={form.discount_percentage}
                  onChange={(event) => setForm((prev) => ({ ...prev, discount_percentage: event.target.value }))}
                  placeholder={selectedPlan ? String(selectedPlan.discount_percentage || 0) : '0'}
                  className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
                />
              </label>
              <label className="space-y-1 text-sm">
                <span>Monto cobrado</span>
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  disabled={working}
                  value={amount}
                  onChange={(event) => setAmount(event.target.value)}
                  placeholder="0"
                  className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
                />
              </label>
              <label className="space-y-1 text-sm">
                <span>Método de pago</span>
                <select
                  disabled={working}
                  value={manualMethod}
                  onChange={(event) => setManualMethod(event.target.value)}
                  className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
                >
                  {MANUAL_METHOD_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
              </label>
              <label className="space-y-1 text-sm md:col-span-2">
                <span>Referencia (opcional)</span>
                <input
                  type="text"
                  disabled={working}
                  value={reference}
                  onChange={(event) => setReference(event.target.value)}
                  placeholder="Nº de transferencia, folio o nota..."
                  className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
                />
              </label>
              <div className="space-y-2 text-sm md:col-span-2">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="font-semibold text-brand-white">Conceptos adicionales</p>
                    <p className="text-xs text-brand-muted">Cargos extra de esta venta (ej. pesas, toalla).</p>
                  </div>
                  <button
                    type="button"
                    disabled={working || lineItems.length >= 50}
                    onClick={addLineItem}
                    className="rounded-lg border border-brand-line px-2.5 py-1.5 text-xs font-semibold text-brand-white disabled:opacity-60"
                  >
                    Agregar concepto
                  </button>
                </div>
                {lineItems.length === 0 ? (
                  <p className="text-xs text-brand-muted">Sin conceptos adicionales.</p>
                ) : (
                  <div className="space-y-2">
                    {lineItems.map((item, index) => (
                      <div key={item.key} className="flex items-center gap-2">
                        <input
                          type="text"
                          disabled={working}
                          value={item.concept}
                          onChange={(event) => updateLineItem(item.key, 'concept', event.target.value)}
                          placeholder="Concepto (ej. pesas, toalla)"
                          aria-label={`Concepto ${index + 1}`}
                          className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
                        />
                        <input
                          type="number"
                          min="0"
                          step="0.01"
                          disabled={working}
                          value={item.amount}
                          onChange={(event) => updateLineItem(item.key, 'amount', event.target.value)}
                          placeholder="0"
                          aria-label={`Monto concepto ${index + 1}`}
                          className="w-28 shrink-0 rounded-lg border border-brand-line bg-black/30 px-3 py-2"
                        />
                        <button
                          type="button"
                          disabled={working}
                          onClick={() => removeLineItem(item.key)}
                          aria-label={`Quitar concepto ${index + 1}`}
                          className="shrink-0 rounded-lg border border-brand-red/40 px-2.5 py-1.5 text-xs text-red-200 disabled:opacity-60"
                        >
                          Quitar
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </>
          ) : null}
          <div className="rounded-lg border border-brand-line bg-black/20 px-3 py-2 text-sm md:col-span-2">
            <p className="text-brand-muted">Detalle de cobro</p>
            {quoteLoading ? (
              <p className="mt-2 text-sm text-brand-muted">Calculando...</p>
            ) : quote ? (
              <div className="mt-2 grid gap-1 text-sm">
                <div className="flex justify-between gap-3"><span>Plan</span><strong>{clp(quote.plan_amount)}</strong></div>
                <div className="flex justify-between gap-3"><span>Matricula</span><strong>{clp(quote.enrollment_fee_amount)}</strong></div>
                <div className="flex justify-between gap-3"><span>Conceptos adicionales</span><strong>{clp(quote.line_items_total)}</strong></div>
                <div className="mt-1 flex justify-between gap-3 border-t border-brand-line pt-2 text-base">
                  <span>Total</span><strong>{clp(quote.total)}</strong>
                </div>
                {quote.enrollment_fee_waived ? (
                  <p className="text-xs text-brand-muted">Alumno exento de matricula anual.</p>
                ) : Number(quote.enrollment_fee_amount || 0) > 0 ? (
                  <p className="text-xs text-brand-orange">Corresponde cobrar matricula anual.</p>
                ) : (
                  <p className="text-xs text-brand-muted">No corresponde cobrar matricula en esta asignacion.</p>
                )}
              </div>
            ) : (
              <>
                <p className="text-lg font-semibold">${finalEstimate.toFixed(2)}</p>
                <p className="text-xs text-brand-muted">Selecciona alumno y plan para calcular el total.</p>
              </>
            )}
            <p className="mt-1 text-xs text-brand-muted">Clases: {isUnlimited ? 'Ilimitado' : Number.isFinite(totalClasses) ? totalClasses : 0}</p>
          </div>
          <div className="md:col-span-2 flex justify-end">
            <button type="submit" disabled={working || loading || quoteLoading} className="rounded-xl bg-brand-blue px-4 py-2 text-sm font-semibold text-white disabled:opacity-60">
              {working ? 'Asignando...' : 'Asignar plan'}
            </button>
          </div>
        </form>
      </section>
    </div>
  )
}
