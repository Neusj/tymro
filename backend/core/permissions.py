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


class ReportPermission(BasePermission):
    """Reportería del gimnasio (P3.4): EXCLUSIVA del `gym_admin` sobre su propia organización.

    Es la superficie más chica posible, y cada exclusión es deliberada:

    * **`manager` NO**, ni de lectura. Es la misma línea que ya traza
      `FinancialResourcePermission` para pagos y planes: el manager gestiona el roster y la
      operación, no la plata. Un reporte de ingresos es plata AGREGADA, o sea más sensible
      que una fila suelta, así que no puede ser más laxo que el recurso del que sale.
    * **`superadmin` TAMPOCO**, y esto no es un olvido: es el mismo criterio que
      `PaymentTransactionListView` (views_payments.py). El superadmin administra la
      plataforma; darle el reporte de ingresos sería darle la facturación de todos los
      gimnasios en un endpoint, que es exactamente lo que ese precedente evita. Sin
      `organization_id` propia tampoco tendría alcance que scopear.
    * **`monitor`/`teacher`/`student`**: fuera por lo mismo.
    * **La ocupación viaja con la misma llave** aunque no sea dinero. Es una decisión de
      producto (dato de gestión, y de paso el gancho de marketing sobre horarios que nadie
      toma), no una consecuencia técnica: si mañana el manager tiene que ver ocupación, se
      abre con una permission propia para ese endpoint y no relajando esta.

    Solo `has_permission`: el aislamiento por organización NO vive acá. Lo hace
    `views_reports._report_scope` estampando `request.user.organization_id` en el
    `ReportScope`, que es el único origen de la organización de todo reporte.
    """

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and user.role == CustomUser.Role.GYM_ADMIN
            and user.organization_id
        )


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
