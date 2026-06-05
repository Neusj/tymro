from django.contrib.auth import authenticate, get_user_model
from datetime import datetime, timedelta
from uuid import uuid4

from django.conf import settings
from django.core import signing
from django.db import models, transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet

from .models import (
    Attendance,
    Branch,
    ClassTemplate,
    ClassType,
    Discipline,
    Enrollment,
    GymClass,
    Holiday,
    Plan,
    Organization,
    generate_attendance_screen_code,
    generate_attendance_screen_session_code,
    Person,
    RecurringEnrollment,
    StudentPlan,
    TeacherPaymentRecord,
    TeacherPaymentRule,
)
from .permissions import IsSuperAdminOrGymAdmin
from .serializers import (
    AttendanceBulkWriteSerializer,
    AttendanceSerializer,
    BranchSerializer,
    ClassTemplateSerializer,
    ClassTypeSerializer,
    CustomUserSerializer,
    DisciplineSerializer,
    EnrollmentSerializer,
    GymClassDetailSerializer,
    GymClassSerializer,
    HolidaySerializer,
    OrganizationSerializer,
    PlanSerializer,
    PersonSerializer,
    RecurringEnrollmentSerializer,
    StudentPlanAssignSerializer,
    StudentPlanSerializer,
    TeacherPaymentRuleAssignmentsUpdateSerializer,
    TeacherPaymentRecordSerializer,
    TeacherPaymentRuleSerializer,
)
from .services.recurrence import (
    activate_template,
    apply_template_updates_to_future_instances,
    can_delete_template,
    cancel_future_instances_for_template,
    create_enrollments_for_recurring_subscription,
    delete_template_safely,
    generate_instances_for_template_range,
    reactivate_future_cancelled_instances_for_template,
)
from .services.class_dashboard import get_class_dashboard_summary
from .services.reservations import (
    ReservationRuleError,
    cancel_enrollment_with_refund,
    cancel_future_recurring_enrollments,
    consume_student_plan_for_enrollment,
    get_active_student_plan,
    get_enrollment_student_plan,
    reserve_student_in_class,
    rollback_consumption_for_enrollment,
    should_refund_consumption,
    validate_student_plan_for_reservation,
)
from .services.teacher_payments import calculate_teacher_payment

User = get_user_model()
QR_ATTENDANCE_SALT = 'tymro.attendance.qr'
QR_TOKEN_TTL_SECONDS = 10
ATTENDANCE_SCREEN_SESSION_TTL_HOURS = 8
QR_WINDOW_BEFORE_MINUTES = 10
QR_WINDOW_AFTER_MINUTES = 15


def _user_role(user):
    return getattr(user, 'role', None)


def _is_superadmin(user):
    return _user_role(user) == User.Role.SUPERADMIN


def _is_gym_admin(user):
    return _user_role(user) == User.Role.GYM_ADMIN


def _is_teacher(user):
    return _user_role(user) == User.Role.TEACHER


def _is_student(user):
    return _user_role(user) == User.Role.STUDENT


def _sync_class_statuses(base_queryset=None):
    queryset = base_queryset if base_queryset is not None else GymClass.objects.all()
    candidates = queryset.filter(status__in=[GymClass.Status.SCHEDULED, GymClass.Status.IN_PROGRESS])
    for gym_class in candidates:
        gym_class.refresh_status_from_schedule(save=True)
        if gym_class.status in {GymClass.Status.COMPLETED, GymClass.Status.COMPLETED_EARLY}:
            calculate_teacher_payment(gym_class)


def _can_close_or_cancel(user, gym_class):
    if _is_superadmin(user):
        return True
    if _is_gym_admin(user) and gym_class.organization_id == user.organization_id:
        return True
    if _is_teacher(user) and gym_class.teacher_id == user.id:
        return True
    return False


def _can_manage_org_resource(user, organization_id):
    if _is_superadmin(user):
        return True
    if _is_gym_admin(user) and user.organization_id == organization_id:
        return True
    return False


def _register_teacher_payment_for_class(gym_class):
    if not gym_class:
        return
    if gym_class.status not in {GymClass.Status.COMPLETED, GymClass.Status.COMPLETED_EARLY}:
        return
    calculate_teacher_payment(gym_class)


def _parse_bool(value, default=True):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {'1', 'true', 'yes', 'on'}


def _apply_ordering(queryset, raw_ordering, allowed_map, default_ordering):
    requested = str(raw_ordering or '').strip()
    if not requested:
        return queryset.order_by(*default_ordering)

    desc = requested.startswith('-')
    key = requested[1:] if desc else requested
    model_field = allowed_map.get(key)
    if not model_field:
        return queryset.order_by(*default_ordering)
    final_field = f'-{model_field}' if desc else model_field
    return queryset.order_by(final_field, *default_ordering)


def _safe_int_setting(name, default=0):
    raw = getattr(settings, name, default)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = default
    return max(0, value)


def _student_can_modify_before_class(start_datetime, hours):
    if not start_datetime:
        return False, 'No se pudo determinar la fecha de la clase.'
    now = timezone.now()
    if start_datetime <= now:
        return False, 'La clase ya comenzo o termino y no admite cambios.'
    if hours <= 0:
        return True, ''
    cutoff = start_datetime - timedelta(hours=hours)
    if now > cutoff:
        return False, f'Ya no puedes modificar esta accion con menos de {hours} hora(s) de anticipacion.'
    return True, ''


def _student_can_cancel_enrollment(enrollment):
    if enrollment.status != 'active':
        return False, 'La reserva ya esta cancelada.'
    if enrollment.gym_class.status == GymClass.Status.CANCELLED:
        return True, ''
    if enrollment.gym_class.status in {GymClass.Status.COMPLETED, GymClass.Status.COMPLETED_EARLY}:
        return False, 'La clase esta cerrada y ya no se puede modificar la reserva.'
    hours = _safe_int_setting('STUDENT_CANCEL_DEADLINE_HOURS', 0)
    return _student_can_modify_before_class(enrollment.gym_class.start_datetime, hours)


def _student_can_manage_recurring(recurring_enrollment):
    now = timezone.now()
    next_class = recurring_enrollment.class_template.instances.filter(start_datetime__gt=now).exclude(
        status__in=[GymClass.Status.CANCELLED, GymClass.Status.COMPLETED, GymClass.Status.COMPLETED_EARLY]
    )
    next_class = next_class.filter(start_datetime__date__gte=recurring_enrollment.start_date)
    if recurring_enrollment.end_date:
        next_class = next_class.filter(start_datetime__date__lte=recurring_enrollment.end_date)
    next_instance = next_class.order_by('start_datetime').first()
    if not next_instance:
        return True, ''
    hours = _safe_int_setting('STUDENT_RECURRING_CHANGE_DEADLINE_HOURS', 0)
    return _student_can_modify_before_class(next_instance.start_datetime, hours)


def _get_active_student_plan(student, on_date=None):
    return get_active_student_plan(student, on_date=on_date)


def _get_active_student_plan_map(student_ids, on_date=None):
    target_date = on_date or timezone.localdate()
    if not student_ids:
        return {}

    active_plans = (
        StudentPlan.objects.filter(
            user_id__in=student_ids,
            is_active=True,
            start_date__lte=target_date,
            end_date__gte=target_date,
        )
        .select_related('plan')
        .order_by('user_id', '-start_date', '-id')
    )

    plan_by_user = {}
    for student_plan in active_plans:
        if student_plan.user_id not in plan_by_user:
            plan_by_user[student_plan.user_id] = student_plan
    return plan_by_user


def _get_latest_student_plan_map(student_ids):
    if not student_ids:
        return {}

    plans = (
        StudentPlan.objects.filter(user_id__in=student_ids)
        .select_related('plan')
        .order_by('user_id', '-end_date', '-start_date', '-id')
    )

    plan_by_user = {}
    for student_plan in plans:
        if student_plan.user_id not in plan_by_user:
            plan_by_user[student_plan.user_id] = student_plan
    return plan_by_user


def _plan_status_payload(student_plan, today=None):
    if not student_plan:
        return {
            'plan_status': 'no_plan',
            'plan_status_label': 'Sin plan',
            'plan_days_to_expiry': None,
            'plan_expiry_alert_level': 'neutral',
            'plan_expiry_alert_message': 'Sin plan vigente',
        }

    target_date = today or timezone.localdate()
    days_to_expiry = None
    if student_plan.end_date:
        days_to_expiry = (student_plan.end_date - target_date).days

    if student_plan.end_date and student_plan.end_date < target_date:
        return {
            'plan_status': 'expired',
            'plan_status_label': 'Vencido',
            'plan_days_to_expiry': days_to_expiry,
            'plan_expiry_alert_level': 'expired',
            'plan_expiry_alert_message': 'Vencido',
        }

    if student_plan.start_date and student_plan.start_date > target_date:
        return {
            'plan_status': 'upcoming',
            'plan_status_label': 'Por iniciar',
            'plan_days_to_expiry': days_to_expiry,
            'plan_expiry_alert_level': 'safe',
            'plan_expiry_alert_message': 'Por iniciar',
        }

    is_vigente = bool(student_plan.is_active)
    if is_vigente:
        if days_to_expiry is None:
            alert_level = 'neutral'
            message = 'Sin fecha de vencimiento'
        elif days_to_expiry <= 5:
            alert_level = 'danger'
            message = 'Vence pronto'
        elif days_to_expiry <= 12:
            alert_level = 'warning'
            message = 'Por vencer'
        else:
            alert_level = 'safe'
            message = f'{days_to_expiry} dias vigentes'
        return {
            'plan_status': 'active',
            'plan_status_label': 'Vigente',
            'plan_days_to_expiry': days_to_expiry,
            'plan_expiry_alert_level': alert_level,
            'plan_expiry_alert_message': message,
        }

    return {
        'plan_status': 'inactive',
        'plan_status_label': 'Inactivo',
        'plan_days_to_expiry': days_to_expiry,
        'plan_expiry_alert_level': 'neutral',
        'plan_expiry_alert_message': 'No vigente',
    }


def _validate_student_plan_for_reservation(student):
    try:
        return validate_student_plan_for_reservation(student)
    except ReservationRuleError as exc:
        raise ValidationError({'detail': 'No tienes clases disponibles o plan activo'})


def _consume_student_plan_for_enrollment(enrollment, student_plan):
    return consume_student_plan_for_enrollment(enrollment, student_plan)


def _rollback_consumption_for_enrollment(enrollment, student_plan):
    return rollback_consumption_for_enrollment(enrollment, student_plan=student_plan)


def _get_enrollment_student_plan(enrollment):
    return get_enrollment_student_plan(enrollment)


def _should_refund_consumption(enrollment, now=None):
    return should_refund_consumption(enrollment, now=now)


@api_view(['GET'])
@permission_classes([AllowAny])
def health_check(request):
    return Response({'message': 'TYMRO backend running', 'status': 'ok'})


@api_view(['GET'])
def dashboard_summary(request):
    _sync_class_statuses()
    user = request.user

    if _is_superadmin(user):
        data = {
            'organizations': Organization.objects.count(),
            'branches': Branch.objects.count(),
            'teachers': User.objects.filter(role=User.Role.TEACHER).count(),
            'students': User.objects.filter(role=User.Role.STUDENT).count(),
            'gym_admins': User.objects.filter(role=User.Role.GYM_ADMIN).count(),
            'users': User.objects.count(),
        }
    elif _is_gym_admin(user) and user.organization_id:
        data = {
            'organization': user.organization.name,
            'branches': Branch.objects.filter(organization=user.organization).count(),
            'teachers': User.objects.filter(role=User.Role.TEACHER, organization=user.organization).count(),
            'students': User.objects.filter(role=User.Role.STUDENT, organization=user.organization).count(),
            'users': User.objects.filter(organization=user.organization).count(),
        }
    else:
        data = {
            'organization': user.organization.name if user.organization else None,
            'branch': user.branch.name if user.branch else None,
            'is_active_member': getattr(user, 'is_active_member', False),
        }

    return Response(data)


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        username = request.data.get('username', '').strip()
        password = request.data.get('password', '')

        if not username or not password:
            return Response({'detail': 'username y password son requeridos.'}, status=status.HTTP_400_BAD_REQUEST)

        user = authenticate(request, username=username, password=password)
        if not user:
            return Response({'detail': 'Credenciales inválidas.'}, status=status.HTTP_400_BAD_REQUEST)

        token, _ = Token.objects.get_or_create(user=user)
        serialized_user = CustomUserSerializer(user, context={'request': request}).data
        return Response(
            {
                'token': token.key,
                'user': serialized_user,
                'role': user.role,
                'organization': user.organization_id,
                'branch': user.branch_id,
            }
        )


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        Token.objects.filter(user=request.user).delete()
        return Response({'detail': 'Sesión cerrada.'})


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = CustomUserSerializer(request.user, context={'request': request})
        return Response(serializer.data)


def _build_qr_token(organization_id):
    now = timezone.now()
    expires_at = now + timedelta(seconds=QR_TOKEN_TTL_SECONDS)
    payload = {
        'organization_id': organization_id,
        'issued_at': now.isoformat(),
        'expires_at': expires_at.isoformat(),
        'nonce': uuid4().hex,
    }
    return signing.dumps(payload, salt=QR_ATTENDANCE_SALT), expires_at


def _normalize_attendance_screen_code(value):
    return str(value or '').strip().upper().replace(' ', '').replace('-', '')


def _get_public_attendance_organization(raw_code):
    code = _normalize_attendance_screen_code(raw_code)
    if not code:
        raise ValidationError({'code': 'Codigo temporal de pantalla requerido.'})
    organization = Organization.objects.filter(attendance_screen_session_code=code, is_active=True).first()
    if not organization:
        raise ValidationError({'code': 'Codigo temporal de pantalla invalido.'})
    expires_at = organization.attendance_screen_session_expires_at
    if not expires_at or timezone.now() > expires_at:
        raise ValidationError({'code': 'La sesión de pantalla expiró.'})
    return organization


def _attendance_screen_session_payload(request, organization):
    expires_at = organization.attendance_screen_session_expires_at
    seconds_left = 0
    if expires_at:
        seconds_left = max(0, int((expires_at - timezone.now()).total_seconds()))
    return {
        'organization_name': organization.name,
        'attendance_screen_code': organization.attendance_screen_code,
        'attendance_screen_session_code': organization.attendance_screen_session_code,
        'attendance_screen_session_expires_at': expires_at,
        'attendance_screen_session_expires_in_seconds': seconds_left,
        'attendance_screen_session_ttl_hours': ATTENDANCE_SCREEN_SESSION_TTL_HOURS,
        'attendance_screen_path': '/attendance/screen',
        'attendance_screen_url': request.build_absolute_uri('/attendance/screen'),
    }


def _start_attendance_screen_session(organization):
    code = generate_attendance_screen_session_code()
    while Organization.objects.filter(attendance_screen_session_code=code).exclude(id=organization.id).exists():
        code = generate_attendance_screen_session_code()
    organization.attendance_screen_session_code = code
    organization.attendance_screen_session_expires_at = timezone.now() + timedelta(hours=ATTENDANCE_SCREEN_SESSION_TTL_HOURS)
    organization.save(
        update_fields=[
            'attendance_screen_session_code',
            'attendance_screen_session_expires_at',
            'updated_at',
        ]
    )
    return organization


def _attendance_qr_payload(request, organization):
    token, expires_at = _build_qr_token(organization.id)
    check_in_path = f'/attendance/check-in?token={token}'
    return {
        'organization_name': organization.name,
        'token': token,
        'expires_at': expires_at,
        'expires_in_seconds': QR_TOKEN_TTL_SECONDS,
        'check_in_path': check_in_path,
        'check_in_url': request.build_absolute_uri(check_in_path),
    }


def _load_qr_token(raw_token):
    if not raw_token:
        raise ValidationError({'token': 'Token QR requerido.'})
    try:
        payload = signing.loads(raw_token, salt=QR_ATTENDANCE_SALT)
    except signing.BadSignature:
        raise ValidationError({'token': 'Token QR inválido.'})

    expires_at = payload.get('expires_at')
    try:
        expires_at = datetime.fromisoformat(expires_at)
    except (TypeError, ValueError):
        raise ValidationError({'token': 'Token QR inválido.'})
    if timezone.is_naive(expires_at):
        expires_at = timezone.make_aware(expires_at, timezone.get_current_timezone())
    if timezone.now() > expires_at:
        raise ValidationError({'token': 'El QR expiró. Escanea el código actualizado.'})

    organization_id = payload.get('organization_id')
    if not organization_id:
        raise ValidationError({'token': 'Token QR inválido.'})
    payload['organization_id'] = int(organization_id)
    payload['expires_at'] = expires_at
    return payload


def _attendance_window(gym_class):
    return (
        gym_class.start_datetime - timedelta(minutes=QR_WINDOW_BEFORE_MINUTES),
        gym_class.start_datetime + timedelta(minutes=QR_WINDOW_AFTER_MINUTES),
    )


def _serialize_qr_class(gym_class):
    teacher = gym_class.teacher
    teacher_name = ''
    if teacher:
        teacher_name = f'{teacher.first_name} {teacher.last_name}'.strip() or teacher.username
    return {
        'id': gym_class.id,
        'name': gym_class.name,
        'discipline': gym_class.discipline.name if gym_class.discipline else '',
        'class_type': gym_class.class_type.name if gym_class.class_type else '',
        'teacher': teacher_name,
        'start_datetime': gym_class.start_datetime,
        'end_datetime': gym_class.end_datetime,
        'branch': gym_class.branch.name if gym_class.branch else '',
    }


def _find_qr_candidate(student, organization_id):
    now = timezone.now()
    today = timezone.localdate(now)
    enrollments = (
        Enrollment.objects.select_related(
            'gym_class',
            'gym_class__teacher',
            'gym_class__discipline',
            'gym_class__class_type',
            'gym_class__branch',
        )
        .filter(
            student=student,
            status='active',
            gym_class__organization_id=organization_id,
            gym_class__start_datetime__date=today,
        )
        .exclude(gym_class__status__in=[GymClass.Status.CANCELLED, GymClass.Status.COMPLETED_EARLY])
        .order_by('gym_class__start_datetime', 'id')
    )

    next_window = None
    for enrollment in enrollments:
        gym_class = enrollment.gym_class
        window_start, window_end = _attendance_window(gym_class)
        if window_start <= now <= window_end:
            return gym_class, None
        if now < window_start and (not next_window or window_start < next_window[0]):
            next_window = (window_start, gym_class)
    return None, next_window


def _qr_preview_payload(student, organization_id):
    if student.organization_id != organization_id:
        return {
            'status': 'wrong_organization',
            'detail': 'Este QR pertenece a otro gimnasio.',
            'class': None,
            'next_check_in_at': None,
        }

    gym_class, next_window = _find_qr_candidate(student, organization_id)
    if not gym_class:
        payload = {
            'status': 'no_available_class',
            'detail': 'No tienes clases disponibles para marcar asistencia en este momento.',
            'class': None,
            'next_check_in_at': None,
        }
        if next_window:
            payload['next_check_in_at'] = next_window[0]
            payload['next_class'] = _serialize_qr_class(next_window[1])
        return payload

    attendance = Attendance.objects.filter(gym_class=gym_class, student=student).first()
    already_registered = bool(attendance and attendance.status == Attendance.Status.PRESENT)
    return {
        'status': 'already_registered' if already_registered else 'ready',
        'detail': 'Tu asistencia ya fue registrada para esta clase.' if already_registered else '',
        'class': _serialize_qr_class(gym_class),
        'attendance_status': attendance.status if attendance else None,
        'attendance_source': attendance.source if attendance else None,
        'next_check_in_at': None,
    }


class AttendanceQrCurrentView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if not _is_gym_admin(user) or not user.organization_id:
            raise PermissionDenied('Solo Gym Admin puede generar QR de asistencia.')
        payload = _attendance_qr_payload(request, user.organization)
        payload.update(_attendance_screen_session_payload(request, user.organization))
        return Response(payload)


class AttendanceQrScreenView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        organization = _get_public_attendance_organization(request.data.get('code'))
        return Response(_attendance_qr_payload(request, organization))


class AttendanceQrScreenCodeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if not _is_gym_admin(user) or not user.organization_id:
            raise PermissionDenied('Solo Gym Admin puede gestionar el codigo de pantalla.')
        return Response(_attendance_screen_session_payload(request, user.organization))

    def post(self, request):
        user = request.user
        if not _is_gym_admin(user) or not user.organization_id:
            raise PermissionDenied('Solo Gym Admin puede regenerar el codigo de pantalla.')

        organization = user.organization
        code = generate_attendance_screen_code()
        while Organization.objects.filter(attendance_screen_code=code).exclude(id=organization.id).exists():
            code = generate_attendance_screen_code()
        organization.attendance_screen_code = code
        organization.save(update_fields=['attendance_screen_code', 'updated_at'])
        return Response(_attendance_screen_session_payload(request, organization))


class AttendanceQrScreenSessionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        if not _is_gym_admin(user) or not user.organization_id:
            raise PermissionDenied('Solo Gym Admin puede iniciar la pantalla de recepcion.')
        organization = _start_attendance_screen_session(user.organization)
        return Response(_attendance_screen_session_payload(request, organization))


class AttendanceQrPreviewView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _is_student(request.user):
            raise PermissionDenied('Solo alumnos pueden marcar asistencia por QR.')
        payload = _load_qr_token(request.query_params.get('token'))
        return Response(_qr_preview_payload(request.user, payload['organization_id']))


class AttendanceQrCheckInView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not _is_student(request.user):
            raise PermissionDenied('Solo alumnos pueden marcar asistencia por QR.')
        payload = _load_qr_token(request.data.get('token'))
        preview = _qr_preview_payload(request.user, payload['organization_id'])
        if preview['status'] == 'already_registered':
            return Response(preview)
        if preview['status'] != 'ready' or not preview.get('class'):
            return Response(preview, status=status.HTTP_400_BAD_REQUEST)

        gym_class = GymClass.objects.get(id=preview['class']['id'])
        now = timezone.now()
        attendance, created = Attendance.objects.update_or_create(
            gym_class=gym_class,
            student=request.user,
            defaults={
                'status': Attendance.Status.PRESENT,
                'source': Attendance.Source.QR,
                'marked_by': request.user,
                'marked_at': now,
                'checked_at': now,
            },
        )
        response_payload = _qr_preview_payload(request.user, payload['organization_id'])
        response_payload['status'] = 'registered'
        response_payload['detail'] = 'Tu asistencia fue registrada correctamente.'
        response_payload['attendance_id'] = attendance.id
        response_payload['created'] = created
        return Response(response_payload)


class OrganizationViewSet(ModelViewSet):
    queryset = Organization.objects.all()
    serializer_class = OrganizationSerializer

    def get_queryset(self):
        user = self.request.user

        if _is_superadmin(user):
            return Organization.objects.all()
        if user.organization_id:
            return Organization.objects.filter(id=user.organization_id)
        return Organization.objects.none()

    def perform_create(self, serializer):
        if not _is_superadmin(self.request.user):
            raise PermissionDenied('Solo superadmin puede crear organizaciones.')
        serializer.save()

    def perform_update(self, serializer):
        if not _is_superadmin(self.request.user):
            raise PermissionDenied('Solo superadmin puede editar organizaciones.')
        serializer.save()

    def perform_destroy(self, instance):
        if not _is_superadmin(self.request.user):
            raise PermissionDenied('Solo superadmin puede eliminar organizaciones.')
        instance.delete()


class BranchViewSet(ModelViewSet):
    queryset = Branch.objects.select_related('organization').all()
    serializer_class = BranchSerializer

    def get_queryset(self):
        user = self.request.user

        if _is_superadmin(user):
            return self.queryset
        if user.organization_id:
            return self.queryset.filter(organization_id=user.organization_id)
        return Branch.objects.none()

    def perform_create(self, serializer):
        user = self.request.user

        if _is_superadmin(user):
            serializer.save()
            return

        if _is_gym_admin(user):
            organization = serializer.validated_data.get('organization') or user.organization
            if not organization or organization.id != user.organization_id:
                raise PermissionDenied('Solo puedes crear sucursales de tu organización.')
            serializer.save(organization=user.organization)
            return

        raise PermissionDenied('No tienes permisos para crear sucursales.')

    def perform_update(self, serializer):
        user = self.request.user
        branch = self.get_object()

        if _is_superadmin(user):
            serializer.save()
            return

        if _is_gym_admin(user) and branch.organization_id == user.organization_id:
            organization = serializer.validated_data.get('organization', branch.organization)
            if organization.id != user.organization_id:
                raise PermissionDenied('No puedes mover sucursales fuera de tu organización.')
            serializer.save()
            return

        raise PermissionDenied('No tienes permisos para editar esta sucursal.')

    def perform_destroy(self, instance):
        user = self.request.user
        if _is_superadmin(user):
            instance.delete()
            return
        if _is_gym_admin(user) and instance.organization_id == user.organization_id:
            instance.delete()
            return
        raise PermissionDenied('No tienes permisos para eliminar esta sucursal.')


class UserViewSet(ModelViewSet):
    queryset = User.objects.select_related('organization', 'branch').all()
    serializer_class = CustomUserSerializer

    def get_queryset(self):
        user = self.request.user
        queryset = self.queryset

        if _is_superadmin(user):
            organization_id = self.request.query_params.get('organization_id')
            role = self.request.query_params.get('role')

            if self.action == 'list':
                if not organization_id:
                    return queryset.none()
                queryset = queryset.filter(organization_id=organization_id)

            if role:
                queryset = queryset.filter(role=role)
            return queryset

        if _is_gym_admin(user) and user.organization_id:
            role = self.request.query_params.get('role')
            queryset = queryset.filter(organization_id=user.organization_id)
            if role:
                queryset = queryset.filter(role=role)
            return queryset

        if _is_teacher(user) or _is_student(user):
            return queryset.filter(id=user.id)
        return queryset.none()

    def list(self, request, *args, **kwargs):
        if _is_teacher(request.user) or _is_student(request.user):
            raise PermissionDenied('No tienes acceso al listado general de usuarios.')
        if _is_superadmin(request.user) and not request.query_params.get('organization_id'):
            raise PermissionDenied('Debes filtrar por organization_id para listar usuarios como superadmin.')
        return super().list(request, *args, **kwargs)

    def _validate_write_permissions(self, data=None, instance=None):
        user = self.request.user
        data = data or {}
        requested_role = data.get('role')
        requested_organization = data.get('organization')

        if _is_superadmin(user):
            return

        if not _is_gym_admin(user):
            raise PermissionDenied('No tienes permisos para gestionar usuarios.')

        if instance and instance.role == User.Role.SUPERADMIN:
            raise PermissionDenied('No puedes gestionar usuarios superadmin.')

        if instance and instance.role == User.Role.GYM_ADMIN:
            raise PermissionDenied('No puedes gestionar usuarios gym_admin.')

        if requested_role == User.Role.SUPERADMIN:
            raise PermissionDenied('No puedes crear o editar superadmins.')

        if requested_role and requested_role not in (User.Role.GYM_ADMIN, User.Role.TEACHER, User.Role.STUDENT):
            raise PermissionDenied('Rol no permitido para gym_admin.')

        if requested_role == User.Role.GYM_ADMIN:
            raise PermissionDenied('Gym admin no puede crear otros gym_admin.')

        if requested_organization is not None:
            try:
                requested_organization_id = int(requested_organization)
            except (TypeError, ValueError):
                raise PermissionDenied('Organización inválida.')

            if requested_organization_id != user.organization_id:
                raise PermissionDenied('Solo puedes gestionar usuarios de tu organización.')

        if instance and instance.organization_id != user.organization_id:
            raise PermissionDenied('Solo puedes gestionar usuarios de tu organización.')

        requested_branch = data.get('branch')
        if requested_branch in (None, ''):
            return

        try:
            branch = Branch.objects.select_related('organization').get(pk=int(requested_branch))
        except (TypeError, ValueError, Branch.DoesNotExist):
            raise PermissionDenied('Sucursal inválida.')

        if branch.organization_id != user.organization_id:
            raise PermissionDenied('Solo puedes asignar sucursales de tu organización.')

    def perform_create(self, serializer):
        self._validate_write_permissions(self.request.data)
        user = self.request.user
        save_kwargs = {}

        if _is_gym_admin(user):
            save_kwargs['organization'] = user.organization

        created_user = serializer.save(**save_kwargs)

        if created_user.role == User.Role.SUPERADMIN:
            created_user.is_staff = True
            created_user.is_superuser = True
            created_user.save(update_fields=['is_staff', 'is_superuser'])

    def perform_update(self, serializer):
        instance = self.get_object()
        self._validate_write_permissions(self.request.data, instance=instance)

        if _is_gym_admin(self.request.user):
            serializer.save(organization=self.request.user.organization)
        else:
            serializer.save()

    def perform_destroy(self, instance):
        self._validate_write_permissions(instance=instance)
        instance.delete()


class PersonViewSet(ModelViewSet):
    queryset = Person.objects.select_related('organization', 'branch').all()
    serializer_class = PersonSerializer

    def get_queryset(self):
        user = self.request.user
        if _is_superadmin(user):
            return self.queryset
        if user.organization_id:
            return self.queryset.filter(organization_id=user.organization_id)
        return self.queryset.none()


class ClassTypeViewSet(ModelViewSet):
    queryset = ClassType.objects.all()
    serializer_class = ClassTypeSerializer
    permission_classes = [IsSuperAdminOrGymAdmin]

    def get_queryset(self):
        user = self.request.user
        organization_id = self.request.query_params.get('organization_id')
        if _is_superadmin(user):
            if organization_id:
                return self.queryset.filter(organization_id=organization_id)
            return self.queryset
        if user.organization_id:
            return self.queryset.filter(organization_id=user.organization_id)
        return self.queryset.none()

    def perform_create(self, serializer):
        user = self.request.user
        if _is_superadmin(user):
            serializer.save()
            return
        if _is_gym_admin(user):
            serializer.save(organization=user.organization)
            return
        raise PermissionDenied('No tienes permisos para crear tipos de clase.')

    def perform_update(self, serializer):
        user = self.request.user
        class_type = self.get_object()
        if _is_superadmin(user):
            serializer.save()
            return
        if _is_gym_admin(user) and class_type.organization_id == user.organization_id:
            serializer.save(organization=user.organization)
            return
        raise PermissionDenied('No tienes permisos para editar este tipo de clase.')

    def perform_destroy(self, instance):
        user = self.request.user
        if _is_superadmin(user):
            instance.delete()
            return
        if _is_gym_admin(user) and instance.organization_id == user.organization_id:
            instance.delete()
            return
        raise PermissionDenied('No tienes permisos para eliminar este tipo de clase.')


class DisciplineViewSet(ModelViewSet):
    queryset = Discipline.objects.all()
    serializer_class = DisciplineSerializer
    permission_classes = [IsSuperAdminOrGymAdmin]

    def get_queryset(self):
        user = self.request.user
        organization_id = self.request.query_params.get('organization_id')
        if _is_superadmin(user):
            if organization_id:
                return self.queryset.filter(organization_id=organization_id)
            return self.queryset
        if user.organization_id:
            return self.queryset.filter(organization_id=user.organization_id)
        return self.queryset.none()

    def perform_create(self, serializer):
        user = self.request.user
        if _is_superadmin(user):
            serializer.save()
            return
        if _is_gym_admin(user):
            serializer.save(organization=user.organization)
            return
        raise PermissionDenied('No tienes permisos para crear disciplinas.')

    def perform_update(self, serializer):
        user = self.request.user
        discipline = self.get_object()
        if _is_superadmin(user):
            serializer.save()
            return
        if _is_gym_admin(user) and discipline.organization_id == user.organization_id:
            serializer.save(organization=user.organization)
            return
        raise PermissionDenied('No tienes permisos para editar esta disciplina.')

    def perform_destroy(self, instance):
        user = self.request.user
        if _is_superadmin(user):
            instance.delete()
            return
        if _is_gym_admin(user) and instance.organization_id == user.organization_id:
            instance.delete()
            return
        raise PermissionDenied('No tienes permisos para eliminar esta disciplina.')


class HolidayViewSet(ModelViewSet):
    queryset = Holiday.objects.select_related('organization', 'branch').all()
    serializer_class = HolidaySerializer
    permission_classes = [IsSuperAdminOrGymAdmin]

    def get_queryset(self):
        user = self.request.user
        queryset = self.queryset
        ordering = self.request.query_params.get('ordering')
        ordering_map = {
            'date': 'date',
            'name': 'name',
            'scope': 'scope',
            'status': 'is_active',
            'source_type': 'source_type',
        }
        default_ordering = ['date', 'id']
        if _is_superadmin(user):
            organization_id = self.request.query_params.get('organization_id')
            if organization_id:
                queryset = queryset.filter(models.Q(organization_id=organization_id) | models.Q(scope=Holiday.Scope.GLOBAL))
            return _apply_ordering(queryset, ordering, ordering_map, default_ordering)
        if _is_gym_admin(user) and user.organization_id:
            queryset = queryset.filter(models.Q(scope=Holiday.Scope.GLOBAL) | models.Q(organization_id=user.organization_id))
            return _apply_ordering(queryset, ordering, ordering_map, default_ordering)
        return queryset.none()

    def perform_create(self, serializer):
        user = self.request.user
        if _is_superadmin(user):
            serializer.save()
            return
        if _is_gym_admin(user):
            serializer.save(organization=user.organization, source_type=Holiday.SourceType.MANUAL)
            return
        raise PermissionDenied('No tienes permisos para crear festivos.')

    def perform_update(self, serializer):
        user = self.request.user
        holiday = self.get_object()
        if _is_superadmin(user):
            serializer.save()
            return
        if _is_gym_admin(user):
            if holiday.scope == Holiday.Scope.GLOBAL:
                raise PermissionDenied('No puedes editar festivos globales.')
            if holiday.organization_id != user.organization_id:
                raise PermissionDenied('No tienes permisos para este festivo.')
            if holiday.source_type == Holiday.SourceType.SYSTEM:
                allowed_keys = {'is_active'}
                changed_keys = set(serializer.validated_data.keys())
                if changed_keys.difference(allowed_keys):
                    raise PermissionDenied('Los festivos de sistema solo permiten activar o desactivar.')
            serializer.save(organization=user.organization)
            return
        raise PermissionDenied('No tienes permisos para editar festivos.')

    def perform_destroy(self, instance):
        user = self.request.user
        if _is_superadmin(user):
            instance.delete()
            return
        if _is_gym_admin(user):
            if instance.scope == Holiday.Scope.GLOBAL:
                raise PermissionDenied('No puedes eliminar festivos globales.')
            if instance.source_type == Holiday.SourceType.SYSTEM:
                raise PermissionDenied('No puedes eliminar festivos de sistema.')
            if instance.organization_id != user.organization_id:
                raise PermissionDenied('No tienes permisos para este festivo.')
            instance.delete()
            return
        raise PermissionDenied('No tienes permisos para eliminar festivos.')


class GymClassViewSet(ModelViewSet):
    queryset = GymClass.objects.select_related('branch', 'teacher', 'class_type', 'discipline', 'organization', 'class_template', 'created_by', 'closed_by').all()
    serializer_class = GymClassSerializer

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return GymClassDetailSerializer
        return GymClassSerializer

    def get_queryset(self):
        user = self.request.user
        organization_id = self.request.query_params.get('organization_id')
        status_value = self.request.query_params.get('status')
        status_in = self.request.query_params.get('status_in')
        discipline = self.request.query_params.get('discipline')
        teacher_id = self.request.query_params.get('teacher_id')
        branch_id = self.request.query_params.get('branch_id')
        start_date_from = self.request.query_params.get('start_date_from')
        start_date_to = self.request.query_params.get('start_date_to')
        has_series = self.request.query_params.get('has_series')
        ordering = self.request.query_params.get('ordering')

        ordering_map = {
            'start_datetime': 'start_datetime',
            'end_datetime': 'end_datetime',
            'teacher': 'teacher__first_name',
            'discipline': 'discipline__name',
            'status': 'status',
            'capacity': 'capacity',
        }
        default_ordering = ['start_datetime', 'id']

        def apply_common_filters(base_queryset):
            queryset = base_queryset
            if discipline:
                queryset = queryset.filter(discipline__name=discipline)
            if status_value:
                queryset = queryset.filter(status=status_value)
            if status_in:
                statuses = [item.strip() for item in status_in.split(',') if item.strip()]
                if statuses:
                    queryset = queryset.filter(status__in=statuses)
            if teacher_id:
                queryset = queryset.filter(teacher_id=teacher_id)
            if branch_id:
                queryset = queryset.filter(branch_id=branch_id)
            if start_date_from:
                queryset = queryset.filter(start_datetime__date__gte=start_date_from)
            if start_date_to:
                queryset = queryset.filter(start_datetime__date__lte=start_date_to)
            has_series_value = str(has_series or '').strip().lower()
            if has_series_value in {'true', '1', 'yes'}:
                queryset = queryset.filter(class_template__isnull=False)
            elif has_series_value in {'false', '0', 'no'}:
                queryset = queryset.filter(class_template__isnull=True)
            return queryset

        if _is_superadmin(user):
            queryset = self.queryset
            if organization_id:
                queryset = queryset.filter(organization_id=organization_id)
            queryset = apply_common_filters(queryset)
            queryset = _apply_ordering(queryset, ordering, ordering_map, default_ordering)
            _sync_class_statuses(queryset)
            return queryset

        if _is_gym_admin(user) and user.organization_id:
            queryset = self.queryset.filter(organization_id=user.organization_id)
            queryset = apply_common_filters(queryset)
            queryset = _apply_ordering(queryset, ordering, ordering_map, default_ordering)
            _sync_class_statuses(queryset)
            return queryset

        if _is_teacher(user):
            queryset = self.queryset.filter(teacher_id=user.id)
            queryset = apply_common_filters(queryset)
            queryset = _apply_ordering(queryset, ordering, ordering_map, default_ordering)
            _sync_class_statuses(queryset)
            return queryset

        if _is_student(user):
            mine_param = str(self.request.query_params.get('mine', '')).lower()
            queryset = self.queryset.filter(organization_id=user.organization_id) if user.organization_id else self.queryset.none()
            if mine_param in {'1', 'true', 'yes'}:
                queryset = queryset.filter(enrollments__student_id=user.id, enrollments__status='active').distinct()
            queryset = apply_common_filters(queryset)
            queryset = _apply_ordering(queryset, ordering, ordering_map, default_ordering)
            _sync_class_statuses(queryset)
            return queryset

        return self.queryset.none()

    @action(detail=False, methods=['get'], url_path='dashboard-summary')
    def dashboard_summary(self, request):
        queryset = self.get_queryset()
        data = get_class_dashboard_summary(queryset)
        return Response(data)

    def perform_create(self, serializer):
        user = self.request.user
        if _is_superadmin(user):
            serializer.save(created_by=user)
            return
        if _is_gym_admin(user):
            serializer.save(organization=user.organization, created_by=user)
            return
        raise PermissionDenied('No tienes permisos para crear clases.')

    def perform_update(self, serializer):
        user = self.request.user
        gym_class = self.get_object()

        if gym_class.is_closed:
            raise PermissionDenied('No puedes editar clases cerradas.')

        if _is_superadmin(user):
            serializer.save()
            return
        if _is_gym_admin(user) and gym_class.organization_id == user.organization_id:
            serializer.save(organization=user.organization)
            return
        raise PermissionDenied('No tienes permisos para editar esta clase.')

    def perform_destroy(self, instance):
        user = self.request.user
        if _is_superadmin(user):
            instance.delete()
            return
        if _is_gym_admin(user) and instance.organization_id == user.organization_id:
            instance.delete()
            return
        raise PermissionDenied('No tienes permisos para eliminar esta clase.')

    @action(detail=True, methods=['get'], url_path='enrolled-students')
    def enrolled_students(self, request, pk=None):
        gym_class = self.get_object()
        enrollments = gym_class.enrollments.filter(status='active').select_related('student')
        student_ids = list(enrollments.values_list('student_id', flat=True))
        active_plan_by_student = _get_active_student_plan_map(student_ids)
        latest_plan_by_student = _get_latest_student_plan_map(student_ids)
        today = timezone.localdate()
        attendance_by_student = {
            item.student_id: item
            for item in gym_class.attendances.select_related('student', 'marked_by').all()
        }

        results = []
        for enrollment in enrollments:
            student = enrollment.student
            attendance = attendance_by_student.get(student.id)
            student_plan = active_plan_by_student.get(student.id)
            latest_plan = latest_plan_by_student.get(student.id)
            remaining_classes = 0
            if student_plan:
                remaining_classes = max((student_plan.total_classes or 0) - (student_plan.classes_used or 0), 0)
            plan_status = _plan_status_payload(latest_plan, today=today)
            full_name = f'{student.first_name} {student.last_name}'.strip()
            results.append(
                {
                    'enrollment_id': enrollment.id,
                    'student_id': student.id,
                    'username': student.username,
                    'name': full_name or student.username,
                    'email': student.email,
                    'attendance_status': attendance.status if attendance else None,
                    'attendance_source': attendance.source if attendance else None,
                    'attendance_marked_at': attendance.marked_at if attendance else None,
                    'attendance_checked_at': attendance.checked_at if attendance else None,
                    'available_classes': remaining_classes,
                    'has_available_classes': remaining_classes > 0,
                    **plan_status,
                }
            )

        return Response(results)

    @action(detail=True, methods=['get'], url_path='enrollable-students')
    def enrollable_students(self, request, pk=None):
        gym_class = self.get_object()
        user = request.user

        if not (
            _is_superadmin(user)
            or (_is_gym_admin(user) and gym_class.organization_id == user.organization_id)
            or (_is_teacher(user) and gym_class.teacher_id == user.id)
        ):
            raise PermissionDenied('No tienes permisos para listar alumnos inscribibles en esta clase.')

        active_enrolled_ids = set(gym_class.enrollments.filter(status='active').values_list('student_id', flat=True))
        candidates = User.objects.filter(
            role=User.Role.STUDENT,
            organization_id=gym_class.organization_id,
            is_active=True,
        ).order_by('first_name', 'last_name', 'username')
        candidate_ids = list(candidates.values_list('id', flat=True))
        active_plan_by_student = _get_active_student_plan_map(candidate_ids)
        latest_plan_by_student = _get_latest_student_plan_map(candidate_ids)
        today = timezone.localdate()

        results = []
        for student in candidates:
            if student.id in active_enrolled_ids:
                continue
            student_plan = active_plan_by_student.get(student.id)
            latest_plan = latest_plan_by_student.get(student.id)
            remaining_classes = 0
            if student_plan:
                remaining_classes = max((student_plan.total_classes or 0) - (student_plan.classes_used or 0), 0)
            plan_status = _plan_status_payload(latest_plan, today=today)
            full_name = f'{student.first_name} {student.last_name}'.strip()
            results.append(
                {
                    'id': student.id,
                    'username': student.username,
                    'name': full_name or student.username,
                    'email': student.email,
                    'branch_id': student.branch_id,
                    'available_classes': remaining_classes,
                    'has_available_classes': remaining_classes > 0,
                    **plan_status,
                }
            )

        return Response(results)

    @action(detail=True, methods=['post'], url_path='attendance')
    def attendance(self, request, pk=None):
        gym_class = self.get_object()
        user = request.user

        if not (_is_superadmin(user) or (_is_gym_admin(user) and gym_class.organization_id == user.organization_id) or (_is_teacher(user) and gym_class.teacher_id == user.id)):
            raise PermissionDenied('No tienes permisos para registrar asistencia en esta clase.')

        gym_class.refresh_status_from_schedule(save=True)

        if gym_class.status == GymClass.Status.CANCELLED:
            raise PermissionDenied('No puedes registrar asistencia en una clase cancelada.')

        serializer = AttendanceBulkWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        attendances_payload = serializer.validated_data['attendances']

        active_enrollments = gym_class.enrollments.filter(status='active').select_related('student')
        enrolled_student_ids = set(active_enrollments.values_list('student_id', flat=True))
        incoming_ids = {item['student_id'] for item in attendances_payload}

        unexpected = sorted(incoming_ids - enrolled_student_ids)
        missing = sorted(enrolled_student_ids - incoming_ids)

        if unexpected or missing:
            return Response(
                {
                    'detail': 'La asistencia debe incluir exactamente los alumnos inscritos activos de la clase.',
                    'unexpected_student_ids': unexpected,
                    'missing_student_ids': missing,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            now = timezone.now()
            for item in attendances_payload:
                Attendance.objects.update_or_create(
                    gym_class=gym_class,
                    student_id=item['student_id'],
                    defaults={
                        'status': item['status'],
                        'source': Attendance.Source.MANUAL,
                        'marked_by': user,
                        'marked_at': now,
                        'checked_at': now,
                    },
                )

        attendances = gym_class.attendances.select_related('student', 'marked_by').all()
        return Response(AttendanceSerializer(attendances, many=True).data)

    @action(detail=True, methods=['post'], url_path='cancel')
    def cancel(self, request, pk=None):
        gym_class = self.get_object()
        user = request.user
        comment = str(request.data.get('comment', '')).strip()

        if not _can_close_or_cancel(user, gym_class):
            raise PermissionDenied('No tienes permisos para cancelar esta clase.')
        if not comment:
            return Response({'detail': 'Debes enviar un comentario o motivo para cancelar la clase.'}, status=status.HTTP_400_BAD_REQUEST)
        if gym_class.status in [GymClass.Status.CANCELLED, GymClass.Status.COMPLETED, GymClass.Status.COMPLETED_EARLY]:
            return Response({'detail': 'La clase ya está cerrada y no se puede cancelar.'}, status=status.HTTP_400_BAD_REQUEST)

        gym_class.status = GymClass.Status.CANCELLED
        gym_class.is_active = False
        gym_class.closed_by = user
        gym_class.closed_at = gym_class.closed_at or timezone.now()
        gym_class.closure_comment = comment
        gym_class.save(update_fields=['status', 'is_active', 'closed_by', 'closed_at', 'closure_comment', 'updated_at'])

        return Response(self.get_serializer(gym_class).data)

    @action(detail=True, methods=['post'], url_path='complete-early')
    def complete_early(self, request, pk=None):
        gym_class = self.get_object()
        user = request.user
        comment = str(request.data.get('comment', '')).strip()

        if not _can_close_or_cancel(user, gym_class):
            raise PermissionDenied('No tienes permisos para cerrar anticipadamente esta clase.')
        if not comment:
            return Response({'detail': 'Debes enviar un comentario o motivo para cerrar anticipadamente.'}, status=status.HTTP_400_BAD_REQUEST)
        if gym_class.status in [GymClass.Status.CANCELLED, GymClass.Status.COMPLETED, GymClass.Status.COMPLETED_EARLY]:
            return Response({'detail': 'La clase ya está cerrada.'}, status=status.HTTP_400_BAD_REQUEST)

        gym_class.status = GymClass.Status.COMPLETED_EARLY
        gym_class.is_active = False
        gym_class.closed_by = user
        gym_class.closed_at = gym_class.closed_at or timezone.now()
        gym_class.closure_comment = comment
        gym_class.save(update_fields=['status', 'is_active', 'closed_by', 'closed_at', 'closure_comment', 'updated_at'])
        gym_class.consolidate_attendance(marked_by=user, marked_at=gym_class.closed_at)
        _register_teacher_payment_for_class(gym_class)

        return Response(self.get_serializer(gym_class).data)

    @action(detail=False, methods=['post'], url_path='bulk-close')
    def bulk_close(self, request):
        class_ids = request.data.get('class_ids') or []
        action_name = str(request.data.get('action', '')).strip()
        comment = str(request.data.get('comment', '')).strip()

        if not isinstance(class_ids, list) or not class_ids:
            return Response({'detail': 'Debes enviar una lista de class_ids.'}, status=status.HTTP_400_BAD_REQUEST)
        if action_name not in ['cancel', 'complete_early']:
            return Response({'detail': 'La acción debe ser cancel o complete_early.'}, status=status.HTTP_400_BAD_REQUEST)
        if not comment:
            return Response({'detail': 'El comentario o motivo es obligatorio.'}, status=status.HTTP_400_BAD_REQUEST)

        user = request.user
        queryset = GymClass.objects.filter(id__in=class_ids)
        updated_ids = []
        skipped = []

        for gym_class in queryset:
            if not _can_close_or_cancel(user, gym_class):
                skipped.append({'id': gym_class.id, 'reason': 'Sin permisos'})
                continue

            if gym_class.status in [GymClass.Status.CANCELLED, GymClass.Status.COMPLETED, GymClass.Status.COMPLETED_EARLY]:
                skipped.append({'id': gym_class.id, 'reason': 'Clase ya cerrada'})
                continue

            gym_class.closed_by = user
            gym_class.closed_at = gym_class.closed_at or timezone.now()
            gym_class.closure_comment = comment
            gym_class.is_active = False

            if action_name == 'cancel':
                gym_class.status = GymClass.Status.CANCELLED
            else:
                gym_class.status = GymClass.Status.COMPLETED_EARLY

            gym_class.save(update_fields=['status', 'is_active', 'closed_by', 'closed_at', 'closure_comment', 'updated_at'])
            if action_name == 'complete_early':
                gym_class.consolidate_attendance(marked_by=user, marked_at=gym_class.closed_at)
                _register_teacher_payment_for_class(gym_class)
            updated_ids.append(gym_class.id)

        return Response(
            {
                'action': action_name,
                'updated_ids': updated_ids,
                'updated_count': len(updated_ids),
                'skipped': skipped,
            }
        )


class ClassTemplateViewSet(ModelViewSet):
    queryset = ClassTemplate.objects.select_related('organization', 'branch', 'teacher', 'class_type', 'discipline', 'created_by').all()
    serializer_class = ClassTemplateSerializer

    def get_queryset(self):
        user = self.request.user
        queryset = self.queryset
        organization_id = self.request.query_params.get('organization_id')
        is_active = self.request.query_params.get('is_active')
        ordering = self.request.query_params.get('ordering')

        ordering_map = {
            'start_date': 'start_date',
            'end_date': 'end_date',
            'teacher': 'teacher__first_name',
            'discipline': 'discipline__name',
            'capacity': 'capacity',
            'status': 'is_active',
        }
        default_ordering = ['start_date', 'start_time', 'id']

        if _is_superadmin(user):
            if organization_id:
                queryset = queryset.filter(organization_id=organization_id)
        elif user.organization_id:
            queryset = queryset.filter(organization_id=user.organization_id)
        else:
            return queryset.none()

        if is_active in {'true', '1'}:
            queryset = queryset.filter(is_active=True)
        elif is_active in {'false', '0'}:
            queryset = queryset.filter(is_active=False)
        return _apply_ordering(queryset, ordering, ordering_map, default_ordering)

    def perform_create(self, serializer):
        user = self.request.user
        if _is_superadmin(user):
            template = serializer.save(created_by=user)
            generate_instances_for_template_range(
                template=template,
                from_date=template.start_date,
                until_date=template.end_date,
                created_by=user,
                skip_holidays=True,
            )
            return
        if _is_gym_admin(user):
            template = serializer.save(organization=user.organization, created_by=user)
            generate_instances_for_template_range(
                template=template,
                from_date=template.start_date,
                until_date=template.end_date,
                created_by=user,
                skip_holidays=True,
            )
            return
        raise PermissionDenied('No tienes permisos para crear plantillas recurrentes.')

    def perform_update(self, serializer):
        user = self.request.user
        template = self.get_object()
        if _can_manage_org_resource(user, template.organization_id):
            updated_template = serializer.save()
            apply_updates = _parse_bool(self.request.data.get('apply_to_future_instances'), default=True)
            if apply_updates:
                apply_template_updates_to_future_instances(updated_template, now=timezone.now())
            return
        raise PermissionDenied('No tienes permisos para editar esta plantilla.')

    def perform_destroy(self, instance):
        user = self.request.user
        if _can_manage_org_resource(user, instance.organization_id):
            delete_result = delete_template_safely(instance)
            if delete_result.get('deleted'):
                return
            raise PermissionDenied(delete_result.get('reason') or 'No se pudo eliminar esta serie.')
        raise PermissionDenied('No tienes permisos para eliminar esta plantilla.')

    def destroy(self, request, *args, **kwargs):
        template = self.get_object()
        if not _can_manage_org_resource(request.user, template.organization_id):
            raise PermissionDenied('No tienes permisos para eliminar esta plantilla.')
        can_delete, reason = can_delete_template(template)
        if not can_delete:
            return Response(
                {
                    'detail': reason,
                    'suggested_action': 'Desactiva la serie o cancela futuras para conservar historico.',
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        delete_template_safely(template)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'], url_path='generate')
    def generate_instances(self, request, pk=None):
        template = self.get_object()
        user = request.user
        if not _can_manage_org_resource(user, template.organization_id):
            raise PermissionDenied('No tienes permisos para generar clases de esta plantilla.')

        from_date = request.data.get('from_date') or template.start_date
        until_date = request.data.get('until_date') or template.end_date
        try:
            summary = generate_instances_for_template_range(
                template=template,
                from_date=from_date,
                until_date=until_date,
                created_by=user,
                skip_holidays=True,
            )
        except ValueError:
            return Response({'detail': 'from_date/until_date deben usar formato YYYY-MM-DD.'}, status=status.HTTP_400_BAD_REQUEST)
        return Response(summary)

    @action(detail=True, methods=['post'], url_path='recurring-enroll')
    def recurring_enroll(self, request, pk=None):
        template = self.get_object()
        user = request.user

        if _is_student(user):
            if user.organization_id != template.organization_id:
                raise PermissionDenied('No puedes suscribirte a una plantilla de otra organización.')
            payload = dict(request.data)
            payload['class_template'] = template.id
            payload['student'] = user.id
            serializer = RecurringEnrollmentSerializer(data=payload, context={'request': request})
            serializer.is_valid(raise_exception=True)
            serializer.save(created_by=user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)

        if _can_manage_org_resource(user, template.organization_id):
            payload = dict(request.data)
            payload['class_template'] = template.id
            serializer = RecurringEnrollmentSerializer(data=payload, context={'request': request})
            serializer.is_valid(raise_exception=True)
            serializer.save(created_by=user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)

        raise PermissionDenied('No tienes permisos para crear esta inscripción recurrente.')

    @action(detail=True, methods=['post'], url_path='cancel-future-instances')
    def cancel_future_instances(self, request, pk=None):
        template = self.get_object()
        user = request.user
        if not _can_manage_org_resource(user, template.organization_id):
            raise PermissionDenied('No tienes permisos para cancelar futuras de esta serie.')
        comment = str(request.data.get('comment', '')).strip() or 'Cancelacion de futuras desde serie'
        summary = cancel_future_instances_for_template(template, actor=user, comment=comment)
        return Response(summary)

    @action(detail=True, methods=['post'], url_path='reactivate-future-cancelled')
    def reactivate_future_cancelled(self, request, pk=None):
        template = self.get_object()
        user = request.user
        if not _can_manage_org_resource(user, template.organization_id):
            raise PermissionDenied('No tienes permisos para reactivar futuras de esta serie.')
        summary = reactivate_future_cancelled_instances_for_template(template)
        return Response(summary)

    @action(detail=False, methods=['post'], url_path='bulk-action')
    def bulk_action(self, request):
        action_name = str(request.data.get('action', '')).strip()
        template_ids = request.data.get('template_ids') or []

        if action_name not in {'activate', 'deactivate', 'delete', 'cancel_future_instances', 'reactivate_future_cancelled', 'generate_pending'}:
            return Response({'detail': 'Accion invalida.'}, status=status.HTTP_400_BAD_REQUEST)
        if not isinstance(template_ids, list) or not template_ids:
            return Response({'detail': 'Debes enviar template_ids.'}, status=status.HTTP_400_BAD_REQUEST)

        user = request.user
        templates = ClassTemplate.objects.filter(id__in=template_ids)
        summary = {'action': action_name, 'updated_ids': [], 'deleted_ids': [], 'skipped': []}
        comment = str(request.data.get('comment', '')).strip() or 'Cancelacion masiva de futuras'

        for template in templates:
            if not _can_manage_org_resource(user, template.organization_id):
                summary['skipped'].append({'id': template.id, 'reason': 'Sin permisos'})
                continue

            if action_name == 'deactivate':
                template.is_active = False
                template.save(update_fields=['is_active', 'updated_at'])
                summary['updated_ids'].append(template.id)
                continue
            if action_name == 'activate':
                activate_template(template)
                summary['updated_ids'].append(template.id)
                continue

            if action_name == 'cancel_future_instances':
                cancel_future_instances_for_template(template, actor=user, comment=comment)
                summary['updated_ids'].append(template.id)
                continue
            if action_name == 'reactivate_future_cancelled':
                reactivation = reactivate_future_cancelled_instances_for_template(template)
                if reactivation.get('skipped'):
                    summary['skipped'].extend(
                        [{'id': template.id, 'reason': f"reactivation_skipped:{item.get('reason')}"} for item in reactivation['skipped']]
                    )
                summary['updated_ids'].append(template.id)
                continue

            if action_name == 'generate_pending':
                generate_instances_for_template_range(
                    template=template,
                    from_date=max(template.start_date, timezone.localdate()),
                    until_date=template.end_date,
                    created_by=user,
                    skip_holidays=True,
                )
                summary['updated_ids'].append(template.id)
                continue

            if action_name == 'delete':
                result = delete_template_safely(template)
                if result.get('deleted'):
                    summary['deleted_ids'].append(template.id)
                else:
                    summary['skipped'].append({'id': template.id, 'reason': result.get('reason', 'No se pudo eliminar')})

        summary['updated_count'] = len(summary['updated_ids'])
        summary['deleted_count'] = len(summary['deleted_ids'])
        return Response(summary)


class RecurringEnrollmentViewSet(ModelViewSet):
    queryset = RecurringEnrollment.objects.select_related(
        'student',
        'class_template',
        'class_template__organization',
        'class_template__branch',
        'class_template__teacher',
        'class_template__discipline',
    ).all()
    serializer_class = RecurringEnrollmentSerializer

    def get_queryset(self):
        user = self.request.user
        queryset = self.queryset
        student_id = self.request.query_params.get('student_id')
        template_id = self.request.query_params.get('class_template')
        is_active = str(self.request.query_params.get('is_active', '')).strip().lower()
        teacher_id = self.request.query_params.get('teacher_id')
        discipline = self.request.query_params.get('discipline')
        branch_id = self.request.query_params.get('branch_id')
        start_date_from = self.request.query_params.get('start_date_from')
        start_date_to = self.request.query_params.get('start_date_to')

        if template_id:
            queryset = queryset.filter(class_template_id=template_id)
        if student_id:
            queryset = queryset.filter(student_id=student_id)
        if is_active in {'true', '1', 'yes'}:
            queryset = queryset.filter(is_active=True)
        elif is_active in {'false', '0', 'no'}:
            queryset = queryset.filter(is_active=False)
        if teacher_id:
            queryset = queryset.filter(class_template__teacher_id=teacher_id)
        if discipline:
            queryset = queryset.filter(class_template__discipline__name=discipline)
        if branch_id:
            queryset = queryset.filter(class_template__branch_id=branch_id)
        if start_date_from:
            queryset = queryset.filter(start_date__gte=start_date_from)
        if start_date_to:
            queryset = queryset.filter(start_date__lte=start_date_to)

        if _is_superadmin(user):
            return queryset
        if _is_gym_admin(user) and user.organization_id:
            return queryset.filter(class_template__organization_id=user.organization_id)
        if _is_student(user):
            return queryset.filter(student_id=user.id)
        return queryset.none()

    def perform_create(self, serializer):
        user = self.request.user
        if _is_student(user):
            serializer.save(student=user, created_by=user)
            return

        template = serializer.validated_data.get('class_template')
        if template and _can_manage_org_resource(user, template.organization_id):
            serializer.save(created_by=user)
            return
        raise PermissionDenied('No tienes permisos para crear esta recurrencia.')

    def perform_update(self, serializer):
        user = self.request.user
        recurring_enrollment = self.get_object()
        if _is_student(user) and recurring_enrollment.student_id != user.id:
            raise PermissionDenied('Solo puedes editar tus propias recurrencias.')
        if _is_gym_admin(user) and recurring_enrollment.class_template.organization_id != user.organization_id:
            raise PermissionDenied('No tienes permisos para editar esta recurrencia.')
        if not (_is_superadmin(user) or _is_gym_admin(user) or _is_student(user)):
            raise PermissionDenied('No tienes permisos para editar recurrencias.')

        if _is_student(user):
            payload_keys = {str(key) for key in self.request.data.keys()}
            payload_keys.discard('csrfmiddlewaretoken')
            if payload_keys.difference({'is_active'}):
                raise PermissionDenied('Como alumno solo puedes pausar o reactivar tu recurrencia.')
            requested_state = serializer.validated_data.get('is_active', recurring_enrollment.is_active)
            if requested_state != recurring_enrollment.is_active:
                can_modify, reason = _student_can_manage_recurring(recurring_enrollment)
                if not can_modify:
                    raise PermissionDenied(reason)
            updated = serializer.save(is_active=requested_state)
            if updated.is_active:
                create_enrollments_for_recurring_subscription(recurring_enrollment=updated)
            else:
                cancel_future_recurring_enrollments(updated)
            return

        updated = serializer.save()
        if updated.is_active:
            create_enrollments_for_recurring_subscription(recurring_enrollment=updated)
        else:
            cancel_future_recurring_enrollments(updated)

    def perform_destroy(self, instance):
        user = self.request.user
        if _is_superadmin(user):
            instance.delete()
            return
        if _is_gym_admin(user) and instance.class_template.organization_id == user.organization_id:
            instance.delete()
            return
        if _is_student(user) and instance.student_id == user.id:
            can_modify, reason = _student_can_manage_recurring(instance)
            if not can_modify:
                raise PermissionDenied(reason)

            cancel_future_recurring_enrollments(instance)
            instance.delete()
            return
        raise PermissionDenied('No tienes permisos para eliminar esta recurrencia.')

    @action(detail=False, methods=['get'], url_path='my')
    def my_recurring(self, request):
        if not _is_student(request.user):
            raise PermissionDenied('Este endpoint es solo para alumnos.')
        queryset = self.get_queryset().filter(student_id=request.user.id, is_active=True)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


class EnrollmentViewSet(ModelViewSet):
    queryset = Enrollment.objects.select_related(
        'gym_class',
        'student',
        'recurring_enrollment',
        'gym_class__organization',
        'gym_class__teacher',
        'gym_class__class_type',
        'gym_class__discipline',
        'gym_class__branch',
    ).all()
    serializer_class = EnrollmentSerializer

    def get_queryset(self):
        user = self.request.user
        organization_id = self.request.query_params.get('organization_id')
        gym_class_id = self.request.query_params.get('gym_class')
        status_value = self.request.query_params.get('status')
        teacher_id = self.request.query_params.get('teacher_id')
        discipline = self.request.query_params.get('discipline')
        branch_id = self.request.query_params.get('branch_id')
        start_date_from = self.request.query_params.get('start_date_from')
        start_date_to = self.request.query_params.get('start_date_to')
        reservation_kind = str(self.request.query_params.get('reservation_kind', '')).strip().lower()
        queryset = self.queryset

        _sync_class_statuses(GymClass.objects.all())

        if gym_class_id:
            queryset = queryset.filter(gym_class_id=gym_class_id)
        if status_value:
            queryset = queryset.filter(status=status_value)
        if teacher_id:
            queryset = queryset.filter(gym_class__teacher_id=teacher_id)
        if discipline:
            queryset = queryset.filter(gym_class__discipline__name=discipline)
        if branch_id:
            queryset = queryset.filter(gym_class__branch_id=branch_id)
        if start_date_from:
            queryset = queryset.filter(gym_class__start_datetime__date__gte=start_date_from)
        if start_date_to:
            queryset = queryset.filter(gym_class__start_datetime__date__lte=start_date_to)
        if reservation_kind == 'recurring':
            queryset = queryset.filter(recurring_enrollment__isnull=False)
        elif reservation_kind in {'single', 'individual'}:
            queryset = queryset.filter(recurring_enrollment__isnull=True)

        if _is_superadmin(user):
            if organization_id:
                queryset = queryset.filter(gym_class__organization_id=organization_id)
            return queryset
        if _is_gym_admin(user) and user.organization_id:
            return queryset.filter(gym_class__organization_id=user.organization_id)
        if _is_teacher(user):
            return queryset.filter(gym_class__teacher_id=user.id)
        if _is_student(user):
            return queryset.filter(student_id=user.id)
        return queryset.none()

    @action(detail=False, methods=['get'], url_path='my')
    def my_reservations(self, request):
        if not _is_student(request.user):
            raise PermissionDenied('Este endpoint es solo para alumnos.')
        queryset = self.get_queryset().filter(student_id=request.user.id)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], url_path='cancel')
    def cancel_reservation(self, request, pk=None):
        enrollment = self.get_object()
        user = request.user

        if _is_student(user) and enrollment.student_id != user.id:
            raise PermissionDenied('Solo puedes cancelar tus propias reservas.')
        if _is_gym_admin(user) and enrollment.gym_class.organization_id != user.organization_id:
            raise PermissionDenied('No tienes permisos para esta reserva.')
        if _is_teacher(user) and enrollment.gym_class.teacher_id != user.id:
            raise PermissionDenied('Solo puedes cancelar inscripciones en tus propias clases.')
        if not (_is_superadmin(user) or _is_gym_admin(user) or _is_teacher(user) or _is_student(user)):
            raise PermissionDenied('No tienes permisos para cancelar esta reserva.')
        if _is_student(user):
            can_cancel, reason = _student_can_cancel_enrollment(enrollment)
            if not can_cancel:
                return Response({'detail': reason}, status=status.HTTP_400_BAD_REQUEST)
        if _is_teacher(user):
            can_cancel, reason = _student_can_modify_before_class(enrollment.gym_class.start_datetime, 0)
            if not can_cancel:
                return Response({'detail': reason}, status=status.HTTP_400_BAD_REQUEST)
            if enrollment.gym_class.status in {GymClass.Status.CANCELLED, GymClass.Status.COMPLETED, GymClass.Status.COMPLETED_EARLY}:
                return Response({'detail': 'La clase esta cerrada y ya no se puede modificar la reserva.'}, status=status.HTTP_400_BAD_REQUEST)
            if enrollment.status != 'active':
                return Response({'detail': 'La reserva ya esta cancelada.'}, status=status.HTTP_400_BAD_REQUEST)

        cancel_enrollment_with_refund(enrollment)
        return Response(self.get_serializer(enrollment).data)

    def perform_create(self, serializer):
        user = self.request.user
        student = serializer.validated_data.get('student')
        if _is_student(user):
            student = student or user
        requested_status = serializer.validated_data.get('status', 'active')
        should_validate_plan = requested_status == 'active' or _is_teacher(user) or _is_student(user)

        with transaction.atomic():
            if requested_status != 'active':
                serializer.save()
                return

            if _is_superadmin(user) or _is_gym_admin(user):
                try:
                    enrollment = reserve_student_in_class(
                        student=student,
                        gym_class=serializer.validated_data.get('gym_class'),
                        require_plan=should_validate_plan,
                    )
                except ReservationRuleError as exc:
                    raise ValidationError({'detail': exc.message})
                serializer.instance = enrollment
                return

            if _is_teacher(user):
                gym_class = serializer.validated_data.get('gym_class')
                if not gym_class or gym_class.teacher_id != user.id:
                    raise PermissionDenied('Solo puedes inscribir alumnos en tus propias clases.')
                try:
                    enrollment = reserve_student_in_class(student=student, gym_class=gym_class, require_plan=True)
                except ReservationRuleError as exc:
                    raise ValidationError({'detail': exc.message})
                serializer.instance = enrollment
                return

            if _is_student(user):
                try:
                    enrollment = reserve_student_in_class(
                        student=user,
                        gym_class=serializer.validated_data.get('gym_class'),
                        require_plan=True,
                    )
                except ReservationRuleError as exc:
                    raise ValidationError({'detail': exc.message})
                serializer.instance = enrollment
                return

            raise PermissionDenied('No tienes permisos para crear inscripciones.')

    def perform_update(self, serializer):
        user = self.request.user
        enrollment = self.get_object()
        if _is_superadmin(user):
            serializer.save()
            return
        if _is_gym_admin(user) and enrollment.gym_class.organization_id == user.organization_id:
            serializer.save()
            return
        raise PermissionDenied('No tienes permisos para editar inscripciones.')

    def perform_destroy(self, instance):
        user = self.request.user
        if _is_superadmin(user):
            instance.delete()
            return
        if _is_gym_admin(user) and instance.gym_class.organization_id == user.organization_id:
            instance.delete()
            return
        if _is_student(user) and instance.student_id == user.id:
            instance.delete()
            return
        raise PermissionDenied('No tienes permisos para eliminar inscripciones.')


class MembershipPlanViewSet(ModelViewSet):
    queryset = Plan.objects.select_related('organization').all()
    serializer_class = PlanSerializer

    def get_queryset(self):
        base_queryset = Plan.objects.select_related('organization').all()
        user = self.request.user
        organization_id = self.request.query_params.get('organization_id')
        if _is_superadmin(user):
            if organization_id:
                base_queryset = base_queryset.filter(organization_id=organization_id)
            return base_queryset
        if (_is_gym_admin(user) or _is_student(user)) and user.organization_id:
            return base_queryset.filter(organization_id=user.organization_id)
        return base_queryset.none()

    def perform_create(self, serializer):
        user = self.request.user
        if not (_is_superadmin(user) or _is_gym_admin(user)):
            raise PermissionDenied('No tienes permisos para crear planes.')
        if _is_gym_admin(user):
            serializer.save(organization=user.organization)
            return
        serializer.save()

    def perform_update(self, serializer):
        user = self.request.user
        if not (_is_superadmin(user) or _is_gym_admin(user)):
            raise PermissionDenied('No tienes permisos para editar planes.')
        if _is_gym_admin(user) and serializer.instance.organization_id != user.organization_id:
            raise PermissionDenied('No puedes editar planes de otra organización.')
        if _is_gym_admin(user):
            serializer.save(organization=user.organization)
            return
        serializer.save()

    def perform_destroy(self, instance):
        user = self.request.user
        if not (_is_superadmin(user) or _is_gym_admin(user)):
            raise PermissionDenied('No tienes permisos para eliminar planes.')
        if _is_gym_admin(user) and instance.organization_id != user.organization_id:
            raise PermissionDenied('No puedes eliminar planes de otra organización.')
        instance.delete()

    @action(detail=False, methods=['post'], url_path='assign')
    def assign(self, request):
        user = request.user
        if not (_is_superadmin(user) or _is_gym_admin(user)):
            raise PermissionDenied('No tienes permisos para asignar planes.')

        serializer = StudentPlanAssignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated = serializer.validated_data
        student = validated['user']
        plan = validated['plan']

        if _is_gym_admin(user) and student.organization_id != user.organization_id:
            raise PermissionDenied('No puedes asignar planes a alumnos de otra organización.')
        if _is_gym_admin(user) and plan.organization_id != user.organization_id:
            raise PermissionDenied('No puedes asignar planes de otra organización.')
        if plan.organization_id != student.organization_id:
            raise PermissionDenied('No puedes asignar un plan de otra organización.')

        with transaction.atomic():
            StudentPlan.objects.filter(user=student, is_active=True).update(is_active=False)
            assigned = StudentPlan.objects.create(
                user=student,
                plan=plan,
                start_date=validated['start_date'],
                end_date=validated['end_date'],
                total_classes=validated['total_classes'],
                discount_percentage=validated['discount_percentage'],
                final_price=max(float(plan.price) * (1 - (validated['discount_percentage'] / 100)), 0),
                is_active=True,
            )

        return Response(StudentPlanSerializer(assigned).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['get'], url_path='my-plan')
    def my_plan(self, request):
        if not _is_student(request.user):
            raise PermissionDenied('Solo estudiantes pueden consultar su plan activo.')
        student_plan = _get_active_student_plan(request.user)
        if not student_plan:
            return Response(None)
        return Response(StudentPlanSerializer(student_plan).data)

    @action(detail=False, methods=['get'], url_path='my-memberships')
    def my_memberships(self, request):
        if not _is_student(request.user):
            raise PermissionDenied('Este endpoint es solo para alumnos.')

        today = timezone.localdate()
        queryset = (
            StudentPlan.objects.select_related('plan', 'user')
            .filter(
                user=request.user,
                is_active=True,
                start_date__lte=today,
                end_date__gte=today,
            )
            .order_by('end_date', '-start_date', '-id')
        )
        serializer = StudentPlanSerializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'], url_path='memberships')
    def memberships(self, request, pk=None):
        user = request.user
        plan = self.get_object()

        if _is_superadmin(user):
            memberships_queryset = (
                StudentPlan.objects.select_related('user', 'plan')
                .filter(plan_id=plan.id, user__role=User.Role.STUDENT)
                .order_by('-is_active', '-start_date', '-id')
            )
        elif _is_gym_admin(user):
            memberships_queryset = (
                StudentPlan.objects.select_related('user', 'plan')
                .filter(plan_id=plan.id, user__role=User.Role.STUDENT, user__organization_id=user.organization_id)
                .order_by('-is_active', '-start_date', '-id')
            )
        else:
            raise PermissionDenied('No tienes permisos para ver membresias de este plan.')

        serializer = StudentPlanSerializer(memberships_queryset, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['delete'], url_path=r'memberships/(?P<membership_id>[^/.]+)')
    def remove_membership(self, request, pk=None, membership_id=None):
        user = request.user
        plan = self.get_object()

        if _is_superadmin(user):
            membership = (
                StudentPlan.objects.select_related('user', 'plan')
                .filter(id=membership_id, plan_id=plan.id, user__role=User.Role.STUDENT)
                .first()
            )
        elif _is_gym_admin(user):
            membership = (
                StudentPlan.objects.select_related('user', 'plan')
                .filter(
                    id=membership_id,
                    plan_id=plan.id,
                    user__role=User.Role.STUDENT,
                    user__organization_id=user.organization_id,
                )
                .first()
            )
        else:
            raise PermissionDenied('No tienes permisos para quitar membresias de este plan.')

        if not membership:
            return Response({'detail': 'Membresia no encontrada para este plan.'}, status=status.HTTP_404_NOT_FOUND)

        if (membership.classes_used or 0) > 0:
            return Response(
                {
                    'detail': 'No se puede quitar esta membresia porque ya tiene clases utilizadas. Define una politica de devolucion primero.'
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        membership.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class TeacherPaymentRuleViewSet(ModelViewSet):
    queryset = TeacherPaymentRule.objects.select_related('organization', 'branch', 'discipline', 'class_type').prefetch_related('teachers').all()
    serializer_class = TeacherPaymentRuleSerializer

    def get_queryset(self):
        user = self.request.user
        queryset = self.queryset.annotate(usage_count=models.Count('teachers', distinct=True))
        if _is_superadmin(user):
            organization_id = self.request.query_params.get('organization_id')
            if organization_id:
                queryset = queryset.filter(organization_id=organization_id)
            return queryset
        if _is_gym_admin(user) and user.organization_id:
            return queryset.filter(organization_id=user.organization_id)
        return queryset.none()

    def perform_create(self, serializer):
        user = self.request.user
        if _is_superadmin(user):
            serializer.save(teacher=None)
            return
        if _is_gym_admin(user):
            serializer.save(organization=user.organization, teacher=None)
            return
        raise PermissionDenied('No tienes permisos para crear reglas de pago.')

    def perform_update(self, serializer):
        user = self.request.user
        instance = self.get_object()
        is_used = instance.teachers.exists()
        if is_used:
            requested = serializer.validated_data
            locked_fields = [
                'organization',
                'branch',
                'discipline',
                'class_type',
                'payment_type',
                'amount',
                'calculation_base',
            ]
            changed_locked = any(field in requested and requested[field] != getattr(instance, field) for field in locked_fields)
            if changed_locked:
                raise ValidationError({'detail': 'Esta regla tiene profesores asignados. Solo puedes activarla o desactivarla.'})
        if _is_superadmin(user):
            serializer.save()
            return
        if _is_gym_admin(user) and instance.organization_id == user.organization_id:
            serializer.save(organization=user.organization)
            return
        raise PermissionDenied('No tienes permisos para editar reglas de pago.')

    def perform_destroy(self, instance):
        if instance.teachers.exists():
            raise ValidationError({'detail': 'No puedes eliminar una regla con profesores asignados. Desasigna primero.'})
        user = self.request.user
        if _is_superadmin(user):
            instance.delete()
            return
        if _is_gym_admin(user) and instance.organization_id == user.organization_id:
            instance.delete()
            return
        raise PermissionDenied('No tienes permisos para eliminar reglas de pago.')

    @action(detail=True, methods=['get', 'put'], url_path='assignments')
    def assignments(self, request, pk=None):
        rule = self.get_object()
        user = request.user
        if not (_is_superadmin(user) or (_is_gym_admin(user) and rule.organization_id == user.organization_id)):
            raise PermissionDenied('No tienes permisos para gestionar asignaciones de esta regla.')

        teachers_qs = User.objects.filter(
            role=User.Role.TEACHER,
            is_active=True,
            organization_id=rule.organization_id,
        ).order_by('first_name', 'last_name', 'username')

        if request.method.lower() == 'put':
            serializer = TeacherPaymentRuleAssignmentsUpdateSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            teacher_ids = serializer.validated_data['teacher_ids']
            valid_ids = set(teachers_qs.values_list('id', flat=True))
            invalid = [teacher_id for teacher_id in teacher_ids if teacher_id not in valid_ids]
            if invalid:
                raise ValidationError({'teacher_ids': f'Teachers invalidos para la organizacion: {invalid}'})
            rule.teachers.set(teacher_ids)

        assigned_ids = set(rule.teachers.values_list('id', flat=True))
        items = []
        for teacher in teachers_qs:
            full_name = f'{teacher.first_name} {teacher.last_name}'.strip()
            items.append(
                {
                    'teacher_id': teacher.id,
                    'teacher_name': full_name or teacher.username,
                    'is_assigned': teacher.id in assigned_ids,
                }
            )
        return Response(items)


class TeacherPaymentRecordViewSet(ModelViewSet):
    queryset = TeacherPaymentRecord.objects.select_related('teacher', 'class_instance', 'rule').all()
    serializer_class = TeacherPaymentRecordSerializer
    http_method_names = ['get', 'head', 'options']

    def get_queryset(self):
        user = self.request.user
        teacher_id = self.request.query_params.get('teacher_id')
        date_from = self.request.query_params.get('date_from')
        date_to = self.request.query_params.get('date_to')

        queryset = self.queryset
        if _is_superadmin(user):
            pass
        elif _is_gym_admin(user) and user.organization_id:
            queryset = queryset.filter(class_instance__organization_id=user.organization_id)
        elif _is_teacher(user):
            queryset = queryset.filter(teacher_id=user.id)
        else:
            return queryset.none()

        if teacher_id:
            queryset = queryset.filter(teacher_id=teacher_id)
        if date_from:
            queryset = queryset.filter(calculated_at__date__gte=date_from)
        if date_to:
            queryset = queryset.filter(calculated_at__date__lte=date_to)
        return queryset.order_by('-calculated_at', '-id')

    @action(detail=False, methods=['get'], url_path='my')
    def my(self, request):
        user = request.user
        if not _is_teacher(user):
            raise PermissionDenied('Solo los profesores pueden usar este endpoint.')
        queryset = self.get_queryset().filter(teacher_id=user.id)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


