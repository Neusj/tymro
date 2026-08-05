from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import NotFound

from accounts import roles
from accounts.rut import clean_rut

from .services.public_urls import trial_signup_url

from .models import (
    Attendance,
    AttendanceChangeLog,
    Branch,
    ChargeLineItem,
    ClassTemplate,
    ClassType,
    Discipline,
    Enrollment,
    GymClass,
    Holiday,
    ManualPayment,
    Plan,
    MembershipPlan,
    Organization,
    PaymentAccount,
    PaymentTransaction,
    Person,
    RecurringEnrollment,
    StudentPlan,
    TeacherPaymentRecord,
    TeacherPaymentRule,
    TrialFollowupConfiguration,
)
from .services.plans import describe_student_plan
from .services.recurrence import create_enrollments_for_recurring_subscription
from .services.reservations import (
    REASON_PLAN_NOT_FOUND,
    ReservationRuleError,
    resolve_student_plan_for_recurring_enrollment,
)

User = get_user_model()


TERMINAL_CLASS_STATUSES = {
    GymClass.Status.COMPLETED,
    GymClass.Status.CANCELLED,
    GymClass.Status.COMPLETED_EARLY,
}


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
    # Subdominio de tenant. Validación (formato + reservados + unicidad) en
    # validate_subdomain; obligatorio al crear (ver validate()).
    subdomain = serializers.CharField(max_length=50, required=False, allow_null=True, allow_blank=True)

    class Meta:
        model = Organization
        fields = [
            'id',
            'name',
            'slug',
            'subdomain',
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
            'trial_validity_days',
            'class_generation_window_days',
            'class_pruning_grace_days',
            'branches_count',
        ]
        read_only_fields = [
            'attendance_screen_code',
            'attendance_screen_session_code',
            'attendance_screen_session_expires_at',
        ]

    def validate_subdomain(self, value):
        if value in (None, ''):
            return None
        normalized = value.strip().lower()
        from .models import validate_subdomain as _validate_subdomain
        try:
            _validate_subdomain(normalized)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages))
        duplicated = Organization.objects.filter(subdomain=normalized)
        if self.instance:
            duplicated = duplicated.exclude(pk=self.instance.pk)
        if duplicated.exists():
            raise serializers.ValidationError('Ese subdominio ya está en uso.')
        return normalized

    def validate(self, attrs):
        # El subdominio es obligatorio al crear (es la clave de acceso de la org).
        if self.instance is None and not attrs.get('subdomain'):
            raise serializers.ValidationError({'subdomain': 'El subdominio es obligatorio.'})
        return attrs

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
        return trial_signup_url(obj)


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
        # Desactivamos el UniqueTogetherValidator que DRF auto-genera a partir de
        # `unique_together = ('organization', 'name')`: ese validador exige
        # `organization` en el payload al crear y corre ANTES de `validate()`,
        # impidiendo que un gym_admin cree sucursales (la organización se asigna
        # en `validate()` desde el usuario). La unicidad se valida abajo,
        # case-insensitive y por organización.
        validators = []

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

        # Mover una sucursal de organización dejaría atrás a sus dependientes, que
        # conservan la organización vieja: el plan exclusivo pasaría a apuntar a una sede
        # de otro tenant (y `PlanSerializer.branch_name` filtraría ese nombre), y la org
        # destino quedaría sin poder borrarse por el RESTRICT de `Plan.branch`. Solo el
        # superadmin llega hasta acá: al gym_admin ya se le forzó su propia organización.
        if instance and instance.organization_id != organization.id:
            dependents = {
                'clases': instance.classes.exists(),
                'series': instance.class_templates.exists(),
                'planes exclusivos': instance.exclusive_plans.exists(),
                'reglas de pago': instance.payment_rules.exists(),
                'feriados': instance.holidays.exists(),
            }
            blocking = [label for label, exists in dependents.items() if exists]
            if blocking:
                raise serializers.ValidationError({
                    'organization': (
                        'No puedes mover esta sucursal a otra organización porque tiene '
                        f'{", ".join(blocking)} asociados, que quedarían apuntando a un '
                        'tenant distinto.'
                    )
                })

        return attrs


class RutField(serializers.CharField):
    """RUT chileno: normaliza a canónico (26711486-2) y valida el dígito
    verificador (Módulo 11). Rechaza '' y null (allow_blank/allow_null False)
    para que nunca se guarde vacío; sin RUT se omite el campo, no se blanquea."""

    def __init__(self, **kwargs):
        kwargs.setdefault('allow_blank', False)
        kwargs.setdefault('allow_null', False)
        kwargs.setdefault('max_length', 12)
        super().__init__(**kwargs)

    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        try:
            return clean_rut(value)
        except ValueError:
            raise serializers.ValidationError(
                'RUT inválido. Revisa el número y el dígito verificador.'
            )


class CustomUserSerializer(serializers.ModelSerializer):
    organization_detail = OrganizationSerializer(source='organization', read_only=True)
    branch_detail = BranchSerializer(source='branch', read_only=True)
    password = serializers.CharField(write_only=True, required=False, min_length=6)
    # Email es la clave de login (único por org). 'username' ya NO se expone: es un
    # identificador interno auto-generado (ver CustomUser.save()).
    email = serializers.EmailField(required=True)
    # RUT: obligatorio en el ALTA de usuarios de organización (ver validate()); en
    # edición el corte es 'por presencia' (required=False => un PATCH parcial de
    # sistema, ej. toggle is_active, no lo exige). Si viene, se valida y normaliza.
    rut = RutField(required=False)
    # Etiqueta legible del rol (única fuente: los choices de CustomUser.Role vía
    # get_role_display()). Solo lectura: nunca expone la key interna ('gym_admin').
    role_display = serializers.CharField(source='get_role_display', read_only=True)

    class Meta:
        model = User
        fields = [
            'id',
            'first_name',
            'last_name',
            'email',
            'is_active',
            'role',
            'role_display',
            'phone',
            'rut',
            'profile_image',
            'is_active_member',
            'organization',
            'branch',
            'organization_detail',
            'branch_detail',
            'password',
            # Estado del alumno para el banner de "clase de prueba gratis" (frontend).
            # SOLO LECTURA: este serializer también sirve al alta/edición de usuarios
            # del admin, y estos flags los mueve solo el backend (verificación de
            # email / reserva de la prueba). Un admin no puede negar la prueba ni
            # falsear la verificación marcándolos a mano.
            'email_verified',
            'has_used_trial',
        ]
        read_only_fields = ['email_verified', 'has_used_trial']

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

        # Email único POR organización (case-insensitive). Mensaje 400 limpio en vez
        # de un IntegrityError 500 de la constraint de DB. La org ya quedó finalizada
        # arriba (None para roles de plataforma, la del actor/payload para org-roles).
        email = attrs.get('email', getattr(self.instance, 'email', None))
        if email:
            target_org = attrs.get('organization', getattr(self.instance, 'organization', None))
            duplicated = User.objects.filter(email__iexact=email)
            duplicated = (
                duplicated.filter(organization=target_org)
                if target_org is not None
                else duplicated.filter(organization__isnull=True)
            )
            if self.instance:
                duplicated = duplicated.exclude(pk=self.instance.pk)
            if duplicated.exists():
                scope = 'esta organización' if target_org is not None else 'la plataforma'
                raise serializers.ValidationError(
                    {'email': f'Ya existe un usuario con ese email en {scope}.'}
                )

        # RUT: obligatorio en el ALTA de usuarios de ORGANIZACIÓN (los roles de
        # plataforma como superadmin no lo requieren). En edición no se exige
        # (corte por presencia): el RutField ya validó/normalizó si vino, y si no
        # vino queda intacto. Nunca se puede blanquear (allow_blank/allow_null False).
        if self.instance is None and effective_role in roles.ORG_ROLES and not attrs.get('rut'):
            raise serializers.ValidationError({'rut': 'El RUT es obligatorio.'})

        # Unicidad de RUT POR organización (mensaje 400 limpio en vez del
        # IntegrityError 500 de la constraint). Mismo RUT en otra org es válido;
        # sin RUT (None) no colisiona.
        rut = attrs.get('rut')
        if rut:
            target_org = attrs.get('organization', getattr(self.instance, 'organization', None))
            rut_dup = User.objects.filter(rut=rut)
            rut_dup = (
                rut_dup.filter(organization=target_org)
                if target_org is not None
                else rut_dup.filter(organization__isnull=True)
            )
            if self.instance:
                rut_dup = rut_dup.exclude(pk=self.instance.pk)
            if rut_dup.exists():
                raise serializers.ValidationError(
                    {'rut': 'Ya existe un usuario con ese RUT en esta organización.'}
                )

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


class SelfProfileSerializer(serializers.ModelSerializer):
    """Perfil editable por el PROPIO usuario (self-service PATCH /api/me/).

    Solo ``rut`` y ``phone`` son escribibles; rol, organización, is_active,
    is_active_member y email son de SOLO lectura: este endpoint jamás puede
    escalar privilegios ni cambiar de organización. Corte por presencia: el rut
    se valida/normaliza si viene, y no se puede blanquear (allow_blank/null False).
    """

    rut = RutField(required=False)
    role_display = serializers.CharField(source='get_role_display', read_only=True)

    class Meta:
        model = User
        fields = [
            'id', 'first_name', 'last_name', 'email', 'phone', 'rut',
            'role', 'role_display', 'is_active', 'is_active_member',
        ]
        read_only_fields = [
            'id', 'first_name', 'last_name', 'email',
            'role', 'role_display', 'is_active', 'is_active_member',
        ]

    def validate(self, attrs):
        rut = attrs.get('rut')
        if rut:
            user = self.instance
            rut_dup = User.objects.filter(rut=rut)
            rut_dup = (
                rut_dup.filter(organization=user.organization)
                if user.organization_id
                else rut_dup.filter(organization__isnull=True)
            )
            if rut_dup.exclude(pk=user.pk).exists():
                raise serializers.ValidationError(
                    {'rut': 'Ya existe un usuario con ese RUT en esta organización.'}
                )
        return attrs


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
        extra_kwargs = {
            'organization': {'required': False},
        }

    def validate(self, attrs):
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        instance = getattr(self, 'instance', None)
        # Para no-superadmin la organización la fuerza el ViewSet (perform_create/
        # update). Ignoramos cualquier 'organization' del payload para evitar
        # escritura cross-tenant.
        if user and user.is_authenticated and user.role != User.Role.SUPERADMIN:
            attrs.pop('organization', None)

        # Forzar la organización NO alcanzaba: la persona quedaba en la org del actor
        # pero colgada de una sucursal de OTRA. `Person.branch` es SET_NULL, así que el
        # borde también se cruza al borrar la sede ajena, y `branch_name` devolvía el
        # nombre de esa sede en la respuesta.
        organization = attrs.get('organization', getattr(instance, 'organization', None))
        if organization is None and user and user.is_authenticated:
            organization = user.organization
        branch = attrs.get('branch', getattr(instance, 'branch', None))
        if organization is None:
            # Superadmin creando sin `organization`: es rol de plataforma, no tiene org
            # propia de la cual derivarla. Sin este caso, con `branch` el check de abajo se
            # salteaba entero (la sucursal ajena entraba sin validar) y sin `branch` la
            # fila llegaba a la base y moría en el NOT NULL con un 500.
            raise serializers.ValidationError(
                {'organization': 'Debes indicar la organización de la persona.'}
            )
        if branch and branch.organization_id != organization.id:
            raise serializers.ValidationError(
                {'branch': 'La sucursal no pertenece a la organización de la persona.'}
            )
        return attrs


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

        # `Holiday.clean()` NORMALIZA además de validar (global ⇒ sin organización ni
        # sucursal; por organización ⇒ sin sucursal), pero lo hacía sobre esta instancia
        # desechable: `save()` usa `validated_data`, así que la normalización se perdía y
        # quedaban filas imposibles. Un global con organización se filtraba a todos los
        # tenants (`get_queryset` expone `Q(scope=GLOBAL)` sin filtro de organización), y
        # un feriado por organización con una sucursal ajena escribía una FK cross-tenant
        # que, por el CASCADE de `Holiday.branch`, le bloqueaba a la otra organización el
        # borrado de su propia sede. Se persiste lo que `clean()` decidió.
        attrs['organization'] = model_instance.organization
        attrs['branch'] = model_instance.branch
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
    # Elección del alumno de CON QUÉ membresía reservar (9.1), write-only. NO se expone
    # `student_plan` (el FK): ese campo se escribe SOLO a través de
    # `resolve_student_plan_for_reservation`, nunca por asignación directa del
    # serializer, porque saltarse esa función implica no validar pertenencia, saldo,
    # vigencia ni sucursal. `IntegerField` y no `PrimaryKeyRelatedField` a propósito: un
    # `PrimaryKeyRelatedField` con queryset acotado por organización sería un ORÁCULO (404
    # vs "no es tuyo" antes de llegar al servicio); sin queryset, cualquier id pasa tal
    # cual y la validación real la hace `resolve_student_plan_for_reservation`.
    student_plan_id = serializers.IntegerField(required=False, allow_null=True, write_only=True)

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
            'student_plan_id',
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

            # El simetrico para el ALUMNO: `Enrollment.student` es CASCADE sobre el
            # usuario, no sobre la organizacion, asi que un alumno movido conserva sus
            # reservas viejas y el solape las encontraba (reserva legitima bloqueada +
            # oraculo de la agenda ajena).
            overlapping_enrollments = Enrollment.objects.filter(
                student=student,
                status='active',
                gym_class__organization_id=gym_class.organization_id,
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

        # Tarea 11.A: el producto decidió PERMITIR que un mismo profesor tenga clases
        # solapadas (ej.: dicta dos disciplinas en paralelo y el alumno elige a cuál
        # ir). Acá vivía el bloqueo de solape profesor+horario; se eliminó a propósito.

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


class AttendanceChangeLogSerializer(serializers.ModelSerializer):
    student = serializers.IntegerField(source='attendance.student_id', read_only=True)
    student_name = serializers.SerializerMethodField()
    changed_by_username = serializers.CharField(source='changed_by.username', read_only=True)

    class Meta:
        model = AttendanceChangeLog
        fields = [
            'id',
            'attendance',
            'student',
            'student_name',
            'previous_status',
            'new_status',
            'changed_by',
            'changed_by_username',
            'changed_at',
            'source',
        ]

    def get_student_name(self, obj):
        student = obj.attendance.student
        full_name = f'{student.first_name} {student.last_name}'.strip()
        return full_name or student.username


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
    # Elección de CON QUÉ membresía se imputan las instancias de esta serie (10.x),
    # write-only y solo en el ALTA. Espejo exacto del campo homónimo de
    # `EnrollmentSerializer` (#9, serializers.py:699-707), incluidos sus dos motivos:
    #
    # * NO se expone el FK `student_plan` como escribible —sigue en `read_only_fields`—:
    #   ese campo se escribe SOLO a través de
    #   `resolve_student_plan_for_recurring_enrollment`, nunca por asignación directa del
    #   serializer, porque saltarse esa función es no validar organización, pertenencia,
    #   saldo ni vigencia.
    # * `IntegerField` y no `PrimaryKeyRelatedField`: un `PrimaryKeyRelatedField` con
    #   queryset acotado por organización sería un ORÁCULO (su error de "no existe" llegaría
    #   antes que la resolución y con otro formato). Sin queryset, el id pasa tal cual y la
    #   validación real —incluido el 404 uniforme— la hace el servicio.
    student_plan_id = serializers.IntegerField(required=False, allow_null=True, write_only=True)

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
            # Lectura únicamente (10.x): con qué membresía se re-imputan las instancias
            # futuras de esta recurrencia, si el alumno ya eligió una explícitamente
            # (NULL = sigue resolviendo el plan por instancia, comportamiento actual).
            # Va en `read_only_fields`, no declarado a mano: es exactamente lo que
            # `ModelSerializer` genera solo para cualquier FK ahí listada —un
            # `PrimaryKeyRelatedField(read_only=True)` que publica solo el id, sin
            # queryset, porque no hay nada que validar en un campo que el input no
            # puede tocar—. La ESCRITURA de la elección entra por `student_plan_id`
            # (write-only, declarado arriba) y solo en el alta: nunca por este campo.
            'student_plan',
            'student_plan_id',
        ]
        read_only_fields = ['created_by', 'created_at', 'updated_at', 'last_sync', 'student_plan']
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

        # `student_plan_id` SOLO gobierna el alta. En un update se descarta acá, y no más
        # abajo, por la trampa T1 de #9 (views.py:3280-3288): `student_plan` es un FK real,
        # así que un `student_plan_id` que sobreviva en `validated_data` se lo come
        # `ModelSerializer.update` como kwarg del FK y escribe la imputación sin pasar por
        # `resolve_student_plan_for_recurring_enrollment` —sin validar organización,
        # pertenencia, saldo ni vigencia—. Cambiar la elección de una serie YA creada es
        # otra operación (tiene que decidir qué hacer con las instancias ya imputadas), así
        # que hasta que exista se ignora en silencio, que es el lado cerrado.
        if instance is not None:
            attrs.pop('student_plan_id', None)

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
        """El ALTA aplica la regla de imputación del núcleo #9 (10.x).

        La resolución vive acá y no en `validate` a propósito: `create` corre dentro de
        `serializer.save()`, o sea DESPUÉS de la autorización de los dos puntos de entrada
        —`RecurringEnrollmentViewSet.perform_create` (views.py:3091-3101) y la acción
        `ClassTemplateViewSet.recurring-enroll` (views.py:2886-2910)—, y esa es la ÚNICA
        posición que respeta el orden de la lección 8.3: las guardas de pertenencia
        cross-org primero, el plan elegido después. En `validate` el lookup del id correría
        ANTES del `PermissionDenied` de `perform_create`, y ahí la diferencia entre 404 y
        403 le contaría a un actor de otra organización si ese id de membresía existe.
        Bonus: al estar en `create` la regla es una sola para los dos endpoints, sin
        duplicar nada en las views.

        El pop de `student_plan_id` es lo que impide que llegue a
        `RecurringEnrollment.objects.create(**validated_data)` como kwarg del FK (trampa T1
        de #9): lo que se graba es la instancia que devolvió el servicio, nunca el id crudo
        del payload.
        """
        chosen_plan_id = validated_data.pop('student_plan_id', None)
        student = validated_data.get('student')
        class_template = validated_data.get('class_template')
        try:
            validated_data['student_plan'] = resolve_student_plan_for_recurring_enrollment(
                student,
                # La organización de la SUSCRIPCIÓN, igual que el backfill de 0036: la
                # plantilla es la que ancla el tenant de la serie, no `student.organization`
                # (que puede cambiar después del alta).
                organization_id=class_template.organization_id,
                # La sede de la PLANTILLA: acá todavía no hay instancias que mirar, y es la
                # sede en la que se van a dictar todas.
                branch_id=class_template.branch_id,
                student_plan_id=chosen_plan_id,
            )
        except ReservationRuleError as exc:
            if exc.code == REASON_PLAN_NOT_FOUND:
                # 404 uniforme para "no existe" y "es de otra organización": ver el
                # docstring del servicio.
                raise NotFound(exc.message)
            # Reglas de negocio sobre un plan que ya se probó de esta organización. Mismo
            # formato que #9 en el wire de reservas (views.py:3332): `{'detail': mensaje}`.
            raise serializers.ValidationError({'detail': exc.message})
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
    branch_name = serializers.CharField(source='branch.name', read_only=True)

    class Meta:
        model = Plan
        fields = [
            'id',
            'organization',
            'organization_name',
            'branch',
            'branch_name',
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

        # `branch` define el alcance del plan (NULL = global, con sucursal = exclusivo).
        # Debe pertenecer a la MISMA organización que el plan: aceptar una sucursal ajena
        # ataría el plan de una org a la sede de otra (regla #1 de multitenancy).
        branch = attrs.get('branch', getattr(instance, 'branch', None))
        if branch and branch.organization_id != organization.id:
            raise serializers.ValidationError(
                {'branch': 'La sucursal no pertenece a la organización del plan.'}
            )

        return attrs


class ChargeLineItemSerializer(serializers.ModelSerializer):
    """Un concepto del desglose de cobro (#12), de solo lectura.

    Sin `organization`/`student_plan`/`created_by`: quien lee esto ya está autorizado a ver
    la membresía completa (viaja anidado dentro de `StudentPlanSerializer` o de la
    transacción que la activó), así que repetir esas FK acá sería ruido, no dato nuevo.
    """

    class Meta:
        model = ChargeLineItem
        fields = ['id', 'concept', 'amount']
        read_only_fields = fields


class StudentPlanSerializer(serializers.ModelSerializer):
    plan_name = serializers.CharField(source='plan.name', read_only=True)
    plan_type = serializers.CharField(source='plan.plan_type', read_only=True)
    user_name = serializers.SerializerMethodField()
    user_email = serializers.CharField(source='user.email', read_only=True)
    remaining_classes = serializers.SerializerMethodField()
    validity_status = serializers.SerializerMethodField()
    validity_status_label = serializers.SerializerMethodField()
    days_to_expiry = serializers.SerializerMethodField()
    expiry_alert_level = serializers.SerializerMethodField()
    expiry_alert_message = serializers.SerializerMethodField()
    enrollment_fee_status = serializers.SerializerMethodField()
    payment_status = serializers.SerializerMethodField()
    # `line_items`/`line_items_total` (#12): igual que `payment_status` arriba, es dato
    # financiero y hereda los mismos lectores — el monitor queda afuera por el check INLINE
    # de `memberships` (views.py ~3721-3722) y por el scope de rol del resto de superficies,
    # no por la clase de permiso. Cualquier superficie NUEVA que use este serializer tiene
    # que repetir ese corte a mano; no alcanza con confiar en `permission_classes`.
    line_items = ChargeLineItemSerializer(source='charge_line_items', many=True, read_only=True)
    line_items_total = serializers.SerializerMethodField()

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
            'validity_status_label',
            'days_to_expiry',
            'expiry_alert_level',
            'expiry_alert_message',
            'discount_percentage',
            'final_price',
            'enrollment_fee',
            'enrollment_fee_paid_at',
            'enrollment_fee_due_at',
            'enrollment_fee_status',
            'payment_status',
            'line_items',
            'line_items_total',
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
        """PINTA desde la fuente única (8.4), no decide: `self._state(obj).enrollment_fee_status`
        ya resolvió `waived`/`paid`/`pending`/`overdue`. Lo único que hace este método es
        adjuntar la fecha que corresponde a CADA status —presentación mecánica—, para no
        romper el dict de wire que el frontend ya lee (`enrollment_fee_status?.status`).
        """
        status = self._state(obj).enrollment_fee_status
        if status == 'paid':
            return {'status': status, 'paid_at': obj.enrollment_fee_paid_at.isoformat()}
        if status in ('overdue', 'pending'):
            due = obj.enrollment_fee_due_at
            return {'status': status, 'due_at': due.isoformat() if due else None}
        return {'status': status}

    def get_user_name(self, obj):
        if not obj.user:
            return ''
        full_name = f'{obj.user.first_name} {obj.user.last_name}'.strip()
        return full_name or obj.user.username

    def _state(self, obj):
        """Estado derivado de la membresia, resuelto por la FUENTE UNICA del predicado.

        Antes este serializer reimplementaba el predicado (fechas + `is_active`) en
        `get_validity_status` y de ahi derivaban los otros tres campos. Ahora lo resuelve
        `describe_student_plan`, la misma funcion que usan el roster y el validador de
        reservas, asi que las tres vistas no pueden volver a divergir.

        MEMOIZADO POR MEMBRESIA: siete campos derivados llaman aca, y desde que el estado
        incluye el eje de pago cada llamada recorre una FK inversa. Sin la cache, serializar
        una sola membresia sin prefetch —`my-plan`, la respuesta de `assign`— costaba siete
        consultas para responder exactamente lo mismo. Se cachea por `pk` y no por instancia
        porque con `many=True` DRF reusa UN serializer hijo para todas las filas; una fila sin
        `pk` (no guardada) no se cachea, para no colisionar todas bajo la misma clave `None`.
        """
        if obj.pk is None:
            return describe_student_plan(obj, timezone.localdate())
        if not hasattr(self, '_state_by_membership'):
            self._state_by_membership = {}
        if obj.pk not in self._state_by_membership:
            self._state_by_membership[obj.pk] = describe_student_plan(
                obj, timezone.localdate()
            )
        return self._state_by_membership[obj.pk]

    def _days_to_expiry(self, obj):
        # Lo calcula el estado, no este serializer: era el mismo `end_date - hoy` escrito dos
        # veces (aca y en `_plan_status_payload` del roster).
        return self._state(obj).days_to_expiry

    def get_validity_status(self, obj):
        # Sin proyección: 7.3 quitó el colapso de `exhausted` a `active` (8.4 después sacó
        # `enrollment_fee_unpaid` del vocabulario entero: la matrícula ya no es un estado de
        # vigencia). Los consumidores ya no traducen el string, pintan `validity_status_label`.
        return self._state(obj).status

    def get_validity_status_label(self, obj):
        # Paridad con `plan_status_label` del roster. Es la MISMA etiqueta de `_LABELS`, no
        # una segunda copia: sin este campo el frontend tendría que reimplementar el mapeo
        # estado→texto, que es justo la re-derivación que 7.3 elimina.
        return self._state(obj).label

    def get_days_to_expiry(self, obj):
        return self._days_to_expiry(obj)

    def get_expiry_alert_level(self, obj):
        # El mapeo (y los umbrales) viven en `core.services.plans._plan_alert`, la misma
        # fuente que consume el roster. Re-ramificar acá sobre el string era lo que hacía
        # que una membresía sin saldo saliera 'neutral' con mensaje de vigente.
        return self._state(obj).alert_level

    def get_expiry_alert_message(self, obj):
        return self._state(obj).alert_message

    def get_payment_status(self, obj):
        """Eje de pago (`paid`/`unpaid`/`free`), SEPARADO de `validity_status`.

        Sale de la misma fuente única que la vigencia, así que no hay una segunda regla que
        mantener sincronizada. Es de solo lectura por construcción —`SerializerMethodField`
        no acepta escritura—: el estado de pago se DERIVA de la contraparte financiera, y un
        campo escribible acá sería la forma de declararse pagado desde el front sin que nada
        lo respalde.

        Los lectores de este serializer son el propio alumno (`my-plan`, `my-memberships`) y
        gym_admin/superadmin (`assign`, `memberships`): `manager` no llega porque
        `FinancialResourcePermission` le niega el ViewSet entero, y `monitor` tampoco porque
        la acción `memberships` lo manda al 403 con un check INLINE. Ese check inline es la
        única barrera del monitor —la clase de permiso lo deja leer—, así que una acción GET
        nueva en este ViewSet que devuelva este serializer tiene que repetirlo: no alcanza
        con confiar en `permission_classes`. La redacción del monitor vive donde el monitor SÍ
        lee membresías: el roster de la clase (`_plan_status_payload` en views.py).
        """
        return self._state(obj).payment_status

    def get_line_items_total(self, obj):
        """Suma del desglose de conceptos extra (#12), en PYTHON y no `.aggregate()`.

        `obj.charge_line_items.all()` ya viene resuelta por el prefetch que arma la view
        (`# eje de pago + desglose sin N+1 por membresia`); un `.aggregate()` acá ignora esa
        cache y dispara una query nueva POR CADA membresía de una lista (el mismo N+1 que
        `origin_transactions`/`manual_payments` ya evitan). La suma vacía da `Decimal('0.00')`,
        nunca `None`.
        """
        total = sum((item.amount for item in obj.charge_line_items.all()), Decimal('0.00'))
        return str(total)


class ChargeLineItemInputSerializer(serializers.Serializer):
    """Entrada de UN concepto extra del desglose (#12). Valida FORMA, no pertenencia.

    Mismos topes que el modelo (`ChargeLineItem.concept`/`amount`): el concepto vacío o el
    monto que no alcanza el mínimo se cortan ACÁ, antes de tocar la base. No hay ningún id
    de recurso ajeno en este payload —concepto y monto son intrínsecos—, así que validar la
    forma antes de las guardas cross-org de la view no filtra nada de otro tenant (la
    lección de 8.3 aplica a validaciones que LEEN el objeto ajeno, y esta no lee ninguno).
    """

    concept = serializers.CharField(max_length=120)
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal('0.01'))


class StudentPlanAssignPaymentSerializer(serializers.Serializer):
    """Sub-payload de `payment` dentro de `assign` (8.3). Declara la vía financiera de la
    membresía nueva: `free` (beca total) o `manual` (cobro fuera de línea).

    `amount`/`reference` espejan a mano `ManualPaymentCreateSerializer` (mismo tope, mismo
    default): las dos rutas terminan en el mismo INSERT de `ManualPayment` vía
    `record_manual_payment`, así que el monto que no alcanza el mínimo o que falta para
    `manual` se corta ACÁ, antes de tocar la base — sin esperar a la regla cruzada de
    `StudentPlanAssignSerializer.validate()` que sí necesita ver el `plan`.

    `line_items` (#12) es el desglose OPCIONAL de conceptos extra de la venta ("pesas",
    "toalla"). Viaja dentro de `payment` porque es parte de la declaración financiera, y
    solo tiene sentido con `manual`: `free` es beca total y un concepto COBRADO encima
    sería la misma incoherencia que un `amount` (se rechaza, no se resuelve en silencio).
    La matrícula (8.4) NO viaja por acá: tiene su propio eje.
    """
    METHOD_FREE = 'free'
    METHOD_MANUAL = 'manual'
    METHOD_CHOICES = (
        (METHOD_FREE, 'Gratis (beca / giftcard)'),
        (METHOD_MANUAL, 'Pago manual (efectivo / transferencia)'),
    )

    method = serializers.ChoiceField(choices=METHOD_CHOICES)
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal('0.01'), required=False)
    reference = serializers.CharField(max_length=120, allow_blank=True, default='')
    # Cota de 50 por la misma clase de motivo que el tope de `student_plan` en
    # `ManualPaymentCreateSerializer`: sin límite, el payload es un vector de inserción
    # masiva. Un alta real trae un puñado de conceptos.
    line_items = ChargeLineItemInputSerializer(many=True, required=False, max_length=50)

    def validate(self, attrs):
        method = attrs.get('method')
        if method == self.METHOD_MANUAL:
            if attrs.get('amount') is None:
                raise serializers.ValidationError({
                    'amount': 'El monto es obligatorio para declarar un pago manual.',
                })
        else:
            # Free ES beca total, no un descuento parcial: un monto o una referencia de cobro
            # encima serían incoherentes con "no se cobró nada", así que no se resuelven en
            # silencio (ni ignorando el monto, ni sumándolo).
            if attrs.get('amount') is not None:
                raise serializers.ValidationError({
                    'amount': 'La vía "free" no admite un monto: es una beca total, no un pago parcial.',
                })
            if attrs.get('reference'):
                raise serializers.ValidationError({
                    'reference': 'La vía "free" no admite una referencia de pago.',
                })
            # `.get(...)` truthy y no `in attrs`: una lista vacía explícita no declara
            # ningún cobro, así que no hay incoherencia que rechazar.
            if attrs.get('line_items'):
                raise serializers.ValidationError({
                    'line_items': (
                        'La vía "free" no admite conceptos adicionales: es una beca total, '
                        'no un pago parcial.'
                    ),
                })
        return attrs


class StudentPlanAssignSerializer(serializers.Serializer):
    user = serializers.PrimaryKeyRelatedField(queryset=User.objects.filter(role=User.Role.STUDENT, is_active=True))
    plan = serializers.PrimaryKeyRelatedField(queryset=Plan.objects.filter(is_active=True))
    start_date = serializers.DateField()
    discount_percentage = serializers.FloatField(required=False, min_value=0, max_value=100)
    # REQUERIDO (8.3): ya no existe el alta sin declaración financiera. Antes de esto, un
    # `assign` sin contraparte de pago quedaba "vendido sin rastro" — ni ManualPayment ni
    # transacción de MercadoPago, y el eje de 8.2 lo derivaba `unpaid` para siempre.
    payment = StudentPlanAssignPaymentSerializer()

    def validate(self, attrs):
        plan = attrs['plan']
        student = attrs['user']
        if plan.organization_id != student.organization_id:
            raise serializers.ValidationError({'plan': 'El plan no pertenece a la organización del alumno.'})
        # La cantidad de clases (y si es ilimitado) se DERIVA del plan, no es editable en la asignación.
        attrs['total_classes'] = plan.total_classes
        attrs['unlimited_classes'] = plan.unlimited_classes

        payment = attrs['payment']
        if payment['method'] == StudentPlanAssignPaymentSerializer.METHOD_FREE:
            # `initial_data` (no `attrs`) es la única forma de distinguir "no vino
            # `discount_percentage`" de "vino con el mismo valor que el default": el campo no
            # tiene `default`, así que sin mirar el payload crudo un descuento explícito
            # convivía en silencio con una vía que ya promete 100% — dos declaraciones
            # distintas del mismo 0 que además podrían no coincidir (p. ej. `discount_percentage: 50`
            # con `payment.method: free`).
            if 'discount_percentage' in self.initial_data:
                raise serializers.ValidationError({
                    'discount_percentage': (
                        'No se puede combinar con `payment.method: "free"`: esa vía ya fija '
                        'el descuento en 100%.'
                    ),
                })
            attrs['discount_percentage'] = 100
        else:
            discount = attrs.get('discount_percentage')
            if discount is None:
                discount = plan.discount_percentage or 0
            attrs['discount_percentage'] = discount
            # La invariante `manual ⟹ final_price > 0` (FREE gana sobre PAID en
            # `_payment_status`) NO se valida acá: este `validate()` corre en
            # `serializer.is_valid()`, que en la view pasa ANTES de las guardas cross-org. Si
            # el `plan` es de OTRA organización, comparar su precio acá filtraría por el
            # status code (400 "la venta queda en $0" vs 403 de la guarda) si ese plan ajeno
            # vale 0 o no -un oráculo de precios de otro tenant, autoincrementales y
            # adivinables-. La guarda vive en la view, DESPUÉS de confirmar que el plan es
            # del actor.

        attrs['end_date'] = attrs['start_date'] + timedelta(days=max(plan.duration_days - 1, 0))
        return attrs


class ManualPaymentCreateSerializer(serializers.Serializer):
    """Entrada del registro de un cobro fuera de línea. Valida FORMA, no pertenencia.

    `student_plan` es un ENTERO y no un `PrimaryKeyRelatedField` a propósito: si el
    serializer resolviera la FK contra `StudentPlan.objects.all()`, una membresía de otra
    organización pasaría la validación y moriría después en la view con 404, mientras que un
    id inexistente moriría acá con 400 — dos códigos distintos para dos casos que tienen que
    ser INDISTINGUIBLES, o el endpoint queda de oráculo de membresías ajenas. La resolución
    la hace la view DENTRO del scope de la organización del actor.

    `organization`, `recorded_by` y `recorded_at` no existen acá: se estampan en el servidor.
    Un campo de organización en la entrada sería exactamente el payload que la regla #1 del
    backend prohíbe.
    """

    # Cota superior por el mismo motivo que `_as_id_list` en views.py:189-193: fuera del
    # rango de bigint, el `filter(pk=...)` revienta en PostgreSQL con un 500 que SQLite no
    # reproduce, así que la suite no lo detectaría.
    student_plan = serializers.IntegerField(min_value=1, max_value=2 ** 63 - 1)
    amount = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=Decimal('0.01'),
    )
    reference = serializers.CharField(max_length=120, allow_blank=True, default='')


class ManualPaymentSerializer(serializers.ModelSerializer):
    """Respuesta del POST. MÍNIMA a propósito.

    No incluye `payment_status` y no anida `StudentPlanSerializer`. La trampa está escrita en
    views.py:551-561: el corte que le oculta el eje financiero al monitor es un check INLINE,
    NO la clase de permiso, así que cada superficie nueva que publique estado de pago tiene
    que repetirlo a mano. La forma barata de no equivocarse es no publicarlo: quien registró
    el pago ya sabe qué registró, y el estado de la membresía se lee donde ya se leía
    (`my-memberships`, `/api/plans/{id}/memberships/`, el roster).

    Tampoco viaja `recorded_by`: es el propio actor, o sea información que el cliente ya
    tiene. Menos campos, menos superficie.
    """

    class Meta:
        model = ManualPayment
        fields = ['id', 'student_plan', 'amount', 'reference', 'recorded_at']
        read_only_fields = fields


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
        elif payment_type in (
            TeacherPaymentRule.PaymentType.PER_ENROLLED,
            TeacherPaymentRule.PaymentType.PER_HOUR,
            TeacherPaymentRule.PaymentType.MONTHLY_FIXED,
        ):
            attrs['calculation_base'] = None
            if amount is None or float(amount) < 0:
                raise serializers.ValidationError({'amount': 'El monto debe ser mayor o igual a 0.'})
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
    sin exponer el token ni datos internos. Incluye la URL pública por subdominio
    para que el redirect de links viejos sepa a dónde saltar."""

    public_registration_url = serializers.SerializerMethodField()

    class Meta:
        model = Organization
        fields = ['name', 'slug', 'logo', 'primary_color', 'secondary_color', 'public_registration_url']

    def get_public_registration_url(self, obj):
        return trial_signup_url(obj)


class PublicRegistrationSerializer(serializers.Serializer):
    """Registro público de un prospecto. NO incluye role ni organization:
    el servidor los fija desde el token de invitación. Inyección imposible."""

    first_name = serializers.CharField(max_length=150)
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)
    phone = serializers.CharField(max_length=40, required=False, allow_blank=True)

    def validate_email(self, value):
        # Email único POR organización: la org viene del contexto (el slug de la
        # invitación, fijado server-side en PublicRegisterView).
        normalized = value.strip().lower()
        organization = self.context.get('organization')
        duplicated = User.objects.filter(email__iexact=normalized)
        duplicated = (
            duplicated.filter(organization=organization)
            if organization is not None
            else duplicated.filter(organization__isnull=True)
        )
        if duplicated.exists():
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


class PaymentAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentAccount
        fields = ['provider', 'status', 'provider_user_id', 'is_sandbox',
                  'connected_at', 'token_expires_at']
        read_only_fields = fields


class PaymentCheckoutRequestSerializer(serializers.Serializer):
    plan_id = serializers.IntegerField(required=False)
    target_student_plan_id = serializers.IntegerField(required=False)

    def validate(self, attrs):
        if bool(attrs.get('plan_id')) == bool(attrs.get('target_student_plan_id')):
            raise serializers.ValidationError('Indica exactamente uno: plan_id o target_student_plan_id.')
        return attrs


class PaymentTransactionStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentTransaction
        fields = ['id', 'status', 'status_detail', 'amount', 'currency']
        read_only_fields = fields


class PaymentTransactionAdminSerializer(serializers.ModelSerializer):
    """Vista de solo lectura de una PaymentTransaction para el panel del gym_admin.
    Incluye datos del alumno y si la transacción activó un StudentPlan."""
    student_name = serializers.SerializerMethodField()
    student_email = serializers.EmailField(source='user.email', read_only=True)
    student_phone = serializers.CharField(source='user.phone', read_only=True)
    plan_name = serializers.CharField(source='plan.name', read_only=True, allow_null=True)
    concept = serializers.SerializerMethodField()
    activated_student_plan = serializers.SerializerMethodField()
    # Desglose (#12) de la membresía que esta transacción activó. Hoy MercadoPago no genera
    # `ChargeLineItem` (el desglose nace solo del alta MANUAL vía `assign`), así que esto sale
    # `[]` casi siempre — se expone igual para que el desglose del panel de transacciones
    # tenga UNA forma de wire, no dos. `concept` (arriba) queda intacto por compat con el
    # front actual hasta que migre a `line_items`.
    line_items = serializers.SerializerMethodField()

    class Meta:
        model = PaymentTransaction
        fields = [
            'id', 'created_at', 'processed_at',
            'status', 'status_detail',
            'amount', 'plan_amount', 'enrollment_fee_amount', 'currency',
            'student_name', 'student_email', 'student_phone',
            'plan_name', 'concept', 'line_items',
            'activated_student_plan', 'student_plan',
        ]
        read_only_fields = fields

    def get_student_name(self, obj):
        full_name = f'{obj.user.first_name} {obj.user.last_name}'.strip()
        return full_name or obj.user.username

    def get_concept(self, obj):
        if obj.plan_id:
            return f'Plan: {obj.plan.name}'
        if obj.target_student_plan_id:
            return 'Matrícula'
        return '—'

    def get_activated_student_plan(self, obj):
        return bool(obj.student_plan_id)

    def get_line_items(self, obj):
        # El corte por organización NO es redundante: seguir `obj.student_plan` confía en
        # la invariante `tx.organization == student_plan.organization`, que hoy se cumple
        # en ambos caminos de escritura pero no la garantiza ninguna constraint (un plan
        # movido de org por superadmin + checkout de matrícula la rompe sin tocar código:
        # `create_checkout` valida el JOIN `sp.plan.organization`, no la COLUMNA
        # `sp.organization_id`). Es el patrón documentado "FK propia sin organización",
        # cortado acá en la lectura: ante la incoherencia, el desglose ajeno no viaja.
        # `student_plan` viene por `select_related` y los items por prefetch, así que la
        # comparación no agrega queries.
        if obj.student_plan_id is None or obj.student_plan.organization_id != obj.organization_id:
            return []
        return ChargeLineItemSerializer(obj.student_plan.charge_line_items.all(), many=True).data

