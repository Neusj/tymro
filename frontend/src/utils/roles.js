export const roleRoutes = {
  superadmin: '/superadmin/organizations',
  gym_admin: '/gym-admin/dashboard',
  teacher: '/teacher/classes/upcoming',
  student: '/student/classes/available',
}

export const roleLabels = {
  superadmin: 'Superadmin',
  gym_admin: 'Gym Admin',
  teacher: 'Teacher',
  student: 'Student',
}

export const defaultRouteByRole = (role) => roleRoutes[role] || '/login'
