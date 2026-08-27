import { useEffect, useMemo, useState } from 'react'
import { Link, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { classesApi, classTemplatesApi } from '../api/client'
import DashboardHeader from '../components/DashboardHeader'
import DataTable from '../components/ui/DataTable'
import ValueBadge from '../components/ui/ValueBadge'
import { firstApiError } from '../utils/format'

const weekdayLabels = ['Lunes', 'Martes', 'Miercoles', 'Jueves', 'Viernes', 'Sabado', 'Domingo']

function formatDateTime(value) {
  if (!value) {
    return '-'
  }
  return new Date(value).toLocaleString('es-CL', {
    dateStyle: 'medium',
    timeStyle: 'short',
  })
}

function formatTime(value) {
  return value?.slice(0, 5) || '-'
}

function instanceStateWeight(row) {
  const status = row.status
  if (status === 'completed' || status === 'completed_early') {
    return 1
  }
  if (status === 'cancelled' || status === 'suspended') {
    return 2
  }
  return 3
}

export default function GymAdminClassTemplateHistoryPage() {
  const { id } = useParams()
  const location = useLocation()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const [template, setTemplate] = useState(null)
  const [instances, setInstances] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [dateFrom, setDateFrom] = useState(searchParams.get('from') || '')
  const [dateTo, setDateTo] = useState(searchParams.get('to') || '')

  useEffect(() => {
    setDateFrom(searchParams.get('from') || '')
    setDateTo(searchParams.get('to') || '')
  }, [searchParams])

  useEffect(() => {
    let cancelled = false

    const loadData = async () => {
      setLoading(true)
      setError('')
      try {
        const params = {
          class_template: id,
          ordering: '-start_datetime',
        }
        const from = searchParams.get('from')
        const to = searchParams.get('to')
        if (from) {
          params.start_date_from = from
        }
        if (to) {
          params.start_date_to = to
        }
        const [templateData, instanceData] = await Promise.all([
          classTemplatesApi.retrieve(id),
          classesApi.list(params),
        ])
        if (!cancelled) {
          setTemplate(templateData)
          setInstances(instanceData)
        }
      } catch (apiError) {
        if (!cancelled) {
          setError(firstApiError(apiError?.response?.data, 'No se pudo cargar el historial de esta programacion.'))
        }
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    }

    loadData()
    return () => {
      cancelled = true
    }
  }, [id, searchParams])

  const summary = useMemo(() => {
    return instances.reduce(
      (acc, row) => {
        acc.total += 1
        acc.inscritos += Number(row.enrollments_count || 0)
        acc.asistencias += Number(row.present_attendances_count || 0)
        if (row.status === 'completed' || row.status === 'completed_early') {
          acc.realizadas += 1
        } else if (row.status === 'cancelled') {
          acc.canceladas += 1
        } else if (row.status === 'suspended') {
          acc.suspendidas += 1
        }
        return acc
      },
      { total: 0, realizadas: 0, canceladas: 0, suspendidas: 0, inscritos: 0, asistencias: 0 },
    )
  }, [instances])

  const detailBackState = useMemo(
    () => ({
      classListBackTo: {
        pathname: `/gym-admin/class-templates/${id}/history`,
        search: location.search,
      },
    }),
    [id, location.search],
  )

  const openInstanceDetail = (row) => {
    navigate(`/gym-admin/classes/${row.id}`, { state: detailBackState })
  }

  const applyFilters = (event) => {
    event.preventDefault()
    const next = {}
    if (dateFrom) {
      next.from = dateFrom
    }
    if (dateTo) {
      next.to = dateTo
    }
    setSearchParams(next, { replace: true })
  }

  const clearFilters = () => {
    setDateFrom('')
    setDateTo('')
    setSearchParams({}, { replace: true })
  }

  const columns = useMemo(
    () => [
      {
        key: 'start_datetime',
        label: 'Fecha',
        mobile: 'title',
        render: (row) => formatDateTime(row.start_datetime),
      },
      { key: 'teacher_name', label: 'Profesor', mobile: 'secondary' },
      {
        key: 'substitute_display_name',
        label: 'Suplente',
        mobile: 'secondary',
        render: (row) => (row.has_substitute ? row.substitute_display_name || row.substitute_name || '-' : <span className="text-brand-muted">Sin suplente</span>),
      },
      {
        key: 'status',
        label: 'Estado',
        mobile: 'meta',
        sortAccessor: instanceStateWeight,
        render: (row) => <ValueBadge kind="class_status" value={row.status} />,
      },
      { key: 'enrollments_count', label: 'Inscritos', render: (row) => `${row.enrollments_count || 0}/${row.capacity || 0}` },
      { key: 'present_attendances_count', label: 'Asistencia', render: (row) => `${row.present_attendances_count || 0}/${row.enrollments_count || 0}` },
      {
        key: 'actions',
        label: 'Acciones',
        sortable: false,
        render: (row) => (
          <Link
            to={`/gym-admin/classes/${row.id}`}
            state={detailBackState}
            className="block w-full rounded-lg border border-brand-blue/40 px-2.5 py-1.5 text-left text-xs text-blue-100"
          >
            Ver detalle guardado
          </Link>
        ),
      },
    ],
    [detailBackState],
  )

  const subtitle = template
    ? `${template.branch_name || '-'} - ${weekdayLabels[template.weekday] || '-'} ${formatTime(template.start_time)} - ${formatTime(template.end_time)}`
    : 'Instancias pasadas y futuras de una programacion.'

  return (
    <div className="space-y-6">
      <DashboardHeader
        title={template?.name ? `Historial - ${template.name}` : 'Historial de programacion'}
        subtitle={subtitle}
        back={{ to: '/gym-admin/class-templates', label: 'Volver a programacion' }}
      />

      {error ? <p className="rounded-lg border border-brand-red/50 bg-brand-red/10 px-3 py-2 text-sm text-red-200">{error}</p> : null}

      <section className="grid gap-4 md:grid-cols-5">
        <article className="card-surface p-4">
          <p className="text-xs uppercase tracking-wide text-brand-muted">Instancias</p>
          <p className="mt-1 font-semibold">{summary.total}</p>
        </article>
        <article className="card-surface p-4">
          <p className="text-xs uppercase tracking-wide text-brand-muted">Realizadas</p>
          <p className="mt-1 font-semibold">{summary.realizadas}</p>
        </article>
        <article className="card-surface p-4">
          <p className="text-xs uppercase tracking-wide text-brand-muted">Canceladas</p>
          <p className="mt-1 font-semibold">{summary.canceladas}</p>
        </article>
        <article className="card-surface p-4">
          <p className="text-xs uppercase tracking-wide text-brand-muted">Inscritos</p>
          <p className="mt-1 font-semibold">{summary.inscritos}</p>
        </article>
        <article className="card-surface p-4">
          <p className="text-xs uppercase tracking-wide text-brand-muted">Asistencias</p>
          <p className="mt-1 font-semibold">{summary.asistencias}</p>
        </article>
      </section>

      <section className="card-surface p-5">
        <form onSubmit={applyFilters} className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto_auto] sm:items-end">
          <label className="space-y-1 text-sm">
            <span>Desde</span>
            <input type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} className="field" />
          </label>
          <label className="space-y-1 text-sm">
            <span>Hasta</span>
            <input type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} className="field" />
          </label>
          <button type="submit" className="btn-primary">
            Filtrar
          </button>
          <button type="button" onClick={clearFilters} className="btn-ghost">
            Limpiar
          </button>
        </form>
      </section>

      <section className="space-y-3">
        <h2 className="panel-title">Instancias de la programacion</h2>
        <DataTable
          columns={columns}
          data={instances}
          loading={loading}
          defaultSort={{ key: 'start_datetime', direction: 'desc' }}
          onRowClick={openInstanceDetail}
        />
      </section>
    </div>
  )
}
