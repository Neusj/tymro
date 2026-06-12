"""Spec de importación de Disciplinas (entidad piloto, sin FK)."""
from ..registry import register
from ..spec import EntityImportSpec, FieldSpec

DISCIPLINES = register(EntityImportSpec(
    slug='disciplines',
    label='Disciplinas',
    description='Las actividades que ofrece tu gimnasio (Yoga, Crossfit, Funcional, ...).',
    model='core.Discipline',
    fields=(
        FieldSpec(
            attr='name', label='Nombre', kind='string', required=True, max_length=120,
            example='Yoga',
            help_text='Nombre de la disciplina. No puede repetirse dentro de tu gimnasio.',
        ),
        FieldSpec(
            attr='description', label='Descripción', kind='text',
            example='Clases para todos los niveles',
            help_text='Descripción breve de la disciplina. Es opcional.',
        ),
        FieldSpec(
            attr='is_active', label='Activa', kind='bool', default=True,
            example='Sí',
            help_text="Escribe 'Sí' o 'No'. Si dejas la celda vacía se asume 'Sí'.",
        ),
    ),
    natural_key=('name',),
    instructions=(
        'Las disciplinas son las actividades que ofrece tu gimnasio (por ejemplo Yoga, '
        'Crossfit o Funcional). Luego podrás asociarlas a tus clases y horarios.',
        'Descarga la plantilla y completa la hoja "Datos", una disciplina por fila.',
        'No cambies ni borres la fila de encabezados.',
        'Borra o reemplaza las filas de ejemplo antes de subir el archivo.',
        'Si una disciplina ya existe con el mismo nombre, esa fila se omite: no se duplica '
        'ni se modifica la existente.',
        'Error común: dejar la columna "Nombre" vacía o repetir el mismo nombre en dos filas.',
    ),
))
