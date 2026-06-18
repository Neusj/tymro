import { useEffect, useMemo, useRef, useState } from 'react'
import { importsApi } from '../api/client'
import ConfirmDialog from '../components/ConfirmDialog'
import DashboardHeader from '../components/DashboardHeader'
import DataTable from '../components/ui/DataTable'

const extractApiErrorMessage = (apiError, fallbackMessage) => {
  const detail = apiError?.response?.data
  if (!detail) {
    return fallbackMessage
  }
  if (typeof detail === 'string') {
    return detail
  }
  if (detail.detail && typeof detail.detail === 'string') {
    return detail.detail
  }
  return fallbackMessage
}

const STATUS_STYLES = {
  ok: 'border-success-line bg-success-soft text-success',
  duplicado_archivo: 'border-amber-400/40 bg-amber-400/10 text-amber-200',
  duplicado_existente: 'border-amber-400/40 bg-amber-400/10 text-amber-200',
  error: 'border-brand-red/50 bg-brand-red/10 text-red-200',
}

const STATUS_LABELS = {
  ok: 'Se creará',
  duplicado_archivo: 'Repetida en el archivo',
  duplicado_existente: 'Ya existe',
  error: 'Con errores',
}

function StatusBadge({ status }) {
  return (
    <span className={`inline-flex whitespace-nowrap rounded-full border px-2 py-0.5 text-xs font-semibold ${STATUS_STYLES[status] || ''}`}>
      {STATUS_LABELS[status] || status}
    </span>
  )
}

function SummaryCard({ label, value, tone }) {
  return (
    <div className={`rounded-xl border px-4 py-3 ${tone}`}>
      <p className="text-2xl font-bold">{value}</p>
      <p className="text-xs">{label}</p>
    </div>
  )
}

export default function GymAdminImportPage() {
  const [catalog, setCatalog] = useState([])
  const [loadingCatalog, setLoadingCatalog] = useState(true)
  const [selectedSlug, setSelectedSlug] = useState(null)
  const [file, setFile] = useState(null)
  const [downloading, setDownloading] = useState(false)
  const [validating, setValidating] = useState(false)
  const [validation, setValidation] = useState(null)
  const [onlyErrors, setOnlyErrors] = useState(false)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [committing, setCommitting] = useState(false)
  const [commitResult, setCommitResult] = useState(null)
  const [commitErrorRows, setCommitErrorRows] = useState(null)
  const [error, setError] = useState('')
  const fileInputRef = useRef(null)

  useEffect(() => {
    const load = async () => {
      try {
        const data = await importsApi.entities()
        setCatalog(data.entities || [])
      } catch (apiError) {
        setError(extractApiErrorMessage(apiError, 'No se pudo cargar el catálogo de importación.'))
      } finally {
        setLoadingCatalog(false)
      }
    }
    load()
  }, [])

  const entity = useMemo(
    () => catalog.find((item) => item.slug === selectedSlug) || null,
    [catalog, selectedSlug],
  )

  const dependencyLabels = useMemo(() => {
    if (!entity) {
      return []
    }
    return entity.dependencies
      .map((slug) => catalog.find((item) => item.slug === slug)?.label || slug)
  }, [entity, catalog])

  // El token de previsualización muere con el archivo/entidad previsualizados.
  const resetPreview = () => {
    setValidation(null)
    setCommitResult(null)
    setCommitErrorRows(null)
    setOnlyErrors(false)
    setError('')
  }

  const selectEntity = (slug) => {
    setSelectedSlug(slug)
    setFile(null)
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
    resetPreview()
  }

  const onFileChange = (event) => {
    setFile(event.target.files?.[0] || null)
    resetPreview()
  }

  const downloadTemplate = async () => {
    if (!entity) {
      return
    }
    setDownloading(true)
    setError('')
    try {
      const response = await importsApi.downloadTemplate(entity.slug)
      const blob = new Blob([response.data], { type: response.headers['content-type'] })
      const url = window.URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `plantilla_${entity.slug}.xlsx`
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
    } catch {
      setError('No se pudo descargar la plantilla. Inténtalo de nuevo.')
    } finally {
      setDownloading(false)
    }
  }

  const runValidate = async () => {
    if (!entity || !file) {
      return
    }
    setValidating(true)
    resetPreview()
    try {
      const data = await importsApi.validate(entity.slug, file)
      setValidation(data)
    } catch (apiError) {
      setError(extractApiErrorMessage(apiError, 'No se pudo validar el archivo.'))
    } finally {
      setValidating(false)
    }
  }

  const runCommit = async () => {
    if (!entity || !file || !validation?.token) {
      return
    }
    setConfirmOpen(false)
    setCommitting(true)
    setError('')
    try {
      const data = await importsApi.commit(entity.slug, file, validation.token)
      setCommitResult(data)
      setValidation(null)
      setFile(null)
      if (fileInputRef.current) {
        fileInputRef.current.value = ''
      }
    } catch (apiError) {
      const detail = apiError?.response?.data
      if (Array.isArray(detail?.rows)) {
        setCommitErrorRows(detail.rows)
      }
      setError(extractApiErrorMessage(apiError, 'No se pudo completar la importación.'))
    } finally {
      setCommitting(false)
    }
  }

  const previewRows = useMemo(() => {
    const rows = commitErrorRows || validation?.rows || []
    return onlyErrors ? rows.filter((row) => row.status === 'error') : rows
  }, [validation, commitErrorRows, onlyErrors])

  // Columnas del preview: reproducen las celdas del listado anterior, pero
  // ahora servidas por DataTable (buscador + paginación + scroll interno).
  const previewColumns = useMemo(() => {
    const labels = entity ? entity.fields.map((field) => field.label) : []
    return [
      {
        key: 'row',
        label: 'Fila',
        sortable: true,
        render: (row) => <span className="text-brand-muted">{row.row}</span>,
      },
      {
        key: 'status',
        label: 'Resultado',
        sortable: true,
        render: (row) => <StatusBadge status={row.status} />,
      },
      ...labels.map((label) => ({
        key: `field:${label}`,
        label,
        sortable: false,
        mobile: 'secondary',
        render: (row) => row.values?.[label] ?? '',
      })),
      {
        key: 'detail',
        label: 'Detalle',
        sortable: false,
        render: (row) =>
          row.errors && row.errors.length > 0 ? (
            <ul className="space-y-0.5 text-xs text-red-200">
              {row.errors.map((rowError, index) => (
                <li key={index}>
                  {rowError.column ? `${rowError.column}: ` : ''}
                  {rowError.message}
                </li>
              ))}
            </ul>
          ) : (
            <span className="text-xs text-brand-muted">{row.note}</span>
          ),
      },
    ]
  }, [entity])

  return (
    <div className="space-y-6">
      <DashboardHeader
        title="Importar datos"
        subtitle="Carga la información inicial de tu gimnasio desde plantillas Excel: descarga, completa, valida y confirma."
      />

      {/* Paso 1: elegir entidad */}
      <section className="card-surface space-y-3 p-5">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-brand-muted">1 · ¿Qué quieres importar?</h2>
        {loadingCatalog ? (
          <p className="text-sm text-brand-muted">Cargando catálogo…</p>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {catalog.map((item) => (
              <button
                key={item.slug}
                type="button"
                onClick={() => selectEntity(item.slug)}
                className={`rounded-xl border p-4 text-left transition ${
                  item.slug === selectedSlug
                    ? 'border-brand-blue bg-brand-blue/10'
                    : 'border-brand-line bg-black/30 hover:border-brand-blue/60'
                }`}
              >
                <p className="font-semibold text-brand-white">{item.label}</p>
                <p className="mt-1 text-xs text-brand-muted">{item.description}</p>
                {item.dependencies.length > 0 ? (
                  <p className="mt-2 text-xs text-amber-200">
                    Requiere haber cargado antes:{' '}
                    {item.dependencies
                      .map((slug) => catalog.find((other) => other.slug === slug)?.label || slug)
                      .join(', ')}
                  </p>
                ) : null}
              </button>
            ))}
          </div>
        )}
      </section>

      {/* Paso 2: guía dinámica + plantilla + archivo */}
      {entity ? (
        <section className="card-surface space-y-4 p-5">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-brand-muted">
            2 · Prepara tu archivo de {entity.label.toLowerCase()}
          </h2>

          {dependencyLabels.length > 0 ? (
            <p className="rounded-lg border border-amber-400/40 bg-amber-400/10 px-3 py-2 text-sm text-amber-200">
              Antes de importar {entity.label.toLowerCase()}, asegúrate de haber cargado: {dependencyLabels.join(', ')}.
            </p>
          ) : null}

          <ul className="list-disc space-y-1 pl-5 text-sm text-brand-muted">
            {entity.instructions.map((text, index) => (
              <li key={index}>{text}</li>
            ))}
          </ul>

          <div className="overflow-x-auto">
            <table className="w-full min-w-[520px] text-left text-sm">
              <thead>
                <tr className="border-b border-brand-line text-xs uppercase tracking-wide text-brand-muted">
                  <th className="py-2 pr-3">Columna</th>
                  <th className="py-2 pr-3">Obligatoria</th>
                  <th className="py-2 pr-3">Ejemplo</th>
                  <th className="py-2">Detalle</th>
                </tr>
              </thead>
              <tbody>
                {entity.fields.map((field) => (
                  <tr key={field.attr} className="border-b border-brand-line/40">
                    <td className="py-2 pr-3 font-semibold text-brand-white">{field.label}</td>
                    <td className="py-2 pr-3">{field.required ? 'Sí' : 'No'}</td>
                    <td className="py-2 pr-3 text-brand-muted">{field.example}</td>
                    <td className="py-2 text-brand-muted">
                      {field.help_text}
                      {field.choices ? ` Opciones: ${field.choices.join(' / ')}.` : ''}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
            <button
              type="button"
              onClick={downloadTemplate}
              disabled={downloading}
              className="rounded-xl border border-brand-blue px-4 py-2 text-sm font-semibold text-brand-blue transition hover:bg-brand-blue/10 disabled:opacity-60"
            >
              {downloading ? 'Descargando…' : 'Descargar plantilla base'}
            </button>
            <label className="flex-1">
              <span className="sr-only">Archivo Excel</span>
              <input
                ref={fileInputRef}
                type="file"
                accept=".xlsx"
                onChange={onFileChange}
                className="w-full cursor-pointer rounded-xl border border-brand-line bg-black/30 px-3 py-2 text-sm text-brand-muted file:mr-3 file:rounded-lg file:border-0 file:bg-brand-blue file:px-3 file:py-1.5 file:text-sm file:font-semibold file:text-white"
              />
            </label>
            <button
              type="button"
              onClick={runValidate}
              disabled={!file || validating}
              className="rounded-xl bg-brand-blue px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
            >
              {validating ? 'Validando…' : 'Validar archivo'}
            </button>
          </div>
        </section>
      ) : null}

      {error ? (
        <p className="rounded-lg border border-brand-red/50 bg-brand-red/10 px-3 py-2 text-sm text-red-200">{error}</p>
      ) : null}

      {commitResult ? (
        <section className="card-surface space-y-2 p-5">
          <p className="rounded-lg border border-success-line bg-success-soft px-3 py-2 text-sm text-success">
            Importación completada: se crearon {commitResult.created} registros
            {commitResult.skipped_duplicates > 0
              ? ` y se omitieron ${commitResult.skipped_duplicates} que ya existían o venían repetidos`
              : ''}
            .
          </p>
        </section>
      ) : null}

      {/* Paso 3: preview y confirmación */}
      {(validation || commitErrorRows) && entity ? (
        <section className="card-surface space-y-4 p-5">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-brand-muted">3 · Revisa y confirma</h2>

          {validation ? (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <SummaryCard
                label="Filas en el archivo"
                value={validation.summary.total_rows}
                tone="border-brand-line bg-black/30 text-brand-white"
              />
              <SummaryCard
                label="Se crearán"
                value={validation.summary.will_create}
                tone="border-success-line bg-success-soft text-success"
              />
              <SummaryCard
                label="Se omitirán (ya existen o repetidas)"
                value={validation.summary.duplicates_in_file + validation.summary.duplicates_in_db}
                tone="border-amber-400/40 bg-amber-400/10 text-amber-200"
              />
              <SummaryCard
                label="Filas con errores"
                value={validation.summary.errors}
                tone="border-brand-red/50 bg-brand-red/10 text-red-200"
              />
            </div>
          ) : null}

          {validation && !validation.can_commit ? (
            <p className="rounded-lg border border-brand-red/50 bg-brand-red/10 px-3 py-2 text-sm text-red-200">
              Hay filas con errores: corrígelas en tu archivo Excel y vuelve a validarlo.
              No se importará nada hasta que todas las filas estén correctas.
            </p>
          ) : null}

          <div className="flex items-center justify-between gap-3">
            <label className="flex items-center gap-2 text-sm text-brand-muted">
              <input
                type="checkbox"
                checked={onlyErrors}
                onChange={(event) => setOnlyErrors(event.target.checked)}
                className="h-4 w-4 rounded border-brand-line bg-black/30"
              />
              <span>Mostrar solo filas con errores</span>
            </label>
            {validation ? (
              <button
                type="button"
                onClick={() => setConfirmOpen(true)}
                disabled={!validation.can_commit || committing || validation.summary.will_create === 0}
                className="rounded-xl bg-brand-blue px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
              >
                {committing ? 'Importando…' : 'Confirmar importación'}
              </button>
            ) : null}
          </div>

          <DataTable
            columns={previewColumns}
            data={previewRows}
            rowIdKey="row"
            defaultSort={{ key: 'row', direction: 'asc' }}
            maxBodyHeight="28rem"
          />
        </section>
      ) : null}

      <ConfirmDialog
        open={confirmOpen}
        title="Confirmar importación"
        description={`Se crearán ${validation?.summary?.will_create || 0} registros de ${entity?.label?.toLowerCase() || ''} en tu organización. Esta acción no se puede deshacer.`}
        confirmLabel="Importar"
        onCancel={() => setConfirmOpen(false)}
        onConfirm={runCommit}
      />
    </div>
  )
}
