import { useEffect, useState } from 'react'
import { branchesApi, disciplinesApi, downloadReportFile, reportsApi } from '../api/client'
import DashboardHeader from '../components/DashboardHeader'
import StatCard from '../components/StatCard'
import ReportFilterBar from '../components/reports/ReportFilterBar'
import TimeSeriesChart from '../components/charts/TimeSeriesChart'
import HorizontalBarChart from '../components/charts/HorizontalBarChart'
import { firstApiError } from '../utils/format'
import { buildReportParams, defaultReportPeriod, formatBucketLabel } from '../utils/reportFilters'

const MAX_BREAKDOWN_ROWS = 10

const formatPct = (value) => `${Math.round(Number(value) || 0)}%`

export default function GymAdminOccupancyReportPage() {
  const [dateFrom, setDateFrom] = useState(() => defaultReportPeriod().dateFrom)
  const [dateTo, setDateTo] = useState(() => defaultReportPeriod().dateTo)
  const [branchId, setBranchId] = useState('')
  const [disciplineId, setDisciplineId] = useState('')
  const [branches, setBranches] = useState([])
  const [disciplines, setDisciplines] = useState([])

  const [report, setReport] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [exporting, setExporting] = useState('')

  const buildParams = () =>
    buildReportParams({ dateFrom, dateTo, branchId, extra: { discipline_id: disciplineId } })

  useEffect(() => {
    let active = true
    Promise.all([branchesApi.list(), disciplinesApi.list()])
      .then(([branchData, disciplineData]) => {
        if (!active) return
        setBranches(Array.isArray(branchData) ? branchData : [])
        setDisciplines((Array.isArray(disciplineData) ? disciplineData : []).filter((item) => item.is_active !== false))
      })
      .catch(() => {
        if (active) {
          setBranches([])
          setDisciplines([])
        }
      })
    return () => {
      active = false
    }
  }, [])

  useEffect(() => {
    let active = true
    const load = async () => {
      setLoading(true)
      setError('')
      try {
        const data = await reportsApi.occupancy(buildParams())
        if (active) setReport(data)
      } catch (apiError) {
        if (active) {
          setError(firstApiError(apiError?.response?.data, 'No se pudo cargar el reporte de ocupación.'))
          setReport(null)
        }
      } finally {
        if (active) setLoading(false)
      }
    }
    load()
    return () => {
      active = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dateFrom, dateTo, branchId, disciplineId])

  const handleExport = async (format) => {
    setExporting(format)
    setError('')
    try {
      const response = await reportsApi.exportOccupancy(buildParams(), format)
      downloadReportFile(response, `ocupacion_${dateFrom}_${dateTo}.${format === 'xlsx' ? 'xlsx' : 'csv'}`)
    } catch {
      setError('No se pudo exportar el reporte.')
    } finally {
      setExporting('')
    }
  }

  const totals = report?.totals || {
    classes: 0,
    capacity: 0,
    enrolled: 0,
    occupancy_rate: 0,
    full_classes: 0,
    empty_classes: 0,
    pruned_classes: 0,
  }
  const byDiscipline = Array.isArray(report?.by_discipline) ? report.by_discipline : []
  const byHour = Array.isArray(report?.by_hour) ? report.by_hour : []
  const series = Array.isArray(report?.series) ? report.series : []
  const filters = report?.filters || {}
  const prunedClasses = Number(totals.pruned_classes) || 0

  const disciplineItems = [...byDiscipline]
    .sort((a, b) => (Number(b.occupancy_rate) || 0) - (Number(a.occupancy_rate) || 0))
    .slice(0, MAX_BREAKDOWN_ROWS)
    .map((row) => ({
      key: row.discipline_id ?? row.discipline_name,
      label: row.discipline_name || 'Sin disciplina',
      value: Number(row.occupancy_rate) || 0,
      hint: `${row.enrolled}/${row.capacity} cupos · ${row.classes} clases`,
    }))

  const hourItems = [...byHour]
    .sort((a, b) => (Number(b.occupancy_rate) || 0) - (Number(a.occupancy_rate) || 0))
    .slice(0, MAX_BREAKDOWN_ROWS)
    .map((row) => ({
      key: row.hour,
      label: row.label || `${row.hour}:00`,
      value: Number(row.occupancy_rate) || 0,
      hint: `${row.enrolled}/${row.capacity} cupos · ${row.classes} clases`,
    }))

  return (
    <div className="space-y-5">
      <DashboardHeader
        title="Ocupación"
        subtitle="Qué tan llenas van las clases del período: % de ocupación, horarios que se llenan y horarios que nadie toma."
        back={{ to: '/gym-admin/dashboard', label: 'Dashboard' }}
      />

      {error ? (
        <p className="rounded-lg border border-danger-line bg-danger-soft px-3 py-2 text-sm text-red-200">{error}</p>
      ) : null}

      <ReportFilterBar
        dateFrom={dateFrom}
        dateTo={dateTo}
        onDateFromChange={setDateFrom}
        onDateToChange={setDateTo}
        branches={branches}
        branchId={branchId}
        onBranchChange={setBranchId}
        extraFilter={{
          label: 'Disciplina',
          value: disciplineId,
          onChange: setDisciplineId,
          options: disciplines.map((item) => ({ value: item.id, label: item.name })),
          allLabel: 'Todas las disciplinas',
        }}
        onExport={handleExport}
        exporting={exporting}
        exportDisabled={loading || Boolean(exporting)}
      />

      <p className="text-xs text-brand-muted">
        {report?.period?.date_from || dateFrom} al {report?.period?.date_to || dateTo} ·{' '}
        {filters.branch_name || 'Todas las sucursales'} · {filters.discipline_name || 'Todas las disciplinas'}
      </p>

      {prunedClasses > 0 ? (
        <p className="rounded-lg border border-info-line bg-info-soft px-3 py-2 text-sm text-blue-200">
          Incluye {prunedClasses} clases vacías ya archivadas (podadas por la ventana rodante). Es el dato de
          marketing: horarios que programaste y nadie tomó.
        </p>
      ) : null}

      <section className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <StatCard
          title="Ocupación del período"
          value={formatPct(totals.occupancy_rate)}
          accent="orange"
          hint={`${totals.enrolled}/${totals.capacity} cupos · ${totals.classes} clases`}
        />
        <StatCard title="Clases llenas" value={totals.full_classes} accent="success" hint="100% de ocupación" />
        <StatCard title="Clases vacías" value={totals.empty_classes} accent="red" hint="0% de ocupación" />
      </section>

      <section className="card-surface space-y-3 p-4 sm:p-5">
        <h2 className="text-sm font-semibold text-brand-white">Evolución de la ocupación</h2>
        <TimeSeriesChart
          data={series}
          series={[{ key: 'occupancy_rate', label: 'Ocupación', tone: 'orange' }]}
          formatValue={formatPct}
          formatBucket={formatBucketLabel}
          yDomain={[0, 100]}
          title="Evolución de ocupación"
        />
      </section>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <section className="card-surface space-y-3 p-4 sm:p-5">
          <h2 className="text-sm font-semibold text-brand-white">Por disciplina</h2>
          <HorizontalBarChart items={disciplineItems} formatValue={formatPct} emptyLabel="Sin clases en el período." />
        </section>
        <section className="card-surface space-y-3 p-4 sm:p-5">
          <h2 className="text-sm font-semibold text-brand-white">Por horario</h2>
          <HorizontalBarChart items={hourItems} formatValue={formatPct} emptyLabel="Sin clases en el período." />
        </section>
      </div>
    </div>
  )
}
