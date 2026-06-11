// Ruta de inicio por rol. manager y monitor reutilizan las páginas /gym-admin/*
// (mismas URLs, allowedRoles ampliados y botones ocultos por capacidad).
export const roleRoutes = {
  superadmin: '/superadmin/organizations',
  gym_admin: '/gym-admin/dashboard',
  manager: '/gym-admin/dashboard',
  monitor: '/gym-admin/classes',
  teacher: '/teacher/classes/upcoming',
  student: '/student/classes/available',
}

// Espejo estático de presentación de CustomUser.Role (la fuente canónica es el
// backend, accounts/models.py). Solo para RoleBadge y fallbacks; los selects de
// gestión de usuarios se llenan desde GET /api/users/assignable-roles/.
export const roleLabels = {
  superadmin: 'Superadmin',
  gym_admin: 'Gym Admin',
  manager: 'Manager',
  monitor: 'Monitor',
  teacher: 'Profesor',
  student: 'Alumno',
}

// Roles de plataforma: nunca se ofrecen al gestionar usuarios de organización.
export const platformRoles = ['superadmin']

export const defaultRouteByRole = (role) => roleRoutes[role] || '/login'

// --- Capacidades (espejo de accounts/roles.py) ---
// Única fuente en el front para ocultar botones de escritura por rol. El backend
// sigue siendo la autoridad (devuelve 403); esto solo evita ofrecer acciones que
// el rol no puede ejecutar.

// Roles de organización con capacidad administrativa sobre usuarios.
export const orgAdminRoles = ['gym_admin', 'manager']

// Escritura sobre recursos operativos (grupo a): clases, tipos, disciplinas,
// festivos, plantillas, inscripciones. superadmin / gym_admin / manager.
export const canManageOperational = (role) => role === 'superadmin' || orgAdminRoles.includes(role)

// Escritura sobre recursos admin (grupo b): sucursales, planes, pagos. NO manager.
export const canManageAdmin = (role) => role === 'superadmin' || role === 'gym_admin'

export const isMonitor = (role) => role === 'monitor'
