"""Spec de importación del Horario recurrente (core.ClassTemplate).

La entidad más conectada: 4 FK (sucursal obligatoria; profesor, tipo de clase
y disciplina opcionales), todas resueltas dentro de la organización del actor.

Las reglas de fila replican ClassTemplate.clean() para que el preview las
atrape (fin > inicio, vigencia coherente, capacidad, solape de profesor contra
BD). El commit además ejecuta full_clean(), que vuelve a validar todo dentro
de la transacción — incluidos los solapes ENTRE filas del propio archivo,
porque cada fila guardada ya es visible para el clean() de la siguiente.
"""
from ..registry import register
from ..spec import EntityImportSpec, FieldSpec, FKSpec, RowError

END_TIME_LABEL = 'Hora de término'
END_DATE_LABEL = 'Vigente hasta'
CAPACITY_LABEL = 'Capacidad'
TEACHER_LABEL = 'Email del profesor'

WEEKDAY_CHOICES = (
    ('Lunes', 0),
    ('Martes', 1),
    ('Miércoles', 2),
    ('Jueves', 3),
    ('Viernes', 4),
    ('Sábado', 5),
    ('Domingo', 6),
)


def _template_rules(values, organization):
    from django.db.models import Q

    from core.models import ClassTemplate

    errors = []
    start_time, end_time = values.get('start_time'), values.get('end_time')
    if start_time is not None and end_time is not None and end_time <= start_time:
        errors.append(RowError(
            row=0, column=END_TIME_LABEL,
            message='La hora de término debe ser posterior a la hora de inicio.',
        ))
    start_date, end_date = values.get('start_date'), values.get('end_date')
    if start_date is not None and end_date is not None and end_date < start_date:
        errors.append(RowError(
            row=0, column=END_DATE_LABEL,
            message="La fecha de 'Vigente hasta' no puede ser anterior a la de 'Vigente desde'.",
        ))
    capacity = values.get('capacity')
    if capacity is not None and not (0 < capacity <= 1000):
        errors.append(RowError(
            row=0, column=CAPACITY_LABEL,
            message='La capacidad debe estar entre 1 y 1000 personas.',
        ))
    if errors:
        return errors

    # Solape del profesor contra el horario y las clases YA existentes (misma
    # lógica que ClassTemplate.clean); los solapes entre filas del archivo los
    # atrapa el full_clean del commit.
    teacher = values.get('teacher')
    if teacher is not None and start_time is not None and end_time is not None:
        weekday = values.get('weekday')
        queryset = ClassTemplate.objects.filter(
            teacher=teacher,
            weekday=weekday,
            is_active=True,
            start_time__lt=end_time,
            end_time__gt=start_time,
        )
        if end_date is None:
            queryset = queryset.filter(Q(end_date__isnull=True) | Q(end_date__gte=start_date))
        else:
            queryset = queryset.filter(Q(start_date__lte=end_date))
            queryset = queryset.filter(Q(end_date__isnull=True) | Q(end_date__gte=start_date))
        if queryset.exists():
            errors.append(RowError(
                row=0, column=TEACHER_LABEL,
                message='El profesor ya tiene otra clase recurrente activa que se cruza con ese horario.',
            ))
            return errors

        from core.models import GymClass

        weekday_for_db = ((weekday + 1) % 7) + 1
        class_query = GymClass.objects.filter(
            teacher=teacher,
            start_datetime__week_day=weekday_for_db,
            start_datetime__time__lt=end_time,
            end_datetime__time__gt=start_time,
        ).exclude(status=GymClass.Status.CANCELLED)
        if end_date is None:
            class_query = class_query.filter(start_datetime__date__gte=start_date)
        else:
            class_query = class_query.filter(
                start_datetime__date__gte=start_date,
                start_datetime__date__lte=end_date,
            )
        if class_query.exists():
            errors.append(RowError(
                row=0, column=TEACHER_LABEL,
                message='El profesor ya tiene clases en el calendario que se cruzan con ese horario.',
            ))
    return errors


def _generate_calendar(instances, organization, actor):
    # Espejo de ClassTemplateViewSet.perform_create: el horario importado genera
    # sus clases en el calendario de inmediato (mismo servicio, mismos saltos de
    # feriados y conflictos). Corre dentro de la transacción del commit.
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
    label='Horario recurrente',
    description='Tu parrilla semanal de clases: día, horario, sucursal y profesor de cada clase que se repite.',
    model='core.ClassTemplate',
    fields=(
        FieldSpec(
            attr='branch', label='Sucursal', kind='fk', required=True,
            fk=FKSpec(model='core.Branch', lookup_field='name', reference_label='la sucursal'),
            example='Sede Centro',
            help_text='Sucursal donde se dicta la clase. Elige un valor de la hoja "Referencias".',
        ),
        FieldSpec(
            attr='weekday', label='Día de la semana', kind='choice', required=True,
            choices=WEEKDAY_CHOICES, example='Lunes',
            help_text='Día en que se repite la clase cada semana.',
        ),
        FieldSpec(
            attr='start_time', label='Hora de inicio', kind='time', required=True,
            example='18:30',
            help_text='Hora de inicio en formato HH:MM (reloj de 24 horas).',
        ),
        FieldSpec(
            attr='end_time', label=END_TIME_LABEL, kind='time', required=True,
            example='19:30',
            help_text='Hora de término en formato HH:MM. Debe ser posterior al inicio.',
        ),
        FieldSpec(
            attr='name', label='Nombre de la clase', kind='string', max_length=150,
            example='Yoga vespertino',
            help_text='Nombre visible de la clase (opcional). Si lo dejas vacío se usa el día y la hora.',
        ),
        FieldSpec(
            attr='teacher', label=TEACHER_LABEL, kind='fk',
            fk=FKSpec(
                model='accounts.CustomUser', lookup_field='email',
                filters={'role': 'teacher', 'is_active': True},
                reference_label='el profesor',
            ),
            example='coach@gym.cl',
            help_text='Email de un profesor ya cargado (opcional, puedes asignarlo después).',
        ),
        FieldSpec(
            attr='class_type', label='Tipo de clase', kind='fk',
            fk=FKSpec(model='core.ClassType', lookup_field='name', reference_label='el tipo de clase'),
            example='Clase grupal',
            help_text='Tipo de clase ya cargado (opcional).',
        ),
        FieldSpec(
            attr='discipline', label='Disciplina', kind='fk',
            fk=FKSpec(model='core.Discipline', lookup_field='name', reference_label='la disciplina'),
            example='Yoga',
            help_text='Disciplina ya cargada (opcional).',
        ),
        FieldSpec(
            attr='capacity', label=CAPACITY_LABEL, kind='int', default=20,
            example='20',
            help_text='Cupos de la clase. Si dejas la celda vacía se asume 20.',
        ),
        FieldSpec(
            attr='start_date', label='Vigente desde', kind='date', required=True,
            example='2026-06-15',
            help_text='Desde qué fecha se generan las clases de este horario. Formato AAAA-MM-DD.',
        ),
        FieldSpec(
            attr='end_date', label=END_DATE_LABEL, kind='date',
            example='',
            help_text='Hasta cuándo vale el horario (opcional: vacío = sin fecha de término).',
        ),
        FieldSpec(
            attr='is_trial_eligible', label='Apta para clase de prueba', kind='bool', default=False,
            example='No',
            help_text="'Sí' si los prospectos pueden agendar su clase de prueba gratis aquí. Vacío = 'No'.",
        ),
    ),
    natural_key=('branch', 'weekday', 'start_time', 'teacher'),
    dependencies=('branches',),
    row_validators=(_template_rules,),
    post_commit=_generate_calendar,
    instructions=(
        'El horario recurrente es tu parrilla semanal: cada fila es una clase que se '
        'repite todas las semanas el mismo día y a la misma hora en una sucursal.',
        'Antes de importar el horario carga las Sucursales (obligatorio). Profesores, '
        'Tipos de clase y Disciplinas son opcionales pero conviene cargarlos antes '
        'para poder asignarlos aquí.',
        'Las horas van en formato de 24 horas (HH:MM): 09:00, 18:30. La hora de '
        'término debe ser posterior a la de inicio.',
        "En 'Vigente desde' indica desde qué fecha se generan las clases (AAAA-MM-DD).",
        'Un profesor no puede tener dos clases que se crucen el mismo día: esas filas '
        'saldrán con error.',
        'Si ya existe una clase en la misma sucursal, día, hora de inicio y profesor, '
        'esa fila se omite (no se duplica). Dos clases en el mismo horario con '
        'profesores distintos sí se cargan ambas.',
        'Al confirmar, las clases del calendario se generan automáticamente desde la '
        'fecha de vigencia (saltando los festivos configurados).',
    ),
))
