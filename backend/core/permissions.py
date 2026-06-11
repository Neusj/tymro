from rest_framework.permissions import BasePermission, SAFE_METHODS

from accounts import roles
from accounts.models import CustomUser


class IsSuperAdmin(BasePermission):
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role == CustomUser.Role.SUPERADMIN
        )


class IsSuperAdminOrGymAdmin(BasePermission):
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role in (CustomUser.Role.SUPERADMIN, CustomUser.Role.GYM_ADMIN)
        )


class OperationalResourcePermission(BasePermission):
    """Recursos operativos restringidos a staff (tipos de clase, disciplinas, festivos):
    escritura para superadmin/gym_admin/manager; lectura además para monitor.
    teacher/student siguen sin acceso (igual que el IsSuperAdminOrGymAdmin anterior)."""

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if request.method in SAFE_METHODS:
            return roles.can_manage_operational(user) or roles.is_monitor(user)
        return roles.can_manage_operational(user)


class FinancialResourcePermission(BasePermission):
    """Pagos a profesores y planes (grupo b financiero): manager NUNCA (403, ni lectura);
    monitor solo lectura; escritura superadmin/gym_admin. Lectores adicionales
    (teacher en pagos, student en planes) pasan has_permission y el get_queryset scopea."""

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if roles.is_manager(user):
            return False
        if request.method in SAFE_METHODS:
            return True
        return roles.can_manage_admin(user)
