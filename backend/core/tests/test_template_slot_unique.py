"""Tests del cierre de la race de doble consumo por instancia de serie duplicada.

Contexto (ver `task-2-brief.md` de la rama `feat/rolling-window`): dos escritores del
MISMO `(class_template, start_datetime)` -- el botón "Actualizar clases", el cron
`advance_class_windows`, dos tabs, dos admins -- podían pasar los dos el `exists()` de
`generate_instances_for_template_range` (`core/services/recurrence.py`) y crear la MISMA
instancia dos veces. El daño real no era la fila repetida: el sync de recurrencias corre
sobre CADA instancia creada y le cobraba el consumo al alumno DOS veces. El fix (ya
implementado, este archivo solo lo pone a prueba) tiene tres piezas:

1. `GymClass.Meta.constraints` (`core/models.py`, `uniq_class_instance_per_template_slot`):
   `UniqueConstraint` por EXPRESIONES (`F('class_template')`, `F('start_datetime')`), no por
   `fields=[...]` -- con `fields` DRF le inyecta un `UniqueTogetherValidator` al
   `GymClassSerializer` que rompe el POST de una clase suelta (sin plantilla). No se toca
   acá, solo se ejercita indirectamente vía el `IntegrityError` que produce.
2. `generate_instances_for_template_range`: el `GymClass.objects.create(...)` corre dentro
   de un `with transaction.atomic():` (savepoint) + `except IntegrityError` ->
   `summary['skipped'].append({..., 'reason': 'duplicate_instance'})` + `continue`. El
   perdedor de la carrera no suma a `created_ids`, así que su instancia NUNCA entra al sync
   de recurrencias de abajo: pierde limpio, sin cobrar.
3. Migración `0040_gymclass_uniq_class_instance_per_template_slot`
   (`resolve_duplicate_template_instances`): limpia duplicados YA EXISTENTES (datos de antes
   del fix) antes de agregar la constraint, conservando la fila con más historia
   (inscripciones + consumos) y, a igualdad, la más antigua -- borrando las perdedoras
   SIEMPRE vía `_delete_class_refunding_consumption` (reverso de consumo primero, delete
   después) para no dejar saldo fantasma.

Sección A -- race de creación concurrente (ejercita el punto 2, contra la constraint real
de la BD del punto 1): la concurrencia real de dos hilos no es viable en SQLite (que además
es el motor con el que corre esta etapa), así que se usa la simulación determinista que
sugiere el brief: se siembra el "ganador" con una corrida real, y se re-ejecuta el generador
con el `exists()` de la guarda optimista anulado a mano PARA LA PRIMERA LLAMADA que hace el
loop a `GymClass.objects.filter(...)` -- exactamente el interleaving real (los dos
escritores vieron `exists() == False` antes de que el ganador commiteara) -- dejando el
resto de las llamadas (la guarda de fechas siguientes, y el `filter(id__in=...)` del sync
final) yendo al `filter` real: mockear TODAS las llamadas por igual rompería el sync final
en el caso de lote mixto (`list(...)` sobre un Mock sin configurar da `[]`, no las instancias
recién creadas).

Sección B -- migración con duplicados sembrados (ejercita el punto 3): la BD de test YA
tiene la constraint aplicada (viene con las migraciones), así que sembrar un duplicado
requiere sacarla del ESQUEMA a mano con `connection.schema_editor()` y volver a ponerla
SIEMPRE al final (try/finally), para no dejar el resto de la suite corriendo sin la
protección que este mismo módulo prueba.
"""
import importlib
from contextlib import contextmanager
from datetime import time, timedelta
from unittest import mock

import pytest
from django.apps import apps as live_apps
from django.db import connection
from django.utils import timezone

from core.models import (
    Branch,
    ClassTemplate,
    ConsumptionLog,
    Enrollment,
    GymClass,
    Plan,
    RecurringEnrollment,
    StudentPlan,
)
from core.services.recurrence import generate_instances_for_template_range

pytestmark = pytest.mark.django_db

FIRST_OFFSET = 3  # calco de test_rolling_window.py / test_advance_class_windows.py
CONSTRAINT_NAME = 'uniq_class_instance_per_template_slot'

# La migración vive en un módulo cuyo nombre empieza con dígitos (no es un identificador
# Python válido, así que `from core.migrations import 0040_...` no compila): se importa por
# string con `importlib`, que solo resuelve el archivo y no exige sintaxis de atributo.
_migration_module = importlib.import_module(
    'core.migrations.0040_gymclass_uniq_class_instance_per_template_slot'
)
resolve_duplicate_template_instances = _migration_module.resolve_duplicate_template_instances


@pytest.fixture
def setup(make_organization, make_user):
    org = make_organization()
    teacher = make_user('teach-tsu', organization=org, role='teacher')
    student = make_user('alu-tsu', organization=org, role='student', email='alu-tsu@gym.cl')
    branch = Branch.objects.create(organization=org, name='Sede')
    return {'org': org, 'teacher': teacher, 'student': student, 'branch': branch}


def _template(setup, *, first_offset=FIRST_OFFSET, end_date=None, name='Serie'):
    """Plantilla cuyo primer dictado cae a `first_offset` días de hoy (calco de
    `test_rolling_window.py::_template`)."""
    today = timezone.localdate()
    first = today + timedelta(days=first_offset)
    return ClassTemplate.objects.create(
        organization=setup['org'], branch=setup['branch'], teacher=setup['teacher'],
        name=name, weekday=first.weekday(), start_time=time(10, 0), end_time=time(11, 0),
        capacity=20, start_date=today, end_date=end_date,
    )


def _student_plan(org, student, *, total_classes=50, classes_used=0):
    """Membresía vigente y holgada (calco de `test_rolling_window.py::_student_plan`)."""
    today = timezone.localdate()
    plan = Plan.objects.create(
        organization=org, name='Pack', plan_type='pack',
        total_classes=total_classes, duration_days=90, price=30000,
    )
    return StudentPlan.objects.create(
        user=student, plan=plan, organization_id=plan.organization_id,
        start_date=today - timedelta(days=1), end_date=today + timedelta(days=120),
        total_classes=total_classes, classes_used=classes_used, final_price=plan.price,
    )


# ==========================================================================================
# A. Race de creación concurrente.
# ==========================================================================================


@contextmanager
def _first_existence_check_forced_false():
    """Fuerza a `False` el PRIMER `.exists()` que el loop de `generate_instances_for_...
    _template_range` evalúa sobre `GymClass.objects.filter(...)` (la guarda optimista de
    cada iteración) y deja el RESTO de las llamadas -- la guarda de las fechas siguientes, y
    el `filter(id__in=...)` del sync final -- yendo al `filter` real.

    Simula el interleaving exacto de la race: dos escritores pasaron el `exists()` en falso
    (uno porque el ganador todavía no había commiteado cuando lo miró; acá, el perdedor,
    porque se lo forzamos a mano) y el desempate real lo hace el INSERT contra la
    constraint de la BD, no la guarda de aplicación.

    Contar llamadas (en vez de mockear TODAS por igual) es lo que permite el caso de lote
    mixto: si se mockeara cada `filter(...)` de la función por igual, el `filter(id__in=...)`
    del sync final -- que SÍ necesita traer las instancias reales recién creadas -- también
    devolvería el stub, y `sync_recurring_enrollments_for_generated_instances` recibiría una
    lista vacía en vez de la instancia nueva.
    """
    real_filter = GymClass.objects.filter
    state = {'calls': 0}

    def _fake(*args, **kwargs):
        state['calls'] += 1
        if state['calls'] == 1:
            stub = mock.MagicMock()
            stub.exists.return_value = False
            return stub
        return real_filter(*args, **kwargs)

    with mock.patch.object(GymClass.objects, 'filter', side_effect=_fake):
        yield


def test_el_perdedor_de_la_race_saltea_limpio_y_no_cobra_dos_veces(setup):
    """Dos escritores del MISMO `(template, start_datetime)`: el "ganador" ya insertó y
    cobró (generación real, alumno con recurrencia activa). El "perdedor" pasa el
    `exists()` -- se lo anulamos a mano -- e intenta el MISMO insert, que la constraint de
    la BD rechaza con `IntegrityError`. Resultado esperado: CERO fila nueva, CERO cobro
    nuevo, `duplicate_instance` en el summary, y la función sigue de pie (no revienta la
    transacción)."""
    membership = _student_plan(setup['org'], setup['student'])
    only_occurrence = timezone.localdate() + timedelta(days=FIRST_OFFSET)
    template = _template(setup, end_date=only_occurrence)
    RecurringEnrollment.objects.create(
        student=setup['student'], class_template=template,
        start_date=timezone.localdate(), student_plan=membership,
    )

    winner_summary = generate_instances_for_template_range(
        template=template, from_date=template.start_date, until_date=template.end_date,
    )
    assert winner_summary['created_count'] == 1, winner_summary
    membership.refresh_from_db()
    assert membership.classes_used == 1
    assert ConsumptionLog.objects.filter(class_instance__class_template=template).count() == 1

    with _first_existence_check_forced_false():
        loser_summary = generate_instances_for_template_range(
            template=template, from_date=template.start_date, until_date=template.end_date,
        )

    assert loser_summary['created_count'] == 0, loser_summary
    assert loser_summary['created_ids'] == []
    assert [item['reason'] for item in loser_summary['skipped']] == ['duplicate_instance']

    # NO hay segunda GymClass: sigue existiendo UNA sola para ese (template, horario).
    assert GymClass.objects.filter(class_template=template).count() == 1
    # El saldo no se tocó una segunda vez.
    membership.refresh_from_db()
    assert membership.classes_used == 1
    assert ConsumptionLog.objects.filter(class_instance__class_template=template).count() == 1
    # La función no dejó la transacción rota: una query más, en el mismo flujo, funciona.
    assert GymClass.objects.filter(class_template=template).exists()


def test_la_race_no_corta_el_resto_de_la_ventana_tras_perder_una_fecha(setup):
    """Ventana con DOS fechas en la MISMA llamada: la primera ya existe (el "ganador" de una
    corrida previa, acotada solo a ella), la segunda es nueva. Con el `exists()` anulado
    SOLO para la primera iteración del loop, la primera reintenta el INSERT sobre la fila
    que ya existe (pierde, `IntegrityError` capturado por el savepoint) y la SEGUNDA se
    crea de verdad -- con su propia auto-inscripción y consumo. El `continue` del
    perdedor no corta el resto del `for`, y el savepoint interno no deja la transacción
    externa inutilizable para las queries que siguen (el `filter(id__in=...)` del sync
    final, la propia inscripción de la segunda fecha)."""
    membership = _student_plan(setup['org'], setup['student'])
    first_date = timezone.localdate() + timedelta(days=FIRST_OFFSET)
    second_date = first_date + timedelta(days=7)
    template = _template(setup, end_date=second_date)
    RecurringEnrollment.objects.create(
        student=setup['student'], class_template=template,
        start_date=timezone.localdate(), student_plan=membership,
    )

    # Se siembra el "ganador" de la PRIMERA fecha con una corrida real acotada solo a ella.
    first_summary = generate_instances_for_template_range(
        template=template, from_date=template.start_date, until_date=first_date,
    )
    assert first_summary['created_count'] == 1, first_summary
    membership.refresh_from_db()
    assert membership.classes_used == 1

    with _first_existence_check_forced_false():
        second_summary = generate_instances_for_template_range(
            template=template, from_date=template.start_date, until_date=template.end_date,
        )

    # La primera fecha perdió (duplicate_instance); la segunda se creó de verdad.
    assert second_summary['created_count'] == 1, second_summary
    assert len(second_summary['created_ids']) == 1
    assert [item['reason'] for item in second_summary['skipped']] == ['duplicate_instance']

    # Exactamente DOS instancias en total (una por fecha), ninguna duplicada.
    assert GymClass.objects.filter(class_template=template).count() == 2
    assert GymClass.objects.filter(
        class_template=template, start_datetime__date=first_date,
    ).count() == 1

    new_instance = GymClass.objects.get(class_template=template, start_datetime__date=second_date)
    assert Enrollment.objects.filter(
        gym_class=new_instance, student=setup['student'], status='active',
    ).exists(), 'la segunda fecha tiene que haberse auto-inscrito igual que si no hubiera habido race'
    membership.refresh_from_db()
    assert membership.classes_used == 2, 'una unidad de saldo por fecha, ninguna de mas ni de menos'
    assert ConsumptionLog.objects.filter(class_instance__class_template=template).count() == 2


# ==========================================================================================
# B. Migración con duplicado sembrado (`resolve_duplicate_template_instances`).
# ==========================================================================================


def _find_constraint():
    for constraint in GymClass._meta.constraints:
        if constraint.name == CONSTRAINT_NAME:
            return constraint
    raise AssertionError(f'no se encontro la constraint {CONSTRAINT_NAME} en GymClass.Meta')


@contextmanager
def _constraint_lifted():
    """Saca del ESQUEMA la constraint única mientras dura el bloque, para poder sembrar a
    mano dos `GymClass` del mismo `(template, start_datetime)` -- exactamente lo que la
    constraint existe para impedir. La vuelve a poner SIEMPRE al salir (aunque el bloque
    falle): dejar la tabla sin la protección de este mismo módulo contaminaría el resto de
    la suite, y el rollback transaccional de `pytest.mark.django_db` no es excusa para
    saltearse la restauración explícita (ver brief)."""
    constraint = _find_constraint()
    with connection.schema_editor() as schema_editor:
        schema_editor.remove_constraint(GymClass, constraint)
    try:
        yield
    finally:
        with connection.schema_editor() as schema_editor:
            schema_editor.add_constraint(GymClass, constraint)


def _seed_duplicate_pair(setup, template):
    """Dos `GymClass` del MISMO `(template, start_datetime)`, sembradas evadiendo la
    constraint. `older` se crea primero (id menor, calco de "el primer escritor de la
    carrera"). DEBE llamarse DENTRO de `_constraint_lifted()`: la fila resultante viola la
    constraint real hasta que `resolve_duplicate_template_instances` la resuelve, así que
    la restauración tiene que esperar a DESPUÉS de esa llamada -- exactamente el orden que
    la migración real impone (`RunPython` limpia, RECIÉN DESPUÉS `AddConstraint`)."""
    start = timezone.now() + timedelta(days=FIRST_OFFSET)
    older = GymClass.objects.create(
        organization=setup['org'], branch=setup['branch'], teacher=setup['teacher'],
        class_template=template, name='Duplicada vieja',
        start_datetime=start, end_datetime=start + timedelta(hours=1), capacity=20,
    )
    newer = GymClass.objects.create(
        organization=setup['org'], branch=setup['branch'], teacher=setup['teacher'],
        class_template=template, name='Duplicada nueva',
        start_datetime=start, end_datetime=start + timedelta(hours=1), capacity=20,
    )
    return older, newer


@pytest.mark.django_db(transaction=True)
def test_duplicado_con_historia_desigual_sobrevive_el_que_tiene_historia(setup):
    """Par duplicado con historia DESIGUAL: la nueva (id mayor) tiene inscripción + consumo,
    la vieja (id menor) no tiene nada. Sobrevive la que TIENE historia aunque sea la más
    nueva -- la regla mira historia ANTES que antigüedad. La perdedora no tenía consumo, así
    que no hay nada que revertirle al alumno (el saldo no se mueve)."""
    membership = _student_plan(setup['org'], setup['student'])
    template = _template(setup)

    with _constraint_lifted():
        older, newer = _seed_duplicate_pair(setup, template)
        Enrollment.objects.create(gym_class=newer, student=setup['student'], status='active')
        ConsumptionLog.objects.create(
            user=setup['student'], student_plan=membership, class_instance=newer, branch=setup['branch'],
        )
        StudentPlan.objects.filter(pk=membership.pk).update(classes_used=1)
        membership.refresh_from_db()

        # Todavía DENTRO del bloque: la constraint solo puede volver a ponerse una vez que
        # el duplicado ya está resuelto (una sola fila por template+horario), igual que en
        # la migración real.
        resolve_duplicate_template_instances(live_apps, None)

    assert GymClass.objects.filter(pk=newer.pk).exists(), 'sobrevivio la que NO tiene historia'
    assert not GymClass.objects.filter(pk=older.pk).exists()
    membership.refresh_from_db()
    assert membership.classes_used == 1, 'no habia nada que revertir del lado de la perdedora'
    assert ConsumptionLog.objects.filter(student_plan=membership).count() == 1
    # Anti-fantasma: el saldo consumido tiene que igualar los consumos vigentes, SIEMPRE.
    assert membership.classes_used == ConsumptionLog.objects.filter(student_plan=membership).count()


@pytest.mark.django_db(transaction=True)
def test_duplicado_con_historia_pareja_sobrevive_el_mas_antiguo_y_el_saldo_queda_sin_fantasma(setup):
    """Escenario real del bug: LAS DOS instancias duplicadas alcanzaron a cobrarle al mismo
    alumno (el daño real de la race -- doble consumo -- antes de este fix). Con historia
    empatada (1 inscripción + 1 consumo cada una), el desempate es por id: sobrevive la MÁS
    VIEJA. El reverso de la perdedora tiene que devolver su consumo: `classes_used` baja de
    2 a 1, y el log que queda es el de la ganadora -- cero saldo fantasma."""
    membership = _student_plan(setup['org'], setup['student'])
    template = _template(setup)

    with _constraint_lifted():
        older, newer = _seed_duplicate_pair(setup, template)
        for gym_class in (older, newer):
            Enrollment.objects.create(gym_class=gym_class, student=setup['student'], status='active')
            ConsumptionLog.objects.create(
                user=setup['student'], student_plan=membership, class_instance=gym_class, branch=setup['branch'],
            )
        StudentPlan.objects.filter(pk=membership.pk).update(classes_used=2)
        membership.refresh_from_db()
        assert membership.classes_used == 2, 'sanidad: el bug de la race ya habia cobrado dos veces'

        resolve_duplicate_template_instances(live_apps, None)

    assert GymClass.objects.filter(pk=older.pk).exists(), 'no sobrevivio la mas antigua'
    assert not GymClass.objects.filter(pk=newer.pk).exists()
    assert not Enrollment.objects.filter(gym_class_id=newer.pk).exists(), 'la inscripcion de la perdedora tiene que caer con ella'
    membership.refresh_from_db()
    assert membership.classes_used == 1, 'el reverso de la perdedora tiene que devolver su consumo'
    remaining_logs = ConsumptionLog.objects.filter(student_plan=membership)
    assert remaining_logs.count() == 1
    assert remaining_logs.first().class_instance_id == older.pk
    # Anti-fantasma: el saldo consumido tiene que igualar los consumos vigentes, SIEMPRE.
    assert membership.classes_used == ConsumptionLog.objects.filter(student_plan=membership).count()


@pytest.mark.django_db(transaction=True)
def test_duplicado_sin_historia_en_ninguna_sobrevive_el_mas_antiguo(setup):
    """Ninguna de las dos tiene inscripción ni consumo (empate 0-0): el desempate cae en el
    id más chico -- la instancia que el primer escritor de la carrera creó."""
    template = _template(setup)

    with _constraint_lifted():
        older, newer = _seed_duplicate_pair(setup, template)
        resolve_duplicate_template_instances(live_apps, None)

    assert GymClass.objects.filter(pk=older.pk).exists()
    assert not GymClass.objects.filter(pk=newer.pk).exists()


def test_clases_manuales_sin_plantilla_con_mismo_horario_no_se_tocan(setup):
    """`class_template=None` (clase suelta creada a mano): dos clases sueltas en el MISMO
    horario NO son un duplicado para esta función -- la agrupación filtra
    `class_template__isnull=False` a propósito (dos clases sueltas compartiendo horario es
    válido; la constraint también las deja pasar, porque NULL nunca choca con NULL). No
    hace falta sacar la constraint para sembrarlas: los NULL nunca colisionan."""
    start = timezone.now() + timedelta(days=FIRST_OFFSET)
    manual_a = GymClass.objects.create(
        organization=setup['org'], branch=setup['branch'], teacher=setup['teacher'],
        name='Suelta A', start_datetime=start, end_datetime=start + timedelta(hours=1), capacity=20,
    )
    manual_b = GymClass.objects.create(
        organization=setup['org'], branch=setup['branch'], teacher=setup['teacher'],
        name='Suelta B', start_datetime=start, end_datetime=start + timedelta(hours=1), capacity=20,
    )

    resolve_duplicate_template_instances(live_apps, None)

    assert GymClass.objects.filter(pk=manual_a.pk).exists()
    assert GymClass.objects.filter(pk=manual_b.pk).exists()
