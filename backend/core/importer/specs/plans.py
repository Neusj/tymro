"""Spec de importación de Planes (Plan).

Plan no tiene unique en name: la clave natural es (nombre, tipo de plan),
igual que la desambiguación que usarán las Membresías en F4.
Si "Clases ilimitadas" = Sí, la cantidad de clases se fuerza a 0 (el flag
unlimited_classes manda y el saldo se ignora, como en el resto de la app).
"""
from ..registry import register
from ..spec import EntityImportSpec, FieldSpec, RowError

CLASSES_LABEL = 'Cantidad de clases'
DURATION_LABEL = 'Duración (días)'
PRICE_LABEL = 'Precio'

PLAN_TYPE_CHOICES = (
    ('Mensual', 'monthly'),
    ('Pack', 'pack'),
    ('Clase suelta', 'single_class'),
    ('Trial', 'trial'),
    ('Giftcard', 'giftcard'),
)


def _plan_rules(values, organization):
    errors = []
    unlimited = values.get('unlimited_classes')
    total = values.get('total_classes')
    if not unlimited:
        if total is None:
            errors.append(RowError(
                row=0, column=CLASSES_LABEL,
                message="Indica la 'Cantidad de clases' o marca 'Clases ilimitadas' como 'Sí'.",
            ))
        elif total <= 0:
            errors.append(RowError(
                row=0, column=CLASSES_LABEL,
                message='La cantidad de clases debe ser mayor que 0 (o usa Clases ilimitadas).',
            ))
    duration = values.get('duration_days')
    if duration is not None and not (0 < duration <= 3660):
        errors.append(RowError(
            row=0, column=DURATION_LABEL,
            message='La duración debe estar entre 1 y 3660 días.',
        ))
    price = values.get('price')
    if price is not None and price < 0:
        errors.append(RowError(
            row=0, column=PRICE_LABEL,
            message='El precio no puede ser negativo. Para planes gratuitos usa 0.',
        ))
    return errors


def _derive_unlimited(values, organization):
    # Plan ilimitado: el saldo no aplica; total_classes queda en 0 (convención
    # del modelo desde la migración 0022).
    if values.get('unlimited_classes'):
        return {'total_classes': 0}
    return {}


PLANS = register(EntityImportSpec(
    slug='plans',
    label='Planes',
    description='Los planes o membresías que vendes (mensual, pack de clases, clase suelta, ...).',
    model='core.Plan',
    fields=(
        FieldSpec(
            attr='name', label='Nombre', kind='string', required=True, max_length=120,
            example='Plan mensual 8 clases',
            help_text='Nombre comercial del plan. Puede repetirse solo si el tipo de plan es distinto.',
        ),
        FieldSpec(
            attr='plan_type', label='Tipo de plan', kind='choice', required=True,
            choices=PLAN_TYPE_CHOICES, example='Mensual',
            help_text='Elige uno: Mensual, Pack, Clase suelta, Trial o Giftcard.',
        ),
        FieldSpec(
            attr='total_classes', label=CLASSES_LABEL, kind='int',
            example='8',
            help_text="Cuántas clases incluye el plan. Déjala vacía solo si 'Clases ilimitadas' es 'Sí'.",
        ),
        FieldSpec(
            attr='unlimited_classes', label='Clases ilimitadas', kind='bool', default=False,
            example='No',
            help_text="Escribe 'Sí' si el plan no tiene tope de clases. En ese caso la cantidad de clases se ignora.",
        ),
        FieldSpec(
            attr='duration_days', label=DURATION_LABEL, kind='int', required=True,
            example='30',
            help_text='Vigencia del plan en días desde su activación (ej. 30 para un mes).',
        ),
        FieldSpec(
            attr='price', label=PRICE_LABEL, kind='decimal', required=True,
            example='45000',
            help_text='Precio del plan, solo números sin puntos ni símbolo (ej. 45000).',
        ),
        FieldSpec(
            attr='is_public', label='Visible para alumnos', kind='bool', default=True,
            example='Sí',
            help_text="'Sí' para que los alumnos lo vean y contraten; 'No' si es interno. Vacío = 'Sí'.",
        ),
        FieldSpec(
            attr='is_active', label='Activo', kind='bool', default=True,
            example='Sí',
            help_text="Escribe 'Sí' o 'No'. Si dejas la celda vacía se asume 'Sí'.",
        ),
    ),
    natural_key=('name', 'plan_type'),
    row_validators=(_plan_rules,),
    derive=_derive_unlimited,
    instructions=(
        'Los planes son las membresías que vendes a tus alumnos: definen cuántas '
        'clases incluyen, cuántos días duran y su precio.',
        'Descarga la plantilla y completa la hoja "Datos", un plan por fila.',
        'El "Tipo de plan" se elige de una lista (ver hoja Referencias): Mensual, '
        'Pack, Clase suelta, Trial o Giftcard.',
        "Para un plan sin tope de clases marca 'Clases ilimitadas' = Sí y deja "
        "vacía la 'Cantidad de clases'.",
        'El precio va sin puntos, comas ni símbolo: 45000, no $45.000.',
        'Si ya existe un plan con el mismo nombre y el mismo tipo, esa fila se '
        'omite: no se duplica ni se modifica el existente.',
        "Error común: dejar 'Cantidad de clases' vacía sin marcar 'Clases ilimitadas'.",
    ),
))
