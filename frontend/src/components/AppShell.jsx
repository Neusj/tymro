import { NavLink } from 'react-router-dom'
import Avatar from './Avatar'
import RoleBadge from './RoleBadge'

const navByRole = {
  superadmin: [
    { to: '/superadmin/organizations', label: 'Organizaciones' },
    { to: '/superadmin/users', label: 'Usuarios por organización' },
  ],
  gym_admin: [
    { to: '/gym-admin/dashboard', label: 'Dashboard' },
    { to: '/gym-admin/users', label: 'Usuarios' },
    { to: '/gym-admin/branches', label: 'Sucursales' },
    { to: '/gym-admin/class-templates', label: 'Gestión de clases' },
    { to: '/gym-admin/class-types', label: 'Tipos' },
  ],
  teacher: [
    { to: '/teacher/classes', label: 'Mis clases' },
  ],
  student: [
    { to: '/student/classes', label: 'Mis clases' },
  ],
}

export default function AppShell({ user, onLogout, children }) {
  const orgName = user?.organization_detail?.name || 'TYMRO'
  const primary = user?.organization_detail?.primary_color || '#dc2626'
  const secondary = user?.organization_detail?.secondary_color || '#2563eb'

  const roleNav = navByRole[user?.role] || []

  return (
    <div
      className="min-h-screen bg-brand-black text-brand-white"
      style={{
        '--dynamic-primary': primary,
        '--dynamic-secondary': secondary,
      }}
    >
      <header className="sticky top-0 z-20 border-b border-brand-line bg-brand-black/90 backdrop-blur">
        <div className="mx-auto flex max-w-7xl flex-col gap-3 px-4 py-4 md:px-6">
          <div className="flex items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <Avatar src={user?.organization_detail?.logo} name={orgName} size="md" />
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.3em] text-brand-orange">TYMRO</p>
                <p className="text-sm text-brand-muted">{orgName}</p>
              </div>
            </div>

            <div className="flex items-center gap-3">
              <RoleBadge role={user?.role} />
              <button
                type="button"
                onClick={onLogout}
                className="rounded-xl border border-brand-line bg-brand-soft px-3 py-2 text-sm font-medium text-brand-white transition hover:border-brand-red hover:text-brand-red"
              >
                Cerrar sesión
              </button>
            </div>
          </div>

          {roleNav.length > 0 ? (
            <nav className="flex flex-wrap gap-2">
              {roleNav.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className={({ isActive }) =>
                    `rounded-lg border px-3 py-1.5 text-sm transition ${
                      isActive ? 'border-brand-orange bg-brand-orange/20 text-brand-white' : 'border-brand-line text-brand-muted hover:text-brand-white'
                    }`
                  }
                >
                  {item.label}
                </NavLink>
              ))}
            </nav>
          ) : null}
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-4 py-6 md:px-6 md:py-8">{children}</main>
    </div>
  )
}
