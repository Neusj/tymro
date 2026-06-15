from django.contrib import admin
from .models import (
    Attendance,
    Branch,
    ClassTemplate,
    ClassType,
    ConsumptionLog,
    Enrollment,
    GymClass,
    Holiday,
    MembershipPlan,
    Organization,
    Plan,
    Person,
    RecurringEnrollment,
    StudentPlan,
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
admin.site.register(TeacherPaymentRule)
admin.site.register(TeacherPaymentRecord)


@admin.register(TrialFollowupConfiguration)
class TrialFollowupConfigurationAdmin(admin.ModelAdmin):
    list_display = ('organization', 'is_active', 'minutes_after_class_end')
    list_filter = ('is_active',)
    search_fields = ('organization__name',)
    readonly_fields = ('created_at', 'updated_at')
