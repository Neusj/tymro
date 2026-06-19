// Aprovisionamiento de datos del PROFESOR vía API de gym_admin (token capturado en
// global-setup → fx.tokens.gymAdmin). El profesor NO puede crear clases ni planes,
// así que un gym_admin prepara estado DESECHABLE para los specs: clases futuras de
// teacher1, alumnos con plan ilimitado, reglas de pago. Todo es idempotente por
// nombre/username; las clases las borra el seed en la próxima corrida.
import { apiContext, creds } from './data.js'

const norm = (d) => (Array.isArray(d) ? d : d?.results || [])
// start_date 2 días atrás: el backend evalúa la vigencia del plan con la fecha LOCAL
// del servidor (America/Santiago, UTC-4). Un start_date = "hoy UTC" puede caer en el
// futuro del servidor (queda "Por iniciar" → sin plan activo). Restar 2 días lo evita.
const planStartDate = () => new Date(Date.now() - 2 * 86_400_000).toISOString().slice(0, 10)

const STUDENT_PASSWORD = 'e2eprof123'
const UNLIMITED_PLAN_NAME = 'E2E Ilimitado (profesor)'

// Resuelve los FKs necesarios para crear una clase (branch/class_type/discipline),
// creándolos si la org no tuviera ninguno. teacherUser viene de teacherUserFromStorage().
export async function getRefs(ctx, teacherUser) {
  const [ctList, discList] = await Promise.all([
    ctx.get('class-types/').then((r) => r.json()).then(norm),
    ctx.get('disciplines/').then((r) => r.json()).then(norm),
  ])

  let classTypeId = ctList.find((c) => c.is_active !== false)?.id || ctList[0]?.id
  if (!classTypeId) {
    classTypeId = (await (await ctx.post('class-types/', { data: { name: 'E2E Tipo' } })).json()).id
  }
  let disciplineId = discList.find((d) => d.is_active !== false)?.id || discList[0]?.id
  if (!disciplineId) {
    disciplineId = (await (await ctx.post('disciplines/', { data: { name: 'E2E Disciplina' } })).json()).id
  }

  let branchId = teacherUser?.branch
  if (!branchId) {
    const branches = norm(await (await ctx.get('branches/')).json())
    branchId = branches[0]?.id
    if (!branchId) {
      branchId = (await (await ctx.post('branches/', { data: { name: 'E2E Sede' } })).json()).id
    }
  }

  // Base horaria a prueba de solapes: las clases desechables se colocan DESPUÉS de la
  // última clase que ya tiene el profesor (seed o specs previas). El backend rechaza
  // clases del mismo profesor que solapen en horario; arrancar tras todo lo existente
  // lo evita de raíz, sin depender de offsets fijos contra una near-future "minada".
  const all = norm(await (await ctx.get('classes/')).json())
  let nextStartMs = Date.now() + 90 * 60_000 // mínimo: +90 min
  for (const c of all) {
    if (c.teacher !== teacherUser.id) continue
    const end = Date.parse(c.end_datetime)
    if (end && end + 60 * 60_000 > nextStartMs) nextStartMs = end + 60 * 60_000 // 1h de colchón
  }

  return { teacherId: teacherUser.id, branchId, classTypeId, disciplineId, nextStartMs }
}

// Crea una clase asignada al profesor en la siguiente ventana libre (refs.nextStartMs),
// avanzando el cursor para que múltiples clases del mismo spec no solapen entre sí.
export async function createFutureClass(ctx, refs, { name, durationMin = 40, capacity = 20 } = {}) {
  const start = new Date(refs.nextStartMs)
  const end = new Date(refs.nextStartMs + durationMin * 60_000)
  refs.nextStartMs = end.getTime() + 60 * 60_000 // siguiente clase 1h después del fin
  const res = await ctx.post('classes/', {
    data: {
      name,
      branch: refs.branchId,
      teacher: refs.teacherId,
      class_type: refs.classTypeId,
      discipline: refs.disciplineId,
      start_datetime: start.toISOString(),
      end_datetime: end.toISOString(),
      capacity,
    },
  })
  if (!res.ok()) throw new Error(`createFutureClass("${name}") ${res.status()}: ${await res.text()}`)
  return res.json()
}

async function ensureUnlimitedPlan(ctx) {
  const plans = norm(await (await ctx.get('plans/')).json())
  const found = plans.find((p) => p.name === UNLIMITED_PLAN_NAME)
  if (found) return found.id
  const res = await ctx.post('plans/', {
    data: {
      name: UNLIMITED_PLAN_NAME,
      plan_type: 'monthly',
      total_classes: 1,
      unlimited_classes: true,
      duration_days: 365,
      price: 30000,
    },
  })
  if (!res.ok()) throw new Error(`ensureUnlimitedPlan ${res.status()}: ${await res.text()}`)
  return (await res.json()).id
}

// Alumnos desechables con plan ILIMITADO activo (no consumen saldo contable, no
// interfieren con la suite de alumno). Idempotente por username.
export async function ensureUnlimitedStudents(ctx, refs, count = 2) {
  const planId = await ensureUnlimitedPlan(ctx)
  const allUsers = norm(await (await ctx.get('users/')).json())
  const students = []
  for (let i = 1; i <= count; i += 1) {
    const username = `e2e_tprof_s${i}`
    let user = allUsers.find((u) => u.username === username)
    if (!user) {
      const res = await ctx.post('users/', {
        data: {
          username,
          password: STUDENT_PASSWORD,
          role: 'student',
          first_name: `AlumnoE2E${i}`,
          last_name: 'Profesor',
          branch: refs.branchId,
        },
      })
      if (!res.ok()) throw new Error(`ensureStudent ${username} ${res.status()}: ${await res.text()}`)
      user = await res.json()
    }
    const assign = await ctx.post('plans/assign/', { data: { user: user.id, plan: planId, start_date: planStartDate() } })
    if (!assign.ok()) throw new Error(`assign plan ilimitado a ${username} ${assign.status()}: ${await assign.text()}`)
    students.push({ id: user.id, username, firstName: `AlumnoE2E${i}` })
  }
  return students
}

// Alumno desechable con plan de SALDO (no ilimitado) para observar devolución de saldo.
export async function ensureBalanceStudent(ctx, refs, { total = 10, username = 'e2e_tprof_bal' } = {}) {
  const allUsers = norm(await (await ctx.get('users/')).json())
  let user = allUsers.find((u) => u.username === username)
  if (!user) {
    const res = await ctx.post('users/', {
      data: { username, password: STUDENT_PASSWORD, role: 'student', first_name: 'AlumnoSaldo', last_name: 'E2E', branch: refs.branchId },
    })
    if (!res.ok()) throw new Error(`ensureBalanceStudent ${res.status()}: ${await res.text()}`)
    user = await res.json()
  }
  const plans = norm(await (await ctx.get('plans/')).json())
  const planName = 'E2E Saldo 10 (profesor)'
  let planId = plans.find((p) => p.name === planName)?.id
  if (!planId) {
    const res = await ctx.post('plans/', {
      data: { name: planName, plan_type: 'pack', total_classes: total, duration_days: 365, price: 30000 },
    })
    if (!res.ok()) throw new Error(`crear plan saldo ${res.status()}: ${await res.text()}`)
    planId = (await res.json()).id
  }
  const assign = await ctx.post('plans/assign/', { data: { user: user.id, plan: planId, start_date: planStartDate() } })
  if (!assign.ok()) throw new Error(`assign plan saldo a ${username} ${assign.status()}: ${await assign.text()}`)
  return { id: user.id, username, password: STUDENT_PASSWORD }
}

export async function enrollActive(ctx, classId, studentId) {
  const res = await ctx.post('enrollments/', { data: { gym_class: classId, student: studentId, status: 'active' } })
  if (!res.ok()) throw new Error(`enrollActive ${res.status()}: ${await res.text()}`)
  return res.json()
}

// Marca asistencia (default 'present') a TODOS los inscritos activos (el backend exige
// exactamente ese conjunto). overrides = { [studentId]: 'absent'|'late'|... }.
export async function setAttendance(ctx, classId, overrides = {}) {
  const enrolled = norm(await (await ctx.get(`classes/${classId}/enrolled-students/`)).json())
  const attendances = enrolled.map((s) => ({ student_id: s.student_id, status: overrides[s.student_id] || 'present' }))
  const res = await ctx.post(`classes/${classId}/attendance/`, { data: { attendances } })
  if (!res.ok()) throw new Error(`setAttendance ${res.status()}: ${await res.text()}`)
  return res.json()
}

export async function completeEarly(ctx, classId, comment = 'E2E cierre') {
  const res = await ctx.post(`classes/${classId}/complete-early/`, { data: { comment } })
  if (!res.ok()) throw new Error(`completeEarly ${res.status()}: ${await res.text()}`)
  return res.json()
}

// Desactiva TODAS las reglas de pago activas de la org (el seed no crea ninguna, así
// que solo desactiva las que crearon specs previos) para dejar UNA sola regla efectiva.
export async function deactivateAllRules(ctx) {
  const rules = norm(await (await ctx.get('teacher-payment-rules/')).json())
  for (const r of rules) {
    if (r.is_active) {
      await ctx.patch(`teacher-payment-rules/${r.id}/`, { data: { is_active: false } })
    }
  }
}

// Crea una regla de pago y la asigna al profesor, dejándola como la ÚNICA activa.
export async function setSingleRule(ctx, teacherId, { payment_type = 'fixed_per_class', amount = 5000, extra = {} } = {}) {
  await deactivateAllRules(ctx)
  const res = await ctx.post('teacher-payment-rules/', { data: { payment_type, amount, is_active: true, ...extra } })
  if (!res.ok()) throw new Error(`setSingleRule create ${res.status()}: ${await res.text()}`)
  const rule = await res.json()
  const assign = await ctx.put(`teacher-payment-rules/${rule.id}/assignments/`, { data: { teacher_ids: [teacherId] } })
  if (!assign.ok()) throw new Error(`setSingleRule assign ${res.status()}: ${await assign.text()}`)
  return rule.id
}

// Helper de alto nivel: abre un apiContext de gym_admin desde el token de fixtures.
export async function gymAdminCtx(fx) {
  if (!fx?.tokens?.gymAdmin) throw new Error('Falta fx.tokens.gymAdmin (¿corrió global-setup?).')
  return apiContext(fx.tokens.gymAdmin)
}

export { creds }
