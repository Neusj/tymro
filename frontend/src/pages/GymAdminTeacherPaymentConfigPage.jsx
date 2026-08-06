import { useEffect, useState } from 'react'
import DashboardHeader from '../components/DashboardHeader'
import { teacherPaymentConfigApi } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { firstApiError } from '../utils/format'

// Configura el valor de UNA clase gratis, usado para calcular el pago al profesor cuando
// dicta clases de planes con discount_percentage=100 (gratuitos). Nace en 0: mientras esté
// en 0, /api/plans/ rechaza crear/editar planes gratuitos (ver PlanListPage, que refleja
// esa misma regla del lado del cliente antes de mandar el POST/PATCH).
export default function GymAdminTeacherPaymentConfigPage() {
  const { user } = useAuth()
  const orgId = user?.organization

  const [value, setValue] = useState('0')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [fieldError, setFieldError] = useState('')
  const [success, setSuccess] = useState('')

  useEffect(() => {
    let active = true
    const load = async () => {
      if (!orgId) {
        setError('No se pudo determinar tu organización.')
        setLoading(false)
        return
      }
      setLoading(true)
      setError('')
      try {
        const data = await teacherPaymentConfigApi.get(orgId)
        if (!active) return
        setValue(String(data?.free_class_teacher_payment_value ?? 0))
      } catch (apiError) {
        if (!active) return
        setError(firstApiError(apiError?.response?.data, 'No se pudo cargar la configuración.'))
      } finally {
        if (active) setLoading(false)
      }
    }
    load()
    return () => {
      active = false
    }
  }, [orgId])

  const submit = async (event) => {
    event.preventDefault()
    const numericValue = Number(value)
    if (!Number.isFinite(numericValue) || numericValue < 0) {
      setFieldError('Ingresa un número mayor o igual a 0.')
      return
    }
    setFieldError('')
    setSaving(true)
    setError('')
    setSuccess('')
    try {
      const data = await teacherPaymentConfigApi.update(orgId, {
        free_class_teacher_payment_value: numericValue,
      })
      setValue(String(data?.free_class_teacher_payment_value ?? numericValue))
      setSuccess('Configuración guardada correctamente.')
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudo guardar la configuración.'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-6">
      <DashboardHeader
        title="Gym Admin · Configuraciones"
        subtitle="Define el valor de una clase gratis, usado para calcular el pago al profesor en planes gratuitos."
        back={{ to: '/gym-admin/dashboard', label: 'Dashboard' }}
      />

      <section className="card-surface p-5">
        {loading ? (
          <p className="text-sm text-brand-muted">Cargando configuración…</p>
        ) : (
          <form onSubmit={submit} className="space-y-5">
            <div className="space-y-2">
              <label className="block text-sm font-semibold" htmlFor="free-class-teacher-payment-value">
                Valor de clase gratis (para pago al profesor)
              </label>
              <p className="text-xs text-brand-muted">
                Es el valor de UNA clase. Se usa para calcular el pago al profesor cuando dicta
                clases de planes gratuitos (100% de descuento). Mientras esté en 0 no se pueden
                crear planes gratuitos.
              </p>
              <input
                id="free-class-teacher-payment-value"
                type="number"
                step="1"
                value={value}
                onChange={(event) => setValue(event.target.value)}
                className="w-48 rounded-lg border border-brand-line bg-black/30 px-3 py-2 text-sm"
              />
              {fieldError ? <p className="text-xs text-red-200">{fieldError}</p> : null}
            </div>

            <div className="flex justify-end">
              <button
                type="submit"
                disabled={saving}
                className="rounded-xl bg-brand-blue px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
              >
                {saving ? 'Guardando…' : 'Guardar'}
              </button>
            </div>
          </form>
        )}

        {error ? (
          <p className="mt-3 rounded-lg border border-brand-red/50 bg-brand-red/10 px-3 py-2 text-sm text-red-200">{error}</p>
        ) : null}
        {success ? (
          <p className="mt-3 rounded-lg border border-success/50 bg-success/10 px-3 py-2 text-sm text-emerald-200">{success}</p>
        ) : null}
      </section>
    </div>
  )
}
