import uuid
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
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

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='legacy_plans')
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


class StudentPlan(TimestampedModel):
    user = models.ForeignKey('accounts.CustomUser', on_delete=models.CASCADE, related_name='student_plans')
    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name='student_plans')
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

    class Meta:
        ordering = ['-start_date']

    def __str__(self):
        return f'{self.user} - {self.plan}'

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
    consumed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-consumed_at']

    def __str__(self):
        return f'Consumo {self.user_id} - {self.class_instance_id}'


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
        if self.branch and self.organization_id and self.branch.organization_id != self.organization_id:
            raise ValidationError({'branch': 'La sucursal no pertenece a la organizacion indicada.'})
        if self.class_type and self.organization_id and self.class_type.organization_id != self.organization_id:
            raise ValidationError({'class_type': 'El tipo de clase no pertenece a la organizacion indicada.'})
        if self.discipline and self.organization_id and self.discipline.organization_id != self.organization_id:
            raise ValidationError({'discipline': 'La disciplina no pertenece a la organizacion indicada.'})

        if not self.teacher:
            return

        queryset = ClassTemplate.objects.filter(
            teacher=self.teacher,
            weekday=self.weekday,
            is_active=True,
            start_time__lt=self.end_time,
            end_time__gt=self.start_time,
        )
        if self.pk:
            queryset = queryset.exclude(pk=self.pk)

        if self.end_date is None:
            queryset = queryset.filter(models.Q(end_date__isnull=True) | models.Q(end_date__gte=self.start_date))
        else:
            queryset = queryset.filter(models.Q(start_date__lte=self.end_date))
            queryset = queryset.filter(models.Q(end_date__isnull=True) | models.Q(end_date__gte=self.start_date))

        if queryset.exists():
            raise ValidationError({'teacher': 'El profesor ya tiene otra plantilla activa en ese horario.'})

        weekday_for_db = ((self.weekday + 1) % 7) + 1
        class_query = GymClass.objects.filter(
            teacher=self.teacher,
            start_datetime__week_day=weekday_for_db,
            start_datetime__time__lt=self.end_time,
            end_datetime__time__gt=self.start_time,
        ).exclude(status=GymClass.Status.CANCELLED)
        if self.pk:
            class_query = class_query.exclude(class_template_id=self.pk)
        if self.end_date is None:
            class_query = class_query.filter(start_datetime__date__gte=self.start_date)
        else:
            class_query = class_query.filter(
                start_datetime__date__gte=self.start_date,
                start_datetime__date__lte=self.end_date,
            )

        if class_query.exists():
            raise ValidationError({'teacher': 'El profesor ya tiene clases creadas que se cruzan con esta plantilla.'})



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
    STATUS_CHOICES = [
        ('pending', 'pending'),
        ('in_process', 'in_process'),
        ('approved', 'approved'),
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


