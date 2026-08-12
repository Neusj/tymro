"""Contrato declarativo del importador de datos.

Cada entidad importable se describe con un ``EntityImportSpec``: el motor
(``engine.py``) no conoce ningún modelo concreto, solo interpreta specs.
Agregar una entidad nueva = declarar un spec en ``specs/`` y registrarlo;
ni el motor ni el frontend cambian.

Todo lo visible para el usuario final (labels, instrucciones, mensajes) va en
español natural; ``attr`` es el atributo técnico del modelo y nunca se muestra.
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class FKSpec:
    """Cómo resolver una FK a partir de un texto escrito en la planilla.

    La resolución SIEMPRE se acota a la organización del actor (salvo
    ``org_field=''`` para modelos globales, que hoy no existen en TYMRO).
    """

    model: str                          # 'core.Branch', 'accounts.CustomUser' (lazy via apps.get_model)
    lookup_field: str = 'name'          # 'email' para FK a usuarios
    org_field: str = 'organization'     # obligatorio: el registry rechaza FK sin scoping de org
    filters: dict = field(default_factory=dict)   # ej. {'role': 'teacher'}
    reference_label: str = ''           # cómo se llama el valor en mensajes/Referencias ("sucursal")
    # Desambiguación con otras columnas de la fila: ((attr_de_la_fila, lookup_del_modelo), ...).
    # Si la columna viene con valor, se suma al filtro (ej. plan por nombre + tipo).
    disambiguators: tuple = ()
    ambiguity_hint: str = ''            # se anexa al error de ambigüedad ("Completa 'Tipo de plan'...")


@dataclass(frozen=True)
class FieldSpec:
    """Una columna de la plantilla mapeada a un atributo del modelo."""

    attr: str                           # atributo técnico del modelo
    label: str                          # encabezado en español de la plantilla
    kind: str = 'string'                # string|text|int|decimal|bool|date|time|email|choice|fk
    required: bool = False
    example: str = ''                   # valor para la fila de ejemplo de la plantilla
    max_length: int | None = None
    choices: tuple = ()                 # ((etiqueta_es, valor_db), ...) para vocabularios fijos
    fk: FKSpec | None = None            # solo si kind == 'fk'
    default: object = None              # se aplica si la celda viene vacía y no es required
    help_text: str = ''                 # descripción para Instrucciones y catálogo
    aliases: tuple = ()                 # encabezados legacy aceptados al parsear archivos existentes
    updatable: bool = False             # upsert: si existe el registro, este campo se actualiza


@dataclass(frozen=True)
class EntityImportSpec:
    slug: str                           # segmento de URL: /api/imports/<slug>/...
    label: str                          # 'Disciplinas'
    description: str                    # frase corta para el selector del frontend
    model: str                          # 'core.Discipline' (lazy via apps.get_model)
    fields: tuple = ()
    natural_key: tuple = ()             # attrs que definen duplicado (archivo y BD)
    # Campo de organización del modelo. Admite rutas con '__' para modelos sin
    # organization propia, acotados vía FK padre (ej. 'user__organization' en
    # StudentPlan); en ese caso el spec DEBE usar build_instance.
    org_field: str = 'organization'
    dedup_filters: dict = field(default_factory=dict)  # filtro extra del dedup contra BD (ej. {'is_active': True})
    # Upsert: atributos del MODELO actualizables que no son columna declarada
    # (ej. derivados como 'is_active', 'total_classes'). Junto con los FieldSpec
    # marcados updatable=True forman el whitelist que el motor compara y aplica.
    updatable_fields: tuple = ()
    dependencies: tuple = ()            # slugs que conviene importar antes (informativo en UI)
    instructions: tuple = ()            # bullets en español (hoja Instrucciones y UI)
    max_rows: int = 1000
    # Hooks para entidades de fases futuras; el motor los invoca si existen:
    row_validators: tuple = ()          # Callable(values: dict, ctx) -> list[RowError]
    expand_rows: object = None          # Callable(row_number, raw) -> [(row_number, raw)] para fan-out
    derive: object = None               # Callable(values, ctx) -> dict de kwargs extra (ej. classes_used)
    build_instance: object = None       # Callable(values, organization) -> instancia sin guardar
    extra_permission: object = None     # Callable(user) -> bool, además del permiso base
    post_commit: object = None          # Callable(instances, organization, actor) tras guardar todo,
                                        # DENTRO de la transacción (ej. generar clases del horario)

    def field_by_attr(self, attr):
        for f in self.fields:
            if f.attr == attr:
                return f
        raise KeyError(attr)

    @property
    def is_upsert(self):
        """True si la entidad activa upsert (algún campo updatable o updatable_fields)."""
        return any(f.updatable for f in self.fields) or bool(self.updatable_fields)


@dataclass
class RowError:
    """Error de una fila: número de fila Excel + columna (label español) + motivo."""

    row: int
    column: str        # '' = error de la fila completa
    message: str       # español natural, apto para usuario no técnico


# Estados posibles de una fila tras validar.
STATUS_OK = 'ok'
STATUS_DUP_FILE = 'duplicado_archivo'
STATUS_DUP_DB = 'duplicado_existente'
STATUS_ERROR = 'error'
STATUS_UPDATED = 'actualizado'      # upsert: existe y hay cambios en campos del whitelist
STATUS_UNCHANGED = 'sin_cambios'    # upsert: existe pero ningún campo del whitelist cambió


@dataclass
class RowResult:
    row: int
    status: str
    values: dict                        # {label_es: valor mostrable} para el preview
    errors: list = field(default_factory=list)
    note: str = ''
    cleaned: dict = field(default_factory=dict)   # {attr: valor coercionado} (uso interno del motor)
    diff: dict = field(default_factory=dict)      # upsert: {label_es: {'from': v, 'to': v}} en STATUS_UPDATED


@dataclass
class ImportReport:
    rows: list = field(default_factory=list)

    @property
    def total_rows(self):
        return len(self.rows)

    def _count(self, status):
        return sum(1 for r in self.rows if r.status == status)

    @property
    def valid(self):
        return self._count(STATUS_OK)

    @property
    def duplicates_in_file(self):
        return self._count(STATUS_DUP_FILE)

    @property
    def duplicates_in_db(self):
        return self._count(STATUS_DUP_DB)

    @property
    def updated(self):
        return self._count(STATUS_UPDATED)

    @property
    def unchanged(self):
        return self._count(STATUS_UNCHANGED)

    @property
    def error_count(self):
        return self._count(STATUS_ERROR)

    @property
    def can_commit(self):
        """True si NINGUNA fila tiene errores de validación. OJO: con import
        parcial NO es el gate de "se puede importar" — un archivo con errores
        igual importa sus filas válidas. El gate real es ``valid + updated > 0``
        (en el front: ``will_create + updated``). Esta señal indica "archivo
        completamente limpio"."""
        return self.error_count == 0

    def summary(self):
        return {
            'total_rows': self.total_rows,
            'valid': self.valid,
            'duplicates_in_file': self.duplicates_in_file,
            'duplicates_in_db': self.duplicates_in_db,
            'errors': self.error_count,
            'will_create': self.valid,
            'updated': self.updated,
            'unchanged': self.unchanged,
        }

    def rows_payload(self, only_errors=False):
        rows = self.rows if not only_errors else [r for r in self.rows if r.status == STATUS_ERROR]
        return [
            {
                'row': r.row,
                'status': r.status,
                'values': r.values,
                'errors': [{'row': e.row, 'column': e.column, 'message': e.message} for e in r.errors],
                'note': r.note,
                'diff': r.diff,
            }
            for r in rows
        ]
