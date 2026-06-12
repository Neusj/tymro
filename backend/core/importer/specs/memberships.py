"""Spec de importación de Membresías activas (core.StudentPlan).

Onboarding con saldo arrastrado: el usuario escribe "Clases restantes" (lo
intuitivo) y el motor calcula classes_used = total del plan - restantes. Si el
plan es ilimitado, el saldo se ignora (unlimited_classes manda).

Convenciones espejo del flujo "Asignar plan" (core/views.py assign):
- total_classes/unlimited_classes se DERIVAN del plan, jamás del archivo.
- Si no se indica fecha de término: inicio + (duración del plan - 1) días.
- final_price = precio del plan con su descuento por defecto.
- Solo alumnos y planes ACTIVOS de la organización.

StudentPlan no tiene organization propia: se acota vía user__organization
(por eso este spec usa build_instance; el registry lo exige).

Dedup: un alumno con membresía ACTIVA (en BD o más arriba en el archivo) se
omite — el importador nunca desactiva ni modifica membresías existentes; para
eso está la pantalla "Asignar plan".
"""
import datetime

from ..registry import register
from ..spec import EntityImportSpec, FieldSpec, FKSpec, RowError

REMAINING_LABEL = 'Clases restantes'
END_LABEL = 'Fecha de término'


def _membership_rules(values, organization):
    errors = []
    plan = values.get('plan')
    remaining = values.get('remaining_classes')
    if plan is not None and not plan.unlimited_classes:
        if remaining is None:
            errors.append(RowError(
                row=0, column=REMAINING_LABEL,
                message=(
                    f"Indica las '{REMAINING_LABEL}' (entre 0 y {plan.total_classes}, "
                    f"el total del plan '{plan.name}')."
                ),
            ))
        elif not (0 <= remaining <= plan.total_classes):
            errors.append(RowError(
                row=0, column=REMAINING_LABEL,
                message=(
                    f"Las clases restantes deben estar entre 0 y {plan.total_classes} "
                    f"(el total del plan '{plan.name}')."
                ),
            ))
    start = values.get('start_date')
    end = values.get('end_date')
    if start is not None and end is not None and end < start:
        errors.append(RowError(
            row=0, column=END_LABEL,
            message='La fecha de término no puede ser anterior a la fecha de inicio.',
        ))
    return errors


def _derive_end_date(values, organization):
    # Calculada ANTES del preview: el usuario confirma la fecha real que se guardará.
    plan = values.get('plan')
    if values.get('end_date') is None and plan is not None and values.get('start_date') is not None:
        return {
            'end_date': values['start_date'] + datetime.timedelta(days=max(plan.duration_days - 1, 0)),
        }
    return {}


def _build_membership(values, organization):
    from django.db import IntegrityError

    from accounts.models import CustomUser
    from core.models import StudentPlan

    # Lock del alumno + re-chequeo dentro de la transacción del commit: si otro
    # proceso (otro import o "Asignar plan") le creó una membresía activa entre
    # el dedup y este punto, abortamos con rollback limpio (400 "vuelve a
    # validar") en vez de dejar dos membresías activas.
    CustomUser.objects.select_for_update().get(pk=values['user'].pk)
    if StudentPlan.objects.filter(user=values['user'], is_active=True).exists():
        raise IntegrityError('el alumno recibió una membresía activa en paralelo')

    plan = values['plan']
    start = values['start_date']
    end = values.get('end_date') or start + datetime.timedelta(days=max(plan.duration_days - 1, 0))
    discount = plan.discount_percentage or 0
    if plan.unlimited_classes:
        total, used, unlimited = 0, 0, True
    else:
        total = plan.total_classes
        used = total - values['remaining_classes']
        unlimited = False
    return StudentPlan(
        user=values['user'],
        plan=plan,
        start_date=start,
        end_date=end,
        total_classes=total,
        unlimited_classes=unlimited,
        classes_used=used,
        discount_percentage=discount,
        final_price=max(float(plan.price) * (1 - (discount / 100)), 0),
        is_active=True,
    )


MEMBERSHIPS = register(EntityImportSpec(
    slug='memberships',
    label='Membresías activas',
    description='El plan vigente de cada alumno, arrastrando las clases que le quedan.',
    model='core.StudentPlan',
    fields=(
        FieldSpec(
            attr='user', label='Email del alumno', kind='fk', required=True,
            fk=FKSpec(
                model='accounts.CustomUser', lookup_field='email',
                filters={'role': 'student', 'is_active': True},
                reference_label='el alumno',
            ),
            example='maria.perez@gmail.com',
            help_text='Email de un alumno ya cargado en tu gimnasio (hoja "Referencias").',
        ),
        FieldSpec(
            attr='plan_type', label='Tipo de plan', kind='choice',
            choices=(
                ('Mensual', 'monthly'),
                ('Pack', 'pack'),
                ('Clase suelta', 'single_class'),
                ('Trial', 'trial'),
                ('Giftcard', 'giftcard'),
            ),
            example='Mensual',
            help_text='Solo es necesario si tienes dos planes con el mismo nombre y distinto tipo.',
        ),
        FieldSpec(
            attr='plan', label='Nombre del plan', kind='fk', required=True,
            fk=FKSpec(
                model='core.Plan', lookup_field='name',
                filters={'is_active': True},
                reference_label='el plan',
                disambiguators=(('plan_type', 'plan_type'),),
                ambiguity_hint="Completa la columna 'Tipo de plan' para distinguirlo.",
            ),
            example='Plan mensual 8 clases',
            help_text='Nombre de un plan ya cargado en tu gimnasio (hoja "Referencias").',
        ),
        FieldSpec(
            attr='start_date', label='Fecha de inicio', kind='date', required=True,
            example='2026-06-01',
            help_text='Cuándo empezó (o empieza) la membresía. Formato AAAA-MM-DD.',
        ),
        FieldSpec(
            attr='end_date', label=END_LABEL, kind='date',
            example='2026-06-30',
            help_text='Hasta cuándo vale. Si la dejas vacía se calcula con la duración del plan.',
        ),
        FieldSpec(
            attr='remaining_classes', label=REMAINING_LABEL, kind='int',
            example='5',
            help_text='Cuántas clases le quedan HOY al alumno. Déjala vacía solo si el plan es ilimitado.',
        ),
    ),
    natural_key=('user',),
    org_field='user__organization',
    dedup_filters={'is_active': True},
    dependencies=('students', 'plans'),
    row_validators=(_membership_rules,),
    derive=_derive_end_date,
    build_instance=_build_membership,
    instructions=(
        'Importa aquí la membresía vigente de cada alumno para que pueda reservar '
        'clases desde el día uno, conservando las clases que le quedan.',
        'Antes de importar membresías carga los Alumnos y los Planes (en ese orden).',
        'Una fila = un alumno con su plan vigente. Si un alumno ya tiene una membresía '
        'activa (o aparece dos veces en el archivo), esa fila se omite: el importador '
        'nunca modifica membresías existentes.',
        "En '" + REMAINING_LABEL + "' escribe las clases que le quedan HOY (se arrastra "
        'el saldo del sistema anterior). Para planes ilimitados déjala vacía.',
        'Las fechas van en formato AAAA-MM-DD (ej. 2026-06-01). Si no indicas término, '
        'se calcula automáticamente con la duración del plan.',
        "Si tienes dos planes con el mismo nombre, usa 'Tipo de plan' para distinguirlos.",
    ),
))
