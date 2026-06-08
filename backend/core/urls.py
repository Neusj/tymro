from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    BranchViewSet,
    AttendanceQrCheckInView,
    AttendanceQrCurrentView,
    AttendanceQrPreviewView,
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
    MeView,
    MembershipPlanViewSet,
    OrganizationViewSet,
    PasswordResetConfirmView,
    PasswordResetRequestView,
    PersonViewSet,
    RecurringEnrollmentViewSet,
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

urlpatterns = [
    path('health/', health_check),
    path('login/', LoginView.as_view()),
    path('logout/', LogoutView.as_view()),
    path('me/', MeView.as_view()),
    path('password-reset/', PasswordResetRequestView.as_view()),
    path('password-reset/confirm/', PasswordResetConfirmView.as_view()),
    path('dashboard/', dashboard_summary),
    path('attendance-qr/current/', AttendanceQrCurrentView.as_view()),
    path('attendance-qr/preview/', AttendanceQrPreviewView.as_view()),
    path('attendance-qr/check-in/', AttendanceQrCheckInView.as_view()),
    path('attendance-qr/screen/', AttendanceQrScreenView.as_view()),
    path('attendance-qr/screen-code/', AttendanceQrScreenCodeView.as_view()),
    path('attendance-qr/screen-session/', AttendanceQrScreenSessionView.as_view()),
    path('my-recurring-enrollments/', RecurringEnrollmentViewSet.as_view({'get': 'my_recurring'})),
    path('', include(router.urls)),
]
