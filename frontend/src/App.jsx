import { Navigate, Route, Routes } from 'react-router-dom'
import { useAuth } from './auth/AuthContext'
import AppLayout from './components/layout/AppLayout'
import GymAdminClassCreatePage from './pages/GymAdminClassCreatePage'
import GymAdminClassDetailPage from './pages/GymAdminClassDetailPage'
import GymAdminClassEditPage from './pages/GymAdminClassEditPage'
import GymAdminClassTemplatesPage from './pages/GymAdminClassTemplatesPage'
import GymAdminClassesPage from './pages/GymAdminClassesPage'
import GymAdminClassTypesPage from './pages/GymAdminClassTypesPage'
import GymAdminDisciplinesPage from './pages/GymAdminDisciplinesPage'
import GymAdminHolidaysPage from './pages/GymAdminHolidaysPage'
import GymAdminBranchesPage from './pages/GymAdminBranchesPage'
import GymAdminAttendanceQrPage from './pages/GymAdminAttendanceQrPage'
import AssignPlanPage from './pages/AssignPlanPage'
import AttendanceScreenPage from './pages/AttendanceScreenPage'
import AttendanceScreenAutoPage from './pages/AttendanceScreenAutoPage'
import GymAdminDashboard from './pages/GymAdminDashboard'
import GymAdminUsersPage from './pages/GymAdminUsersPage'
import GymAdminPlanMembershipsPage from './pages/GymAdminPlanMembershipsPage'
import LoginPage from './pages/LoginPage'
import ForgotPasswordPage from './pages/ForgotPasswordPage'
import ResetPasswordPage from './pages/ResetPasswordPage'
import GymPublicRegisterPage from './pages/GymPublicRegisterPage'
import VerifyEmailPage from './pages/VerifyEmailPage'
import TrialBookingPage from './pages/TrialBookingPage'
import PlanListPage from './pages/PlanListPage'
import StudentClassesPage from './pages/StudentClassesPage'
import StudentDashboard from './pages/StudentDashboard'
import StudentPlansPage from './pages/StudentPlansPage'
import StudentRecurringEnrollmentsPage from './pages/StudentRecurringEnrollmentsPage'
import StudentQrCheckInPage from './pages/StudentQrCheckInPage'
import SuperadminOrganizationDetailPage from './pages/SuperadminOrganizationDetailPage'
import SuperadminOrganizationsPage from './pages/SuperadminOrganizationsPage'
import SuperadminUsersPage from './pages/SuperadminUsersPage'
import TeacherClassesPage from './pages/TeacherClassesPage'
import TeacherDashboard from './pages/TeacherDashboard'
import TeacherPaymentRulesPage from './pages/TeacherPaymentRulesPage'
import TeacherPaymentsOverviewPage from './pages/TeacherPaymentsOverviewPage'
import TeacherPaymentsPage from './pages/TeacherPaymentsPage'
import ProtectedRoute from './routes/ProtectedRoute'
import { defaultRouteByRole } from './utils/roles'

function RoleBasedHome() {
  const { user } = useAuth()
  if (!user) {
    return <Navigate to="/login" replace />
  }
  return <Navigate to={defaultRouteByRole(user.role)} replace />
}

function ShellRoute({ children }) {
  const { user, logout } = useAuth()

  return (
    <AppLayout user={user} onLogout={logout}>
      {children}
    </AppLayout>
  )
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/forgot-password" element={<ForgotPasswordPage />} />
      <Route path="/reset-password" element={<ResetPasswordPage />} />
      <Route path="/:slug/clase-gratis" element={<GymPublicRegisterPage />} />
      <Route path="/verify-email" element={<VerifyEmailPage />} />
      <Route
        path="/trial"
        element={
          <ProtectedRoute allowedRoles={['student']}>
            <TrialBookingPage />
          </ProtectedRoute>
        }
      />
      <Route path="/attendance/screen" element={<AttendanceScreenPage />} />
      <Route path="/attendance/screen/:code" element={<AttendanceScreenAutoPage />} />
      <Route
        path="/attendance/check-in"
        element={
          <ProtectedRoute allowedRoles={['student']}>
            <StudentQrCheckInPage />
          </ProtectedRoute>
        }
      />

      <Route
        path="/superadmin"
        element={
          <ProtectedRoute allowedRoles={['superadmin']}>
            <Navigate to="/superadmin/organizations" replace />
          </ProtectedRoute>
        }
      />
      <Route
        path="/superadmin/organizations"
        element={
          <ProtectedRoute allowedRoles={['superadmin']}>
            <ShellRoute>
              <SuperadminOrganizationsPage />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/superadmin/organizations/:id"
        element={
          <ProtectedRoute allowedRoles={['superadmin']}>
            <ShellRoute>
              <SuperadminOrganizationDetailPage />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/superadmin/users"
        element={
          <ProtectedRoute allowedRoles={['superadmin']}>
            <ShellRoute>
              <SuperadminUsersPage />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/superadmin/plans"
        element={
          <ProtectedRoute allowedRoles={['superadmin']}>
            <ShellRoute>
              <PlanListPage title="Superadmin · Planes" subtitle="Planes globales disponibles en la plataforma." />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/superadmin/plans/assign"
        element={
          <ProtectedRoute allowedRoles={['superadmin']}>
            <ShellRoute>
              <AssignPlanPage />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/superadmin/teacher-payments"
        element={
          <ProtectedRoute allowedRoles={['superadmin']}>
            <ShellRoute>
              <TeacherPaymentsOverviewPage />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/superadmin/teacher-payments/rules"
        element={
          <ProtectedRoute allowedRoles={['superadmin']}>
            <ShellRoute>
              <TeacherPaymentRulesPage />
            </ShellRoute>
          </ProtectedRoute>
        }
      />

      <Route
        path="/gym-admin"
        element={
          <ProtectedRoute allowedRoles={['gym_admin']}>
            <Navigate to="/gym-admin/dashboard" replace />
          </ProtectedRoute>
        }
      />
      <Route
        path="/gym-admin/dashboard"
        element={
          <ProtectedRoute allowedRoles={['gym_admin']}>
            <ShellRoute>
              <GymAdminDashboard />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/gym-admin/users"
        element={
          <ProtectedRoute allowedRoles={['gym_admin']}>
            <ShellRoute>
              <GymAdminUsersPage />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/gym-admin/branches"
        element={
          <ProtectedRoute allowedRoles={['gym_admin']}>
            <ShellRoute>
              <GymAdminBranchesPage />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/gym-admin/classes"
        element={
          <ProtectedRoute allowedRoles={['gym_admin']}>
            <ShellRoute>
              <GymAdminClassesPage />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/gym-admin/attendance-qr"
        element={
          <ProtectedRoute allowedRoles={['gym_admin']}>
            <ShellRoute>
              <GymAdminAttendanceQrPage />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/gym-admin/class-templates"
        element={
          <ProtectedRoute allowedRoles={['gym_admin']}>
            <ShellRoute>
              <GymAdminClassTemplatesPage />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/gym-admin/classes/create"
        element={
          <ProtectedRoute allowedRoles={['gym_admin']}>
            <ShellRoute>
              <GymAdminClassCreatePage />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/gym-admin/classes/:id/edit"
        element={
          <ProtectedRoute allowedRoles={['gym_admin']}>
            <ShellRoute>
              <GymAdminClassEditPage />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/gym-admin/classes/:id"
        element={
          <ProtectedRoute allowedRoles={['gym_admin']}>
            <ShellRoute>
              <GymAdminClassDetailPage />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/gym-admin/class-types"
        element={
          <ProtectedRoute allowedRoles={['gym_admin']}>
            <ShellRoute>
              <GymAdminClassTypesPage />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/gym-admin/disciplines"
        element={
          <ProtectedRoute allowedRoles={['gym_admin']}>
            <ShellRoute>
              <GymAdminDisciplinesPage />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/gym-admin/holidays"
        element={
          <ProtectedRoute allowedRoles={['gym_admin']}>
            <ShellRoute>
              <GymAdminHolidaysPage />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/gym-admin/plans"
        element={
          <ProtectedRoute allowedRoles={['gym_admin']}>
            <ShellRoute>
              <PlanListPage
                title="Gym Admin · Planes"
                subtitle="Lista de planes y creación de nuevas opciones."
                showMembershipsAction
                membershipsBasePath="/gym-admin/plans"
              />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/gym-admin/plans/:id/memberships"
        element={
          <ProtectedRoute allowedRoles={['gym_admin']}>
            <ShellRoute>
              <GymAdminPlanMembershipsPage />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/gym-admin/plans/assign"
        element={
          <ProtectedRoute allowedRoles={['gym_admin']}>
            <ShellRoute>
              <AssignPlanPage />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/gym-admin/teacher-payments"
        element={
          <ProtectedRoute allowedRoles={['gym_admin']}>
            <ShellRoute>
              <TeacherPaymentsOverviewPage />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/gym-admin/teacher-payments/rules"
        element={
          <ProtectedRoute allowedRoles={['gym_admin']}>
            <ShellRoute>
              <TeacherPaymentRulesPage />
            </ShellRoute>
          </ProtectedRoute>
        }
      />

      <Route
        path="/teacher"
        element={
          <ProtectedRoute allowedRoles={['teacher']}>
            <Navigate to="/teacher/classes/upcoming" replace />
          </ProtectedRoute>
        }
      />
      <Route
        path="/teacher/dashboard"
        element={
          <ProtectedRoute allowedRoles={['teacher']}>
            <ShellRoute>
              <TeacherDashboard />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/teacher/classes"
        element={
          <ProtectedRoute allowedRoles={['teacher']}>
            <Navigate to="/teacher/classes/upcoming" replace />
          </ProtectedRoute>
        }
      />
      <Route
        path="/teacher/classes/upcoming"
        element={
          <ProtectedRoute allowedRoles={['teacher']}>
            <ShellRoute>
              <TeacherClassesPage mode="upcoming" />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/teacher/classes/history"
        element={
          <ProtectedRoute allowedRoles={['teacher']}>
            <ShellRoute>
              <TeacherClassesPage mode="history" />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/teacher/payments"
        element={
          <ProtectedRoute allowedRoles={['teacher']}>
            <ShellRoute>
              <TeacherPaymentsPage />
            </ShellRoute>
          </ProtectedRoute>
        }
      />

      <Route
        path="/student"
        element={
          <ProtectedRoute allowedRoles={['student']}>
            <Navigate to="/student/classes/available" replace />
          </ProtectedRoute>
        }
      />
      <Route
        path="/student/dashboard"
        element={
          <ProtectedRoute allowedRoles={['student']}>
            <ShellRoute>
              <StudentDashboard />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/student/classes"
        element={
          <ProtectedRoute allowedRoles={['student']}>
            <Navigate to="/student/classes/available" replace />
          </ProtectedRoute>
        }
      />
      <Route
        path="/student/plans"
        element={
          <ProtectedRoute allowedRoles={['student']}>
            <ShellRoute>
              <StudentPlansPage />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/student/classes/available"
        element={
          <ProtectedRoute allowedRoles={['student']}>
            <ShellRoute>
              <StudentClassesPage mode="available" />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/student/classes/reservations"
        element={
          <ProtectedRoute allowedRoles={['student']}>
            <ShellRoute>
              <StudentClassesPage mode="reservations" />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/student/classes/recurring"
        element={
          <ProtectedRoute allowedRoles={['student']}>
            <ShellRoute>
              <StudentRecurringEnrollmentsPage />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/student/classes/history"
        element={
          <ProtectedRoute allowedRoles={['student']}>
            <ShellRoute>
              <StudentClassesPage mode="history" />
            </ShellRoute>
          </ProtectedRoute>
        }
      />

      <Route
        path="/"
        element={
          <ProtectedRoute>
            <RoleBasedHome />
          </ProtectedRoute>
        }
      />

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

