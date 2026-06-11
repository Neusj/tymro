// manager y monitor no tienen UI propia todavía (Ronda 3): defaultRouteByRole
// los manda a /login.
export const roleRoutes = {
  superadmin: '/superadmin/organizations',
  gym_admin: '/gym-admin/dashboard',
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
