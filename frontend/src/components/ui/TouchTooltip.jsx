import { useEffect, useRef, useState } from 'react'

export default function TouchTooltip({ text, label = 'Info' }) {
  const [open, setOpen] = useState(false)
  const wrapRef = useRef(null)

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
    <span ref={wrapRef} className="relative inline-flex">
      <button
        type="button"
        data-keep-menu-open="true"
        onClick={() => setOpen((prev) => !prev)}
        className="inline-flex h-5 w-5 items-center justify-center rounded-full border border-brand-line text-[10px] text-brand-muted hover:text-brand-white"
        aria-label={label}
      >
        i
      </button>
      {open ? (
        <span className="absolute right-0 top-6 z-20 w-52 rounded-lg border border-brand-line bg-brand-soft px-2 py-1 text-[11px] text-brand-white shadow-glow">
          {text}
        </span>
      ) : null}
    </span>
  )
}
