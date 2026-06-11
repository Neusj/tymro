"""Única fuente de verdad de la jerarquía de roles: qué rol puede asignar/gestionar quién.

Importable desde core.views y core.serializers sin ciclos: accounts no importa core
a nivel de módulo (las FKs de CustomUser usan referencias lazy 'core.Organization').

Regla central: la misma matriz gobierna CREAR usuarios con un rol y EDITAR/BORRAR
usuarios existentes (un actor gestiona a un usuario si instance.role está en
assignable_roles(actor)).
"""
from accounts.models import CustomUser

Role = CustomUser.Role

# Roles de plataforma: nunca asignables por actores de organización (barrera dura).
PLATFORM_ROLES = frozenset({Role.SUPERADMIN})

# Roles de organización.
ORG_ROLES = frozenset({Role.GYM_ADMIN, Role.MANAGER, Role.MONITOR, Role.TEACHER, Role.STUDENT})

# Roles de organización con capacidad administrativa sobre usuarios:
# organización forzada a la propia en escrituras y listado org-wide en UserViewSet.
ORG_ADMIN_ROLES = frozenset({Role.GYM_ADMIN, Role.MANAGER})

# Roles con escritura sobre recursos admin (grupo b): sucursales, pagos, planes.
# Manager queda EXCLUIDO a propósito.
ADMIN_WRITE_ROLES = PLATFORM_ROLES | frozenset({Role.GYM_ADMIN})

_ASSIGNABLE_BY_ROLE = {
    Role.SUPERADMIN: PLATFORM_ROLES | ORG_ROLES,
    Role.GYM_ADMIN: ORG_ROLES,
    Role.MANAGER: frozenset({Role.TEACHER, Role.STUDENT}),
    Role.MONITOR: frozenset(),
    Role.TEACHER: frozenset(),
    Role.STUDENT: frozenset(),
}


def role_of(user):
    """Rol del usuario, o None si es None, anónimo o no tiene rol."""
    if user is None or not getattr(user, 'is_authenticated', False):
        return None
    return getattr(user, 'role', None)


def assignable_roles_for_role(role):
    """Matriz pura por rol. Roles desconocidos o None -> conjunto vacío."""
    return _ASSIGNABLE_BY_ROLE.get(role, frozenset())


def assignable_roles(user):
    """Roles que `user` puede asignar (y, por la regla central, gestionar)."""
    return assignable_roles_for_role(role_of(user))


def can_assign(actor, target_role):
    """True si `actor` puede asignar `target_role` (crear) o gestionar a un
    usuario existente con ese rol (editar/borrar).

    Barrera de seguridad independiente de la matriz: un actor cuyo rol no es
    de plataforma JAMÁS puede asignar un rol de PLATFORM_ROLES, aunque la
    matriz se modificara por error.
    """
    if target_role in PLATFORM_ROLES and role_of(actor) not in PLATFORM_ROLES:
        return False
    return target_role in assignable_roles(actor)


def is_org_admin(user):
    """Actor de organización con capacidad administrativa (gym_admin/manager)."""
    return role_of(user) in ORG_ADMIN_ROLES


def is_manager(user):
    return role_of(user) == Role.MANAGER


def is_monitor(user):
    return role_of(user) == Role.MONITOR


def can_manage_operational(user):
    """Escritura sobre recursos operativos (grupo a): superadmin, gym_admin, manager."""
    role = role_of(user)
    return role in PLATFORM_ROLES or role in ORG_ADMIN_ROLES


def can_manage_admin(user):
    """Escritura sobre recursos admin (grupo b): superadmin, gym_admin (NO manager)."""
    return role_of(user) in ADMIN_WRITE_ROLES


# Labels canónicos (español), derivados del modelo — única fuente de etiquetas.
ROLE_LABELS = dict(Role.choices)


def assignable_role_choices(user):
    """Lista [{'value', 'label'}] de roles asignables por `user`, en el orden
    canónico de declaración de Role (el frozenset de la matriz no tiene orden).
    Sin roles asignables -> lista vacía."""
    assignable = assignable_roles(user)
    return [
        {'value': value, 'label': label}
        for value, label in Role.choices
        if value in assignable
    ]
