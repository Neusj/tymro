"""Spec de importación de Sucursales (Branch)."""
from ..registry import register
from ..spec import EntityImportSpec, FieldSpec

BRANCHES = register(EntityImportSpec(
    slug='branches',
    label='Sucursales',
    description='Las sedes o locales de tu gimnasio. Si tienes uno solo, crea una única sucursal.',
    model='core.Branch',
    fields=(
        FieldSpec(
            attr='name', label='Nombre', kind='string', required=True, max_length=120,
            example='Sede Centro',
            help_text='Nombre de la sucursal. No puede repetirse dentro de tu gimnasio.',
        ),
        FieldSpec(
            attr='code', label='Código', kind='string', max_length=30,
            example='CEN',
            help_text='Código corto interno para identificarla (opcional).',
        ),
        FieldSpec(
            attr='address', label='Dirección', kind='string', max_length=255,
            example='Av. Libertador 1234, Santiago',
            help_text='Dirección de la sucursal (opcional).',
        ),
        FieldSpec(
            attr='is_active', label='Activa', kind='bool', default=True,
            example='Sí',
            help_text="Escribe 'Sí' o 'No'. Si dejas la celda vacía se asume 'Sí'.",
        ),
    ),
    natural_key=('name',),
    instructions=(
        'Las sucursales son las sedes físicas de tu gimnasio. Casi todo lo demás '
        '(horarios, clases, usuarios) se asocia a una sucursal, así que conviene '
        'cargarlas primero.',
        'Descarga la plantilla y completa la hoja "Datos", una sucursal por fila.',
        'No cambies ni borres la fila de encabezados.',
        'Borra o reemplaza las filas de ejemplo antes de subir el archivo.',
        'Si una sucursal ya existe con el mismo nombre, esa fila se omite: no se '
        'duplica ni se modifica la existente.',
        'Error común: dejar la columna "Nombre" vacía o repetir el mismo nombre en dos filas.',
    ),
))
