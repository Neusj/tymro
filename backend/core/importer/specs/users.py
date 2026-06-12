"""Specs de importación de Alumnos y Profesores (accounts.CustomUser).

Comparten estructura; cambian rol fijo, labels e instrucciones. Convenciones
de la app (mismas que el registro público en core/views.py):
- username = email.
- Sin clave usable (set_unusable_password): la persona define su clave vía
  "olvidé mi contraseña" / invitación por email.
- El rol lo fija el spec (Alumnos=student, Profesores=teacher); el archivo no
  puede elegir rol ni organización.

Email no es unique en BD pero username sí (global): un email que ya exista en
OTRA organización es un conflicto explícito de fila (no se toca esa cuenta).
Dentro de la propia org, un email existente se omite (on_conflict=skip).
"""
from ..registry import register
from ..spec import EntityImportSpec, FieldSpec, FKSpec, RowError

EMAIL_LABEL = 'Email'


def _email_conflict_outside_org(values, organization):
    from django.db.models import Q

    from accounts.models import CustomUser

    email = values.get('email')
    if not email:
        return []
    # OJO: .exclude(organization=org) NO matchea organization NULL (lógica
    # trivalente de SQL); el filtro explícito incluye cuentas de plataforma.
    exists_elsewhere = (
        CustomUser.objects
        .filter(Q(email__iexact=email) | Q(username__iexact=email))
        .filter(Q(organization__isnull=True) | ~Q(organization=organization))
        .exists()
    )
    if exists_elsewhere:
        return [RowError(
            row=0, column=EMAIL_LABEL,
            message=(
                f"El email '{email}' ya pertenece a una cuenta de otra organización en TYMRO. "
                'No se puede importar: usa otro email o contacta a soporte.'
            ),
        )]
    return []


def _email_valid_as_username(values, organization):
    # username = email, así que el email debe pasar el validador de username
    # (si no, full_clean lo rechazaría recién en el commit con mensaje técnico).
    from django.contrib.auth.validators import UnicodeUsernameValidator
    from django.core.exceptions import ValidationError

    email = values.get('email')
    if not email:
        return []
    try:
        UnicodeUsernameValidator()(email)
    except ValidationError:
        return [RowError(
            row=0, column=EMAIL_LABEL,
            message=(
                f"El email '{email}' contiene caracteres no permitidos para una cuenta "
                'de TYMRO. Usa solo letras, números y los símbolos @ . + - _'
            ),
        )]
    return []


def _build_user_factory(role):
    def _build(values, organization):
        from accounts.models import CustomUser

        email = values['email']
        user = CustomUser(
            username=email,
            email=email,
            first_name=values.get('first_name') or '',
            last_name=values.get('last_name') or '',
            phone=values.get('phone') or '',
            branch=values.get('branch'),
            role=role,
            organization=organization,
        )
        user.set_unusable_password()
        return user
    return _build


def _user_fields(person_label):
    return (
        FieldSpec(
            # max_length 150 (no 254): username=email y username es CharField(150).
            attr='email', label=EMAIL_LABEL, kind='email', required=True, max_length=150,
            example='maria.perez@gmail.com',
            help_text=f'Email de {person_label}. Será su usuario para entrar a TYMRO y no puede repetirse.',
        ),
        FieldSpec(
            attr='first_name', label='Nombre', kind='string', required=True, max_length=150,
            example='María',
            help_text=f'Nombre de pila de {person_label}.',
        ),
        FieldSpec(
            attr='last_name', label='Apellido', kind='string', max_length=150,
            example='Pérez',
            help_text='Apellido (opcional pero recomendado).',
        ),
        FieldSpec(
            attr='phone', label='Teléfono', kind='string', max_length=40,
            example='+56 9 1234 5678',
            help_text='Teléfono de contacto (opcional).',
        ),
        FieldSpec(
            attr='branch', label='Sucursal', kind='fk',
            fk=FKSpec(model='core.Branch', lookup_field='name', reference_label='la sucursal'),
            example='Sede Centro',
            help_text='Sucursal habitual (opcional). Elige un valor de la hoja "Referencias".',
        ),
    )


_COMMON_INSTRUCTIONS = (
    'No cambies ni borres la fila de encabezados, y borra las filas de ejemplo antes de subir.',
    'Las personas importadas quedan SIN contraseña: para entrar a TYMRO deben usar '
    '"¿Olvidaste tu contraseña?" con su email, donde la definen por primera vez.',
    'Si quieres asignarles sucursal, primero importa o crea las Sucursales; la columna '
    'es opcional y puedes dejarla vacía.',
    'Un email que ya exista en tu gimnasio se omite (no se duplica ni se modifica). '
    'Un email que pertenezca a otra organización aparecerá como error: esa cuenta no se toca.',
    'Error común: emails mal escritos (sin @ o con espacios) o repetidos en varias filas.',
)


STUDENTS = register(EntityImportSpec(
    slug='students',
    label='Alumnos',
    description='Tus alumnos o socios. Quedan listos para asignarles membresías y reservar clases.',
    model='accounts.CustomUser',
    fields=_user_fields('el alumno o la alumna'),
    natural_key=('email',),
    row_validators=(_email_valid_as_username, _email_conflict_outside_org),
    build_instance=_build_user_factory('student'),
    instructions=(
        'Importa aquí a tus alumnos y alumnas. Cada fila crea una cuenta de alumno '
        'en tu gimnasio (rol Alumno, sin acceso administrativo).',
    ) + _COMMON_INSTRUCTIONS,
))


TEACHERS = register(EntityImportSpec(
    slug='teachers',
    label='Profesores',
    description='Tus profesores o coaches. Quedan listos para asignarlos a clases y horarios.',
    model='accounts.CustomUser',
    fields=_user_fields('el profesor o la profesora'),
    natural_key=('email',),
    row_validators=(_email_valid_as_username, _email_conflict_outside_org),
    build_instance=_build_user_factory('teacher'),
    instructions=(
        'Importa aquí a tus profesores y coaches. Cada fila crea una cuenta de profesor '
        'en tu gimnasio (rol Profesor: puede ver sus clases y pagos, sin acceso administrativo).',
    ) + _COMMON_INSTRUCTIONS,
))
