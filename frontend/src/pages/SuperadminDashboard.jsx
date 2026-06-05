import { useEffect, useState } from 'react'
import { branchesApi, dashboardApi, organizationsApi, usersApi } from '../api/client'
import DashboardHeader from '../components/DashboardHeader'
import EmptyState from '../components/EmptyState'
import SectionCard from '../components/SectionCard'
import StatCard from '../components/StatCard'

const emptySummary = {
  organizations: 0,
  branches: 0,
  gym_admins: 0,
  teachers: 0,
  students: 0,
  users: 0,
}

export default function SuperadminDashboard() {
  const [summary, setSummary] = useState(emptySummary)
  const [organizations, setOrganizations] = useState([])
  const [branches, setBranches] = useState([])
  const [users, setUsers] = useState([])

  useEffect(() => {
    const load = async () => {
      try {
        const [summaryData, organizationsData, branchesData, usersData] = await Promise.all([
          dashboardApi.summary(),
          organizationsApi.list(),
          branchesApi.list(),
          usersApi.list(),
        ])

        setSummary({ ...emptySummary, ...summaryData })
        setOrganizations(organizationsData.slice(0, 6))
        setBranches(branchesData.slice(0, 6))
        setUsers(usersData.slice(0, 8))
      } catch {
        setSummary(emptySummary)
      }
    }

    load()
  }, [])

  return (
    <div className="space-y-6">
      <DashboardHeader
        title="Dashboard Superadmin"
        subtitle="Vista global de organizaciones, sucursales y usuarios del ecosistema TYMRO"
      />

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard title="Organizaciones" value={summary.organizations} accent="orange" />
        <StatCard title="Sucursales" value={summary.branches} accent="blue" />
        <StatCard title="Usuarios" value={summary.users} accent="red" />
        <StatCard title="Gym Admins" value={summary.gym_admins} accent="orange" />
      </section>

      <section className="grid gap-4 xl:grid-cols-3">
        <SectionCard title="Organizaciones" subtitle="Catálogo global">
          <div className="space-y-3">
            {organizations.length === 0 ? <EmptyState title="Sin organizaciones" description="Aún no hay registros." /> : null}
            {organizations.map((item) => (
              <div key={item.id} className="rounded-xl border border-brand-line bg-black/20 p-4">
                <p className="font-semibold text-brand-white">{item.name}</p>
                <p className="mt-1 text-sm text-brand-muted">
                  {item.city || 'Sin ciudad'} · {item.country || 'Sin país'}
                </p>
              </div>
            ))}
          </div>
        </SectionCard>

        <SectionCard title="Sucursales" subtitle="Cobertura actual">
          <div className="space-y-3">
            {branches.length === 0 ? <EmptyState title="Sin sucursales" description="Aún no hay registros." /> : null}
            {branches.map((item) => (
              <div key={item.id} className="rounded-xl border border-brand-line bg-black/20 p-4">
                <p className="font-semibold text-brand-white">{item.name}</p>
                <p className="mt-1 text-sm text-brand-muted">{item.organization_name || 'Sin organización'}</p>
              </div>
            ))}
          </div>
        </SectionCard>

        <SectionCard title="Usuarios" subtitle="Listado global">
          <div className="space-y-3">
            {users.length === 0 ? <EmptyState title="Sin usuarios" description="Aún no hay registros." /> : null}
            {users.map((item) => (
              <div key={item.id} className="rounded-xl border border-brand-line bg-black/20 p-4">
                <p className="font-semibold text-brand-white">{item.first_name || item.username}</p>
                <p className="mt-1 text-sm uppercase tracking-wide text-brand-muted">{item.role}</p>
              </div>
            ))}
          </div>
        </SectionCard>
      </section>
    </div>
  )
}
