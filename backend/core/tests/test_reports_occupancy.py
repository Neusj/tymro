"""Reporte de ocupación (P3.4 · Pieza 3): `services/reports_occupancy.build_occupancy_report`
y su puerta HTTP `GET /api/reports/occupancy/`.

LO QUE ESTE ARCHIVO DEFIENDE, en una línea: **el porcentaje de ocupación no puede mejorar
solo porque pasó el tiempo.** El reporte suma DOS fuentes —las clases vivas del rango y el
rastro (`ClassOccupancySnapshot`) de las que la poda de la ventana rodante ya borró— porque lo
que la poda se lleva son exactamente las clases que nadie tomó. Sin la segunda fuente, el
histórico de un mes cerrado se vería cada vez mejor a medida que sus clases vacías desaparecen
de la base. `test_the_prune_trace_lowers_the_occupancy_rate` es ESE test.

El resto fija los bordes que un reporte agregado puede equivocar sin que nadie lo note:

* qué estados cuentan como oferta dictada (`cancelled`/`suspended` no se dictaron; y el
  `is_active=False` que acompaña a todo cierre terminal NO puede vaciar el reporte del mes
  pasado — ver `test_terminal_states_that_did_not_happen_do_not_count`);
* llenas vs. vacías vs. a medias, y el cupo 0 que no tiene denominador;
* los tres cortes (disciplina, hora local, serie con ceros);
* y el aislamiento: organización del ACTOR, sede y disciplina verificadas, roles.
"""
from datetime import datetime, timedelta

import pytest
from django.utils import timezone

from core.models import (
    Branch,
    ClassOccupancySnapshot,
    Discipline,
    Enrollment,
    GymClass,
)
from core.services.reports_base import GRANULARITY_DAY, GRANULARITY_MONTH, ReportScope
from core.services.reports_occupancy import build_occupancy_report, occupancy_export_spec

pytestmark = pytest.mark.django_db

URL = '/api/reports/occupancy/'


# --------------------------------------------------------------------------------------
# Fixtures y helpers. Las clases se crean con hora LOCAL explícita (`_local`): el corte
# `by_hour` es por hora del gimnasio (`America/Santiago`), así que un helper que use UTC haría
# que los tests pasaran o fallaran según la época del año.
# --------------------------------------------------------------------------------------

@pytest.fixture
def org(make_organization):
    return make_organization('Gym Ocupación')


@pytest.fixture
def branch(org):
    return Branch.objects.create(organization=org, name='Sede Centro')


@pytest.fixture
def teacher(org, make_user):
    return make_user('teach-occ', organization=org, role='teacher',
                     first_name='Ana', last_name='Profe')


@pytest.fixture
def admin(org, make_user):
    return make_user('admin-occ', organization=org, role='gym_admin')


def _local(day, hour, minute=0):
    """Datetime aware en la zona del proyecto para `day` a las `hour:minute` locales."""
    return timezone.make_aware(datetime(day.year, day.month, day.day, hour, minute))


def _gym_class(org, branch, *, day, hour=10, capacity=10, teacher=None, discipline=None,
               status=GymClass.Status.SCHEDULED, is_active=True, name='Clase'):
    start = _local(day, hour)
    return GymClass.objects.create(
        organization=org, branch=branch, teacher=teacher, discipline=discipline,
        name=name, start_datetime=start, end_datetime=start + timedelta(hours=1),
        capacity=capacity, status=status, is_active=is_active,
    )


def _snapshot(org, *, day, hour=10, capacity=10, branch=None, discipline=None,
              discipline_name='', enrolled=0, source_class_id=None, name='Clase podada'):
    """Rastro de una clase ya borrada por la poda (lo que escribe
    `record_occupancy_snapshot`; acá se arma a mano para no acoplar este archivo al job)."""
    start = _local(day, hour)
    return ClassOccupancySnapshot.objects.create(
        organization=org,
        source_class_id=source_class_id or (ClassOccupancySnapshot.objects.count() + 9000),
        branch=branch,
        branch_name=getattr(branch, 'name', '') or '',
        discipline=discipline,
        discipline_name=discipline_name or getattr(discipline, 'name', '') or '',
        class_name=name,
        start_datetime=start,
        end_datetime=start + timedelta(hours=1),
        capacity=capacity,
        enrolled_count=enrolled,
    )


def _enroll(gym_class, students, *, status='active'):
    for student in students:
        Enrollment.objects.create(gym_class=gym_class, student=student, status=status)


def _students(org, make_user, count, prefix='alu-occ'):
    return [
        make_user(f'{prefix}-{index}', organization=org, role='student')
        for index in range(count)
    ]


def _scope(org, *, date_from, date_to, granularity=GRANULARITY_DAY, branch=None):
    return ReportScope(organization_id=org.id, date_from=date_from, date_to=date_to,
                       granularity=granularity, branch=branch)


# --------------------------------------------------------------------------------------
# 1. Llenas, a medias y vacías.
# --------------------------------------------------------------------------------------

def test_full_half_and_empty_classes_are_counted_separately(org, branch, make_user):
    """Tres clases del mismo día: una llena (5/5), una a medias (2/5) y una vacía (0/5).

    Fija las tres definiciones a la vez porque se calculan en el mismo recorrido:
    `full_classes` es `enrolled >= capacity`, `empty_classes` es `enrolled == 0`, y la
    ocupación total es la suma de inscritos sobre la suma de cupos (7/15), NO el promedio de
    los tres porcentajes —que daría 46,7 % y le daría el mismo peso a una clase de 5 cupos que
    a una de 50—."""
    today = timezone.localdate()
    full = _gym_class(org, branch, day=today, hour=8, capacity=5, name='Llena')
    half = _gym_class(org, branch, day=today, hour=9, capacity=5, name='Media')
    _gym_class(org, branch, day=today, hour=10, capacity=5, name='Vacia')
    _enroll(full, _students(org, make_user, 5, 'full'))
    _enroll(half, _students(org, make_user, 2, 'half'))

    data = build_occupancy_report(_scope(org, date_from=today, date_to=today))

    assert data['totals'] == {
        'classes': 3,
        'capacity': 15,
        'enrolled': 7,
        'occupancy_rate': 46.7,   # 7/15
        'full_classes': 1,
        'empty_classes': 1,
        'pruned_classes': 0,
    }


def test_a_cancelled_enrollment_is_not_an_occupied_seat(org, branch, make_user):
    """Una inscripción `cancelled` no ocupa plaza: la clase queda VACÍA para el reporte.

    Es la diferencia con el filtro de la poda, que sí protege a la clase con una inscripción
    cancelada (alguien reservó y se bajó: es historia). Para la ocupación, en cambio, esa
    plaza no se usó."""
    today = timezone.localdate()
    gym_class = _gym_class(org, branch, day=today, capacity=4)
    _enroll(gym_class, _students(org, make_user, 2, 'canc'), status='cancelled')

    data = build_occupancy_report(_scope(org, date_from=today, date_to=today))

    assert data['totals']['enrolled'] == 0
    assert data['totals']['empty_classes'] == 1
    assert data['totals']['occupancy_rate'] == 0.0


def test_a_class_without_declared_capacity_counts_but_has_no_denominator(org, branch, make_user):
    """Cupo 0: la clase se dictó (cuenta en `classes`) pero no aporta denominador — dividir
    por cero no es 0 % ni 100 %, es una pregunta sin respuesta. Con la clase de cupo 0 al lado
    de una 2/4, la ocupación tiene que seguir siendo 50 % y no romperse."""
    today = timezone.localdate()
    normal = _gym_class(org, branch, day=today, hour=8, capacity=4, name='Con cupo')
    _gym_class(org, branch, day=today, hour=9, capacity=0, name='Sin cupo')
    _enroll(normal, _students(org, make_user, 2, 'cap0'))

    data = build_occupancy_report(_scope(org, date_from=today, date_to=today))

    assert data['totals']['classes'] == 2
    assert data['totals']['capacity'] == 4
    assert data['totals']['occupancy_rate'] == 50.0
    # La de cupo 0 no está "llena" (con `capacity=0`, `enrolled >= capacity` es siempre cierto)
    # pero sí está vacía: cero inscritos es cero inscritos.
    assert data['totals']['full_classes'] == 0
    assert data['totals']['empty_classes'] == 1


# --------------------------------------------------------------------------------------
# 2. EL test del archivo: el rastro de la poda alimenta el histórico y BAJA el porcentaje.
# --------------------------------------------------------------------------------------

def test_the_prune_trace_lowers_the_occupancy_rate(org, branch, make_user):
    """Mismo período, dos lecturas: sin rastro y con rastro.

    La clase viva está 4/5 (80 %). Al aparecer el rastro de una clase vacía de 5 cupos que la
    poda borró, la ocupación real del período era 4/10 = 40 %: la mitad de la oferta no se
    vendió. Sin la segunda fuente el reporte diría 80 % y ese número MEJORARÍA con el tiempo,
    porque la poda va borrando justo las clases que nadie tomó.

    Se asserta el ANTES y el DESPUÉS en el mismo test a propósito: el punto no es que el
    número sea 40, es que el rastro lo BAJA."""
    today = timezone.localdate()
    live = _gym_class(org, branch, day=today, hour=8, capacity=5, name='Viva casi llena')
    _enroll(live, _students(org, make_user, 4, 'trace'))
    scope = _scope(org, date_from=today, date_to=today)

    optimistic = build_occupancy_report(scope)
    assert optimistic['totals']['occupancy_rate'] == 80.0
    assert optimistic['totals']['pruned_classes'] == 0

    _snapshot(org, day=today, hour=9, capacity=5, branch=branch)

    honest = build_occupancy_report(scope)

    assert honest['totals']['occupancy_rate'] == 40.0
    assert honest['totals']['occupancy_rate'] < optimistic['totals']['occupancy_rate']
    assert honest['totals']['classes'] == 2
    assert honest['totals']['capacity'] == 10
    assert honest['totals']['empty_classes'] == 1
    # `pruned_classes` publica cuánto del denominador ya no tiene fila viva detrás.
    assert honest['totals']['pruned_classes'] == 1
    # El rastro también entra en los cortes, no solo en el total.
    assert [point['classes'] for point in honest['series']] == [2]
    assert sorted(item['hour'] for item in honest['by_hour']) == [8, 9]


def test_the_trace_of_another_period_does_not_leak_into_this_one(org, branch):
    """El rastro se filtra por la fecha de la CLASE (`start_datetime`), no por cuándo se podó:
    la poda corre días después, y un snapshot de junio no puede aparecer en el reporte de
    julio solo porque el cron lo escribió en julio."""
    today = timezone.localdate()
    _snapshot(org, day=today - timedelta(days=40), capacity=8, branch=branch)
    inside = _snapshot(org, day=today, capacity=6, branch=branch)

    data = build_occupancy_report(_scope(org, date_from=today, date_to=today))

    assert data['totals']['classes'] == 1
    assert data['totals']['capacity'] == inside.capacity


# --------------------------------------------------------------------------------------
# 3. Estados: qué se dictó y qué no.
# --------------------------------------------------------------------------------------

def test_terminal_states_that_did_not_happen_do_not_count(org, branch):
    """`cancelled` y `suspended` NO son oferta desaprovechada: esa clase no se dictó, y
    contarla con 0 inscritos castigaría al gimnasio por haber cancelado bien.

    Y la mitad que importa más: `completed`/`completed_early` SÍ cuentan aunque lleguen con
    `is_active=False`. En este modelo `is_active` no es un flag independiente —lo apaga TODO
    cierre terminal, incluido el flip automático a `completed` de
    `refresh_status_from_schedule`—, así que un `filter(is_active=True)` parejo dejaría el
    reporte de cualquier mes ya terminado en CERO clases. Este test es la red contra ese
    'arreglo'."""
    today = timezone.localdate()
    _gym_class(org, branch, day=today, hour=7, capacity=5, name='Cancelada',
               status=GymClass.Status.CANCELLED, is_active=False)
    _gym_class(org, branch, day=today, hour=8, capacity=5, name='Suspendida',
               status=GymClass.Status.SUSPENDED, is_active=False)
    _gym_class(org, branch, day=today, hour=9, capacity=5, name='Completada',
               status=GymClass.Status.COMPLETED, is_active=False)
    _gym_class(org, branch, day=today, hour=10, capacity=5, name='Cerrada antes',
               status=GymClass.Status.COMPLETED_EARLY, is_active=False)
    _gym_class(org, branch, day=today, hour=11, capacity=5, name='En curso',
               status=GymClass.Status.IN_PROGRESS, is_active=True)
    # Programada y dada de baja SIN pasar por ningún cierre: el único caso donde `is_active`
    # todavía dice algo por sí mismo. No cuenta.
    _gym_class(org, branch, day=today, hour=12, capacity=5, name='Programada inactiva',
               status=GymClass.Status.SCHEDULED, is_active=False)

    data = build_occupancy_report(_scope(org, date_from=today, date_to=today))

    assert data['totals']['classes'] == 3, [item['label'] for item in data['by_hour']]
    assert data['totals']['capacity'] == 15
    assert [item['hour'] for item in data['by_hour']] == [9, 10, 11]


# --------------------------------------------------------------------------------------
# 4. Los tres cortes.
# --------------------------------------------------------------------------------------

def test_by_discipline_groups_live_classes_snapshots_and_the_ones_without_discipline(
    org, branch, make_user,
):
    """Un grupo por disciplina, más el grupo explícito de las clases SIN disciplina (que se
    dictaron y ocuparon una sala: es un grupo real, no un hueco).

    El snapshot de la disciplina viva tiene que caer en el MISMO grupo que su clase viva —se
    agrupa por id y por el nombre actual de la disciplina, no por el texto fotografiado—."""
    today = timezone.localdate()
    yoga = Discipline.objects.create(organization=org, name='Yoga')
    crossfit = Discipline.objects.create(organization=org, name='Crossfit')
    yoga_live = _gym_class(org, branch, day=today, hour=8, capacity=5, discipline=yoga)
    _enroll(yoga_live, _students(org, make_user, 5, 'yoga'))
    _snapshot(org, day=today, hour=9, capacity=5, branch=branch, discipline=yoga)
    _gym_class(org, branch, day=today, hour=10, capacity=4, discipline=crossfit)
    _gym_class(org, branch, day=today, hour=11, capacity=2, discipline=None, name='Sin nada')

    data = build_occupancy_report(_scope(org, date_from=today, date_to=today))

    by_name = {item['discipline_name']: item for item in data['by_discipline']}
    assert set(by_name) == {'Yoga', 'Crossfit', 'Sin disciplina'}
    # Yoga: la clase viva llena + el rastro vacío = 5/10.
    assert by_name['Yoga']['classes'] == 2
    assert by_name['Yoga']['discipline_id'] == yoga.id
    assert by_name['Yoga']['capacity'] == 10
    assert by_name['Yoga']['enrolled'] == 5
    assert by_name['Yoga']['occupancy_rate'] == 50.0
    assert by_name['Yoga']['full_classes'] == 1
    assert by_name['Yoga']['empty_classes'] == 1
    assert by_name['Crossfit']['discipline_id'] == crossfit.id
    assert by_name['Crossfit']['occupancy_rate'] == 0.0
    assert by_name['Sin disciplina']['discipline_id'] is None
    assert by_name['Sin disciplina']['classes'] == 1
    # Orden por volumen: Yoga (2 clases) primero.
    assert data['by_discipline'][0]['discipline_name'] == 'Yoga'


def test_a_snapshot_whose_discipline_was_deleted_keeps_its_own_group_by_name(org, branch):
    """La disciplina se borra DESPUÉS de la poda (las FK del snapshot son SET_NULL): la fila
    queda con `discipline_id` NULL y su nombre en texto. No puede caer en 'Sin disciplina' —
    eso borraría la única información que quedó de ella—."""
    today = timezone.localdate()
    pilates = Discipline.objects.create(organization=org, name='Pilates')
    _snapshot(org, day=today, hour=8, capacity=5, branch=branch, discipline=pilates)
    _gym_class(org, branch, day=today, hour=9, capacity=5, discipline=None, name='Sin nada')
    pilates.delete()

    data = build_occupancy_report(_scope(org, date_from=today, date_to=today))

    by_name = {item['discipline_name']: item for item in data['by_discipline']}
    assert set(by_name) == {'Pilates', 'Sin disciplina'}
    assert by_name['Pilates']['discipline_id'] is None
    assert by_name['Pilates']['classes'] == 1


def test_by_hour_uses_the_local_hour_and_only_the_hours_with_classes(org, branch, make_user):
    """La hora es la LOCAL del gimnasio (`America/Santiago`), que es la que el administrador
    reconoce en su grilla; en UTC la clase de las 19:00 aparecería a las 22:00 o 23:00 según
    la época del año. Y solo salen las horas CON clases: rellenar las 24 con ceros ensuciaría
    el gráfico sin informar nada (ningún gimnasio abre a las 4 AM)."""
    today = timezone.localdate()
    early = _gym_class(org, branch, day=today, hour=7, capacity=4, name='Matinal')
    evening = _gym_class(org, branch, day=today, hour=19, capacity=4, name='Vespertina')
    _gym_class(org, branch, day=today, hour=19, capacity=6, name='Vespertina 2')
    _enroll(early, _students(org, make_user, 1, 'early'))
    _enroll(evening, _students(org, make_user, 4, 'even'))

    data = build_occupancy_report(_scope(org, date_from=today, date_to=today))

    assert [item['hour'] for item in data['by_hour']] == [7, 19]
    assert [item['label'] for item in data['by_hour']] == ['07:00', '19:00']
    assert data['by_hour'][0]['occupancy_rate'] == 25.0    # 1/4
    # Las dos clases de las 19 se agregan en un solo punto: 4 inscritos sobre 10 cupos.
    assert data['by_hour'][1]['classes'] == 2
    assert data['by_hour'][1]['occupancy_rate'] == 40.0


def test_the_series_covers_every_bucket_filled_with_zeros(org, branch, make_user):
    """Un punto por CADA día del rango, en orden y con ceros donde no hubo clases: una línea
    que une el día 1 con el día 5 dibuja una pendiente que nadie dictó, y un día sin oferta es
    un dato (el gimnasio cerró), no una ausencia de dato."""
    today = timezone.localdate()
    date_from = today - timedelta(days=4)
    first = _gym_class(org, branch, day=date_from, capacity=4, name='Primera')
    _enroll(first, _students(org, make_user, 2, 'serie'))
    _gym_class(org, branch, day=today, capacity=4, name='Ultima')

    data = build_occupancy_report(_scope(org, date_from=date_from, date_to=today))

    assert [point['bucket'] for point in data['series']] == [
        (date_from + timedelta(days=offset)).isoformat() for offset in range(5)
    ]
    assert [point['classes'] for point in data['series']] == [1, 0, 0, 0, 1]
    assert [point['occupancy_rate'] for point in data['series']] == [50.0, 0.0, 0.0, 0.0, 0.0]
    assert data['period']['days'] == 5
    assert data['period']['granularity'] == GRANULARITY_DAY


def test_a_monthly_granularity_series_has_one_bucket_per_month(org, branch):
    """Con granularidad mensual los buckets son `YYYY-MM` y siguen sin huecos: el rango de un
    trimestre da tres puntos aunque el del medio esté vacío."""
    today = timezone.localdate()
    date_from = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
    _gym_class(org, branch, day=today, capacity=4, name='De este mes')

    data = build_occupancy_report(
        _scope(org, date_from=date_from, date_to=today, granularity=GRANULARITY_MONTH))

    buckets = [point['bucket'] for point in data['series']]
    assert buckets == [f'{date_from.year:04d}-{date_from.month:02d}',
                       f'{today.year:04d}-{today.month:02d}']
    assert data['series'][-1]['classes'] == 1
    assert data['series'][0]['classes'] == 0


# --------------------------------------------------------------------------------------
# 5. Aislamiento por organización — la regla 1 del backend, en las DOS fuentes.
# --------------------------------------------------------------------------------------

def test_classes_and_snapshots_of_another_organization_never_appear(
    org, branch, make_organization, make_user,
):
    """La organización del scope la estampa la view desde el ACTOR. Las dos fuentes se filtran
    por ella: ni una clase viva ni un rastro del gimnasio de al lado puede entrar al
    denominador —serían clases ajenas empeorando (o mejorando) la ocupación propia—."""
    today = timezone.localdate()
    other = make_organization('Gym Vecino')
    other_branch = Branch.objects.create(organization=other, name='Sede vecina')
    mine = _gym_class(org, branch, day=today, hour=8, capacity=5, name='Mia')
    _enroll(mine, _students(org, make_user, 5, 'mine'))
    _gym_class(other, other_branch, day=today, hour=9, capacity=50, name='Ajena vacia')
    _snapshot(other, day=today, hour=10, capacity=40, branch=other_branch)

    data = build_occupancy_report(_scope(org, date_from=today, date_to=today))

    assert data['totals'] == {
        'classes': 1,
        'capacity': 5,
        'enrolled': 5,
        'occupancy_rate': 100.0,
        'full_classes': 1,
        'empty_classes': 0,
        'pruned_classes': 0,
    }


# --------------------------------------------------------------------------------------
# 6. Filtros de sede y de disciplina — en las dos fuentes.
# --------------------------------------------------------------------------------------

def test_the_branch_filter_applies_to_live_classes_and_to_the_trace(org, branch):
    today = timezone.localdate()
    other_branch = Branch.objects.create(organization=org, name='Sede Norte')
    _gym_class(org, branch, day=today, hour=8, capacity=5, name='Centro')
    _gym_class(org, other_branch, day=today, hour=9, capacity=7, name='Norte')
    _snapshot(org, day=today, hour=10, capacity=3, branch=branch)
    _snapshot(org, day=today, hour=11, capacity=9, branch=other_branch)

    data = build_occupancy_report(
        _scope(org, date_from=today, date_to=today, branch=branch))

    assert data['totals']['classes'] == 2
    assert data['totals']['capacity'] == 8          # 5 de la viva + 3 del rastro
    assert data['totals']['pruned_classes'] == 1
    assert data['filters']['branch_id'] == branch.id
    assert data['filters']['branch_name'] == branch.name


def test_the_discipline_filter_applies_to_live_classes_and_to_the_trace(org, branch):
    today = timezone.localdate()
    yoga = Discipline.objects.create(organization=org, name='Yoga')
    spinning = Discipline.objects.create(organization=org, name='Spinning')
    _gym_class(org, branch, day=today, hour=8, capacity=5, discipline=yoga)
    _gym_class(org, branch, day=today, hour=9, capacity=6, discipline=spinning)
    _snapshot(org, day=today, hour=10, capacity=4, branch=branch, discipline=yoga)
    _snapshot(org, day=today, hour=11, capacity=8, branch=branch, discipline=spinning)

    data = build_occupancy_report(
        _scope(org, date_from=today, date_to=today), discipline=yoga)

    assert data['totals']['classes'] == 2
    assert data['totals']['capacity'] == 9          # 5 de la viva + 4 del rastro
    assert data['totals']['pruned_classes'] == 1
    assert data['filters']['discipline_id'] == yoga.id
    assert data['filters']['discipline_name'] == 'Yoga'
    assert [item['discipline_name'] for item in data['by_discipline']] == ['Yoga']


def test_an_empty_period_is_zeros_and_not_an_error(org):
    """Ninguna clase en el rango: el payload sale completo, con la serie en ceros y sin
    división por cero. Es lo que ve un gimnasio recién creado al abrir el reporte."""
    today = timezone.localdate()

    data = build_occupancy_report(_scope(org, date_from=today, date_to=today))

    assert data['totals']['classes'] == 0
    assert data['totals']['occupancy_rate'] == 0.0
    assert data['by_discipline'] == []
    assert data['by_hour'] == []
    assert data['series'] == [{'bucket': today.isoformat(), 'classes': 0, 'capacity': 0,
                               'enrolled': 0, 'occupancy_rate': 0.0}]


# --------------------------------------------------------------------------------------
# 7. La puerta HTTP: `GET /api/reports/occupancy/`.
# --------------------------------------------------------------------------------------

def test_gym_admin_gets_the_report_of_their_own_organization(api_client, org, branch, admin,
                                                             make_user):
    today = timezone.localdate()
    gym_class = _gym_class(org, branch, day=today, capacity=4)
    _enroll(gym_class, _students(org, make_user, 2, 'http'))
    api_client.force_authenticate(user=admin)

    resp = api_client.get(URL, {'date_from': today.isoformat(), 'date_to': today.isoformat()})

    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body['totals']['classes'] == 1
    assert body['totals']['occupancy_rate'] == 50.0
    assert body['period']['date_from'] == today.isoformat()
    assert body['filters'] == {'branch_id': None, 'branch_name': None,
                              'discipline_id': None, 'discipline_name': None}
    assert set(body) == {'period', 'filters', 'totals', 'by_discipline', 'by_hour', 'series'}


@pytest.mark.parametrize('role', ['manager', 'monitor', 'teacher', 'student'])
def test_no_other_organization_role_can_read_the_report(api_client, org, make_user, role):
    """403 para todos: la ocupación viaja con la misma llave que los reportes de plata (ver
    `ReportPermission`). Es una decisión de producto —dato de gestión—, y si mañana el
    manager tiene que verla se abre con una permission propia, no relajando esta."""
    actor = make_user(f'{role}-occ', organization=org, role=role)
    api_client.force_authenticate(user=actor)

    resp = api_client.get(URL)

    assert resp.status_code == 403, resp.content


def test_superadmin_cannot_read_the_report_either(api_client, make_user):
    """El superadmin también 403 (mismo criterio que `PaymentTransactionListView`): es rol de
    plataforma, sin `organization_id` que scopear, y darle este endpoint sería darle la
    ocupación de todos los gimnasios."""
    root = make_user('root-occ', organization=None, role='superadmin')
    api_client.force_authenticate(user=root)

    resp = api_client.get(URL)

    assert resp.status_code == 403, resp.content


def test_unauthenticated_request_is_rejected(api_client):
    assert api_client.get(URL).status_code == 401


def test_a_branch_or_discipline_of_another_organization_is_404(api_client, org, admin,
                                                              make_organization):
    """404 y no 403: los ids son autoincrementales y adivinables, y un 403 confirmaría
    "existe, pero no es tuyo" —delataría la topología de sedes o el catálogo de disciplinas
    del gimnasio de al lado— (mismo criterio anti-oráculo que `views_payments._branch_scope`).
    """
    other = make_organization('Gym Ajeno')
    other_branch = Branch.objects.create(organization=other, name='Sede ajena')
    other_discipline = Discipline.objects.create(organization=other, name='Boxeo ajeno')
    api_client.force_authenticate(user=admin)

    by_branch = api_client.get(URL, {'branch_id': other_branch.id})
    by_discipline = api_client.get(URL, {'discipline_id': other_discipline.id})

    assert by_branch.status_code == 404, by_branch.content
    assert by_discipline.status_code == 404, by_discipline.content


def test_the_report_of_another_admin_does_not_see_my_classes(api_client, org, branch,
                                                             make_organization, make_user):
    """La contraparte por HTTP del scoping: el admin del gimnasio vecino pide el MISMO
    endpoint, sin ningún parámetro de organización (no existe), y ve cero clases."""
    today = timezone.localdate()
    _gym_class(org, branch, day=today, capacity=5, name='Mia')
    other = make_organization('Gym Vecino HTTP')
    other_admin = make_user('admin-vecino-occ', organization=other, role='gym_admin')
    api_client.force_authenticate(user=other_admin)

    resp = api_client.get(URL, {'date_from': today.isoformat(), 'date_to': today.isoformat()})

    assert resp.status_code == 200, resp.content
    assert resp.json()['totals']['classes'] == 0


def test_export_csv_returns_a_spreadsheet_with_the_discipline_breakdown(
    api_client, org, branch, admin, make_user,
):
    """`?export=csv` (el parámetro es `export`, no `format`: DRF reserva `format` para
    negociación de contenido) devuelve `text/csv` con el corte por disciplina y su fila de
    totales, salido del MISMO payload que el JSON."""
    today = timezone.localdate()
    yoga = Discipline.objects.create(organization=org, name='Yoga')
    gym_class = _gym_class(org, branch, day=today, capacity=4, discipline=yoga)
    _enroll(gym_class, _students(org, make_user, 2, 'csv'))
    api_client.force_authenticate(user=admin)

    resp = api_client.get(URL, {'date_from': today.isoformat(), 'date_to': today.isoformat(),
                                'export': 'csv'})

    assert resp.status_code == 200, resp.content
    assert resp['Content-Type'].startswith('text/csv')
    assert 'ocupacion' in resp['Content-Disposition']
    content = resp.content.decode('utf-8-sig')
    assert 'Disciplina' in content
    assert 'Yoga' in content
    assert 'Total' in content


def test_the_export_spec_mirrors_the_payload(org, branch, make_user):
    """El export no vuelve a consultar la base: se arma de `data`, así que la planilla no
    puede divergir del gráfico que el administrador está mirando."""
    today = timezone.localdate()
    yoga = Discipline.objects.create(organization=org, name='Yoga')
    gym_class = _gym_class(org, branch, day=today, capacity=4, discipline=yoga)
    _enroll(gym_class, _students(org, make_user, 3, 'spec'))
    data = build_occupancy_report(_scope(org, date_from=today, date_to=today))

    spec = occupancy_export_spec(data)

    assert spec['header'][0] == 'Disciplina'
    assert len(spec['rows']) == len(data['by_discipline'])
    assert spec['rows'][0][:5] == ['Yoga', 1, 4, 3, 75.0]
    assert spec['total_row'] == ['Total', 1, 4, 3, 75.0, 0, 0]
