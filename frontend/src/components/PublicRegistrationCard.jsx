import { useEffect, useState } from 'react'
import QRCode from 'qrcode'
import { organizationsApi } from '../api/client'
import FormModal from './FormModal'

export default function PublicRegistrationCard() {
  const [org, setOrg] = useState(null)
  const [copied, setCopied] = useState(false)
  const [qrCopied, setQrCopied] = useState(false)
  const [qrOpen, setQrOpen] = useState(false)
  const [qrImage, setQrImage] = useState('')
  const [savingToggle, setSavingToggle] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    const load = async () => {
      try {
        const data = await organizationsApi.list()
        const mine = Array.isArray(data) ? data[0] : data?.results?.[0]
        if (active) {
          setOrg(mine || null)
        }
      } catch {
        if (active) {
          setError('No se pudo cargar el link de registro.')
        }
      }
    }
    load()
    return () => {
      active = false
    }
  }, [])

  const link = org?.public_registration_url || ''
  const enabled = Boolean(org?.public_registration_enabled)

  const copy = async () => {
    if (!link) {
      return
    }
    try {
      await navigator.clipboard.writeText(link)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1800)
    } catch {
      setError('No se pudo copiar. Cópialo manualmente.')
    }
  }

  const openQr = async () => {
    if (!link) {
      return
    }
    setError('')
    try {
      const image = await QRCode.toDataURL(link, {
        width: 640,
        margin: 2,
        color: { dark: '#0b0b0d', light: '#ffffff' },
      })
      setQrImage(image)
      setQrCopied(false)
      setQrOpen(true)
    } catch {
      setError('No se pudo generar el QR.')
    }
  }

  const downloadQr = () => {
    if (!qrImage) {
      return
    }
    const anchor = document.createElement('a')
    anchor.href = qrImage
    anchor.download = `clase-prueba-${org?.slug || 'gym'}.png`
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
  }

  const copyQrImage = async () => {
    if (!qrImage) {
      return
    }
    try {
      const blob = await (await fetch(qrImage)).blob()
      await navigator.clipboard.write([new window.ClipboardItem({ 'image/png': blob })])
      setQrCopied(true)
      window.setTimeout(() => setQrCopied(false), 1800)
    } catch {
      setError('Tu navegador no permite copiar la imagen. Usá "Descargar PNG".')
    }
  }

  const toggleEnabled = async () => {
    if (!org) {
      return
    }
    setSavingToggle(true)
    setError('')
    try {
      const updated = await organizationsApi.setPublicRegistration(org.id, !enabled)
      setOrg(updated)
    } catch {
      setError('No se pudo cambiar el estado del registro.')
    } finally {
      setSavingToggle(false)
    }
  }

  return (
    <article className="card-surface p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="panel-title">Link de clase de prueba</h2>
          <p className="mt-1 text-sm text-brand-muted">
            Comparte este link para que nuevos alumnos se registren solos y reserven una clase gratis.
          </p>
        </div>
        <button
          type="button"
          onClick={toggleEnabled}
          disabled={!org || savingToggle}
          className={`shrink-0 rounded-full border px-3 py-1 text-xs font-semibold transition disabled:opacity-60 ${
            enabled
              ? 'border-success-line bg-success-soft text-success'
              : 'border-brand-line bg-black/30 text-brand-muted'
          }`}
        >
          {enabled ? 'Activado' : 'Desactivado'}
        </button>
      </div>

      <div className="mt-4 flex flex-col gap-2 sm:flex-row">
        <input
          readOnly
          value={link}
          onFocus={(event) => event.target.select()}
          className="field min-h-11 flex-1 px-3 text-sm"
          placeholder="Cargando…"
        />
        <div className="flex gap-2">
          <button
            type="button"
            onClick={copy}
            disabled={!link}
            className="min-h-11 rounded-xl bg-brand-blue px-4 py-2 text-sm font-semibold text-white transition hover:brightness-110 disabled:opacity-60"
          >
            {copied ? '¡Copiado!' : 'Copiar'}
          </button>
          <button
            type="button"
            onClick={openQr}
            disabled={!link}
            className="min-h-11 rounded-xl border border-brand-line px-4 py-2 text-sm font-semibold text-brand-white transition hover:border-brand-orange hover:text-brand-orange disabled:opacity-60"
          >
            QR
          </button>
        </div>
      </div>

      {!enabled && org ? (
        <p className="mt-3 text-xs text-brand-muted">
          El registro público está desactivado: este link no funcionará hasta que lo actives.
        </p>
      ) : null}

      {error ? <p className="mt-3 text-sm text-red-200">{error}</p> : null}

      <FormModal open={qrOpen} title="QR de clase de prueba" onClose={() => setQrOpen(false)}>
        <div className="space-y-4 text-center">
          <p className="text-sm text-brand-muted">
            Escanéalo para abrir el registro. Ideal para folletos, vitrinas y redes.
          </p>
          {qrImage ? (
            <img
              src={qrImage}
              alt="QR del link de clase de prueba"
              className="mx-auto h-56 w-56 rounded-2xl border border-brand-line bg-white p-3"
            />
          ) : null}
          <p className="break-all text-xs text-brand-dim">{link}</p>
          <div className="flex flex-col gap-2 sm:flex-row sm:justify-center">
            <button
              type="button"
              onClick={downloadQr}
              className="min-h-11 rounded-xl bg-brand-blue px-4 py-2 text-sm font-semibold text-white transition hover:brightness-110"
            >
              Descargar PNG
            </button>
            <button
              type="button"
              onClick={copyQrImage}
              className="min-h-11 rounded-xl border border-brand-line px-4 py-2 text-sm font-semibold text-brand-white transition hover:border-brand-orange hover:text-brand-orange"
            >
              {qrCopied ? '¡Imagen copiada!' : 'Copiar imagen'}
            </button>
          </div>
        </div>
      </FormModal>
    </article>
  )
}
