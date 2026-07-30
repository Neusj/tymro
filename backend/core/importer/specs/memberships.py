"""Spec de importación de Membresías activas (core.StudentPlan).

Onboarding con saldo arrastrado: el usuario escribe "Clases restantes" (lo
intuitivo) y el motor calcula classes_used = total del plan - restantes. Si el
plan es ilimitado, el saldo se ignora (unlimited_classes manda).

Convenciones espejo del flujo "Asignar plan" (core/views.py assign):
- total_classes/unlimited_classes se DERIVAN del plan, jamás del archivo.
- Si no se indica fecha de término: inicio + (duración del plan - 1) días.
- final_price = precio del plan con su descuento por defecto.
- Solo alumnos y planes ACTIVOS de la organización.

StudentPlan tiene organization propia desde 0030 (copia de plan.organization).
Se sigue usando build_instance porque el resto de los campos son derivados.

Dedup: un alumno con membresía ACTIVA (en BD o más arriba en el archivo) se
omite — el importador nunca desactiva ni modifica membresías existentes; para
eso está la pantalla "Asignar plan".
"""
import datetime

from django.utils import timezone

from ..registry import register
from ..spec import EntityImportSpec, FieldSpec, FKSpec, RowError

REMAINING_LABEL = 'Clases restantes'
USED_LABEL = 'Clases utilizadas'
FEE_LABEL = 'Matrícula'
END_LABEL = 'Fecha de término'


def _membership_rules(values, organization):
    """Saldo flexible: para planes LIMITADOS basta indicar 'Clases restantes' O
    'Clases utilizadas' (el motor calcula la otra). Si vienen ambas, deben cuadrar
    con el total del plan. Para planes ILIMITADOS el saldo se ignora."""
    errors = []
    plan = values.get('plan')
    remaining = values.get('remaining_classes')
    used = values.get('classes_used')
    if plan is not None and not plan.unlimited_classes:
        total = plan.total_classes
        if remaining is None and used is None:
            errors.append(RowError(
                row=0, column=REMAINING_LABEL,
                message=(
                    f"Indica las '{REMAINING_LABEL}' o las '{USED_LABEL}' "
                    f"(el total del plan '{plan.name}' es {total})."
                ),
            ))
        else:
            if remaining is not None and not (0 <= remaining <= total):
                errors.append(RowError(
                    row=0, column=REMAINING_LABEL,
                    message=(
                        f"Las clases restantes deben estar entre 0 y {total} "
                        f"(el total del plan '{plan.name}')."
                    ),
                ))
            if used is not None and not (0 <= used <= total):
                errors.append(RowError(
                    row=0, column=USED_LABEL,
                    message=(
                        f"Las clases utilizadas deben estar entre 0 y {total} "
                        f"(el total del plan '{plan.name}')."
                    ),
                ))
            if (
                remaining is not None and used is not None
                and 0 <= remaining <= total and 0 <= used <= total
                and used + remaining != total
            ):
                errors.append(RowError(
                    row=0, column=USED_LABEL,
                    message=(
                        f"No cuadra: utilizadas ({used}) + restantes ({remaining}) debe ser "
                        f"igual al total del plan '{plan.name}' ({total})."
                    ),
                ))
    start = values.get('start_date')
    end = values.get('end_date')
    if start is not None and end is not None and end < start:
        errors.append(RowError(
            row=0, column=END_LABEL,
            message='La fecha de término no puede ser anterior a la fecha de inicio.',
        ))

    # ¿Esta fila quedaría como membresía vigente? (mismo cálculo que _build_membership)
    if plan is not None and start is not None:
        effective_end = end or start + datetime.timedelta(days=max(plan.duration_days - 1, 0))
        would_be_active = effective_end >= timezone.localdate()
        # Plan inactivo solo se permite en membresías históricas (ya vencidas).
        if would_be_active and not plan.is_active:
            errors.append(RowError(
                row=0, column='Nombre del plan',
                message=(
                    f"El plan '{plan.name}' está inactivo: solo puedes usarlo en "
                    'membresías históricas (con fecha de término ya pasada).'
                ),
            ))
        # Doble activa: el alumno ya tiene otra membresía vigente (no esta misma fila).
        if would_be_active:
            from accounts.models import CustomUser
            from core.models import StudentPlan

            user = values.get('user')
            # Acotado a la organizacion del import: la membresia es de quien la vendio
            # (`plan.organization`). Sin el filtro, una membresia activa de OTRA
            # organizacion bloqueaba una fila legitima y delataba su existencia.
            if isinstance(user, CustomUser) and (
                StudentPlan.objects.filter(
                    user=user, organization_id=organization.id, is_active=True,
                )
                .exclude(start_date=start).exists()
            ):
                errors.append(RowError(
                    row=0, column='Email del alumno',
                    message=(
                        'El alumno ya tiene una membresía activa; el importador no la '
                        'modifica. Usa "Asignar plan" para cambiar la membresía vigente.'
                    ),
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
    from django.db import IntegrityError, connection

    from accounts.models import CustomUser
    from core.models import StudentPlan

    plan = values['plan']
    start = values['start_date']
    end = values.get('end_date') or start + datetime.timedelta(days=max(plan.duration_days - 1, 0))
    # Vigente solo si su fecha de término no pasó: las históricas quedan inactivas
    # y NO las toca el flujo de reservas (que exige is_active + ventana de fechas).
    is_active = end >= timezone.localdate()

    # Guarda anti-doble-activa: SOLO en commit (transacción) y solo si esta fila
    # quedaría activa. Lock del alumno + re-chequeo: si otro proceso (otro import o
    # "Asignar plan") le dejó otra activa en paralelo, abortamos con rollback limpio
    # (400 "vuelve a validar") en vez de dejar dos vigentes. Excluye la propia
    # membresía (misma clave natural user+start) para no bloquear su actualización.
    # En validate (sin transacción) no corre: select_for_update exige atomic.
    if connection.in_atomic_block and is_active:
        CustomUser.objects.select_for_update().get(pk=values['user'].pk)
        if (StudentPlan.objects.filter(
                    user=values['user'],
                    organization_id=organization.id,
                    is_active=True,
                )
                .exclude(start_date=start).exists()):
            raise IntegrityError('el alumno recibió otra membresía activa en paralelo')

    discount = plan.discount_percentage or 0
    if plan.unlimited_classes:
        total, used, unlimited = 0, 0, True
    else:
        total = plan.total_classes
        # 'Clases utilizadas' explícita manda; si no, se deriva de las restantes.
        if values.get('classes_used') is not None:
            used = values['classes_used']
        elif values.get('remaining_classes') is not None:
            used = total - values['remaining_classes']
        else:
            used = 0
        unlimited = False
    return StudentPlan(
        user=values['user'],
        plan=plan,
        # Misma fuente que `activate_student_plan`: la organización del PLAN. El motor
        # verifica que coincida con la del actor (`_commit_create`), así que un plan de
        # otra org —que el lookup de FK ya filtra— nunca llegaría hasta acá.
        organization_id=plan.organization_id,
        # Misma derivación que `activate_student_plan`: la sede queda registrada para
        # los planes exclusivos y en NULL para los globales. Sin esto, onboardear por
        # importador dejaba todas las membresías sin sucursal.
        branch=plan.branch,
        start_date=start,
        end_date=end,
        total_classes=total,
        unlimited_classes=unlimited,
        classes_used=used,
        discount_percentage=discount,
        final_price=max(float(plan.price) * (1 - (discount / 100)), 0),
        enrollment_fee=values.get('enrollment_fee') or 0,
        is_active=is_active,
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
                # Sin filtro is_active: las membresías históricas pueden apuntar a
                # planes ya dados de baja. _membership_rules exige plan activo solo
                # cuando la membresía quedaría vigente.
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
            attr='remaining_classes', label=REMAINING_LABEL, kind='int', updatable=True,
            example='5',
            help_text=(
                'Cuántas clases le quedan HOY al alumno. Alternativa a '
                "'Clases utilizadas': indica una u otra. Déjala vacía si el plan es ilimitado."
            ),
        ),
        FieldSpec(
            attr='classes_used', label=USED_LABEL, kind='int', updatable=True,
            example='3',
            help_text=(
                "Cuántas clases YA usó el alumno. Alternativa a 'Clases restantes'. "
                'Si indicas ambas, deben sumar el total del plan.'
            ),
        ),
        FieldSpec(
            attr='enrollment_fee', label=FEE_LABEL, kind='decimal', updatable=True,
            example='50000',
            help_text='Matrícula del alumno para este plan. Déjala vacía o en 0 si no cobra matrícula.',
        ),
    ),
    natural_key=('user', 'start_date'),
    # Columna propia desde 0030: los tres guardas del motor (dedup, `_commit_create` y
    # `_commit_update`) chequean la organización de la FILA en vez de seguir el join a
    # `plan__organization`. Es más estricto —ve lo que quedó guardado, no lo que el plan
    # implica— y de paso saca el join del dedup.
    org_field='organization',
    # Upsert: una membresía existente (mismo alumno + misma fecha de inicio) se
    # actualiza en vez de omitirse. Sin filtro is_active en el dedup: el histórico
    # inactivo también cuenta como existente (idempotencia al re-importar).
    dedup_filters={},
    updatable_fields=('plan_id', 'total_classes', 'unlimited_classes', 'final_price', 'is_active'),
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
        "También puedes usar '" + USED_LABEL + "' (clases ya consumidas) en vez de las "
        'restantes: indica una u otra. Si pones ambas, deben sumar el total del plan.',
        "'" + FEE_LABEL + "' es opcional: si la dejas vacía o en 0, el alumno no paga matrícula. "
        'Si es mayor a 0, el alumno deberá pagarla antes de poder reservar.',
        'Las fechas van en formato AAAA-MM-DD (ej. 2026-06-01). Si no indicas término, '
        'se calcula automáticamente con la duración del plan.',
        "Si tienes dos planes con el mismo nombre, usa 'Tipo de plan' para distinguirlos.",
    ),
))
