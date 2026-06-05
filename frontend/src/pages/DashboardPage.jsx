import { useEffect, useState } from 'react'
import { api } from '../api/client'
import SectionCard from '../components/SectionCard'
import StatCard from '../components/StatCard'

const emptySummary = {
  organizations: 0,
  branches: 0,
  students: 0,
  teachers: 0,
  scheduled_classes: 0,
  completed_classes: 0,
  active_plans: 0,
  private_classes: 0,
}

export default function DashboardPage() {
  const [summary, setSummary] = useState(emptySummary)
  const [organizations, setOrganizations] = useState([])
  const [classes, setClasses] = useState([])
  const [plans, setPlans] = useState([])
  const [health, setHealth] = useState('conectando...')

  useEffect(() => {
    api.get('/health/').then((res) => setHealth(res.data.message)).catch(() => setHealth('backend no disponible'))
    api.get('/dashboard/').then((res) => setSummary(res.data)).catch(() => {})
    api.get('/organizations/').then((res) => setOrganizations(res.data.slice(0, 5))).catch(() => {})
    api.get('/classes/').then((res) => setClasses(res.data.slice(0, 5))).catch(() => {})
    api.get('/plans/').then((res) => setPlans(res.data.slice(0, 5))).catch(() => {})
  }, [])

  return (
    <div className="space-y-6">
      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard title="Organizaciones" value={summary.organizations} accent="orange" />
        <StatCard title="Sucursales" value={summary.branches} accent="blue" />
        <StatCard title="Alumnos activos" value={summary.students} accent="red" />
        <StatCard title="Profesores" value={summary.teachers} accent="orange" />
      </section>

      <section className="grid gap-4 lg:grid-cols-3">
        <SectionCard title="Estado de conexión" subtitle="Verificación rápida del backend Django">
          <div className="rounded-2xl border border-brand-line bg-black/20 p-4">
            <p className="text-sm text-brand-muted">API</p>
            <p className="mt-2 text-xl font-semibold">{health}</p>
          </div>
        </SectionCard>

        <SectionCard title="Operación del día" subtitle="Resumen inicial del MVP">
          <div className="space-y-3 text-sm text-brand-muted">
            <div className="flex items-center justify-between rounded-xl border border-brand-line px-4 py-3">
              <span>Clases programadas</span>
              <span className="font-semibold text-brand-white">{summary.scheduled_classes}</span>
            </div>
            <div className="flex items-center justify-between rounded-xl border border-brand-line px-4 py-3">
              <span>Clases realizadas</span>
              <span className="font-semibold text-brand-white">{summary.completed_classes}</span>
            </div>
            <div className="flex items-center justify-between rounded-xl border border-brand-line px-4 py-3">
              <span>Planes activos</span>
              <span className="font-semibold text-brand-white">{summary.active_plans}</span>
            </div>
            <div className="flex items-center justify-between rounded-xl border border-brand-line px-4 py-3">
              <span>Privadas</span>
              <span className="font-semibold text-brand-white">{summary.private_classes}</span>
            </div>
          </div>
        </SectionCard>

        <SectionCard title="Enfoque del producto" subtitle="Core del SaaS">
          <div className="space-y-3 text-sm text-brand-muted">
            <p>Registrar lo que pasa en el tatami y convertirlo en gestión real.</p>
            <ul className="space-y-2">
              <li>• Clases y asistencia</li>
              <li>• Planes y consumo</li>
              <li>• Reglas de pago a profesores</li>
              <li>• Base lista para multi-sucursal</li>
            </ul>
          </div>
        </SectionCard>
      </section>

      <section className="grid gap-4 xl:grid-cols-3">
        <SectionCard title="Organizaciones" subtitle="Primeras 5 registradas">
          <div className="space-y-3">
            {organizations.length === 0 ? <p className="text-sm text-brand-muted">Aún no hay datos.</p> : null}
            {organizations.map((item) => (
              <div key={item.id} className="rounded-xl border border-brand-line p-4">
                <p className="font-semibold text-brand-white">{item.name}</p>
                <p className="mt-1 text-sm text-brand-muted">{item.city || 'Sin ciudad'} · {item.country || 'Sin país'}</p>
              </div>
            ))}
          </div>
        </SectionCard>

        <SectionCard title="Clases" subtitle="Últimas registradas">
          <div className="space-y-3">
            {classes.length === 0 ? <p className="text-sm text-brand-muted">Aún no hay clases.</p> : null}
            {classes.map((item) => (
              <div key={item.id} className="rounded-xl border border-brand-line p-4">
                <p className="font-semibold text-brand-white">{item.title}</p>
                <p className="mt-1 text-sm text-brand-muted">{item.branch_name || 'Sin sucursal'} · {item.teacher_name || 'Sin profesor'}</p>
              </div>
            ))}
          </div>
        </SectionCard>

        <SectionCard title="Planes" subtitle="Oferta activa del gimnasio">
          <div className="space-y-3">
            {plans.length === 0 ? <p className="text-sm text-brand-muted">Aún no hay planes.</p> : null}
            {plans.map((item) => (
              <div key={item.id} className="rounded-xl border border-brand-line p-4">
                <div className="flex items-center justify-between gap-3">
                  <p className="font-semibold text-brand-white">{item.name}</p>
                  <span className="rounded-full bg-brand-blue/20 px-3 py-1 text-xs font-semibold text-brand-white">{item.plan_kind}</span>
                </div>
                <p className="mt-2 text-sm text-brand-muted">Precio: {item.price}</p>
              </div>
            ))}
          </div>
        </SectionCard>
      </section>
    </div>
  )
}
