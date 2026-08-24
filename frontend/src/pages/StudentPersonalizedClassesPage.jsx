import { useCallback, useEffect, useState } from 'react'
import { personalizedClassesApi } from '../api/client'
import DashboardHeader from '../components/DashboardHeader'
import PersonalizedClassesTable from '../components/PersonalizedClassesTable'
import { firstApiError } from '../utils/format'

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

export default function StudentPersonalizedClassesPage() {
  const [listData, setListData] = useState(emptyList)
  const [search, setSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

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
      setError(firstApiError(apiError?.response?.data, 'No se pudieron cargar tus clases personalizadas.'))
    } finally {
      setLoading(false)
    }
  }, [debouncedSearch, page, pageSize, statusFilter])

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

  return (
    <div className="space-y-6">
      <DashboardHeader
        title="Mis clases personalizadas"
        subtitle="Busca, filtra y revisa tus sesiones privadas en curso y dictadas."
      />

      {error ? <p className="rounded-lg border border-brand-red/50 bg-brand-red/10 px-3 py-2 text-sm text-red-200">{error}</p> : null}

      <PersonalizedClassesTable
        items={listData.results}
        loading={loading}
        search={search}
        status={statusFilter}
        pagination={listData}
        showStudent={false}
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
      />
    </div>
  )
}
