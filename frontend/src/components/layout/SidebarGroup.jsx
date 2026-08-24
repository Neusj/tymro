import { useEffect, useState } from 'react'
import { NavLink, useLocation } from 'react-router-dom'

function ChevronIcon({ expanded }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      className={['h-4 w-4 shrink-0 transition-transform duration-200', expanded ? 'rotate-90' : 'rotate-0'].join(' ')}
    >
      <path d="m9 18 6-6-6-6" />
    </svg>
  )
}

function itemIsActive(item, pathname) {
  if (item.type === 'section') {
    return (item.children || []).some((child) => itemIsActive(child, pathname))
  }
  return Boolean(item.to) && (pathname === item.to || pathname.startsWith(`${item.to}/`))
}

function SidebarChildLink({ item, isMobile, onNavigate }) {
  return (
    <NavLink
      to={item.to}
      onClick={() => {
        if (isMobile) {
          onNavigate()
        }
      }}
      className={({ isActive }) =>
        [
          'block rounded-lg px-2 py-2 text-sm transition duration-200',
          isActive
            ? 'bg-brand-orange/20 text-brand-white'
            : 'text-brand-muted hover:bg-brand-soft hover:text-brand-white',
        ].join(' ')
      }
    >
      {item.label}
    </NavLink>
  )
}

function SidebarSection({ item, pathname, isMobile, onNavigate }) {
  const hasActiveChild = itemIsActive(item, pathname)
  const [expanded, setExpanded] = useState(hasActiveChild)

  useEffect(() => {
    if (hasActiveChild) {
      setExpanded(true)
    }
  }, [hasActiveChild])

  return (
    <div className="pt-1">
      <button
        type="button"
        aria-expanded={expanded}
        onClick={() => setExpanded((prev) => !prev)}
        className={[
          'flex min-h-9 w-full items-center justify-between gap-2 rounded-lg px-2 py-2 text-left text-xs font-semibold uppercase tracking-wide transition duration-200',
          hasActiveChild
            ? 'bg-brand-orange/15 text-brand-white'
            : 'text-brand-dim hover:bg-brand-soft hover:text-brand-white',
        ].join(' ')}
      >
        <span className="truncate">{item.label}</span>
        <ChevronIcon expanded={expanded} />
      </button>
      {expanded ? (
        <ul className="mt-1 space-y-1 pl-3">
          {(item.children || []).map((child) => (
            <li key={child.type === 'section' ? child.label : child.to}>
              {child.type === 'section' ? (
                <SidebarSection item={child} pathname={pathname} isMobile={isMobile} onNavigate={onNavigate} />
              ) : (
                <SidebarChildLink item={child} isMobile={isMobile} onNavigate={onNavigate} />
              )}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}

export default function SidebarGroup({ label, icon, items, isOpen, isMobile, onNavigate, onRequestOpen }) {
  const location = useLocation()
  const expandedSidebar = isMobile || isOpen
  const hasActiveChild = items.some((item) => itemIsActive(item, location.pathname))
  const [expanded, setExpanded] = useState(hasActiveChild)

  useEffect(() => {
    if (hasActiveChild) {
      setExpanded(true)
    }
  }, [hasActiveChild])

  const handleToggle = () => {
    if (!expandedSidebar) {
      if (!isMobile) {
        onRequestOpen?.()
        setExpanded(true)
      }
      return
    }
    setExpanded((prev) => !prev)
  }

  return (
    <div className="group relative">
      <button
        type="button"
        onClick={handleToggle}
        title={!expandedSidebar ? label : undefined}
        className={[
          'flex h-11 w-full items-center rounded-lg border px-3 text-sm font-medium transition duration-200',
          expandedSidebar ? 'justify-between' : 'justify-center px-0',
          hasActiveChild
            ? 'border-brand-orange bg-brand-orange/15 text-brand-white'
            : 'border-transparent text-brand-muted hover:border-brand-line hover:bg-brand-soft hover:text-brand-white',
        ].join(' ')}
      >
        <span className="flex min-w-0 items-center gap-3">
          <span className="shrink-0">{icon}</span>
          <span
            className={[
              expandedSidebar ? 'opacity-100' : 'w-0 opacity-0',
              'whitespace-nowrap transition-opacity duration-200',
            ].join(' ')}
          >
            {label}
          </span>
        </span>
        {expandedSidebar ? <ChevronIcon expanded={expanded} /> : null}
      </button>

      {!expandedSidebar ? (
        <span className="pointer-events-none absolute left-full top-1/2 z-50 ml-2 -translate-y-1/2 whitespace-nowrap rounded-md border border-brand-line bg-brand-soft px-2 py-1 text-xs text-brand-white opacity-0 shadow-glow transition-opacity duration-200 group-hover:opacity-100">
          {label}
        </span>
      ) : null}

      <div
        className={[
          'grid overflow-hidden transition-all duration-300 ease-out',
          expandedSidebar && expanded ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0',
        ].join(' ')}
      >
        <ul className="min-h-0 space-y-1 pl-8 pt-1">
          {items.map((item) => (
            <li key={item.type === 'section' ? item.label : item.to}>
              {item.type === 'section' ? (
                <SidebarSection
                  item={item}
                  pathname={location.pathname}
                  isMobile={isMobile}
                  onNavigate={onNavigate}
                />
              ) : (
                <SidebarChildLink item={item} isMobile={isMobile} onNavigate={onNavigate} />
              )}
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
