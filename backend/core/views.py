from django.contrib.auth import authenticate, get_user_model
import csv
import logging
from datetime import datetime, timedelta
from uuid import uuid4

from django.conf import settings
from django.http import HttpResponse
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core import signing
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import send_mail
from django.db import models, transaction
from django.db.models import ProtectedError
from django.utils import timezone
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import MethodNotAllowed, NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet

from accounts import roles

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
    TeacherPayout,
    TrialFollowupConfiguration,
)
from .permissions import (
    FinancialResourcePermission,
    IsSuperAdminOrGymAdmin,
    OperationalResourcePermission,
)
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
    ManualPaymentCreateSerializer,
    ManualPaymentSerializer,
    OrganizationSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    PlanSerializer,
    PublicOrganizationBrandingSerializer,
    PublicRegistrationSerializer,
    PublicTrialClassSerializer,
    PersonSerializer,
    RecurringEnrollmentSerializer,
    SelfProfileSerializer,
    StudentPlanAssignSerializer,
    StudentPlanSerializer,
    TeacherPaymentRuleAssignmentsUpdateSerializer,
    TeacherPaymentRecordSerializer,
    TeacherPaymentRuleSerializer,
    TrialFollowupConfigurationSerializer,
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
from .services.manual_payments import (
    ManualPaymentOrganizationMismatch,
    record_manual_payment,
)
from .services.plans import REASON_PLAN_UNAVAILABLE, AlertLevel, describe_student_plan
from .services.public_urls import organization_public_base_url
from .services.reservations import (
    ReservationRuleError,
    cancel_enrollment_with_refund,
    cancel_future_recurring_enrollments,
    consume_student_plan_for_enrollment,
    get_active_student_plan,
    get_enrollment_student_plan,
    reserve_student_in_class,
    revert_consumption_for_class,
    revert_consumption_for_enrollment,
    rollback_consumption_for_enrollment,
    should_refund_consumption,
    validate_student_plan_for_reservation,
)
from .services.teacher_payments import build_teacher_payment_summary, calculate_teacher_payment

User = get_user_model()
QR_ATTENDANCE_SALT = 'tymro.attendance.qr'
# Rotación de la pantalla DESACOPLADA de la aceptación del backend:
#  - REFRESH: cada cuántos segundos la pantalla muestra un QR nuevo (anti-reutilización).
#  - ACCEPTANCE: cuántos segundos atrás el backend sigue aceptando un token al validarlo.
# La pantalla refresca rápido, pero un código escaneado justo antes de rotar sigue
# siendo válido lo suficiente para absorber la latencia escaneo→preview.
QR_TOKEN_REFRESH_SECONDS = 10
QR_TOKEN_ACCEPTANCE_SECONDS = 60
# Permiso de un solo uso emitido por el preview para confirmar la asistencia. Vale
# por (student, clase, org) durante una ventana cómoda; la unicidad de Attendance lo
# vuelve de un solo uso. NO revalida el token del QR al confirmar.
QR_CHECKIN_GRANT_SALT = 'tymro.attendance.checkin-grant'
QR_CHECKIN_GRANT_TTL_SECONDS = 120
ATTENDANCE_SCREEN_SESSION_TTL_HOURS = 8
QR_WINDOW_BEFORE_MINUTES = 10
QR_WINDOW_AFTER_MINUTES = 15


def _user_role(user):
    return getattr(user, 'role', None)


def _is_superadmin(user):
    return _user_role(user) == User.Role.SUPERADMIN


def _is_gym_admin(user):
    return _user_role(user) == User.Role.GYM_ADMIN


def _is_manager(user):
    return _user_role(user) == User.Role.MANAGER


def _is_monitor(user):
    return _user_role(user) == User.Role.MONITOR


def _is_teacher(user):
    return _user_role(user) == User.Role.TEACHER


def _is_student(user):
    return _user_role(user) == User.Role.STUDENT


def _sync_class_statuses(base_queryset):
    # El queryset es OBLIGATORIO a proposito: esta funcion ESCRIBE (status, is_active,
    # closed_at, Attendance y TeacherPaymentRecord). Con un default global, un call site
    # futuro que se olvide del argumento reintroduce en silencio la escritura sobre todas
    # las organizaciones. Usar `_class_sync_scope(user)`.
    queryset = base_queryset
    candidates = queryset.filter(status__in=[GymClass.Status.SCHEDULED, GymClass.Status.IN_PROGRESS])
    for gym_class in candidates:
        gym_class.refresh_status_from_schedule(save=True)
        if gym_class.status in {GymClass.Status.COMPLETED, GymClass.Status.COMPLETED_EARLY}:
            calculate_teacher_payment(gym_class)


def _as_id_list(raw_ids):
    """(ids enteros, ids inválidos) de una lista de ids que llegó del cliente.

    Los endpoints bulk solo validaban "lista no vacía" y pasaban el contenido crudo a
    `filter(id__in=...)`: un valor no numérico levantaba `ValueError` fuera del manejo de
    DRF y respondía 500. Sirve igual para un id suelto de query param (`[valor]`).
    """
    ids, invalid = [], []
    for raw in raw_ids:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            invalid.append(raw)
            continue
        # Fuera del rango de bigint el `id__in` revienta en PostgreSQL (500). SQLite lo
        # tolera, asi que la suite no lo detectaria.
        if not -(2 ** 63) <= value < 2 ** 63:
            invalid.append(raw)
            continue
        ids.append(value)
    return ids, invalid


def _org_scoped(queryset, user):
    """Acota un queryset con FK directa `organization` a lo que este actor puede alcanzar.

    Para las acciones `detail=False` que reciben ids en el body, donde `get_object()` no
    interviene y por lo tanto el scoping tiene que ser explícito.
    """
    if _is_superadmin(user):
        return queryset
    if getattr(user, 'organization_id', None):
        return queryset.filter(organization_id=user.organization_id)
    return queryset.none()


def _class_sync_scope(user):
    """Clases que ESTE actor puede hacer sincronizar.

    `_sync_class_statuses` parece un helper de listado pero ESCRIBE: persiste
    `status`/`is_active`/`closed_at`, consolida `Attendance` y crea el
    `TeacherPaymentRecord` del profe. Llamarla sin filtrar (`GymClass.objects.all()`)
    dejaba que cualquier autenticado —un alumno, incluso— cerrara clases y materializara
    los pagos de OTRAS organizaciones (regla #1: scoping antes de cualquier escritura).

    El superadmin es rol de plataforma y sí abarca todo; un usuario sin organización no
    sincroniza nada.
    """
    if _is_superadmin(user):
        return GymClass.objects.all()
    if getattr(user, 'organization_id', None):
        return GymClass.objects.filter(organization_id=user.organization_id)
    return GymClass.objects.none()


def _is_own_class_teacher(user, gym_class):
    """El profesor de ESTA clase, y de la misma organización que él.

    `teacher_id == user.id` a secas no alcanza: `GymClass.teacher` es SET_NULL, así que una
    clase conserva el `teacher_id` aunque después muevan al profesor a otra organización
    (`PATCH /api/users/{id}/ {"organization": ...}` del superadmin). Con esa FK rancia, el
    usuario leía y ESCRIBÍA en la organización que dejó atrás: cerrar la clase, cancelar
    inscripciones, registrar asistencia y disparar el pago al profe. El scope del profesor
    es la intersección de "mis clases" con "mi organización" (regla #1), nunca solo la FK.
    """
    return (
        _is_teacher(user)
        and gym_class.teacher_id == user.id
        and bool(user.organization_id)
        and gym_class.organization_id == user.organization_id
    )


def _is_own_org_student(user, enrollment):
    """El alumno de ESTA inscripcion, y de la misma organizacion que ella.

    Simetrico a `_is_own_class_teacher`: `enrollment.student_id == user.id` a secas no
    alcanza porque `Enrollment.student` es CASCADE sobre el usuario, no sobre la
    organizacion. Mover a un alumno de la org A a la org B le deja sus reservas de A vivas,
    y desde B seguia leyendolas y escribiendolas (cancelar, borrar, y con el reverso de
    consumo, descontar un `StudentPlan` de la organizacion que dejo).
    """
    return (
        _is_student(user)
        and enrollment.student_id == user.id
        and bool(user.organization_id)
        and enrollment.gym_class.organization_id == user.organization_id
    )


def _can_close_or_cancel(user, gym_class):
    if _is_superadmin(user):
        return True
    if roles.is_org_admin(user) and gym_class.organization_id == user.organization_id:
        return True
    if _is_own_class_teacher(user, gym_class):
        return True
    return False


def _refund_active_enrollments_for_cancelled_class(gym_class):
    """Al cancelar una clase, cada inscripción activa se cancela y se devuelve la
    clase consumida al plan del alumno (should_refund_consumption ya es True porque
    la clase quedó en estado CANCELLED). Devuelve la cantidad de inscripciones
    afectadas."""
    refunded = 0
    for enrollment in gym_class.enrollments.filter(status='active').select_related('student'):
        enrollment.gym_class = gym_class  # asegura que el refund vea el estado CANCELLED en memoria
        cancel_enrollment_with_refund(enrollment)
        refunded += 1
    return refunded


def _can_manage_org_resource(user, organization_id):
    if _is_superadmin(user):
        return True
    if _is_gym_admin(user) and user.organization_id == organization_id:
        return True
    return False


def _can_manage_operational_resource(user, organization_id):
    """Gestión de recursos operativos (grupo a): superadmin o org-admin (gym_admin/manager)
    de la misma organización. Para config de organización usar _can_manage_org_resource."""
    if _is_superadmin(user):
        return True
    if roles.is_org_admin(user) and user.organization_id == organization_id:
        return True
    return False


def _register_teacher_payment_for_class(gym_class):
    if not gym_class:
        return
    if gym_class.status not in {GymClass.Status.COMPLETED, GymClass.Status.COMPLETED_EARLY}:
        return
    calculate_teacher_payment(gym_class)


def _payment_type_label(code):
    if not code:
        return '-'
    return dict(TeacherPaymentRule.PaymentType.choices).get(code, code)


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


def _get_active_student_plan_map(student_ids, organization_id, on_date=None):
    """Membresía vigente de cada alumno EN `organization_id`.

    `organization_id` es obligatorio a propósito: filtrar solo por `user_id__in` mostraba
    en el roster de una clase el saldo, el vencimiento y las alertas del plan que le vendió
    OTRA organización (`StudentPlan.user` es CASCADE sobre el usuario, no sobre la org).
    Además quedaba incoherente con el flujo de reserva, que sí acota por organización: el
    roster decía "9 clases disponibles" y reservar fallaba con `plan_unavailable`.

    Se acota por la COLUMNA `organization` y no por el join `plan__organization`: ver
    `get_active_student_plan`, que es la misma decisión y tiene que dar el mismo resultado.
    """
    target_date = on_date or timezone.localdate()
    if not student_ids:
        return {}

    active_plans = (
        StudentPlan.objects.filter(
            user_id__in=student_ids,
            organization_id=organization_id,
        )
        .valid_on(target_date)
        .select_related('plan')
        # El eje de pago del estado sale de estas dos FKs inversas. Sin prefetch,
        # `_plan_status_payload` dispara una consulta por alumno del roster.
        .prefetch_related('origin_transactions', 'manual_payments')
        .order_by('user_id', '-start_date', '-id')
    )

    plan_by_user = {}
    for student_plan in active_plans:
        if student_plan.user_id not in plan_by_user:
            plan_by_user[student_plan.user_id] = student_plan
    return plan_by_user


def _get_latest_student_plan_map(student_ids, organization_id):
    """Última membresía de cada alumno en `organization_id` (vigente o no).

    Mismo acotamiento que `_get_active_student_plan_map`, y acá era aún más amplio: no
    filtraba ni por fecha ni por `is_active`, así que traía cualquier membresía histórica
    de cualquier organización.
    """
    if not student_ids:
        return {}

    plans = (
        StudentPlan.objects.filter(
            user_id__in=student_ids,
            organization_id=organization_id,
        )
        .select_related('plan')
        .prefetch_related('origin_transactions', 'manual_payments')   # mismo N+1 que en el mapa de vigentes
        .order_by('user_id', '-end_date', '-start_date', '-id')
    )

    plan_by_user = {}
    for student_plan in plans:
        if student_plan.user_id not in plan_by_user:
            plan_by_user[student_plan.user_id] = student_plan
    return plan_by_user


def _plan_status_payload(state, *, expose_reason=True):
    """Proyeccion del estado de la membresia al payload del roster.

    Ya no queda NADA que decidir aca: el predicado lo resuelve `describe_student_plan` y la
    presentacion —etiqueta, nivel de alerta y texto— sale de `_plan_alert`, la misma fuente
    que consume `StudentPlanSerializer`. Esta funcion solo renombra al prefijo `plan_` que
    usa el roster; mientras re-ramificaba sobre el string, una membresia sin saldo salia
    'safe' con el mensaje "20 dias vigentes".

    `plan_reason_code` es el motivo maquina del bloqueo, con los mismos codigos que
    `ReservationRuleError`: sin el, la UI le dice "sin clases disponibles" a un alumno que
    tiene 8 clases y lo unico que debe es la matricula.

    `expose_reason=False` REDACTA la membresia vigente-pero-inutilizable. La matricula
    impaga es un dato FINANCIERO y este es un endpoint operativo. gym_admin, manager y el
    profe de la clase la reciben entera porque ya podian inferirla: pueden POSTear la
    inscripcion y el 400 les devuelve 'Debes pagar la matricula de tu plan antes de
    reservar.'. El monitor no puede inscribir, asi que para el seria informacion nueva.

    Se redactan los CUATRO campos juntos. Degradar solo `plan_reason_code` no alcanzaba: el
    hecho seguia viajando en `plan_status`, en `plan_status_label` y en el mensaje de alerta
    —que es justo el que la UI pinta—, o sea la redaccion no redactaba nada.

    El BLOQUEO se sigue viendo (`has_available_classes` sale de `is_usable`, que no depende
    de esto); lo que se oculta es la CAUSA.

    `expose_reason` gobierna ADEMAS el eje de pago (`plan_payment_status`, 8.1), porque el
    corte de lector es exactamente el mismo: todos menos monitor. Pero la redaccion del eje
    de pago es INCONDICIONAL y por OMISION, y las dos diferencias son a proposito:

    * Incondicional: `plan_status` solo delata algo financiero en dos de sus formas
      (`exhausted`/`enrollment_fee_unpaid`), asi que se degrada solo ahi. `payment_status` ES
      el dato financiero en las tres. Si se omitiera solo cuando el alumno debe, la AUSENCIA
      del campo seria la deuda y el monitor la leeria igual.
    * Por omision: 7.3 pudo degradar a un balde opaco ('No disponible') porque el vocabulario
      de vigencia tiene un valor neutro que publicar y porque la UI ya pintaba esos campos.
      Aca los tres valores (`paid`/`unpaid`/`free`) son afirmaciones financieras —no existe
      un neutro— y el campo es nuevo, asi que nada se rompe al no mandarlo.
    """
    if not expose_reason and _is_redacted_for_non_financial(state):
        payload = {
            'plan_status': _REDACTED_PLAN_STATUS,
            'plan_status_label': _REDACTED_PLAN_LABEL,
            'plan_days_to_expiry': state.days_to_expiry,
            'plan_reason_code': REASON_PLAN_UNAVAILABLE,
            'plan_expiry_alert_level': AlertLevel.DANGER,
            'plan_expiry_alert_message': _REDACTED_PLAN_LABEL,
        }
    else:
        payload = {
            'plan_status': state.status,
            'plan_status_label': state.label,
            'plan_days_to_expiry': state.days_to_expiry,
            'plan_reason_code': state.reason_code,
            'plan_expiry_alert_level': state.alert_level,
            'plan_expiry_alert_message': state.alert_message,
        }
    if expose_reason:
        payload['plan_payment_status'] = state.payment_status
    return payload


# Balde opaco de la redaccion. NO es un `PlanStatus`: no pertenece al vocabulario del
# dominio, existe solo en el wire del roster y para un lector concreto.
_REDACTED_PLAN_STATUS = 'unavailable'
_REDACTED_PLAN_LABEL = 'No disponible'


def _is_redacted_for_non_financial(state):
    """Membresia DENTRO de su ventana pero inutilizable: saldo agotado o matricula impaga.

    Se deriva de las dos propiedades del estado en vez de enumerar estados, asi que un
    estado futuro con la misma forma queda redactado sin tocar esto.

    Los DOS caen al mismo balde a proposito. Si solo se ocultara la matricula, "No
    disponible" seria sinonimo de deuda y el monitor la inferiria por eliminacion; con los
    dos juntos, "sin saldo" —que no es dato financiero— le da cobertura. Ademas es lo que el
    monitor ya veia antes de 7.3, cuando el wire colapsaba los dos a `active`: no pierde
    nada que tuviera. Los estados no financieros (vencido, por iniciar, inactivo, sin plan)
    no entran, y se le siguen mostrando tal cual.
    """
    return state.passes_valid_on and not state.is_usable


def _may_see_plan_reason(user):
    """Quien recibe el motivo REAL del bloqueo. Todos los lectores del roster menos monitor.

    Se expresa como "monitor no" y no como "financiero si" a proposito: `manager` no pasa
    `FinancialResourcePermission`, pero si puede inscribir alumnos
    (`roles.is_org_admin`), o sea ya tiene el oraculo del 400. El corte real es "puede
    inscribir", y el unico lector del roster que no puede es el monitor.

    OJO, ESTE CHECK INLINE ES LA UNICA BARRERA: `FinancialResourcePermission` NO excluye al
    monitor —solo al manager—, y para `SAFE_METHODS` deja pasar a todo el resto
    (`permissions.py`: "monitor solo lectura"). Cualquier superficie NUEVA que publique
    estado financiero de una membresia tiene que repetir este corte a mano; apoyarse en la
    clase de permiso le entrega el dato al monitor sin que nada falle.

    Desde 8.1 este mismo flag gobierna `plan_payment_status`. Que el `manager` lo reciba es
    deliberado (misma regla que el motivo del bloqueo: puede inscribir), aunque tenga 403 en
    `/api/plans/` y `/api/teacher-payments/`: el corte de este endpoint es operativo, no el
    de la superficie financiera.
    """
    return not _is_monitor(user)


def _resolve_roster_student_plan(student_id, active_by_student, latest_by_student):
    """La UNICA membresia que el roster describe para este alumno.

    El saldo y la etiqueta salian de dos mapas distintos y con orden distinto
    (`-start_date` vs `-end_date`), asi que con dos membresias vigentes —4 BJJ + 8
    kickboxing, el caso que el modelo soporta a proposito— el roster mostraba el saldo de una
    con el vencimiento de la otra. Se elige UNA fila y todo se deriva de ella.

    Se prefiere la vigente y se cae a la ultima solo para poder etiquetar "Vencido" cuando no
    hay ninguna vigente; eso conserva exactamente el criterio de seleccion anterior.

    TODO #9: cual de las N vigentes es LA membresia del alumno sigue sin definirse. Este
    `or` hereda el desempate arbitrario de `_get_active_student_plan_map` (`-start_date`), el
    mismo que `get_active_student_plan` usa para descontar el consumo. Definir la regla de
    imputacion (por disciplina, eleccion del alumno, o la que vence antes) es parte de #9.
    """
    return active_by_student.get(student_id) or latest_by_student.get(student_id)


def _roster_plan_balance(student_plan, state):
    """`(available_classes, has_available_classes, unlimited_classes)` de LA MISMA fila.

    Solo se informa saldo cuando la fila elegida pasa `valid_on`: una membresia vencida
    conserva clases sin usar en la columna, pero ofrecerlas contradiria al flujo de reserva,
    que la rechaza. Es la misma incoherencia que ya se habia cerrado del lado de la
    organizacion ("9 clases disponibles" y reservar fallaba).

    OFRECER se decide con `is_usable`, no con `passes_valid_on`: es exactamente la
    propiedad que consulta `validate_student_plan_for_reservation`, asi que el roster y la
    reserva coinciden por construccion y no por coincidencia. `passes_valid_on` dejaba
    pasar la matricula impaga —dentro de la ventana y con saldo—, y el POST moria en 400.

    El SALDO se sigue informando tal cual. Forzarlo a 0 seria cambiar una mentira por otra:
    las 8 clases existen y el motivo del bloqueo lo dice `plan_reason_code`, no el saldo.
    """
    if student_plan is None or not state.passes_valid_on:
        return 0, False, False
    if student_plan.unlimited_classes:
        return None, state.is_usable, True
    return state.remaining_classes, state.is_usable, False


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
    user = request.user
    _sync_class_statuses(_class_sync_scope(user))

    if _is_superadmin(user):
        data = {
            'organizations': Organization.objects.count(),
            'branches': Branch.objects.count(),
            'teachers': User.objects.filter(role=User.Role.TEACHER).count(),
            'students': User.objects.filter(role=User.Role.STUDENT).count(),
            'gym_admins': User.objects.filter(role=User.Role.GYM_ADMIN).count(),
            'users': User.objects.count(),
        }
    elif roles.is_org_admin(user) and user.organization_id:
        # gym_admin y manager: conteos agregados de su organización (solo lectura).
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
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'login'

    def post(self, request):
        # Email es la clave de login. 'identifier' es un alias del payload (mismo valor,
        # un email). NO se acepta login por username: el username es interno y opaco.
        identifier = (request.data.get('email') or request.data.get('identifier') or '').strip()
        password = request.data.get('password', '')

        if not identifier or not password:
            return Response({'detail': 'email y password son requeridos.'}, status=status.HTTP_400_BAD_REQUEST)

        # La organización viene del subdominio (OrganizationMiddleware). El login está
        # ESTRICTAMENTE acotado a ese contexto: en un subdominio sólo entran usuarios de
        # esa org; en el apex SÓLO cuentas de plataforma (organization NULL = superadmin).
        # Sin fallbacks cross-org (evita escalada de tenant→plataforma y org→org).
        organization = getattr(request, 'organization', None)
        candidates = User.objects.filter(email__iexact=identifier, is_active=True)
        if organization is not None:
            candidates = candidates.filter(organization=organization)
        else:
            candidates = candidates.filter(organization__isnull=True)

        user = candidates.first()
        if user is None or not user.check_password(password):
            return Response({'detail': 'Credenciales inválidas.'}, status=status.HTTP_400_BAD_REQUEST)

        # Rotación: descartar cualquier token previo y emitir uno nuevo (created fresco).
        Token.objects.filter(user=user).delete()
        token = Token.objects.create(user=user)
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

    def patch(self, request):
        """Self-service acotado: el usuario completa/actualiza SU rut (y phone).
        SelfProfileSerializer deja de solo-lectura rol/org/is_active: no escala.
        Devuelve el perfil completo (CustomUserSerializer) para refrescar `me`."""
        serializer = SelfProfileSerializer(
            request.user, data=request.data, partial=True, context={'request': request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(CustomUserSerializer(request.user, context={'request': request}).data)


logger = logging.getLogger(__name__)


class PasswordResetRequestView(APIView):
    """Paso 1: el usuario pide el reset con su email.

    Responde siempre 200 (no revela si el email existe — anti-enumeración).
    """

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'password_reset'

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email']

        # Email único POR organización: el reset se acota a la org del subdominio
        # (o a cuentas de plataforma en el apex) para no quedar ambiguo entre orgs.
        User = get_user_model()
        organization = getattr(request, 'organization', None)
        candidates = User.objects.filter(email__iexact=email, is_active=True)
        if organization is not None:
            candidates = candidates.filter(organization=organization)
        else:
            candidates = candidates.filter(organization__isnull=True)
        user = candidates.first()
        if user:
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            base = organization_public_base_url(getattr(user, 'organization', None))
            reset_link = f"{base}/reset-password?uid={uid}&token={token}"
            try:
                send_mail(
                    subject='Restablecer tu contraseña — TYMRO',
                    message=(
                        'Recibimos una solicitud para restablecer tu contraseña.\n\n'
                        f'Abre este enlace para elegir una nueva contraseña:\n{reset_link}\n\n'
                        'Si no fuiste tú, puedes ignorar este correo.'
                    ),
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[email],
                    fail_silently=False,
                )
            except Exception:
                # El envío falló (proveedor caído/mal config): NO lo revelamos al
                # cliente (anti-enumeración). Logueamos para diagnóstico.
                logger.exception('Fallo enviando email de reset de contraseña a %s', email)

        return Response(
            {'detail': 'Si el email existe, te enviamos instrucciones para restablecer la contraseña.'}
        )


class PasswordResetConfirmView(APIView):
    """Paso 2: el usuario setea la nueva contraseña con uid + token del email."""

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'password_reset_confirm'

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        uid = serializer.validated_data['uid']
        token = serializer.validated_data['token']
        new_password = serializer.validated_data['new_password']

        User = get_user_model()
        try:
            user_pk = force_str(urlsafe_base64_decode(uid))
            user = User.objects.get(pk=user_pk, is_active=True)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            user = None

        if user is None or not default_token_generator.check_token(user, token):
            return Response(
                {'detail': 'El enlace no es válido o expiró. Pide uno nuevo.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            validate_password(new_password, user=user)
        except DjangoValidationError as exc:
            return Response({'new_password': list(exc.messages)}, status=status.HTTP_400_BAD_REQUEST)

        user.set_password(new_password)
        user.save(update_fields=['password'])
        # Invalidar sesiones por token previas tras el cambio de contraseña.
        Token.objects.filter(user=user).delete()

        return Response({'detail': 'Contraseña actualizada. Ya puedes iniciar sesión.'})


def _resolve_invite_org(slug):
    """Resuelve la organización por su slug, solo si está activa y con el registro
    público habilitado. El link es público (va en flyers/QR); el control de corte
    es ``public_registration_enabled`` (interruptor on/off). Devuelve None ante
    cualquier desajuste (404 → link inválido o desactivado)."""
    if not slug:
        return None
    try:
        return Organization.objects.get(
            slug=slug,
            is_active=True,
            public_registration_enabled=True,
        )
    except Organization.DoesNotExist:
        return None


def _resolve_public_org(request, slug=None):
    """Org del flujo público: por subdominio (``request.organization``, lo setea
    OrganizationMiddleware) y, como back-compat para links viejos servidos en el
    apex, por ``slug``. Respeta el interruptor ``public_registration_enabled``."""
    org = getattr(request, 'organization', None)
    if org is not None:
        return org if org.public_registration_enabled else None
    if slug:
        return _resolve_invite_org(slug)
    return None


class PublicInviteValidateView(APIView):
    """Valida el link público y devuelve la marca del gimnasio para la landing.
    Subdominio/slug desconocido o registro desactivado → 404."""

    # Endpoint público: no autenticamos. Un token caducado en el header no debe
    # producir 401 en una vista AllowAny (la autenticación corre antes que el permiso).
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'public_invite'

    def get(self, request):
        organization = _resolve_public_org(request, request.query_params.get('slug'))
        if organization is None:
            return Response({'detail': 'Link inválido o desactivado.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(PublicOrganizationBrandingSerializer(organization, context={'request': request}).data)


def send_verification_email(user):
    """Envía el correo de confirmación de email al ``user``. Deriva la org de
    ``user.organization``, arma el link de verificación con el subdominio público
    de esa org (``organization_public_base_url``) y lo envía vía el backend de
    correo (Resend/anymail en prod). Si el envío falla lo loguea y NO propaga: el
    usuario ya existe y puede reintentar o pedir un reenvío."""
    organization = user.organization
    org_name = organization.name if organization else 'TYMRO'
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    verify_link = f"{organization_public_base_url(organization)}/verify-email?uid={uid}&token={token}"
    try:
        send_mail(
            subject=f'Confirma tu email — {org_name}',
            message=(
                f'¡Bienvenido/a a {org_name}!\n\n'
                'Confirma tu email para activar tu cuenta y agendar tu clase de prueba gratis:\n'
                f'{verify_link}\n\n'
                'Si no fuiste tú, puedes ignorar este correo.'
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )
    except Exception:
        # El usuario ya se creó; si el correo de verificación falla, lo logueamos
        # y dejamos que la vista responda éxito igual (puede pedir reenvío).
        logger.exception('Fallo enviando email de verificación a %s', user.email)


class PublicRegisterView(APIView):
    """Registro público de un prospecto. La organización se fija server-side
    desde el slug; el rol es siempre STUDENT. El payload no puede elegir org/rol."""

    # Endpoint público: no autenticamos (ver PublicInviteValidateView).
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'public_register'

    def post(self, request):
        organization = _resolve_public_org(request, request.data.get('slug'))
        if organization is None:
            return Response({'detail': 'Link inválido o desactivado.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = PublicRegistrationSerializer(
            data=request.data, context={'organization': organization}
        )
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # username se auto-genera en CustomUser.save() (ya no es el email; el email
        # es único por org pero el username es global, así que no puede ser el email).
        user = User(
            email=data['email'],
            first_name=data['first_name'],
            last_name=data.get('last_name', ''),
            phone=data.get('phone', ''),
            role=User.Role.STUDENT,
            organization=organization,
            branch=None,
            is_active=True,
            email_verified=False,
            has_used_trial=False,
        )
        user.set_password(data['password'])
        user.save()

        send_verification_email(user)

        return Response(
            {'detail': 'Cuenta creada. Te enviamos un email para confirmar tu cuenta.'},
            status=status.HTTP_201_CREATED,
        )


class PublicVerifyEmailView(APIView):
    """Confirma el email con uid + token del correo y auto-loguea (devuelve token
    de auth) para que el prospecto pueda agendar su clase de prueba."""

    # Endpoint público: no autenticamos (ver PublicInviteValidateView). La identidad
    # se prueba con el uid+token del correo, no con el header Authorization.
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'public_verify'

    def post(self, request):
        uid = request.data.get('uid')
        token = request.data.get('token')
        try:
            user_pk = force_str(urlsafe_base64_decode(uid))
            user = User.objects.get(pk=user_pk, is_active=True)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            user = None

        if user is None or not default_token_generator.check_token(user, token):
            return Response(
                {'detail': 'El enlace no es válido o expiró.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not user.email_verified:
            user.email_verified = True
            user.save(update_fields=['email_verified'])

        Token.objects.filter(user=user).delete()
        auth_token = Token.objects.create(user=user)
        return Response(
            {
                'token': auth_token.key,
                'user': CustomUserSerializer(user, context={'request': request}).data,
                'role': user.role,
                'organization': user.organization_id,
                'branch': user.branch_id,
            }
        )


class ResendVerificationView(APIView):
    """Reenvía el correo de confirmación al usuario autenticado. Si su email ya
    está verificado es no-op (200 sin enviar). Acotado por throttle
    (scope 'resend_verification') contra spam de reenvíos."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'resend_verification'

    def post(self, request):
        user = request.user
        if user.email_verified:
            return Response({'detail': 'Tu email ya está confirmado.'})
        send_verification_email(user)
        return Response({'detail': 'Te reenviamos el correo de confirmación.'})


TRIAL_WINDOW_DEFAULT_DAYS = 7


def _trial_window_days(organization):
    """Días de validez de la clase de prueba para la org (#19). Default 7 si no hay
    config o si el valor guardado es inválido (<= 0)."""
    days = getattr(organization, 'trial_validity_days', None)
    if not days or days <= 0:
        return TRIAL_WINDOW_DEFAULT_DAYS
    return days


class PublicTrialClassesView(APIView):
    """Lista las próximas clases elegibles para prueba con cupo, de la organización
    del alumno autenticado, dentro de la ventana de validez de la prueba."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if not _is_student(user) or not user.organization_id:
            return Response([], status=status.HTTP_200_OK)

        now = timezone.now()
        window_end = now + timedelta(days=_trial_window_days(user.organization))
        queryset = (
            GymClass.objects.filter(
                organization_id=user.organization_id,
                is_trial_eligible=True,
                status=GymClass.Status.SCHEDULED,
                start_datetime__gt=now,
                # Ventana de validez de la prueba (#19): no se ofrecen clases más allá
                # de la ventana configurada por la org (default 7 días).
                start_datetime__lte=window_end,
            )
            .select_related('branch', 'teacher', 'class_type')
            .order_by('start_datetime')
        )
        serializer = PublicTrialClassSerializer(queryset, many=True, context={'request': request})
        # Solo las que aún tienen cupo.
        data = [item for item in serializer.data if item['seats_left'] > 0]
        return Response(data)


class PublicTrialBookView(APIView):
    """Inscribe al alumno en UNA clase de prueba gratis. Requiere email verificado
    y que no haya usado su prueba antes. No consume plan (require_plan=False)."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        if not _is_student(user):
            raise PermissionDenied('Solo alumnos pueden agendar una clase de prueba.')

        gym_class_id = request.data.get('gym_class')
        if not gym_class_id:
            return Response({'detail': 'Falta la clase (gym_class).'}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            locked_user = User.objects.select_for_update().get(pk=user.pk)
            if not locked_user.email_verified:
                return Response(
                    {'detail': 'Confirma tu email antes de agendar tu clase de prueba.'},
                    status=status.HTTP_403_FORBIDDEN,
                )
            if locked_user.has_used_trial:
                return Response(
                    {'detail': 'Ya usaste tu clase de prueba gratis.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            try:
                gym_class = GymClass.objects.get(
                    pk=gym_class_id,
                    organization_id=locked_user.organization_id,
                    is_trial_eligible=True,
                )
            except GymClass.DoesNotExist:
                return Response(
                    {'detail': 'Esa clase no está disponible para prueba.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Ventana de validez de la prueba (#19): no se puede agendar fuera de ella.
            window_end = timezone.now() + timedelta(days=_trial_window_days(gym_class.organization))
            if gym_class.start_datetime > window_end:
                return Response(
                    {'detail': 'Esa clase está fuera de la ventana para agendar tu clase de prueba.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            try:
                reserve_student_in_class(
                    student=locked_user,
                    gym_class=gym_class,
                    require_plan=False,
                    is_trial=True,
                )
            except ReservationRuleError as exc:
                return Response({'detail': exc.message}, status=status.HTTP_400_BAD_REQUEST)

            locked_user.has_used_trial = True
            locked_user.save(update_fields=['has_used_trial'])

        return Response(
            {'detail': '¡Listo! Reservaste tu clase de prueba gratis.'},
            status=status.HTTP_201_CREATED,
        )


def _build_qr_token(organization_id):
    now = timezone.now()
    expires_at = now + timedelta(seconds=QR_TOKEN_ACCEPTANCE_SECONDS)
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


def _get_organization_by_screen_code(raw_code):
    """Resuelve la organización por su código de pantalla PERMANENTE
    (``attendance_screen_code``). Se usa para el enlace automático por gym, que
    muestra el QR rotando sin iniciar sesión temporal ni tipear código."""
    code = _normalize_attendance_screen_code(raw_code)
    if not code:
        raise ValidationError({'code': 'Codigo de pantalla requerido.'})
    organization = Organization.objects.filter(attendance_screen_code=code, is_active=True).first()
    if not organization:
        raise ValidationError({'code': 'Codigo de pantalla invalido.'})
    return organization


def _attendance_screen_session_payload(request, organization):
    expires_at = organization.attendance_screen_session_expires_at
    seconds_left = 0
    if expires_at:
        seconds_left = max(0, int((expires_at - timezone.now()).total_seconds()))
    auto_path = f'/attendance/screen/{organization.attendance_screen_code}'
    return {
        'organization_name': organization.name,
        'attendance_screen_code': organization.attendance_screen_code,
        'attendance_screen_session_code': organization.attendance_screen_session_code,
        'attendance_screen_session_expires_at': expires_at,
        'attendance_screen_session_expires_in_seconds': seconds_left,
        'attendance_screen_session_ttl_hours': ATTENDANCE_SCREEN_SESSION_TTL_HOURS,
        'attendance_screen_path': '/attendance/screen',
        'attendance_screen_url': request.build_absolute_uri('/attendance/screen'),
        # Enlace automático por gym (recomendado): abre y muestra el QR solo.
        'attendance_screen_auto_path': auto_path,
        'attendance_screen_auto_url': request.build_absolute_uri(auto_path),
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
        'expires_in_seconds': QR_TOKEN_REFRESH_SECONDS,
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


def _build_checkin_grant(student_id, gym_class_id, organization_id):
    """Emite el permiso de un solo uso para confirmar asistencia tras un preview
    válido. Firmado con `signing.dumps` (lleva timestamp para el TTL del grant)."""
    payload = {
        'student_id': student_id,
        'gym_class_id': gym_class_id,
        'organization_id': organization_id,
        'issued_at': timezone.now().isoformat(),
    }
    return signing.dumps(payload, salt=QR_CHECKIN_GRANT_SALT)


def _load_checkin_grant(raw_grant):
    if not raw_grant:
        raise ValidationError({'grant': 'Permiso de asistencia requerido.'})
    try:
        payload = signing.loads(raw_grant, salt=QR_CHECKIN_GRANT_SALT, max_age=QR_CHECKIN_GRANT_TTL_SECONDS)
    except signing.SignatureExpired:
        raise ValidationError({'grant': 'El permiso de asistencia caducó. Vuelve a escanear el código.'})
    except signing.BadSignature:
        raise ValidationError({'grant': 'Permiso de asistencia inválido.'})
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


def _teacher_qr_class_or_403(teacher, class_id):
    """Autoriza a un profesor a exponer el QR SOLO en el contexto de una clase que
    dicta él y que pertenece a SU propia organización. Devuelve la clase o levanta
    403. El filtro por (id, organization_id, teacher_id) es aislante: una clase de
    otra org (o de otro profe) simplemente no aparece → nunca se filtra cross-tenant
    ni se autoriza una clase ajena."""
    if not class_id:
        raise PermissionDenied('Indica la clase para exponer el QR de asistencia.')
    try:
        class_id = int(class_id)
    except (TypeError, ValueError):
        # class_id malformado (no numérico): se trata como clase inexistente → 403,
        # nunca un 500 por castear el PK.
        raise PermissionDenied('Solo puedes exponer el QR de una clase que dictas en tu gimnasio.')
    gym_class = GymClass.objects.filter(
        id=class_id,
        organization_id=teacher.organization_id,
        teacher_id=teacher.id,
    ).first()
    if gym_class is None:
        raise PermissionDenied('Solo puedes exponer el QR de una clase que dictas en tu gimnasio.')
    return gym_class


class AttendanceQrCurrentView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if not user.organization_id:
            raise PermissionDenied('Solo el staff del gimnasio puede generar el QR de asistencia.')

        # gym_admin: genera el QR de su org + gestiona la sesión de pantalla (como hoy).
        if _is_gym_admin(user):
            payload = _attendance_qr_payload(request, user.organization)
            payload.update(_attendance_screen_session_payload(request, user.organization))
            return Response(payload)

        # teacher: puede exponer el QR SOLO de una clase que dicta él, y siempre de
        # su propia org (scoped por org). No recibe la gestión de la pantalla de
        # recepción: solo el QR rotante para mostrarlo en su clase.
        if _is_teacher(user):
            _teacher_qr_class_or_403(user, request.query_params.get('class_id'))
            return Response(_attendance_qr_payload(request, user.organization))

        raise PermissionDenied('No tienes permiso para generar el QR de asistencia.')


class AttendanceQrScreenView(APIView):
    # Pantalla pública de recepción: no autenticamos. Un token caducado en el
    # header no debe producir 401 en esta vista AllowAny.
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        organization = _get_public_attendance_organization(request.data.get('code'))
        return Response(_attendance_qr_payload(request, organization))


class AttendanceQrScreenAutoView(APIView):
    """Pantalla automática por gimnasio: dado el código PERMANENTE en la URL,
    devuelve el QR rotante sin requerir sesión temporal. Pensada para el enlace
    fijo de recepción (TV/tablet) que se abre y muestra el QR solo."""

    # Pantalla pública por gimnasio: no autenticamos (ver AttendanceQrScreenView).
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        organization = _get_organization_by_screen_code(request.query_params.get('code'))
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
        # Frescura del QR se valida UNA sola vez, aquí (firma + ventana + enrollment).
        payload = _load_qr_token(request.query_params.get('token'))
        preview = _qr_preview_payload(request.user, payload['organization_id'])
        # Si el alumno puede marcar, emitimos el permiso de un solo uso para confirmar.
        if preview.get('status') == 'ready' and preview.get('class'):
            preview['checkin_grant'] = _build_checkin_grant(
                student_id=request.user.id,
                gym_class_id=preview['class']['id'],
                organization_id=payload['organization_id'],
            )
        return Response(preview)


class AttendanceQrCheckInView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not _is_student(request.user):
            raise PermissionDenied('Solo alumnos pueden marcar asistencia por QR.')

        # Confirma con el GRANT, no con el token del QR: ya no puede vencerse a mitad.
        grant = _load_checkin_grant(request.data.get('grant'))

        if grant.get('student_id') != request.user.id:
            raise PermissionDenied('Este permiso de asistencia no es tuyo.')
        if grant.get('organization_id') != request.user.organization_id:
            return Response(
                {'detail': 'Este permiso pertenece a otro gimnasio.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            gym_class = GymClass.objects.get(
                id=grant.get('gym_class_id'),
                organization_id=request.user.organization_id,
            )
        except GymClass.DoesNotExist:
            return Response(
                {'detail': 'La clase del permiso ya no está disponible.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        existing = Attendance.objects.filter(gym_class=gym_class, student=request.user).first()
        if existing and existing.status == Attendance.Status.PRESENT:
            # Unicidad por (student, clase): el grant es de un solo uso efectivo.
            return Response(
                {
                    'status': 'already_registered',
                    'detail': 'Tu asistencia ya fue registrada para esta clase.',
                    'class': _serialize_qr_class(gym_class),
                    'attendance_status': existing.status,
                    'attendance_source': existing.source,
                    'next_check_in_at': None,
                }
            )

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
        return Response(
            {
                'status': 'registered',
                'detail': 'Tu asistencia fue registrada correctamente.',
                'class': _serialize_qr_class(gym_class),
                'attendance_status': attendance.status,
                'attendance_source': attendance.source,
                'attendance_id': attendance.id,
                'created': created,
                'next_check_in_at': None,
            }
        )


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

    def destroy(self, request, *args, **kwargs):
        """Guarda contra el `ProtectedError` de `StudentPlan.organization`.

        Desde 0030 la membresía tiene FK propia a la organización con `PROTECT`, así que
        la vieja cascada Organization → Plan → StudentPlan → ConsumptionLog ya no corre:
        borrar la organización se llevaba en silencio el historial de consumo y los
        precios cobrados. Sin esta guarda el intento sale como 500 con el ProtectedError
        crudo; acá se traduce a un 400 que dice qué lo bloquea. Mismo criterio que
        `BranchViewSet.destroy` y `MembershipPlanViewSet.destroy`.
        """
        instance = self.get_object()
        if not _is_superadmin(request.user):
            raise PermissionDenied('Solo superadmin puede eliminar organizaciones.')

        sold = StudentPlan.objects.filter(organization_id=instance.id).count()
        if sold:
            return Response(
                {
                    'detail': (
                        f'La organización tiene {sold} membresías vendidas: no se puede '
                        'eliminar sin destruir el historial de consumo y los precios '
                        'cobrados que las respaldan.'
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError:
            # Red de fondo, por dos motivos. El conteo de arriba y el DELETE no comparten
            # lock: entre medio, un webhook de pago puede activar una membresía. Y la lista
            # de bloqueadores está cableada a StudentPlan —hoy es el único PROTECT hacia
            # Organization—, así que el próximo que se agregue volvería a dar 500.
            return Response(
                {
                    'detail': (
                        'La organización tiene datos que no se pueden eliminar en '
                        'cascada. Revisá sus membresías antes de borrarla.'
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

    @action(detail=True, methods=['post'], url_path='set-public-registration')
    def set_public_registration(self, request, pk=None):
        organization = self.get_object()
        if not _can_manage_org_resource(request.user, organization.id):
            raise PermissionDenied('No puedes cambiar el registro público de esta organización.')
        organization.public_registration_enabled = _parse_bool(request.data.get('enabled'), default=True)
        organization.save(update_fields=['public_registration_enabled', 'updated_at'])
        return Response(self.get_serializer(organization).data)

    @action(detail=True, methods=['get', 'put'], url_path='trial-followup-config')
    def trial_followup_config(self, request, pk=None):
        """Config del email de seguimiento de clases de prueba de la organización.

        GET devuelve la config (la crea con defaults si aún no existe); PUT la
        actualiza. Solo superadmin (cualquier org) o el gym_admin de ESA org.
        """
        # Buscamos sin pasar por get_queryset() (que filtra a la org del actor)
        # para distinguir 404 (org inexistente) de 403 (org ajena).
        organization = Organization.objects.filter(pk=pk).first()
        if organization is None:
            raise NotFound('Organización no encontrada.')
        if not _can_manage_org_resource(request.user, organization.id):
            raise PermissionDenied('No tienes permisos para gestionar esta configuración.')

        config, _ = TrialFollowupConfiguration.objects.get_or_create(organization=organization)

        if request.method == 'GET':
            return Response(TrialFollowupConfigurationSerializer(config).data)

        serializer = TrialFollowupConfigurationSerializer(config, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class BranchViewSet(ModelViewSet):
    queryset = Branch.objects.select_related('organization').all()
    serializer_class = BranchSerializer

    def get_queryset(self):
        user = self.request.user
        # Partimos siempre de un queryset fresco: devolver self.queryset (la
        # instancia de clase) reusaría su _result_cache entre requests del mismo
        # proceso y dejaría el listado obsoleto hasta reiniciar el worker.
        queryset = Branch.objects.select_related('organization').all()

        if _is_superadmin(user):
            return queryset
        if user.organization_id:
            return queryset.filter(organization_id=user.organization_id)
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

    @staticmethod
    def _cascade_blocker(branch):
        """Qué historial arrastraría el hard delete de esta sucursal, o None si es seguro.

        `Branch` tiene tres FKs entrantes con CASCADE: `GymClass.branch`,
        `ClassTemplate.branch` y `Holiday.branch`. Borrar las clases se lleva por delante
        Enrollment / Attendance / ConsumptionLog, y los ConsumptionLog se van SIN
        decrementar `StudentPlan.classes_used` (ese contador solo baja por
        `rollback_consumption_for_enrollment`, que la cascada nunca ejecuta): el alumno
        queda con clases consumidas fantasma. Las series arrastran además las
        recurrencias de alumnos que `delete_template_safely` se niega a borrar, así que
        mirar solo `classes` dejaría a la sucursal como puerta trasera de esa validación.

        La cuarta comprobación NO es por cascada sino al revés: `TeacherPaymentRule.branch`
        es SET_NULL, y en `_match_rule_for_class` una regla con `branch=NULL` es la regla
        COMODÍN que aplica a todas las sedes. Borrar la sucursal no borra la regla: la
        convierte en global, y una regla acotada a una sede pasa a pagar las clases de
        todas las demás.

        Las otras FKs SET_NULL —`CustomUser.branch`, `Person.branch`, `StudentPlan.branch`
        y `ConsumptionLog.branch`— se evaluaron y se aceptan a propósito: ahí `NULL`
        significa "sin sede registrada", que es una pérdida de dato menor y no una
        inversión de alcance. No son un olvido.
        """
        if branch.classes.exists():
            return (
                'La sucursal tiene clases asociadas: se desactivó en vez de eliminarse '
                'para no corromper el historial de clases ni los saldos de los planes '
                'de los alumnos.'
            )
        if branch.class_templates.exists():
            return (
                'La sucursal tiene series de clases asociadas: se desactivó en vez de '
                'eliminarse para conservar el historial y las recurrencias de los alumnos.'
            )
        if branch.holidays.exists():
            return (
                'La sucursal tiene feriados propios: se desactivó en vez de eliminarse '
                'para conservar su historial de configuración.'
            )
        if branch.payment_rules.exists():
            return (
                'La sucursal tiene reglas de pago a profesores asociadas: se desactivó '
                'en vez de eliminarse porque borrarla convertiría esas reglas en reglas '
                'para todas las sucursales.'
            )
        if branch.exclusive_plans.exists():
            return (
                'La sucursal tiene planes exclusivos asociados: se desactivó en vez de '
                'eliminarse porque borrarla convertiría esos planes en planes globales '
                'de toda la organización.'
            )
        return None

    def destroy(self, request, *args, **kwargs):
        # Se sobreescribe `destroy` y no solo `perform_destroy` porque el soft-delete es
        # una ESCRITURA que debe persistir junto a una respuesta de ERROR. Lanzar una
        # APIException haría que DRF invocara `set_rollback()`: con `ATOMIC_REQUESTS`
        # activo —o si algún día este método se envolviera en `transaction.atomic`— la
        # desactivación se revertiría en silencio mientras la respuesta seguiría diciendo
        # que se desactivó. Devolver un `Response` explícito no dispara ese rollback.
        instance = self.get_object()  # ya scoped por get_queryset(): 404 si es de otra org

        user = request.user
        if not (
            _is_superadmin(user)
            or (_is_gym_admin(user) and instance.organization_id == user.organization_id)
        ):
            raise PermissionDenied('No tienes permisos para eliminar esta sucursal.')

        # La guarda aplica también al superadmin: la cascada corrompe los saldos igual
        # sin importar quién dispare el borrado.
        blocker = self._cascade_blocker(instance)
        if blocker:
            if instance.is_active:
                instance.is_active = False
                instance.save(update_fields=['is_active', 'updated_at'])
            return Response({'detail': blocker}, status=status.HTTP_400_BAD_REQUEST)

        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


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
                    # Sin organización solo se listan usuarios de plataforma
                    # (superadmins, que no tienen organización); el resto exige org.
                    if role in roles.PLATFORM_ROLES:
                        return queryset.filter(role=role)
                    return queryset.none()
                queryset = queryset.filter(organization_id=organization_id)

            if role:
                queryset = queryset.filter(role=role)
            return queryset

        # gym_admin/manager (escritura) y monitor (solo lectura) ven su organización.
        if (roles.is_org_admin(user) or _is_monitor(user)) and user.organization_id:
            role = self.request.query_params.get('role')
            queryset = queryset.filter(organization_id=user.organization_id)
            if role:
                queryset = queryset.filter(role=role)
            return queryset

        if _is_teacher(user) or _is_student(user) or _is_monitor(user):
            return queryset.filter(id=user.id)
        return queryset.none()

    def list(self, request, *args, **kwargs):
        if _is_teacher(request.user) or _is_student(request.user):
            raise PermissionDenied('No tienes acceso al listado general de usuarios.')
        if (
            _is_superadmin(request.user)
            and not request.query_params.get('organization_id')
            and request.query_params.get('role') not in roles.PLATFORM_ROLES
        ):
            raise PermissionDenied('Debes filtrar por organization_id para listar usuarios como superadmin.')
        return super().list(request, *args, **kwargs)

    @action(detail=False, methods=['get'], url_path='assignable-roles')
    def assignable_roles(self, request):
        """Roles que request.user puede asignar, como [{'value','label'}].
        La matriz y los labels viven SOLO en accounts/roles.py."""
        return Response(roles.assignable_role_choices(request.user))

    def _validate_write_permissions(self, data=None, instance=None):
        """Autorización de escrituras sobre usuarios. La matriz de qué rol puede
        asignar/gestionar quién vive SOLO en accounts/roles.py."""
        user = self.request.user
        data = data or {}
        requested_role = data.get('role')
        requested_organization = data.get('organization')

        if not roles.assignable_roles(user):
            raise PermissionDenied('No tienes permisos para gestionar usuarios.')

        if instance is not None and not roles.can_assign(user, instance.role):
            raise PermissionDenied('No tienes permisos para gestionar usuarios con ese rol.')

        if requested_role and not roles.can_assign(user, requested_role):
            raise PermissionDenied('No puedes asignar ese rol.')

        if roles.role_of(user) in roles.PLATFORM_ROLES:
            return

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

        if roles.is_org_admin(user):
            save_kwargs['organization'] = user.organization

        created_user = serializer.save(**save_kwargs)

        if created_user.role == User.Role.SUPERADMIN:
            created_user.is_staff = True
            created_user.is_superuser = True
            created_user.save(update_fields=['is_staff', 'is_superuser'])

    def perform_update(self, serializer):
        instance = self.get_object()
        self._validate_write_permissions(self.request.data, instance=instance)

        if roles.is_org_admin(self.request.user):
            serializer.save(organization=self.request.user.organization)
        else:
            serializer.save()

    def perform_destroy(self, instance):
        self._validate_write_permissions(instance=instance)
        instance.delete()


class PersonViewSet(ModelViewSet):
    queryset = Person.objects.select_related('organization', 'branch').all()
    serializer_class = PersonSerializer
    permission_classes = [IsSuperAdminOrGymAdmin]

    def get_queryset(self):
        user = self.request.user
        if _is_superadmin(user):
            return self.queryset
        if user.organization_id:
            return self.queryset.filter(organization_id=user.organization_id)
        return self.queryset.none()

    def perform_create(self, serializer):
        user = self.request.user
        if _is_superadmin(user):
            serializer.save()
        else:
            serializer.save(organization=user.organization)

    def perform_update(self, serializer):
        user = self.request.user
        if not _is_superadmin(user) and serializer.instance.organization_id != user.organization_id:
            raise PermissionDenied('No puedes editar registros de otra organización.')
        if _is_superadmin(user):
            serializer.save()
        else:
            serializer.save(organization=user.organization)

    def perform_destroy(self, instance):
        user = self.request.user
        if not _is_superadmin(user) and instance.organization_id != user.organization_id:
            raise PermissionDenied('No puedes eliminar registros de otra organización.')
        instance.delete()


class ClassTypeViewSet(ModelViewSet):
    queryset = ClassType.objects.all()
    serializer_class = ClassTypeSerializer
    permission_classes = [OperationalResourcePermission]

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
        if roles.is_org_admin(user):
            serializer.save(organization=user.organization)
            return
        raise PermissionDenied('No tienes permisos para crear tipos de clase.')

    def perform_update(self, serializer):
        user = self.request.user
        class_type = self.get_object()
        if _is_superadmin(user):
            serializer.save()
            return
        if roles.is_org_admin(user) and class_type.organization_id == user.organization_id:
            serializer.save(organization=user.organization)
            return
        raise PermissionDenied('No tienes permisos para editar este tipo de clase.')

    def perform_destroy(self, instance):
        user = self.request.user
        if _is_superadmin(user):
            instance.delete()
            return
        if roles.is_org_admin(user) and instance.organization_id == user.organization_id:
            instance.delete()
            return
        raise PermissionDenied('No tienes permisos para eliminar este tipo de clase.')


class DisciplineViewSet(ModelViewSet):
    queryset = Discipline.objects.all()
    serializer_class = DisciplineSerializer
    permission_classes = [OperationalResourcePermission]

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
        if roles.is_org_admin(user):
            serializer.save(organization=user.organization)
            return
        raise PermissionDenied('No tienes permisos para crear disciplinas.')

    def perform_update(self, serializer):
        user = self.request.user
        discipline = self.get_object()
        if _is_superadmin(user):
            serializer.save()
            return
        if roles.is_org_admin(user) and discipline.organization_id == user.organization_id:
            serializer.save(organization=user.organization)
            return
        raise PermissionDenied('No tienes permisos para editar esta disciplina.')

    def perform_destroy(self, instance):
        user = self.request.user
        if _is_superadmin(user):
            instance.delete()
            return
        if roles.is_org_admin(user) and instance.organization_id == user.organization_id:
            instance.delete()
            return
        raise PermissionDenied('No tienes permisos para eliminar esta disciplina.')


class HolidayViewSet(ModelViewSet):
    queryset = Holiday.objects.select_related('organization', 'branch').all()
    serializer_class = HolidaySerializer
    permission_classes = [OperationalResourcePermission]

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
        if (roles.is_org_admin(user) or _is_monitor(user)) and user.organization_id:
            queryset = queryset.filter(models.Q(scope=Holiday.Scope.GLOBAL) | models.Q(organization_id=user.organization_id))
            return _apply_ordering(queryset, ordering, ordering_map, default_ordering)
        return queryset.none()

    def perform_create(self, serializer):
        user = self.request.user
        if _is_superadmin(user):
            serializer.save()
            return
        if roles.is_org_admin(user):
            serializer.save(organization=user.organization, source_type=Holiday.SourceType.MANUAL)
            return
        raise PermissionDenied('No tienes permisos para crear festivos.')

    def perform_update(self, serializer):
        user = self.request.user
        holiday = self.get_object()
        if _is_superadmin(user):
            serializer.save()
            return
        if roles.is_org_admin(user):
            if holiday.scope == Holiday.Scope.GLOBAL:
                raise PermissionDenied('No puedes editar festivos globales.')
            if holiday.organization_id != user.organization_id:
                raise PermissionDenied('No tienes permisos para este festivo.')
            if holiday.source_type == Holiday.SourceType.SYSTEM:
                allowed_keys = {'is_active'}
                # Se comparan VALORES, no claves: `HolidaySerializer.validate` inyecta
                # siempre `organization` y `branch` (persiste lo que decidió
                # `Holiday.clean()`), así que contar las claves dejaba la guarda
                # insatisfacible para cualquier PATCH; restarlas a ciegas, en cambio, dejaba
                # pasar un cambio REAL de sucursal en un festivo de sistema con
                # `scope=branch`, que es lo que decide qué sede saltea la generación.
                changed_keys = {
                    key for key, value in serializer.validated_data.items()
                    if value != getattr(holiday, key, None)
                }
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
        if roles.is_org_admin(user):
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

        if (roles.is_org_admin(user) or _is_monitor(user)) and user.organization_id:
            queryset = self.queryset.filter(organization_id=user.organization_id)
            queryset = apply_common_filters(queryset)
            queryset = _apply_ordering(queryset, ordering, ordering_map, default_ordering)
            _sync_class_statuses(queryset)
            return queryset

        if _is_teacher(user):
            # Acotado también por organización: ver `_is_own_class_teacher`. Sin esto, una
            # clase con `teacher_id` rancio se listaba y `_sync_class_statuses` (que
            # ESCRIBE) corría sobre la organización que el profe ya dejó.
            queryset = (
                self.queryset.filter(teacher_id=user.id, organization_id=user.organization_id)
                if user.organization_id else self.queryset.none()
            )
            queryset = apply_common_filters(queryset)
            queryset = _apply_ordering(queryset, ordering, ordering_map, default_ordering)
            _sync_class_statuses(queryset)
            return queryset

        if _is_student(user):
            mine_param = str(self.request.query_params.get('mine', '')).lower()
            queryset = self.queryset.filter(organization_id=user.organization_id) if user.organization_id else self.queryset.none()
            # Una clase suspendida no es visible ni reservable para alumnos.
            queryset = queryset.exclude(status=GymClass.Status.SUSPENDED)
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
        if roles.is_org_admin(user):
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
        if roles.is_org_admin(user) and gym_class.organization_id == user.organization_id:
            serializer.save(organization=user.organization)
            return
        raise PermissionDenied('No tienes permisos para editar esta clase.')

    def perform_destroy(self, instance):
        user = self.request.user
        if not (
            _is_superadmin(user)
            or (roles.is_org_admin(user) and instance.organization_id == user.organization_id)
        ):
            raise PermissionDenied('No tienes permisos para eliminar esta clase.')

        # `ConsumptionLog.class_instance` es CASCADE: borrar la clase se llevaría los
        # consumos SIN decrementar `StudentPlan.classes_used`, dejando al alumno con
        # clases consumidas fantasma. Se devuelve el saldo primero, en la misma
        # transacción que el borrado, para que nunca quede el contador inflado sin log.
        with transaction.atomic():
            revert_consumption_for_class(instance)
            instance.delete()

    @action(detail=True, methods=['get'], url_path='enrolled-students')
    def enrolled_students(self, request, pk=None):
        gym_class = self.get_object()
        user = request.user

        if not (
            _is_superadmin(user)
            or ((roles.is_org_admin(user) or _is_monitor(user)) and gym_class.organization_id == user.organization_id)
            or _is_own_class_teacher(user, gym_class)
        ):
            raise PermissionDenied('No tienes permisos para ver los alumnos inscritos en esta clase.')

        expose_reason = _may_see_plan_reason(user)
        enrollments = gym_class.enrollments.filter(status='active').select_related('student')
        student_ids = list(enrollments.values_list('student_id', flat=True))
        active_plan_by_student = _get_active_student_plan_map(student_ids, gym_class.organization_id)
        latest_plan_by_student = _get_latest_student_plan_map(student_ids, gym_class.organization_id)
        today = timezone.localdate()
        attendance_by_student = {
            item.student_id: item
            for item in gym_class.attendances.select_related('student', 'marked_by').all()
        }

        results = []
        for enrollment in enrollments:
            student = enrollment.student
            attendance = attendance_by_student.get(student.id)
            student_plan = _resolve_roster_student_plan(
                student.id, active_plan_by_student, latest_plan_by_student
            )
            state = describe_student_plan(student_plan, today)
            remaining_classes, has_available, unlimited = _roster_plan_balance(student_plan, state)
            plan_status = _plan_status_payload(state, expose_reason=expose_reason)
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
                    'has_available_classes': has_available,
                    'unlimited_classes': unlimited,
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
            or ((roles.is_org_admin(user) or _is_monitor(user)) and gym_class.organization_id == user.organization_id)
            or _is_own_class_teacher(user, gym_class)
        ):
            raise PermissionDenied('No tienes permisos para listar alumnos inscribibles en esta clase.')

        expose_reason = _may_see_plan_reason(user)
        active_enrolled_ids = set(gym_class.enrollments.filter(status='active').values_list('student_id', flat=True))
        candidates = User.objects.filter(
            role=User.Role.STUDENT,
            organization_id=gym_class.organization_id,
            is_active=True,
        ).order_by('first_name', 'last_name', 'username')
        candidate_ids = list(candidates.values_list('id', flat=True))
        active_plan_by_student = _get_active_student_plan_map(candidate_ids, gym_class.organization_id)
        latest_plan_by_student = _get_latest_student_plan_map(candidate_ids, gym_class.organization_id)
        today = timezone.localdate()

        results = []
        for student in candidates:
            if student.id in active_enrolled_ids:
                continue
            student_plan = _resolve_roster_student_plan(
                student.id, active_plan_by_student, latest_plan_by_student
            )
            state = describe_student_plan(student_plan, today)
            remaining_classes, has_available, unlimited = _roster_plan_balance(student_plan, state)
            plan_status = _plan_status_payload(state, expose_reason=expose_reason)
            full_name = f'{student.first_name} {student.last_name}'.strip()
            results.append(
                {
                    'id': student.id,
                    'username': student.username,
                    'name': full_name or student.username,
                    'email': student.email,
                    'branch_id': student.branch_id,
                    'available_classes': remaining_classes,
                    'has_available_classes': has_available,
                    'unlimited_classes': unlimited,
                    **plan_status,
                }
            )

        return Response(results)

    @action(detail=True, methods=['post'], url_path='attendance')
    def attendance(self, request, pk=None):
        gym_class = self.get_object()
        user = request.user

        if not (
            _is_superadmin(user)
            or (roles.is_org_admin(user) and gym_class.organization_id == user.organization_id)
            or _is_own_class_teacher(user, gym_class)
        ):
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
        _refund_active_enrollments_for_cancelled_class(gym_class)

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

    @action(detail=True, methods=['post'], url_path='suspend')
    def suspend(self, request, pk=None):
        gym_class = self.get_object()
        user = request.user

        if not _can_close_or_cancel(user, gym_class):
            raise PermissionDenied('No tienes permisos para suspender esta clase.')
        if gym_class.status not in [GymClass.Status.SCHEDULED, GymClass.Status.IN_PROGRESS]:
            return Response(
                {'detail': 'Solo puedes suspender clases programadas o en progreso.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        reason = str(request.data.get('suspend_reason', '')).strip()
        reactivation_date = request.data.get('reactivation_expected_date') or None

        gym_class.status = GymClass.Status.SUSPENDED
        gym_class.suspend_reason = reason
        gym_class.suspended_at = timezone.now()
        gym_class.suspended_by = user
        gym_class.reactivation_expected_date = reactivation_date
        gym_class.is_active = False
        gym_class.save(update_fields=[
            'status', 'suspend_reason', 'suspended_at', 'suspended_by',
            'reactivation_expected_date', 'is_active', 'updated_at',
        ])

        self._notify_suspension(gym_class)
        return Response(self.get_serializer(gym_class).data)

    @action(detail=True, methods=['post'], url_path='reactivate')
    def reactivate(self, request, pk=None):
        gym_class = self.get_object()
        user = request.user

        if not _can_close_or_cancel(user, gym_class):
            raise PermissionDenied('No tienes permisos para reactivar esta clase.')
        if gym_class.status != GymClass.Status.SUSPENDED:
            return Response(
                {'detail': 'Solo puedes reactivar clases suspendidas.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        now = timezone.now()
        if now >= gym_class.end_datetime:
            return Response(
                {'detail': 'La clase ya terminó: no se puede reactivar. Usa completar anticipadamente o cancelar.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        new_status = GymClass.Status.IN_PROGRESS if now >= gym_class.start_datetime else GymClass.Status.SCHEDULED

        gym_class.status = new_status
        gym_class.suspend_reason = ''
        gym_class.suspended_at = None
        gym_class.suspended_by = None
        gym_class.reactivation_expected_date = None
        gym_class.is_active = True
        gym_class.save(update_fields=[
            'status', 'suspend_reason', 'suspended_at', 'suspended_by',
            'reactivation_expected_date', 'is_active', 'updated_at',
        ])

        return Response(self.get_serializer(gym_class).data)

    def _notify_suspension(self, gym_class):
        """Avisa por email a los alumnos con inscripción activa. No bloquea la
        suspensión si el envío falla (fail_silently)."""
        recipients = [
            enrollment.student.email
            for enrollment in gym_class.enrollments.filter(status='active').select_related('student')
            if enrollment.student and enrollment.student.email
        ]
        if not recipients:
            return
        when = timezone.localtime(gym_class.start_datetime).strftime('%d/%m %H:%M')
        reactivation = (
            gym_class.reactivation_expected_date.isoformat() if hasattr(gym_class.reactivation_expected_date, 'isoformat') else 'próximamente'
            if gym_class.reactivation_expected_date else 'una fecha por confirmar'
        )
        body = (
            f'Hola,\n\n'
            f'Tu clase de {gym_class.name} del {when} fue suspendida.\n'
            f'Motivo: {gym_class.suspend_reason or "sin detalle"}.\n'
            f'Fecha estimada de reactivación: {reactivation}.\n\n'
            f'Gracias por tu paciencia.\n— Equipo TYMRO'
        )
        for email in recipients:
            send_mail(
                subject='Tu clase fue suspendida',
                message=body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[email],
                fail_silently=True,
            )

    @action(detail=False, methods=['post'], url_path='bulk-close')
    def bulk_close(self, request):
        class_ids = request.data.get('class_ids') or []
        action_name = str(request.data.get('action', '')).strip()
        comment = str(request.data.get('comment', '')).strip()

        if not isinstance(class_ids, list) or not class_ids:
            return Response({'detail': 'Debes enviar una lista de class_ids.'}, status=status.HTTP_400_BAD_REQUEST)
        class_ids, invalid_ids = _as_id_list(class_ids)
        if invalid_ids:
            return Response({'detail': 'class_ids debe contener solo ids numéricos.'}, status=status.HTTP_400_BAD_REQUEST)
        if action_name not in ['cancel', 'complete_early']:
            return Response({'detail': 'La acción debe ser cancel o complete_early.'}, status=status.HTTP_400_BAD_REQUEST)
        if not comment:
            return Response({'detail': 'El comentario o motivo es obligatorio.'}, status=status.HTTP_400_BAD_REQUEST)

        user = request.user
        # Acotado por organización ANTES del bucle. El check por objeto ya negaba la
        # escritura, pero la respuesta delataba la diferencia entre un id AJENO ("Sin
        # permisos") y uno INEXISTENTE (ausente del summary): eso convertía el endpoint en
        # un enumerador del espacio global de ids para cualquier autenticado. Con el
        # queryset acotado, ambos casos caen en el mismo `not_found`.
        queryset = _org_scoped(GymClass.objects.all(), user).filter(id__in=class_ids)
        # Acotado a lo que `_can_close_or_cancel` aceptaria, no solo a la organizacion: si
        # no, "Sin permisos" seguia distinguiendo un id existente de uno inexistente DENTRO
        # de la propia org (un profe enumeraba las clases de sus colegas).
        if _is_teacher(user):
            queryset = queryset.filter(teacher_id=user.id)
        elif not (_is_superadmin(user) or roles.is_org_admin(user)):
            queryset = GymClass.objects.none()
        reachable_ids = set()
        updated_ids = []
        skipped = []

        for gym_class in queryset:
            reachable_ids.add(gym_class.id)
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
            if action_name == 'cancel':
                _refund_active_enrollments_for_cancelled_class(gym_class)
            if action_name == 'complete_early':
                gym_class.consolidate_attendance(marked_by=user, marked_at=gym_class.closed_at)
                _register_teacher_payment_for_class(gym_class)
            updated_ids.append(gym_class.id)

        skipped.extend(
            {'id': class_id, 'reason': 'not_found'}
            for class_id in class_ids if class_id not in reachable_ids
        )
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
        if roles.is_org_admin(user):
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
        if _can_manage_operational_resource(user, template.organization_id):
            updated_template = serializer.save()
            apply_updates = _parse_bool(self.request.data.get('apply_to_future_instances'), default=True)
            if apply_updates:
                apply_template_updates_to_future_instances(updated_template, now=timezone.now())
            return
        raise PermissionDenied('No tienes permisos para editar esta plantilla.')

    # `perform_destroy` NO se define a propósito: `destroy` está sobreescrito y nunca lo
    # invocaría, así que existía como código muerto declarando una TERCERA política de
    # borrado (permitía manager) distinta de las dos reales. La política de borrado de
    # serie es única y vive acá abajo: `_can_manage_org_resource` (gym_admin/superadmin).

    def destroy(self, request, *args, **kwargs):
        template = self.get_object()
        # Borrar una serie destruye historial (`delete_template_safely` arrastra las clases
        # generadas), así que queda en gym_admin/superadmin: el manager NO, por ninguna vía
        # —ni acá ni por `bulk-action`—. Al manager le quedan desactivar, cancelar futuras y
        # regenerar, que no borran la fila.
        #
        # OJO: "no borra la fila" no es lo mismo que "inocuo". Quedan dos huecos conocidos:
        # 1. Las dos cancelaciones masivas del manager se comportan al REVÉS entre sí:
        #    `classes/bulk-close` con `action='cancel'` devuelve el consumo, y
        #    `class-templates/bulk-action` con `cancel_future_instances` NO —hace un
        #    `queryset.update()` en bloque (`cancel_future_instances_for_template`)—. Como
        #    tampoco cancela las `Enrollment`, quedan `active` sobre una clase `CANCELLED`:
        #    el alumno recupera el saldo SOLO si cancela su reserva a mano. No es
        #    irreversible, es que el silencio lo paga el alumno.
        # 2. `DELETE /api/classes/{id}/` sigue abierto al manager (vía `roles.is_org_admin`),
        #    así que puede borrar las instancias de la serie una por una. Ese borrado sí es
        #    íntegro (pasa por `revert_consumption_for_class`), pero destruye el mismo
        #    historial que esta guarda protege.
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
        if not _can_manage_operational_resource(user, template.organization_id):
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

        if _can_manage_operational_resource(user, template.organization_id):
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
        if not _can_manage_operational_resource(user, template.organization_id):
            raise PermissionDenied('No tienes permisos para cancelar futuras de esta serie.')
        comment = str(request.data.get('comment', '')).strip() or 'Cancelacion de futuras desde serie'
        summary = cancel_future_instances_for_template(template, actor=user, comment=comment)
        return Response(summary)

    @action(detail=True, methods=['post'], url_path='reactivate-future-cancelled')
    def reactivate_future_cancelled(self, request, pk=None):
        template = self.get_object()
        user = request.user
        if not _can_manage_operational_resource(user, template.organization_id):
            raise PermissionDenied('No tienes permisos para reactivar futuras de esta serie.')
        summary = reactivate_future_cancelled_instances_for_template(template)
        return Response(summary)

    @action(detail=False, methods=['post'], url_path='bulk-action')
    def bulk_action(self, request):
        user = request.user
        action_name = str(request.data.get('action', '')).strip()
        template_ids = request.data.get('template_ids') or []

        if action_name not in {'activate', 'deactivate', 'delete', 'cancel_future_instances', 'reactivate_future_cancelled', 'generate_pending'}:
            return Response({'detail': 'Accion invalida.'}, status=status.HTTP_400_BAD_REQUEST)
        # Misma política que `destroy`: borrar series es de gym_admin/superadmin. Era la vía
        # por la que el manager SÍ borraba (la selección múltiple del frontend pasa por acá),
        # y contradecía al `destroy` que se lo negaba. El rechazo es de la petición COMPLETA
        # y antes de mirar los ids: un `skipped` fila por fila delataría qué series existen.
        # `roles.can_manage_admin` y no `_can_manage_org_resource(user, user.organization_id)`:
        # ese helper compara la org contra sí misma, así que colapsaba a un check de rol
        # disfrazado de check de tenant. La matriz de roles vive en `accounts/roles.py`
        # (fuente única de verdad); el acotamiento por organización lo hacen `_org_scoped`
        # y el predicado por objeto de más abajo.
        if action_name == 'delete' and not roles.can_manage_admin(user):
            raise PermissionDenied('Solo un administrador del gimnasio puede eliminar series.')
        if not isinstance(template_ids, list) or not template_ids:
            return Response({'detail': 'Debes enviar template_ids.'}, status=status.HTTP_400_BAD_REQUEST)
        template_ids, invalid_ids = _as_id_list(template_ids)
        if invalid_ids:
            return Response({'detail': 'template_ids debe contener solo ids numéricos.'}, status=status.HTTP_400_BAD_REQUEST)

        # Mismo motivo que en `bulk-close`: acotar por organización antes del bucle para no
        # delatar qué ids existen en otros tenants.
        templates = _org_scoped(ClassTemplate.objects.all(), user).filter(id__in=template_ids)
        # Igual que en `bulk-close`: quien no puede gestionar NINGUNA plantilla no debe
        # poder distinguir un id existente de uno inexistente.
        if not (_is_superadmin(user) or roles.is_org_admin(user)):
            templates = ClassTemplate.objects.none()
        reachable_ids = set()
        summary = {'action': action_name, 'updated_ids': [], 'deleted_ids': [], 'skipped': []}
        comment = str(request.data.get('comment', '')).strip() or 'Cancelacion masiva de futuras'

        # El borrado usa la política estrecha (gym_admin/superadmin) y el resto de las
        # acciones la operativa (incluye manager). Redundante con el gate de más arriba
        # para `delete`, y a propósito: si ese gate se toca, el bucle sigue siendo correcto.
        can_manage = (
            _can_manage_org_resource if action_name == 'delete'
            else _can_manage_operational_resource
        )

        for template in templates:
            reachable_ids.add(template.id)
            if not can_manage(user, template.organization_id):
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
                # El id se guarda ANTES de borrar: `delete()` deja el pk en None y la
                # respuesta reportaba `deleted_ids: [None]`.
                template_id = template.id
                result = delete_template_safely(template)
                if result.get('deleted'):
                    summary['deleted_ids'].append(template_id)
                else:
                    summary['skipped'].append({'id': template_id, 'reason': result.get('reason', 'No se pudo eliminar')})

        summary['skipped'].extend(
            {'id': template_id, 'reason': 'not_found'}
            for template_id in template_ids if template_id not in reachable_ids
        )
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
        if (roles.is_org_admin(user) or _is_monitor(user)) and user.organization_id:
            return queryset.filter(class_template__organization_id=user.organization_id)
        if _is_student(user):
            # Mismo acotamiento por organizacion: la recurrencia cuelga de la plantilla,
            # asi que la org sale de `class_template`.
            if not user.organization_id:
                return queryset.none()
            return queryset.filter(
                student_id=user.id,
                class_template__organization_id=user.organization_id,
            )
        return queryset.none()

    def perform_create(self, serializer):
        user = self.request.user
        if _is_student(user):
            serializer.save(student=user, created_by=user)
            return

        template = serializer.validated_data.get('class_template')
        if template and _can_manage_operational_resource(user, template.organization_id):
            serializer.save(created_by=user)
            return
        raise PermissionDenied('No tienes permisos para crear esta recurrencia.')

    def perform_update(self, serializer):
        user = self.request.user
        recurring_enrollment = self.get_object()
        if _is_student(user) and not (
            recurring_enrollment.student_id == user.id
            and user.organization_id
            and recurring_enrollment.class_template.organization_id == user.organization_id
        ):
            raise PermissionDenied('Solo puedes editar tus propias recurrencias.')
        if roles.is_org_admin(user) and recurring_enrollment.class_template.organization_id != user.organization_id:
            raise PermissionDenied('No tienes permisos para editar esta recurrencia.')
        if not (_is_superadmin(user) or roles.is_org_admin(user) or _is_student(user)):
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
        if roles.is_org_admin(user) and instance.class_template.organization_id == user.organization_id:
            instance.delete()
            return
        if _is_student(user) and (
            instance.student_id == user.id
            and user.organization_id
            and instance.class_template.organization_id == user.organization_id
        ):
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

        _sync_class_statuses(_class_sync_scope(user))

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
        if (roles.is_org_admin(user) or _is_monitor(user)) and user.organization_id:
            return queryset.filter(gym_class__organization_id=user.organization_id)
        if _is_teacher(user):
            # Acotado por organización además del profesor: ver `_is_own_class_teacher`.
            if not user.organization_id:
                return queryset.none()
            return queryset.filter(
                gym_class__teacher_id=user.id,
                gym_class__organization_id=user.organization_id,
            )
        if _is_student(user):
            # Acotado por organizacion ademas del alumno: ver `_is_own_org_student`.
            if not user.organization_id:
                return queryset.none()
            return queryset.filter(
                student_id=user.id,
                gym_class__organization_id=user.organization_id,
            )
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

        if _is_student(user) and not _is_own_org_student(user, enrollment):
            raise PermissionDenied('Solo puedes cancelar tus propias reservas.')
        if roles.is_org_admin(user) and enrollment.gym_class.organization_id != user.organization_id:
            raise PermissionDenied('No tienes permisos para esta reserva.')
        if _is_teacher(user) and not _is_own_class_teacher(user, enrollment.gym_class):
            raise PermissionDenied('Solo puedes cancelar inscripciones en tus propias clases.')
        if not (_is_superadmin(user) or roles.is_org_admin(user) or _is_teacher(user) or _is_student(user)):
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
        gym_class = serializer.validated_data.get('gym_class')

        # La autorización va ANTES del atajo por estado. El atajo de `status != 'active'`
        # se ejecutaba antes de las ramas por rol y de su PermissionDenied, y el único
        # filtro restante (EnrollmentSerializer.validate) condiciona su check de
        # organización a roles.is_org_admin: monitor y teacher no lo activaban y podían
        # crear inscripciones en OTRA organización (regla #1). Este check cubre los dos
        # caminos con la misma matriz que ya aplicaba la rama de status='active'.
        if not (
            _is_superadmin(user)
            or (
                gym_class is not None
                and user.organization_id
                and gym_class.organization_id == user.organization_id
                and (
                    roles.is_org_admin(user)
                    or _is_own_class_teacher(user, gym_class)
                    or _is_student(user)
                )
            )
        ):
            raise PermissionDenied('No tienes permisos para crear inscripciones.')

        with transaction.atomic():
            if requested_status != 'active':
                serializer.save()
                return

            if _is_superadmin(user) or roles.is_org_admin(user):
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
                if not gym_class or not _is_own_class_teacher(user, gym_class):
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
        if not (
            _is_superadmin(user)
            or (roles.is_org_admin(user) and enrollment.gym_class.organization_id == user.organization_id)
        ):
            raise PermissionDenied('No tienes permisos para editar inscripciones.')

        # Los CAMBIOS DE ESTADO van por los servicios de reserva, no por un `save()`
        # directo. `EnrollmentSerializer.validate` cubre organización, cupo, solape y
        # duplicados, pero no plan activo, matrícula impaga, exclusividad de sucursal ni
        # el consumo del plan. Sin esto, crear en 'cancelled' y PATCHear a 'active' era
        # un bypass de dos llamadas: saltaba la restricción de sede y regalaba la clase.
        new_status = serializer.validated_data.get('status', enrollment.status)
        if new_status != enrollment.status:
            if new_status == 'active':
                try:
                    serializer.instance = reserve_student_in_class(
                        student=enrollment.student,
                        gym_class=serializer.validated_data.get('gym_class', enrollment.gym_class),
                        recurring_enrollment=enrollment.recurring_enrollment,
                        require_plan=True,
                    )
                except ReservationRuleError as exc:
                    raise ValidationError({'detail': exc.message})
                return
            if new_status == 'cancelled':
                serializer.instance = cancel_enrollment_with_refund(enrollment)
                return

        serializer.save()

    def _destroy_with_refund(self, instance):
        """Borrar una inscripción tiene que llevarse su consumo.

        `ConsumptionLog` no cuelga de `Enrollment`, así que el borrado no lo cascadea: el
        log sobrevivía y `classes_used` quedaba inflado (alumno cobrado sin reserva, y
        consumo huérfano que ciega las guardas de borrado de clases y series).
        """
        with transaction.atomic():
            revert_consumption_for_enrollment(instance)
            instance.delete()

    def perform_destroy(self, instance):
        user = self.request.user
        if _is_superadmin(user):
            self._destroy_with_refund(instance)
            return
        if roles.is_org_admin(user) and instance.gym_class.organization_id == user.organization_id:
            self._destroy_with_refund(instance)
            return
        if _is_own_org_student(user, instance):
            # DELETE no puede ser la puerta trasera de la acción `cancel`: sin este
            # check el alumno se saltaba STUDENT_CANCEL_DEADLINE_HOURS borrando la
            # reserva en vez de cancelarla, y con el reverso del consumo encima ahora
            # además recuperaría el saldo. Misma política que `cancel_reservation`.
            can_cancel, reason = _student_can_cancel_enrollment(instance)
            if not can_cancel:
                raise ValidationError({'detail': reason})
            self._destroy_with_refund(instance)
            return
        raise PermissionDenied('No tienes permisos para eliminar inscripciones.')


class MembershipPlanViewSet(ModelViewSet):
    queryset = Plan.objects.select_related('organization').all()
    serializer_class = PlanSerializer
    permission_classes = [FinancialResourcePermission]

    def get_queryset(self):
        base_queryset = Plan.objects.select_related('organization').all()
        user = self.request.user
        organization_id = self.request.query_params.get('organization_id')
        if _is_superadmin(user):
            if organization_id:
                # Mismo criterio que `_as_id_list` con los ids del body: un valor no
                # numérico es un 400 de forma, no un 500 por ValueError crudo del ORM.
                ids, invalid = _as_id_list([organization_id])
                if invalid:
                    raise ValidationError({'organization_id': 'Debe ser un id numérico.'})
                base_queryset = base_queryset.filter(organization_id=ids[0])
            return base_queryset
        if (_is_gym_admin(user) or _is_student(user) or _is_monitor(user)) and user.organization_id:
            base_queryset = base_queryset.filter(organization_id=user.organization_id)
            if _is_student(user):
                # `is_public`/`is_active` son la vitrina del alumno y el filtro vivía SOLO
                # en el frontend (StudentBuyPlanPage.jsx): precios internos, convenios y
                # planes ya retirados se leían con un `curl`. El checkout sí validaba
                # (`views_payments.py`), así que lo abierto era la LECTURA. Va en
                # `get_queryset` y no en la acción de listado a propósito: así el detalle
                # (`/api/plans/{id}/`) también responde 404, que hace falta porque el id
                # es autoincremental y adivinable.
                # `gym_admin`/`superadmin` siguen viendo todo (lo administran) y `manager`
                # ni llega: `FinancialResourcePermission` le da 403.
                # La tercera condición replica la que faltaba del front: los planes trial y
                # giftcard nacen con `is_public=True` (default del modelo) pero no se compran
                # en línea —`create_checkout` los rechaza—, así que tampoco van en la vitrina.
                base_queryset = base_queryset.filter(is_public=True, is_active=True).exclude(
                    plan_type__in=Plan.NOT_PURCHASABLE_ONLINE,
                )
            return base_queryset
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

    @staticmethod
    def _cascade_blocker(plan):
        """Qué historial arrastraría el hard delete de este plan, o None si es seguro.

        `StudentPlan.plan` es CASCADE: borrar el plan se lleva TODAS las membresías
        vendidas y, en cascada (`ConsumptionLog.student_plan`), el historial de consumo
        que respalda `classes_used`. Peor: las `Enrollment` no cuelgan del plan —cuelgan
        de la clase y del alumno— así que sobreviven en estado `active` respaldadas por
        una membresía que ya no existe. Y de paso era el atajo para saltarse la guarda de
        `remove_membership`, que se niega a quitar una membresía con `classes_used > 0`
        hasta que exista una política de devolución.

        La segunda comprobación NO es por cascada sino por SET_NULL:
        `PaymentTransaction.plan`. Borrar el plan no borra el cobro, lo deja sin decir QUÉ
        se compró. Un pago aprobado normalmente ya activó su membresía y la primera guarda
        alcanza; el hueco es el cobrado-sin-activar (ver `test_payment_plan_org_mismatch`),
        que es justo el que hay que poder auditar. Un checkout abandonado —sin
        `provider_payment_id`, o sea sin plata de por medio— no bloquea nada.
        """
        if plan.student_plans.exists():
            return (
                'El plan tiene membresías de alumnos asociadas: se desactivó en vez de '
                'eliminarse para no corromper el historial de consumo ni dejar '
                'inscripciones activas sin membresía que las respalde.'
            )
        if plan.payment_transactions.filter(provider_payment_id__isnull=False).exists():
            return (
                'El plan tiene pagos cobrados asociados: se desactivó en vez de '
                'eliminarse para que esos cobros conserven el historial de qué se compró.'
            )
        return None

    def destroy(self, request, *args, **kwargs):
        # Se sobreescribe `destroy` y no `perform_destroy` por el mismo motivo que en
        # `BranchViewSet.destroy`: el soft-delete es una ESCRITURA que acompaña a una
        # respuesta de ERROR, y una APIException haría que DRF invocara `set_rollback()`,
        # revirtiendo la desactivación mientras la respuesta seguiría diciendo que se
        # desactivó. Devolver un `Response` explícito no dispara ese rollback.
        instance = self.get_object()  # ya scoped por get_queryset(): 404 si es de otra org

        user = request.user
        if not (
            _is_superadmin(user)
            or (_is_gym_admin(user) and instance.organization_id == user.organization_id)
        ):
            raise PermissionDenied('No tienes permisos para eliminar planes.')

        # La guarda aplica también al superadmin: la cascada corrompe el historial igual
        # sin importar quién dispare el borrado.
        blocker = self._cascade_blocker(instance)
        if blocker:
            if instance.is_active:
                instance.is_active = False
                instance.save(update_fields=['is_active', 'updated_at'])
            return Response({'detail': blocker}, status=status.HTTP_400_BAD_REQUEST)

        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

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

        from core.services.plans import activate_student_plan
        assigned = activate_student_plan(
            student=student,
            plan=plan,
            start_date=validated['start_date'],
            discount_percentage=validated['discount_percentage'],
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
                # La membresia es de quien la vendio, y eso lo dice la COLUMNA
                # `organization` (copia hecha al vender), no el join `plan__organization`.
                # Sin este filtro, un alumno movido de organizacion seguia viendo el plan
                # de la anterior.
                organization_id=request.user.organization_id,
            )
            .valid_on(today)
            .prefetch_related('origin_transactions', 'manual_payments')   # eje de pago sin N+1 por membresia
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
                .prefetch_related('origin_transactions', 'manual_payments')   # eje de pago sin N+1 por membresia
                .filter(plan_id=plan.id, user__role=User.Role.STUDENT)
                .order_by('-is_active', '-start_date', '-id')
            )
        elif _is_gym_admin(user):
            # Se acota por `organization` (la organizacion que VENDIO la membresia) y no por
            # `user__organization_id`: la organizacion del usuario cambia cuando el alumno se
            # muda de gimnasio, y entonces el gym que cobro la venta dejaba de verla en su
            # propio plan. La columna no se mueve con el alumno.
            memberships_queryset = (
                StudentPlan.objects.select_related('user', 'plan')
                .prefetch_related('origin_transactions', 'manual_payments')   # eje de pago sin N+1 por membresia
                .filter(plan_id=plan.id, user__role=User.Role.STUDENT, organization_id=user.organization_id)
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
            # Misma correccion que en `memberships`: si el scope fuera `user__organization_id`,
            # mover al alumno de gimnasio dejaria la membresia inalcanzable para el unico
            # tenant con derecho a tocarla.
            membership = (
                StudentPlan.objects.select_related('user', 'plan')
                .filter(
                    id=membership_id,
                    plan_id=plan.id,
                    user__role=User.Role.STUDENT,
                    organization_id=user.organization_id,
                )
                .first()
            )
        else:
            raise PermissionDenied('No tienes permisos para quitar membresias de este plan.')

        if not membership:
            return Response({'detail': 'Membresia no encontrada para este plan.'}, status=status.HTTP_404_NOT_FOUND)

        # Se miran las DOS cosas, y el historial primero. `classes_used` es un contador
        # DERIVADO y escribible: el importador lo declara `updatable`, así que una
        # re-importación con las 'Clases restantes' mal puestas lo baja a 0 dejando los
        # ConsumptionLog vivos. Con la guarda solo sobre el contador, ese descuadre abría
        # un bypass de dos pasos —quitar la membresía (cascadeando sus logs) y después
        # borrar el plan, que ya no tenía membresías— que anulaba la guarda de
        # `_cascade_blocker` sin un solo error de por medio.
        # El contador se conserva como segunda condición y no se reemplaza: una membresía
        # onboardeada por importador tiene saldo arrastrado y CERO logs a propósito
        # (el consumo es anterior al sistema), y ahí el contador es lo único que protege.
        if membership.consumption_logs.exists() or (membership.classes_used or 0) > 0:
            return Response(
                {
                    'detail': 'No se puede quitar esta membresia porque ya tiene clases utilizadas. Define una politica de devolucion primero.'
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        membership.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ManualPaymentCreateView(APIView):
    """`POST /api/manual-payments/` — registra un cobro en efectivo o por transferencia.

    SOLO ESCRITURA, y a propósito: no hay GET, PATCH ni DELETE. Un listado devolvería los
    importes cobrados de cada membresía y, si mañana lo consumiera el roster, reabriría por
    otra puerta lo que la redacción del monitor cierra (views.py:551-561). Anular o corregir
    un pago tampoco existe todavía: tiene semántica propia y es otra tarea.

    SOLO `gym_admin`. Ni manager, ni monitor, ni teacher, ni student — y tampoco superadmin.
    El superadmin es rol de PLATAFORMA y no tiene organización, así que no hay org que
    estampar sin creerle al payload; y derivarla de la membresía volvería TAUTOLÓGICA la
    única guarda cross-tenant que tiene este endpoint —`org(actor) == org(membresía)` pasaría
    a comparar la membresía consigo misma— dejando cualquier membresía de la plataforma
    pagable desde un solo actor sin ancla de tenant. Además la plata la recibió el gimnasio,
    no el operador. Denegar es reversible; abrir no.

    La restricción vive ACÁ, en el backend. El control del frontend es cosmético.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        # El check va inline y no en una clase de permiso porque además del ROL exige el
        # ANCLA: sin `organization_id` no hay organización que estampar en la fila, y una
        # clase que solo mire `role` no lo expresa.
        if not (_is_gym_admin(user) and user.organization_id):
            raise PermissionDenied(
                'Solo el administrador del gimnasio puede registrar pagos manuales.'
            )

        serializer = ManualPaymentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated = serializer.validated_data

        # La membresía se busca YA acotada por la organización del actor, en una sola
        # consulta: no existe un momento en que el código tenga en la mano una membresía
        # ajena. Se filtra por la COLUMNA `organization` —quien VENDIÓ la membresía— y jamás
        # por `user__organization_id`: `StudentPlan.user` es CASCADE sobre el usuario, así que
        # un alumno movido de gimnasio dejaría su membresía vieja alcanzable desde el
        # gimnasio nuevo (mismo criterio que views.py:3512-3515).
        membership = StudentPlan.objects.filter(
            pk=validated['student_plan'],
            organization_id=user.organization_id,
        ).first()
        if membership is None:
            # 404 y no 403/400: el id de `StudentPlan` es autoincremental y adivinable (mismo
            # argumento que views.py:3346-3348), así que distinguir "no existe" de "es de otra
            # organización" convierte el endpoint en un oráculo de membresías ajenas.
            raise NotFound('Membresía no encontrada.')

        try:
            payment = record_manual_payment(
                student_plan=membership,
                amount=validated['amount'],
                reference=validated['reference'],
                # NUNCA del payload: el actor y su organización, y nada más.
                recorded_by=user,
                organization=user.organization,
            )
        except ManualPaymentOrganizationMismatch as exc:
            # Inalcanzable con el lookup de arriba. Queda como red por si un refactor futuro
            # afloja el scope del queryset — y si eso pasa, tiene que fallar CERRADA sin
            # reabrir el oráculo: un 403 acá distinguiría "existe pero es de otra
            # organización" de un 404 "no existe", exactamente lo que el guard cross-org de
            # arriba existe para no revelar. Mismo mensaje, mismo código.
            raise NotFound('Membresía no encontrada.')
        except DjangoValidationError as exc:
            # `full_clean()` levanta la excepción de Django, que DRF no traduce: sin esto
            # saldría 500. Las dos reglas que puede violar (monto e incoherencia de org) ya
            # las cubren el serializer y el lookup, así que esto es defensa en profundidad.
            raise ValidationError(
                exc.message_dict if hasattr(exc, 'message_dict') else {'detail': exc.messages}
            )

        return Response(
            ManualPaymentSerializer(payment).data,
            status=status.HTTP_201_CREATED,
        )


class TeacherPaymentRuleViewSet(ModelViewSet):
    queryset = TeacherPaymentRule.objects.select_related('organization', 'branch', 'discipline', 'class_type').prefetch_related('teachers').all()
    serializer_class = TeacherPaymentRuleSerializer
    permission_classes = [FinancialResourcePermission]

    def get_queryset(self):
        user = self.request.user
        queryset = self.queryset.annotate(usage_count=models.Count('teachers', distinct=True))
        if _is_superadmin(user):
            organization_id = self.request.query_params.get('organization_id')
            if organization_id:
                queryset = queryset.filter(organization_id=organization_id)
            return queryset
        if (_is_gym_admin(user) or _is_monitor(user)) and user.organization_id:
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
                'per_plan_price_base',
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
        is_read = request.method.lower() == 'get'
        allowed = _is_superadmin(user) or (
            (roles.is_org_admin(user) or (is_read and _is_monitor(user)))
            and rule.organization_id == user.organization_id
        )
        if not allowed:
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
    permission_classes = [FinancialResourcePermission]
    http_method_names = ['get', 'post', 'head', 'options']

    def create(self, request, *args, **kwargs):
        # POST sólo se usa para acciones custom (mark-paid); no se permite crear records vía API.
        raise MethodNotAllowed('POST')

    def get_queryset(self):
        user = self.request.user
        teacher_id = self.request.query_params.get('teacher_id')
        date_from = self.request.query_params.get('date_from')
        date_to = self.request.query_params.get('date_to')

        queryset = self.queryset
        if _is_superadmin(user):
            pass
        elif (_is_gym_admin(user) or _is_monitor(user)) and user.organization_id:
            queryset = queryset.filter(class_instance__organization_id=user.organization_id)
        elif _is_teacher(user):
            # Un pago calculado sobre una clase de otra organización (FK de profesor
            # rancia) no es del profe: ver `_is_own_class_teacher`.
            if not user.organization_id:
                return queryset.none()
            queryset = queryset.filter(
                teacher_id=user.id,
                class_instance__organization_id=user.organization_id,
            )
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

    # --- Resumen agregado por profesor en un periodo ---
    @staticmethod
    def _parse_summary_period(request):
        today = timezone.localdate()
        default_from = today.replace(day=1)
        if default_from.month == 12:
            next_month = default_from.replace(year=default_from.year + 1, month=1)
        else:
            next_month = default_from.replace(month=default_from.month + 1)
        default_to = next_month - timedelta(days=1)

        def _parse(value, fallback):
            if not value:
                return fallback
            try:
                return datetime.strptime(value, '%Y-%m-%d').date()
            except ValueError:
                raise ValidationError({'period': 'Formato de fecha invalido (usa YYYY-MM-DD).'})

        date_from = _parse(request.query_params.get('date_from'), default_from)
        date_to = _parse(request.query_params.get('date_to'), default_to)
        if date_to < date_from:
            raise ValidationError({'period': 'date_to no puede ser anterior a date_from.'})
        return date_from, date_to

    def _resolve_summary_scope(self, request):
        user = request.user
        teacher_id = None
        if _is_superadmin(user):
            organization_id = request.query_params.get('organization_id')
            if not organization_id:
                raise ValidationError({'organization_id': 'Debes indicar la organizacion.'})
        elif (_is_gym_admin(user) or _is_monitor(user)) and user.organization_id:
            organization_id = user.organization_id
        elif _is_teacher(user) and user.organization_id:
            organization_id = user.organization_id
            teacher_id = user.id  # el profe solo ve su propia fila
        else:
            raise PermissionDenied('No tienes permisos para ver el resumen de pagos.')

        requested_teacher = request.query_params.get('teacher_id')
        if requested_teacher and teacher_id is None:
            teacher_id = requested_teacher

        date_from, date_to = self._parse_summary_period(request)
        return organization_id, date_from, date_to, teacher_id

    @staticmethod
    def _attach_payouts(data, organization_id, date_from):
        """Anexa a cada fila el estado de pago del periodo (mes de date_from).
        Solo lectura; no toca el motor de calculo."""
        payouts = {
            p.teacher_id: p
            for p in TeacherPayout.objects.filter(
                organization_id=organization_id,
                period_year=date_from.year,
                period_month=date_from.month,
            )
        }
        for row in data['rows']:
            payout = payouts.get(row['teacher_id'])
            paid_amount = round(float(payout.amount), 2) if payout else 0.0
            row['payout'] = (
                {'paid_at': payout.paid_at.isoformat(), 'amount': paid_amount}
                if payout
                else None
            )
            # Campo derivado: lo que aún se debe = max(0, total vivo - lo ya pagado).
            # Si el total creció tras el pago (ej. clase cerrada tarde), aquí aparece el saldo nuevo.
            row['pending'] = round(max(0.0, float(row['total']) - paid_amount), 2)
        return data

    @action(detail=False, methods=['get'], url_path='summary')
    def summary(self, request):
        organization_id, date_from, date_to, teacher_id = self._resolve_summary_scope(request)
        data = build_teacher_payment_summary(organization_id, date_from, date_to, teacher_id=teacher_id)
        self._attach_payouts(data, organization_id, date_from)
        return Response(data)

    @action(detail=False, methods=['post'], url_path='mark-paid')
    def mark_paid(self, request):
        """Marca como pagado a un profesor en un periodo (mes). Solo gym_admin/superadmin.
        Guarda un snapshot del total del periodo en TeacherPayout. Scoped por organizacion."""
        user = request.user
        if _is_superadmin(user):
            organization_id = request.data.get('organization_id')
            if not organization_id:
                raise ValidationError({'organization_id': 'Debes indicar la organizacion.'})
        elif _is_gym_admin(user) and user.organization_id:
            organization_id = user.organization_id
        else:
            raise PermissionDenied('No tienes permisos para marcar pagos.')

        teacher_id = request.data.get('teacher_id')
        if not teacher_id:
            raise ValidationError({'teacher_id': 'Debes indicar el profesor.'})
        try:
            year = int(request.data.get('year'))
            month = int(request.data.get('month'))
            if not 1 <= month <= 12:
                raise ValueError
        except (TypeError, ValueError):
            raise ValidationError({'period': 'year/month invalidos.'})

        # El profesor debe pertenecer a la organizacion (evita marcar profes de otra org).
        teacher = User.objects.filter(id=teacher_id, organization_id=organization_id, role=User.Role.TEACHER).first()
        if teacher is None:
            raise ValidationError({'teacher_id': 'Profesor no encontrado en la organizacion.'})

        date_from = datetime(year, month, 1).date()
        if month == 12:
            next_month = datetime(year + 1, 1, 1).date()
        else:
            next_month = datetime(year, month + 1, 1).date()
        date_to = next_month - timedelta(days=1)

        summary = build_teacher_payment_summary(organization_id, date_from, date_to, teacher_id=teacher_id)
        row = next((r for r in summary['rows'] if r['teacher_id'] == teacher.id), None)
        amount = round(float(row['total']), 2) if row else 0.0

        payout, _created = TeacherPayout.objects.update_or_create(
            teacher_id=teacher.id,
            organization_id=organization_id,
            period_year=year,
            period_month=month,
            defaults={'amount': amount, 'paid_at': timezone.now(), 'marked_by': user},
        )
        return Response(
            {
                'teacher_id': teacher.id,
                'period_year': year,
                'period_month': month,
                'amount': round(float(payout.amount), 2),
                'paid_at': payout.paid_at.isoformat(),
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=['get'], url_path='summary/export')
    def summary_export(self, request):
        organization_id, date_from, date_to, teacher_id = self._resolve_summary_scope(request)
        data = build_teacher_payment_summary(organization_id, date_from, date_to, teacher_id=teacher_id)
        self._attach_payouts(data, organization_id, date_from)
        # OJO: no usar el param 'format' (lo reserva DRF para negociacion de contenido).
        export_format = (request.query_params.get('fmt') or 'csv').lower()
        filename = f"pagos_profesores_{data['period']['date_from']}_{data['period']['date_to']}"
        if export_format == 'xlsx':
            return self._export_summary_xlsx(data, filename)
        return self._export_summary_csv(data, filename)

    @staticmethod
    def _summary_header():
        return [
            'Profesor', 'Modalidades', 'Clases', 'Asistentes', 'Sueldo base', 'Por clase', 'Total',
            'Estado', 'Pagado', 'Fecha pago', 'Pendiente',
        ]

    @staticmethod
    def _summary_data_row(row):
        payout = row.get('payout')
        pending = int(round(row.get('pending', row['total'])))
        paid_amount = int(round(payout['amount'])) if payout else 0
        paid_date = payout['paid_at'][:10] if payout else ''
        if not payout:
            estado = 'Pendiente'
        elif pending > 0:
            estado = 'Pagado parcial'
        else:
            estado = 'Pagado'
        return [
            row['teacher_name'],
            ', '.join(_payment_type_label(code) for code in row['modalities']),
            row['classes_count'],
            row['attendees_total'],
            int(round(row['monthly_total'])),
            int(round(row['per_class_total'])),
            int(round(row['total'])),
            estado,
            paid_amount,
            paid_date,
            pending,
        ]

    @staticmethod
    def _summary_total_row(data):
        grand_paid = sum(
            int(round(row['payout']['amount'])) if row.get('payout') else 0
            for row in data['rows']
        )
        grand_pending = sum(int(round(row.get('pending', row['total']))) for row in data['rows'])
        return ['TOTAL', '', '', '', '', '', int(round(data['grand_total'])), '', grand_paid, '', grand_pending]

    @classmethod
    def _export_summary_csv(cls, data, filename):
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="{filename}.csv"'
        response.write('﻿')  # BOM para que Excel respete acentos
        writer = csv.writer(response)
        writer.writerow(cls._summary_header())
        for row in data['rows']:
            writer.writerow(cls._summary_data_row(row))
        writer.writerow(cls._summary_total_row(data))
        return response

    @classmethod
    def _export_summary_xlsx(cls, data, filename):
        from openpyxl import Workbook
        from openpyxl.styles import Font

        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = 'Pagos profesores'
        worksheet.append(cls._summary_header())
        for cell in worksheet[1]:
            cell.font = Font(bold=True)
        for row in data['rows']:
            worksheet.append(cls._summary_data_row(row))
        worksheet.append(cls._summary_total_row(data))
        for cell in worksheet[worksheet.max_row]:
            cell.font = Font(bold=True)

        response = HttpResponse(
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = f'attachment; filename="{filename}.xlsx"'
        workbook.save(response)
        return response


