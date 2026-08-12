import { useAuth } from '../auth/AuthContext'
import DashboardHeader from '../components/DashboardHeader'
import EmptyState from '../components/EmptyState'
import SectionCard from '../components/SectionCard'

function ProfileImage({ user }) {
  if (user?.profile_image) {
    return <img src={user.profile_image} alt={user.username} className="h-16 w-16 rounded-2xl border border-brand-line object-cover" />
  }

  const initials = `${user?.first_name?.[0] || ''}${user?.last_name?.[0] || ''}`.trim() || 'T'
  return (
    <div className="flex h-16 w-16 items-center justify-center rounded-2xl border border-brand-line bg-brand-blue/20 text-xl font-bold">
      {initials.toUpperCase()}
    </div>
  )
}

export default function TeacherDashboard() {
  const { user } = useAuth()

  return (
    <div className="space-y-6">
      <DashboardHeader title="Dashboard Teacher" subtitle="Resumen personal y vista inicial de trabajo docente" />

      <section className="grid gap-4 lg:grid-cols-2">
        <SectionCard title="Perfil" subtitle="Información de tu cuenta">
          <div className="flex items-center gap-4 rounded-xl border border-brand-line bg-black/20 p-4">
            <ProfileImage user={user} />
            <div>
              <p className="text-lg font-semibold">{`${user?.first_name || ''} ${user?.last_name || ''}`.trim() || user?.username}</p>
              <p className="text-sm text-brand-muted">{user?.email || 'Sin email'}</p>
            </div>
          </div>
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <div className="rounded-xl border border-brand-line p-3">
              <p className="text-xs uppercase tracking-wide text-brand-muted">Organización</p>
              <p className="mt-1 text-sm font-semibold">{user?.organization_detail?.name || 'Sin organización'}</p>
            </div>
            <div className="rounded-xl border border-brand-line p-3">
              <p className="text-xs uppercase tracking-wide text-brand-muted">Sucursal</p>
              <p className="mt-1 text-sm font-semibold">{user?.branch_detail?.name || 'Sin sucursal'}</p>
            </div>
          </div>
        </SectionCard>

        <SectionCard title="Mis clases" subtitle="Vista inicial de trabajo docente">
          <EmptyState title="Sin datos aún" description="Aquí verás próximas clases, asistencia e inscritos." />
        </SectionCard>
      </section>
    </div>
  )
}
