"""Vista integral de UN alumno (P4 · Prompt 2 · Feature B). SOLO LECTURA, SOLO `gym_admin`.

Consolida en una sola pantalla lo que hoy vive repartido en varias superficies (membresías,
consumo, asistencia, reservas, recurrencias) para que el `gym_admin` no tenga que saltar de
pantalla en pantalla para entender la situación de un alumno. Split de `views.py`, mismo
criterio de tamaño que `views_reports.py`/`views_payments.py`.

SUPERFICIE FINANCIERA — el payload incluye `payment_status` de cada membresía (mismo eje que
`StudentPlanSerializer`/`_plan_status_payload` en `views.py`). Por eso el corte de rol es el
MÁS ANGOSTO posible y se aplica DOS VECES:

1. `permission_classes = [ReportPermission]` — igual que reportería: solo `gym_admin` CON
   organización. `manager`, `monitor`, `teacher`, `student` y `superadmin` quedan fuera (403).
2. Un CHECK INLINE explícito al principio del handler, que repite exactamente lo mismo.

El check inline no es redundancia inofensiva: es la defensa que pide el docstring de
`_plan_status_payload` en `views.py` (~511-592) — "DEFAULT ABIERTO ... una superficie NUEVA
que llame a esta función sin pensarlo publica los dos ejes". Si algún día esta vista se
reutiliza desde otro router o alguien afloja `permission_classes` sin pensarlo, esta línea
sigue cortando al monitor (que es, literalmente, el lector que NUNCA puede ver
`payment_status` por ningún camino — ver el mismo docstring).

`superadmin` queda AFUERA a propósito, mismo criterio que `ReportPermission`/
`PaymentTransactionListView`: esta pantalla es de la organización del `gym_admin`, no de la
plataforma. Es una decisión de producto, no solo técnica — a confirmar por Javier.

ORDEN (lección 8.3): se resuelve el alumno ACOTADO por `organization_id` del actor ANTES de
tocar cualquier otra tabla, y se sale con 404 si no matchea. Alumno inexistente y alumno de
otra organización devuelven EXACTAMENTE el mismo 404 (`Http404` sin detalle propio, el genérico
de DRF) — anti-oráculo, mismo criterio que `views_reports._scoped_id` y
`RevenuePaymentDetailView`. El id llega por `<str:>` (ver `urls.py`, comentario junto a la
ruta) y se valida la FORMA acá: malformado -> 400, ajeno/inexistente -> 404.

El alumno NO se filtra por `role == 'student'`. Mismo argumento que ya usa
`PlanViewSet.memberships` en `views.py` para no filtrar por el rol ACTUAL del dueño de una
membresía histórica ("la membresía es del plan y de la organización, no del rol"): con la
doble identidad del `gym_admin` (P4, commit 9c93034) puede haber datos de alumno colgando de
un usuario que hoy es `gym_admin`/`teacher`, y no hay ninguna razón de seguridad para
esconderlos si son de la MISMA organización que ya se puede auditar por otras vías.

FUENTE ÚNICA — el estado/vigencia/saldo/pago de cada membresía sale de `StudentPlanSerializer`
(que internamente llama a `describe_student_plan`, `services/plans.py:332`). Esta vista NO
recalcula nada de eso: arma el queryset con el MISMO prefetch que ya usan
`MembershipPlanViewSet.memberships`/`my_memberships` (views.py ~4237-4289) para no disparar una
consulta por membresía, y lo pasa entero al serializer.

RENDIMIENTO — consumo, asistencia y reservas son historiales que pueden crecer sin límite (años
de clases). Se acotan con "últimas N" + `has_more`, y un tope MÁXIMO duro
(`MAX_HISTORY_LIMIT`) que ningún query param puede superar — mismo criterio que
`services/reports_revenue_detail.MAX_ROWS`. `has_more` se resuelve pidiendo `limit + 1` filas y
descartando la última, para no pagar un `COUNT()` aparte sobre una tabla que puede tener miles
de filas por alumno. Las membresías van COMPLETAS (activas e históricas): es la razón de ser de
la pantalla y en la práctica son pocas filas por alumno (un plan por disciplina contratada, no
una fila por clase). Las recurrencias VIGENTES también van completas: están acotadas por el
número de plantillas de clase de la organización, no por el historial del alumno.

CADA COLECCIÓN, ACOTADA POR ORGANIZACIÓN ADEMÁS DE POR ALUMNO (lección recurrente del repo,
"FK propia sin organización"): ni `ConsumptionLog`, ni `Attendance`, ni `Enrollment`, ni
`RecurringEnrollment` tienen columna propia `organization` — se acotan por la FK que SÍ la
tiene y es de fiar (`class_instance`/`gym_class`/`class_template`, todas CASCADE sobre
`Organization`), nunca confiando solo en `user_id`/`student_id`, que son FKs sobre el USUARIO y
sobreviven si se lo mueve de organización.
"""
from django.contrib.auth import get_user_model
from django.http import Http404
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import CustomUser

from .models import (
    Attendance,
    ConsumptionLog,
    Enrollment,
    RecurringEnrollment,
    StudentPlan,
)
from .permissions import ReportPermission
from .serializers import StudentPlanSerializer

User = get_user_model()

# Misma validación de FORMA que `views_reports._id_field` / `views_payments._branch_scope`, y
# por los mismos motivos: `int()` a mano acepta floats/bools en silencio, y un id fuera del
# rango de bigint revienta con 500 en PostgreSQL (SQLite no lo reproduce). Cada módulo define
# su propia copia en vez de importar la de otro — mismo patrón que ya sigue `views_reports.py`.
_id_field = serializers.IntegerField(min_value=1, max_value=2 ** 63 - 1)

#: Filas por defecto de cada historial acotado (consumo/asistencia/reservas) y tope máximo
#: duro. El tope no es una regla de negocio, es cordura de rendimiento: un `?xxx_limit=999999`
#: nunca puede superarlo, sin importar lo que pida el cliente.
DEFAULT_HISTORY_LIMIT = 20
MAX_HISTORY_LIMIT = 100


def _parse_student_id(raw_value):
    """Valida la FORMA del segmento de ruta. Malformado -> 400, nunca 404 (ver docstring del
    módulo y el comentario de `urls.py` junto a esta ruta: con `<str:>` la vista tiene que
    validar la forma a mano, el 404 es solo para el id ajeno/inexistente)."""
    try:
        return _id_field.run_validation(raw_value)
    except serializers.ValidationError as exc:
        raise DRFValidationError({'student_id': exc.detail})


def _history_limit(raw_value):
    """`raw_value` del query string a un entero en `[1, MAX_HISTORY_LIMIT]`.

    Ausente o con basura (no numérico, negativo, cero) cae al default: no es un parámetro de
    negocio ni de seguridad, así que un valor raro no amerita 400, simplemente se ignora. Lo
    que SÍ es no negociable es el tope superior: se aplica SIEMPRE, incluso sobre un valor
    válido, y es la única línea que un query param no puede saltarse.
    """
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return DEFAULT_HISTORY_LIMIT
    if value < 1:
        return DEFAULT_HISTORY_LIMIT
    return min(value, MAX_HISTORY_LIMIT)


def _paged(queryset, limit):
    """Trae `limit + 1` filas y separa la fila de más para resolver `has_more` SIN un `COUNT()`
    aparte — sobre un historial de miles de filas por alumno, ese `COUNT()` es la misma
    consulta cara que este endpoint existe para evitar."""
    rows = list(queryset[: limit + 1])
    has_more = len(rows) > limit
    return rows[:limit], has_more


def _full_name(user):
    if user is None:
        return None
    full_name = f'{user.first_name} {user.last_name}'.strip()
    return full_name or user.username


def _class_summary(gym_class):
    if gym_class is None:
        return None
    return {
        'id': gym_class.id,
        'name': gym_class.name,
        'start_datetime': gym_class.start_datetime,
        'end_datetime': gym_class.end_datetime,
        'status': gym_class.status,
        'discipline_name': gym_class.discipline.name if gym_class.discipline_id else None,
        'teacher_name': _full_name(gym_class.teacher) if gym_class.teacher_id else None,
    }


def _plan_name_of(student_plan, org_id):
    """Nombre del plan de la membresía, REDACTADO si la membresía es de otra organización.

    `Enrollment.student_plan` y `RecurringEnrollment.student_plan` son FKs propias sin
    organización: sus querysets se acotan por la clase/plantilla (que sí es de la org del
    actor), pero eso no dice nada de la organización de la MEMBRESÍA colgada de la fila. Es
    la forma exacta del hallazgo del drill-down de ingresos, donde el nombre del plan y el PK
    de un `student_plan` ajeno se colaron por este mismo camino: la tolerancia de "FK propia
    sin org" vale para NOMBRES DE PERSONAS y nada más.

    Hoy la API no permite fabricar esa fila —las tres escrituras de estas FKs anclan la
    organización antes—, pero el docstring de `get_enrollment_student_plan`
    (`services/reservations.py`) documenta que SÍ existen filas legacy, anteriores al fix de
    scoping multitenant, apuntando a una membresía de otra organización.

    Se redacta el NOMBRE en vez de filtrar la fila a propósito: `student_plan` es nullable
    (clase de prueba, `require_plan=False`), así que un `filter(student_plan__organization_id
    =org_id)` a secas borraría del historial reservas legítimas sin membresía.
    """
    if student_plan is None or not student_plan.plan_id:
        return None
    if student_plan.organization_id != org_id:
        return None
    return student_plan.plan.name


def _consumption_row(log, org_id):
    return {
        'id': log.id,
        'consumed_at': log.consumed_at,
        'branch_name': log.branch.name if log.branch_id else None,
        'plan_name': _plan_name_of(log.student_plan, org_id),
        'class': _class_summary(log.class_instance),
    }


def _attendance_row(attendance):
    return {
        'id': attendance.id,
        'status': attendance.status,
        'source': attendance.source,
        'marked_at': attendance.marked_at,
        'marked_by_name': _full_name(attendance.marked_by) if attendance.marked_by_id else None,
        'class': _class_summary(attendance.gym_class),
    }


def _reservation_row(enrollment, org_id):
    return {
        'id': enrollment.id,
        'status': enrollment.status,
        'is_trial': enrollment.is_trial,
        'created_at': enrollment.created_at,
        'plan_name': _plan_name_of(enrollment.student_plan, org_id),
        'class': _class_summary(enrollment.gym_class),
    }


def _recurring_row(recurring, org_id):
    template = recurring.class_template
    return {
        'id': recurring.id,
        'start_date': recurring.start_date,
        'end_date': recurring.end_date,
        'plan_name': _plan_name_of(recurring.student_plan, org_id),
        'class_template': {
            'id': template.id,
            'name': template.name,
            'weekday': template.weekday,
            'start_time': template.start_time,
            'end_time': template.end_time,
            'discipline_name': template.discipline.name if template.discipline_id else None,
            'teacher_name': _full_name(template.teacher) if template.teacher_id else None,
        },
    }


class StudentOverviewView(APIView):
    """`GET /api/students/<student_id>/overview/` — ver docstring del módulo."""

    permission_classes = [ReportPermission]

    def get(self, request, student_id):
        actor = request.user

        # CHECK INLINE explícito, ADEMÁS de `permission_classes` — ver docstring del módulo.
        if actor.role != CustomUser.Role.GYM_ADMIN or not actor.organization_id:
            raise PermissionDenied(
                'Solo un administrador del gimnasio puede ver la vista integral del alumno.'
            )

        parsed_id = _parse_student_id(student_id)

        # Guarda de pertenencia ANTES de tocar cualquier otra tabla (lección 8.3): el alumno
        # se resuelve acotado por la organización del actor, y "no existe" y "es de otra
        # organización" salen exactamente igual (404 genérico, sin detalle propio).
        student = (
            User.objects.filter(pk=parsed_id, organization_id=actor.organization_id)
            .select_related('branch')
            .first()
        )
        if student is None:
            raise Http404

        org_id = actor.organization_id

        consumption_limit = _history_limit(request.query_params.get('consumption_limit'))
        attendance_limit = _history_limit(request.query_params.get('attendance_limit'))
        reservations_limit = _history_limit(request.query_params.get('reservations_limit'))

        memberships_qs = (
            # `user` va en el `select_related` aunque sea siempre el MISMO alumno:
            # `StudentPlanSerializer` publica `user_name`/`user_email`, y sin esto es una
            # consulta por membresía para releer la misma fila.
            StudentPlan.objects.select_related('plan', 'user')
            # Eje de pago + desglose sin N+1 por membresía — mismo prefetch que
            # `MembershipPlanViewSet.memberships`/`my_memberships` (views.py).
            .prefetch_related('origin_transactions', 'manual_payments', 'charge_line_items')
            .filter(user_id=student.id, organization_id=org_id)
            .order_by('-is_active', '-start_date', '-id')
        )
        memberships = StudentPlanSerializer(memberships_qs, many=True).data

        consumption_qs = (
            ConsumptionLog.objects
            .filter(
                user_id=student.id,
                # Doble intersección de organización (class_instance Y student_plan): ninguna
                # de las dos es la columna "oficial" del modelo (no existe), así que se acota
                # por las dos FKs que sí son de fiar en vez de confiar en una sola.
                class_instance__organization_id=org_id,
                student_plan__organization_id=org_id,
            )
            .select_related(
                'class_instance', 'class_instance__discipline', 'class_instance__teacher',
                'branch', 'student_plan__plan',
            )
            .order_by('-consumed_at', '-id')
        )
        consumption_rows, consumption_has_more = _paged(consumption_qs, consumption_limit)

        attendance_qs = (
            Attendance.objects
            .filter(student_id=student.id, gym_class__organization_id=org_id)
            .select_related('gym_class', 'gym_class__discipline', 'gym_class__teacher', 'marked_by')
            .order_by('-marked_at', '-id')
        )
        attendance_rows, attendance_has_more = _paged(attendance_qs, attendance_limit)

        reservations_qs = (
            Enrollment.objects
            .filter(student_id=student.id, gym_class__organization_id=org_id)
            .select_related(
                'gym_class', 'gym_class__discipline', 'gym_class__teacher', 'student_plan__plan',
            )
            .order_by('-gym_class__start_datetime', '-id')
        )
        reservation_rows, reservations_has_more = _paged(reservations_qs, reservations_limit)

        # Vigentes solamente (`is_active=True`): son la elección ACTUAL que gobierna reservas
        # futuras, no un historial. Acotadas por el número de plantillas de la organización,
        # así que van completas.
        recurring_qs = (
            RecurringEnrollment.objects
            .filter(student_id=student.id, is_active=True, class_template__organization_id=org_id)
            .select_related(
                'class_template', 'class_template__discipline', 'class_template__teacher',
                'student_plan__plan',
            )
            .order_by('class_template__weekday', 'class_template__start_time')
        )

        return Response({
            'student': {
                'id': student.id,
                'username': student.username,
                'name': _full_name(student),
                'email': student.email,
                'phone': student.phone,
                'role': student.role,
                'is_active': student.is_active,
                'branch_id': student.branch_id,
                'branch_name': student.branch.name if student.branch_id else None,
            },
            'memberships': memberships,
            'consumption': {
                'items': [_consumption_row(row, org_id) for row in consumption_rows],
                'limit': consumption_limit,
                'has_more': consumption_has_more,
            },
            'attendance': {
                'items': [_attendance_row(row) for row in attendance_rows],
                'limit': attendance_limit,
                'has_more': attendance_has_more,
            },
            'reservations': {
                'items': [_reservation_row(row, org_id) for row in reservation_rows],
                'limit': reservations_limit,
                'has_more': reservations_has_more,
            },
            'recurring_enrollments': [_recurring_row(row, org_id) for row in recurring_qs],
        })
