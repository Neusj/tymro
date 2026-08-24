from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .importer.views import ImporterViewSet
from .views_payments import (
    PaymentAccountView,
    PaymentCheckoutView,
    PaymentConnectView,
    PaymentDisconnectView,
    PaymentOAuthCallbackView,
    PaymentTransactionListView,
    PaymentTransactionStatusView,
    PaymentWebhookView,
)
from .views_reports import (
    OccupancyReportView,
    RetentionReportView,
    RevenuePaymentDetailView,
    RevenuePaymentsReportView,
    RevenueReportView,
    TrialConversionReportView,
)
from .views_student_overview import (
    StudentAttendanceDetailView,
    StudentConsumptionDetailView,
    StudentMembershipsDetailView,
    StudentOverviewView,
    StudentRecurringReservationsDetailView,
    StudentReservationsDetailView,
)
from .views import (
    AdvanceClassWindowsView,
    BranchViewSet,
    AttendanceQrCheckInView,
    AttendanceQrCurrentView,
    AttendanceQrPreviewView,
    AttendanceQrScreenAutoView,
    AttendanceQrScreenCodeView,
    AttendanceQrScreenSessionView,
    AttendanceQrScreenView,
    ClassTemplateViewSet,
    ClassTypeViewSet,
    DisciplineViewSet,
    EnrollmentViewSet,
    GymClassViewSet,
    HolidayViewSet,
    LoginView,
    LogoutView,
    ManualPaymentCreateView,
    MeView,
    MembershipPlanViewSet,
    OrganizationViewSet,
    PasswordResetConfirmView,
    PasswordResetRequestView,
    PersonalizedClassQrView,
    PersonViewSet,
    PushPreferenceView,
    PushSubscriptionView,
    PublicInviteValidateView,
    PublicRegisterView,
    PublicTrialBookView,
    PublicTrialClassesView,
    PublicVerifyEmailView,
    RecurringEnrollmentViewSet,
    ResendVerificationView,
    TeacherPaymentRecordViewSet,
    TeacherPaymentRuleViewSet,
    UserViewSet,
    dashboard_summary,
    health_check,
)

router = DefaultRouter()
router.register('organizations', OrganizationViewSet)
router.register('branches', BranchViewSet)
router.register('users', UserViewSet)
router.register('people', PersonViewSet)
router.register('class-types', ClassTypeViewSet)
router.register('disciplines', DisciplineViewSet)
router.register('classes', GymClassViewSet)
router.register('class-templates', ClassTemplateViewSet)
router.register('holidays', HolidayViewSet)
router.register('recurring-enrollments', RecurringEnrollmentViewSet)
router.register('enrollments', EnrollmentViewSet)
router.register('plans', MembershipPlanViewSet)
router.register('teacher-payment-rules', TeacherPaymentRuleViewSet)
router.register('teacher-payments', TeacherPaymentRecordViewSet, basename='teacher-payments')
router.register('imports', ImporterViewSet, basename='imports')

urlpatterns = [
    path('health/', health_check),
    path('login/', LoginView.as_view()),
    path('logout/', LogoutView.as_view()),
    path('me/', MeView.as_view()),
    path('resend-verification/', ResendVerificationView.as_view()),
    path('password-reset/', PasswordResetRequestView.as_view()),
    path('password-reset/confirm/', PasswordResetConfirmView.as_view()),
    path('push/preferences/', PushPreferenceView.as_view()),
    path('push/subscriptions/', PushSubscriptionView.as_view()),
    path('public/invite/', PublicInviteValidateView.as_view()),
    path('public/register/', PublicRegisterView.as_view()),
    path('public/verify-email/', PublicVerifyEmailView.as_view()),
    path('public/trial-classes/', PublicTrialClassesView.as_view()),
    path('public/trial/book/', PublicTrialBookView.as_view()),
    path('dashboard/', dashboard_summary),
    path('attendance-qr/current/', AttendanceQrCurrentView.as_view()),
    path('attendance-qr/preview/', AttendanceQrPreviewView.as_view()),
    path('attendance-qr/check-in/', AttendanceQrCheckInView.as_view()),
    path('attendance-qr/screen/', AttendanceQrScreenView.as_view()),
    path('attendance-qr/screen-auto/', AttendanceQrScreenAutoView.as_view()),
    path('attendance-qr/screen-code/', AttendanceQrScreenCodeView.as_view()),
    path('attendance-qr/screen-session/', AttendanceQrScreenSessionView.as_view()),
    path('personalized-classes/qr/', PersonalizedClassQrView.as_view()),
    path('my-recurring-enrollments/', RecurringEnrollmentViewSet.as_view({'get': 'my_recurring'})),
    path('payments/connect/', PaymentConnectView.as_view(), name='payments-connect'),
    path('payments/oauth/callback/', PaymentOAuthCallbackView.as_view(), name='payments-oauth-callback'),
    path('payments/account/', PaymentAccountView.as_view(), name='payments-account'),
    path('payments/disconnect/', PaymentDisconnectView.as_view(), name='payments-disconnect'),
    path('payments/checkout/', PaymentCheckoutView.as_view(), name='payments-checkout'),
    path('payments/transactions/', PaymentTransactionListView.as_view(),
         name='payments-transactions-list'),
    path('payments/transactions/<uuid:pk>/status/', PaymentTransactionStatusView.as_view(),
         name='payments-transaction-status'),
    path('payments/webhook/', PaymentWebhookView.as_view(), name='payments-webhook'),
    # Cobro registrado a mano por el gimnasio. NO va bajo `payments/`: eso es la plomería del
    # proveedor (checkout, OAuth, webhook) y esto no toca ningún proveedor. Solo POST.
    path('manual-payments/', ManualPaymentCreateView.as_view(), name='manual-payments-create'),
    # Disparo manual del robot de la ventana rodante (el mismo del cron diario). Ruta PLANA y no
    # una acción del router: dispara un job de toda la organización —extiende series, consolida
    # estados y poda clases— y no cuelga de ningún recurso en particular. Colgarlo de
    # `class-templates/<pk>/` o de `classes/` mentiría sobre su alcance. Solo POST: no es una
    # lectura, mueve saldo y borra filas.
    path('advance-class-windows/', AdvanceClassWindowsView.as_view(), name='advance-class-windows'),
    # Reportería (P3.4). Namespace propio `reports/` y rutas PLANAS, no acciones del router:
    # un reporte no es un recurso REST (no se crea, no se borra, no tiene detalle) sino una
    # LECTURA AGREGADA de varias tablas a la vez. Colgarlo de `payments/` o de `classes/`
    # mentiría sobre su alcance, y `payments/` además es la plomería del proveedor.
    # Solo GET. El export usa el MISMO endpoint con `?export=csv|xlsx`.
    path('reports/revenue/', RevenueReportView.as_view(), name='reports-revenue'),
    # Las dos capas de zoom del reporte de ingresos: el listado de los cobros de UN medio y la
    # ficha de un pago. Cuelgan de `reports/revenue/` y no de una raíz propia porque son ese
    # mismo reporte con más detalle -mismos totales, mismo permiso-, no otro recurso.
    #
    # El detalle usa `<str:...>` en los DOS segmentos a propósito, y no `<int:>`/`<uuid:>`: con
    # converters, un id malformado no matchearía la ruta y saldría un 404 de URLconf, que dice
    # "acá no hay nada" cuando lo cierto es "ese id está mal escrito". La view valida la forma y
    # devuelve 400, y reserva el 404 para el id AJENO (anti-oráculo). Además `<int:>` igual deja
    # pasar enteros fuera del rango de bigint, que es justo el que revienta con 500 en Postgres.
    path('reports/revenue/payments/', RevenuePaymentsReportView.as_view(),
         name='reports-revenue-payments'),
    path('reports/revenue/payments/<str:kind>/<str:payment_id>/',
         RevenuePaymentDetailView.as_view(), name='reports-revenue-payment-detail'),
    path('reports/occupancy/', OccupancyReportView.as_view(), name='reports-occupancy'),
    # P3.4 · parte 2: los dos reportes de PERSONAS (vencimientos/renovaciones y conversión de
    # la clase de prueba). Misma plomería que los tres de arriba, rutas planas por el mismo
    # motivo.
    path('reports/retention/', RetentionReportView.as_view(), name='reports-retention'),
    path('reports/trial-conversion/', TrialConversionReportView.as_view(),
         name='reports-trial-conversion'),
    # Vista integral de UN alumno (P4 · Feature B): membresías, consumo, asistencia,
    # reservas y recurrencias en una sola lectura agregada. Ruta PLANA, mismo motivo que
    # `reports/`: no es un recurso REST (no se crea, no se borra, no tiene un ViewSet detrás)
    # sino una LECTURA AGREGADA de varias tablas para UN alumno. Solo GET, solo `gym_admin`
    # (ver `views_student_overview.py`).
    #
    # `<str:student_id>` y NO `<int:>`, a propósito, mismo motivo que
    # `reports/revenue/payments/<str:kind>/<str:payment_id>/` unas líneas arriba: con
    # converter, un id malformado no matchearía la ruta y saldría un 404 de URLconf que dice
    # "acá no hay nada" cuando lo cierto es "ese id está mal escrito". Además `<int:>` deja
    # pasar enteros fuera del rango de bigint, que revientan con 500 en PostgreSQL. La view
    # valida la forma y devuelve 400; el 404 queda reservado para el alumno ajeno/inexistente
    # (anti-oráculo).
    path('students/<str:student_id>/overview/', StudentOverviewView.as_view(),
         name='student-overview'),
    path('students/<str:student_id>/reservations/', StudentReservationsDetailView.as_view(),
         name='student-reservations-detail'),
    path('students/<str:student_id>/attendance/', StudentAttendanceDetailView.as_view(),
         name='student-attendance-detail'),
    path('students/<str:student_id>/consumption/', StudentConsumptionDetailView.as_view(),
         name='student-consumption-detail'),
    path('students/<str:student_id>/memberships/', StudentMembershipsDetailView.as_view(),
         name='student-memberships-detail'),
    path('students/<str:student_id>/recurring-reservations/',
         StudentRecurringReservationsDetailView.as_view(),
         name='student-recurring-reservations-detail'),
    path('', include(router.urls)),
]
