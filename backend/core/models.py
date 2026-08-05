import uuid
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.utils import timezone
import re
import secrets
import string

from .fields import EncryptedTextField


# Subdominios reservados para la plataforma: ninguna organización puede tomarlos
# (el apex y estos labels resuelven a contexto plataforma / infra, no a una org).
RESERVED_SUBDOMAINS = {
    'admin', 'app', 'www', 'api', 'qa', 'static', 'media', 'localhost', 'mail',
}

validate_subdomain_format = RegexValidator(
    regex=r'^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$',
    message='El subdominio debe ser minúsculas, números y guiones (sin espacios ni mayúsculas).',
)


def validate_subdomain(value):
    """Valida formato y que no sea un subdominio reservado."""
    validate_subdomain_format(value)
    if value in RESERVED_SUBDOMAINS:
        raise ValidationError(f'"{value}" es un subdominio reservado y no puede usarse.')


def generate_attendance_screen_code():
    alphabet = string.ascii_uppercase + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(12))


def generate_attendance_screen_session_code():
    alphabet = string.ascii_uppercase + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(6))


def generate_invite_token():
    return secrets.token_urlsafe(24)


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Organization(TimestampedModel):
    name = models.CharField(max_length=150)
    slug = models.SlugField(unique=True)
    # Subdominio de tenant: el host <subdomain>.<BASE_DOMAIN> resuelve a esta org
    # (ver core.middleware.OrganizationMiddleware). Único; nullable a nivel de DB
    # para migraciones seguras, pero requerido al crear vía API.
    subdomain = models.CharField(
        max_length=50,
        unique=True,
        null=True,
        blank=True,
        validators=[validate_subdomain],
    )
    country = models.CharField(max_length=80, blank=True)
    city = models.CharField(max_length=80, blank=True)
    logo = models.ImageField(upload_to='organizations/logos/', blank=True, null=True)
    primary_color = models.CharField(max_length=20, blank=True)
    secondary_color = models.CharField(max_length=20, blank=True)
    is_active = models.BooleanField(default=True)
    attendance_screen_code = models.CharField(
        max_length=32,
        unique=True,
        default=generate_attendance_screen_code,
    )
    attendance_screen_session_code = models.CharField(
        max_length=16,
        unique=True,
        null=True,
        blank=True,
    )
    attendance_screen_session_expires_at = models.DateTimeField(null=True, blank=True)
    public_invite_token = models.CharField(
        max_length=64,
        unique=True,
        default=generate_invite_token,
    )
    public_registration_enabled = models.BooleanField(default=True)
    # Ventana de validez de la clase de prueba: cuántos días hacia adelante se puede
    # agendar una prueba. Configurable por org; default 7 días (evita agendar a meses).
    trial_validity_days = models.PositiveIntegerField(
        default=7,
        help_text='Días hacia adelante en que se puede agendar una clase de prueba.',
    )
    # Ventana de materialización de series recurrentes: cuántos días hacia adelante
    # se generan clases concretas a partir de una serie. Configurable por org; default 21 días.
    class_generation_window_days = models.PositiveIntegerField(
        default=21,
        validators=[MaxValueValidator(366)],
        help_text='Días hacia adelante en que se materializan clases de series recurrentes.',
    )
    # Colchón de poda: cuántos días tiene que llevar TERMINADA una clase vacía para que el
    # job advance_class_windows la borre. Margen para backfill tardío (pasar lista el lunes
    # por la clase del viernes). 0 = sin colchón (podar apenas termina).
    class_pruning_grace_days = models.PositiveIntegerField(
        default=7,
        validators=[MaxValueValidator(90)],
        help_text='Días de gracia antes de podar una clase terminada sin inscripciones ni historia.',
    )

    class Meta:
        ordering = ['name']

    def save(self, *args, **kwargs):
        # Red de seguridad: ninguna organización debe quedar sin subdominio (sería
        # inalcanzable por el middleware). La API EXIGE subdomain al crear (serializer),
        # pero ORM/admin/seed pueden omitirlo; aquí lo derivamos del slug, único.
        if not self.subdomain and self.slug:
            base = re.sub(r'[^a-z0-9-]+', '-', self.slug.lower()).strip('-')[:50] or 'org'
            candidate, n = base, 2
            while Organization.objects.exclude(pk=self.pk).filter(subdomain=candidate).exists():
                candidate = f'{base}-{n}'[:50]
                n += 1
            self.subdomain = candidate
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class TrialFollowupConfiguration(TimestampedModel):
    """Configuración por organización del email de seguimiento post clase de prueba.

    Variables disponibles en asunto/cuerpo: {student_name}, {org_name},
    {class_name}, {teacher_name}, {signup_link}.
    """

    DEFAULT_SUBJECT = '¿Qué te pareció tu clase en {org_name}?'
    DEFAULT_BODY = (
        'Hola {student_name},\n\n'
        'Gracias por venir a tu clase de prueba de {class_name} en {org_name}. '
        '¡Esperamos que la hayas disfrutado!\n\n'
        'Si quieres seguir entrenando con nosotros, inscríbete aquí: {signup_link}\n\n'
        '¡Te esperamos!\n— Equipo {org_name}'
    )

    organization = models.OneToOneField(
        Organization,
        on_delete=models.CASCADE,
        related_name='trial_followup_config',
    )
    is_active = models.BooleanField(
        default=True,
        help_text='¿Enviar emails de seguimiento de clases de prueba?',
    )
    minutes_after_class_end = models.PositiveIntegerField(
        default=30,
        help_text='Minutos tras el fin de la clase para enviar el email.',
    )
    email_subject = models.CharField(max_length=200, default=DEFAULT_SUBJECT)
    email_body = models.TextField(default=DEFAULT_BODY)

    class Meta:
        verbose_name = 'Configuración de email de prueba'
        verbose_name_plural = 'Configuraciones de email de prueba'

    def __str__(self):
        return f'Config prueba - {self.organization.name}'


class Branch(TimestampedModel):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='branches')
    name = models.CharField(max_length=120)
    code = models.CharField(max_length=30, blank=True)
    address = models.CharField(max_length=255, blank=True)
    logo = models.ImageField(upload_to='branches/logos/', blank=True, null=True)
    primary_color = models.CharField(max_length=20, blank=True)
    secondary_color = models.CharField(max_length=20, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['organization__name', 'name']
        unique_together = ('organization', 'name')

    def __str__(self):
        return f'{self.name} - {self.organization.name}'


class Person(TimestampedModel):
    ROLE_CHOICES = [
        ('student', 'Alumno'),
        ('teacher', 'Profesor'),
        ('admin', 'Administrador'),
    ]

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='people')
    branch = models.ForeignKey(Branch, on_delete=models.SET_NULL, null=True, blank=True, related_name='people')
    first_name = models.CharField(max_length=80)
    last_name = models.CharField(max_length=80, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['first_name', 'last_name']

    def __str__(self):
        full_name = f'{self.first_name} {self.last_name}'.strip()
        return full_name or self.email


class ClassType(TimestampedModel):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='class_types')
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True, default='')
    color = models.CharField(max_length=20, default='#f97316')
    duration_minutes = models.PositiveIntegerField(default=60)
    is_private = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']
        unique_together = ('organization', 'name')

    def __str__(self):
        return self.name


class Discipline(TimestampedModel):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='disciplines')
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True, default='')
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']
        unique_together = ('organization', 'name')

    def __str__(self):
        return self.name


class GymClass(TimestampedModel):
    class Status(models.TextChoices):
        SCHEDULED = 'scheduled', 'Programada'
        IN_PROGRESS = 'in_progress', 'En progreso'
        COMPLETED = 'completed', 'Completada'
        CANCELLED = 'cancelled', 'Cancelada'
        COMPLETED_EARLY = 'completed_early', 'Completada anticipadamente'
        SUSPENDED = 'suspended', 'Suspendida'

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='classes')
    class_template = models.ForeignKey(
        'ClassTemplate',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='instances',
    )
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='classes')
    teacher = models.ForeignKey('accounts.CustomUser', on_delete=models.SET_NULL, null=True, blank=True, related_name='teaching_classes')
    class_type = models.ForeignKey(ClassType, on_delete=models.SET_NULL, null=True, blank=True, related_name='classes')
    discipline = models.ForeignKey(Discipline, on_delete=models.SET_NULL, null=True, blank=True, related_name='classes')
    name = models.CharField(max_length=150)
    start_datetime = models.DateTimeField()
    end_datetime = models.DateTimeField()
    capacity = models.PositiveIntegerField(default=20)
    is_trial_eligible = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SCHEDULED)
    created_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_classes',
    )
    closed_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='closed_classes',
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    closure_comment = models.TextField(blank=True)
    suspended_at = models.DateTimeField(null=True, blank=True)
    suspend_reason = models.TextField(blank=True, default='')
    suspended_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='suspended_classes',
    )
    reactivation_expected_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['-start_datetime']
        constraints = [
            # Cierra la race de doble consumo del rail de materialización de series:
            # `generate_instances_for_template_range` (services/recurrence.py) hace
            # check-then-create —`exists()` y después `create()`— y dos escritores
            # simultáneos (el botón "Actualizar clases", el cron `advance_class_windows`,
            # dos tabs, dos admins) pasaban los dos el `exists()` y creaban la MISMA
            # instancia dos veces. El daño real no era la fila repetida sino que el sync
            # de recurrencias corre sobre cada instancia creada y le cobraba el consumo
            # al alumno DOS veces. La unicidad tiene que vivir en la BD: en la aplicación
            # no hay forma de cerrarlo sin un lock, y el perdedor de la carrera ahora
            # levanta IntegrityError y se saltea limpio (sin sumar a `created_ids`, así
            # que sin cobrar).
            #
            # `class_template` es nullable (SET_NULL): en Postgres y en SQLite los NULL no
            # chocan entre sí, así que las clases creadas a mano —sin plantilla— quedan
            # FUERA de la restricción, que es lo correcto: dos clases sueltas pueden
            # compartir horario.
            #
            # Es estrictamente MÁS LAXA que la guarda que ya aplicaba el generador (que
            # filtra por `start_datetime__date`, o sea una instancia por plantilla y por
            # DÍA): no prohíbe nada que el rail permitiera antes.
            #
            # ⚠️ POR QUÉ `F(...)` Y NO `fields=[...]` (no es cosmético, no lo "simplifiques"):
            # DRF 3.15 lee `Model._meta.constraints` y, por cada `UniqueConstraint` con
            # `len(constraint.fields) > 1`, le inyecta al ModelSerializer un
            # `UniqueTogetherValidator` Y marca sus campos como `required=True`
            # (`serializers.get_uniqueness_extra_kwargs`). Con la forma `fields=[...]`,
            # `GymClassSerializer` pasaba a exigir `class_template` en el POST y
            # `POST /api/classes/` —la creación de una clase SUELTA, sin plantilla, que es
            # el flujo normal del gym_admin— empezaba a responder
            # `400 {"class_template": ["Este campo es requerido."]}`. Verificado: rompía 9
            # tests de la suite (test_teacher_overlap_relaxed, test_overlap_checks_org_scope,
            # test_cross_org_write_isolation, test_branch_delete_guard).
            # Poner `required=False` en el serializer NO alcanza:
            # `UniqueTogetherValidator.enforce_required_fields` exige la clave en `attrs`
            # sin mirar el flag.
            # Con expresiones, `constraint.fields` queda vacío, DRF ignora la constraint y
            # la API se comporta EXACTAMENTE como antes; en la BD el efecto es el mismo
            # (índice único sobre las dos columnas, NULL distintos entre sí).
            # CONTRAPARTIDA ACEPTADA: al no haber validador de DRF, un POST a mano que
            # mande `class_template` + un `start_datetime` ya ocupado devuelve 500
            # (IntegrityError) en lugar de 400. No es alcanzable desde la UI (el form de
            # clase suelta no manda plantilla) y no corrompe datos.
            models.UniqueConstraint(
                models.F('class_template'),
                models.F('start_datetime'),
                name='uniq_class_instance_per_template_slot',
            ),
        ]

    def __str__(self):
        return self.name

    @property
    def is_closed(self):
        return self.status in {self.Status.COMPLETED, self.Status.CANCELLED, self.Status.COMPLETED_EARLY}

    @property
    def is_suspended(self):
        return self.status == self.Status.SUSPENDED

    def consolidate_attendance(self, marked_by=None, marked_at=None):
        from django.contrib.auth import get_user_model

        if self.status == self.Status.CANCELLED:
            return

        AttendanceModel = Attendance
        User = get_user_model()
        timestamp = marked_at or timezone.now()
        active_student_ids = list(
            self.enrollments.filter(status='active').values_list('student_id', flat=True)
        )
        existing_ids = set(
            AttendanceModel.objects.filter(gym_class=self).values_list('student_id', flat=True)
        )

        create_items = []
        safe_marked_by = marked_by if isinstance(marked_by, User) else None
        for student_id in active_student_ids:
            if student_id in existing_ids:
                continue
            create_items.append(
                AttendanceModel(
                    gym_class=self,
                    student_id=student_id,
                    status=AttendanceModel.Status.ABSENT,
                    source=AttendanceModel.Source.SYSTEM,
                    marked_by=safe_marked_by,
                    marked_at=timestamp,
                    checked_at=timestamp,
                )
            )

        if create_items:
            AttendanceModel.objects.bulk_create(create_items)

    def refresh_status_from_schedule(self, now=None, save=True):
        now = now or timezone.now()
        changed = False

        if self.status not in {self.Status.CANCELLED, self.Status.COMPLETED_EARLY, self.Status.COMPLETED, self.Status.SUSPENDED}:
            if now >= self.end_datetime:
                self.status = self.Status.COMPLETED
                self.is_active = False
                self.closed_at = self.closed_at or now
                changed = True
            elif now >= self.start_datetime:
                if self.status != self.Status.IN_PROGRESS:
                    self.status = self.Status.IN_PROGRESS
                    changed = True
                self.is_active = True
            else:
                if self.status != self.Status.SCHEDULED:
                    self.status = self.Status.SCHEDULED
                    changed = True
                self.is_active = True

        if save and changed:
            self.save(update_fields=['status', 'is_active', 'closed_at', 'updated_at'])

        if self.status in {self.Status.COMPLETED, self.Status.COMPLETED_EARLY}:
            self.consolidate_attendance(marked_by=self.closed_by, marked_at=self.closed_at or now)

        return changed


class Enrollment(TimestampedModel):
    STATUS_CHOICES = [
        ('active', 'Activa'),
        ('cancelled', 'Cancelada'),
    ]

    gym_class = models.ForeignKey(GymClass, on_delete=models.CASCADE, related_name='enrollments')
    student = models.ForeignKey('accounts.CustomUser', on_delete=models.CASCADE, related_name='class_enrollments')
    recurring_enrollment = models.ForeignKey(
        'RecurringEnrollment',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='enrollments',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    is_trial = models.BooleanField(
        default=False,
        help_text='Esta inscripción se generó mediante una clase de prueba.',
    )
    # De dónde se descontó esta reserva (#9): registro HISTÓRICO de imputación, no la
    # fuente del reverso del consumo —eso lo sigue resolviendo `ConsumptionLog` vía
    # `get_enrollment_student_plan`, que no cambia—. NULL significa fila anterior al
    # backfill sin `ConsumptionLog` que la respalde, reserva de prueba (trial) o reserva
    # sin plan (`require_plan=False`). `SET_NULL` porque borrar la membresía no puede
    # llevarse la reserva.
    student_plan = models.ForeignKey(
        'StudentPlan',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='enrollments',
    )

    class Meta:
        ordering = ['created_at']
        unique_together = ('gym_class', 'student')

    def __str__(self):
        return f'{self.student} - {self.gym_class}'


class Attendance(TimestampedModel):
    class Status(models.TextChoices):
        PRESENT = 'present', 'Presente'
        ABSENT = 'absent', 'Ausente'
        LATE = 'late', 'Tarde'
        EXCUSED = 'excused', 'Justificado'
        NO_SHOW = 'no_show', 'No asistió'

    class Source(models.TextChoices):
        MANUAL = 'manual', 'Manual'
        QR = 'qr', 'QR'
        SYSTEM = 'system', 'Sistema'

    gym_class = models.ForeignKey(GymClass, on_delete=models.CASCADE, related_name='attendances', null=True, blank=True)
    student = models.ForeignKey('accounts.CustomUser', on_delete=models.CASCADE, related_name='attendance_records', null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ABSENT)
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.MANUAL)
    marked_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='marked_attendances',
    )
    marked_at = models.DateTimeField(default=timezone.now)
    checked_at = models.DateTimeField(default=timezone.now)
    trial_followup_sent_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Cuándo se envió el email de seguimiento de la clase de prueba.',
    )

    class Meta:
        ordering = ['-marked_at', 'id']
        unique_together = ('gym_class', 'student')

    def __str__(self):
        return f'Asistencia {self.gym_class_id}-{self.student_id}'


class AttendanceChangeLog(TimestampedModel):
    """Registro append-only de correcciones de asistencia.

    Se escribe solo cuando un admin cambia un `status` ya registrado en `Attendance`.
    No hay endpoint de UPDATE ni de DELETE sobre estas filas: la existencia de la fila
    es el hecho.
    """

    # Hecho SOBRE ese registro de asistencia: no significa nada sin él (mismo
    # razonamiento que `ManualPayment.student_plan`, models.py:991-1002). PROTECT
    # convertiría en 500 el borrado en cascada de clases/usuarios que hoy funciona.
    attendance = models.ForeignKey(
        Attendance,
        on_delete=models.CASCADE,
        related_name='change_logs',
    )
    previous_status = models.CharField(max_length=10, choices=Attendance.Status.choices)
    new_status = models.CharField(max_length=10, choices=Attendance.Status.choices)
    # Distingue la corrección manual de admin (10.2) de la pisada por check-in QR
    # (10.2-H1: un alumno que se marca por QR sobre un status ya corregido). Default
    # MANUAL para que las filas existentes, todas de corrección manual, queden coherentes.
    source = models.CharField(max_length=10, choices=Attendance.Source.choices, default=Attendance.Source.MANUAL)
    # Quién hizo el cambio. SET_NULL, mismo razonamiento que
    # `ManualPayment.recorded_by` (models.py:1025-1035): perder el autor es aceptable,
    # perder el hecho no. OJO: esta FK NO es el ancla multitenant; para eso está la
    # columna `organization`.
    changed_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='attendance_changes_recorded',
    )
    # `default=timezone.now` y no `auto_now_add`, igual que `ManualPayment.recorded_at`
    # (models.py:1043-1047): se llena solo pero sigue siendo escribible desde código.
    changed_at = models.DateTimeField(default=timezone.now)
    # Se estampa desde la organización YA VALIDADA del actor (la guarda de
    # pertenencia corre primero en la view): nunca del payload, nunca derivada de
    # `changed_by` (SET_NULL + el usuario puede mudarse de org). PROTECT por el mismo
    # motivo que `ManualPayment.organization` (models.py:981-985): borrar la
    # organización no puede llevarse la auditoría en silencio, y
    # `OrganizationViewSet.destroy` ya captura `ProtectedError`.
    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name='attendance_change_logs',
    )

    class Meta:
        ordering = ['-changed_at', 'id']

    def __str__(self):
        return f'{self.attendance_id}: {self.previous_status} -> {self.new_status}'


class MembershipPlan(TimestampedModel):
    PLAN_KIND_CHOICES = [
        ('monthly', 'Mensual'),
        ('pack', 'Pack'),
        ('single', 'Clase suelta'),
        ('private', 'Privada'),
    ]

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='plans')
    name = models.CharField(max_length=120)
    plan_kind = models.CharField(max_length=20, choices=PLAN_KIND_CHOICES)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    class_limit = models.PositiveIntegerField(default=0)
    expires_in_days = models.PositiveIntegerField(default=30)
    allows_rollover = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Plan(TimestampedModel):
    class PlanType(models.TextChoices):
        MONTHLY = 'monthly', 'Mensual'
        PACK = 'pack', 'Pack'
        SINGLE_CLASS = 'single_class', 'Clase suelta'
        TRIAL = 'trial', 'Trial'
        GIFTCARD = 'giftcard', 'Giftcard'

    # Tipos que el gimnasio asigna a mano y NO se venden en línea. Fuente única de verdad:
    # la usan `create_checkout` (rechaza la compra) y el catálogo del alumno en
    # `MembershipPlanViewSet.get_queryset` (los saca de la vitrina). Estaban duplicados como
    # literales en el servicio de pagos y en el frontend, y por eso divergieron.
    NOT_PURCHASABLE_ONLINE = frozenset({PlanType.TRIAL, PlanType.GIFTCARD})

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='legacy_plans')
    # Alcance del plan: NULL = GLOBAL (vale en toda la organización); con sucursal =
    # EXCLUSIVO (solo cubre las clases de esa sede). `RESTRICT` y no `SET_NULL` a
    # propósito: como NULL significa "todas las sedes", un SET_NULL convertiría un plan
    # exclusivo en global al borrar la sucursal —la misma inversión de semántica que ya
    # tenía `TeacherPaymentRule.branch`—. RESTRICT lo impide a nivel de DB pero deja
    # pasar el borrado en cascada de la organización, donde el plan también se elimina.
    branch = models.ForeignKey(
        Branch,
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name='exclusive_plans',
        help_text='Vacío = plan global de la organización. Con sucursal = exclusivo de esa sede.',
    )
    name = models.CharField(max_length=120)
    plan_type = models.CharField(max_length=20, choices=PlanType.choices)
    total_classes = models.IntegerField()
    unlimited_classes = models.BooleanField(default=False)
    duration_days = models.IntegerField()
    price = models.FloatField()
    discount_percentage = models.FloatField(default=0)
    is_public = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class StudentPlanQuerySet(models.QuerySet):
    """Fuente única de la mitad TEMPORAL del predicado de vigencia.

    El bloque `is_active=True + start_date__lte + end_date__gte` estaba escrito tres veces
    —`get_active_student_plan`, `_get_active_student_plan_map` y `my_memberships`— y las
    copias ya habían divergido en el origen de la organización y en el desempate. Vive acá
    como queryset, y no como property del modelo, porque los tres consumidores lo usan
    dentro de un `filter()` y necesitan encadenarlo sobre su propio scope.

    La otra mitad del predicado —saldo y matrícula— NO está acá: no se puede expresar en
    un `filter()` sin duplicar la regla de `unlimited_classes`, y además produce estados
    distinguibles ("agotado" no es lo mismo que "vencido"). Vive en
    `core.services.plans.describe_student_plan`, que consume este queryset.
    """

    def valid_on(self, on_date):
        """Membresías cuya ventana cubre `on_date` y que no fueron dadas de baja.

        `on_date` es OBLIGATORIO a propósito. El default implícito a "hoy" es lo que hace
        que una reserva para una clase futura se valide contra la vigencia de hoy y
        descuente saldo para clases posteriores al `end_date` (#9): sin default, el
        llamador tiene que declarar contra qué fecha evalúa.
        """
        return self.filter(
            is_active=True,
            start_date__lte=on_date,
            end_date__gte=on_date,
        )


class StudentPlan(TimestampedModel):
    user = models.ForeignKey('accounts.CustomUser', on_delete=models.CASCADE, related_name='student_plans')
    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name='student_plans')
    # Organización que VENDIÓ la membresía. Es una copia de `plan.organization`, no una
    # dimensión nueva: se desnormaliza para que la organización de una membresía no
    # dependa de seguir el join `plan__organization`. La leen las guardas multitenant del
    # motor de importación (`org_field='organization'`) y `clean()` la mantiene en sincronía
    # con el plan.
    #
    # NO existe para imponer unicidad. Un alumno puede tener varias membresías activas a la
    # vez en esta misma organización (dos disciplinas) —ver el `Meta` más abajo: no hay
    # constraint sobre (user, organization) y no debe agregarse—.
    #
    # `PROTECT` y no CASCADE: perder la organización de una membresía histórica corrompe
    # el dinero (`final_price`, matrícula) y el consumo (`ConsumptionLog` cuelga de acá).
    # El borrado de una organización con membresías tiene que ser una decisión explícita,
    # no un efecto colateral.
    #
    # OJO: la fuente de verdad es `plan.organization`, JAMÁS `user.organization`. Un
    # alumno movido de organización conserva vivas las membresías que le vendió la
    # anterior (`user` es CASCADE sobre el usuario, no sobre la org); derivar de ahí las
    # movería de tenant.
    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name='student_plans',
    )
    # Sucursal en que se activó la membresía; se deriva del plan (NULL si el plan es
    # global). Es un registro histórico: la restricción de reserva se evalúa contra
    # `plan.branch`, que es la fuente de verdad del alcance. `SET_NULL` alcanza porque
    # aquí NULL significa "sin sede registrada", no "todas las sedes".
    branch = models.ForeignKey(
        Branch,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='student_plans',
    )
    start_date = models.DateField()
    end_date = models.DateField()
    total_classes = models.IntegerField()
    unlimited_classes = models.BooleanField(default=False)
    classes_used = models.IntegerField(default=0)
    discount_percentage = models.FloatField(default=0)
    final_price = models.FloatField(null=True, blank=True)
    enrollment_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text='Matrícula individual del alumno para este plan (0 = sin matrícula).',
    )
    enrollment_fee_paid_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Cuándo pagó la matrícula. Vacío = pendiente.',
    )
    enrollment_fee_due_at = models.DateField(
        null=True,
        blank=True,
        help_text='Fecha de vencimiento de la matrícula. Por defecto un año desde la creación.',
    )
    is_active = models.BooleanField(default=True)

    # `from_queryset` y NO un override de `get_queryset()`: el manager tiene que seguir
    # devolviendo TODAS las filas. `plan.student_plans` (related manager) resuelve por
    # `_default_manager`, y la guarda de borrado en cascada de planes cuenta membresías por
    # ahí; un manager que filtrara volvería esa cuenta parcial y dejaría pasar el borrado.
    # Lo único que agrega es el método `valid_on`, explícito en cada llamador.
    objects = models.Manager.from_queryset(StudentPlanQuerySet)()

    class Meta:
        # SIN constraint de unicidad sobre (user, organization) a propósito: un alumno
        # puede tener VARIAS membresías activas al mismo tiempo en la misma organización
        # —contratar dos disciplinas, p. ej. un plan de 4 BJJ más uno de 8 kickboxing—.
        # Cada contratación es su propia fila y ninguna desplaza a las otras.
        ordering = ['-start_date']

    def __str__(self):
        return f'{self.user} - {self.plan}'

    def clean(self):
        # `organization` es una copia de `plan.organization`, y nada en el esquema obliga a
        # que sigan iguales. Importa porque las guardas multitenant del importador pasaron
        # a leer esta columna (`org_field='organization'`): si se desincronizara, la org B
        # podría reclamar —y reactivar— una membresía que vendió la org A y que el resto
        # del código sigue mostrando como de A. El importador llama `full_clean()` en el
        # create y en el update, así que la guarda cubre el upsert; el admin también.
        super().clean()
        if self.plan_id and self.organization_id != self.plan.organization_id:
            raise ValidationError(
                {'organization': 'La organización debe ser la misma que la del plan.'}
            )

    def save(self, *args, **kwargs):
        # created_at (auto_now_add) es NULL hasta DESPUÉS del INSERT: por eso el
        # vencimiento por defecto se calcula tras super().save(), no antes.
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if (
            is_new
            and self.enrollment_fee
            and self.enrollment_fee > 0
            and self.enrollment_fee_due_at is None
            and self.created_at is not None
        ):
            self.enrollment_fee_due_at = (self.created_at + timedelta(days=365)).date()
            super().save(update_fields=['enrollment_fee_due_at', 'updated_at'])


class ConsumptionLog(TimestampedModel):
    user = models.ForeignKey('accounts.CustomUser', on_delete=models.CASCADE, related_name='consumption_logs')
    student_plan = models.ForeignKey(StudentPlan, on_delete=models.CASCADE, related_name='consumption_logs')
    class_instance = models.ForeignKey(GymClass, on_delete=models.CASCADE, related_name='consumption_logs')
    # Sucursal donde se consumió la sesión; se deriva de `class_instance.branch`. Se
    # desnormaliza para que el consumo conserve la sede aunque la clase cambie de
    # sucursal después. NULL solo en filas anteriores a la migración de backfill.
    branch = models.ForeignKey(
        Branch,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='consumption_logs',
    )
    consumed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-consumed_at']

    def __str__(self):
        return f'Consumo {self.user_id} - {self.class_instance_id}'


class OrganizationExpiryNotificationConfig(TimestampedModel):
    """Qué avisos de vencimiento manda cada organización. APAGADA por defecto (7.4).

    Los defaults son deliberadamente inertes —lista vacía y flag en False— porque el job
    corre sobre alumnos reales: al desplegar no puede salir ni un correo hasta que cada
    gimnasio lo active a mano. La data migration que crea las filas de las organizaciones
    existentes usa exactamente estos defaults por el mismo motivo.

    Por ahora solo se edita desde el admin de Django: 7.4 no expone API ni UI.
    """

    # Tope del horizonte de aviso y de la cantidad de avisos. No son reglas de negocio
    # finas, son cotas de cordura: evitan que un typo en el admin genere un recordatorio
    # por cada día de un año o avise el vencimiento con una década de anticipación.
    MAX_DAYS_BEFORE = 365
    MAX_REMINDERS = 10

    organization = models.OneToOneField(
        Organization,
        on_delete=models.CASCADE,
        related_name='expiry_notification_config',
    )
    # JSONField y no ArrayField de postgres: la suite corre en SQLite (`settings_test`) y
    # ArrayField no tiene `db_type` fuera de postgres, así que la migración ni siquiera
    # aplicaría ahí. Guarda una lista de enteros; `clean()` es quien impone esa forma.
    reminder_days_before = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            'Días de anticipación con que avisar el vencimiento, p. ej. [10, 3]. '
            'Vacío = no se envían recordatorios.'
        ),
    )
    send_expired_notice = models.BooleanField(
        default=False,
        help_text='¿Avisar al alumno el día en que su plan vence?',
    )

    class Meta:
        verbose_name = 'Configuración de avisos de vencimiento'
        verbose_name_plural = 'Configuraciones de avisos de vencimiento'

    def __str__(self):
        return f'Avisos de vencimiento - {self.organization.name}'

    @property
    def is_enabled(self):
        """¿La organización pidió ALGO? Si no, el job la saltea entera."""
        return bool(self.reminder_days_before) or self.send_expired_notice

    def clean(self):
        super().clean()
        days = self.reminder_days_before
        if days in (None, ''):
            self.reminder_days_before = []
            return
        if not isinstance(days, list):
            raise ValidationError(
                {'reminder_days_before': 'Debe ser una lista de días, p. ej. [10, 3].'}
            )
        if len(days) > self.MAX_REMINDERS:
            raise ValidationError(
                {'reminder_days_before': f'Máximo {self.MAX_REMINDERS} recordatorios.'}
            )
        cleaned = []
        for value in days:
            # `bool` es subclase de `int` y no queremos aceptar True como "1 día".
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValidationError(
                    {'reminder_days_before': f'"{value}" no es un número de días.'}
                )
            if value < 1 or value > self.MAX_DAYS_BEFORE:
                raise ValidationError({
                    'reminder_days_before':
                        f'Los días deben estar entre 1 y {self.MAX_DAYS_BEFORE} ("{value}").',
                })
            cleaned.append(value)
        if len(set(cleaned)) != len(cleaned):
            raise ValidationError(
                {'reminder_days_before': 'No repitas el mismo día de anticipación.'}
            )
        # Orden descendente: es el orden en que el alumno los recibe. Se normaliza en vez
        # de rechazarse porque el orden no cambia lo que se envía y exigirlo a mano en el
        # admin sería una molestia sin contrapartida.
        self.reminder_days_before = sorted(cleaned, reverse=True)


class PlanExpiryNotification(TimestampedModel):
    """Un aviso YA ENVIADO. Es el registro de idempotencia del job (7.4).

    El job corre varias veces al día, así que "¿ya avisé esto?" no puede depender de la
    hora en que se ejecutó ni de un flag en `StudentPlan`: se responde con la existencia de
    la fila. Cada envío entra por `get_or_create`, y el par (membresía, tipo, offset) es la
    identidad del aviso.
    """

    class Kind(models.TextChoices):
        REMINDER = 'reminder', 'Por vencer'
        EXPIRED = 'expired', 'Vencido'

    student_plan = models.ForeignKey(
        StudentPlan,
        on_delete=models.CASCADE,
        related_name='expiry_notifications',
    )
    # Copia de `student_plan.organization`. Se desnormaliza para que el scope multitenant
    # del job sea un filtro directo y no un join, igual que en `StudentPlan`. `PROTECT` por
    # coherencia con esa FK: la organización de una membresía no desaparece de costado.
    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name='plan_expiry_notifications',
    )
    kind = models.CharField(max_length=16, choices=Kind.choices)
    # Solo para REMINDER: con qué anticipación se mandó. NULL en EXPIRED, que ocurre una
    # sola vez por membresía.
    days_before = models.PositiveIntegerField(null=True, blank=True)
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-sent_at']
        constraints = [
            models.UniqueConstraint(
                fields=['student_plan', 'kind', 'days_before'],
                condition=models.Q(days_before__isnull=False),
                name='uniq_plan_expiry_reminder_per_offset',
            ),
            # La segunda constraint NO es redundante: en SQL `NULL != NULL`, así que un
            # índice único sobre (plan, kind, days_before) deja pasar infinitas filas con
            # `days_before` NULL —justo el caso del aviso de vencido—. Sin esto, la
            # idempotencia del "venció" quedaría solo en el `get_or_create` de la
            # aplicación y dos corridas simultáneas mandarían el correo dos veces.
            models.UniqueConstraint(
                fields=['student_plan', 'kind'],
                condition=models.Q(days_before__isnull=True),
                name='uniq_plan_expiry_notice_without_offset',
            ),
        ]

    def __str__(self):
        offset = f' ({self.days_before}d)' if self.days_before is not None else ''
        return f'{self.get_kind_display()}{offset} - plan {self.student_plan_id}'


class TeacherPaymentRule(TimestampedModel):
    class PaymentType(models.TextChoices):
        FIXED_PER_CLASS = 'fixed_per_class', 'Fijo por clase'
        PER_STUDENT = 'per_student', 'Por alumno presente'
        PER_ENROLLED = 'per_enrolled', 'Por alumno inscrito'
        PER_HOUR = 'per_hour', 'Por hora'
        REVENUE_SHARE = 'revenue_share', 'Porcentaje de ingreso'
        MONTHLY_FIXED = 'monthly_fixed', 'Sueldo mensual fijo'
        PER_PLAN_PRICE = 'per_plan_price', 'Porcentaje del precio del plan del alumno'

    class CalculationBase(models.TextChoices):
        ATTENDANCE = 'attendance', 'Asistencia'
        ENROLLMENT = 'enrollment', 'Inscripcion'

    class PerPlanPriceBase(models.TextChoices):
        ACTIVE_ENROLLMENTS = 'active_enrollments', 'Todos los alumnos inscritos'
        PRESENT_ATTENDEES = 'present_attendees', 'Solo alumnos presentes'

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='payment_rules')
    teacher = models.ForeignKey('accounts.CustomUser', on_delete=models.CASCADE, related_name='payment_rules', null=True, blank=True)
    teachers = models.ManyToManyField('accounts.CustomUser', related_name='assigned_payment_rules', blank=True)
    branch = models.ForeignKey(Branch, on_delete=models.SET_NULL, null=True, blank=True, related_name='payment_rules')
    discipline = models.ForeignKey(Discipline, on_delete=models.SET_NULL, null=True, blank=True, related_name='payment_rules')
    class_type = models.ForeignKey(ClassType, on_delete=models.SET_NULL, null=True, blank=True, related_name='payment_rules')
    payment_type = models.CharField(max_length=30, choices=PaymentType.choices, default=PaymentType.FIXED_PER_CLASS)
    amount = models.FloatField(default=0)
    calculation_base = models.CharField(max_length=20, choices=CalculationBase.choices, null=True, blank=True)
    per_plan_price_base = models.CharField(
        max_length=20,
        choices=PerPlanPriceBase.choices,
        default=PerPlanPriceBase.ACTIVE_ENROLLMENTS,
        help_text='Solo para per_plan_price: ¿sobre quién se calcula el porcentaje?',
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['-updated_at', '-id']

    def __str__(self):
        return f'Regla #{self.id} - {self.payment_type}'

    def clean(self):
        if self.teacher and self.teacher.role != 'teacher':
            raise ValidationError({'teacher': 'El usuario seleccionado no es profesor.'})
        if self.teacher and self.organization_id and self.teacher.organization_id != self.organization_id:
            raise ValidationError({'teacher': 'El profesor no pertenece a la organizacion indicada.'})
        if self.branch and self.organization_id and self.branch.organization_id != self.organization_id:
            raise ValidationError({'branch': 'La sucursal no pertenece a la organizacion indicada.'})
        if self.discipline and self.organization_id and self.discipline.organization_id != self.organization_id:
            raise ValidationError({'discipline': 'La disciplina no pertenece a la organizacion indicada.'})
        if self.class_type and self.organization_id and self.class_type.organization_id != self.organization_id:
            raise ValidationError({'class_type': 'El tipo de clase no pertenece a la organizacion indicada.'})
        if self.payment_type == self.PaymentType.REVENUE_SHARE:
            if self.calculation_base not in {self.CalculationBase.ATTENDANCE, self.CalculationBase.ENROLLMENT}:
                raise ValidationError({'calculation_base': 'Debes elegir la base de calculo para revenue_share.'})
            if self.amount < 0 or self.amount > 100:
                raise ValidationError({'amount': 'El porcentaje debe estar entre 0 y 100.'})
        elif self.payment_type == self.PaymentType.PER_PLAN_PRICE:
            # Usa per_plan_price_base (no calculation_base) para elegir la base.
            if self.calculation_base:
                raise ValidationError({'calculation_base': 'per_plan_price usa per_plan_price_base, no calculation_base.'})
            if self.per_plan_price_base not in {
                self.PerPlanPriceBase.ACTIVE_ENROLLMENTS,
                self.PerPlanPriceBase.PRESENT_ATTENDEES,
            }:
                raise ValidationError({'per_plan_price_base': 'Elige la base de cálculo para per_plan_price.'})
            if self.amount < 0 or self.amount > 100:
                raise ValidationError({'amount': 'El porcentaje debe estar entre 0 y 100.'})
        elif self.payment_type == self.PaymentType.PER_STUDENT:
            if self.calculation_base and self.calculation_base != self.CalculationBase.ATTENDANCE:
                raise ValidationError({'calculation_base': 'per_student siempre usa attendance.'})
            if self.amount < 0:
                raise ValidationError({'amount': 'El monto debe ser mayor o igual a 0.'})
        else:
            if self.calculation_base:
                raise ValidationError({'calculation_base': 'fixed_per_class no usa calculation_base.'})
            if self.amount < 0:
                raise ValidationError({'amount': 'El monto debe ser mayor o igual a 0.'})


class TeacherPaymentRecord(TimestampedModel):
    teacher = models.ForeignKey('accounts.CustomUser', on_delete=models.CASCADE, related_name='payment_records')
    class_instance = models.ForeignKey(GymClass, on_delete=models.CASCADE, related_name='teacher_payment_records', null=True, blank=True)
    rule = models.ForeignKey(TeacherPaymentRule, on_delete=models.SET_NULL, null=True, blank=True, related_name='payment_records')
    total_students = models.PositiveIntegerField(default=0)
    total_amount = models.FloatField(default=0)
    calculated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-calculated_at', '-id']
        unique_together = ('teacher', 'class_instance')

    def __str__(self):
        return f'{self.teacher} - clase #{self.class_instance_id}'


class TeacherPayout(TimestampedModel):
    """Marca de pago a NIVEL PERIODO (mes), cubre tambien a salariados sin record por clase.

    Es un snapshot: guarda el monto del periodo al momento de marcar pagado, de modo que
    cambios posteriores en clases/asistencia no alteren lo ya liquidado.
    """
    teacher = models.ForeignKey('accounts.CustomUser', on_delete=models.CASCADE, related_name='payouts')
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='teacher_payouts')
    period_year = models.PositiveIntegerField()
    period_month = models.PositiveSmallIntegerField()
    amount = models.FloatField(default=0)
    paid_at = models.DateTimeField(default=timezone.now)
    marked_by = models.ForeignKey(
        'accounts.CustomUser', on_delete=models.SET_NULL, null=True, blank=True, related_name='payouts_marked'
    )

    class Meta:
        ordering = ['-period_year', '-period_month', '-id']
        unique_together = ('teacher', 'organization', 'period_year', 'period_month')

    def __str__(self):
        return f'{self.teacher} - {self.period_year}-{self.period_month:02d} ({self.amount})'


class ManualPayment(TimestampedModel):
    """Cobro de una membresía recibido FUERA de línea (efectivo, transferencia).

    Es la contraparte de `PaymentTransaction` para el gimnasio que cobra en la recepción.
    Hasta 8.2 ese cobro no tenía dónde anotarse, así que el eje de pago de la membresía
    (`core.services.plans._payment_status`) tenía que ADIVINARLO desde el precio de venta y
    las transacciones de MercadoPago colgadas de la fila. Con este registro, `PAID` deja de
    ser una inferencia y pasa a ser un hecho declarado por alguien con nombre.

    LA EXISTENCIA DE LA FILA ES EL HECHO. No hay campo `status` ni estado parcial a
    propósito: "pagado a medias" es otra pregunta —cuánto falta— y contestarla acá obligaría
    a que el vocabulario de tres valores (`paid`/`unpaid`/`free`) creciera un cuarto. Por el
    mismo motivo `amount` NO se compara nunca contra `StudentPlan.final_price`: se guarda
    porque es el dato del cobro, no porque la derivación lo consulte.

    Puede haber VARIAS filas por membresía (dos abonos en efectivo, o el saldo pagado una
    semana después) y ninguna desplaza a las otras: no hay constraint de unicidad y no debe
    agregarse.

    `amount` es `Decimal` y no `Float` como `TeacherPayout.amount`: el resto del dinero
    COBRADO del esquema ya es decimal —`PaymentTransaction.amount`/`plan_amount`/
    `enrollment_fee_amount`, `StudentPlan.enrollment_fee`— y esto es de esa familia. Los
    montos float del esquema son valores DERIVADOS de un cálculo (el payout del profe,
    `final_price`); un cobro recibido es un dato de entrada y no puede arrastrar el error de
    representación binaria.
    """

    # La organización que COBRÓ. Se estampa desde el actor que registra: NUNCA del payload y
    # NUNCA derivada de `recorded_by.organization`. Esa FK es SET_NULL y además el usuario
    # puede cambiar de organización después, así que derivar de ahí movería el cobro de
    # tenant solo (el agujero multitenant recurrente del proyecto: seguir una FK propia sin
    # intersectar `organization_id`). Es también la ÚNICA columna que la derivación
    # intersecta para decidir si este pago le habla a esta membresía.
    #
    # PROTECT por el mismo motivo que `StudentPlan.organization` (migración 0030): borrar la
    # organización no puede llevarse en silencio la plata cobrada. No agrega una superficie
    # de 500: `OrganizationViewSet.destroy` ya cuenta membresías y devuelve 400 antes del
    # DELETE, y encima envuelve el `super().destroy()` en un `except ProtectedError`
    # pensado literalmente para "el próximo PROTECT que se agregue" (views.py:1609-1615).
    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name='manual_payments',
    )
    # CASCADE, igual que `ConsumptionLog.student_plan`: este registro es un hecho SOBRE esa
    # membresía y no significa nada sin ella —la derivación solo lo alcanza por esta FK, así
    # que huérfano sería ilegible—.
    #
    # PROTECT se descartó a propósito: convertiría en 500 dos borrados que hoy funcionan y
    # que nadie envuelve en un try —`DELETE /api/users/{id}/` (cascadea usuario →
    # membresías, `UserViewSet.perform_destroy` no captura `ProtectedError`) y
    # `DELETE /api/plans/{id}/memberships/{id}/`—. Endurecer esos dos caminos es otra tarea.
    # RIESGO RESIDUAL ASUMIDO: quitar una membresía sin consumo se lleva sus pagos
    # manuales. La guarda que ya existe en `remove_membership` (consumo o `classes_used > 0`)
    # cubre el caso común, y 8.2 no abre ninguna puerta nueva de borrado (el admin está
    # cerrado y no hay API de anulación).
    student_plan = models.ForeignKey(
        StudentPlan,
        on_delete=models.CASCADE,
        related_name='manual_payments',
    )
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
        help_text='Monto cobrado. Debe ser mayor a cero.',
    )
    # Texto libre OPCIONAL: nº de transferencia, folio de boleta, "efectivo caja 2". Se deja
    # vacío a propósito: el efectivo NO tiene comprobante, y exigir el campo obligaría al
    # administrador a inventar un valor —ensuciando justo la columna que existe para
    # auditar—. `blank=True` + `default=''` y no `null=True`: un solo valor vacío, la
    # convención del resto del esquema para texto.
    reference = models.CharField(
        max_length=120,
        blank=True,
        default='',
        help_text='Nº de transferencia, folio o nota. Vacío si fue efectivo sin comprobante.',
    )
    # Quién registró el cobro. SET_NULL —igual que `TeacherPayout.marked_by`— y no CASCADE:
    # con CASCADE, borrar al administrador que cobró BORRARÍA el cobro, y la membresía
    # volvería en silencio de `paid` a `unpaid` sin que quede rastro de que alguna vez se
    # pagó. PROTECT tampoco: `UserViewSet.perform_destroy` no captura `ProtectedError`, así
    # que borrar a ese administrador saldría 500. Perder el autor es aceptable; perder el
    # hecho no.
    #
    # OJO: esta FK NO es el ancla multitenant y no debe usarse como tal. La organización de
    # la fila es la COLUMNA `organization`, estampada al crear. Con SET_NULL este campo puede
    # quedar en NULL o apuntar a alguien que después se mudó de organización, y ninguna de
    # las dos cosas puede mover el pago de tenant.
    recorded_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='manual_payments_recorded',
    )
    # `default=timezone.now` y no `auto_now_add`, igual que `TeacherPayout.paid_at`: se llena
    # solo (el endpoint jamás lo lee del payload) pero sigue siendo escribible desde código,
    # que es exactamente lo que va a necesitar cualquier carga histórica de cobros viejos.
    # Con `auto_now_add` esa fecha solo se podría corregir con un UPDATE crudo.
    recorded_at = models.DateTimeField(default=timezone.now)

    class Meta:
        # SIN unicidad sobre (student_plan, ...) a propósito: un gimnasio puede recibir dos
        # abonos por la misma membresía y cada uno es su propia fila.
        ordering = ['-recorded_at', '-id']
        constraints = [
            # Misma regla que el validador del campo, una capa más abajo: el validador solo
            # corre en `full_clean()`, y esto también protege contra un INSERT por shell o
            # por una futura carga masiva. `check=` (no `condition=`) porque el repo está en
            # Django 5.0.6; `condition=` recién existe desde 5.1.
            models.CheckConstraint(
                check=models.Q(amount__gt=0),
                name='manual_payment_amount_positive',
            ),
        ]

    def __str__(self):
        return f'Pago manual {self.amount} - membresia {self.student_plan_id}'

    def clean(self):
        # Misma guarda que `StudentPlan.clean()` con su plan: nada en el esquema obliga a que
        # la organización de la fila sea la que vendió la membresía, y la derivación del eje
        # de pago intersecta justo esa columna. Desincronizadas, una fila de la org B le
        # declararía pagada una deuda a la org A.
        super().clean()
        if (
            self.student_plan_id
            and self.organization_id != self.student_plan.organization_id
        ):
            raise ValidationError(
                {'organization': 'La organización debe ser la misma que la de la membresía.'}
            )


class ChargeLineItem(TimestampedModel):
    """Desglose de conceptos EXTRA cobrados junto a la venta de una membresía (#12).

    Cuando el alta de una membresía (`assign`) cobra algo más allá del plan —"pesas $5000",
    "toalla $1000"—, cada concepto queda como una fila acá en vez de perderse en un campo de
    texto libre del pago. Es puramente informativo: no hay `status` ni lógica de consumo,
    igual que `ManualPayment` (LA EXISTENCIA DE LA FILA ES EL HECHO).

    La matrícula (`StudentPlan.enrollment_fee`, eje `EnrollmentFeeStatus` de 8.4) NO pasa por
    acá: tiene su propio campo y su propio ciclo de vida. Este modelo es para conceptos
    arbitrarios que un administrador tipea en el momento, no para las columnas ya modeladas
    de la venta.

    `amount` nunca se compara contra `StudentPlan.final_price` ni contra `ManualPayment.amount`:
    es el desglose informativo de EN QUÉ se cobró, no la contabilidad de CUÁNTO falta o se
    pagó (esa cuenta la sigue llevando `ManualPayment`/`PaymentTransaction`).
    """

    # Se estampa del actor que registra el alta, nunca del payload — mismo motivo que
    # `ManualPayment.organization` (ver ahí el detalle: derivar de una FK propia del usuario
    # es el agujero cross-tenant recurrente del proyecto). PROTECT por la misma razón que
    # `ManualPayment.organization`: borrar la organización no puede llevarse en silencio
    # conceptos de cobro ya registrados.
    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name='charge_line_items',
    )
    # CASCADE: mismo razonamiento que `ManualPayment.student_plan` — el concepto es un hecho
    # SOBRE esa venta y huérfano sería ilegible. PROTECT se descarta por los mismos dos
    # caminos de borrado documentados junto a `ManualPayment.student_plan`.
    student_plan = models.ForeignKey(
        StudentPlan,
        on_delete=models.CASCADE,
        related_name='charge_line_items',
    )
    # Texto libre pero OBLIGATORIO (sin `blank=True`): a diferencia de `ManualPayment.reference`
    # acá no hay equivalente "efectivo sin comprobante" — el concepto es el dato mismo de la
    # fila, no una nota opcional sobre otro dato.
    concept = models.CharField(
        max_length=120,
        help_text='Concepto cobrado (ej. "pesas", "toalla").',
    )
    # Decimal y no Float: mismo argumento que `ManualPayment.amount` — dato de entrada
    # cobrado, no un valor derivado de un cálculo.
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
        help_text='Monto del concepto. Debe ser mayor a cero.',
    )
    # SET_NULL: mismo motivo que `ManualPayment.recorded_by` — perder el autor es aceptable,
    # perder el hecho no. Tampoco es ancla multitenant (esa es la columna `organization`).
    created_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='charge_line_items_created',
    )

    class Meta:
        # Los conceptos de una venta se leen en el orden en que se cargaron.
        ordering = ['id']
        constraints = [
            # Misma defensa en profundidad que `manual_payment_amount_positive`: el
            # validador del campo solo corre en `full_clean()`. `check=` y no `condition=`
            # porque el repo está en Django 5.0.6 (`condition=` es de 5.1).
            models.CheckConstraint(
                check=models.Q(amount__gt=0),
                name='charge_line_item_amount_positive',
            ),
        ]
        # SIN unicidad sobre (student_plan, concept) a propósito: dos conceptos iguales en
        # la misma venta ("pesas" dos veces) son dos filas legítimas, no un duplicado.

    def __str__(self):
        return f'{self.concept} {self.amount} - membresia {self.student_plan_id}'


class ClassTemplate(TimestampedModel):
    class Weekday(models.IntegerChoices):
        MONDAY = 0, 'Lunes'
        TUESDAY = 1, 'Martes'
        WEDNESDAY = 2, 'Miercoles'
        THURSDAY = 3, 'Jueves'
        FRIDAY = 4, 'Viernes'
        SATURDAY = 5, 'Sabado'
        SUNDAY = 6, 'Domingo'

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='class_templates')
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='class_templates')
    teacher = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='class_templates',
    )
    class_type = models.ForeignKey(ClassType, on_delete=models.SET_NULL, null=True, blank=True, related_name='class_templates')
    discipline = models.ForeignKey(Discipline, on_delete=models.SET_NULL, null=True, blank=True, related_name='class_templates')
    name = models.CharField(max_length=150, blank=True)
    description = models.TextField(blank=True)
    weekday = models.PositiveSmallIntegerField(choices=Weekday.choices)
    start_time = models.TimeField()
    end_time = models.TimeField()
    capacity = models.PositiveIntegerField(default=20)
    is_trial_eligible = models.BooleanField(default=False)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_class_templates',
    )

    class Meta:
        ordering = ['weekday', 'start_time', 'id']

    def __str__(self):
        return self.name or f'Plantilla {self.get_weekday_display()} {self.start_time}'

    def clean(self):
        if self.end_time <= self.start_time:
            raise ValidationError({'end_time': 'La hora de termino debe ser posterior a la hora de inicio.'})
        if self.end_date and self.end_date < self.start_date:
            raise ValidationError({'end_date': 'La fecha de termino no puede ser menor a la fecha de inicio.'})
        if self.capacity <= 0:
            raise ValidationError({'capacity': 'La capacidad debe ser mayor a cero.'})
        if self.teacher and self.teacher.role != 'teacher':
            raise ValidationError({'teacher': 'El usuario seleccionado no es profesor.'})
        # Del profesor se validaba solo el ROL, no la organización. Las instancias que la
        # serie genera NO vuelven a pasar por `GymClassSerializer` (que sí lo valida), así
        # que un profe ajeno acá terminaba dictando clases de esta organización y
        # arrastraba su `TeacherPaymentRecord` cruzando el borde.
        if self.teacher and self.organization_id and self.teacher.organization_id != self.organization_id:
            raise ValidationError({'teacher': 'El profesor no pertenece a la organizacion indicada.'})
        if self.branch and self.organization_id and self.branch.organization_id != self.organization_id:
            raise ValidationError({'branch': 'La sucursal no pertenece a la organizacion indicada.'})
        if self.class_type and self.organization_id and self.class_type.organization_id != self.organization_id:
            raise ValidationError({'class_type': 'El tipo de clase no pertenece a la organizacion indicada.'})
        if self.discipline and self.organization_id and self.discipline.organization_id != self.organization_id:
            raise ValidationError({'discipline': 'La disciplina no pertenece a la organizacion indicada.'})

        # Tarea 11.A: el producto decidió PERMITIR que un mismo profesor tenga
        # plantillas/clases solapadas (ej.: dicta dos disciplinas en paralelo y el
        # alumno elige a cuál ir). Acá vivían los dos chequeos de solape de profesor
        # (plantilla-vs-plantilla y plantilla-vs-clases existentes); se eliminaron a
        # propósito.


class Holiday(TimestampedModel):
    class Scope(models.TextChoices):
        GLOBAL = 'global', 'Global'
        ORGANIZATION = 'organization', 'Organizacion'
        BRANCH = 'branch', 'Sucursal'
    class SourceType(models.TextChoices):
        SYSTEM = 'system', 'Sistema'
        MANUAL = 'manual', 'Manual'

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='holidays', null=True, blank=True)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='holidays', null=True, blank=True)
    date = models.DateField()
    name = models.CharField(max_length=150)
    scope = models.CharField(max_length=20, choices=Scope.choices, default=Scope.ORGANIZATION)
    source_type = models.CharField(max_length=20, choices=SourceType.choices, default=SourceType.MANUAL)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['date', 'name']
        constraints = [
            models.UniqueConstraint(
                fields=['scope', 'date', 'organization', 'branch'],
                name='unique_holiday_scope_date',
            )
        ]

    def __str__(self):
        return f'{self.date} - {self.name}'

    @staticmethod
    def scope_q_global():
        return models.Q(scope=Holiday.Scope.GLOBAL)

    @staticmethod
    def scope_q_organization(organization_id=None):
        if not organization_id:
            return models.Q(pk__isnull=True)
        return models.Q(scope=Holiday.Scope.ORGANIZATION, organization_id=organization_id)

    @staticmethod
    def scope_q_branch(branch_id=None):
        if not branch_id:
            return models.Q(pk__isnull=True)
        return models.Q(scope=Holiday.Scope.BRANCH, branch_id=branch_id)

    def clean(self):
        if self.scope == self.Scope.GLOBAL:
            self.organization = None
            self.branch = None
            return
        if self.scope == self.Scope.ORGANIZATION:
            if not self.organization:
                raise ValidationError({'organization': 'Debes indicar organizacion para festivo por organizacion.'})
            self.branch = None
            return
        if self.scope == self.Scope.BRANCH:
            if not self.organization:
                raise ValidationError({'organization': 'Debes indicar organizacion para festivo por sucursal.'})
            if not self.branch:
                raise ValidationError({'branch': 'Debes indicar sucursal para festivo por sucursal.'})
            if self.branch.organization_id != self.organization_id:
                raise ValidationError({'branch': 'La sucursal no pertenece a la organizacion indicada.'})
class RecurringEnrollment(TimestampedModel):
    class RecurrenceType(models.TextChoices):
        WEEKLY = 'weekly', 'Semanal'

    student = models.ForeignKey('accounts.CustomUser', on_delete=models.CASCADE, related_name='recurring_enrollments')
    class_template = models.ForeignKey(ClassTemplate, on_delete=models.CASCADE, related_name='recurring_enrollments')
    recurrence_type = models.CharField(max_length=20, choices=RecurrenceType.choices, default=RecurrenceType.WEEKLY)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_recurring_enrollments',
    )
    # Con qué membresía se re-imputan las instancias futuras de esta recurrencia. Espejo
    # de `Enrollment.student_plan` (#9, models.py:395-401) pero RESTRICT y no SET_NULL: ahí
    # el campo es un registro HISTÓRICO de una reserva ya hecha (perder la membresía no
    # puede llevarse la reserva); acá es la elección VIGENTE que gobierna reservas
    # FUTURAS todavía no generadas —si el plan elegido se borra, la recurrencia tiene que
    # bloquear ese borrado, no caer en silencio de vuelta a la resolución arbitraria por
    # instancia—. NULL es el comportamiento actual: el loop de recurrencia sigue
    # resolviendo el plan por instancia vía `resolve_student_plan_for_reservation`, sin
    # imputación fija. Sin constraint de unicidad, igual que `StudentPlan` no la tiene
    # sobre (user, organization): varias recurrencias pueden apuntar a la misma membresía.
    #
    # RESTRICT y NO PROTECT (misma elección que `Plan.branch`), por la diferencia que solo
    # aparece en las CASCADAS: los dos bloquean el borrado directo de la membresía, pero
    # PROTECT también revienta cuando la fila que protege se borra en la MISMA operación.
    # `RecurringEnrollment.student` y `StudentPlan.user` son ambos CASCADE sobre el alumno,
    # así que borrar un alumno se lleva la recurrencia Y la membresía juntas: ahí no hay
    # nada que proteger, y con PROTECT `DELETE /api/users/{id}/` respondía 500
    # (`ProtectedError` sin capturar en `UserViewSet.perform_destroy`) para cualquier alumno
    # con recurrencia y plan. RESTRICT permite exactamente ese caso —la referencia muere en
    # el mismo `delete()`— y sigue levantando `RestrictedError` cuando alguien intenta
    # quitarle al alumno la membresía que su serie tiene fijada (`remove_membership`, que la
    # atrapa y devuelve un 400 accionable).
    student_plan = models.ForeignKey(
        'StudentPlan',
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name='recurring_enrollments',
    )

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['student', 'class_template'],
                condition=models.Q(is_active=True),
                name='unique_active_recurring_enrollment',
            )
        ]

    def __str__(self):
        return f'{self.student} -> {self.class_template}'

    def clean(self):
        if self.student and self.student.role != 'student':
            raise ValidationError({'student': 'Solo se pueden crear recurrencias para usuarios student.'})
        if self.end_date and self.end_date < self.start_date:
            raise ValidationError({'end_date': 'La fecha de termino no puede ser menor a la fecha de inicio.'})
        if self.class_template and self.student and self.class_template.organization_id != self.student.organization_id:
            raise ValidationError({'class_template': 'La plantilla no pertenece a la organizacion del alumno.'})
        if not self.class_template:
            return
        if self.start_date < self.class_template.start_date:
            raise ValidationError({'start_date': 'No puedes iniciar la recurrencia antes del inicio de la plantilla.'})
        if self.class_template.end_date and self.start_date > self.class_template.end_date:
            raise ValidationError({'start_date': 'La fecha de inicio supera el termino de la plantilla.'})
        if self.end_date and self.class_template.end_date and self.end_date > self.class_template.end_date:
            raise ValidationError({'end_date': 'La recurrencia no puede terminar despues de la plantilla.'})


class PaymentAccount(TimestampedModel):
    STATUS_CONNECTED = 'connected'
    STATUS_DISCONNECTED = 'disconnected'
    STATUS_CHOICES = [(STATUS_CONNECTED, 'Conectada'), (STATUS_DISCONNECTED, 'Desconectada')]

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='payment_accounts')
    provider = models.CharField(max_length=30, default='mercadopago')
    provider_user_id = models.CharField(max_length=64)
    # null tras desconectar: la fila se conserva (histórico + reconexión) pero sin tokens.
    access_token = EncryptedTextField(null=True, blank=True)
    refresh_token = EncryptedTextField(null=True, blank=True)
    # Strings opacos que devuelve el proveedor OAuth (MP): el scope es una lista
    # larga separada por espacios que supera varchar(255). Sin límite de longitud.
    public_key = models.TextField(null=True, blank=True)
    scope = models.TextField(null=True, blank=True)
    token_expires_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_CONNECTED)
    is_sandbox = models.BooleanField(default=False)
    connected_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [('organization', 'provider')]

    def __str__(self):
        return f'{self.organization} · {self.provider} ({self.status})'


class PaymentTransaction(TimestampedModel):
    # Lista literal (evita import circular models -> core.services.providers.base).
    # Debe mantenerse en sync con core.services.providers.base.PaymentStatus.
    #
    # `STATUS_APPROVED` sale de la lista como constante porque es el ÚNICO estado que
    # significa "esto se cobró": lo consulta el eje de pago de la membresía
    # (`core.services.plans._payment_status`). Sin la constante, ese predicado repetiría el
    # literal 'approved' en un cuarto lugar y podría divergir de lo que el webhook escribe.
    STATUS_APPROVED = 'approved'
    STATUS_CHOICES = [
        ('pending', 'pending'),
        ('in_process', 'in_process'),
        (STATUS_APPROVED, 'approved'),
        ('rejected', 'rejected'),
        ('cancelled', 'cancelled'),
        ('refunded', 'refunded'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='payment_transactions')
    user = models.ForeignKey('accounts.CustomUser', on_delete=models.CASCADE, related_name='payment_transactions')
    provider = models.CharField(max_length=30, default='mercadopago')
    provider_preference_id = models.CharField(max_length=64, null=True, blank=True)
    provider_payment_id = models.CharField(max_length=64, null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    status_detail = models.CharField(max_length=120, null=True, blank=True)
    currency = models.CharField(max_length=3, default='CLP')
    plan = models.ForeignKey(Plan, on_delete=models.SET_NULL, null=True, blank=True,
                             related_name='payment_transactions')
    plan_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    enrollment_fee_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    target_student_plan = models.ForeignKey(StudentPlan, on_delete=models.SET_NULL, null=True, blank=True,
                                            related_name='enrollment_fee_transactions')
    student_plan = models.ForeignKey(StudentPlan, on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name='origin_transactions')
    processed_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    raw_provider_payload = models.JSONField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['provider', 'provider_payment_id'],
                condition=models.Q(provider_payment_id__isnull=False),
                name='uniq_provider_payment',
            ),
        ]
        indexes = [
            models.Index(fields=['organization', 'status']),
            models.Index(fields=['user', 'status']),
        ]

    def __str__(self):
        return f'{self.id} · {self.status} · {self.amount} {self.currency}'


class WebhookEvent(TimestampedModel):
    provider = models.CharField(max_length=30, default='mercadopago')
    provider_payment_id = models.CharField(max_length=64, null=True, blank=True)
    transaction = models.ForeignKey(PaymentTransaction, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='webhook_events')
    raw_body = models.TextField()
    headers = models.JSONField(default=dict, blank=True)
    processed_ok = models.BooleanField(default=False)
    note = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        ordering = ['-created_at']


