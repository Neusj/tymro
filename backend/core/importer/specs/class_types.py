"""Spec de importación de Tipos de clase (ClassType)."""
from ..registry import register
from ..spec import EntityImportSpec, FieldSpec, RowError

DURATION_LABEL = 'Duración (minutos)'


def _duration_positive(values, organization):
    duration = values.get('duration_minutes')
    if duration is not None and not (0 < duration <= 1440):
        return [RowError(
            row=0, column=DURATION_LABEL,
            message='La duración debe estar entre 1 y 1440 minutos (un día completo).',
        )]
    return []


CLASS_TYPES = register(EntityImportSpec(
    slug='class-types',
    label='Tipos de clase',
    description='Los formatos de clase que dictas (Grupal, Personalizada, Iniciación, ...).',
    model='core.ClassType',
    fields=(
        FieldSpec(
            attr='name', label='Nombre', kind='string', required=True, max_length=120,
            example='Clase grupal',
            help_text='Nombre del tipo de clase. No puede repetirse dentro de tu gimnasio.',
        ),
        FieldSpec(
            attr='description', label='Descripción', kind='text',
            example='Clase para hasta 20 personas',
            help_text='Descripción breve del tipo de clase. Es opcional.',
        ),
        FieldSpec(
            attr='duration_minutes', label=DURATION_LABEL, kind='int', default=60,
            example='60',
            help_text='Duración habitual en minutos. Si dejas la celda vacía se asume 60.',
        ),
        FieldSpec(
            attr='is_private', label='Clase privada', kind='bool', default=False,
            example='No',
            help_text="Escribe 'Sí' si es una clase personalizada/privada. Si dejas la celda vacía se asume 'No'.",
        ),
        FieldSpec(
            attr='is_active', label='Activa', kind='bool', default=True,
            example='Sí',
            help_text="Escribe 'Sí' o 'No'. Si dejas la celda vacía se asume 'Sí'.",
        ),
    ),
    natural_key=('name',),
    row_validators=(_duration_positive,),
    instructions=(
        'Los tipos de clase describen el formato de tus clases (por ejemplo "Clase '
        'grupal", "Personalizada" o "Iniciación") y se usan al armar el horario.',
        'Descarga la plantilla y completa la hoja "Datos", un tipo de clase por fila.',
        'No cambies ni borres la fila de encabezados.',
        'Borra o reemplaza las filas de ejemplo antes de subir el archivo.',
        'La duración va en minutos y debe ser mayor que 0 (por ejemplo 45, 60 o 90).',
        'Si un tipo de clase ya existe con el mismo nombre, esa fila se omite: no se '
        'duplica ni se modifica el existente.',
    ),
))
