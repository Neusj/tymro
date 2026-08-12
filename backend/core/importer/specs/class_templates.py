"""Spec de importacion de Clases semanales (core.ClassTemplate).

Cada fila crea una o mas clases semanales recurrentes, igual que el formulario
/gym-admin/class-templates: la columna "Dias de la semana" acepta uno o varios
dias, y el motor expande internamente una plantilla por dia para conservar el
preview, la deduplicacion y la generacion de calendario por clase.

El inicio se infiere como hoy y no se pide fecha de termino: las clases se
generan hacia adelante por la ventana rodante, igual que el alta manual.
"""
import re
import unicodedata

from ..registry import register
from ..spec import EntityImportSpec, FieldSpec, FKSpec, RowError

WEEKDAYS_LABEL = 'Dias de la semana'
END_TIME_LABEL = 'Hora termino'
CAPACITY_LABEL = 'Capacidad'
TEACHER_LABEL = 'Email del profesor'
SUBSTITUTE_LABEL = 'Clase con suplente'
SUBSTITUTE_TEACHER_LABEL = 'Email del profesor suplente'
SUBSTITUTE_NAME_LABEL = 'Nombre del suplente externo'

WEEKDAY_CHOICES = (
    ('Lunes', 0),
    ('Martes', 1),
    ('Miercoles', 2),
    ('Jueves', 3),
    ('Viernes', 4),
    ('Sabado', 5),
    ('Domingo', 6),
)

TEACHER_FILTERS = {'role__in': ('teacher', 'gym_admin'), 'is_active': True}


def _text(value):
    if value is None:
        return ''
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()


def _normalize_weekday_token(value):
    text = unicodedata.normalize('NFKD', _text(value).casefold())
    return ''.join(char for char in text if not unicodedata.combining(char)).strip()


WEEKDAY_TOKEN_MAP = {
    _normalize_weekday_token(label): label
    for label, _ in WEEKDAY_CHOICES
}
WEEKDAY_TOKEN_MAP.update({
    str(db_value): label
    for label, db_value in WEEKDAY_CHOICES
})


def _split_weekdays(raw_value):
    text = _text(raw_value)
    if not text:
        return []
    text = re.sub(r'\s+y\s+', ',', text, flags=re.IGNORECASE)
    return [part.strip() for part in re.split(r'[,;/|\n]+', text) if part.strip()]


def _expand_weekday_rows(row_number, raw):
    tokens = _split_weekdays(raw.get('weekday'))
    if not tokens:
        return [(row_number, raw)]

    rows = []
    seen = set()
    for token in tokens:
        canonical = WEEKDAY_TOKEN_MAP.get(_normalize_weekday_token(token))
        value = canonical or token
        dedup_key = _normalize_weekday_token(value)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        expanded = dict(raw)
        expanded['weekday'] = value
        rows.append((row_number, expanded))
    return rows or [(row_number, raw)]


def _template_rules(values, organization):
    errors = []
    start_time, end_time = values.get('start_time'), values.get('end_time')
    if start_time is not None and end_time is not None and end_time <= start_time:
        errors.append(RowError(
            row=0, column=END_TIME_LABEL,
            message='La hora de termino debe ser posterior a la hora de inicio.',
        ))

    capacity = values.get('capacity')
    if capacity is not None and not (0 < capacity <= 1000):
        errors.append(RowError(
            row=0, column=CAPACITY_LABEL,
            message='La capacidad debe estar entre 1 y 1000 personas.',
        ))

    has_substitute = bool(values.get('has_substitute'))
    substitute_teacher = values.get('substitute_teacher')
    substitute_name = str(values.get('substitute_name') or '').strip()

    if not has_substitute and (substitute_teacher is not None or substitute_name):
        errors.append(RowError(
            row=0, column=SUBSTITUTE_LABEL,
            message=(
                "Marca 'Clase con suplente' como 'Si' si vas a indicar un profesor "
                'suplente o un suplente externo.'
            ),
        ))

    if has_substitute:
        if substitute_teacher is None and not substitute_name:
            errors.append(RowError(
                row=0, column=SUBSTITUTE_LABEL,
                message=(
                    'Indica el email de un profesor suplente o el nombre de un '
                    'suplente externo.'
                ),
            ))
        if substitute_teacher is not None and substitute_name:
            errors.append(RowError(
                row=0, column=SUBSTITUTE_LABEL,
                message=(
                    'Usa solo una opcion de suplente: email de profesor registrado '
                    'o nombre de suplente externo.'
                ),
            ))
        if substitute_teacher is not None and substitute_teacher == values.get('teacher'):
            errors.append(RowError(
                row=0, column=SUBSTITUTE_TEACHER_LABEL,
                message='El suplente no puede ser el profesor titular.',
            ))

    return errors


def _derive_defaults(values, organization):
    from django.utils import timezone

    derived = {
        'start_date': timezone.localdate(),
        'end_date': None,
        'is_active': True,
    }
    if not values.get('has_substitute'):
        derived['substitute_teacher'] = None
        derived['substitute_name'] = ''
        derived['substitution_source'] = ''
        derived['substitution_assigned_at'] = None
        derived['substitution_assigned_by'] = None
        return derived

    from core.models import GymClass

    derived['substitute_name'] = str(values.get('substitute_name') or '').strip()
    derived['substitution_source'] = (
        GymClass.SubstitutionSource.ADMIN_ASSIGNED
        if values.get('substitute_teacher') is not None
        else GymClass.SubstitutionSource.EXTERNAL_ADMIN
    )
    derived['substitution_assigned_at'] = timezone.now()
    return derived


def _generate_calendar(instances, organization, actor):
    # Espejo de ClassTemplateViewSet.perform_create: la clase importada genera
    # su calendario de inmediato dentro de la ventana rodante.
    from core.services.recurrence import generate_instances_for_template_range

    for template in instances:
        generate_instances_for_template_range(
            template=template,
            from_date=template.start_date,
            until_date=template.end_date,
            created_by=actor,
            skip_holidays=True,
        )


CLASS_TEMPLATES = register(EntityImportSpec(
    slug='class-templates',
    label='Clases',
    description='Crea clases semanales con profesor, tipo, disciplina, cupos y opciones de suplente.',
    model='core.ClassTemplate',
    fields=(
        FieldSpec(
            attr='name', label='Nombre visible', kind='string', max_length=150,
            example='Yoga vespertino',
            help_text='Nombre visible de la clase (opcional).',
        ),
        FieldSpec(
            attr='weekday', label=WEEKDAYS_LABEL, kind='choice', required=True,
            choices=WEEKDAY_CHOICES, example='Lunes, Miercoles, Viernes',
            help_text=(
                'Dias en que se repite la clase cada semana. Puedes indicar uno o '
                'varios separados por coma.'
            ),
            aliases=('Dia de la semana',),
        ),
        FieldSpec(
            attr='branch', label='Sucursal', kind='fk', required=True,
            fk=FKSpec(model='core.Branch', lookup_field='name', reference_label='la sucursal'),
            example='Sede Centro',
            help_text='Sucursal donde se dicta la clase. Elige un valor de la hoja "Referencias".',
        ),
        FieldSpec(
            attr='teacher', label=TEACHER_LABEL, kind='fk', required=True,
            fk=FKSpec(
                model='accounts.CustomUser', lookup_field='email',
                filters=TEACHER_FILTERS,
                reference_label='el profesor',
            ),
            example='coach@gym.cl',
            help_text='Email de un profesor o administrador-profesor activo de tu gimnasio.',
        ),
        FieldSpec(
            attr='class_type', label='Tipo', kind='fk', required=True,
            fk=FKSpec(model='core.ClassType', lookup_field='name', reference_label='el tipo de clase'),
            example='Clase grupal',
            help_text='Tipo de clase ya cargado.',
        ),
        FieldSpec(
            attr='discipline', label='Disciplina', kind='fk', required=True,
            fk=FKSpec(model='core.Discipline', lookup_field='name', reference_label='la disciplina'),
            example='Yoga',
            help_text='Disciplina ya cargada.',
        ),
        FieldSpec(
            attr='start_time', label='Hora inicio', kind='time', required=True,
            example='18:30',
            help_text='Hora de inicio en formato HH:MM (reloj de 24 horas).',
        ),
        FieldSpec(
            attr='end_time', label=END_TIME_LABEL, kind='time', required=True,
            example='19:30',
            help_text='Hora de termino en formato HH:MM. Debe ser posterior al inicio.',
        ),
        FieldSpec(
            attr='capacity', label=CAPACITY_LABEL, kind='int', default=20,
            example='20',
            help_text='Cupos de la clase. Si dejas la celda vacia se asume 20.',
        ),
        FieldSpec(
            attr='description', label='Descripcion', kind='text',
            example='',
            help_text='Descripcion opcional de la clase.',
        ),
        FieldSpec(
            attr='is_trial_eligible', label='Elegible para clase de prueba gratis',
            kind='bool', default=False, example='No',
            help_text="'Si' si los prospectos pueden agendar su clase de prueba gratis aqui. Vacio = 'No'.",
        ),
        FieldSpec(
            attr='has_substitute', label=SUBSTITUTE_LABEL,
            kind='bool', default=False, example='No',
            help_text="'Si' cuando la clase tiene un suplente por defecto. Vacio = 'No'.",
        ),
        FieldSpec(
            attr='substitute_teacher', label=SUBSTITUTE_TEACHER_LABEL, kind='fk',
            fk=FKSpec(
                model='accounts.CustomUser', lookup_field='email',
                filters=TEACHER_FILTERS,
                reference_label='el profesor suplente',
            ),
            example='suplente@gym.cl',
            help_text='Opcional. Usalo solo si el suplente es un profesor registrado.',
        ),
        FieldSpec(
            attr='substitute_name', label=SUBSTITUTE_NAME_LABEL, kind='string', max_length=150,
            example='Juan Perez',
            help_text='Opcional. Usalo solo si el suplente es externo.',
        ),
    ),
    natural_key=('branch', 'weekday', 'start_time', 'teacher'),
    dependencies=('branches', 'class-types', 'disciplines', 'teachers'),
    row_validators=(_template_rules,),
    expand_rows=_expand_weekday_rows,
    derive=_derive_defaults,
    post_commit=_generate_calendar,
    instructions=(
        'Cada fila puede crear una clase semanal para uno o varios dias. Para varios '
        'dias usa coma, por ejemplo: Lunes, Miercoles, Viernes.',
        'Antes de importar clases carga Sucursales, Tipos, Disciplinas y Profesores.',
        'La clase arranca hoy y no tiene fecha de fin: se genera automaticamente cada '
        'semana hacia adelante dentro de la ventana configurada.',
        'Las horas van en formato de 24 horas (HH:MM): 09:00, 18:30. La hora de '
        'termino debe ser posterior a la de inicio.',
        "Para 'Clase con suplente', marca 'Si' y completa solo una de estas columnas: "
        'Email del profesor suplente o Nombre del suplente externo.',
        'Si ya existe una clase en la misma sucursal, dia, hora de inicio y profesor, '
        'esa fila se omite (no se duplica).',
        'Al confirmar, las clases del calendario se generan automaticamente desde hoy '
        '(saltando los festivos configurados).',
    ),
))
