import { useCallback, useEffect, useMemo, useState } from 'react'
import { personalizedClassesApi } from '../api/client'
import DashboardHeader from '../components/DashboardHeader'
import EmptyState from '../components/EmptyState'
import { firstApiError, formatDate } from '../utils/format'

function formatDateTime(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return `${formatDate(value)} ${date.toLocaleTimeString('es-CL', { hour: '2-digit', minute: '2-digit' })}`
}

function statusBadge(item) {
  if (item.status === 'finished') {
    return { text: 'Dictada', className: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200' }
  }
  return { text: 'En curso', className: 'border-brand-orange/50 bg-brand-orange/10 text-amber-200' }
}

function StudentSessionCard({ item }) {
  const badge = statusBadge(item)
  return (
    <article className="rounded-xl border border-brand-line bg-brand-soft/80 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="font-semibold text-brand-white">Clase personalizada</h3>
        <span className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${badge.className}`}>
          {badge.text}
        </span>
      </div>
      <dl className="mt-3 grid gap-2 text-sm text-brand-muted sm:grid-cols-2">
        <div>
          <dt className="text-xs uppercase tracking-wide text-brand-muted/80">Profesor</dt>
          <dd className="font-medium text-brand-white">{item.teacher || '-'}</dd>
        </div>
        <div>
          <dt className="text-xs uppercase tracking-wide text-brand-muted/80">Plan</dt>
          <dd>{item.student_plan_name || '-'}</dd>
        </div>
        <div>
          <dt className="text-xs uppercase tracking-wide text-brand-muted/80">Inicio</dt>
          <dd>{formatDateTime(item.confirmed_at)}</dd>
        </div>
        <div>
          <dt className="text-xs uppercase tracking-wide text-brand-muted/80">Fin</dt>
          <dd>{formatDateTime(item.finished_at)}</dd>
        </div>
        <div>
          <dt className="text-xs uppercase tracking-wide text-brand-muted/80">Sede</dt>
          <dd>{item.branch || '-'}</dd>
        </div>
        <div>
          <dt className="text-xs uppercase tracking-wide text-brand-muted/80">Disciplina</dt>
          <dd>{item.discipline || item.class_type || '-'}</dd>
        </div>
      </dl>
    </article>
  )
}

export default function StudentPersonalizedClassesPage() {
  const [sessions, setSessions] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const loadSessions = useCallback(async () => {
    try {
      const data = await personalizedClassesApi.list()
      setSessions(Array.isArray(data) ? data : [])
      setError('')
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudieron cargar tus clases personalizadas.'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadSessions()
  }, [loadSessions])

  const currentSessions = useMemo(
    () => sessions.filter((item) => item.status === 'confirmed'),
    [sessions],
  )
  const finishedSessions = useMemo(
    () => sessions.filter((item) => item.status === 'finished'),
    [sessions],
  )

  return (
    <div className="space-y-6">
      <DashboardHeader
        title="Mis clases personalizadas"
        subtitle="Revisa tus sesiones privadas en curso y dictadas."
        extra={(
          <button type="button" onClick={loadSessions} className="inline-flex min-h-10 items-center rounded-lg border border-brand-line px-4 py-2 text-sm font-semibold text-brand-white transition hover:border-brand-orange">
            Actualizar
          </button>
        )}
      />

      {error ? <p className="rounded-lg border border-brand-red/50 bg-brand-red/10 px-3 py-2 text-sm text-red-200">{error}</p> : null}

      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-brand-white">En curso</h2>
        {loading ? <p className="text-sm text-brand-muted">Cargando clases...</p> : null}
        {!loading && currentSessions.length === 0 ? (
          <EmptyState title="Sin clases en curso" description="Cuando escanees el QR de una clase personalizada aparecera aqui." />
        ) : (
          <div className="grid gap-3">
            {currentSessions.map((item) => <StudentSessionCard key={item.id} item={item} />)}
          </div>
        )}
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-brand-white">Dictadas</h2>
        {!loading && finishedSessions.length === 0 ? (
          <EmptyState title="Sin clases dictadas" description="Las clases finalizadas por el profesor quedan registradas aqui." />
        ) : (
          <div className="grid gap-3">
            {finishedSessions.map((item) => <StudentSessionCard key={item.id} item={item} />)}
          </div>
        )}
      </section>
    </div>
  )
}
