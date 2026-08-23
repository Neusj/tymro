import axios from 'axios'

export const API_BASE_URL = import.meta.env.VITE_API_URL || import.meta.env.VITE_API_BASE_URL || '/api'

// Toda petición corta a los 10s. Sin esto axios usa el default 0 = esperar
// indefinidamente: una petición colgada (red caída, proxy sin responder) queda
// a merced del timeout TCP del SO —minutos— y la UI se queda sin desenlace.
// Con el corte, el error llega a la app y cada pantalla puede reaccionar.
const REQUEST_TIMEOUT_MS = 10000

// Overrides por request para endpoints que tardan legítimamente más que el
// default. No se sube el default global: 10s sigue siendo lo correcto para el
// resto, y aflojarlo para todos reviviría el problema que el timeout resuelve.
// Login: en un cold start de Railway el servidor puede tardar bastante en
// responder. Cortar a los 10s es peor que esperar, porque el intento YA se gastó
// contra el throttle de login (5/min) y el token YA rotó server-side: el usuario
// pierde la sesión que el backend acaba de emitir y a los pocos reintentos come
// un 429 sin haber entrado nunca.
const LOGIN_TIMEOUT_MS = 40000
// Importador: validate parsea el XLSX completo y commit escribe fila por fila
// dentro de una transacción, ambos antes de responder.
const IMPORT_TIMEOUT_MS = 60000
// Robot de la ventana rodante disparado a mano (botón "actualizar clases" del
// gym_admin): corre SÍNCRONO dentro del propio request (extensión de series +
// sync de estados + poda), sin cola de background. En prod solo hay 3 workers
// gunicorn, así que puede tardar bastante más que el default de 10s.
const ADVANCE_CLASS_WINDOWS_TIMEOUT_MS = 60000

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: REQUEST_TIMEOUT_MS,
})

// Instancia separada para endpoints PÚBLICOS (registro de clase de prueba y
// pantalla pública de asistencia). NUNCA adjunta Authorization ni tiene el
// interceptor de 401→/login: así un token caducado guardado en localStorage no
// puede provocar un 401 espurio ni expulsar al visitante anónimo. `setAuthToken`
// no la toca (solo escribe en `api`). Se exporta SOLO para poder verificar su
// config (timeout) en tests: las llamadas siguen pasando por los módulos de
// abajo (`registrationApi`, `attendanceQrApi`), no por la instancia directa.
export const publicApi = axios.create({
  baseURL: API_BASE_URL,
  timeout: REQUEST_TIMEOUT_MS,
})

// Claves de sesión (mismas que usa AuthContext).
const TOKEN_KEY = 'tymro_token'
const USER_KEY = 'tymro_user'

// Ante un 401 (token expirado/inválido) limpiamos la sesión y mandamos al login.
// No redirige cuando el 401 viene del propio login ni cuando ya estamos en /login,
// para no romper el mensaje de "credenciales inválidas" ni provocar loops.
api.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error?.response?.status
    const requestUrl = error?.config?.url || ''
    const isAuthEndpoint = requestUrl.includes('/login/') || requestUrl.includes('/password-reset')
    // Endpoints públicos AllowAny (clase de prueba + pantalla pública de asistencia):
    // aunque normalmente usan `publicApi` sin token, blindamos también `api` para que
    // un 401 espurio jamás redirija a /login a un visitante anónimo. OJO: se enumeran
    // de forma exacta y NO con un `/public/` amplio, porque /public/trial-classes/ y
    // /public/trial/book/ SÍ son autenticados (alumno) y su 401 sí debe redirigir.
    const isPublicEndpoint =
      requestUrl.includes('/public/invite/') ||
      requestUrl.includes('/public/register/') ||
      requestUrl.includes('/public/verify-email/') ||
      requestUrl.includes('/attendance-qr/screen-auto') ||
      requestUrl.includes('/attendance-qr/screen/')

    if (status === 401 && !isAuthEndpoint && !isPublicEndpoint && window.location.pathname !== '/login') {
      localStorage.removeItem(TOKEN_KEY)
      localStorage.removeItem(USER_KEY)
      setAuthToken(null)
      window.location.assign('/login')
    }

    return Promise.reject(error)
  },
)

const toFormData = (payload = {}) => {
  const formData = new FormData()
  Object.entries(payload).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') {
      return
    }
    formData.append(key, value)
  })
  return formData
}

export const setAuthToken = (token) => {
  if (token) {
    api.defaults.headers.common.Authorization = `Token ${token}`
  } else {
    delete api.defaults.headers.common.Authorization
  }
}

export const resolveMediaUrl = (url) => {
  if (!url) {
    return ''
  }
  if (url.startsWith('http')) {
    return url
  }

  const backendBase = API_BASE_URL.replace(/\/api\/?$/, '')
  return `${backendBase}${url}`
}

export const authApi = {
  login: async (credentials) => {
    const { data } = await api.post('/login/', credentials, { timeout: LOGIN_TIMEOUT_MS })
    return data
  },
  logout: async () => {
    const { data } = await api.post('/logout/')
    return data
  },
  me: async () => {
    const { data } = await api.get('/me/')
    return data
  },
  // Self-service: el propio usuario completa/actualiza su RUT (y teléfono). El
  // backend acota los campos escribibles (nunca rol/org/is_active).
  updateMe: async (payload) => {
    const { data } = await api.patch('/me/', payload)
    return data
  },
  requestPasswordReset: async (email) => {
    const { data } = await api.post('/password-reset/', { email })
    return data
  },
  confirmPasswordReset: async ({ uid, token, newPassword }) => {
    const { data } = await api.post('/password-reset/confirm/', {
      uid,
      token,
      new_password: newPassword,
    })
    return data
  },
  // Reenvía el correo de confirmación al usuario autenticado (#26). Instancia
  // `api` (con Authorization): el backend lo exige (IsAuthenticated) y responde
  // 200 tanto si envía como si ya estaba verificado (no-op); 429 si topa el throttle.
  resendVerification: async () => {
    const { data } = await api.post('/resend-verification/')
    return data
  },
}

// Registro público de prospectos + clase de prueba gratis (links por gimnasio).
// Usa `publicApi` (sin Authorization, sin redirect 401): la persona que escanea
// el QR no está autenticada y un token viejo en el navegador no debe interferir.
export const registrationApi = {
  // Resuelve el gym por el SUBDOMINIO del host (sin slug) y devuelve su branding.
  // `slug` es opcional: solo lo usan los links viejos servidos en el apex (back-compat).
  validateInvite: async ({ slug } = {}) => {
    const { data } = await publicApi.get('/public/invite/', { params: slug ? { slug } : {} })
    return data
  },
  register: async ({ slug, firstName, lastName, email, password, phone }) => {
    const payload = {
      first_name: firstName,
      last_name: lastName,
      email,
      password,
      phone,
    }
    if (slug) {
      payload.slug = slug
    }
    const { data } = await publicApi.post('/public/register/', payload)
    return data
  },
  verifyEmail: async ({ uid, token }) => {
    const { data } = await publicApi.post('/public/verify-email/', { uid, token })
    return data
  },
  listTrialClasses: async () => {
    const { data } = await api.get('/public/trial-classes/')
    return data
  },
  bookTrial: async (gymClassId) => {
    const { data } = await api.post('/public/trial/book/', { gym_class: gymClassId })
    return data
  },
}

export const dashboardApi = {
  summary: async () => {
    const { data } = await api.get('/dashboard/')
    return data
  },
}

export const organizationsApi = {
  list: async () => {
    const { data } = await api.get('/organizations/')
    return data
  },
  retrieve: async (id) => {
    const { data } = await api.get(`/organizations/${id}/`)
    return data
  },
  create: async (payload, asFormData = false) => {
    const body = asFormData ? toFormData(payload) : payload
    const { data } = await api.post('/organizations/', body)
    return data
  },
  update: async (id, payload, asFormData = false) => {
    const body = asFormData ? toFormData(payload) : payload
    const { data } = await api.patch(`/organizations/${id}/`, body)
    return data
  },
  remove: async (id) => {
    await api.delete(`/organizations/${id}/`)
  },
  setPublicRegistration: async (id, enabled) => {
    const { data } = await api.post(`/organizations/${id}/set-public-registration/`, { enabled })
    return data
  },
}

export const branchesApi = {
  list: async (params = {}) => {
    const { data } = await api.get('/branches/', { params })
    return data
  },
  create: async (payload, asFormData = false) => {
    const body = asFormData ? toFormData(payload) : payload
    const { data } = await api.post('/branches/', body)
    return data
  },
  update: async (id, payload, asFormData = false) => {
    const body = asFormData ? toFormData(payload) : payload
    const { data } = await api.patch(`/branches/${id}/`, body)
    return data
  },
  remove: async (id) => {
    await api.delete(`/branches/${id}/`)
  },
}

export const usersApi = {
  list: async (params = {}) => {
    const { data } = await api.get('/users/', { params })
    return data
  },
  retrieve: async (id) => {
    const { data } = await api.get(`/users/${id}/`)
    return data
  },
  assignableRoles: async () => {
    const { data } = await api.get('/users/assignable-roles/')
    return data
  },
  create: async (payload, asFormData = false) => {
    const body = asFormData ? toFormData(payload) : payload
    const { data } = await api.post('/users/', body)
    return data
  },
  update: async (id, payload, asFormData = false) => {
    const body = asFormData ? toFormData(payload) : payload
    const { data } = await api.patch(`/users/${id}/`, body)
    return data
  },
  remove: async (id) => {
    await api.delete(`/users/${id}/`)
  },
}

export const classTypesApi = {
  list: async (params = {}) => {
    const { data } = await api.get('/class-types/', { params })
    return data
  },
  create: async (payload) => {
    const { data } = await api.post('/class-types/', payload)
    return data
  },
  update: async (id, payload) => {
    const { data } = await api.patch(`/class-types/${id}/`, payload)
    return data
  },
  remove: async (id) => {
    await api.delete(`/class-types/${id}/`)
  },
}

export const disciplinesApi = {
  list: async (params = {}) => {
    const { data } = await api.get('/disciplines/', { params })
    return data
  },
  create: async (payload) => {
    const { data } = await api.post('/disciplines/', payload)
    return data
  },
  update: async (id, payload) => {
    const { data } = await api.patch(`/disciplines/${id}/`, payload)
    return data
  },
  remove: async (id) => {
    await api.delete(`/disciplines/${id}/`)
  },
}

export const classesApi = {
  list: async (params = {}) => {
    const { data } = await api.get('/classes/', { params })
    return data
  },
  byDate: async (date, params = {}) => {
    const { data } = await api.get('/classes/by-date/', { params: { ...params, date } })
    return data
  },
  coverable: async (date, params = {}) => {
    const requestParams = date ? { ...params, date } : params
    const { data } = await api.get('/classes/coverable/', { params: requestParams })
    return data
  },
  retrieve: async (id) => {
    const { data } = await api.get(`/classes/${id}/`)
    return data
  },
  create: async (payload) => {
    const { data } = await api.post('/classes/', payload)
    return data
  },
  update: async (id, payload) => {
    const { data } = await api.patch(`/classes/${id}/`, payload)
    return data
  },
  claimSubstitution: async (id) => {
    const { data } = await api.post(`/classes/${id}/claim-substitution/`)
    return data
  },
  releaseSubstitution: async (id) => {
    const { data } = await api.post(`/classes/${id}/release-substitution/`)
    return data
  },
  remove: async (id) => {
    await api.delete(`/classes/${id}/`)
  },
  enrolledStudents: async (id) => {
    const { data } = await api.get(`/classes/${id}/enrolled-students/`)
    return data
  },
  enrollableStudents: async (id) => {
    const { data } = await api.get(`/classes/${id}/enrollable-students/`)
    return data
  },
  saveAttendance: async (id, attendances) => {
    const { data } = await api.post(`/classes/${id}/attendance/`, { attendances })
    return data
  },
  toggleAttendance: async (id, payload) => {
    const { data } = await api.post(`/classes/${id}/attendance-toggle/`, payload)
    return data
  },
  // Historial inmutable de correcciones de asistencia (solo gym_admin/superadmin;
  // el backend responde 403 para otros roles). Lista [{id, attendance, student,
  // student_name, previous_status, new_status, changed_by, changed_by_username,
  // changed_at}] ordenada por -changed_at.
  getAttendanceHistory: async (id) => {
    const { data } = await api.get(`/classes/${id}/attendance-history/`)
    return data
  },
  cancel: async (id, comment) => {
    const { data } = await api.post(`/classes/${id}/cancel/`, { comment })
    return data
  },
  completeEarly: async (id, comment) => {
    const { data } = await api.post(`/classes/${id}/complete-early/`, { comment })
    return data
  },
  suspend: async (id, payload = {}) => {
    const { data } = await api.post(`/classes/${id}/suspend/`, payload)
    return data
  },
  reactivate: async (id) => {
    const { data } = await api.post(`/classes/${id}/reactivate/`)
    return data
  },
  bulkClose: async (payload) => {
    const { data } = await api.post('/classes/bulk-close/', payload)
    return data
  },
  dashboardSummary: async (params = {}) => {
    const { data } = await api.get('/classes/dashboard-summary/', { params })
    return data
  },
}

export const classTemplatesApi = {
  list: async (params = {}) => {
    const { data } = await api.get('/class-templates/', { params })
    return data
  },
  create: async (payload) => {
    const { data } = await api.post('/class-templates/', payload)
    return data
  },
  update: async (id, payload) => {
    const { data } = await api.patch(`/class-templates/${id}/`, payload)
    return data
  },
  remove: async (id) => {
    await api.delete(`/class-templates/${id}/`)
  },
  generate: async (id, payload = {}) => {
    const { data } = await api.post(`/class-templates/${id}/generate/`, payload)
    return data
  },
  bulkAction: async (payload) => {
    const { data } = await api.post('/class-templates/bulk-action/', payload)
    return data
  },
  cancelFutureInstances: async (id, payload = {}) => {
    const { data } = await api.post(`/class-templates/${id}/cancel-future-instances/`, payload)
    return data
  },
  reactivateFutureCancelled: async (id, payload = {}) => {
    const { data } = await api.post(`/class-templates/${id}/reactivate-future-cancelled/`, payload)
    return data
  },
  recurringEnroll: async (id, payload = {}) => {
    const { data } = await api.post(`/class-templates/${id}/recurring-enroll/`, payload)
    return data
  },
  reservationCandidates: async (id, payload = {}) => {
    const { data } = await api.post(`/class-templates/${id}/reservation-candidates/`, payload)
    return data
  },
}

// Botón "actualizar clases" del gym_admin (panel de series recurrentes): dispara a
// mano el mismo robot que corre el cron diario, para la organización del actor. El
// backend no lee body (la org sale del token) y el 403 es la autorización real
// (solo gym_admin con org activa); acá NO se decide quién puede llamarlo.
export const advanceClassWindowsApi = {
  run: async () => {
    const { data } = await api.post('/advance-class-windows/', undefined, {
      timeout: ADVANCE_CLASS_WINDOWS_TIMEOUT_MS,
    })
    return data
  },
}

export const holidaysApi = {
  list: async (params = {}) => {
    const { data } = await api.get('/holidays/', { params })
    return data
  },
  create: async (payload) => {
    const { data } = await api.post('/holidays/', payload)
    return data
  },
  update: async (id, payload) => {
    const { data } = await api.patch(`/holidays/${id}/`, payload)
    return data
  },
  remove: async (id) => {
    await api.delete(`/holidays/${id}/`)
  },
}

// Configuración del email de seguimiento de clases de prueba (panel gym_admin).
// Contrato: is_enabled, delay_minutes, email_subject, email_body.
export const trialFollowupConfigApi = {
  get: async (orgId) => {
    const { data } = await api.get(`/organizations/${orgId}/trial-followup-config/`)
    return data
  },
  update: async (orgId, payload) => {
    const { data } = await api.put(`/organizations/${orgId}/trial-followup-config/`, payload)
    return data
  },
}

// Configuración de avisos de vencimiento de membresía (R5). Contrato:
// reminder_days_before (lista de enteros, días de anticipación) + send_expired_notice
// (bool). La MISMA lista maneja el correo que manda el backend y el banner que ve el
// alumno en /student/classes/available (show_expiry_banner en getMyMemberships): no
// hay dos configs separadas.
export const expiryNotificationConfigApi = {
  get: async (orgId) => {
    const { data } = await api.get(`/organizations/${orgId}/expiry-notification-config/`)
    return data
  },
  update: async (orgId, payload) => {
    const { data } = await api.put(`/organizations/${orgId}/expiry-notification-config/`, payload)
    return data
  },
}

// Configuración del valor de "clase gratis" usado para calcular el pago al profesor en
// planes con discount_percentage=100 (gratuitos). Contrato: free_class_teacher_payment_value
// (número, nace en 0). En 0 el backend rechaza la creación/edición de planes gratuitos.
export const teacherPaymentConfigApi = {
  get: async (orgId) => {
    const { data } = await api.get(`/organizations/${orgId}/teacher-payment-config/`)
    return data
  },
  update: async (orgId, payload) => {
    const { data } = await api.put(`/organizations/${orgId}/teacher-payment-config/`, payload)
    return data
  },
}

export const enrollmentFeeConfigApi = {
  get: async (orgId) => {
    const { data } = await api.get(`/organizations/${orgId}/enrollment-fee-config/`)
    return data
  },
  update: async (orgId, payload) => {
    const { data } = await api.put(`/organizations/${orgId}/enrollment-fee-config/`, payload)
    return data
  },
}

export const reservationWindowConfigApi = {
  get: async (orgId) => {
    const { data } = await api.get(`/organizations/${orgId}/reservation-window-config/`)
    return data
  },
  update: async (orgId, payload) => {
    const { data } = await api.put(`/organizations/${orgId}/reservation-window-config/`, payload)
    return data
  },
}

export const attendanceEditConfigApi = {
  get: async (orgId) => {
    const { data } = await api.get(`/organizations/${orgId}/attendance-edit-config/`)
    return data
  },
  update: async (orgId, payload) => {
    const { data } = await api.put(`/organizations/${orgId}/attendance-edit-config/`, payload)
    return data
  },
}

export const recurringEnrollmentsApi = {
  list: async (params = {}) => {
    const { data } = await api.get('/recurring-enrollments/', { params })
    return data
  },
  my: async (params = {}) => {
    const { data } = await api.get('/my-recurring-enrollments/', { params })
    return data
  },
  update: async (id, payload) => {
    const { data } = await api.patch(`/recurring-enrollments/${id}/`, payload)
    return data
  },
  remove: async (id) => {
    await api.delete(`/recurring-enrollments/${id}/`)
  },
}

export const enrollmentsApi = {
  list: async (params = {}) => {
    const { data } = await api.get('/enrollments/', { params })
    return data
  },
  create: async (payload) => {
    const { data } = await api.post('/enrollments/', payload)
    return data
  },
  batch: async (payload) => {
    const { data } = await api.post('/enrollments/batch/', payload)
    return data
  },
  update: async (id, payload) => {
    const { data } = await api.patch(`/enrollments/${id}/`, payload)
    return data
  },
  remove: async (id) => {
    await api.delete(`/enrollments/${id}/`)
  },
  my: async () => {
    const { data } = await api.get('/enrollments/my/')
    return data
  },
  cancel: async (id) => {
    const { data } = await api.post(`/enrollments/${id}/cancel/`)
    return data
  },
}

export const teacherPaymentRulesApi = {
  list: async (params = {}) => {
    const { data } = await api.get('/teacher-payment-rules/', { params })
    return data
  },
  create: async (payload) => {
    const { data } = await api.post('/teacher-payment-rules/', payload)
    return data
  },
  update: async (id, payload) => {
    const { data } = await api.put(`/teacher-payment-rules/${id}/`, payload)
    return data
  },
  remove: async (id) => {
    await api.delete(`/teacher-payment-rules/${id}/`)
  },
  assignments: async (id) => {
    const { data } = await api.get(`/teacher-payment-rules/${id}/assignments/`)
    return data
  },
  updateAssignments: async (id, teacherIds = []) => {
    const { data } = await api.put(`/teacher-payment-rules/${id}/assignments/`, { teacher_ids: teacherIds })
    return data
  },
}

export const teacherPaymentsApi = {
  list: async (params = {}) => {
    const { data } = await api.get('/teacher-payments/', { params })
    return data
  },
  my: async (params = {}) => {
    const { data } = await api.get('/teacher-payments/my/', { params })
    return data
  },
  summary: async (params = {}) => {
    const { data } = await api.get('/teacher-payments/summary/', { params })
    return data
  },
  exportSummary: async (params = {}) => {
    const response = await api.get('/teacher-payments/summary/export/', {
      params,
      responseType: 'blob',
    })
    return response
  },
  markPaid: async (payload = {}) => {
    const { data } = await api.post('/teacher-payments/mark-paid/', payload)
    return data
  },
}

// Importador de datos (onboarding): solo gym_admin/superadmin (el backend lo
// exige; aquí no hay control real). El flujo es plantilla → validate → commit
// con el MISMO archivo + token de previsualización.
export const importsApi = {
  entities: async () => {
    const { data } = await api.get('/imports/entities/')
    return data
  },
  downloadTemplate: async (entity) => {
    const response = await api.get(`/imports/${entity}/template/`, { responseType: 'blob' })
    return response
  },
  validate: async (entity, file) => {
    const { data } = await api.post(`/imports/${entity}/validate/`, toFormData({ file }), {
      timeout: IMPORT_TIMEOUT_MS,
    })
    return data
  },
  commit: async (entity, file, token) => {
    const { data } = await api.post(`/imports/${entity}/commit/`, toFormData({ file, token }), {
      timeout: IMPORT_TIMEOUT_MS,
    })
    return data
  },
}

export const attendanceQrApi = {
  current: async () => {
    const { data } = await api.get('/attendance-qr/current/')
    return data
  },
  // Pantalla pública de recepción (sin sesión): usa `publicApi`, sin token.
  screen: async (code) => {
    const { data } = await publicApi.post('/attendance-qr/screen/', { code })
    return data
  },
  // Pantalla automática por gym: usa el código permanente embebido en la URL.
  // Pública (TV/tablet sin sesión): `publicApi`, sin token.
  screenAuto: async (code) => {
    const { data } = await publicApi.get('/attendance-qr/screen-auto/', { params: { code } })
    return data
  },
  screenCode: async () => {
    const { data } = await api.get('/attendance-qr/screen-code/')
    return data
  },
  regenerateScreenCode: async () => {
    const { data } = await api.post('/attendance-qr/screen-code/')
    return data
  },
  startScreenSession: async () => {
    const { data } = await api.post('/attendance-qr/screen-session/')
    return data
  },
  preview: async (token) => {
    const { data } = await api.get('/attendance-qr/preview/', { params: { token } })
    return data
  },
  // Confirma con el grant de un solo uso emitido por el preview (no el token del QR).
  checkIn: async (grant) => {
    const { data } = await api.post('/attendance-qr/check-in/', { grant })
    return data
  },
}

const normalizeListResponse = (data) => {
  if (Array.isArray(data)) {
    return data
  }
  if (Array.isArray(data?.results)) {
    return data.results
  }
  if (Array.isArray(data?.data)) {
    return data.data
  }
  return []
}

export const getPlans = async (params = {}) => {
  const { data } = await api.get('/plans/', { params })
  return normalizeListResponse(data)
}

export const getPlanById = async (id) => {
  const { data } = await api.get(`/plans/${id}/`)
  return data
}

export const createPlan = async (payload) => {
  const { data } = await api.post('/plans/', payload)
  return data
}

export const updatePlan = async (id, payload) => {
  const { data } = await api.patch(`/plans/${id}/`, payload)
  return data
}

export const removePlan = async (id) => {
  await api.delete(`/plans/${id}/`)
}

export const assignPlanToUser = async (payload) => {
  const { data } = await api.post('/plans/assign/', payload)
  return data
}

export const quotePlanAssignment = async (payload) => {
  const { data } = await api.post('/plans/assignment-quote/', payload)
  return data
}

export const getPlanMemberships = async (planId) => {
  const { data } = await api.get(`/plans/${planId}/memberships/`)
  return data
}

export const removePlanMembership = async (planId, membershipId) => {
  await api.delete(`/plans/${planId}/memberships/${membershipId}/`)
}

export const updatePlanMembership = async (planId, membershipId, payload) => {
  const { data } = await api.patch(`/plans/${planId}/memberships/${membershipId}/edit/`, payload)
  return data
}

export const getPlanMembershipChangeLog = async (planId, membershipId) => {
  const { data } = await api.get(`/plans/${planId}/memberships/${membershipId}/change-log/`)
  return data
}

export const getMyPlan = async () => {
  const { data } = await api.get('/plans/my-plan/')
  return data
}

export const getMyMemberships = async () => {
  const { data } = await api.get('/plans/my-memberships/')
  return data
}

// P4 · Feature B (gym_admin, solo lectura): vista integral de UN alumno de la propia
// organización — membresías, consumo, asistencia, reservas y recurrencias vigentes en una
// sola lectura agregada. `params` acepta los límites del historial acotado (opcionales):
// `consumption_limit`, `attendance_limit`, `reservations_limit`, cada uno con un tope duro
// que decide el backend (el front no puede pedir más de ahí aunque lo intente).
export const getStudentOverview = async (studentId, params = {}) => {
  const { data } = await api.get(`/students/${encodeURIComponent(studentId)}/overview/`, { params })
  return data
}

export const studentOverviewDetailsApi = {
  reservations: async (studentId, params = {}) => {
    const { data } = await api.get(`/students/${encodeURIComponent(studentId)}/reservations/`, { params })
    return data
  },
  attendance: async (studentId, params = {}) => {
    const { data } = await api.get(`/students/${encodeURIComponent(studentId)}/attendance/`, { params })
    return data
  },
  consumption: async (studentId, params = {}) => {
    const { data } = await api.get(`/students/${encodeURIComponent(studentId)}/consumption/`, { params })
    return data
  },
  memberships: async (studentId, params = {}) => {
    const { data } = await api.get(`/students/${encodeURIComponent(studentId)}/memberships/`, { params })
    return data
  },
  recurringReservations: async (studentId, params = {}) => {
    const { data } = await api.get(`/students/${encodeURIComponent(studentId)}/recurring-reservations/`, { params })
    return data
  },
}

// Pagos con MercadoPago (Checkout Pro + OAuth por organización). Todo por la
// instancia autenticada `api`: los cuatro endpoints exigen token (nunca publicApi).
// La activación real del plan la confirma el webhook del backend, no estas llamadas.
export const paymentsApi = {
  // gym_admin/superadmin: estado de la conexión. Sin branchId → cuenta PRINCIPAL de la org
  // (comportamiento de siempre). Con branchId → cuenta de ESA sucursal.
  // → {status:'disconnected', provider} (nunca existió una fila para ese scope) o
  //   {provider, status:'connected'|'disconnected', provider_user_id, is_sandbox,
  //    connected_at, token_expires_at, branch} (existe fila; branch=null es la principal).
  getAccount: async ({ branchId } = {}) => {
    const params = branchId ? { branch_id: branchId } : undefined
    const { data } = await api.get('/payments/account/', { params })
    return data
  },
  // gym_admin/superadmin: inicia OAuth. Sin branchId → conecta la cuenta PRINCIPAL. Con
  // branchId → conecta la cuenta PROPIA de esa sucursal (409 si la principal no está
  // conectada todavía). → {authorization_url}
  connect: async ({ branchId } = {}) => {
    const payload = branchId ? { branch_id: branchId } : {}
    const { data } = await api.post('/payments/connect/', payload)
    return data
  },
  // gym_admin/superadmin: desconecta la cuenta (borra tokens, no la fila). Sin branchId →
  // la principal. Con branchId → SOLO la de esa sucursal. → {status:'disconnected', provider}
  disconnect: async ({ branchId } = {}) => {
    const payload = branchId ? { branch_id: branchId } : {}
    const { data } = await api.post('/payments/disconnect/', payload)
    return data
  },
  // student: crea PaymentTransaction + preference. Exactamente uno de planId
  // (comprar/renovar plan) o targetStudentPlanId (pagar matrícula pendiente).
  // → {transaction_id, redirect_url}
  checkout: async ({ planId, targetStudentPlanId } = {}) => {
    const payload = {}
    if (planId) payload.plan_id = planId
    if (targetStudentPlanId) payload.target_student_plan_id = targetStudentPlanId
    const { data } = await api.post('/payments/checkout/', payload)
    return data
  },
  // student dueño de la tx: estado informativo para el polling del back_url.
  // → {id, status, status_detail, amount, currency}
  transactionStatus: async (id) => {
    const { data } = await api.get(`/payments/transactions/${id}/status/`)
    return data
  },
  // gym_admin: listado paginado (server-side) de transacciones de su organización.
  // Params: page, pageSize, status, dateFrom, dateTo. → { count, next, previous, results }
  listTransactions: async ({ page = 1, pageSize = 25, status, dateFrom, dateTo } = {}) => {
    const params = { page, page_size: pageSize }
    if (status) params.status = status
    if (dateFrom) params.date_from = dateFrom
    if (dateTo) params.date_to = dateTo
    const { data } = await api.get('/payments/transactions/', { params })
    return data
  },
}

// Reportería P3.4/P3.5 (gym_admin): reportes de solo lectura, mismo contrato de query
// params en la mayoría (date_from, date_to, branch_id, granularity, + un filtro propio de
// cada uno: method en revenue, discipline_id en occupancy, plan_id en retención). `export`
// pide el MISMO endpoint pero con el archivo (csv/xlsx) en vez de JSON — no es una ruta
// separada como `/teacher-payments/summary/export/`, así que exportRevenue/... reusan la
// misma URL que revenue/occupancy/..., solo cambiando `export` y `responseType`.
// El reporte de "pagos manuales" (listado propio) se eliminó en P3.5: ese drilldown ahora
// vive DENTRO de Ingresos (capas 2/3 de revenuePayments/revenuePaymentDetail más abajo) —
// no reintroducir manualPayments/exportManualPayments, ese endpoint del backend ya no existe.
export const reportsApi = {
  revenue: async (params = {}) => {
    const { data } = await api.get('/reports/revenue/', { params })
    return data
  },
  // Capa 2 del drilldown de Ingresos: cobros + devoluciones de UN método (mercadopago |
  // cash | transfer | card | check | unknown), en el mismo período/sucursal que la capa 1.
  revenuePayments: async (params = {}) => {
    const { data } = await api.get('/reports/revenue/payments/', { params })
    return data
  },
  exportRevenuePayments: async (params = {}, format = 'csv') => {
    const response = await api.get('/reports/revenue/payments/', {
      params: { ...params, export: format },
      responseType: 'blob',
    })
    return response
  },
  // Capa 3 del drilldown de Ingresos: el detalle de UN pago puntual. `kind` es
  // 'mercadopago' | 'manual', `id` es el UUID (mercadopago) o el int (manual) de esa fila.
  // `encodeURIComponent` en los dos: `kind` e `id` salen de los params de la ruta, o sea de
  // la URL que el usuario tiene en la barra, no de una lista cerrada nuestra. Sin escapar, un
  // `id` con `/` o `?` reescribe el path o inyecta query params en una request de plata.
  // El backend igual responde 400/404 a cualquier valor que no sea un UUID o un int, pero la
  // URL tiene que llegar entera para que sea ESE 404 y no otra ruta.
  revenuePaymentDetail: async (kind, id) => {
    const { data } = await api.get(
      `/reports/revenue/payments/${encodeURIComponent(kind)}/${encodeURIComponent(id)}/`)
    return data
  },
  occupancy: async (params = {}) => {
    const { data } = await api.get('/reports/occupancy/', { params })
    return data
  },
  // P3.4 parte 2: mismo contrato de query params que los tres de arriba (date_from,
  // date_to, branch_id, granularity, export), más el filtro propio de cada uno
  // (plan_id en retención; trial-conversion no tiene filtro propio, solo período+sucursal).
  retention: async (params = {}) => {
    const { data } = await api.get('/reports/retention/', { params })
    return data
  },
  trialConversion: async (params = {}) => {
    const { data } = await api.get('/reports/trial-conversion/', { params })
    return data
  },
  exportRevenue: async (params = {}, format = 'csv') => {
    const response = await api.get('/reports/revenue/', {
      params: { ...params, export: format },
      responseType: 'blob',
    })
    return response
  },
  exportOccupancy: async (params = {}, format = 'csv') => {
    const response = await api.get('/reports/occupancy/', {
      params: { ...params, export: format },
      responseType: 'blob',
    })
    return response
  },
  exportRetention: async (params = {}, format = 'csv') => {
    const response = await api.get('/reports/retention/', {
      params: { ...params, export: format },
      responseType: 'blob',
    })
    return response
  },
  exportTrialConversion: async (params = {}, format = 'csv') => {
    const response = await api.get('/reports/trial-conversion/', {
      params: { ...params, export: format },
      responseType: 'blob',
    })
    return response
  },
}

// Dispara la descarga de un blob de respuesta (export CSV/XLSX de reportería). Mismo
// patrón que ya usan TeacherPaymentsOverviewPage.handleExport y GymAdminImportPage.
// downloadTemplate (Blob → object URL → <a download> → click → revoke); centralizado
// acá para que las 3 páginas nuevas de reportería no lo copien una tercera, cuarta y
// quinta vez.
export const downloadReportFile = (response, filename) => {
  const blob = new Blob([response.data], { type: response.headers?.['content-type'] })
  const url = window.URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.URL.revokeObjectURL(url)
}

export default api
