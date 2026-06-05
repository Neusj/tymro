import axios from 'axios'

export const API_BASE_URL = import.meta.env.VITE_API_URL || import.meta.env.VITE_API_BASE_URL || '/api'

const api = axios.create({
  baseURL: API_BASE_URL,
})

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
    const { data } = await api.post('/login/', credentials)
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
  cancel: async (id, comment) => {
    const { data } = await api.post(`/classes/${id}/cancel/`, { comment })
    return data
  },
  completeEarly: async (id, comment) => {
    const { data } = await api.post(`/classes/${id}/complete-early/`, { comment })
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
}

export const attendanceQrApi = {
  current: async () => {
    const { data } = await api.get('/attendance-qr/current/')
    return data
  },
  screen: async (code) => {
    const { data } = await api.post('/attendance-qr/screen/', { code })
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
  checkIn: async (token) => {
    const { data } = await api.post('/attendance-qr/check-in/', { token })
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

export const getPlanMemberships = async (planId) => {
  const { data } = await api.get(`/plans/${planId}/memberships/`)
  return data
}

export const removePlanMembership = async (planId, membershipId) => {
  await api.delete(`/plans/${planId}/memberships/${membershipId}/`)
}

export const getMyPlan = async () => {
  const { data } = await api.get('/plans/my-plan/')
  return data
}

export const getMyMemberships = async () => {
  const { data } = await api.get('/plans/my-memberships/')
  return data
}

export default api
