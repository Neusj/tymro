"""7.1 — `StudentPlan.organization` propia, y N membresías activas por alumno.

La columna existe para que la organización de una membresía no dependa de seguir el join
`plan__organization`: la escriben `activate_student_plan` y el importador, la leen las
guardas multitenant del motor de importación, y `PROTECT` impide que borrar una
organización se lleve en cascada el historial de cobros y consumo que la respalda.

Lo que acá NO se impone es unicidad. Un alumno puede tener varias membresías vigentes al
mismo tiempo en la misma organización —el caso normal es contratar dos disciplinas, p. ej.
un plan de 4 BJJ y otro de 8 kickboxing—. Activar no desactiva nada y cada contratación es
su propia fila.

La fuente de verdad de la columna es SIEMPRE `plan.organization` —nunca
`user.organization`—. El alumno movido de organización conserva vivas las membresías
que le vendió la anterior (`StudentPlan.user` es CASCADE sobre el usuario, no sobre la
org): estamparlas con la org actual del usuario las movería de tenant.
"""
from datetime import timedelta

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from core.models import Plan, StudentPlan
from core.services.plans import activate_student_plan

pytestmark = pytest.mark.django_db

MIGRATION_BEFORE = '0029_plan_studentplan_consumptionlog_branch'
MIGRATION_AFTER = '0030_studentplan_organization'


# --------------------------------------------------------------------------- helpers


@pytest.fixture
def migrator(transactional_db):
    """Migra la DB de test hacia atrás/adelante para ejercitar el backfill de datos.

    El teardown vuelve SIEMPRE al head: un test que dejara la DB en 0029 haría correr
    al resto de la suite contra un esquema viejo.
    """

    def _migrate(target):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate([('core', target)])
        executor.loader.build_graph()
        return executor.loader.project_state([('core', target)]).apps

    yield _migrate

    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(executor.loader.graph.leaf_nodes())


def _legacy_membership(user, plan, is_active=True, start_offset=0):
    """Inserta una membresía con el esquema PREVIO a 0030 (sin `organization`).

    Va por SQL crudo a propósito. Los modelos históricos de `project_state` no sirven acá:
    el estado se arma siguiendo solo los ancestros de `core.0029`, así que `CustomUser`
    aparece sin las columnas que le agregaron migraciones de `accounts` posteriores —que
    la tabla real sí tiene y son NOT NULL—. Y el modelo real tampoco sirve: todavía no
    existe la columna que va a escribir.
    """
    today = timezone.localdate()
    with connection.cursor() as cursor:
        # Los booleanos van como parámetros y NO como literales: SQLite acepta 0/1 en una
        # columna boolean, PostgreSQL —el motor de producción— la rechaza con
        # DatatypeMismatch. Escribirlos a mano acá haría que el test pase solo en dev.
        cursor.execute(
            """
            INSERT INTO core_studentplan
                (created_at, updated_at, user_id, plan_id, branch_id,
                 start_date, end_date, total_classes, unlimited_classes, classes_used,
                 discount_percentage, final_price, enrollment_fee, is_active)
            VALUES (%s, %s, %s, %s, NULL, %s, %s, 10, %s, 0, 0, 30000, 0, %s)
            """,
            [
                timezone.now(), timezone.now(), user.pk, plan.pk,
                today - timedelta(days=start_offset), today + timedelta(days=30),
                False, is_active,
            ],
        )


def _plan_for(org, name='Pack 10'):
    return Plan.objects.create(
        organization=org, name=name, plan_type='pack',
        total_classes=10, duration_days=30, price=30000,
    )


def _membership(user, plan, **extra):
    today = timezone.localdate()
    defaults = dict(
        user=user, plan=plan, organization=plan.organization,
        start_date=today, end_date=today + timedelta(days=30),
        # Derivado del plan, igual que `activate_student_plan`: con dos planes distintos
        # cada membresía tiene que quedar con SU saldo. Estaba fijo en 10 y hacía que dos
        # membresías de planes distintos salieran con el mismo total.
        total_classes=plan.total_classes, classes_used=0,
    )
    defaults.update(extra)
    return StudentPlan.objects.create(**defaults)


# --------------------------------------------------------------------------- backfill


def test_backfill_stamps_the_organization_of_the_plan_not_of_the_user(
    migrator, make_organization, make_user,
):
    """El caso que hace que la fuente importe: alumno movido de la org A a la B con una
    membresía viva que le vendió A. Debe quedar en A —quien la vendió—, no en B."""
    org_a = make_organization()
    org_b = make_organization()
    student = make_user('nomade', organization=org_a, role='student')
    plan_a = _plan_for(org_a)

    migrator(MIGRATION_BEFORE)
    _legacy_membership(student, plan_a)
    # El alumno se muda a la org B; la membresía de A queda viva apuntando al plan de A.
    student.organization = org_b
    student.save(update_fields=['organization'])

    apps = migrator(MIGRATION_AFTER)
    HistoricalStudentPlan = apps.get_model('core', 'StudentPlan')

    migrated = HistoricalStudentPlan.objects.get(user_id=student.id)
    assert migrated.organization_id == org_a.id, 'la membresía la vendió A, no B'
    assert migrated.organization_id != org_b.id


def test_backfill_resolves_a_membership_of_an_orphan_user(
    migrator, make_organization, make_user,
):
    """`CustomUser.organization` es SET_NULL: un usuario puede quedar sin organización.
    Como la fuente es `plan.organization` (NOT NULL), el huérfano se resuelve igual."""
    org = make_organization()
    student = make_user('huerfano', organization=org, role='student')
    plan = _plan_for(org)

    migrator(MIGRATION_BEFORE)
    _legacy_membership(student, plan)
    student.organization = None
    student.save(update_fields=['organization'])

    apps = migrator(MIGRATION_AFTER)
    HistoricalStudentPlan = apps.get_model('core', 'StudentPlan')

    assert HistoricalStudentPlan.objects.get(user_id=student.id).organization_id == org.id


def test_backfill_migrates_a_student_with_two_active_memberships(
    migrator, make_organization, make_user,
):
    """Un alumno con dos membresías vigentes en la misma organización es un dato VÁLIDO
    (dos disciplinas), y la migración tiene que estamparlas a las dos sin chistar.

    Reemplaza a un test anterior que exigía lo contrario: 0030 llegó a traer un pre-chequeo
    que abortaba la migración en este escenario, para poder crear un índice único que ya no
    existe. Ese pre-chequeo habría volteado la migración justo para los alumnos con más de
    un plan contratado.
    """
    org = make_organization()
    student = make_user('dos_disciplinas', organization=org, role='student')
    bjj = _plan_for(org, name='BJJ 4')
    kick = _plan_for(org, name='Kick 8')

    migrator(MIGRATION_BEFORE)
    _legacy_membership(student, bjj, start_offset=10)
    _legacy_membership(student, kick, start_offset=0)

    apps = migrator(MIGRATION_AFTER)
    HistoricalStudentPlan = apps.get_model('core', 'StudentPlan')

    memberships = HistoricalStudentPlan.objects.filter(user_id=student.id)
    assert memberships.count() == 2
    assert memberships.filter(is_active=True).count() == 2
    assert {m.organization_id for m in memberships} == {org.id}


def test_backfill_leaves_no_null_organization(migrator, make_organization, make_user):
    org = make_organization()
    plan = _plan_for(org)
    students = [make_user(f'alu{n}', organization=org, role='student') for n in range(3)]

    migrator(MIGRATION_BEFORE)
    for student in students:
        _legacy_membership(student, plan)

    migrator(MIGRATION_AFTER)

    assert StudentPlan.objects.count() == 3
    assert not StudentPlan.objects.filter(organization__isnull=True).exists()


# ------------------------------------------------- N membresías activas por alumno


def test_two_active_memberships_in_the_same_org_coexist(make_organization, make_user):
    """La regla de negocio: dos disciplinas contratadas a la vez conviven.

    Invierte un test anterior que exigía que la DB RECHAZARA la segunda activa. Ese
    comportamiento venía de un `UniqueConstraint(user, organization)` parcial que resultó
    ser un bug: impedía el caso más común de un gimnasio con más de una disciplina.
    """
    org = make_organization()
    student = make_user('alu', organization=org, role='student')
    bjj = Plan.objects.create(organization=org, name='BJJ 4', plan_type='pack',
                              total_classes=4, duration_days=30, price=20000)
    kick = Plan.objects.create(organization=org, name='Kick 8', plan_type='pack',
                               total_classes=8, duration_days=30, price=30000)

    first = _membership(student, bjj, is_active=True)
    second = _membership(student, kick, is_active=True)

    active = StudentPlan.objects.filter(user=student, is_active=True)
    assert active.count() == 2
    assert {m.pk for m in active} == {first.pk, second.pk}
    # Cada una conserva su propio saldo: no se fusionan ni se pisan.
    assert {m.total_classes for m in active} == {4, 8}


def test_no_uniqueness_constraint_on_active_memberships():
    """Fija la ausencia del constraint, no su forma: si alguien lo reintroduce, este test
    lo detiene antes de que vuelva a romper el alumno con dos disciplinas."""
    names = {c.name for c in StudentPlan._meta.constraints}
    assert 'uniq_active_student_plan_per_org' not in names
    assert names == set(), f'constraints inesperados en StudentPlan: {names}'


def test_two_active_memberships_are_allowed_in_different_organizations(
    make_organization, make_user,
):
    """Caso aparte del de arriba: acá las dos activas son de organizaciones DISTINTAS.
    No es un alumno "en dos organizaciones" —`CustomUser.organization` es una FK simple—:
    es el residuo de un alumno movido de org, que conserva viva la membresía que le vendió
    la anterior. Sigue siendo legítimo, y ninguna org puede tocar la de la otra."""
    org_a = make_organization()
    org_b = make_organization()
    student = make_user('nomade', organization=org_a, role='student')
    plan_a = Plan.objects.create(organization=org_a, name='Pack A', plan_type='pack',
                                 total_classes=10, duration_days=30, price=30000)
    plan_b = Plan.objects.create(organization=org_b, name='Pack B', plan_type='pack',
                                 total_classes=10, duration_days=30, price=30000)

    _membership(student, plan_a, is_active=True)
    student.organization = org_b
    student.save(update_fields=['organization'])
    _membership(student, plan_b, is_active=True)

    assert StudentPlan.objects.filter(user=student, is_active=True).count() == 2
    assert StudentPlan.objects.filter(user=student, organization=org_a).count() == 1
    assert StudentPlan.objects.filter(user=student, organization=org_b).count() == 1


def test_a_membership_cannot_be_saved_with_an_organization_other_than_its_plans(
    make_organization, make_user,
):
    """`organization` es una copia de `plan.organization` y el esquema no obliga a que
    sigan iguales. Importa porque las guardas multitenant del importador pasaron a leer
    esta columna: una fila desincronizada dejaría que la org B reclame —y reactive— una
    membresía que vendió la org A y que el resto del código sigue mostrando como de A."""
    from django.core.exceptions import ValidationError as DjangoValidationError

    org_a = make_organization()
    org_b = make_organization()
    student = make_user('alu', organization=org_a, role='student')
    plan_a = Plan.objects.create(organization=org_a, name='Pack A', plan_type='pack',
                                 total_classes=10, duration_days=30, price=30000)

    today = timezone.localdate()
    desynced = StudentPlan(
        user=student, plan=plan_a, organization=org_b,
        start_date=today, end_date=today + timedelta(days=30), total_classes=10,
    )

    with pytest.raises(DjangoValidationError) as excinfo:
        desynced.full_clean()

    assert 'organization' in excinfo.value.message_dict


# ------------------------------------------------------------------------- activate


def test_activate_student_plan_stamps_the_organization_of_the_plan(
    make_organization, make_user,
):
    org = make_organization()
    student = make_user('alu', organization=org, role='student')
    plan = Plan.objects.create(organization=org, name='Mensual', plan_type='monthly',
                               total_classes=12, duration_days=30, price=30000)

    sp = activate_student_plan(student=student, plan=plan,
                               start_date=timezone.localdate())

    assert sp.organization_id == plan.organization_id
    assert sp.organization_id == org.id


def test_activate_does_not_deactivate_the_other_memberships(
    make_organization, make_user,
):
    """Activar agrega, no reemplaza.

    `activate_student_plan` hacía `filter(user=..., is_active=True).update(is_active=False)`
    antes de crear la nueva fila. Eso era un bug: al contratar kickboxing le apagaba al
    alumno el plan de BJJ que estaba usando. Cada contratación es independiente.
    """
    org = make_organization()
    student = make_user('alu', organization=org, role='student')
    bjj = Plan.objects.create(organization=org, name='BJJ 4', plan_type='pack',
                              total_classes=4, duration_days=30, price=20000)
    kick = Plan.objects.create(organization=org, name='Kick 8', plan_type='pack',
                               total_classes=8, duration_days=30, price=30000)

    today = timezone.localdate()
    first = activate_student_plan(student=student, plan=bjj, start_date=today)
    second = activate_student_plan(student=student, plan=kick, start_date=today)

    first.refresh_from_db()
    assert first.is_active is True, 'la membresía previa no puede quedar desactivada'
    assert second.is_active is True
    assert StudentPlan.objects.filter(user=student, is_active=True).count() == 2


def test_activating_the_same_plan_twice_creates_a_new_row(make_organization, make_user):
    """"Contratar nuevamente" no reusa ni muta la fila anterior: crea otra.

    Es la invariante que la UI de renovación tiene que respetar —ver la nota de diseño en
    `core/services/plans.py`—: el historial de lo ya cobrado queda intacto.
    """
    org = make_organization()
    student = make_user('alu', organization=org, role='student')
    plan = Plan.objects.create(organization=org, name='Mensual', plan_type='monthly',
                               total_classes=12, duration_days=30, price=30000)

    today = timezone.localdate()
    first = activate_student_plan(student=student, plan=plan, start_date=today)
    second = activate_student_plan(student=student, plan=plan,
                                   start_date=today + timedelta(days=30))

    assert second.pk != first.pk
    first.refresh_from_db()
    assert first.start_date == today, 'no se le pueden mover las fechas a la anterior'
    assert first.total_classes == 12 and first.classes_used == 0
    assert StudentPlan.objects.filter(user=student, plan=plan).count() == 2


# ------------------------------------------------------- consecuencia del PROTECT


def _login(api_client, username):
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.get(username=username)
    host = {'HTTP_HOST': f'{user.organization.subdomain}.localhost'} if user.organization_id else {}
    token = api_client.post(
        '/api/login/', {'email': user.email, 'password': 'Passw0rd2026'},
        format='json', **host,
    ).json()['token']
    api_client.credentials(HTTP_AUTHORIZATION=f'Token {token}')


def test_deleting_an_organization_with_sold_memberships_is_blocked(
    api_client, make_organization, make_user,
):
    """Consecuencia directa de `PROTECT`: borrar la organización ya no puede llevarse en
    cascada las membresías que vendió (y con ellas el historial de consumo y los precios
    cobrados). Antes de 0030 la cascada Organization → Plan → StudentPlan lo hacía en
    silencio.

    Lo que se exige acá es que la negativa llegue como un 400 explicando qué la bloquea,
    no como el `ProtectedError` crudo convertido en 500.
    """
    org = make_organization()
    student = make_user('alu', organization=org, role='student')
    plan = Plan.objects.create(organization=org, name='Pack 10', plan_type='pack',
                               total_classes=10, duration_days=30, price=30000)
    _membership(student, plan, is_active=True)
    make_user('root', role='superadmin', organization=None)
    _login(api_client, 'root')

    resp = api_client.delete(f'/api/organizations/{org.id}/')

    assert resp.status_code == 400, resp.content
    assert 'membresías' in resp.json()['detail']
    assert StudentPlan.objects.filter(user=student).exists()
    assert Plan.objects.filter(pk=plan.pk).exists()


def test_an_organization_without_memberships_can_still_be_deleted(
    api_client, make_organization, make_user,
):
    """La guarda tiene que ser específica: sin membresías vendidas, el borrado sigue."""
    from core.models import Organization

    org = make_organization()
    Plan.objects.create(organization=org, name='Pack 10', plan_type='pack',
                        total_classes=10, duration_days=30, price=30000)
    make_user('root', role='superadmin', organization=None)
    _login(api_client, 'root')

    resp = api_client.delete(f'/api/organizations/{org.id}/')

    assert resp.status_code == 204, resp.content
    assert not Organization.objects.filter(pk=org.pk).exists()


# NOTA sobre los locks: acá NO hay tests de concurrencia, porque ya no hay lock que
# verificar. `activate_student_plan` llegó a tomar `SELECT ... FOR UPDATE` sobre las
# membresías del alumno y sobre su fila de usuario, para volver atómico el par
# "desactivar las vigentes + crear la nueva". Al desaparecer el auto-desactivado, la
# función quedó como un INSERT suelto: no hay secuencia leer-y-después-escribir que
# proteger, y dos activaciones concurrentes creando dos filas es el resultado correcto.
#
# Los locks se quitaron, y con ellos sus dos tests. De paso desaparece el AB-BA que
# introducían contra el importador, que lockea en el orden inverso (`_commit_update`
# toma la fila de StudentPlan y recién después `_build_membership` la del alumno).
