import { useEffect, useState } from 'react'
import FormModal from './FormModal'

export default function BulkActionModal({
  open,
  title,
  selectedCount,
  actions = [],
  requiresCommentActions = [],
  defaultAction = '',
  onClose,
  onConfirm,
  loading = false,
}) {
  const [action, setAction] = useState(defaultAction || actions?.[0]?.value || '')
  const [comment, setComment] = useState('')

  useEffect(() => {
    if (!open) {
      return
    }
    setAction(defaultAction || actions?.[0]?.value || '')
    setComment('')
  }, [open, defaultAction, actions])

  const requiresComment = requiresCommentActions.includes(action)
  const selectedAction = actions.find((item) => item.value === action)

  const submit = async (event) => {
    event.preventDefault()
    if (!action) {
      return
    }
    if (requiresComment && !comment.trim()) {
      return
    }
    await onConfirm({ action, comment: comment.trim() })
  }

  return (
    <FormModal open={open} title={title} onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        <div className="rounded-lg border border-brand-line bg-black/30 px-3 py-2 text-sm text-brand-muted">
          Seleccionados: <span className="font-semibold text-brand-white">{selectedCount}</span>
        </div>

        <label className="space-y-1 text-sm">
          <span>Accion</span>
          <select
            value={action}
            onChange={(event) => setAction(event.target.value)}
            className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
          >
            {actions.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </label>

        {selectedAction?.description ? (
          <p className="rounded-lg border border-brand-line bg-black/20 px-3 py-2 text-xs text-brand-muted">{selectedAction.description}</p>
        ) : null}

        {requiresComment ? (
          <label className="space-y-1 text-sm">
            <span>Comentario obligatorio</span>
            <textarea
              value={comment}
              onChange={(event) => setComment(event.target.value)}
              placeholder="Ingresa el motivo de la accion"
              className="min-h-[90px] w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
            />
          </label>
        ) : null}

        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className="rounded-xl border border-brand-line px-4 py-2 text-sm text-brand-muted">
            Cancelar
          </button>
          <button type="submit" disabled={loading || (requiresComment && !comment.trim())} className="rounded-xl bg-brand-blue px-4 py-2 text-sm font-semibold text-white disabled:opacity-60">
            {loading ? 'Procesando...' : 'Confirmar'}
          </button>
        </div>
      </form>
    </FormModal>
  )
}
