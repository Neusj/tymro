from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers

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
    MembershipPlan,
    Organization,
    Person,
    RecurringEnrollment,
    StudentPlan,
    TeacherPaymentRecord,
    TeacherPaymentRule,
    TrialFollowupConfiguration,
)
from .services.recurrence import create_enrollments_for_recurring_subscription

User = get_user_model()


TERMINAL_CLASS_STATUSES = {
    GymClass.Status.COMPLETED,
    GymClass.Status.CANCELLED,
    GymClass.Status.COMPLETED_EARLY,
}


def _overlap_filter(start_datetime, end_datetime):
    return Q(start_datetime__lt=end_datetime, end_datetime__gt=start_datetime)

def _safe_int_setting(name, default=0):
    raw = getattr(settings, name, default)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = default
    return max(0, value)

def _student_deadline_message(hours):
    if hours <= 0:
        return 'Puedes modificar mientras la clase aun no haya comenzado.'
    return f'Puedes modificar hasta {hours} hora(s) antes del inicio de la clase.'

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


class OrganizationSerializer(serializers.ModelSerializer):
    branches_count = serializers.IntegerField(source='branches.count', read_only=True)
    public_registration_url = serializers.SerializerMethodField()

    class Meta:
        model = Organization
        fields = [
            'id',
            'name',
            'slug',
            'country',
            'city',
            'logo',
            'primary_color',
            'secondary_color',
            'is_active',
            'attendance_screen_code',
            'attendance_screen_session_code',
            'attendance_screen_session_expires_at',
            'public_registration_enabled',
            'public_registration_url',
            'branches_count',
        ]
        read_only_fields = [
            'attendance_screen_code',
            'attendance_screen_session_code',
            'attendance_screen_session_expires_at',
        ]

    def get_fields(self):
        fields = super().get_fields()
        # `is_active` y `public_registration_enabled` son editables solo al ACTUALIZAR
        # (PATCH del superadmin). En la creación se ignoran a propósito: las
        # organizaciones deben nacer SIEMPRE con los defaults del modelo
        # (is_active=True, public_registration_enabled=True). Sin esto, un payload
        # de create podría dar a luz una org desactivada o con el registro público
        # apagado. `self.instance is None` ⇒ estamos creando.
        if self.instance is None:
            fields['is_active'].read_only = True
            fields['public_registration_enabled'].read_only = True
        return fields

    def get_public_registration_url(self, obj):
        base = settings.FRONTEND_URL.rstrip('/')
        return f'{base}/{obj.slug}/clase-gratis'


class BranchSerializer(serializers.ModelSerializer):
    organization_name = serializers.CharField(source='organization.name', read_only=True)

    class Meta:
        model = Branch
        fields = [
            'id',
            'organization',
            'organization_name',
            'name',
            'code',
            'address',
            'logo',
            'primary_color',
            'secondary_color',
            'is_active',
        ]
        extra_kwargs = {
            'organization': {'required': False},
        }

    def validate(self, attrs):
        request = self.context.get('request')
        instance = getattr(self, 'instance', None)
        organization = attrs.get('organization', getattr(instance, 'organization', None))
        name = attrs.get('name', getattr(instance, 'name', ''))

        if request and request.user.is_authenticated and request.user.role == User.Role.GYM_ADMIN:
            attrs['organization'] = request.user.organization
            organization = attrs['organization']

        if not organization:
            raise serializers.ValidationError({'organization': 'La organización es obligatoria.'})

        normalized_name = str(name).strip()
        if not normalized_name:
            raise serializers.ValidationError({'name': 'El nombre es obligatorio.'})

        duplicated = Branch.objects.filter(organization=organization, name__iexact=normalized_name)
        if instance:
            duplicated = duplicated.exclude(id=instance.id)
        if duplicated.exists():
            raise serializers.ValidationError({'name': 'Ya existe una sucursal con ese nombre en esta organización.'})

        attrs['name'] = normalized_name

        return attrs


class CustomUserSerializer(serializers.ModelSerializer):
    organization_detail = OrganizationSerializer(source='organization', read_only=True)
    branch_detail = BranchSerializer(source='branch', read_only=True)
    password = serializers.CharField(write_only=True, required=False, min_length=6)

    class Meta:
        model = User
        fields = [
            'id',
            'username',
            'first_name',
            'last_name',
            'email',
            'is_active',
            'role',
            'phone',
            'profile_image',
            'is_active_member',
            'organization',
            'branch',
            'organization_detail',
            'branch_detail',
            'password',
        ]

    def validate(self, attrs):
        """Integridad de datos del usuario. La decisión de qué rol puede asignar
        quién vive SOLO en accounts/roles.py (can_assign); aquí solo se consulta
        como defensa en profundidad (el viewset ya la aplica con PermissionDenied)."""
        request = self.context.get('request')
        actor = getattr(request, 'user', None)

        # Rol efectivo: el del payload; en updates sin 'role', el de la instancia;
        # en create sin 'role', el default del modelo.
        effective_role = attrs.get('role') or (self.instance.role if self.instance else User.Role.STUDENT)

        # Actores org-admin (gym_admin/manager): la organización SIEMPRE es la suya.
        if roles.is_org_admin(actor):
            attrs['organization'] = actor.organization

        if actor is not None and getattr(actor, 'is_authenticated', False):
            if not roles.can_assign(actor, effective_role):
                raise serializers.ValidationError({'role': 'No puedes asignar este rol.'})

        organization = attrs.get('organization', getattr(self.instance, 'organization', None))
        branch = attrs.get('branch', getattr(self.instance, 'branch', None))

        if effective_role in roles.PLATFORM_ROLES:
            attrs['organization'] = None
            attrs['branch'] = None
        elif effective_role in roles.ORG_ROLES and not organization:
            raise serializers.ValidationError({'organization': 'Este rol requiere una organización.'})

        if branch and organization and branch.organization_id != organization.id:
            raise serializers.ValidationError({'branch': 'La sucursal no pertenece a la organización seleccionada.'})

        return attrs

    def create(self, validated_data):
        password = validated_data.pop('password', None)
        user = User(**validated_data)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save()
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        for key, value in validated_data.items():
            setattr(instance, key, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance


class PersonSerializer(serializers.ModelSerializer):
    organization_name = serializers.CharField(source='organization.name', read_only=True)
    branch_name = serializers.CharField(source='branch.name', read_only=True)

    class Meta:
        model = Person
        fields = [
            'id',
            'organization',
            'organization_name',
            'branch',
            'branch_name',
            'first_name',
            'last_name',
            'email',
            'phone',
            'role',
            'is_active',
        ]


class ClassTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClassType
        fields = ['id', 'organization', 'name', 'description', 'is_active']
        extra_kwargs = {
            'organization': {'required': False},
            'description': {'required': False},
            'is_active': {'required': False},
        }
        validators = []

    def validate(self, attrs):
        request = self.context.get('request')
        instance = getattr(self, 'instance', None)
        organization = attrs.get('organization', getattr(instance, 'organization', None))
        name = attrs.get('name', getattr(instance, 'name', ''))

        if request and request.user.is_authenticated and roles.is_org_admin(request.user):
            attrs['organization'] = request.user.organization
            organization = attrs['organization']

        if not organization:
            raise serializers.ValidationError({'organization': 'La organización es obligatoria.'})

        normalized_name = str(name).strip()
        if not normalized_name:
            raise serializers.ValidationError({'name': 'El nombre es obligatorio.'})

        duplicated = ClassType.objects.filter(organization=organization, name__iexact=normalized_name)
        if instance:
            duplicated = duplicated.exclude(id=instance.id)
        if duplicated.exists():
            raise serializers.ValidationError({'name': 'Ya existe un tipo de clase con ese nombre en esta organización.'})

        attrs['name'] = normalized_name

        return attrs


class TrialFollowupConfigurationSerializer(serializers.ModelSerializer):
    """Config del email de seguimiento de clases de prueba (una por organización).

    El modelo persiste los campos como ``is_active`` y ``minutes_after_class_end``.
    Exponemos los nombres externos ``is_enabled`` y ``delay_minutes`` vía ``source``
    para respetar el contrato pedido sin tocar el modelo ni su migración (el comando
    ``send_trial_followups`` sigue leyendo los nombres internos).
    """

    is_enabled = serializers.BooleanField(source='is_active', required=False)
    delay_minutes = serializers.IntegerField(
        source='minutes_after_class_end', required=False, min_value=0,
    )

    class Meta:
        model = TrialFollowupConfiguration
        fields = ['id', 'is_enabled', 'delay_minutes', 'email_subject', 'email_body', 'updated_at']
        read_only_fields = ['id', 'updated_at']
        extra_kwargs = {
            'email_subject': {'required': False},
            'email_body': {'required': False},
        }

    def validate_email_subject(self, value):
        if not str(value).strip():
            raise serializers.ValidationError('El asunto no puede quedar vacío.')
        return value

    def validate_email_body(self, value):
        if not str(value).strip():
            raise serializers.ValidationError('El cuerpo no puede quedar vacío.')
        return value


class DisciplineSerializer(serializers.ModelSerializer):
    class Meta:
        model = Discipline
        fields = ['id', 'organization', 'name', 'description', 'is_active']
        extra_kwargs = {
            'organization': {'required': False},
            'description': {'required': False},
            'is_active': {'required': False},
        }
        validators = []

    def validate(self, attrs):
        request = self.context.get('request')
        instance = getattr(self, 'instance', None)
        organization = attrs.get('organization', getattr(instance, 'organization', None))
        name = attrs.get('name', getattr(instance, 'name', ''))

        if request and request.user.is_authenticated and roles.is_org_admin(request.user):
            attrs['organization'] = request.user.organization
            organization = attrs['organization']

        if not organization:
            raise serializers.ValidationError({'organization': 'La organización es obligatoria.'})

        normalized_name = str(name).strip()
        if not normalized_name:
            raise serializers.ValidationError({'name': 'El nombre es obligatorio.'})

        duplicated = Discipline.objects.filter(organization=organization, name__iexact=normalized_name)
        if instance:
            duplicated = duplicated.exclude(id=instance.id)
        if duplicated.exists():
            raise serializers.ValidationError({'name': 'Ya existe una disciplina con ese nombre en esta organización.'})

        attrs['name'] = normalized_name
        return attrs


class HolidaySerializer(serializers.ModelSerializer):
    organization_name = serializers.CharField(source='organization.name', read_only=True)
    branch_name = serializers.CharField(source='branch.name', read_only=True)

    class Meta:
        model = Holiday
        fields = [
            'id',
            'organization',
            'organization_name',
            'branch',
            'branch_name',
            'date',
            'name',
            'scope',
            'source_type',
            'is_active',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']
        validators = []

    def validate(self, attrs):
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        instance = getattr(self, 'instance', None)

        scope = attrs.get('scope', getattr(instance, 'scope', Holiday.Scope.ORGANIZATION))
        source_type = attrs.get('source_type', getattr(instance, 'source_type', Holiday.SourceType.MANUAL))
        organization = attrs.get('organization', getattr(instance, 'organization', None))
        branch = attrs.get('branch', getattr(instance, 'branch', None))

        if user and user.is_authenticated and roles.is_org_admin(user):
            if scope == Holiday.Scope.GLOBAL:
                raise serializers.ValidationError({'scope': 'Gym admin no puede crear festivos globales.'})
            if source_type == Holiday.SourceType.SYSTEM:
                raise serializers.ValidationError({'source_type': 'Gym admin no puede crear festivos de sistema.'})
            organization = user.organization
            attrs['organization'] = organization
            if branch and branch.organization_id != user.organization_id:
                raise serializers.ValidationError({'branch': 'La sucursal debe pertenecer a tu organizacion.'})

        if instance and instance.source_type == Holiday.SourceType.SYSTEM:
            if 'source_type' in attrs and attrs['source_type'] != Holiday.SourceType.SYSTEM:
                raise serializers.ValidationError({'source_type': 'No se puede cambiar el origen de un festivo de sistema.'})

        model_instance = Holiday(
            organization=organization,
            branch=branch,
            date=attrs.get('date', getattr(instance, 'date', None)),
            name=attrs.get('name', getattr(instance, 'name', None)),
            scope=scope,
            source_type=source_type,
            is_active=attrs.get('is_active', getattr(instance, 'is_active', True)),
        )
        if instance:
            model_instance.pk = instance.pk
        try:
            model_instance.clean()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict or {'detail': exc.messages})
        return attrs


class EnrollmentSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    student_email = serializers.EmailField(source='student.email', read_only=True)
    gym_class_name = serializers.CharField(source='gym_class.name', read_only=True)
    class_branch_name = serializers.CharField(source='gym_class.branch.name', read_only=True)
    class_teacher_name = serializers.SerializerMethodField()
    class_discipline_name = serializers.CharField(source='gym_class.discipline.name', read_only=True)
    class_type_name = serializers.CharField(source='gym_class.class_type.name', read_only=True)
    class_template_id = serializers.IntegerField(source='gym_class.class_template_id', read_only=True)
    class_status = serializers.CharField(source='gym_class.status', read_only=True)
    class_start = serializers.DateTimeField(source='gym_class.start_datetime', read_only=True)
    class_end = serializers.DateTimeField(source='gym_class.end_datetime', read_only=True)
    reservation_kind = serializers.SerializerMethodField()
    recurring_is_active = serializers.BooleanField(source='recurring_enrollment.is_active', read_only=True)
    can_cancel = serializers.SerializerMethodField()
    cancel_block_reason = serializers.SerializerMethodField()
    cancel_policy_message = serializers.SerializerMethodField()
    attendance_status = serializers.SerializerMethodField()

    class Meta:
        model = Enrollment
        fields = [
            'id',
            'student',
            'student_name',
            'student_email',
            'gym_class',
            'gym_class_name',
            'class_branch_name',
            'class_teacher_name',
            'class_discipline_name',
            'class_type_name',
            'class_template_id',
            'class_status',
            'class_start',
            'class_end',
            'recurring_enrollment',
            'reservation_kind',
            'recurring_is_active',
            'status',
            'can_cancel',
            'cancel_block_reason',
            'cancel_policy_message',
            'attendance_status',
            'is_trial',
            'created_at',
        ]
        read_only_fields = ['created_at', 'recurring_enrollment', 'is_trial']
        extra_kwargs = {
            'student': {'required': False},
        }
        validators = []

    def get_student_name(self, obj):
        full_name = f'{obj.student.first_name} {obj.student.last_name}'.strip()
        return full_name or obj.student.username

    def get_class_teacher_name(self, obj):
        teacher = getattr(obj.gym_class, 'teacher', None)
        if not teacher:
            return ''
        full_name = f'{teacher.first_name} {teacher.last_name}'.strip()
        return full_name or teacher.username

    def get_reservation_kind(self, obj):
        return 'recurring' if obj.recurring_enrollment_id else 'single'

    def _cancel_state(self, obj):
        if obj.status != 'active':
            return False, 'La reserva ya esta cancelada.'
        if obj.gym_class.status in TERMINAL_CLASS_STATUSES:
            return False, 'La clase esta cerrada y ya no se puede modificar la reserva.'
        hours = _safe_int_setting('STUDENT_CANCEL_DEADLINE_HOURS', 0)
        allowed, reason = _student_can_modify_before_class(obj.gym_class.start_datetime, hours)
        if not allowed:
            return False, reason
        return True, ''

    def get_attendance_status(self, obj):
        # Estado de asistencia del alumno de ESTA reserva en ESA clase (present/absent/
        # no_show/late) o None si aún no se marcó. Scoped al student de la inscripción.
        attendance = (
            Attendance.objects.filter(gym_class_id=obj.gym_class_id, student_id=obj.student_id)
            .only('status')
            .first()
        )
        return attendance.status if attendance else None

    def get_can_cancel(self, obj):
        return self._cancel_state(obj)[0]

    def get_cancel_block_reason(self, obj):
        return self._cancel_state(obj)[1]

    def get_cancel_policy_message(self, obj):
        return _student_deadline_message(_safe_int_setting('STUDENT_CANCEL_DEADLINE_HOURS', 0))

    def validate(self, attrs):
        instance = getattr(self, 'instance', None)
        student = attrs.get('student', getattr(instance, 'student', None))
        gym_class = attrs.get('gym_class', getattr(instance, 'gym_class', None))
        status_value = attrs.get('status', getattr(instance, 'status', Enrollment.STATUS_CHOICES[0][0]))
        request = self.context.get('request')
        user = getattr(request, 'user', None)

        if user and user.is_authenticated and user.role == User.Role.STUDENT:
            if student and student.id != user.id:
                raise serializers.ValidationError({'student': 'Solo puedes reservar para tu propio usuario.'})
            student = user
            attrs['student'] = user

        if not student:
            raise serializers.ValidationError({'student': 'El alumno es obligatorio.'})
        if not gym_class:
            raise serializers.ValidationError({'gym_class': 'La clase es obligatoria.'})

        if student.role != User.Role.STUDENT:
            raise serializers.ValidationError({'student': 'Solo se pueden inscribir usuarios con rol student.'})

        if student.organization_id != gym_class.organization_id:
            raise serializers.ValidationError({'student': 'No puedes inscribir alumnos de otra organización.'})

        if gym_class.status == GymClass.Status.CANCELLED:
            raise serializers.ValidationError({'gym_class': 'No puedes reservar una clase cancelada.'})

        now = timezone.now()
        if gym_class.start_datetime <= now:
            raise serializers.ValidationError({'gym_class': 'No puedes reservar clases pasadas o ya iniciadas.'})

        if status_value == 'active' and gym_class.status in TERMINAL_CLASS_STATUSES:
            raise serializers.ValidationError({'gym_class': 'No puedes reservar una clase cerrada.'})

        if user and roles.is_org_admin(user) and gym_class.organization_id != user.organization_id:
            raise serializers.ValidationError({'gym_class': 'Solo puedes gestionar clases de tu organización.'})

        duplicate_exists = Enrollment.objects.filter(gym_class=gym_class, student=student)
        if instance:
            duplicate_exists = duplicate_exists.exclude(id=instance.id)
        existing = duplicate_exists.first()
        if existing and existing.status == 'active':
            raise serializers.ValidationError({'student': 'El alumno ya tiene una reserva para esta clase.'})

        if status_value == 'active':
            active_count = gym_class.enrollments.filter(status='active')
            if instance:
                active_count = active_count.exclude(id=instance.id)
            if active_count.count() >= gym_class.capacity:
                raise serializers.ValidationError({'gym_class': 'La clase ya alcanzó su capacidad máxima.'})

            overlapping_enrollments = Enrollment.objects.filter(
                student=student,
                status='active',
                gym_class__status__in=[GymClass.Status.SCHEDULED, GymClass.Status.IN_PROGRESS],
            ).filter(
                Q(
                    gym_class__start_datetime__lt=gym_class.end_datetime,
                    gym_class__end_datetime__gt=gym_class.start_datetime,
                )
            )
            if instance:
                overlapping_enrollments = overlapping_enrollments.exclude(id=instance.id)
            if overlapping_enrollments.exists():
                raise serializers.ValidationError({'student': 'El alumno ya tiene otra clase reservada o confirmada en ese horario.'})

        return attrs

    def create(self, validated_data):
        gym_class = validated_data['gym_class']
        student = validated_data['student']
        requested_status = validated_data.get('status', 'active')

        existing = Enrollment.objects.filter(gym_class=gym_class, student=student).first()
        if existing:
            # Si existe una reserva cancelada, la reactivamos en lugar de crear una nueva.
            existing.status = requested_status
            existing.save(update_fields=['status', 'updated_at'])
            return existing

        return Enrollment.objects.create(**validated_data)


class GymClassSerializer(serializers.ModelSerializer):
    class_template_name = serializers.CharField(source='class_template.name', read_only=True)
    branch_name = serializers.CharField(source='branch.name', read_only=True)
    teacher_name = serializers.SerializerMethodField()
    class_type_name = serializers.CharField(source='class_type.name', read_only=True)
    discipline_name = serializers.CharField(source='discipline.name', read_only=True)
    enrollments_count = serializers.SerializerMethodField()
    attendances_count = serializers.SerializerMethodField()
    present_attendances_count = serializers.SerializerMethodField()
    is_suspended = serializers.SerializerMethodField()
    can_suspend = serializers.SerializerMethodField()
    can_reactivate = serializers.SerializerMethodField()

    class Meta:
        model = GymClass
        fields = [
            'id',
            'name',
            'organization',
            'class_template',
            'class_template_name',
            'branch',
            'branch_name',
            'teacher',
            'teacher_name',
            'class_type',
            'class_type_name',
            'discipline',
            'discipline_name',
            'start_datetime',
            'end_datetime',
            'capacity',
            'is_trial_eligible',
            'status',
            'created_by',
            'closed_by',
            'closed_at',
            'closure_comment',
            'suspended_at',
            'suspend_reason',
            'suspended_by',
            'reactivation_expected_date',
            'is_suspended',
            'can_suspend',
            'can_reactivate',
            'is_active',
            'enrollments_count',
            'attendances_count',
            'present_attendances_count',
        ]
        extra_kwargs = {
            'organization': {'required': False},
            'created_by': {'read_only': True},
            'closed_by': {'read_only': True},
            'closed_at': {'read_only': True},
            'closure_comment': {'read_only': True},
            'suspended_at': {'read_only': True},
            'suspend_reason': {'read_only': True},
            'suspended_by': {'read_only': True},
            'reactivation_expected_date': {'read_only': True},
        }

    def get_teacher_name(self, obj):
        if not obj.teacher:
            return ''
        full_name = f'{obj.teacher.first_name} {obj.teacher.last_name}'.strip()
        return full_name or obj.teacher.username

    def get_enrollments_count(self, obj):
        return obj.enrollments.filter(status='active').count()

    def get_attendances_count(self, obj):
        return obj.attendances.count()

    def get_present_attendances_count(self, obj):
        return obj.attendances.filter(status=Attendance.Status.PRESENT).count()

    def get_is_suspended(self, obj):
        return obj.status == GymClass.Status.SUSPENDED

    def get_can_suspend(self, obj):
        return obj.status in {GymClass.Status.SCHEDULED, GymClass.Status.IN_PROGRESS}

    def get_can_reactivate(self, obj):
        return obj.status == GymClass.Status.SUSPENDED

    def validate(self, attrs):
        instance = getattr(self, 'instance', None)
        request = self.context.get('request')
        user = getattr(request, 'user', None)

        organization = attrs.get('organization', getattr(instance, 'organization', None))
        branch = attrs.get('branch', getattr(instance, 'branch', None))
        teacher = attrs.get('teacher', getattr(instance, 'teacher', None))
        class_type = attrs.get('class_type', getattr(instance, 'class_type', None))
        discipline = attrs.get('discipline', getattr(instance, 'discipline', None))
        class_template = attrs.get('class_template', getattr(instance, 'class_template', None))
        start_datetime = attrs.get('start_datetime', getattr(instance, 'start_datetime', None))
        end_datetime = attrs.get('end_datetime', getattr(instance, 'end_datetime', None))
        capacity = attrs.get('capacity', getattr(instance, 'capacity', None))

        if instance and instance.is_closed:
            editable_fields = {'name', 'branch', 'teacher', 'class_type', 'discipline', 'start_datetime', 'end_datetime', 'capacity'}
            if editable_fields.intersection(attrs.keys()):
                raise serializers.ValidationError({'status': 'No puedes editar una clase que ya está cerrada.'})

        if user and user.is_authenticated and roles.is_org_admin(user):
            organization = user.organization
            attrs['organization'] = organization

        if not organization:
            raise serializers.ValidationError({'organization': 'La organización es obligatoria.'})
        if not branch:
            raise serializers.ValidationError({'branch': 'La sucursal es obligatoria.'})
        if not teacher:
            raise serializers.ValidationError({'teacher': 'El profesor es obligatorio.'})
        if not class_type:
            raise serializers.ValidationError({'class_type': 'El tipo de clase es obligatorio.'})
        if not discipline:
            raise serializers.ValidationError({'discipline': 'La disciplina es obligatoria.'})

        if branch.organization_id != organization.id:
            raise serializers.ValidationError({'branch': 'La sucursal no pertenece a la organización indicada.'})
        if class_type.organization_id != organization.id:
            raise serializers.ValidationError({'class_type': 'El tipo de clase no pertenece a la organización indicada.'})
        if discipline.organization_id != organization.id:
            raise serializers.ValidationError({'discipline': 'La disciplina no pertenece a la organización indicada.'})
        if class_template and class_template.organization_id != organization.id:
            raise serializers.ValidationError({'class_template': 'La plantilla no pertenece a la organización indicada.'})

        if teacher.role != User.Role.TEACHER:
            raise serializers.ValidationError({'teacher': 'El usuario seleccionado no es profesor.'})
        if teacher.organization_id != organization.id:
            raise serializers.ValidationError({'teacher': 'El profesor debe pertenecer a la misma organización.'})

        if start_datetime and end_datetime and end_datetime <= start_datetime:
            raise serializers.ValidationError({'end_datetime': 'La fecha de término debe ser posterior al inicio.'})

        if capacity is not None and int(capacity) <= 0:
            raise serializers.ValidationError({'capacity': 'La capacidad debe ser mayor que cero.'})

        if start_datetime and end_datetime and teacher:
            conflicting_classes = GymClass.objects.filter(
                teacher=teacher,
            ).exclude(status=GymClass.Status.CANCELLED).filter(
                _overlap_filter(start_datetime, end_datetime)
            )
            if instance:
                conflicting_classes = conflicting_classes.exclude(id=instance.id)
            if conflicting_classes.exists():
                raise serializers.ValidationError({'teacher': 'El profesor ya está asignado a otra clase en ese horario.'})

        incoming_status = attrs.get('status')
        if incoming_status in TERMINAL_CLASS_STATUSES:
            raise serializers.ValidationError({'status': 'Usa las acciones de cierre/cancelación para cambiar a un estado terminal.'})
        if incoming_status == GymClass.Status.SUSPENDED:
            raise serializers.ValidationError({'status': 'Usa la acción de suspender para suspender una clase.'})

        return attrs


class AttendanceSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    student_email = serializers.EmailField(source='student.email', read_only=True)
    marked_by_username = serializers.CharField(source='marked_by.username', read_only=True)

    class Meta:
        model = Attendance
        fields = [
            'id',
            'gym_class',
            'student',
            'student_name',
            'student_email',
            'status',
            'source',
            'marked_by',
            'marked_by_username',
            'marked_at',
            'checked_at',
            'trial_followup_sent_at',
        ]
        read_only_fields = ['trial_followup_sent_at']

    def get_student_name(self, obj):
        full_name = f'{obj.student.first_name} {obj.student.last_name}'.strip()
        return full_name or obj.student.username


class AttendanceItemWriteSerializer(serializers.Serializer):
    student_id = serializers.IntegerField()
    status = serializers.ChoiceField(choices=Attendance.Status.choices)


class AttendanceBulkWriteSerializer(serializers.Serializer):
    attendances = AttendanceItemWriteSerializer(many=True, allow_empty=False)

    def validate_attendances(self, value):
        seen_ids = set()
        for item in value:
            student_id = item['student_id']
            if student_id in seen_ids:
                raise serializers.ValidationError('No puedes repetir el mismo alumno en la lista de asistencia.')
            seen_ids.add(student_id)
        return value


class GymClassDetailSerializer(GymClassSerializer):
    enrollments = EnrollmentSerializer(many=True, read_only=True)
    attendances = AttendanceSerializer(many=True, read_only=True)

    class Meta(GymClassSerializer.Meta):
        fields = GymClassSerializer.Meta.fields + ['enrollments', 'attendances']


class ClassTemplateSerializer(serializers.ModelSerializer):
    organization_name = serializers.CharField(source='organization.name', read_only=True)
    branch_name = serializers.CharField(source='branch.name', read_only=True)
    teacher_name = serializers.SerializerMethodField()
    class_type_name = serializers.CharField(source='class_type.name', read_only=True)
    discipline_name = serializers.CharField(source='discipline.name', read_only=True)
    generated_instances_count = serializers.SerializerMethodField()
    has_active_enrollments = serializers.SerializerMethodField()

    class Meta:
        model = ClassTemplate
        fields = [
            'id',
            'organization',
            'organization_name',
            'branch',
            'branch_name',
            'teacher',
            'teacher_name',
            'class_type',
            'class_type_name',
            'discipline',
            'discipline_name',
            'name',
            'description',
            'weekday',
            'start_time',
            'end_time',
            'capacity',
            'is_trial_eligible',
            'start_date',
            'end_date',
            'is_active',
            'generated_instances_count',
            'has_active_enrollments',
            'created_by',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['created_by', 'created_at', 'updated_at']
        extra_kwargs = {
            'organization': {'required': False},
        }

    def get_teacher_name(self, obj):
        if not obj.teacher:
            return ''
        full_name = f'{obj.teacher.first_name} {obj.teacher.last_name}'.strip()
        return full_name or obj.teacher.username

    def get_generated_instances_count(self, obj):
        return obj.instances.count()

    def get_has_active_enrollments(self, obj):
        return obj.instances.filter(enrollments__status='active').exists()

    def validate(self, attrs):
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        instance = getattr(self, 'instance', None)

        organization = attrs.get('organization', getattr(instance, 'organization', None))
        branch = attrs.get('branch', getattr(instance, 'branch', None))
        teacher = attrs.get('teacher', getattr(instance, 'teacher', None))
        class_type = attrs.get('class_type', getattr(instance, 'class_type', None))
        discipline = attrs.get('discipline', getattr(instance, 'discipline', None))

        if user and user.is_authenticated and roles.is_org_admin(user):
            organization = user.organization
            attrs['organization'] = organization

        if not organization:
            raise serializers.ValidationError({'organization': 'La organización es obligatoria.'})
        if not branch:
            raise serializers.ValidationError({'branch': 'La sucursal es obligatoria.'})
        if not teacher:
            raise serializers.ValidationError({'teacher': 'El profesor es obligatorio.'})
        if not class_type:
            raise serializers.ValidationError({'class_type': 'El tipo de clase es obligatorio.'})
        if not discipline:
            raise serializers.ValidationError({'discipline': 'La disciplina es obligatoria.'})

        data = {
            'organization': organization,
            'branch': branch,
            'teacher': teacher,
            'class_type': class_type,
            'discipline': discipline,
            'name': attrs.get('name', getattr(instance, 'name', '')),
            'description': attrs.get('description', getattr(instance, 'description', '')),
            'weekday': attrs.get('weekday', getattr(instance, 'weekday', None)),
            'start_time': attrs.get('start_time', getattr(instance, 'start_time', None)),
            'end_time': attrs.get('end_time', getattr(instance, 'end_time', None)),
            'capacity': attrs.get('capacity', getattr(instance, 'capacity', None)),
            'start_date': attrs.get('start_date', getattr(instance, 'start_date', None)),
            'end_date': attrs.get('end_date', getattr(instance, 'end_date', None)),
            'is_active': attrs.get('is_active', getattr(instance, 'is_active', True)),
            'created_by': getattr(instance, 'created_by', None),
        }
        model_instance = ClassTemplate(**data)
        if instance:
            model_instance.pk = instance.pk
        try:
            model_instance.clean()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict or {'detail': exc.messages})
        return attrs


class RecurringEnrollmentSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    template_name = serializers.CharField(source='class_template.name', read_only=True)
    template_branch_name = serializers.CharField(source='class_template.branch.name', read_only=True)
    template_teacher_name = serializers.SerializerMethodField()
    template_discipline_name = serializers.CharField(source='class_template.discipline.name', read_only=True)
    template_weekday = serializers.IntegerField(source='class_template.weekday', read_only=True)
    template_start_time = serializers.TimeField(source='class_template.start_time', read_only=True)
    template_end_time = serializers.TimeField(source='class_template.end_time', read_only=True)
    last_sync = serializers.SerializerMethodField()
    next_class_start = serializers.SerializerMethodField()
    can_manage_now = serializers.SerializerMethodField()
    manage_block_reason = serializers.SerializerMethodField()
    manage_policy_message = serializers.SerializerMethodField()

    class Meta:
        model = RecurringEnrollment
        fields = [
            'id',
            'student',
            'student_name',
            'class_template',
            'template_name',
            'template_branch_name',
            'template_teacher_name',
            'template_discipline_name',
            'template_weekday',
            'template_start_time',
            'template_end_time',
            'recurrence_type',
            'start_date',
            'end_date',
            'is_active',
            'created_by',
            'created_at',
            'updated_at',
            'last_sync',
            'next_class_start',
            'can_manage_now',
            'manage_block_reason',
            'manage_policy_message',
        ]
        read_only_fields = ['created_by', 'created_at', 'updated_at', 'last_sync']
        extra_kwargs = {
            'student': {'required': False},
        }

    def get_student_name(self, obj):
        full_name = f'{obj.student.first_name} {obj.student.last_name}'.strip()
        return full_name or obj.student.username

    def get_template_teacher_name(self, obj):
        teacher = getattr(obj.class_template, 'teacher', None)
        if not teacher:
            return ''
        full_name = f'{teacher.first_name} {teacher.last_name}'.strip()
        return full_name or teacher.username

    def get_last_sync(self, obj):
        latest = obj.enrollments.order_by('-updated_at').first()
        return latest.updated_at if latest else None

    def _next_applicable_class(self, obj):
        now = timezone.now()
        queryset = obj.class_template.instances.filter(start_datetime__gt=now).exclude(status__in=TERMINAL_CLASS_STATUSES)
        queryset = queryset.filter(start_datetime__date__gte=obj.start_date)
        if obj.end_date:
            queryset = queryset.filter(start_datetime__date__lte=obj.end_date)
        return queryset.order_by('start_datetime').first()

    def _manage_state(self, obj):
        next_class = self._next_applicable_class(obj)
        if not next_class:
            return True, ''
        hours = _safe_int_setting('STUDENT_RECURRING_CHANGE_DEADLINE_HOURS', 0)
        allowed, reason = _student_can_modify_before_class(next_class.start_datetime, hours)
        if not allowed:
            return False, reason
        return True, ''

    def get_next_class_start(self, obj):
        next_class = self._next_applicable_class(obj)
        return next_class.start_datetime if next_class else None

    def get_can_manage_now(self, obj):
        return self._manage_state(obj)[0]

    def get_manage_block_reason(self, obj):
        return self._manage_state(obj)[1]

    def get_manage_policy_message(self, obj):
        return _student_deadline_message(_safe_int_setting('STUDENT_RECURRING_CHANGE_DEADLINE_HOURS', 0))

    def validate(self, attrs):
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        instance = getattr(self, 'instance', None)

        student = attrs.get('student', getattr(instance, 'student', None))
        class_template = attrs.get('class_template', getattr(instance, 'class_template', None))

        if user and user.is_authenticated and user.role == User.Role.STUDENT:
            student = user
            attrs['student'] = user

        if not student:
            raise serializers.ValidationError({'student': 'El alumno es obligatorio.'})
        if not class_template:
            raise serializers.ValidationError({'class_template': 'La plantilla es obligatoria.'})
        if not class_template.is_active:
            raise serializers.ValidationError({'class_template': 'Solo puedes suscribirte a plantillas activas.'})

        if class_template.organization_id != student.organization_id:
            raise serializers.ValidationError({'class_template': 'La plantilla no pertenece a tu organización.'})

        data = {
            'student': student,
            'class_template': class_template,
            'recurrence_type': attrs.get('recurrence_type', getattr(instance, 'recurrence_type', RecurringEnrollment.RecurrenceType.WEEKLY)),
            'start_date': attrs.get('start_date', getattr(instance, 'start_date', None)),
            'end_date': attrs.get('end_date', getattr(instance, 'end_date', None)),
            'is_active': attrs.get('is_active', getattr(instance, 'is_active', True)),
            'created_by': getattr(instance, 'created_by', None),
        }
        model_instance = RecurringEnrollment(**data)
        if instance:
            model_instance.pk = instance.pk
        try:
            model_instance.clean()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict or {'detail': exc.messages})

        if model_instance.is_active:
            duplicate = RecurringEnrollment.objects.filter(
                student=student,
                class_template=class_template,
                is_active=True,
            )
            if instance:
                duplicate = duplicate.exclude(pk=instance.pk)
            if duplicate.exists():
                raise serializers.ValidationError({'class_template': 'Ya existe una recurrencia activa para este alumno en esta serie.'})

        return attrs

    def create(self, validated_data):
        recurring_enrollment = RecurringEnrollment.objects.create(**validated_data)
        create_enrollments_for_recurring_subscription(recurring_enrollment=recurring_enrollment)
        return recurring_enrollment


class MembershipPlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = MembershipPlan
        fields = [
            'id',
            'organization',
            'name',
            'plan_kind',
            'price',
            'class_limit',
            'expires_in_days',
            'allows_rollover',
            'is_active',
        ]


class PlanSerializer(serializers.ModelSerializer):
    organization_name = serializers.CharField(source='organization.name', read_only=True)

    class Meta:
        model = Plan
        fields = [
            'id',
            'organization',
            'organization_name',
            'name',
            'plan_type',
            'total_classes',
            'unlimited_classes',
            'duration_days',
            'price',
            'discount_percentage',
            'is_public',
            'is_active',
        ]
        extra_kwargs = {
            'organization': {'required': False},
        }

    def validate(self, attrs):
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        instance = getattr(self, 'instance', None)
        organization = attrs.get('organization', getattr(instance, 'organization', None))

        if user and user.is_authenticated and user.role == User.Role.GYM_ADMIN:
            organization = user.organization
            attrs['organization'] = organization

        if not organization:
            raise serializers.ValidationError({'organization': 'La organización es obligatoria.'})

        if user and user.is_authenticated and user.role == User.Role.STUDENT:
            raise serializers.ValidationError({'detail': 'Los alumnos no pueden gestionar planes.'})

        return attrs


class StudentPlanSerializer(serializers.ModelSerializer):
    plan_name = serializers.CharField(source='plan.name', read_only=True)
    plan_type = serializers.CharField(source='plan.plan_type', read_only=True)
    user_name = serializers.SerializerMethodField()
    user_email = serializers.CharField(source='user.email', read_only=True)
    remaining_classes = serializers.SerializerMethodField()
    validity_status = serializers.SerializerMethodField()
    days_to_expiry = serializers.SerializerMethodField()
    expiry_alert_level = serializers.SerializerMethodField()
    expiry_alert_message = serializers.SerializerMethodField()
    enrollment_fee_status = serializers.SerializerMethodField()

    class Meta:
        model = StudentPlan
        fields = [
            'id',
            'user',
            'user_name',
            'user_email',
            'plan',
            'plan_name',
            'plan_type',
            'start_date',
            'end_date',
            'total_classes',
            'unlimited_classes',
            'classes_used',
            'remaining_classes',
            'validity_status',
            'days_to_expiry',
            'expiry_alert_level',
            'expiry_alert_message',
            'discount_percentage',
            'final_price',
            'enrollment_fee',
            'enrollment_fee_paid_at',
            'enrollment_fee_due_at',
            'enrollment_fee_status',
            'is_active',
        ]
        read_only_fields = [
            'unlimited_classes',
            'classes_used',
            'remaining_classes',
            'final_price',
            'enrollment_fee',
            'enrollment_fee_paid_at',
            'enrollment_fee_due_at',
        ]

    def get_remaining_classes(self, obj):
        if getattr(obj, 'unlimited_classes', False):
            return None
        return max((obj.total_classes or 0) - (obj.classes_used or 0), 0)

    def get_enrollment_fee_status(self, obj):
        fee = obj.enrollment_fee or 0
        if fee <= 0:
            return {'status': 'waived'}
        if obj.enrollment_fee_paid_at:
            return {'status': 'paid', 'paid_at': obj.enrollment_fee_paid_at.isoformat()}
        due = obj.enrollment_fee_due_at
        if due and timezone.localdate() > due:
            return {'status': 'overdue', 'due_at': due.isoformat()}
        return {'status': 'pending', 'due_at': due.isoformat() if due else None}

    def get_user_name(self, obj):
        if not obj.user:
            return ''
        full_name = f'{obj.user.first_name} {obj.user.last_name}'.strip()
        return full_name or obj.user.username

    def _days_to_expiry(self, obj):
        if not obj or not obj.end_date:
            return None
        return (obj.end_date - timezone.localdate()).days

    def get_validity_status(self, obj):
        today = timezone.localdate()
        if obj.end_date and obj.end_date < today:
            return 'expired'
        if obj.start_date and obj.start_date > today:
            return 'upcoming'
        if not obj.is_active:
            return 'inactive'
        return 'active'

    def get_days_to_expiry(self, obj):
        return self._days_to_expiry(obj)

    def get_expiry_alert_level(self, obj):
        status_value = self.get_validity_status(obj)
        if status_value == 'upcoming':
            return 'safe'
        if status_value != 'active':
            return 'expired' if status_value == 'expired' else 'neutral'

        days = self._days_to_expiry(obj)
        if days is None:
            return 'neutral'
        if days <= 5:
            return 'danger'
        if days <= 12:
            return 'warning'
        return 'safe'

    def get_expiry_alert_message(self, obj):
        status_value = self.get_validity_status(obj)
        if status_value == 'expired':
            return 'Vencido'
        if status_value == 'upcoming':
            return 'Por iniciar'
        if status_value == 'inactive':
            return 'No vigente'
        days = self._days_to_expiry(obj)
        if days is None:
            return 'Sin fecha de vencimiento'
        if days == 0:
            return 'Vence hoy'
        if days == 1:
            return '1 dia vigente'
        return f'{days} dias vigentes'


class StudentPlanAssignSerializer(serializers.Serializer):
    user = serializers.PrimaryKeyRelatedField(queryset=User.objects.filter(role=User.Role.STUDENT, is_active=True))
    plan = serializers.PrimaryKeyRelatedField(queryset=Plan.objects.filter(is_active=True))
    start_date = serializers.DateField()
    discount_percentage = serializers.FloatField(required=False, min_value=0, max_value=100)

    def validate(self, attrs):
        plan = attrs['plan']
        student = attrs['user']
        if plan.organization_id != student.organization_id:
            raise serializers.ValidationError({'plan': 'El plan no pertenece a la organización del alumno.'})
        # La cantidad de clases (y si es ilimitado) se DERIVA del plan, no es editable en la asignación.
        attrs['total_classes'] = plan.total_classes
        attrs['unlimited_classes'] = plan.unlimited_classes
        attrs['discount_percentage'] = attrs.get('discount_percentage', plan.discount_percentage or 0)
        attrs['end_date'] = attrs['start_date'] + timedelta(days=max(plan.duration_days - 1, 0))
        return attrs

class TeacherPaymentRuleSerializer(serializers.ModelSerializer):
    branch_name = serializers.CharField(source='branch.name', read_only=True)
    discipline_name = serializers.CharField(source='discipline.name', read_only=True)
    class_type_name = serializers.CharField(source='class_type.name', read_only=True)
    usage_count = serializers.IntegerField(read_only=True)
    is_used = serializers.SerializerMethodField()
    assigned_teachers_count = serializers.SerializerMethodField()

    class Meta:
        model = TeacherPaymentRule
        fields = [
            'id',
            'organization',
            'branch',
            'branch_name',
            'discipline',
            'discipline_name',
            'class_type',
            'class_type_name',
            'payment_type',
            'amount',
            'calculation_base',
            'per_plan_price_base',
            'is_active',
            'usage_count',
            'is_used',
            'assigned_teachers_count',
            'created_at',
            'updated_at',
        ]
        extra_kwargs = {
            'organization': {'required': False},
        }

    def get_is_used(self, obj):
        usage = getattr(obj, 'usage_count', None)
        if usage is None:
            usage = obj.teachers.count()
        return int(usage or 0) > 0

    def get_assigned_teachers_count(self, obj):
        return obj.teachers.count()

    def validate(self, attrs):
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        instance = getattr(self, 'instance', None)

        organization = attrs.get('organization', getattr(instance, 'organization', None))
        branch = attrs.get('branch', getattr(instance, 'branch', None))
        discipline = attrs.get('discipline', getattr(instance, 'discipline', None))
        class_type = attrs.get('class_type', getattr(instance, 'class_type', None))
        payment_type = attrs.get('payment_type', getattr(instance, 'payment_type', None))
        amount = attrs.get('amount', getattr(instance, 'amount', None))
        calculation_base = attrs.get('calculation_base', getattr(instance, 'calculation_base', None))
        per_plan_price_base = attrs.get('per_plan_price_base', getattr(instance, 'per_plan_price_base', None))

        if user and user.is_authenticated and user.role == User.Role.GYM_ADMIN:
            organization = user.organization
            attrs['organization'] = organization

        if not organization:
            raise serializers.ValidationError({'organization': 'La organizacion es obligatoria.'})
        if branch and branch.organization_id != organization.id:
            raise serializers.ValidationError({'branch': 'La sucursal no pertenece a la organizacion seleccionada.'})
        if discipline and discipline.organization_id != organization.id:
            raise serializers.ValidationError({'discipline': 'La disciplina no pertenece a la organizacion seleccionada.'})
        if class_type and class_type.organization_id != organization.id:
            raise serializers.ValidationError({'class_type': 'El tipo de clase no pertenece a la organizacion seleccionada.'})

        if payment_type == TeacherPaymentRule.PaymentType.FIXED_PER_CLASS:
            attrs['calculation_base'] = None
            if amount is None or float(amount) < 0:
                raise serializers.ValidationError({'amount': 'El monto debe ser mayor o igual a 0.'})
        elif payment_type == TeacherPaymentRule.PaymentType.PER_STUDENT:
            attrs['calculation_base'] = TeacherPaymentRule.CalculationBase.ATTENDANCE
            if amount is None or float(amount) < 0:
                raise serializers.ValidationError({'amount': 'El monto por alumno debe ser mayor o igual a 0.'})
        elif payment_type == TeacherPaymentRule.PaymentType.REVENUE_SHARE:
            if calculation_base not in {
                TeacherPaymentRule.CalculationBase.ATTENDANCE,
                TeacherPaymentRule.CalculationBase.ENROLLMENT,
            }:
                raise serializers.ValidationError({'calculation_base': 'Selecciona attendance o enrollment.'})
            if amount is None or float(amount) < 0 or float(amount) > 100:
                raise serializers.ValidationError({'amount': 'El porcentaje debe estar entre 0 y 100.'})
        elif payment_type == TeacherPaymentRule.PaymentType.PER_PLAN_PRICE:
            attrs['calculation_base'] = None
            if per_plan_price_base not in {
                TeacherPaymentRule.PerPlanPriceBase.ACTIVE_ENROLLMENTS,
                TeacherPaymentRule.PerPlanPriceBase.PRESENT_ATTENDEES,
            }:
                raise serializers.ValidationError(
                    {'per_plan_price_base': 'Selecciona inscritos o presentes.'}
                )
            if amount is None or float(amount) < 0 or float(amount) > 100:
                raise serializers.ValidationError({'amount': 'El porcentaje debe estar entre 0 y 100.'})
        else:
            raise serializers.ValidationError({'payment_type': 'Tipo de pago invalido.'})

        return attrs


class TeacherPaymentRuleAssignmentsUpdateSerializer(serializers.Serializer):
    teacher_ids = serializers.ListField(child=serializers.IntegerField(), allow_empty=True)


class TeacherPaymentRecordSerializer(serializers.ModelSerializer):
    teacher_name = serializers.SerializerMethodField()
    class_name = serializers.CharField(source='class_instance.name', read_only=True)
    class_start = serializers.DateTimeField(source='class_instance.start_datetime', read_only=True)
    payment_type = serializers.CharField(source='rule.payment_type', read_only=True)

    class Meta:
        model = TeacherPaymentRecord
        fields = [
            'id',
            'teacher',
            'teacher_name',
            'class_instance',
            'class_name',
            'class_start',
            'rule',
            'payment_type',
            'total_students',
            'total_amount',
            'calculated_at',
        ]

    def get_teacher_name(self, obj):
        if not obj.teacher_id:
            return '-'
        full_name = f'{obj.teacher.first_name} {obj.teacher.last_name}'.strip()
        return full_name or obj.teacher.username


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class PasswordResetConfirmSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(write_only=True)


class PublicOrganizationBrandingSerializer(serializers.ModelSerializer):
    """Marca pública del gimnasio para la landing de registro. Solo lectura,
    sin exponer el token ni datos internos."""

    class Meta:
        model = Organization
        fields = ['name', 'slug', 'logo', 'primary_color', 'secondary_color']


class PublicRegistrationSerializer(serializers.Serializer):
    """Registro público de un prospecto. NO incluye role ni organization:
    el servidor los fija desde el token de invitación. Inyección imposible."""

    first_name = serializers.CharField(max_length=150)
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)
    phone = serializers.CharField(max_length=40, required=False, allow_blank=True)

    def validate_email(self, value):
        normalized = value.strip().lower()
        if User.objects.filter(email__iexact=normalized).exists() or User.objects.filter(username__iexact=normalized).exists():
            raise serializers.ValidationError('Ya existe una cuenta con ese email.')
        return normalized

    def validate_password(self, value):
        from django.contrib.auth.password_validation import validate_password

        try:
            validate_password(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages))
        return value


class PublicTrialClassSerializer(serializers.ModelSerializer):
    branch_name = serializers.CharField(source='branch.name', read_only=True)
    teacher_name = serializers.SerializerMethodField()
    class_type_name = serializers.CharField(source='class_type.name', read_only=True)
    seats_left = serializers.SerializerMethodField()

    class Meta:
        model = GymClass
        fields = [
            'id',
            'name',
            'branch_name',
            'teacher_name',
            'class_type_name',
            'start_datetime',
            'end_datetime',
            'capacity',
            'seats_left',
        ]

    def get_teacher_name(self, obj):
        if not obj.teacher_id:
            return ''
        full_name = f'{obj.teacher.first_name} {obj.teacher.last_name}'.strip()
        return full_name or obj.teacher.username

    def get_seats_left(self, obj):
        active = obj.enrollments.filter(status='active').count()
        return max(0, obj.capacity - active)





