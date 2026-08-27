import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

const VIEWPORT_MARGIN = 8
const MENU_GAP = 8
const DEFAULT_MENU_WIDTH = 176
const DEFAULT_MENU_HEIGHT = 280

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
  const [menuPosition, setMenuPosition] = useState({
    top: VIEWPORT_MARGIN,
    left: VIEWPORT_MARGIN,
    maxHeight: DEFAULT_MENU_HEIGHT,
  })
  const containerRef = useRef(null)
  const buttonRef = useRef(null)
  const menuRef = useRef(null)

  const updatePosition = () => {
    const buttonRect = buttonRef.current?.getBoundingClientRect()
    if (!buttonRect || typeof window === 'undefined') {
      return
    }

    const menuRect = menuRef.current?.getBoundingClientRect()
    const viewportWidth = window.innerWidth || document.documentElement.clientWidth
    const viewportHeight = window.innerHeight || document.documentElement.clientHeight
    const availableWidth = Math.max(0, viewportWidth - VIEWPORT_MARGIN * 2)
    const menuWidth = Math.min(menuRect?.width || DEFAULT_MENU_WIDTH, availableWidth)
    const menuHeight = menuRect?.height || DEFAULT_MENU_HEIGHT
    const preferredLeft = align === 'left' ? buttonRect.left : buttonRect.right - menuWidth
    const maxLeft = Math.max(VIEWPORT_MARGIN, viewportWidth - menuWidth - VIEWPORT_MARGIN)
    const left = Math.min(Math.max(VIEWPORT_MARGIN, preferredLeft), maxLeft)

    const spaceBelow = Math.max(0, viewportHeight - buttonRect.bottom - MENU_GAP - VIEWPORT_MARGIN)
    const spaceAbove = Math.max(0, buttonRect.top - MENU_GAP - VIEWPORT_MARGIN)
    const openUpward = spaceBelow < menuHeight && spaceAbove > spaceBelow
    const maxHeight = Math.max(80, Math.min(menuHeight, openUpward ? spaceAbove : spaceBelow))
    const top = openUpward
      ? Math.max(VIEWPORT_MARGIN, buttonRect.top - MENU_GAP - maxHeight)
      : Math.min(buttonRect.bottom + MENU_GAP, viewportHeight - maxHeight - VIEWPORT_MARGIN)

    setMenuPosition({ top, left, maxHeight })
  }

  useLayoutEffect(() => {
    if (open) {
      updatePosition()
    }
  }, [align, open])

  useEffect(() => {
    if (!open) {
      return undefined
    }

    const updateAfterLayout = () => {
      const schedule = window.requestAnimationFrame || window.setTimeout
      schedule(updatePosition)
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

    updateAfterLayout()
    document.addEventListener('mousedown', handleOutsideClick)
    document.addEventListener('keydown', handleEscape)
    window.addEventListener('resize', updateAfterLayout)
    window.addEventListener('scroll', updateAfterLayout, true)

    return () => {
      document.removeEventListener('mousedown', handleOutsideClick)
      document.removeEventListener('keydown', handleEscape)
      window.removeEventListener('resize', updateAfterLayout)
      window.removeEventListener('scroll', updateAfterLayout, true)
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
              className="fixed z-[1200] min-w-[11rem] overflow-y-auto rounded-lg border border-brand-line bg-brand-soft p-2 shadow-glow"
              style={{ top: menuPosition.top, left: menuPosition.left, maxHeight: menuPosition.maxHeight }}
              onClick={(event) => {
                const interactive = event.target.closest('button, a')
                if (interactive && !interactive.closest('[data-keep-menu-open="true"]')) {
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
