from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import CustomUser


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    list_display = ('username', 'email', 'role', 'organization', 'branch', 'is_active_member', 'is_staff')
    list_filter = ('role', 'organization', 'branch', 'is_active', 'is_active_member')
    fieldsets = UserAdmin.fieldsets + (
        (
            'TYMRO',
            {
                'fields': (
                    'role',
                    'organization',
                    'branch',
                    'phone',
                    'profile_image',
                    'is_active_member',
                )
            },
        ),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        (
            'TYMRO',
            {
                'fields': (
                    'role',
                    'organization',
                    'branch',
                    'phone',
                    'profile_image',
                    'is_active_member',
                )
            },
        ),
    )
