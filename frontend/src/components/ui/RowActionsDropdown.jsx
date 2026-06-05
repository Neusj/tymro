import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

function GearIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4 w-4">
      <path d="M12 8.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7Z" />
      <path d="M19.4 15a1 1 0 0 0 .2 1.1l.1.1a1 1 0 0 1 0 1.4l-1.2 1.2a1 1 0 0 1-1.4 0l-.1-.1a1 1 0 0 0-1.1-.2 1 1 0 0 0-.6.9V20a1 1 0 0 1-1 1h-1.6a1 1 0 0 1-1-1v-.1a1 1 0 0 0-.6-.9 1 1 0 0 0-1.1.2l-.1.1a1 1 0 0 1-1.4 0l-1.2-1.2a1 1 0 0 1 0-1.4l.1-.1a1 1 0 0 0 .2-1.1 1 1 0 0 0-.9-.6H4a1 1 0 0 1-1-1v-1.6a1 1 0 0 1 1-1h.1a1 1 0 0 0 .9-.6 1 1 0 0 0-.2-1.1l-.1-.1a1 1 0 0 1 0-1.4l1.2-1.2a1 1 0 0 1 1.4 0l.1.1a1 1 0 0 0 1.1.2 1 1 0 0 0 .6-.9V4a1 1 0 0 1 1-1h1.6a1 1 0 0 1 1 1v.1a1 1 0 0 0 .6.9 1 1 0 0 0 1.1-.2l.1-.1a1 1 0 0 1 1.4 0l1.2 1.2a1 1 0 0 1 0 1.4l-.1.1a1 1 0 0 0-.2 1.1 1 1 0 0 0 .9.6H20a1 1 0 0 1 1 1v1.6a1 1 0 0 1-1 1h-.1a1 1 0 0 0-.9.6Z" />
    </svg>
  )
}

export default function RowActionsDropdown({ children, align = 'right' }) {
  const [open, setOpen] = useState(false)
  const [menuPosition, setMenuPosition] = useState({ top: 0, left: 0, right: 'auto' })
  const containerRef = useRef(null)
  const buttonRef = useRef(null)
  const menuRef = useRef(null)

  useEffect(() => {
    if (!open) {
      return undefined
    }

    const updatePosition = () => {
      const buttonRect = buttonRef.current?.getBoundingClientRect()
      if (!buttonRect) {
        return
      }

      const top = buttonRect.bottom + 8
      if (align === 'left') {
        setMenuPosition({ top, left: buttonRect.left, right: 'auto' })
        return
      }

      setMenuPosition({
        top,
        left: 'auto',
        right: Math.max(8, window.innerWidth - buttonRect.right),
      })
    }

    const handleOutsideClick = (event) => {
      const clickedInsideTrigger = containerRef.current?.contains(event.target)
      const clickedInsideMenu = menuRef.current?.contains(event.target)
      if (!clickedInsideTrigger && !clickedInsideMenu) {
        setOpen(false)
      }
    }

    const handleEscape = (event) => {
      if (event.key === 'Escape') {
        setOpen(false)
      }
    }

    updatePosition()
    document.addEventListener('mousedown', handleOutsideClick)
    document.addEventListener('keydown', handleEscape)
    window.addEventListener('resize', updatePosition)
    window.addEventListener('scroll', updatePosition, true)

    return () => {
      document.removeEventListener('mousedown', handleOutsideClick)
      document.removeEventListener('keydown', handleEscape)
      window.removeEventListener('resize', updatePosition)
      window.removeEventListener('scroll', updatePosition, true)
    }
  }, [align, open])

  return (
    <div ref={containerRef} className="relative inline-flex">
      <button
        ref={buttonRef}
        type="button"
        aria-label="Abrir acciones"
        aria-expanded={open}
        onClick={() => setOpen((prev) => !prev)}
        className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-brand-line bg-black/30 text-brand-muted transition hover:border-brand-orange hover:text-brand-white"
      >
        <GearIcon />
      </button>

      {open && typeof document !== 'undefined'
        ? createPortal(
            <div
              ref={menuRef}
              className="fixed z-[1200] min-w-[11rem] rounded-lg border border-brand-line bg-brand-soft p-2 shadow-glow"
              style={{ top: menuPosition.top, left: menuPosition.left, right: menuPosition.right }}
              onClick={(event) => {
                const interactive = event.target.closest('button, a')
                if (interactive) {
                  setOpen(false)
                }
              }}
            >
              <div className="flex flex-col gap-2">{children}</div>
            </div>,
            document.body,
          )
        : null}
    </div>
  )
}
