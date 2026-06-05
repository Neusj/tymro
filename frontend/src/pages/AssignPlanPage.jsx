import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { assignPlanToUser, getPlans, usersApi } from '../api/client'
import DashboardHeader from '../components/DashboardHeader'

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

export default function AssignPlanPage() {
  const [searchParams] = useSearchParams()
  const [students, setStudents] = useState([])
  const [plans, setPlans] = useState([])
  const [loading, setLoading] = useState(true)
  const [working, setWorking] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const [form, setForm] = useState({
    user: '',
    plan: '',
    start_date: new Date().toISOString().slice(0, 10),
    total_classes: '',
    discount_percentage: '',
  })

  const selectedPlan = useMemo(() => plans.find((item) => String(item.id) === String(form.plan)), [plans, form.plan])
  const totalClasses = form.total_classes !== '' ? Number(form.total_classes) : Number(selectedPlan?.total_classes || 0)
  const discount = form.discount_percentage !== '' ? Number(form.discount_percentage) : Number(selectedPlan?.discount_percentage || 0)
  const basePrice = Number(selectedPlan?.price || 0)
  const finalEstimate = Math.max(basePrice * (1 - discount / 100), 0)

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
      const [usersData, plansData] = await Promise.all([usersApi.list({ ...params, role: 'student' }), getPlans()])
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

  const submit = async (event) => {
    event.preventDefault()
    if (!form.user || !form.plan) {
      setError('Selecciona usuario y plan.')
      return
    }
    setWorking(true)
    setError('')
    setNotice('')
    try {
      await assignPlanToUser({
        user: Number(form.user),
        plan: Number(form.plan),
        start_date: form.start_date,
        total_classes: totalClasses,
        discount_percentage: discount,
      })
      setNotice('Plan asignado correctamente.')
      setForm((prev) => ({ ...prev, user: '' }))
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
          <label className="space-y-1 text-sm">
            <span>Total clases (editable)</span>
            <input
              type="number"
              min="0"
              disabled={working}
              value={form.total_classes}
              onChange={(event) => setForm((prev) => ({ ...prev, total_classes: event.target.value }))}
              placeholder={selectedPlan ? String(selectedPlan.total_classes) : 'Segun plan'}
              className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
            />
          </label>
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
          <div className="rounded-lg border border-brand-line bg-black/20 px-3 py-2 text-sm">
            <p className="text-brand-muted">Precio final estimado</p>
            <p className="text-lg font-semibold">${finalEstimate.toFixed(2)}</p>
            <p className="text-xs text-brand-muted">Clases estimadas: {Number.isFinite(totalClasses) ? totalClasses : 0}</p>
          </div>
          <div className="md:col-span-2 flex justify-end">
            <button type="submit" disabled={working || loading} className="rounded-xl bg-brand-blue px-4 py-2 text-sm font-semibold text-white disabled:opacity-60">
              {working ? 'Asignando...' : 'Asignar plan'}
            </button>
          </div>
        </form>
      </section>
    </div>
  )
}
