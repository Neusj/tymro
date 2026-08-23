import { Navigate, Route, Routes } from 'react-router-dom'
import { useAuth } from './auth/AuthContext'
import AppLayout from './components/layout/AppLayout'
import OfflineBanner from './components/OfflineBanner'
import GymAdminClassCreatePage from './pages/GymAdminClassCreatePage'
import GymAdminClassDetailPage from './pages/GymAdminClassDetailPage'
import GymAdminClassEditPage from './pages/GymAdminClassEditPage'
import GymAdminClassTemplatesPage from './pages/GymAdminClassTemplatesPage'
import GymAdminClassesPage from './pages/GymAdminClassesPage'
import GymAdminClassTypesPage from './pages/GymAdminClassTypesPage'
import GymAdminDisciplinesPage from './pages/GymAdminDisciplinesPage'
import GymAdminHolidaysPage from './pages/GymAdminHolidaysPage'
import GymAdminTrialFollowupPage from './pages/GymAdminTrialFollowupPage'
import GymAdminExpiryNotificationConfigPage from './pages/GymAdminExpiryNotificationConfigPage'
import GymAdminEnrollmentFeeConfigPage from './pages/GymAdminEnrollmentFeeConfigPage'
import GymAdminReservationWindowConfigPage from './pages/GymAdminReservationWindowConfigPage'
import GymAdminAttendanceEditConfigPage from './pages/GymAdminAttendanceEditConfigPage'
import GymAdminTeacherPaymentConfigPage from './pages/GymAdminTeacherPaymentConfigPage'
import GymAdminImportPage from './pages/GymAdminImportPage'
import GymAdminBranchesPage from './pages/GymAdminBranchesPage'
import GymAdminAttendanceQrPage from './pages/GymAdminAttendanceQrPage'
import AssignPlanPage from './pages/AssignPlanPage'
import AttendanceScreenPage from './pages/AttendanceScreenPage'
import AttendanceScreenAutoPage from './pages/AttendanceScreenAutoPage'
import ClassAttendancePage from './pages/ClassAttendancePage'
import GymAdminDashboard from './pages/GymAdminDashboard'
import GymAdminUsersPage from './pages/GymAdminUsersPage'
import GymAdminStudentOverviewPage from './pages/GymAdminStudentOverviewPage'
import GymAdminStudentMembershipsPage from './pages/GymAdminStudentMembershipsPage'
import GymAdminPlanMembershipsPage from './pages/GymAdminPlanMembershipsPage'
import GymAdminPaymentsSettingsPage from './pages/GymAdminPaymentsSettingsPage'
import GymAdminPaymentsTransactionsPage from './pages/GymAdminPaymentsTransactionsPage'
import GymAdminRevenueReportPage from './pages/GymAdminRevenueReportPage'
import GymAdminRevenueMethodPage from './pages/GymAdminRevenueMethodPage'
import GymAdminPaymentDetailPage from './pages/GymAdminPaymentDetailPage'
import GymAdminOccupancyReportPage from './pages/GymAdminOccupancyReportPage'
import GymAdminRetentionReportPage from './pages/GymAdminRetentionReportPage'
import GymAdminTrialConversionReportPage from './pages/GymAdminTrialConversionReportPage'
import StudentBuyPlanPage from './pages/StudentBuyPlanPage'
import PaymentResultPage from './pages/PaymentResultPage'
import LoginPage from './pages/LoginPage'
import ForgotPasswordPage from './pages/ForgotPasswordPage'
import ResetPasswordPage from './pages/ResetPasswordPage'
import GymPublicRegisterPage from './pages/GymPublicRegisterPage'
import TrialLinkRedirect from './pages/TrialLinkRedirect'
import VerifyEmailPage from './pages/VerifyEmailPage'
import TrialBookingPage from './pages/TrialBookingPage'
import PlanListPage from './pages/PlanListPage'
import StudentClassesPage from './pages/StudentClassesPage'
import StudentDashboard from './pages/StudentDashboard'
import StudentPlansPage from './pages/StudentPlansPage'
import StudentRecurringEnrollmentsPage from './pages/StudentRecurringEnrollmentsPage'
import StudentQrCheckInPage from './pages/StudentQrCheckInPage'
import StudentAttendanceScanPage from './pages/StudentAttendanceScanPage'
import SuperadminOrganizationDetailPage from './pages/SuperadminOrganizationDetailPage'
import SuperadminOrganizationsPage from './pages/SuperadminOrganizationsPage'
import SuperadminUsersPage from './pages/SuperadminUsersPage'
import SuperadminPlatformPage from './pages/SuperadminPlatformPage'
import TeacherClassesPage from './pages/TeacherClassesPage'
import TeacherDashboard from './pages/TeacherDashboard'
import TeacherPaymentRulesPage from './pages/TeacherPaymentRulesPage'
import TeacherPaymentsOverviewPage from './pages/TeacherPaymentsOverviewPage'
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
    <>
      <OfflineBanner />
      <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/forgot-password" element={<ForgotPasswordPage />} />
      <Route path="/reset-password" element={<ResetPasswordPage />} />
      <Route path="/clase-gratis" element={<GymPublicRegisterPage />} />
      <Route path="/:slug/clase-gratis" element={<TrialLinkRedirect />} />
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
        path="/superadmin/platform"
        element={
          <ProtectedRoute allowedRoles={['superadmin']}>
            <ShellRoute>
              <SuperadminPlatformPage />
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
          <ProtectedRoute allowedRoles={['gym_admin', 'manager']}>
            <ShellRoute>
              <GymAdminDashboard />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/gym-admin/users"
        element={
          <ProtectedRoute allowedRoles={['gym_admin', 'manager', 'monitor']}>
            <ShellRoute>
              <GymAdminUsersPage />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      {/* P4 · Feature B: vista integral de UN alumno (membresías, consumo, asistencia,
          reservas, recurrencias). SOLO gym_admin — es superficie financiera
          (`payment_status` de cada membresía), mismo criterio que la reportería: manager y
          monitor no entran (backend responde 403; el front tampoco ofrece la puerta). Sin
          `superadmin` a propósito: la pantalla es de la organización del gym_admin, no de la
          plataforma (decisión a confirmar por Javier, ver views_student_overview.py). Sin
          segmento de id en la ruta: el alumno se elige con `?student_id=` (mismo patrón que
          `/gym-admin/plans/assign?user_id=`), así que la misma pantalla sirve tanto al acceso
          directo desde una fila de Usuarios como a la entrada libre desde el Sidebar. */}
      <Route
        path="/gym-admin/students/overview"
        element={
          <ProtectedRoute allowedRoles={['gym_admin']}>
            <ShellRoute>
              <GymAdminStudentOverviewPage />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/gym-admin/students/:studentId/memberships"
        element={
          <ProtectedRoute allowedRoles={['gym_admin']}>
            <ShellRoute>
              <GymAdminStudentMembershipsPage />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/gym-admin/branches"
        element={
          <ProtectedRoute allowedRoles={['gym_admin', 'manager']}>
            <ShellRoute>
              <GymAdminBranchesPage />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/gym-admin/classes"
        element={
          <ProtectedRoute allowedRoles={['gym_admin', 'manager', 'monitor']}>
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
          <ProtectedRoute allowedRoles={['gym_admin', 'manager']}>
            <ShellRoute>
              <GymAdminClassTemplatesPage />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      {/* TODO unificacion: ruta de la pantalla puntual, inerte (sin acceso desde la UI). Se
          mantiene registrada a proposito; decidir en el rediseno si se elimina o se fusiona. */}
      <Route
        path="/gym-admin/classes/create"
        element={
          <ProtectedRoute allowedRoles={['gym_admin', 'manager']}>
            <ShellRoute>
              <GymAdminClassCreatePage />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/gym-admin/classes/:id/edit"
        element={
          <ProtectedRoute allowedRoles={['gym_admin', 'manager']}>
            <ShellRoute>
              <GymAdminClassEditPage />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/gym-admin/classes/:id/attendance"
        element={
          <ProtectedRoute allowedRoles={['gym_admin', 'manager', 'monitor']}>
            <ShellRoute>
              <ClassAttendancePage />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/gym-admin/classes/:id"
        element={
          <ProtectedRoute allowedRoles={['gym_admin', 'manager', 'monitor']}>
            <ShellRoute>
              <GymAdminClassDetailPage />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/gym-admin/class-types"
        element={
          <ProtectedRoute allowedRoles={['gym_admin', 'manager', 'monitor']}>
            <ShellRoute>
              <GymAdminClassTypesPage />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/gym-admin/import"
        element={
          <ProtectedRoute allowedRoles={['gym_admin']}>
            <ShellRoute>
              <GymAdminImportPage />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/gym-admin/pagos/transacciones"
        element={
          <ProtectedRoute allowedRoles={['gym_admin']}>
            <ShellRoute>
              <GymAdminPaymentsTransactionsPage />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      {/* Reportería P3.4/P3.5: SOLO gym_admin (manager/monitor/teacher/student/superadmin no
          entran; el backend responde 403 a los demás roles, pero el front tampoco debe
          ofrecerles la puerta — por eso allowedRoles no incluye 'manager' ni 'monitor'
          como sí hacen la mayoría de las rutas /gym-admin/* de arriba). Mismo gate exacto
          para las capas 2 y 3 del drilldown de Ingresos: no son pantallas nuevas de
          "otro" reporte, son la misma pantalla de Ingresos, un nivel más adentro. */}
      <Route
        path="/gym-admin/reports/revenue"
        element={
          <ProtectedRoute allowedRoles={['gym_admin']}>
            <ShellRoute>
              <GymAdminRevenueReportPage />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      {/* Capa 2 (detalle de un método): 1 solo segmento después de /revenue, ej.
          /revenue/mercadopago. Capa 3 (detalle de un pago) es la ruta de abajo, con 2
          segmentos, ej. /revenue/mercadopago/<uuid>. 'mercadopago' es a la vez un
          `method` válido acá y un `kind` válido allá, pero React Router no ambigua por
          NOMBRE de segmento sino por CANTIDAD: una URL con un segmento después de
          /revenue solo calza contra :method, una con dos solo contra :kind/:id. Por eso
          no hace falta /revenue/method/:method vs /revenue/payment/:kind/:id. */}
      <Route
        path="/gym-admin/reports/revenue/:method"
        element={
          <ProtectedRoute allowedRoles={['gym_admin']}>
            <ShellRoute>
              <GymAdminRevenueMethodPage />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/gym-admin/reports/revenue/:kind/:id"
        element={
          <ProtectedRoute allowedRoles={['gym_admin']}>
            <ShellRoute>
              <GymAdminPaymentDetailPage />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/gym-admin/reports/occupancy"
        element={
          <ProtectedRoute allowedRoles={['gym_admin']}>
            <ShellRoute>
              <GymAdminOccupancyReportPage />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/gym-admin/reports/retention"
        element={
          <ProtectedRoute allowedRoles={['gym_admin']}>
            <ShellRoute>
              <GymAdminRetentionReportPage />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/gym-admin/reports/trial-conversion"
        element={
          <ProtectedRoute allowedRoles={['gym_admin']}>
            <ShellRoute>
              <GymAdminTrialConversionReportPage />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/gym-admin/disciplines"
        element={
          <ProtectedRoute allowedRoles={['gym_admin', 'manager', 'monitor']}>
            <ShellRoute>
              <GymAdminDisciplinesPage />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/gym-admin/holidays"
        element={
          <ProtectedRoute allowedRoles={['gym_admin', 'manager', 'monitor']}>
            <ShellRoute>
              <GymAdminHolidaysPage />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/gym-admin/settings/trial-followup"
        element={
          <ProtectedRoute allowedRoles={['gym_admin']}>
            <ShellRoute>
              <GymAdminTrialFollowupPage />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/gym-admin/settings/expiry-notification"
        element={
          <ProtectedRoute allowedRoles={['gym_admin']}>
            <ShellRoute>
              <GymAdminExpiryNotificationConfigPage />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/gym-admin/settings/enrollment-fee"
        element={
          <ProtectedRoute allowedRoles={['gym_admin']}>
            <ShellRoute>
              <GymAdminEnrollmentFeeConfigPage />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/gym-admin/settings/reservation-window"
        element={
          <ProtectedRoute allowedRoles={['gym_admin']}>
            <ShellRoute>
              <GymAdminReservationWindowConfigPage />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/gym-admin/settings/attendance-edit"
        element={
          <ProtectedRoute allowedRoles={['gym_admin']}>
            <ShellRoute>
              <GymAdminAttendanceEditConfigPage />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/gym-admin/settings/teacher-payment"
        element={
          <ProtectedRoute allowedRoles={['gym_admin']}>
            <ShellRoute>
              <GymAdminTeacherPaymentConfigPage />
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
          <ProtectedRoute allowedRoles={['gym_admin', 'monitor']}>
            <ShellRoute>
              <TeacherPaymentsOverviewPage />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/gym-admin/teacher-payments/rules"
        element={
          <ProtectedRoute allowedRoles={['gym_admin', 'monitor']}>
            <ShellRoute>
              <TeacherPaymentRulesPage />
            </ShellRoute>
          </ProtectedRoute>
        }
      />

      <Route
        path="/teacher"
        element={
          <ProtectedRoute allowedRoles={['teacher', 'gym_admin']}>
            <Navigate to="/teacher/classes/upcoming" replace />
          </ProtectedRoute>
        }
      />
      <Route
        path="/teacher/dashboard"
        element={
          <ProtectedRoute allowedRoles={['teacher', 'gym_admin']}>
            <ShellRoute>
              <TeacherDashboard />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/teacher/classes"
        element={
          <ProtectedRoute allowedRoles={['teacher', 'gym_admin']}>
            <Navigate to="/teacher/classes/upcoming" replace />
          </ProtectedRoute>
        }
      />
      <Route
        path="/teacher/classes/all"
        element={
          <ProtectedRoute allowedRoles={['teacher', 'gym_admin']}>
            <Navigate to="/teacher/classes/upcoming" replace />
          </ProtectedRoute>
        }
      />
      <Route
        path="/teacher/classes/upcoming"
        element={
          <ProtectedRoute allowedRoles={['teacher', 'gym_admin']}>
            <ShellRoute>
              <TeacherClassesPage mode="upcoming" />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/teacher/classes/coverable"
        element={
          <ProtectedRoute allowedRoles={['teacher', 'gym_admin']}>
            <ShellRoute>
              <TeacherClassesPage mode="coverable" />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/teacher/classes/:id/attendance"
        element={
          <ProtectedRoute allowedRoles={['teacher', 'gym_admin']}>
            <ShellRoute>
              <ClassAttendancePage />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/teacher/classes/history"
        element={
          <ProtectedRoute allowedRoles={['teacher', 'gym_admin']}>
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
            <Navigate to="/teacher/classes/upcoming" replace />
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
        path="/student/attendance"
        element={
          <ProtectedRoute allowedRoles={['student']}>
            <ShellRoute>
              <StudentAttendanceScanPage />
            </ShellRoute>
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
        path="/student/plans/comprar"
        element={
          <ProtectedRoute allowedRoles={['student']}>
            <ShellRoute>
              <StudentBuyPlanPage />
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

      {/* Pagos MercadoPago — rutas top-level que el backend hardcodea en el callback
          OAuth (/ajustes/pagos) y en los back_urls del checkout (/pagos/resultado). */}
      <Route
        path="/ajustes/pagos"
        element={
          <ProtectedRoute allowedRoles={['gym_admin', 'superadmin']}>
            <ShellRoute>
              <GymAdminPaymentsSettingsPage />
            </ShellRoute>
          </ProtectedRoute>
        }
      />
      <Route
        path="/pagos/resultado"
        element={
          <ProtectedRoute allowedRoles={['student']}>
            <ShellRoute>
              <PaymentResultPage />
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
    </>
  )
}

