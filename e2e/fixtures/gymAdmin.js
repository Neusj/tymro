import { loadFixtures, apiContext, gymAdminTokenFromStorage } from './data.js'

// Fixtures sembradas (.fixtures.json). Llamar DENTRO de beforeAll/test, no en el
// top-level del módulo (global-setup las escribe antes de correr los tests).
export function fixtures() {
  return loadFixtures()
}

// Context API autenticado como gym_admin, leyendo el token del storageState.gym.json
// (no gatilla el throttle de /login/).
export async function gymApi() {
  return apiContext(gymAdminTokenFromStorage())
}

// La summary de pagos devuelve teacher_id/teacher_name (no username); mapeamos
// username -> id vía /users/?role=teacher para asertar por profesor.
export async function teacherIdByUsername(api, username) {
  const res = await api.get('users/?role=teacher')
  const data = await res.json()
  const list = Array.isArray(data) ? data : data.results || []
  const u = list.find((x) => x.username === username)
  if (!u) {
    throw new Error(`No se encontró el profesor ${username} en /users/?role=teacher`)
  }
  return u.id
}
