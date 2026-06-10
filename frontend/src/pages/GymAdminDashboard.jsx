import { useEffect, useState } from 'react'
import { branchesApi, dashboardApi, usersApi } from '../api/client'
import DashboardHeader from '../components/DashboardHeader'
import StatCard from '../components/StatCard'
import PublicRegistrationCard from '../components/PublicRegistrationCard'

const emptySummary = {
  branches: 0,
  teachers: 0,
  students: 0,
  users: 0,
  organization: '',
}

export default function GymAdminDashboard() {
  const [summary, setSummary] = useState(emptySummary)
  const [recentUsers, setRecentUsers] = useState([])
  const [branches, setBranches] = useState([])

  useEffect(() => {
    const load = async () => {
      const [summaryData, usersData, branchesData] = await Promise.all([dashboardApi.summary(), usersApi.list(), branchesApi.list()])
      setSummary({ ...emptySummary, ...summaryData })
      setRecentUsers(usersData.slice(0, 6))
      setBranches(branchesData.slice(0, 6))
    }

    load()
  }, [])

  return (
    <div className="space-y-6">
      <DashboardHeader title="Gym Admin · Dashboard" subtitle={`Gestión de ${summary.organization || 'tu organización'}`} />

      <section className="grid grid-cols-2 gap-3 md:gap-4 xl:grid-cols-4">
        <StatCard title="Sucursales" value={summary.branches} accent="blue" to="/gym-admin/branches" />
        <StatCard title="Profesores" value={summary.teachers} accent="orange" to="/gym-admin/users" />
        <StatCard title="Alumnos" value={summary.students} accent="red" to="/gym-admin/users" />
        <StatCard title="Usuarios" value={summary.users} accent="orange" to="/gym-admin/users" />
      </section>

      <PublicRegistrationCard />

      <section className="grid gap-4 lg:grid-cols-2">
        <article className="card-surface p-5">
          <h2 className="panel-title">Usuarios recientes</h2>
          <div className="mt-4 space-y-2">
            {recentUsers.length === 0 ? <p className="text-sm text-brand-muted">Sin usuarios todavía.</p> : null}
            {recentUsers.map((user) => (
              <div key={user.id} className="rounded-lg border border-brand-line px-3 py-2">
                <p className="text-sm font-semibold">{`${user.first_name || ''} ${user.last_name || ''}`.trim() || user.username}</p>
                <p className="text-xs text-brand-muted">{user.role} · {user.branch_detail?.name || 'Sin sucursal'}</p>
              </div>
            ))}
          </div>
        </article>

        <article className="card-surface p-5">
          <h2 className="panel-title">Sucursales</h2>
          <div className="mt-4 space-y-2">
            {branches.length === 0 ? <p className="text-sm text-brand-muted">Sin sucursales todavía.</p> : null}
            {branches.map((branch) => (
              <div key={branch.id} className="rounded-lg border border-brand-line px-3 py-2">
                <p className="text-sm font-semibold">{branch.name}</p>
                <p className="text-xs text-brand-muted">{branch.address || 'Sin dirección'}</p>
              </div>
            ))}
          </div>
        </article>
      </section>
    </div>
  )
}
