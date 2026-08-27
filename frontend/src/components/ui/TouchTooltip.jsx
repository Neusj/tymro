import { useEffect, useId, useRef, useState } from 'react'

export default function TouchTooltip({ text, label = 'Info', children, className = 'relative inline-flex' }) {
  const [open, setOpen] = useState(false)
  const wrapRef = useRef(null)
  const tooltipId = useId()

  useEffect(() => {
    if (!open) {
      return undefined
    }
    const handleOutside = (event) => {
      if (!wrapRef.current?.contains(event.target)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleOutside)
    document.addEventListener('touchstart', handleOutside)
    return () => {
      document.removeEventListener('mousedown', handleOutside)
      document.removeEventListener('touchstart', handleOutside)
    }
  }, [open])

  return (
    <span
      ref={wrapRef}
      data-keep-menu-open="true"
      data-tooltip-root="true"
      className={`relative ${className}`}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocusCapture={() => setOpen(true)}
      onBlurCapture={() => setOpen(false)}
    >
      {children || (
        <button
          type="button"
          onClick={() => setOpen((prev) => !prev)}
          className="inline-flex h-5 w-5 items-center justify-center rounded-full border border-brand-line text-[10px] text-brand-muted hover:text-brand-white"
          aria-label={label}
          aria-describedby={open ? tooltipId : undefined}
        >
          i
        </button>
      )}
      {open ? (
        <span
          id={tooltipId}
          role="tooltip"
          className="absolute right-0 top-6 z-20 w-52 rounded-lg border border-brand-line bg-brand-soft px-2 py-1 text-[11px] text-brand-white shadow-glow"
        >
          {text}
        </span>
      ) : null}
    </span>
  )
}
