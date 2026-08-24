from django.contrib import admin
from .models import (
    Attendance,
    Branch,
    ChargeLineItem,
    ClassTemplate,
    ClassType,
    ConsumptionLog,
    Enrollment,
    GymClass,
    Holiday,
    ManualPayment,
    MembershipPlan,
    Organization,
    OrganizationExpiryNotificationConfig,
    PersonalizedClassSession,
    Plan,
    PlanExpiryNotification,
    Person,
    PushNotification,
    PushPreference,
    PushSubscription,
    RecurringEnrollment,
    StudentPlan,
    StudentPlanFreeze,
    TeacherPaymentRecord,
    TeacherPaymentRule,
    TrialFollowupConfiguration,
)

admin.site.register(Organization)
admin.site.register(Branch)
admin.site.register(Person)
admin.site.register(ClassType)
admin.site.register(ClassTemplate)
admin.site.register(GymClass)
admin.site.register(Holiday)
admin.site.register(Enrollment)
admin.site.register(RecurringEnrollment)
admin.site.register(Attendance)
admin.site.register(MembershipPlan)
admin.site.register(Plan)
admin.site.register(StudentPlan)
admin.site.register(ConsumptionLog)
admin.site.register(PersonalizedClassSession)
admin.site.register(TeacherPaymentRule)
admin.site.register(TeacherPaymentRecord)


@admin.register(PushPreference)
class PushPreferenceAdmin(admin.ModelAdmin):
    list_display = ('user', 'organization', 'push_enabled', 'prompt_status', 'last_profile_reminder_sent_on')
    list_filter = ('push_enabled', 'prompt_status', 'organization')
    search_fields = ('user__email', 'user__username')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(PushSubscription)
class PushSubscriptionAdmin(admin.ModelAdmin):
    list_display = ('user', 'organization', 'is_active', 'created_at', 'deactivated_at')
    list_filter = ('is_active', 'organization')
    search_fields = ('user__email', 'endpoint')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(PushNotification)
class PushNotificationAdmin(admin.ModelAdmin):
    list_display = ('event_type', 'user', 'organization', 'status', 'sent_count', 'sent_at', 'created_at')
    list_filter = ('event_type', 'status', 'organization')
    search_fields = ('user__email', 'dedupe_key', 'title')
    readonly_fields = (
        'organization', 'user', 'event_type', 'dedupe_key', 'title', 'body', 'data',
        'status', 'sent_at', 'sent_count', 'error', 'created_at', 'updated_at',
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(StudentPlanFreeze)
class StudentPlanFreezeAdmin(admin.ModelAdmin):
    list_display = (
        'student_plan', 'organization', 'status', 'start_date', 'planned_end_date',
        'actual_end_date', 'extension_days', 'created_by', 'ended_by',
    )
    list_filter = ('status', 'organization')
    search_fields = ('student_plan__user__username', 'student_plan__user__email', 'reason')
    readonly_fields = (
        'student_plan', 'organization', 'start_date', 'planned_end_date',
        'actual_end_date', 'reason', 'status', 'created_by', 'ended_by', 'ended_at',
        'extension_days', 'cancelled_future_enrollments', 'created_at', 'updated_at',
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(TrialFollowupConfiguration)
class TrialFollowupConfigurationAdmin(admin.ModelAdmin):
    list_display = ('organization', 'is_active', 'minutes_after_class_end')
    list_filter = ('is_active',)
    search_fields = ('organization__name',)
    readonly_fields = ('created_at', 'updated_at')


@admin.register(OrganizationExpiryNotificationConfig)
class OrganizationExpiryNotificationConfigAdmin(admin.ModelAdmin):
    """Único lugar donde se encienden los avisos de vencimiento (7.4: sin API ni UI).

    El `ModelForm` corre `full_clean()`, así que la validación de
    `reminder_days_before` —enteros positivos, sin repetir, dentro del tope— aplica acá.
    """

    list_display = ('organization', 'reminder_days_before', 'send_expired_notice')
    list_filter = ('send_expired_notice',)
    search_fields = ('organization__name',)
    readonly_fields = ('created_at', 'updated_at')


@admin.register(PlanExpiryNotification)
class PlanExpiryNotificationAdmin(admin.ModelAdmin):
    """Bitácora de avisos enviados. Solo lectura: borrar una fila REENVÍA el correo.

    Es el registro de idempotencia del job, no un log decorativo; por eso no se puede
    crear ni editar desde acá.
    """

    list_display = ('student_plan', 'organization', 'kind', 'days_before', 'sent_at')
    list_filter = ('kind', 'organization')
    search_fields = ('student_plan__user__username', 'student_plan__user__email')
    readonly_fields = (
        'student_plan', 'organization', 'kind', 'days_before',
        'sent_at', 'created_at', 'updated_at',
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        # Sin esto el changelist ofrece "Eliminar los objetos seleccionados", y borrar una
        # fila de acá REENVÍA el correo que representa.
        return False


@admin.register(ManualPayment)
class ManualPaymentAdmin(admin.ModelAdmin):
    """Libro de cobros fuera de línea. SOLO LECTURA: la única escritura es el endpoint.

    Los tres permisos cerrados, y cada uno por su motivo:

    * `delete` — lección 7.4 (`PlanExpiryNotificationAdmin`), acá con plata de por medio.
      Borrar una fila devuelve la membresía de `paid` a `unpaid` sin dejar rastro de que
      alguna vez se cobró, y el changelist ofrece la acción masiva por defecto.
    * `add` — el formulario del admin deja elegir `organization` y `student_plan` por
      separado: es exactamente la fila cross-tenant que el endpoint prohíbe, y encima sin
      `recorded_by`. `clean()` impide la incoherencia, pero la organización CORRECTA no la
      puede adivinar un formulario: sale del actor que recibió la plata.
    * `change` — editar el importe o repuntar `student_plan` mueve un cobro de una membresía
      a otra. Corregir un pago mal registrado tiene semántica propia (anular + registrar de
      nuevo) y 8.2 no la define; hacerlo por acá lo dejaría sin historial.

    Queda como lo que es: una vista de auditoría.
    """

    list_display = (
        'student_plan', 'organization', 'amount', 'reference', 'recorded_by', 'recorded_at',
    )
    list_filter = ('organization',)
    search_fields = (
        'reference', 'student_plan__user__username', 'student_plan__user__email',
    )
    readonly_fields = (
        'organization', 'student_plan', 'amount', 'reference', 'recorded_by',
        'recorded_at', 'created_at', 'updated_at',
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ChargeLineItem)
class ChargeLineItemAdmin(admin.ModelAdmin):
    """Desglose de conceptos extra cobrados junto a una membresía. SOLO LECTURA.

    Misma lección que `ManualPaymentAdmin`: con plata de por medio, borrar o editar una
    fila de acá cambiaría el desglose del cobro sin dejar rastro.
    """

    list_display = (
        'student_plan', 'organization', 'concept', 'amount', 'created_by', 'created_at',
    )
    list_filter = ('organization',)
    search_fields = (
        'concept', 'student_plan__user__username', 'student_plan__user__email',
    )
    readonly_fields = (
        'organization', 'student_plan', 'concept', 'amount', 'created_by',
        'created_at', 'updated_at',
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
