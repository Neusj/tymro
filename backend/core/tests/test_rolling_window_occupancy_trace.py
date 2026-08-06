"""El RASTRO de ocupación que deja la poda de la ventana rodante (P3.4 · Pieza 3).

`rolling_window._prune_past_empty_classes` borra las clases pasadas que nadie usó. Ese borrado
es correcto para el calendario y destruye justo el dato más valioso del reporte de ocupación:
qué horarios el gimnasio ofreció y NADIE tomó. Desde P3.4, antes de borrar, la poda escribe un
`ClassOccupancySnapshot` (`services/reports_occupancy.record_occupancy_snapshot`).

Este archivo NO vuelve a mirar el criterio de la poda —eso lo fija `test_advance_class_windows.py`
con su matriz completa— sino el rastro y su acoplamiento con el borrado:

1. `test_a_pruned_class_leaves_its_occupancy_trace` — la clase se va y queda la fila, con
   fecha/disciplina/profe/horario/cupo e `enrolled_count=0`.
2. `test_the_trace_survives_the_class_and_even_the_discipline` — la clase ya no existe (y la
   disciplina/el profe pueden borrarse después): los NOMBRES en texto son lo que sobrevive.
3. `test_running_the_prune_twice_does_not_duplicate_the_trace` y
   `test_writing_the_trace_twice_keeps_a_single_row` — idempotencia. El job corre todos los días
   y la poda atrapa las excepciones POR CLASE: un rastro escrito dos veces inflaría el
   DENOMINADOR del reporte (la misma clase contada dos veces como oferta vacía).
4. `test_a_class_that_does_not_qualify_for_pruning_leaves_no_trace` — sin poda no hay rastro.
5. `test_the_trace_does_not_change_the_prune_summary` — el `pruned_count` que ve el operador
   sigue siendo el mismo.
6. `test_a_failed_deletion_leaves_no_trace` — el par rastro+borrado es UN SOLO HECHO. Si el
   `DELETE` falla, el rastro no puede quedar: la clase sigue viva y el reporte la contaría dos
   veces (la fila viva más su snapshot).

`days_ago=10` en todas las clases podables, por la misma razón que en
`test_advance_class_windows.py`: el colchón de gracia default es de 7 días, así que con 3 o 5 lo
que decidiría el resultado sería el colchón y no lo que el test dice mirar.
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from core.models import (
    Branch,
    ClassOccupancySnapshot,
    Discipline,
    Enrollment,
    GymClass,
)
from core.services import rolling_window
from core.services.reports_occupancy import record_occupancy_snapshot

pytestmark = pytest.mark.django_db


@pytest.fixture
def setup(make_organization, make_user):
    org = make_organization('Gym Rastro')
    return {
        'org': org,
        'branch': Branch.objects.create(organization=org, name='Sede Rastro'),
        'discipline': Discipline.objects.create(organization=org, name='Yoga'),
        'teacher': make_user('teach-trace', organization=org, role='teacher',
                             first_name='Ana', last_name='Profe'),
    }


def _past_class(setup, *, days_ago=10, capacity=12, name='Vacia pasada',
                status=GymClass.Status.SCHEDULED, discipline=True, teacher=True):
    """Clase pasada creada a mano (calco de `test_advance_class_windows.py::_past_class`), con
    disciplina y profe cargados: el rastro tiene que copiar los tres nombres."""
    start = timezone.now() - timedelta(days=days_ago)
    return GymClass.objects.create(
        organization=setup['org'],
        branch=setup['branch'],
        teacher=setup['teacher'] if teacher else None,
        discipline=setup['discipline'] if discipline else None,
        name=name,
        start_datetime=start,
        end_datetime=start + timedelta(hours=1),
        capacity=capacity,
        status=status,
    )


def _run(setup):
    """La fase 3 completa por su vía real (`advance_windows_for_org`), y devuelve el summary."""
    return rolling_window.advance_windows_for_org(setup['org'])


# --------------------------------------------------------------------------------------
# 1. La poda borra la clase y deja el rastro.
# --------------------------------------------------------------------------------------

def test_a_pruned_class_leaves_its_occupancy_trace(setup):
    """Una clase vacía y pasada se poda, y su rastro queda con TODO lo que el reporte de
    ocupación necesita: la fecha/hora real de la clase, el cupo que se ofreció, la sede, la
    disciplina, el profe y los inscritos (0).

    `enrolled_count=0` no está hardcodeado en el escritor: se cuenta de verdad de las
    inscripciones activas. Hoy es siempre 0 porque la poda solo alcanza clases con
    `enrollments__isnull=True`, y este assert es el que fija esa equivalencia."""
    gym_class = _past_class(setup)
    class_id = gym_class.pk

    _run(setup)

    assert not GymClass.objects.filter(pk=class_id).exists(), 'la poda no borró la clase'
    snapshot = ClassOccupancySnapshot.objects.get(organization=setup['org'],
                                                 source_class_id=class_id)
    assert snapshot.source == ClassOccupancySnapshot.SOURCE_PRUNE
    assert snapshot.start_datetime == gym_class.start_datetime
    assert snapshot.end_datetime == gym_class.end_datetime
    assert snapshot.capacity == 12
    assert snapshot.enrolled_count == 0
    assert snapshot.class_name == gym_class.name
    assert snapshot.branch_id == setup['branch'].id
    assert snapshot.branch_name == 'Sede Rastro'
    assert snapshot.discipline_id == setup['discipline'].id
    assert snapshot.discipline_name == 'Yoga'
    assert snapshot.teacher_id == setup['teacher'].id
    # Nombre completo, con fallback al username (patrón de la casa).
    assert snapshot.teacher_name == 'Ana Profe'
    assert snapshot.pruned_at is not None


def test_the_trace_of_a_class_without_discipline_or_teacher_is_still_written(setup):
    """Una clase suelta sin disciplina ni profe también deja rastro: para la ocupación sigue
    siendo oferta que nadie tomó. Los textos quedan vacíos y el reporte la agrupa en su grupo
    explícito ('Sin disciplina')."""
    gym_class = _past_class(setup, discipline=False, teacher=False, name='Suelta sin nada')

    _run(setup)

    snapshot = ClassOccupancySnapshot.objects.get(source_class_id=gym_class.pk)
    assert snapshot.discipline_id is None
    assert snapshot.discipline_name == ''
    assert snapshot.teacher_id is None
    assert snapshot.teacher_name == ''
    assert snapshot.capacity == 12


def test_the_teacher_name_falls_back_to_the_username(setup, make_user):
    """Sin nombre ni apellido cargados, el rastro guarda el username: el texto existe para
    que la fila sea legible cuando la cuenta del profe ya no esté, así que no puede quedar
    vacío solo porque el perfil estaba incompleto."""
    setup['teacher'] = make_user('profe-sin-nombre', organization=setup['org'], role='teacher')
    gym_class = _past_class(setup, name='Vacia con profe sin nombre')

    _run(setup)

    snapshot = ClassOccupancySnapshot.objects.get(source_class_id=gym_class.pk)
    assert snapshot.teacher_name == 'profe-sin-nombre'


# --------------------------------------------------------------------------------------
# 2. El rastro sobrevive a lo que lo originó.
# --------------------------------------------------------------------------------------

def test_the_trace_survives_the_class_and_even_the_discipline(setup):
    """Por esto los nombres se copian como TEXTO además de la FK.

    La clase se borra en la MISMA transacción del rastro (por eso el modelo no tiene FK a
    `GymClass`: sería NULL siempre). Y la sede/disciplina/profe pueden borrarse cualquier día
    después: las tres FK son `SET_NULL`, así que el id se apaga y el texto es lo único que
    queda para que el reporte pueda seguir diciendo 'Yoga a las 9 de la mañana, 0 de 12'."""
    gym_class = _past_class(setup)
    class_id = gym_class.pk
    _run(setup)

    setup['discipline'].delete()
    setup['teacher'].delete()

    snapshot = ClassOccupancySnapshot.objects.get(source_class_id=class_id)
    assert not GymClass.objects.filter(pk=class_id).exists()
    assert snapshot.discipline_id is None
    assert snapshot.teacher_id is None
    assert snapshot.discipline_name == 'Yoga'
    assert snapshot.teacher_name == 'Ana Profe'
    assert snapshot.capacity == 12
    assert snapshot.enrolled_count == 0


# --------------------------------------------------------------------------------------
# 3. Idempotencia.
# --------------------------------------------------------------------------------------

def test_running_the_prune_twice_does_not_duplicate_the_trace(setup):
    """El job corre TODOS LOS DÍAS. Dos corridas seguidas dejan exactamente una fila: la
    segunda no encuentra candidata (lo borrado no vuelve a ser candidato) y, si por cualquier
    camino la volviera a visitar, el `get_or_create` por (organización, `source_class_id`) la
    reconoce."""
    gym_class = _past_class(setup)

    _run(setup)
    _run(setup)

    assert ClassOccupancySnapshot.objects.filter(source_class_id=gym_class.pk).count() == 1


def test_writing_the_trace_twice_keeps_a_single_row(setup):
    """Prueba directa del escritor, que es donde vive la garantía: la poda atrapa las
    excepciones POR CLASE, así que un reintento sobre la misma clase (el `DELETE` falló, el job
    volvió a correr) tiene que ENCONTRAR su rastro y no escribir un segundo. Un rastro
    duplicado infla el denominador del reporte —la misma clase contada dos veces como oferta
    vacía— y eso no se ve mirando el porcentaje.

    Además, la segunda escritura no pisa la primera: el rastro fotografía el momento de la
    poda y no hay un segundo momento que valga más."""
    gym_class = _past_class(setup)

    first = record_occupancy_snapshot(gym_class)
    gym_class.capacity = 99
    gym_class.save(update_fields=['capacity'])
    second = record_occupancy_snapshot(gym_class)

    assert first.pk == second.pk
    assert ClassOccupancySnapshot.objects.filter(source_class_id=gym_class.pk).count() == 1
    second.refresh_from_db()
    assert second.capacity == 12, 'la segunda escritura pisó la foto original'


# --------------------------------------------------------------------------------------
# 4. Sin poda no hay rastro.
# --------------------------------------------------------------------------------------

def test_a_class_that_does_not_qualify_for_pruning_leaves_no_trace(setup, make_user):
    """El rastro nace SOLO del borrado automático. Ninguna de estas cuatro se poda —una
    futura, una con historia, una suspendida (decisión humana) y una todavía dentro del colchón
    de gracia— y ninguna deja fila: el snapshot no es un registro de "clases que hubo", es el
    reemplazo de las que la poda destruyó."""
    student = make_user('alu-trace', organization=setup['org'], role='student')
    future = _past_class(setup, days_ago=-5, name='Futura')
    with_history = _past_class(setup, name='Con inscripcion')
    Enrollment.objects.create(gym_class=with_history, student=student, status='cancelled')
    suspended = _past_class(setup, status=GymClass.Status.SUSPENDED, name='Suspendida')
    inside_grace = _past_class(setup, days_ago=3, name='Dentro del colchon')

    summary = _run(setup)

    assert summary['pruned_count'] == 0, summary
    for gym_class in (future, with_history, suspended, inside_grace):
        assert GymClass.objects.filter(pk=gym_class.pk).exists()
    assert not ClassOccupancySnapshot.objects.exists()


# --------------------------------------------------------------------------------------
# 5. El rastro no cambia lo que el operador ve.
# --------------------------------------------------------------------------------------

def test_the_trace_does_not_change_the_prune_summary(setup):
    """`pruned_count` sigue contando CLASES BORRADAS, no filas escritas: el operador del cron
    lee ese número y no puede empezar a ver el doble (ni cero) porque ahora hay un escritor más
    dentro de la transacción. Y `prune_errors` vacío: el rastro no introduce fallas."""
    _past_class(setup, name='Vacia 1')
    _past_class(setup, name='Vacia 2')
    _past_class(setup, days_ago=3, name='Dentro del colchon')

    summary = _run(setup)

    assert summary['pruned_count'] == 2, summary
    assert summary['prune_errors'] == []
    assert ClassOccupancySnapshot.objects.count() == 2


# --------------------------------------------------------------------------------------
# 6. Atomicidad: el rastro y el borrado son UN SOLO HECHO.
# --------------------------------------------------------------------------------------

def test_a_failed_deletion_leaves_no_trace(setup, monkeypatch):
    """Si el `DELETE` revienta, el rastro se va con él (la transacción por clase de la poda los
    envuelve a los dos).

    Es el invariante que obliga a escribir el rastro DENTRO de esa transacción: con un rastro
    commiteado y la clase todavía viva, el reporte contaría la misma clase DOS VECES —la fila
    viva más su snapshot— e inventaría oferta que nunca existió. El fallo tiene que quedar
    visible como error de la corrida, no en silencio."""
    gym_class = _past_class(setup)

    def _boom(locked):
        raise RuntimeError('delete boom')

    monkeypatch.setattr(rolling_window, '_delete_class_refunding_consumption', _boom)

    summary = _run(setup)

    assert GymClass.objects.filter(pk=gym_class.pk).exists()
    assert not ClassOccupancySnapshot.objects.exists(), (
        'quedó un rastro de una clase que sigue viva: el reporte la contaría dos veces'
    )
    assert summary['pruned_count'] == 0
    assert len(summary['prune_errors']) == 1
    assert str(gym_class.pk) in summary['prune_errors'][0]
