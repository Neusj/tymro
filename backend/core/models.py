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


# P4 — doble identidad del administrador.
#
# `CustomUser.role` es una opción ÚNICA y el par (email, RUT) es único por organización:
# no hay forma de tener dos roles ni de duplicar el usuario. En vez de inventar un rol
# compuesto —que encendería el riesgo de autopago y autoasignación en TODOS los endpoints
# a la vez, sin punto de corte—, se amplía la ELEGIBILIDAD: un `gym_admin` puede además
# ser sujeto de las dos identidades operativas de su propio gimnasio.
#
# Estas constantes responden "¿QUÉ ROL PUEDE SER esto?" (validación de integridad), nunca
# "¿quién puede HACER esto?" (autorización): eso sigue viviendo en `accounts.roles` y en
# las guardas de las views, que no se tocan. Y NINGUNA de las dos dice nada de
# `organization_id`: la pertenencia se valida SIEMPRE aparte y DESPUÉS (lección 8.3), así
# que un admin de otra organización jamás resulta elegible por esta vía.
#
# Literales y no `CustomUser.Role.*` porque este módulo no importa `accounts.models`
# (las FKs usan referencias lazy); es el mismo criterio que ya usaban los `clean()`.
TEACHER_ELIGIBLE_ROLES = frozenset({'teacher', 'gym_admin'})
STUDENT_SUBJECT_ROLES = frozenset({'student', 'gym_admin'})


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
    max_reservation_window_days = models.IntegerField(
        default=21,
        validators=[MinValueValidator(1), MaxValueValidator(366)],
        help_text='Días hacia adelante en que se puede reservar una clase.',
    )
    # Colchón de poda: cuántos días tiene que llevar TERMINADA una clase vacía para que el
    # job advance_class_windows la borre. Margen para backfill tardío (pasar lista el lunes
    # por la clase del viernes). 0 = sin colchón (podar apenas termina).
    class_pruning_grace_days = models.PositiveIntegerField(
        default=7,
        validators=[MaxValueValidator(90)],
        help_text='Días de gracia antes de podar una clase terminada sin inscripciones ni historia.',
    )
    free_class_teacher_payment_value = models.FloatField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text=(
            'Valor de UNA clase de un plan gratuito, para el pago al profesor. '
            '0 = sin configurar (bloquea la creación de planes gratuitos).'
        ),
    )
    annual_enrollment_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(Decimal('0'))],
        help_text='Matrícula anual del gimnasio. 0 = sin matrícula.',
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

    class SubstitutionSource(models.TextChoices):
        EXTERNAL_ADMIN = 'external_admin', 'Externo asignado por admin'
        ADMIN_ASSIGNED = 'admin_assigned', 'Profesor asignado por admin'
        TEACHER_CLAIMED = 'teacher_claimed', 'Tomada por profesor'

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
    # Clase con suplente (P4 #A): registro/visualización PURO, no toca a quién se le paga.
    # `teacher` sigue siendo el titular asignado y sigue siendo el ÚNICO que
    # `calculate_teacher_payment` (services/teacher_payments.py) considera — estos dos campos
    # no se leen en ningún camino de pago, adrede. El arreglo económico con el suplente ocurre
    # FUERA de la plataforma (decisión de producto #11).
    # `substitute_name` es texto libre, NO una FK a `CustomUser`: el suplente puede no existir
    # en el sistema (un profe externo, alguien que cubre por única vez). Normalización en
    # `GymClassSerializer.validate`: `has_substitute=False` fuerza el nombre a `''` (sin
    # huérfanos de un check apagado) y `has_substitute=True` exige nombre no vacío.
    has_substitute = models.BooleanField(default=False)
    substitute_name = models.CharField(max_length=150, blank=True, default='')
    substitute_teacher = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='substituted_classes',
    )
    substitution_source = models.CharField(
        max_length=30,
        choices=SubstitutionSource.choices,
        blank=True,
        default='',
    )
    substitution_assigned_at = models.DateTimeField(null=True, blank=True)
    substitution_assigned_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_class_substitutions',
    )

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
    recurring_resync_blocked = models.BooleanField(
        default=False,
        help_text=(
            'Bloquea que una recurrencia reactive esta instancia concreta tras una '
            'cancelación individual.'
        ),
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
            and self.enrollment_fee_paid_at is not None
            and self.enrollment_fee_due_at is None
        ):
            self.enrollment_fee_due_at = (
                timezone.localtime(self.enrollment_fee_paid_at).date() + timedelta(days=365)
            )
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
    # Sucursal de la membresía cobrada. Se deriva de `student_plan.branch` en el servicio de
    # escritura y NUNCA del payload, por el mismo motivo que `organization` (ver arriba): es
    # el registro histórico de dónde se cobró, no un dato que el cliente pueda elegir.
    #
    # `SET_NULL` y no `PROTECT` como `organization`: acá NULL significa "sin sede registrada"
    # —membresía global, o fila anterior a esta columna—, una pérdida de dato menor. No
    # invierte ningún alcance, así que borrar la sucursal no puede corromper nada (a
    # diferencia de `PaymentAccount.branch`, donde NULL significa "es LA cuenta principal" y
    # por eso ahí es PROTECT). Mismo criterio que `StudentPlan.branch` y
    # `PaymentTransaction.branch`, las dos columnas hermanas de esta.
    branch = models.ForeignKey(
        Branch,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='manual_payments',
    )
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
        help_text='Monto cobrado. Debe ser mayor a cero.',
    )
    # Instrumento del cobro (P3.2): efectivo o transferencia. Hasta acá "transferencia"
    # solo existía como texto libre dentro de `reference` -un gimnasio podía escribir
    # "transf", "Transferencia", "TRANSF." o nada- y un reporte no puede filtrar ni sumar
    # sobre texto que cada quien redacta distinto. Esta columna estructura ESA pregunta
    # para que P3.4 (reporte por medio de pago) tenga una columna que agrupar, y deja
    # `reference` para lo que sigue siendo texto libre de verdad: el folio, el nº de
    # operación, la nota.
    #
    # `blank=True, default=''` es DELIBERADO. `''` significa "método no registrado" y NO es
    # una opción que el API ofrezca: `ManualPaymentCreateSerializer.method` es un
    # `ChoiceField` sin `allow_blank` ni default, así que todo cobro nuevo declara
    # `cash` o `transfer` sí o sí. El vacío existe SOLO para las filas que ya viven en
    # producción desde 8.2/8.3, de antes de que esta columna existiera.
    # Mismo criterio que `reference` un poco más abajo (`blank=True, default=''`, no
    # `null=True`): un solo valor vacío para "no hay dato", la convención del resto del
    # esquema para texto ausente.
    #
    # Por eso la migración que agrega esta columna NO hace backfill a `cash`: las filas
    # viejas pudieron ser efectivo O transferencia y no hay forma de saberlo desde acá.
    # Adivinar `cash` por ser el caso más común fabricaría historia -exactamente el dato
    # que esta columna existe para dejar de inferir- y ensuciaría desde el día uno el
    # reporte que la motiva.
    #
    # SIN `CheckConstraint` que exija no vacío, a diferencia de `amount__gt=0` en `Meta` más
    # abajo: esa constraint reventaría contra las filas legacy en `''` en cualquier `save()`
    # futuro sobre ellas (una corrección de `reference`, por ejemplo), y esas filas no van
    # a dejar de existir.
    #
    # `blank=True` también significa que `clean_fields()` SALTEA la validación de choices
    # para valores vacíos ("Skip validation for empty fields with blank=True",
    # django/db/models/base.py): un `full_clean()` sobre una fila NUEVA con `method=''` (o
    # `None`, que ni siquiera dispara el choice-check y muere como `IntegrityError` en el
    # INSERT si se salta `full_clean()`) pasaría sin queja si dependiéramos solo de eso. Por
    # eso la fila-nueva-vacía se corta aparte, a mano, en `clean()` más abajo -ver ese método
    # para el motivo de por qué esa validación NO puede vivir en una `CheckConstraint` ni en
    # `blank=False` (ambas reventarían las filas legacy) y sí puede vivir ahí sin duplicar la
    # validación de choices que este campo ya trae.
    METHOD_CASH = 'cash'
    METHOD_TRANSFER = 'transfer'
    METHOD_CARD = 'card'
    METHOD_CHECK = 'check'
    METHOD_CHOICES = (
        (METHOD_CASH, 'Efectivo'),
        (METHOD_TRANSFER, 'Transferencia'),
        (METHOD_CARD, 'Tarjeta'),
        (METHOD_CHECK, 'Cheque'),
    )
    method = models.CharField(
        max_length=16,
        choices=METHOD_CHOICES,
        blank=True,
        default='',
        help_text='Efectivo, transferencia, tarjeta o cheque. Vacio solo en filas historicas anteriores a P3.2.',
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
    plan_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(Decimal('0'))],
        help_text='Parte del cobro manual imputada al plan.',
    )
    enrollment_fee_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(Decimal('0'))],
        help_text='Parte del cobro manual imputada a la matrícula anual.',
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
        # `method` vacío ('' o None) es el estado LEGÍTIMO de las filas de 8.2/8.3, de antes
        # de que P3.2 agregara esta columna, y esas filas tienen que poder seguir pasando por
        # `full_clean()` sin reventar (una corrección de `reference`, por ejemplo). Pero una
        # fila NUEVA con `method` vacío es otra cosa: es el kwarg obligatorio de
        # `record_manual_payment` cumplido a medias -pasa algo, no pasa algo VÁLIDO- y
        # `clean_fields()` no lo frena porque el campo es `blank=True` (ver el comentario del
        # campo más arriba). Sin este corte, ese caller crearía en silencio una fila nueva
        # indistinguible de las legacy, y es exactamente el caller que este archivo anticipa:
        # una carga histórica de cobros viejos desde CSV, donde una columna vacía llega justo
        # como ''.
        #
        # `self._state.adding` y no `self.pk is None`: es la señal explícita que el propio
        # Django usa para decidir INSERT vs UPDATE en `save()`, así que sigue siendo correcta
        # incluso si algún caller construye la instancia con un `pk` ya asignado a mano antes
        # del primer guardado (`self.pk is None` daría falso negativo justo ahí).
        #
        # NO se resuelve con `CheckConstraint` (reventaría las filas legacy en la base) ni
        # con `blank=False` (rompe el admin y esas mismas filas legacy en cualquier
        # `full_clean()`): tiene que ser una regla que sepa distinguir alta de edición, y ese
        # conocimiento vive acá, no en el esquema.
        if self._state.adding and not self.method:
            raise ValidationError({
                'method': (
                    'Debe declararse el método de pago (efectivo o transferencia) al '
                    'registrar un cobro nuevo. El valor vacío es válido solo en las filas '
                    'registradas antes de P3.2 y no puede usarse para una fila nueva.'
                ),
            })
        plan_amount = self.plan_amount or Decimal('0')
        enrollment_fee_amount = self.enrollment_fee_amount or Decimal('0')
        if plan_amount + enrollment_fee_amount > self.amount:
            raise ValidationError({
                'amount': 'El desglose de plan y matrícula no puede superar el monto cobrado.',
            })


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
    # Clase con suplente (P4 #A): MISMOS dos campos que `GymClass.has_substitute` /
    # `substitute_name`, con el mismo significado (registro puro, el pago sigue yendo al
    # `teacher` titular). Acá son el DEFAULT de la serie, y siguen exactamente el mismo
    # contrato de propagación que `is_trial_eligible`/`capacity`/`teacher` hoy (no se inventa
    # uno nuevo): `generate_instances_for_template_range` (services/recurrence.py) los copia a
    # cada instancia NUEVA al materializar, y `apply_template_updates_to_future_instances` los
    # reescribe también en las instancias futuras YA materializadas que no tengan inscritos
    # activos (esas quedan protegidas). Una instancia ya cerrada o con inscritos no se toca.
    has_substitute = models.BooleanField(default=False)
    substitute_name = models.CharField(max_length=150, blank=True, default='')
    substitute_teacher = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='substitute_class_templates',
    )
    substitution_source = models.CharField(
        max_length=30,
        choices=GymClass.SubstitutionSource.choices,
        blank=True,
        default='',
    )
    substitution_assigned_at = models.DateTimeField(null=True, blank=True)
    substitution_assigned_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_template_substitutions',
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
        # Del profesor se validaba solo el ROL, no la organización. Las instancias que la
        # serie genera NO vuelven a pasar por `GymClassSerializer` (que sí lo valida), así
        # que un profe ajeno acá terminaba dictando clases de esta organización y
        # arrastraba su `TeacherPaymentRecord` cruzando el borde.
        #
        # Va PRIMERO, antes del check de rol (lección 8.3 / P4): con el rol adelante, los dos
        # mensajes distinguían el rol de una cuenta de otro tenant.
        if self.teacher and self.organization_id and self.teacher.organization_id != self.organization_id:
            raise ValidationError({'teacher': 'El profesor no pertenece a la organizacion indicada.'})
        # P4: `gym_admin` también es elegible como profesor de SU organización.
        if self.teacher and self.teacher.role not in TEACHER_ELIGIBLE_ROLES:
            raise ValidationError({'teacher': 'El usuario seleccionado no es profesor.'})
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
        # ORGANIZACIÓN PRIMERO, ROL DESPUÉS (lección 8.3 / P4): con el rol adelante, el par
        # de mensajes distinguía el rol de una cuenta de otro tenant.
        #
        # Se testean los `_id` y no los descriptores: `student` y `class_template` son FKs NO
        # anulables, así que `self.class_template` sobre una instancia a la que todavía no se
        # le asignó la FK levanta `RelatedObjectDoesNotExist` —subclase de `AttributeError`,
        # NO de `ValidationError`—, y `full_clean()` llama a `clean()` aunque `clean_fields()`
        # ya haya fallado. Con los descriptores, este check adelantado convertía en 500 lo que
        # antes salía como 400 por el check de rol.
        if (
            self.class_template_id
            and self.student_id
            and self.class_template.organization_id != self.student.organization_id
        ):
            raise ValidationError({'class_template': 'La plantilla no pertenece a la organizacion del alumno.'})
        # P4: `gym_admin` también puede ser sujeto de una recurrencia (identidad de alumno).
        if self.student and self.student.role not in STUDENT_SUBJECT_ROLES:
            raise ValidationError({'student': 'Solo se pueden crear recurrencias para usuarios student.'})
        if self.end_date and self.end_date < self.start_date:
            raise ValidationError({'end_date': 'La fecha de termino no puede ser menor a la fecha de inicio.'})
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
    # Sucursal dueña de la cuenta. NULL = cuenta PRINCIPAL de la organización: la que cobra
    # por todas las sedes que no tengan cuenta propia (y el estado de siempre, antes de que
    # existieran cuentas por sede).
    #
    # `PROTECT` y no `SET_NULL`: acá NULL no significa "sin sede registrada" sino "es LA
    # principal", así que un SET_NULL al borrar la sucursal ascendería su cuenta a principal
    # de la organización —desviando en silencio el dinero de todas las demás sedes a otro
    # MercadoPago— o chocaría con la principal ya existente. Mismo criterio que el resto de
    # los modelos de dinero (`ManualPayment.organization`, `StudentPlan.organization`):
    # perder la sede tiene que ser una decisión explícita. `BranchViewSet.destroy` lo
    # traduce a un 400 en vez de dejar salir un 500.
    branch = models.ForeignKey(
        Branch,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='payment_accounts',
    )
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
        constraints = [
            # UNA sola cuenta principal por organización y proveedor. La condición
            # `branch__isnull=True` no es cosmética: en SQL dos NULL nunca son iguales, así
            # que un unique plano sobre (organización, sucursal, proveedor) dejaría crear
            # dos principales y el cobro elegiría una al azar.
            models.UniqueConstraint(
                fields=['organization', 'provider'],
                condition=models.Q(branch__isnull=True),
                name='uniq_main_payment_account_per_org',
            ),
            # Y una sola cuenta propia por sucursal y proveedor.
            models.UniqueConstraint(
                fields=['organization', 'branch', 'provider'],
                condition=models.Q(branch__isnull=False),
                name='uniq_branch_payment_account',
            ),
        ]

    def __str__(self):
        scope = self.branch or 'principal'
        return f'{self.organization} · {scope} · {self.provider} ({self.status})'


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
    # Sucursal de la membresía que se está pagando: se deriva de `plan.branch` en la compra
    # de plan y de `student_plan.branch` en la matrícula. Es un registro histórico y se
    # estampa aunque el cobro caiga a la cuenta principal (la sede puede no tener cuenta
    # propia). `SET_NULL` alcanza porque aquí NULL significa "sin sede registrada" —plan
    # global o fila anterior a las cuentas por sede—, no "todas las sedes"; mismo criterio
    # que `StudentPlan.branch`.
    branch = models.ForeignKey(
        Branch,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payment_transactions',
    )
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
    # Cuenta EXACTA que emitió la preference de este cobro. Con varias cuentas por
    # organización (principal + sedes), el webhook tiene que validar el `collector_id` y
    # consultar el pago con el token de ESTA cuenta: re-resolver por (organización, sede) en
    # el webhook puede devolver otra si la topología cambió entre el checkout y la
    # notificación —una sede conectó o desconectó su cuenta—, y eso da o un
    # `PaymentIntegrityError` falso o un fetch con el token de un tercero.
    # NULL = fila anterior a las cuentas por sede; ahí el webhook cae a la principal, que es
    # la única que pudo haber cobrado entonces.
    payment_account = models.ForeignKey(PaymentAccount, on_delete=models.SET_NULL, null=True,
                                        blank=True, related_name='transactions')
    processed_at = models.DateTimeField(null=True, blank=True)
    # --- Plata COBRADA y plata DEVUELTA (P3.4) ---------------------------------------
    # Estos tres campos existen para que la reportería de ingresos no tenga que deducir
    # dinero desde `status`, que es un valor PISABLE: cuando MercadoPago avisa de un
    # reembolso o un contracargo, `status` pasa a `refunded` y el hecho de que ese cobro
    # ENTRÓ desaparece de la fila. Un reporte que sumara `status='approved'` empezaría a
    # mentir HACIA ATRÁS con cada devolución (el ingreso de julio cambiaría en agosto).
    #
    # `collected_at` = instante en que el proveedor confirmó el COBRO. Se estampa UNA sola
    # vez y NUNCA se limpia, tampoco al devolver: es un hecho histórico, no un estado.
    # NO es `processed_at` y la diferencia importa: `processed_at` significa "además se
    # activó la membresía", y hay un camino real donde el cobro entra y la activación no
    # ocurre (el `plan_org_mismatch` de `apply_provider_payment`, que deja la fila COBRADA y
    # sin `processed_at` a propósito). La plata igual entró a la cuenta del gimnasio, así que
    # el ingreso bruto se cuenta por `collected_at`: un reporte no puede depender de que la
    # activación del plan haya salido bien.
    collected_at = models.DateTimeField(null=True, blank=True)
    # Instante en que se REGISTRÓ la devolución (reembolso o contracargo). Hasta P3.4 esa
    # notificación del proveedor era un no-op absoluto —la guarda de idempotencia por
    # `processed_at` cortaba antes de mirar el estado— y la devolución no quedaba en ninguna
    # parte: el plan seguía activo y el ingreso seguía contando entero.
    refunded_at = models.DateTimeField(null=True, blank=True)
    # Monto devuelto. Hoy solo puede haber devoluciones TOTALES y vale `amount`: la
    # abstracción de proveedor colapsa `refunded` y `charged_back` en un único
    # `PaymentStatus.REFUNDED` y `ProviderPayment.amount` trae el monto ORIGINAL del pago,
    # no lo reembolsado. Es un campo propio y no una property justamente para que el día que
    # el proveedor exponga el parcial se guarde acá sin migrar nada más.
    refunded_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
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
            # Reportería de ingresos (P3.4). Los dos ejes del reporte son distintos y no se
            # pueden servir con un índice: el bruto se saca por (organización, fecha de
            # COBRO) y las devoluciones por (organización, fecha de DEVOLUCIÓN). Sin estos
            # índices cada reporte recorre la tabla de pagos de TODOS los tenants.
            models.Index(fields=['organization', 'collected_at']),
            models.Index(fields=['organization', 'refunded_at']),
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


class ClassOccupancySnapshot(TimestampedModel):
    """Rastro de una clase VACÍA que la poda de la ventana rodante borró (P3.4).

    POR QUÉ EXISTE: `rolling_window._prune_past_empty_classes` borra las clases pasadas que
    nadie usó —sin inscripciones, sin asistencias, sin consumos, sin pago a profesor—. Ese
    borrado es correcto para el calendario y DESTRUYE justo el dato más valioso del reporte
    de ocupación: qué horarios/disciplinas el gimnasio ofreció y nadie tomó. Sin este rastro
    el reporte de ocupación mide sobre las clases sobrevivientes y da un porcentaje
    OPTIMISTA: cuanto más tiempo pasa, más clases vacías desaparecen y mejor se ve la
    ocupación histórica. Con el rastro, una clase podada sigue contando como oferta con 0
    inscritos.

    ES UN SNAPSHOT, NO UNA VISTA. Los nombres de sede/disciplina/profesor se copian como
    texto además de la FK: la fila tiene que sobrevivir al borrado de la clase (que ya
    ocurrió cuando esto se lee) y también al de la sede o la disciplina. Las FK quedan
    `SET_NULL` para poder agrupar por id mientras el objeto exista, y el texto es el que se
    muestra cuando ya no existe. NO se agrega FK a `GymClass`: la clase se borra en la misma
    transacción, una FK sería NULL siempre.

    `enrolled_count` se guarda explícitamente aunque hoy sea SIEMPRE 0 (la poda exige
    `enrollments__isnull=True`, es el único caso que llega acá). Guardarlo evita que el
    reporte tenga que asumir el 0 desde el nombre de la tabla: si mañana entra otra fuente
    de rastro —una clase cancelada, un archivado manual—, el reporte suma este campo y no
    hay que revisar quién lo escribió.
    """
    SOURCE_PRUNE = 'prune'
    SOURCE_CHOICES = ((SOURCE_PRUNE, 'Poda de ventana rodante'),)

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE,
                                     related_name='class_occupancy_snapshots')
    # El id de la `GymClass` que se borró. Entero pelado y no FK (la fila ya no existe), y
    # con unicidad por organización para que la poda pueda re-intentar sin duplicar oferta:
    # `_prune_past_empty_classes` atrapa la excepción por clase y el job vuelve a correr
    # todos los días, así que un rastro escrito dos veces inflaría el denominador.
    source_class_id = models.BigIntegerField()
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default=SOURCE_PRUNE)

    branch = models.ForeignKey(Branch, on_delete=models.SET_NULL, null=True, blank=True,
                               related_name='class_occupancy_snapshots')
    branch_name = models.CharField(max_length=150, blank=True, default='')
    discipline = models.ForeignKey(Discipline, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='class_occupancy_snapshots')
    discipline_name = models.CharField(max_length=150, blank=True, default='')
    teacher = models.ForeignKey('accounts.CustomUser', on_delete=models.SET_NULL, null=True,
                                blank=True, related_name='class_occupancy_snapshots')
    teacher_name = models.CharField(max_length=200, blank=True, default='')
    class_name = models.CharField(max_length=150, blank=True, default='')

    start_datetime = models.DateTimeField()
    end_datetime = models.DateTimeField()
    capacity = models.PositiveIntegerField(default=0)
    enrolled_count = models.PositiveIntegerField(default=0)
    pruned_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-start_datetime', '-id']
        constraints = [
            # `fields=[...]` y no `F(...)`: la trampa de DRF documentada en
            # `GymClass.Meta.constraints` solo muerde a los modelos expuestos por un
            # `ModelSerializer`, y este no lo está ni debe estarlo (el reporte arma dicts).
            models.UniqueConstraint(fields=['organization', 'source_class_id'],
                                    name='uniq_occupancy_snapshot_per_class'),
        ]
        indexes = [
            # El reporte de ocupación filtra por (organización, rango de fechas de la clase).
            models.Index(fields=['organization', 'start_datetime']),
        ]

    def __str__(self):
        return f'{self.class_name} · {self.start_datetime:%Y-%m-%d %H:%M} · 0/{self.capacity}'


