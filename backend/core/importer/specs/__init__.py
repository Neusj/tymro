"""Importa cada módulo de entidad para que su spec quede registrado.

El orden de import define el orden del catálogo (y del selector en la UI):
primero las entidades sin dependencias, en el orden sugerido de carga.
"""
from . import branches  # noqa: F401
from . import disciplines  # noqa: F401
from . import class_types  # noqa: F401
from . import plans  # noqa: F401
from . import users  # noqa: F401
from . import memberships  # noqa: F401
from . import class_templates  # noqa: F401
