import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { getPlanById, getPlanMemberships, removePlanMembership } from '../api/client'
import ConfirmDialog from '../components/ConfirmDialog'
import DashboardHeader from '../components/DashboardHeader'
import DataTable from '../components/ui/DataTable'
import PlanAlertBadge from '../components/ui/PlanAlertBadge'
import { formatDate } from '../utils/format'

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

export default function GymAdminPlanMembershipsPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [plan, setPlan] = useState(null)
  const [memberships, setMemberships] = useState([])
  const [loading, setLoading] = useState(true)
  const [working, setWorking] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [deleting, setDeleting] = useState(null)

  const loadData = async () => {
    setLoading(true)
    setError('')
    try {
      const [planData, membershipsData] = await Promise.all([getPlanById(id), getPlanMemberships(id)])
      setPlan(planData)
      setMemberships(Array.isArray(membershipsData) ? membershipsData : [])
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudieron cargar las membresias del plan.'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [id])

  // Se cuenta el MISMO estado que pinta la columna, no `is_active`. El flag significa "no
  // fue reemplazada" y `activate_student_plan` lo deja en true para siempre, así que el
  // KPI decía "12 activas" sobre una tabla de 12 filas que decían "Vencido". El endpoint
  // sigue devolviendo el histórico completo: lo que cambia es qué se cuenta de él.
  const activeCount = useMemo(
    () => memberships.filter((item) => item.validity_status === 'active').length,
    [memberships],
  )

  const removeMembership = async () => {
    if (!deleting) {
      return
    }
    setWorking(true)
    setError('')
    setNotice('')
    try {
      await removePlanMembership(id, deleting.id)
      setNotice(`Membresia quitada para ${deleting.user_name || deleting.user_email || 'alumno'}.`)
      setDeleting(null)
      await loadData()
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudo quitar la membresia.'))
    } finally {
      setWorking(false)
    }
  }

  const columns = useMemo(
    () => [
      { key: 'user_name', label: 'Alumno', render: (row) => row.user_name || `#${row.user}` },
      { key: 'user_email', label: 'Email', render: (row) => row.user_email || '-' },
      { key: 'start_date', label: 'Inicio', render: (row) => formatDate(row.start_date) },
      { key: 'end_date', label: 'Termino', render: (row) => formatDate(row.end_date) },
      { key: 'total_classes', label: 'Clases totales' },
      { key: 'classes_used', label: 'Usadas' },
      { key: 'remaining_classes', label: 'Disponibles' },
      {
        key: 'validity_status',
        label: 'Estado',
        // La escalera de cuatro ramas mandaba al `else` ("Inactiva") todo lo que no
        // conocía, o sea exactamente los dos estados que 7.3 destapa.
        //
        // Sigue siendo un chip y no texto pelado: en móvil DataTable manda esta celda a la
        // zona `meta`, que NO aporta estilo propio, así que el color tiene que venir del
        // contenido. La severidad la decide el backend; acá no se deriva nada.
        render: (row) => <PlanAlertBadge level={row.expiry_alert_level} message={row.validity_status_label} />,
      },
      {
        key: 'alert',
        label: 'Alerta',
        sortable: false,
        render: (row) => <PlanAlertBadge level={row.expiry_alert_level} message={row.expiry_alert_message} />,
      },
      {
        key: 'actions',
        label: 'Acciones',
        sortable: false,
        render: (row) => (
          <button
            type="button"
            disabled={working || Number(row.classes_used || 0) > 0}
            onClick={() => setDeleting(row)}
            className="rounded border border-brand-red/40 px-2 py-1 text-xs text-red-200 disabled:opacity-50"
            title={Number(row.classes_used || 0) > 0 ? 'No se puede quitar si ya utilizo clases.' : ''}
          >
            Quitar plan
          </button>
        ),
      },
    ],
    [working],
  )

  return (
    <div className="space-y-6">
      <DashboardHeader
        title={`Membresias · ${plan?.name || 'Plan'}`}
        subtitle="Gestiona alumnos con este plan. Solo puedes quitar membresias sin consumo."
        back={{ to: '/gym-admin/plans', label: 'Planes' }}
      />

      {error ? <p className="rounded-lg border border-brand-red/50 bg-brand-red/10 px-3 py-2 text-sm text-red-200">{error}</p> : null}
      {notice ? <p className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-200">{notice}</p> : null}

      <section className="card-surface space-y-4 p-5">
        <div className="grid gap-3 md:grid-cols-3">
          <div className="rounded-xl border border-brand-line bg-black/20 p-3">
            <p className="text-xs text-brand-muted">Total membresias</p>
            <p className="text-xl font-semibold">{memberships.length}</p>
          </div>
          <div className="rounded-xl border border-brand-line bg-black/20 p-3">
            <p className="text-xs text-brand-muted">Membresias activas</p>
            <p className="text-xl font-semibold">{activeCount}</p>
          </div>
          <div className="rounded-xl border border-brand-line bg-black/20 p-3">
            <p className="text-xs text-brand-muted">Politica actual</p>
            <p className="text-sm font-semibold">Solo sin uso (0 clases)</p>
          </div>
        </div>
      </section>

      <section className="card-surface p-5">
        <DataTable columns={columns} data={memberships} loading={loading} />
      </section>

      <ConfirmDialog
        open={Boolean(deleting)}
        title="Quitar membresia"
        description={`Se quitara el plan de ${deleting?.user_name || deleting?.user_email || 'este alumno'}. Solo permitido si no ha usado clases.`}
        confirmLabel="Quitar plan"
        loading={working}
        onCancel={() => setDeleting(null)}
        onConfirm={removeMembership}
      />
    </div>
  )
}
