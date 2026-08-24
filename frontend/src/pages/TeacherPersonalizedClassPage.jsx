import { useCallback, useEffect, useMemo, useState } from 'react'
import QRCode from 'qrcode'
import { personalizedClassesApi } from '../api/client'
import DashboardHeader from '../components/DashboardHeader'
import FormModal from '../components/FormModal'
import PersonalizedClassesTable from '../components/PersonalizedClassesTable'
import { firstApiError } from '../utils/format'

function formatSeconds(value) {
  const seconds = Math.max(0, Number(value || 0))
  const minutes = Math.floor(seconds / 60)
  const rest = seconds % 60
  if (minutes > 0) return `${minutes}m ${rest}s`
  return `${rest}s`
}

const emptyList = { count: 0, page: 1, page_size: 10, total_pages: 1, results: [] }

function normalizeList(data) {
  if (Array.isArray(data)) {
    return { ...emptyList, count: data.length, results: data }
  }
  return {
    count: Number(data?.count || 0),
    page: Number(data?.page || 1),
    page_size: Number(data?.page_size || 10),
    total_pages: Number(data?.total_pages || 1),
    results: Array.isArray(data?.results) ? data.results : [],
  }
}

export default function TeacherPersonalizedClassPage() {
  const [listData, setListData] = useState(emptyList)
  const [search, setSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [qrData, setQrData] = useState(null)
  const [qrImage, setQrImage] = useState('')
  const [secondsLeft, setSecondsLeft] = useState(0)
  const [loading, setLoading] = useState(true)
  const [starting, setStarting] = useState(false)
  const [finishingId, setFinishingId] = useState(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [modalOpen, setModalOpen] = useState(false)

  const loadSessions = useCallback(async () => {
    setLoading(true)
    try {
      const params = { page, page_size: pageSize }
      if (debouncedSearch.trim()) params.search = debouncedSearch.trim()
      if (statusFilter !== 'all') params.status = statusFilter
      const data = await personalizedClassesApi.list(params)
      setListData(normalizeList(data))
      setError('')
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudieron cargar las clases personalizadas.'))
    } finally {
      setLoading(false)
    }
  }, [debouncedSearch, page, pageSize, statusFilter])

  const startClass = async () => {
    setStarting(true)
    setError('')
    setNotice('')
    try {
      const data = await personalizedClassesApi.createQr()
      const image = await QRCode.toDataURL(data.check_in_url, {
        margin: 1,
        width: 360,
        color: { dark: '#05070d', light: '#ffffff' },
      })
      setQrData(data)
      setQrImage(image)
      setSecondsLeft(Number(data.expires_in_seconds || 0))
      setModalOpen(true)
      setNotice('QR listo. La clase se creara solo si el alumno lo escanea.')
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudo comenzar la clase personalizada.'))
      setQrData(null)
      setQrImage('')
      setSecondsLeft(0)
    } finally {
      setStarting(false)
    }
  }

  const finishClass = async (sessionId) => {
    setFinishingId(sessionId)
    setError('')
    setNotice('')
    try {
      await personalizedClassesApi.finish(sessionId)
      setNotice('Clase personalizada finalizada.')
      await loadSessions()
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudo finalizar la clase personalizada.'))
    } finally {
      setFinishingId(null)
    }
  }

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedSearch(search)
      setPage(1)
    }, 300)
    return () => window.clearTimeout(timer)
  }, [search])

  useEffect(() => {
    loadSessions()
  }, [loadSessions])

  useEffect(() => {
    const timer = window.setInterval(() => {
      setSecondsLeft((prev) => Math.max(0, prev - 1))
    }, 1000)
    return () => window.clearInterval(timer)
  }, [])

  useEffect(() => {
    if (!modalOpen) return undefined
    const poll = window.setInterval(loadSessions, 5000)
    return () => window.clearInterval(poll)
  }, [loadSessions, modalOpen])

  const hasActiveQr = Boolean(qrData?.check_in_url && secondsLeft > 0)
  const subtitle = useMemo(
    () => 'Busca, filtra y pagina sesiones privadas. Los QR no usados no se guardan como clases.',
    [],
  )

  return (
    <div className="space-y-6">
      <DashboardHeader
        title="Clases personalizadas"
        subtitle={subtitle}
        extra={(
          <button
            type="button"
            onClick={startClass}
            disabled={starting}
            className="inline-flex min-h-11 items-center justify-center rounded-lg bg-brand-orange px-4 py-2 text-sm font-semibold text-brand-black transition hover:bg-amber-300 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {starting ? 'Comenzando...' : 'Comenzar clase'}
          </button>
        )}
      />

      {error ? <p className="rounded-lg border border-brand-red/50 bg-brand-red/10 px-3 py-2 text-sm text-red-200">{error}</p> : null}
      {notice ? <p className="rounded-lg border border-brand-blue/40 bg-brand-blue/10 px-3 py-2 text-sm text-brand-white">{notice}</p> : null}

      <PersonalizedClassesTable
        items={listData.results}
        loading={loading}
        search={search}
        status={statusFilter}
        pagination={listData}
        showStudent
        showTeacher
        onSearchChange={setSearch}
        onStatusChange={(value) => {
          setStatusFilter(value)
          setPage(1)
        }}
        onPageChange={setPage}
        onPageSizeChange={(value) => {
          setPageSize(value)
          setPage(1)
        }}
        onFinish={finishClass}
        finishingId={finishingId}
      />

      <FormModal open={modalOpen} title="QR de clase personalizada" onClose={() => setModalOpen(false)}>
        <div className="space-y-4 text-center">
          <div className="mx-auto flex aspect-square w-full max-w-sm items-center justify-center rounded-xl border border-brand-line bg-white p-4">
            {qrImage ? (
              <img src={qrImage} alt="QR de clase personalizada" className="h-full w-full object-contain" />
            ) : (
              <span className="px-4 text-sm font-medium text-brand-black">Generando QR...</span>
            )}
          </div>
          <span className={`inline-flex rounded-full border px-3 py-1 text-sm font-semibold ${hasActiveQr ? 'border-emerald-500/40 text-emerald-200' : 'border-brand-red/40 text-red-200'}`}>
            {hasActiveQr ? `Vence en ${formatSeconds(secondsLeft)}` : 'QR vencido'}
          </span>
          <p className="text-sm text-brand-muted">
            Si nadie lo escanea, no se guarda ninguna clase. Si el alumno confirma, aparecera en la tabla como En curso.
          </p>
        </div>
      </FormModal>
    </div>
  )
}
