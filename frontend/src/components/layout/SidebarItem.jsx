import { NavLink } from 'react-router-dom'

export default function SidebarItem({ to, label, icon, isOpen, isMobile, onNavigate }) {
  const expanded = isMobile || isOpen

  return (
    <div className="group relative">
      <NavLink
        to={to}
        onClick={() => {
          if (isMobile) {
            onNavigate()
          }
        }}
        title={!expanded ? label : undefined}
        className={({ isActive }) =>
          [
            'flex h-11 items-center gap-3 rounded-lg border px-3 text-sm font-medium transition duration-200',
            expanded ? 'justify-start' : 'justify-center px-0',
            isActive
              ? 'border-brand-orange bg-brand-orange/15 text-brand-white'
              : 'border-transparent text-brand-muted hover:border-brand-line hover:bg-brand-soft hover:text-brand-white',
          ].join(' ')
        }
      >
        <span className="shrink-0">{icon}</span>
        <span className={[expanded ? 'opacity-100' : 'w-0 opacity-0', 'whitespace-nowrap transition-opacity duration-200'].join(' ')}>{label}</span>
      </NavLink>

      {!expanded ? (
        <span className="pointer-events-none absolute left-full top-1/2 z-50 ml-2 -translate-y-1/2 whitespace-nowrap rounded-md border border-brand-line bg-brand-soft px-2 py-1 text-xs text-brand-white opacity-0 shadow-glow transition-opacity duration-200 group-hover:opacity-100">
          {label}
        </span>
      ) : null}
    </div>
  )
}
