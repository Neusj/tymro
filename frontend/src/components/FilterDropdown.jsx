import { createContext, useContext, useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

// Permite que varios FilterDropdown coordinen "solo uno abierto a la vez".
// FilterPanel provee este contexto; en uso aislado cae a estado local.
export const FilterGroupContext = createContext(null)

const MENU_MIN_WIDTH = 220

export default function FilterDropdown({ label, value, options = [], onChange }) {
  const group = useContext(FilterGroupContext)
  const id = useId()
  const [localOpen, setLocalOpen] = useState(false)
  const open = group ? group.openId === id : localOpen
  const setOpen = (next) => {
    if (group) {
      group.setOpenId(next ? id : null)
    } else {
      setLocalOpen(next)
    }
  }

  const buttonRef = useRef(null)
  const menuRef = useRef(null)
  const [coords, setCoords] = useState(null)

  const currentLabel = options.find((item) => item.value === value)?.label || 'Todos'

  const updatePosition = () => {
    const el = buttonRef.current
    if (!el || typeof window === 'undefined') {
      return
    }
    const rect = el.getBoundingClientRect()
    const width = Math.max(rect.width, MENU_MIN_WIDTH)
    const left = Math.min(Math.max(8, rect.left), window.innerWidth - width - 8)
    setCoords({ top: rect.bottom + 6, left, width })
  }

  useLayoutEffect(() => {
    if (!open) {
      return undefined
    }
    updatePosition()
    const handle = () => updatePosition()
    window.addEventListener('resize', handle)
    window.addEventListener('scroll', handle, true)
    return () => {
      window.removeEventListener('resize', handle)
      window.removeEventListener('scroll', handle, true)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  useEffect(() => {
    if (!open) {
      return undefined
    }
    const handleClick = (event) => {
      if (buttonRef.current?.contains(event.target) || menuRef.current?.contains(event.target)) {
        return
      }
      setOpen(false)
    }
    const handleKey = (event) => {
      if (event.key === 'Escape') {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    document.addEventListener('keydown', handleKey)
    return () => {
      document.removeEventListener('mousedown', handleClick)
      document.removeEventListener('keydown', handleKey)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  return (
    <div className="relative">
      <button
        ref={buttonRef}
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="inline-flex min-h-10 min-w-[180px] items-center justify-between gap-2 rounded-lg border border-brand-line bg-black/30 px-3 py-2 text-sm text-brand-white transition hover:border-brand-orange"
      >
        <span className="text-brand-muted">{label}:</span>
        <span className="flex items-center gap-1.5">
          {currentLabel}
          <svg
            width="13"
            height="13"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
            className={`text-brand-muted transition-transform duration-200 ${open ? 'rotate-180' : ''}`}
          >
            <path d="m6 9 6 6 6-6" />
          </svg>
        </span>
      </button>
      {open && coords
        ? createPortal(
            <div
              ref={menuRef}
              style={{ position: 'fixed', top: coords.top, left: coords.left, minWidth: coords.width }}
              className="z-[80] animate-scale-in rounded-lg border border-brand-line bg-brand-soft p-2 shadow-glow"
            >
              <div className="max-h-[50vh] space-y-1 overflow-y-auto">
                {options.map((option) => {
                  const active = value === option.value
                  return (
                    <button
                      key={`${label}-${option.value || 'all'}`}
                      type="button"
                      onClick={() => {
                        onChange(option.value)
                        setOpen(false)
                      }}
                      className={`w-full rounded-md px-2 py-1.5 text-left text-sm transition ${
                        active
                          ? 'border border-brand-blue bg-brand-blue/20 text-brand-white'
                          : 'border border-transparent text-brand-muted hover:border-brand-line hover:text-brand-white'
                      }`}
                    >
                      {option.label}
                    </button>
                  )
                })}
              </div>
            </div>,
            document.body,
          )
        : null}
    </div>
  )
}
