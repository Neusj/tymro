import { useCallback, useEffect, useState } from 'react'
import { getPlans, individualConsultationsApi, usersApi } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import DashboardHeader from '../components/DashboardHeader'
import QrCameraScanner from '../components/QrCameraScanner'
import { firstApiError } from '../utils/format'

const name = (user) => `${user?.first_name || ''} ${user?.last_name || ''}`.trim() || user?.email || user?.username

export default function IndividualConsultationsPage() {
  const { user } = useAuth()
  const admin = user?.role === 'gym_admin'
  const [items, setItems] = useState([]); const [users, setUsers] = useState([]); const [products, setProducts] = useState([])
  const [error, setError] = useState(''); const [qr, setQr] = useState(''); const [scanning, setScanning] = useState(false); const [form, setForm] = useState({ student_id: '', professional_id: '', product_id: '', agreed_at: '' })
  const load = useCallback(async () => {
    try {
      const list = await individualConsultationsApi.list(); setItems(Array.isArray(list) ? list : [])
      if (admin) {
        const [people, plans] = await Promise.all([usersApi.list(), getPlans()])
        setUsers(Array.isArray(people) ? people : people?.results || []); setProducts((Array.isArray(plans) ? plans : plans?.results || []).filter((plan) => plan.plan_type === 'consultation'))
      }
    } catch (e) { setError(firstApiError(e?.response?.data, 'No se pudieron cargar las consultas.')) }
  }, [admin])
  useEffect(() => { load() }, [load])
  const assign = async (e) => { e.preventDefault(); try { await individualConsultationsApi.create({ ...form, agreed_at: form.agreed_at || null }); setForm({ student_id: '', professional_id: '', product_id: '', agreed_at: '' }); await load() } catch (e) { setError(firstApiError(e?.response?.data, 'No se pudo asignar la consulta.')) } }
  const start = async (id) => { try { await individualConsultationsApi.start(id, qr); setQr(''); await load() } catch (e) { setError(firstApiError(e?.response?.data, 'No se pudo iniciar la consulta.')) } }
  const finish = async (id) => { try { await individualConsultationsApi.finish(id); await load() } catch (e) { setError(firstApiError(e?.response?.data, 'No se pudo finalizar la consulta.')) } }
  return <div className="space-y-6"><DashboardHeader title="Consultas individuales" subtitle="Unidades sin horario inicial; coordina y registra su realización." />
    {error && <p className="rounded-lg border border-brand-red/50 bg-brand-red/10 p-3 text-sm text-red-200">{error}</p>}
    {admin && <form onSubmit={assign} className="card-surface grid gap-3 p-5 md:grid-cols-4"><select required value={form.student_id} onChange={e => setForm({ ...form, student_id: e.target.value })}><option value="">Alumno</option>{users.filter(x => x.role === 'student').map(x => <option key={x.id} value={x.id}>{name(x)}</option>)}</select><select required value={form.professional_id} onChange={e => setForm({ ...form, professional_id: e.target.value })}><option value="">Profesional</option>{users.filter(x => ['teacher', 'gym_admin'].includes(x.role)).map(x => <option key={x.id} value={x.id}>{name(x)}</option>)}</select><select required value={form.product_id} onChange={e => setForm({ ...form, product_id: e.target.value })}><option value="">Producto</option>{products.map(x => <option key={x.id} value={x.id}>{x.name}</option>)}</select><input type="datetime-local" value={form.agreed_at} onChange={e => setForm({ ...form, agreed_at: e.target.value })} /><button className="rounded-xl bg-brand-blue px-4 py-2 font-semibold text-white">Asignar consulta</button></form>}
    {(user?.role === 'teacher' || admin) && <div className="card-surface space-y-3 p-4"><div className="flex gap-2"><input className="flex-1" placeholder="Escanea o pega el QR fijo del alumno" value={qr} onChange={e => setQr(e.target.value)} /><button type="button" onClick={() => setScanning(!scanning)} className="rounded-lg border border-brand-line px-3 text-sm">{scanning ? 'Cerrar cámara' : 'Escanear QR'}</button></div><p className="text-xs text-brand-muted">El QR se valida al iniciar la consulta seleccionada.</p>{scanning && <QrCameraScanner paused={false} onDecode={(token) => { setQr(token); setScanning(false) }} />}</div>}
    <section className="space-y-3">{items.map(item => <article key={item.id} className="card-surface flex flex-wrap items-center justify-between gap-3 p-4"><div><h2 className="font-semibold text-brand-white">{item.product_name}</h2><p className="text-sm text-brand-muted">{item.student_name} · {item.professional_name} · {item.status}</p><p className="text-xs text-brand-muted">Vence: {new Date(item.expires_at).toLocaleString()} {item.agreed_at ? `· Acordada: ${new Date(item.agreed_at).toLocaleString()}` : ''}</p></div>{item.can_manage && <div className="flex gap-2">{['available', 'scheduled'].includes(item.status) && <button onClick={() => start(item.id)} disabled={!qr} className="rounded-lg bg-brand-blue px-3 py-2 text-sm font-semibold text-white disabled:opacity-50">Iniciar</button>}{item.status === 'started' && <button onClick={() => finish(item.id)} className="rounded-lg bg-brand-orange px-3 py-2 text-sm font-semibold text-black">Finalizar consulta</button>}</div>}</article>)}</section>
  </div>
}
