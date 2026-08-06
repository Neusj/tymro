import SidebarGroup from './SidebarGroup'
import SidebarItem from './SidebarItem'

function DashboardIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-5 w-5">
      <rect x="3" y="3" width="8" height="8" rx="1.5" />
      <rect x="13" y="3" width="8" height="5" rx="1.5" />
      <rect x="13" y="10" width="8" height="11" rx="1.5" />
      <rect x="3" y="13" width="8" height="8" rx="1.5" />
    </svg>
  )
}

function UsersIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-5 w-5">
      <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
      <circle cx="9" cy="7" r="4" />
      <path d="M22 21v-2a4 4 0 0 0-3-3.87" />
      <path d="M16 3.13a4 4 0 0 1 0 7.75" />
    </svg>
  )
}

function BranchesIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-5 w-5">
      <path d="M3 21h18" />
      <path d="M5 21V7l7-4 7 4v14" />
      <path d="M9 9h6" />
      <path d="M9 13h6" />
      <path d="M9 17h6" />
    </svg>
  )
}

function ClassesIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-5 w-5">
      <path d="M4 6h16" />
      <path d="M4 12h16" />
      <path d="M4 18h16" />
      <circle cx="7" cy="6" r="1" fill="currentColor" stroke="none" />
      <circle cx="7" cy="12" r="1" fill="currentColor" stroke="none" />
      <circle cx="7" cy="18" r="1" fill="currentColor" stroke="none" />
    </svg>
  )
}

function ImportIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-5 w-5">
      <path d="M12 3v12" />
      <path d="M7 10l5 5 5-5" />
      <path d="M4 21h16" />
      <path d="M4 17v4" />
      <path d="M20 17v4" />
    </svg>
  )
}

function OrgIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-5 w-5">
      <rect x="3" y="3" width="7" height="18" rx="1.5" />
      <rect x="14" y="8" width="7" height="13" rx="1.5" />
      <path d="M6.5 7h.01M6.5 11h.01M6.5 15h.01M17.5 12h.01M17.5 16h.01" />
    </svg>
  )
}

function PlansIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-5 w-5">
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="M8 9h8" />
      <path d="M8 13h8" />
      <path d="M8 17h5" />
    </svg>
  )
}

function PaymentsIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-5 w-5">
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="M3 9h18" />
      <path d="M7 14h4" />
      <path d="M14 14h3" />
    </svg>
  )
}

function ReportsIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-5 w-5">
      <path d="M3 3v18h18" />
      <path d="M7 15l4-5 3 3 5-7" />
    </svg>
  )
}

function QrIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-5 w-5">
      <rect x="3" y="3" width="7" height="7" rx="1" />
      <rect x="14" y="3" width="7" height="7" rx="1" />
      <rect x="3" y="14" width="7" height="7" rx="1" />
      <path d="M14 14h3v3M20 14v.01M14 20h.01M17 20h.01M20 17v3" />
    </svg>
  )
}

function SettingsIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-5 w-5">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  )
}

const navByRole = {
  superadmin: [
    { type: 'item', to: '/superadmin/organizations', label: 'Organizaciones', icon: <OrgIcon /> },
    { type: 'item', to: '/superadmin/users', label: 'Usuarios por organización', icon: <UsersIcon /> },
    { type: 'item', to: '/superadmin/platform', label: 'Plataforma', icon: <UsersIcon /> },
    { type: 'item', to: '/superadmin/plans', label: 'Planes', icon: <PlansIcon /> },
    {
      type: 'group',
      label: 'Pagos Profesores',
      icon: <PaymentsIcon />,
      children: [
        { to: '/superadmin/teacher-payments', label: 'Resumen pagos' },
        { to: '/superadmin/teacher-payments/rules', label: 'Reglas de pago' },
      ],
    },
  ],
  gym_admin: [
    { type: 'item', to: '/gym-admin/dashboard', label: 'Dashboard', icon: <DashboardIcon /> },
    { type: 'item', to: '/gym-admin/users', label: 'Usuarios', icon: <UsersIcon /> },
    { type: 'item', to: '/gym-admin/branches', label: 'Sucursales', icon: <BranchesIcon /> },
    { type: 'item', to: '/gym-admin/attendance-qr', label: 'QR asistencia', icon: <ClassesIcon /> },
    { type: 'item', to: '/gym-admin/import', label: 'Importar datos', icon: <ImportIcon /> },
    {
      type: 'group',
      label: 'Clases',
      icon: <ClassesIcon />,
      children: [
        { to: '/gym-admin/classes', label: 'Ver clases' },
        { to: '/gym-admin/class-templates', label: 'Crear Clase' },
        { to: '/gym-admin/holidays', label: 'Festivos' },
        { to: '/gym-admin/class-types', label: 'Tipos de clase' },
        { to: '/gym-admin/disciplines', label: 'Disciplinas' },
      ],
    },
    {
      type: 'group',
      label: 'Planes',
      icon: <PlansIcon />,
      children: [
        { to: '/gym-admin/plans', label: 'Lista de planes' },
        { to: '/gym-admin/plans/assign', label: 'Asignar plan' },
      ],
    },
    {
      type: 'group',
      label: 'Pagos Profesores',
      icon: <PaymentsIcon />,
      children: [
        { to: '/gym-admin/teacher-payments', label: 'Resumen pagos' },
        { to: '/gym-admin/teacher-payments/rules', label: 'Reglas de pago' },
      ],
    },
    {
      // P3.4: reportería, SOLO gym_admin (manager/monitor reutilizan /gym-admin/* para
      // todo lo demás, pero NO para esto — el backend responde 403 a ambos roles).
      type: 'group',
      label: 'Reportes',
      icon: <ReportsIcon />,
      children: [
        { to: '/gym-admin/reports/revenue', label: 'Ingresos' },
        { to: '/gym-admin/reports/occupancy', label: 'Ocupación' },
        { to: '/gym-admin/reports/retention', label: 'Retención' },
        { to: '/gym-admin/reports/trial-conversion', label: 'Conversión de prueba' },
      ],
    },
    {
      type: 'group',
      label: 'Configuraciones',
      icon: <SettingsIcon />,
      children: [
        { to: '/gym-admin/pagos/transacciones', label: 'Transacciones' },
        { to: '/ajustes/pagos', label: 'Pagos (MercadoPago)' },
        { to: '/gym-admin/settings/trial-followup', label: 'Emails de prueba' },
        { to: '/gym-admin/settings/expiry-notification', label: 'Avisos de vencimiento' },
        { to: '/gym-admin/settings/teacher-payment', label: 'Pago al profesor' },
      ],
    },
  ],
  teacher: [
    { type: 'item', to: '/teacher/dashboard', label: 'Dashboard', icon: <DashboardIcon /> },
    {
      type: 'group',
      label: 'Mis clases',
      icon: <ClassesIcon />,
      children: [
        { to: '/teacher/classes/upcoming', label: 'Próximas clases' },
        { to: '/teacher/classes/history', label: 'Clases realizadas' },
      ],
    },
    { type: 'item', to: '/teacher/payments', label: 'Mis pagos', icon: <PaymentsIcon /> },
  ],
  student: [
    { type: 'item', to: '/student/dashboard', label: 'Dashboard', icon: <DashboardIcon /> },
    { type: 'item', to: '/student/attendance', label: 'Marcar asistencia', icon: <QrIcon /> },
    {
      type: 'group',
      label: 'Mis planes',
      icon: <PlansIcon />,
      children: [
        { to: '/student/plans', label: 'Vigentes' },
        { to: '/student/plans/comprar', label: 'Comprar plan' },
      ],
    },
    {
      type: 'group',
      label: 'Mis clases',
      icon: <ClassesIcon />,
      children: [
        { to: '/student/classes/available', label: 'Disponibles' },
        { to: '/student/classes/reservations', label: 'Mis reservas' },
        { to: '/student/classes/recurring', label: 'Mis recurrencias' },
        { to: '/student/classes/history', label: 'Historial' },
      ],
    },
  ],
  // Manager: páginas operativas del gym_admin (reutiliza /gym-admin/*). Sin planes,
  // sin pagos a profesores, sin QR; ve sucursales en solo lectura.
  manager: [
    { type: 'item', to: '/gym-admin/dashboard', label: 'Dashboard', icon: <DashboardIcon /> },
    { type: 'item', to: '/gym-admin/users', label: 'Usuarios', icon: <UsersIcon /> },
    { type: 'item', to: '/gym-admin/branches', label: 'Sucursales', icon: <BranchesIcon /> },
    {
      type: 'group',
      label: 'Clases',
      icon: <ClassesIcon />,
      children: [
        { to: '/gym-admin/classes', label: 'Ver clases' },
        { to: '/gym-admin/class-templates', label: 'Crear Clase' },
        { to: '/gym-admin/holidays', label: 'Festivos' },
        { to: '/gym-admin/class-types', label: 'Tipos de clase' },
        { to: '/gym-admin/disciplines', label: 'Disciplinas' },
      ],
    },
  ],
  // Monitor: solo lectura sobre lo de su organización (reutiliza /gym-admin/*).
  monitor: [
    {
      type: 'group',
      label: 'Clases',
      icon: <ClassesIcon />,
      children: [
        { to: '/gym-admin/classes', label: 'Ver clases' },
        { to: '/gym-admin/holidays', label: 'Festivos' },
        { to: '/gym-admin/class-types', label: 'Tipos de clase' },
        { to: '/gym-admin/disciplines', label: 'Disciplinas' },
      ],
    },
    { type: 'item', to: '/gym-admin/users', label: 'Usuarios', icon: <UsersIcon /> },
    {
      type: 'group',
      label: 'Pagos Profesores',
      icon: <PaymentsIcon />,
      children: [
        { to: '/gym-admin/teacher-payments', label: 'Resumen pagos' },
        { to: '/gym-admin/teacher-payments/rules', label: 'Reglas de pago' },
      ],
    },
  ],
}

export default function Sidebar({ isOpen, isMobile, user, onNavigate, onRequestOpen }) {
  const items = navByRole[user?.role] || []
  const displayExpanded = isMobile || isOpen

  return (
    <aside
      className={[
        'pt-safe-top z-40 flex h-screen-dvh flex-col border-r border-brand-line bg-brand-black transition-all duration-300 ease-out',
        isMobile ? 'fixed left-0 top-0 w-60' : displayExpanded ? 'w-60 shrink-0' : 'w-[70px] shrink-0',
        isMobile && !isOpen ? '-translate-x-full' : 'translate-x-0',
      ].join(' ')}
    >
      <div className="flex h-16 items-center border-b border-brand-line px-4">
        {displayExpanded ? <span className="text-xs font-semibold uppercase tracking-[0.3em] text-brand-orange">TYMRO</span> : null}
      </div>

      <nav className="flex-1 overflow-y-auto px-2 py-3">
        <ul className="space-y-1">
          {items.map((item) => (
            <li key={`${item.type}-${item.label}`}>
              {item.type === 'group' ? (
                <SidebarGroup
                  label={item.label}
                  icon={item.icon}
                  items={item.children}
                  isOpen={isOpen}
                  isMobile={isMobile}
                  onNavigate={onNavigate}
                  onRequestOpen={onRequestOpen}
                />
              ) : (
                <SidebarItem
                  to={item.to}
                  label={item.label}
                  icon={item.icon}
                  isOpen={isOpen}
                  isMobile={isMobile}
                  onNavigate={onNavigate}
                />
              )}
            </li>
          ))}
        </ul>
      </nav>
    </aside>
  )
}
