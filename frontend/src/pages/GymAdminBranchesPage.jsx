import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { branchesApi, paymentsApi } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import ConfirmDialog from '../components/ConfirmDialog'
import DashboardHeader from '../components/DashboardHeader'
import DataTable from '../components/ui/DataTable'
import FormModal from '../components/FormModal'
import SectionCard from '../components/SectionCard'
import { canManageAdmin } from '../utils/roles'
import { firstApiError } from '../utils/format'

const initialForm = {
  name: '',
  code: '',
  address: '',
  logo: null,
  primary_color: '',
  secondary_color: '',
}

// Fecha larga es-CL (ej. "5 de julio de 2026, 14:30"), igual que en Ajustes → Pagos.
function formatDateTime(value) {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString('es-CL', {
    day: 'numeric', month: 'long', year: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

// ¿La respuesta de `GET account?branch_id=` corresponde a una fila que existe (o existió)
// para esta sucursal? Sin cuenta propia el backend devuelve el literal
// `{status:'disconnected', provider}` — sin más claves. Si la fila existe (conectada o
// desconectada), el serializer completo siempre trae `provider_user_id` (aunque haya
// quedado vacío tras desconectar). Es la única forma de distinguir "nunca configuró cuenta
// propia" de "la configuró y la desconectó" con la misma respuesta 200/status disconnected.
function accountRowExists(account) {
  return Boolean(account) && Object.prototype.hasOwnProperty.call(account, 'provider_user_id')
}

// Sección "Cuenta de pagos propia" de UNA sucursal: colapsada por defecto, consulta su
// estado (account?branch_id=) recién al abrirse por primera vez — no hay endpoint de
// listado batch, así que precargar todas de una dispararía N requests al entrar a la página.
function BranchPaymentAccountItem({ branch }) {
  const [open, setOpen] = useState(false)
  const [account, setAccount] = useState(null)
  const [loaded, setLoaded] = useState(false)
  const [loading, setLoading] = useState(false)
  const [wantsOwnAccount, setWantsOwnAccount] = useState(false)
  const [connecting, setConnecting] = useState(false)
  const [confirmingDisconnect, setConfirmingDisconnect] = useState(false)
  const [disconnecting, setDisconnecting] = useState(false)
  const [error, setError] = useState('')
  const [mainAccountRequired, setMainAccountRequired] = useState(false)
  const [notice, setNotice] = useState('')

  const loadAccount = async () => {
    setLoading(true)
    setError('')
    try {
      const data = await paymentsApi.getAccount({ branchId: branch.id })
      setAccount(data)
      setLoaded(true)
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudo cargar el estado de la cuenta de esta sucursal.'))
    } finally {
      setLoading(false)
    }
  }

  const toggleOpen = () => {
    const next = !open
    setOpen(next)
    if (next && !loaded) {
      loadAccount()
    }
  }

  const connected = account?.status === 'connected'
  const rowExists = accountRowExists(account)

  const handleConnect = async () => {
    setConnecting(true)
    setError('')
    setNotice('')
    setMainAccountRequired(false)
    try {
      const { authorization_url: url } = await paymentsApi.connect({ branchId: branch.id })
      if (!url) throw new Error('sin url')
      // Redirige a MercadoPago para autorizar la cuenta propia de esta sede.
      window.location.assign(url)
    } catch (apiError) {
      setConnecting(false)
      setError(firstApiError(apiError?.response?.data, 'No se pudo iniciar la conexión con MercadoPago.'))
      // 409: la org no tiene la cuenta principal conectada todavía (piso del modelo).
      setMainAccountRequired(apiError?.response?.status === 409)
    }
    // Si el assign tiene éxito no reseteamos connecting: la página se descarga.
  }

  const handleDisconnect = async () => {
    setDisconnecting(true)
    setError('')
    setNotice('')
    try {
      // La respuesta del endpoint ES el estado autoritativo (desconectado): se aplica
      // directo, sin un segundo GET (mismo motivo que en Ajustes → Pagos).
      const data = await paymentsApi.disconnect({ branchId: branch.id })
      setAccount(data)
      setWantsOwnAccount(false)
      setNotice('Desconectaste la cuenta propia de esta sucursal. Sus cobros vuelven a ir a la cuenta principal del gimnasio.')
    } catch (apiError) {
      setError(firstApiError(apiError?.response?.data, 'No se pudo desconectar la cuenta de esta sucursal.'))
    } finally {
      setDisconnecting(false)
      setConfirmingDisconnect(false)
    }
  }

  return (
    <div className="rounded-xl border border-brand-line bg-black/20">
      <button
        type="button"
        onClick={toggleOpen}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left"
      >
        <span className="min-w-0">
          <span className="font-display text-sm font-semibold text-brand-white">{branch.name}</span>
          {branch.code ? <span className="ml-2 text-xs text-brand-muted">({branch.code})</span> : null}
        </span>
        <span className="shrink-0 text-xs font-semibold text-brand-blue">
          {open ? 'Ocultar' : 'Cuenta de pagos propia'}
        </span>
      </button>

      {open ? (
        <div className="border-t border-brand-line px-4 py-4">
          {error ? (
            <div className="mb-3 space-y-2">
              <p className="rounded-lg border border-brand-red/50 bg-brand-red/10 px-3 py-2 text-sm text-red-200">{error}</p>
              {mainAccountRequired ? (
                <Link to="/ajustes/pagos" className="inline-block text-sm font-semibold text-brand-blue underline hover:text-brand-orange">
                  Ir a Ajustes → Pagos para conectar la cuenta principal
                </Link>
              ) : null}
            </div>
          ) : null}
          {notice ? <p className="mb-3 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-200">{notice}</p> : null}

          {loading ? (
            <p className="text-sm text-brand-muted">Cargando estado de la conexión…</p>
          ) : connected ? (
            <div className="space-y-3">
              <p className="text-sm text-brand-muted">
                Esta sucursal cobra sus membresías con su propia cuenta de MercadoPago.
              </p>
              <dl className="grid gap-3 sm:grid-cols-2">
                <div className="rounded-lg border border-brand-line bg-black/25 p-3">
                  <dt className="text-[11px] uppercase tracking-wide text-brand-dim">Cuenta cobradora</dt>
                  <dd className="mt-1 break-all text-sm font-semibold text-brand-white">{account?.provider_user_id || '—'}</dd>
                </div>
                <div className="rounded-lg border border-brand-line bg-black/25 p-3">
                  <dt className="text-[11px] uppercase tracking-wide text-brand-dim">Conectada el</dt>
                  <dd className="mt-1 text-sm font-semibold text-brand-white">{formatDateTime(account?.connected_at)}</dd>
                </div>
              </dl>
              <button
                type="button"
                onClick={() => setConfirmingDisconnect(true)}
                disabled={disconnecting}
                className="rounded-xl border border-brand-red/50 bg-transparent px-4 py-2 text-sm font-semibold text-red-200 transition hover:border-brand-red hover:bg-brand-red/10 disabled:cursor-not-allowed disabled:opacity-60"
              >
                Desconectar
              </button>
            </div>
          ) : rowExists ? (
            <div className="space-y-3">
              <p className="text-sm text-brand-muted">
                La cuenta propia de esta sucursal está desconectada: sus cobros vuelven a ir a la
                cuenta principal del gimnasio hasta que reconectes.
              </p>
              <button
                type="button"
                onClick={handleConnect}
                disabled={connecting}
                className="inline-flex min-h-10 items-center justify-center gap-2 rounded-xl bg-[#00b1ea] px-4 py-2 text-sm font-semibold text-white shadow-soft transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {connecting ? 'Redirigiendo…' : 'Reconectar MercadoPago'}
              </button>
            </div>
          ) : (
            <div className="space-y-3">
              <p className="text-sm text-brand-muted">
                Por defecto, esta sucursal cobra sus membresías con la cuenta principal del gimnasio.
              </p>
              <label className="flex items-center gap-2 text-sm text-brand-white">
                <input
                  type="checkbox"
                  className="h-4 w-4 accent-brand-blue"
                  checked={wantsOwnAccount}
                  onChange={(event) => setWantsOwnAccount(event.target.checked)}
                />
                Usar cuenta propia para esta sucursal
              </label>
              {wantsOwnAccount ? (
                <button
                  type="button"
                  onClick={handleConnect}
                  disabled={connecting}
                  className="inline-flex min-h-10 items-center justify-center gap-2 rounded-xl bg-[#00b1ea] px-4 py-2 text-sm font-semibold text-white shadow-soft transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {connecting ? 'Redirigiendo…' : 'Conectar MercadoPago'}
                </button>
              ) : null}
            </div>
          )}
        </div>
      ) : null}

      <ConfirmDialog
        open={confirmingDisconnect}
        title="Desconectar cuenta de la sucursal"
        description={`${branch.name} dejará de cobrar con su cuenta propia de MercadoPago; sus cobros volverán a la cuenta principal del gimnasio.`}
        confirmLabel="Sí, desconectar"
        loading={disconnecting}
        onConfirm={handleDisconnect}
        onCancel={() => setConfirmingDisconnect(false)}
      />
    </div>
  )
}

export default function GymAdminBranchesPage() {
  const { user } = useAuth()
  const canManage = canManageAdmin(user?.role)
  const [branches, setBranches] = useState([])
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState(null)
  const [form, setForm] = useState(initialForm)
  const [deleting, setDeleting] = useState(null)

  const loadData = async () => {
    const data = await branchesApi.list()
    setBranches(data)
  }

  useEffect(() => {
    loadData()
  }, [])

  const openCreate = () => {
    setEditing(null)
    setForm(initialForm)
    setModalOpen(true)
  }

  const openEdit = (branch) => {
    setEditing(branch)
    setForm({
      name: branch.name || '',
      code: branch.code || '',
      address: branch.address || '',
      logo: null,
      primary_color: branch.primary_color || '',
      secondary_color: branch.secondary_color || '',
    })
    setModalOpen(true)
  }

  const submit = async (event) => {
    event.preventDefault()
    const payload = { ...form }
    if (!payload.logo) {
      delete payload.logo
    }

    if (editing) {
      await branchesApi.update(editing.id, payload, true)
    } else {
      await branchesApi.create(payload, true)
    }
    setModalOpen(false)
    await loadData()
  }

  const removeBranch = async () => {
    if (!deleting) {
      return
    }
    await branchesApi.remove(deleting.id)
    setDeleting(null)
    await loadData()
  }

  const columns = [
    { key: 'name', label: 'Nombre' },
    { key: 'code', label: 'Código' },
    { key: 'address', label: 'Dirección' },
    { key: 'primary_color', label: 'Color primario', render: (row) => row.primary_color || '-' },
    ...(canManage
      ? [
          {
            key: 'actions',
            label: 'Acciones',
            render: (row) => (
              <div className="flex gap-2">
                <button type="button" onClick={() => openEdit(row)} className="rounded border border-brand-line px-2 py-1 text-xs text-brand-muted">
                  Editar
                </button>
                <button type="button" onClick={() => setDeleting(row)} className="rounded border border-brand-red/40 px-2 py-1 text-xs text-red-200">
                  Eliminar
                </button>
              </div>
            ),
          },
        ]
      : []),
  ]

  const activeBranches = branches.filter((branch) => branch.is_active)

  return (
    <div className="space-y-6">
      <DashboardHeader
        title="Gym Admin · Sucursales"
        subtitle="CRUD de sucursales dentro de tu organización."
        extra={
          canManage ? (
            <button type="button" onClick={openCreate} className="rounded-xl bg-brand-orange px-4 py-2 text-sm font-semibold text-white">
              Nueva sucursal
            </button>
          ) : null
        }
      />

      <section className="card-surface p-5">
        <DataTable columns={columns} data={branches} />
      </section>

      {canManage ? (
        <SectionCard
          title="Cuentas de pago por sucursal"
          subtitle="Por defecto todas las sucursales cobran con la cuenta principal de MercadoPago (Ajustes → Pagos). Una sucursal puede conectar su propia cuenta para que sus cobros vayan directo a ella."
        >
          {activeBranches.length === 0 ? (
            <p className="text-sm text-brand-muted">No hay sucursales activas.</p>
          ) : (
            <div className="space-y-2">
              {activeBranches.map((branch) => (
                <BranchPaymentAccountItem key={branch.id} branch={branch} />
              ))}
            </div>
          )}
        </SectionCard>
      ) : null}

      <FormModal open={modalOpen} onClose={() => setModalOpen(false)} title={editing ? 'Editar sucursal' : 'Nueva sucursal'}>
        <form onSubmit={submit} className="grid gap-3">
          <label className="space-y-1 text-sm">
            <span>Nombre</span>
            <input
              required
              value={form.name}
              onChange={(event) => setForm((prev) => ({ ...prev, name: event.target.value }))}
              className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
            />
          </label>
          <label className="space-y-1 text-sm">
            <span>Código</span>
            <input value={form.code} onChange={(event) => setForm((prev) => ({ ...prev, code: event.target.value }))} className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2" />
          </label>
          <label className="space-y-1 text-sm">
            <span>Dirección</span>
            <input
              value={form.address}
              onChange={(event) => setForm((prev) => ({ ...prev, address: event.target.value }))}
              className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
            />
          </label>
          <label className="space-y-1 text-sm">
            <span>Color primario</span>
            <input
              placeholder="#dc2626"
              value={form.primary_color}
              onChange={(event) => setForm((prev) => ({ ...prev, primary_color: event.target.value }))}
              className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
            />
          </label>
          <label className="space-y-1 text-sm">
            <span>Color secundario</span>
            <input
              placeholder="#2563eb"
              value={form.secondary_color}
              onChange={(event) => setForm((prev) => ({ ...prev, secondary_color: event.target.value }))}
              className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
            />
          </label>
          <label className="space-y-1 text-sm">
            <span>Logo</span>
            <input
              type="file"
              accept="image/*"
              onChange={(event) => setForm((prev) => ({ ...prev, logo: event.target.files?.[0] || null }))}
              className="w-full rounded-lg border border-brand-line bg-black/30 px-3 py-2"
            />
          </label>
          <div className="flex justify-end">
            <button type="submit" className="rounded-xl bg-brand-blue px-4 py-2 text-sm font-semibold text-white">
              Guardar
            </button>
          </div>
        </form>
      </FormModal>

      <ConfirmDialog
        open={Boolean(deleting)}
        title="Eliminar sucursal"
        description={`Se eliminará ${deleting?.name || 'esta sucursal'}.`}
        confirmLabel="Eliminar"
        onCancel={() => setDeleting(null)}
        onConfirm={removeBranch}
      />
    </div>
  )
}
