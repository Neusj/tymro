import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

const MENU_MIN_WIDTH = 220
const VIEWPORT_MARGIN = 8
const GAP = 6 // separacion entre el trigger y el panel
// Alto del panel estimado en vez de medido: medir exige renderizar primero, y eso obliga a un
// doble pase que parpadea al abrir. Los numeros salen de las clases de abajo — si cambian el
// min-h de las filas, el space-y o el padding del footer, hay que actualizarlos o el panel
// muestra scrollbar cuando en realidad entra entero.
const ROW_HEIGHT = 48 // min-h-11 (44) + space-y-1 (4)
const LIST_PADDING = 16 // p-2 arriba y abajo
const FOOTER_HEIGHT = 46 // contador + boton "Listo" (medido 43; se redondea hacia arriba a
// proposito: quedarse corto aprieta la lista y le mete scroll aunque el panel entre entero,
// mientras que pasarse solo deja el cap un poco holgado y no rompe nada)

// "Lunes" / "Lunes y Viernes" / "Lunes, Miercoles y Viernes".
function joinReadable(labels) {
  if (labels.length <= 1) {
    return labels[0] || ''
  }
  return `${labels.slice(0, -1).join(', ')} y ${labels[labels.length - 1]}`
}

/**
 * Dropdown de seleccion multiple. Mismo vocabulario visual que FilterDropdown (portal a
 * document.body con position:fixed, animate-scale-in, cierre por Escape / click afuera), pero
 * con checkboxes reales adentro: se pueden marcar varios y el panel NO se cierra al elegir.
 *
 * El portal es obligatorio, no cosmetico: el form vive dentro de .card-surface, y un menu en
 * position:absolute queda recortado por el contenedor.
 */
export default function MultiSelectDropdown({
  label,
  options = [],
  value = [],
  onChange,
  placeholder = 'Seleccionar',
  allSelectedLabel,
  invalid = false,
  className = '',
}) {
  const id = useId()
  const labelId = `${id}-label`
  const panelId = `${id}-panel`
  const [open, setOpen] = useState(false)
  const [coords, setCoords] = useState(null)
  const buttonRef = useRef(null)
  const menuRef = useRef(null)

  const selectedLabels = options.filter((option) => value.includes(option.value)).map((option) => option.label)
  const allSelected = options.length > 0 && selectedLabels.length === options.length
  const summary = allSelected && allSelectedLabel ? allSelectedLabel : joinReadable(selectedLabels)

  const closeAndRefocus = () => {
    setOpen(false)
    buttonRef.current?.focus()
  }

  const toggle = (optionValue) => {
    const next = value.includes(optionValue)
      ? value.filter((item) => item !== optionValue)
      : [...value, optionValue]
    // Ordenado por el orden del catalogo, no por orden de click: si no, marcar Viernes antes
    // que Lunes mandaria [4,0] y el resumen se leeria "Viernes y Lunes".
    onChange(options.filter((option) => next.includes(option.value)).map((option) => option.value))
  }

  const updatePosition = () => {
    const el = buttonRef.current
    if (!el || typeof window === 'undefined') {
      return
    }
    const rect = el.getBoundingClientRect()
    const width = Math.min(
      Math.max(rect.width, MENU_MIN_WIDTH),
      window.innerWidth - VIEWPORT_MARGIN * 2,
    )
    const maxLeft = Math.max(VIEWPORT_MARGIN, window.innerWidth - width - VIEWPORT_MARGIN)
    const left = Math.min(Math.max(VIEWPORT_MARGIN, rect.left), maxLeft)

    const wanted = options.length * ROW_HEIGHT + LIST_PADDING + FOOTER_HEIGHT
    const spaceBelow = Math.max(0, window.innerHeight - rect.bottom - VIEWPORT_MARGIN - GAP)
    const spaceAbove = Math.max(0, rect.top - VIEWPORT_MARGIN - GAP)
    // Voltea hacia arriba solo si abajo no entra Y arriba tiene mas aire: en un form largo en
    // movil el campo suele quedar en la mitad baja de la pantalla.
    const flip = spaceBelow < wanted && spaceAbove > spaceBelow
    // Sin piso de altura: un piso mayor al espacio disponible empuja el panel fuera del
    // viewport (pasaba en landscape de celular). Acotado al aire real, el panel siempre entra
    // y si queda corto scrollea adentro.
    const maxHeight = Math.min(wanted, flip ? spaceAbove : spaceBelow)
    const top = flip ? rect.top - GAP - maxHeight : rect.bottom + GAP

    setCoords({ top, left, width, maxHeight })
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
  }, [open, options.length])

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
        closeAndRefocus()
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

  // El panel se monta como portal al final del body, asi que Tab desde el trigger NO cae
  // adentro. Mover el foco a la primera opcion al abrir es lo que lo hace navegable por teclado.
  useEffect(() => {
    if (open && coords) {
      menuRef.current?.querySelector('input[type="checkbox"]')?.focus()
    }
  }, [open, Boolean(coords)])

  return (
    <div className={`space-y-1 text-sm ${className}`.trim()}>
      <span id={labelId} className="block">
        {label}
      </span>
      <button
        ref={buttonRef}
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        aria-labelledby={labelId}
        aria-invalid={invalid || undefined}
        className={`flex min-h-11 w-full items-center justify-between gap-2 rounded-lg border bg-black/30 px-3 py-2 text-left text-sm transition ${
          invalid ? 'border-brand-red' : 'border-brand-line hover:border-brand-orange'
        }`}
      >
        <span className="flex min-w-0 items-center gap-2">
          <span className={`truncate ${selectedLabels.length ? 'text-brand-white' : 'text-brand-muted'}`}>
            {summary || placeholder}
          </span>
          {selectedLabels.length > 1 ? (
            <span className="shrink-0 rounded-md bg-brand-blue/25 px-1.5 py-0.5 text-[11px] font-semibold text-brand-white">
              {selectedLabels.length}
            </span>
          ) : null}
        </span>
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
          className={`shrink-0 text-brand-muted transition-transform duration-200 ${open ? 'rotate-180' : ''}`}
        >
          <path d="m6 9 6 6 6-6" />
        </svg>
      </button>

      {open && coords
        ? createPortal(
            <div
              ref={menuRef}
              id={panelId}
              role="group"
              aria-labelledby={labelId}
              style={{
                position: 'fixed',
                top: coords.top,
                left: coords.left,
                width: coords.width,
                // El cap va sobre el panel entero, no sobre la lista: si solo se limitara la
                // lista, el footer sumaria su alto encima y el panel se saldria del viewport.
                maxHeight: coords.maxHeight,
              }}
              className="z-[80] flex animate-scale-in flex-col overflow-hidden rounded-lg border border-brand-line bg-brand-soft shadow-glow"
            >
              <div className="min-h-0 flex-1 space-y-1 overflow-y-auto p-2">
                {options.map((option) => {
                  const checked = value.includes(option.value)
                  return (
                    <label
                      key={option.value}
                      className={`flex min-h-11 cursor-pointer items-center gap-3 rounded-md border px-2.5 py-2 text-sm text-brand-white transition ${
                        checked ? 'border-brand-blue bg-brand-blue/20' : 'border-transparent hover:border-brand-line'
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggle(option.value)}
                        className="h-4 w-4 shrink-0 accent-brand-orange"
                      />
                      {option.label}
                    </label>
                  )
                })}
              </div>
              <div className="flex shrink-0 items-center justify-between gap-3 border-t border-brand-line px-3 py-2">
                <span className="text-xs text-brand-muted">
                  {selectedLabels.length} de {options.length} elegidos
                </span>
                <button
                  type="button"
                  onClick={closeAndRefocus}
                  className="rounded-lg border border-brand-line px-2.5 py-1.5 text-xs font-semibold text-brand-white transition hover:border-brand-orange"
                >
                  Listo
                </button>
              </div>
            </div>,
            document.body,
          )
        : null}
    </div>
  )
}
