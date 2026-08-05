"""Rolling window (Task 2) — la materialización de series se corta en la ventana de la org.

Antes de este cambio, dar de alta una serie recurrente materializaba TODO el horizonte:
`generate_instances_for_template_range` caía en un fallback de 365 días
(`effective_from + timedelta(days=365)`) cuando la plantilla no tenía `end_date`, o sea
~52 filas de `GymClass` por plantilla. Y como el loop de recurrencia
(`create_enrollments_for_recurring_subscription`) auto-inscribe y DESCUENTA saldo por
adelantado en cada instancia que ve (regla #9: `reserve_student_in_class` con el
`student_plan_id` de la suscripción), esas ~52 filas se traducían en ~52 consumos
inmediatos: el alumno quedaba cobrado el año entero el día del alta.

Este archivo fija el contrato nuevo: el horizonte de materialización SIEMPRE está topeado
por `Organization.class_generation_window_days` (Task 1, default 21). `until_date` y
`template.end_date` siguen acotando si son MÁS cortos; nada se materializa más allá de
`hoy + ventana`. El consumo NO cambió de momento (sigue siendo al inscribir): lo que
cambia es el UNIVERSO de instancias que existen para inscribir.

Mapa de casos (los 5 del brief):

1. `test_template_without_end_date_only_materializes_inside_the_window` — sin `end_date`,
   solo las fechas ≤ hoy+21 (3 filas para un weekday), no ~52.
2. `test_each_org_materializes_according_to_its_own_window` — ventanas 7 y 28 en dos orgs.
3. `test_a_shorter_end_date_or_until_date_still_wins` — el más corto sigue mandando.
4. `test_recurring_series_only_enrolls_and_consumes_inside_the_window` (generación) y
   `test_the_self_built_queryset_of_the_loop_is_also_capped_by_the_window` (Pieza B: el
   queryset que arma el loop cuando NO recibe instancias explícitas).
5. `test_reserving_inside_the_window_works_and_outside_there_is_no_row` — reservar dentro
   de la ventana OK; contra una fila inexistente (fuera de ventana no hay fila) el wire
   responde 400/404, nunca 500.

Truco de fechas usado en todo el archivo: el `weekday` de la plantilla se elige para que
la PRIMERA ocurrencia caiga a `FIRST_OFFSET` (3) días de hoy. Así la cantidad de
instancias esperadas es determinista cualquier día que corra la suite
(offsets 3, 10, 17, 24, ...) y ninguna instancia cae hoy (una clase de hoy a las 10:00
podría estar ya empezada y el loop la saltearía con `class_started`).
"""
from datetime import time, timedelta

import pytest
from django.test import override_settings
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
from core.services.recurrence import (
    create_enrollments_for_recurring_subscription,
    generate_instances_for_template_range,
)

pytestmark = pytest.mark.django_db

PASSWORD = 'Passw0rd2026'
FIRST_OFFSET = 3
DEFAULT_WINDOW = 21


def _login(api_client, user):
    """Calco de test_recurring_enrollment_plan_choice.py:55-60 (login por email + subdominio)."""
    host = {'HTTP_HOST': f'{user.organization.subdomain}.localhost'} if user.organization_id else {}
    token = api_client.post(
        '/api/login/', {'email': user.email, 'password': PASSWORD}, format='json', **host
    ).json()['token']
    api_client.credentials(HTTP_AUTHORIZATION=f'Token {token}')


@pytest.fixture
def setup(make_organization, make_user):
    org = make_organization()
    teacher = make_user('teach-rw', organization=org, role='teacher')
    student = make_user('alu-rw', organization=org, role='student', email='alu-rw@gym.cl')
    branch = Branch.objects.create(organization=org, name='Sede')
    return {'org': org, 'teacher': teacher, 'student': student, 'branch': branch}


def _template(setup, *, first_offset=FIRST_OFFSET, end_date=None, start_time=time(10, 0),
              name='Serie', org=None, branch=None, teacher=None):
    """Plantilla cuyo primer dictado cae a `first_offset` días de hoy."""
    today = timezone.localdate()
    first = today + timedelta(days=first_offset)
    return ClassTemplate.objects.create(
        organization=org or setup['org'],
        branch=branch or setup['branch'],
        teacher=teacher or setup['teacher'],
        name=name,
        weekday=first.weekday(),
        start_time=start_time,
        end_time=time(start_time.hour + 1, start_time.minute),
        capacity=20,
        start_date=today,
        end_date=end_date,
    )


def _expected_dates(horizon_days, first_offset=FIRST_OFFSET):
    """Fechas que DEBEN materializarse con un horizonte de `horizon_days` días."""
    today = timezone.localdate()
    return [today + timedelta(days=offset) for offset in range(first_offset, horizon_days + 1, 7)]


def _instance_dates(template):
    return [
        timezone.localtime(instance.start_datetime).date()
        for instance in GymClass.objects.filter(class_template=template).order_by('start_datetime')
    ]


def _student_plan(org, student, *, total_classes=50, classes_used=0):
    """Membresía vigente y usable (calco de test_recurring_enrollment_plan_choice.py:97-105),
    con saldo de sobra para que el tope de instancias sea el ÚNICO límite observable."""
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


def _gym_class(setup, template, *, days):
    """Instancia suelta de la serie, creada A MANO a `days` días de hoy.

    Simula lo que dejó el comportamiento viejo: filas ya materializadas más allá de la
    ventana (o una generación con otra ventana). Es la entrada del test de la Pieza B.
    """
    start = timezone.localtime(timezone.now()) + timedelta(days=days)
    return GymClass.objects.create(
        organization=setup['org'], branch=setup['branch'], teacher=setup['teacher'],
        class_template=template, name='Instancia',
        start_datetime=start, end_datetime=start + timedelta(hours=1),
        capacity=20, status=GymClass.Status.SCHEDULED,
    )


# --------------------------------------------------------------------------------------
# 1. Sin end_date: la ventana reemplaza al fallback de 365 días.
# --------------------------------------------------------------------------------------

def test_template_without_end_date_only_materializes_inside_the_window(setup):
    assert setup['org'].class_generation_window_days == DEFAULT_WINDOW
    template = _template(setup)
    assert template.end_date is None

    summary = generate_instances_for_template_range(
        template=template,
        from_date=template.start_date,
        until_date=template.end_date,
        created_by=None,
    )

    expected = _expected_dates(DEFAULT_WINDOW)
    assert len(expected) == 3, expected  # sanidad del fixture de fechas
    # Antes: ~52 filas (fallback de 365 días).
    assert summary['created_count'] == 3, summary
    assert _instance_dates(template) == expected
    assert max(_instance_dates(template)) <= timezone.localdate() + timedelta(days=DEFAULT_WINDOW)


# --------------------------------------------------------------------------------------
# 2. La ventana es POR ORGANIZACIÓN: cada plantilla obedece a la de su propia org.
# --------------------------------------------------------------------------------------

def test_each_org_materializes_according_to_its_own_window(make_organization, make_user):
    short_org = make_organization()
    short_org.class_generation_window_days = 7
    short_org.save(update_fields=['class_generation_window_days'])
    long_org = make_organization()
    long_org.class_generation_window_days = 28
    long_org.save(update_fields=['class_generation_window_days'])

    short_setup = {
        'org': short_org,
        'branch': Branch.objects.create(organization=short_org, name='Sede corta'),
        'teacher': make_user('teach-rw-short', organization=short_org, role='teacher'),
    }
    long_setup = {
        'org': long_org,
        'branch': Branch.objects.create(organization=long_org, name='Sede larga'),
        'teacher': make_user('teach-rw-long', organization=long_org, role='teacher'),
    }
    short_template = _template(short_setup, name='Serie corta')
    long_template = _template(long_setup, name='Serie larga')

    short_summary = generate_instances_for_template_range(
        template=short_template, from_date=short_template.start_date, until_date=None,
    )
    long_summary = generate_instances_for_template_range(
        template=long_template, from_date=long_template.start_date, until_date=None,
    )

    assert short_summary['created_count'] == 1, short_summary
    assert long_summary['created_count'] == 4, long_summary
    assert _instance_dates(short_template) == _expected_dates(7)
    assert _instance_dates(long_template) == _expected_dates(28)


# --------------------------------------------------------------------------------------
# 3. La ventana es un TOPE, no un piso: un rango más corto sigue mandando.
# --------------------------------------------------------------------------------------

def test_a_shorter_end_date_or_until_date_still_wins(setup):
    today = timezone.localdate()
    by_end_date = _template(setup, end_date=today + timedelta(days=10), name='Con fin')
    by_until = _template(setup, start_time=time(15, 0), name='Con until')

    end_date_summary = generate_instances_for_template_range(
        template=by_end_date, from_date=by_end_date.start_date, until_date=by_end_date.end_date,
    )
    until_summary = generate_instances_for_template_range(
        template=by_until, from_date=by_until.start_date, until_date=today + timedelta(days=5),
    )

    # end_date = hoy+10 (< ventana 21) → solo los dictados de hoy+3 y hoy+10.
    assert end_date_summary['created_count'] == 2, end_date_summary
    assert _instance_dates(by_end_date) == _expected_dates(10)
    # until_date = hoy+5 (< ventana 21) → solo el dictado de hoy+3.
    assert until_summary['created_count'] == 1, until_summary
    assert _instance_dates(by_until) == _expected_dates(5)


def test_an_until_date_from_the_request_cannot_push_past_the_window(api_client, setup, make_user):
    """La otra dirección, la que importa para el orden 8.3: `until_date` solo ACOTA, nunca
    estira. La ventana se lee de la org del RECURSO, así que un `until_date` a 300 días
    —input del request, por el endpoint real— no puede materializar (ni cobrar) más allá
    de la ventana configurada."""
    admin = make_user('admin-rw', organization=setup['org'], role='gym_admin')
    template = _template(setup)
    _login(api_client, admin)

    resp = api_client.post(
        f'/api/class-templates/{template.id}/generate/',
        {
            'from_date': str(template.start_date),
            'until_date': str(timezone.localdate() + timedelta(days=300)),
        },
        format='json',
    )

    assert resp.status_code == 200, resp.content
    assert resp.json()['created_count'] == 3, resp.json()
    assert _instance_dates(template) == _expected_dates(DEFAULT_WINDOW)


# --------------------------------------------------------------------------------------
# 4. Auto-inscripción + consumo: solo la ventana, no el año.
# --------------------------------------------------------------------------------------

def test_recurring_series_only_enrolls_and_consumes_inside_the_window(setup):
    membership = _student_plan(setup['org'], setup['student'])
    template = _template(setup)
    recurring = RecurringEnrollment.objects.create(
        student=setup['student'], class_template=template,
        start_date=timezone.localdate(), student_plan=membership,
    )

    summary = generate_instances_for_template_range(
        template=template, from_date=template.start_date, until_date=template.end_date,
    )

    assert summary['created_count'] == 3, summary
    # Auto-inscripción de la serie (sync_recurring_enrollments_for_generated_instances).
    enrollments = Enrollment.objects.filter(recurring_enrollment=recurring, status='active')
    assert enrollments.count() == 3
    assert {timezone.localtime(e.gym_class.start_datetime).date() for e in enrollments} == set(
        _expected_dates(DEFAULT_WINDOW)
    )
    # Y el consumo (regla #9) también: 3 clases descontadas, no ~52.
    membership.refresh_from_db()
    assert membership.classes_used == 3
    assert ConsumptionLog.objects.filter(
        user=setup['student'], class_instance__class_template=template,
    ).count() == 3
    assert all(e.student_plan_id == membership.id for e in enrollments)
    # Nada existe (ni se cobró) más allá de la ventana.
    assert not GymClass.objects.filter(
        class_template=template,
        start_datetime__date__gt=timezone.localdate() + timedelta(days=DEFAULT_WINDOW),
    ).exists()


def test_the_self_built_queryset_of_the_loop_is_also_capped_by_the_window(setup):
    """Pieza B: cuando el loop NO recibe `class_instances` arma su propio queryset sobre
    las instancias YA materializadas de la serie (lo hace el alta de la recurrencia y el
    reactivar del alumno). Ese queryset también se topea con la ventana: una fila vieja
    a hoy+60 no se inscribe ni se cobra."""
    membership = _student_plan(setup['org'], setup['student'])
    template = _template(setup)
    inside = _gym_class(setup, template, days=FIRST_OFFSET)
    outside = _gym_class(setup, template, days=60)
    recurring = RecurringEnrollment.objects.create(
        student=setup['student'], class_template=template,
        start_date=timezone.localdate(), student_plan=membership,
    )

    summary = create_enrollments_for_recurring_subscription(recurring_enrollment=recurring)

    assert summary['created_count'] == 1, summary
    assert Enrollment.objects.filter(gym_class=inside, student=setup['student']).exists()
    assert not Enrollment.objects.filter(gym_class=outside).exists()
    # Fuera de la ventana no entra ni como `skipped`: no está en el universo del loop.
    assert outside.id not in [item.get('class_id') for item in summary['skipped']]
    membership.refresh_from_db()
    assert membership.classes_used == 1
    assert not ConsumptionLog.objects.filter(class_instance=outside).exists()


# --------------------------------------------------------------------------------------
# 5. Punto de reserva: dentro de la ventana se reserva; fuera no hay fila que reservar.
# --------------------------------------------------------------------------------------

def test_reserving_inside_the_window_works_and_outside_there_is_no_row(api_client, setup):
    _student_plan(setup['org'], setup['student'])
    template = _template(setup)
    generate_instances_for_template_range(
        template=template, from_date=template.start_date, until_date=template.end_date,
    )
    inside = GymClass.objects.filter(class_template=template).order_by('start_datetime').first()
    _login(api_client, setup['student'])

    resp = api_client.post(
        '/api/enrollments/', {'gym_class': inside.id, 'student': setup['student'].id}, format='json',
    )
    assert resp.status_code == 201, resp.content

    # Fuera de la ventana no hay NADA que reservar: la fila no existe.
    out_of_window = timezone.localdate() + timedelta(days=FIRST_OFFSET + 28)
    assert not GymClass.objects.filter(
        class_template=template, start_datetime__date=out_of_window,
    ).exists()
    ghost_id = GymClass.objects.order_by('-id').first().id + 999
    ghost_resp = api_client.post(
        '/api/enrollments/', {'gym_class': ghost_id, 'student': setup['student'].id}, format='json',
    )
    # Error de cliente claro (no existe), nunca un 500.
    assert ghost_resp.status_code in (400, 404), ghost_resp.content
    assert not Enrollment.objects.filter(gym_class_id=ghost_id).exists()


# ========================================================================================
# Task 3 — regresiones de los ⚠️ del audit rolling-window (`task-2-report.md`, sección
# "Spec regresiones RW"). Estos tests NO ejercitan código nuevo de Task 1/2: fijan
# comportamiento que YA EXISTE para que un cambio futuro que "afloje" la ventana en estos
# dos puntos (el dashboard, o la lectura/escritura de una recurrencia sin próxima clase
# materializada) rompa un test en vez de llegar a producción en silencio.
# ========================================================================================


def _set_window(org, days):
    org.class_generation_window_days = days
    org.save(update_fields=['class_generation_window_days'])


# --------------------------------------------------------------------------------------
# 6. `dashboard_summary` (views.py:643-673) es INDEPENDIENTE de la ventana: ningún campo
#    del payload de ninguno de los tres roles sale de `GymClass`, así que cambiar cuántas
#    instancias hay materializadas (ventana chica vs. grande) no puede cambiar la
#    respuesta. Y con CERO instancias materializadas el endpoint sigue devolviendo 200.
# --------------------------------------------------------------------------------------

def test_dashboard_summary_superadmin_counts_are_window_independent(api_client, setup, make_user):
    root = make_user('root-rw', organization=None, role='superadmin', email='root-rw@tymro.cl')
    template = _template(setup)
    _set_window(setup['org'], 7)
    generate_instances_for_template_range(
        template=template, from_date=template.start_date, until_date=template.end_date,
    )
    assert GymClass.objects.filter(class_template=template).count() == 1  # ventana 7: solo hoy+3
    _login(api_client, root)

    short_resp = api_client.get('/api/dashboard/')
    assert short_resp.status_code == 200, short_resp.content

    _set_window(setup['org'], 365)
    generate_instances_for_template_range(
        template=template, from_date=template.start_date, until_date=template.end_date,
    )
    # Sanity: la ventana larga SÍ materializó bastante más (si no, el test no probaría nada).
    assert GymClass.objects.filter(class_template=template).count() > 1

    long_resp = api_client.get('/api/dashboard/')
    assert long_resp.status_code == 200, long_resp.content
    assert long_resp.json() == short_resp.json()


def test_dashboard_summary_org_admin_counts_are_window_independent(api_client, setup, make_user):
    admin = make_user('admin-rw-dash', organization=setup['org'], role='gym_admin')
    template = _template(setup)
    _set_window(setup['org'], 7)
    generate_instances_for_template_range(
        template=template, from_date=template.start_date, until_date=template.end_date,
    )
    assert GymClass.objects.filter(class_template=template).count() == 1
    _login(api_client, admin)

    short_resp = api_client.get('/api/dashboard/')
    assert short_resp.status_code == 200, short_resp.content
    assert short_resp.json()['branches'] == 1
    assert short_resp.json()['teachers'] == 1
    assert short_resp.json()['students'] == 1

    _set_window(setup['org'], 365)
    generate_instances_for_template_range(
        template=template, from_date=template.start_date, until_date=template.end_date,
    )
    assert GymClass.objects.filter(class_template=template).count() > 1

    long_resp = api_client.get('/api/dashboard/')
    assert long_resp.status_code == 200, long_resp.content
    assert long_resp.json() == short_resp.json()


def test_dashboard_summary_student_and_teacher_payload_is_window_independent(api_client, setup):
    """Misma rama de `views.py` para alumno y profe (el `else` final): ninguno de sus tres
    campos —`organization`, `branch`, `is_active_member`— sale de `GymClass`, así que
    alcanza con probar un rol de los dos para fijar la rama completa."""
    template = _template(setup)
    _set_window(setup['org'], 7)
    generate_instances_for_template_range(
        template=template, from_date=template.start_date, until_date=template.end_date,
    )
    assert GymClass.objects.filter(class_template=template).count() == 1
    _login(api_client, setup['student'])

    short_resp = api_client.get('/api/dashboard/')
    assert short_resp.status_code == 200, short_resp.content
    assert short_resp.json()['organization'] == setup['org'].name

    _set_window(setup['org'], 365)
    generate_instances_for_template_range(
        template=template, from_date=template.start_date, until_date=template.end_date,
    )
    assert GymClass.objects.filter(class_template=template).count() > 1

    long_resp = api_client.get('/api/dashboard/')
    assert long_resp.status_code == 200, long_resp.content
    assert long_resp.json() == short_resp.json()


def test_dashboard_summary_is_200_with_zero_materialized_instances(api_client, setup, make_user):
    """Ventana chica + serie que arranca después de la ventana: cero `GymClass`
    materializadas todavía. El dashboard no debe romper (KeyError/500) por eso — ningún
    conteo depende de que exista una próxima clase."""
    admin = make_user('admin-rw-zero', organization=setup['org'], role='gym_admin')
    # Ventana 1 < FIRST_OFFSET (3): el primer dictado de la serie cae fuera de la ventana,
    # así que no se materializa nada todavía.
    _set_window(setup['org'], 1)
    template = _template(setup)
    generate_instances_for_template_range(
        template=template, from_date=template.start_date, until_date=template.end_date,
    )
    assert not GymClass.objects.filter(class_template=template).exists()
    _login(api_client, admin)

    resp = api_client.get('/api/dashboard/')

    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body['branches'] == 1
    assert body['teachers'] == 1
    assert body['students'] == 1


# --------------------------------------------------------------------------------------
# 7. El modelo de LECTURA (`_next_applicable_class` / los tres campos derivados del
#    serializer, serializers.py:1312-1338) y la guarda de ESCRITURA
#    (`_student_can_manage_recurring`, views.py:387-399) tienen que EMPATAR bajo la
#    ventana: un `can_manage_now: true` no puede mentir, y el tope de ventana no puede
#    aflojar el deadline viejo para una instancia que SÍ está materializada.
# --------------------------------------------------------------------------------------

def test_no_materialized_future_instance_unlocks_read_and_write(api_client, setup):
    """Serie cuya próxima clase real cae fuera de la ventana (ventana 1, primer dictado a
    hoy+3 = FIRST_OFFSET): no hay ninguna `GymClass` futura ligada a la plantilla. Se
    espera `next_class_start: null`, `can_manage_now: true`, `manage_block_reason: ''` —
    y el PATCH de pausa que ese estado de lectura habilita tiene que aceptarse de verdad:
    si una de las dos rutas se filtrara por ventana y la otra no, la lectura mentiría."""
    _set_window(setup['org'], 1)
    template = _template(setup)
    generate_instances_for_template_range(
        template=template, from_date=template.start_date, until_date=template.end_date,
    )
    assert not GymClass.objects.filter(class_template=template).exists()
    recurring = RecurringEnrollment.objects.create(
        student=setup['student'], class_template=template, start_date=timezone.localdate(),
    )
    _login(api_client, setup['student'])

    detail = api_client.get(f'/api/recurring-enrollments/{recurring.id}/')
    assert detail.status_code == 200, detail.content
    body = detail.json()
    assert body['next_class_start'] is None
    assert body['can_manage_now'] is True
    assert body['manage_block_reason'] == ''

    patch_resp = api_client.patch(
        f'/api/recurring-enrollments/{recurring.id}/', {'is_active': False}, format='json',
    )
    assert patch_resp.status_code == 200, patch_resp.content
    recurring.refresh_from_db()
    assert recurring.is_active is False


@override_settings(STUDENT_RECURRING_CHANGE_DEADLINE_HOURS=48)
def test_a_materialized_instance_inside_the_window_still_respects_the_deadline(api_client, setup):
    """El tope de ventana NO afloja la regla vieja: con una instancia SÍ materializada
    adentro de la ventana (a ~24h) y el deadline de alumno vencido (48h configuradas),
    pausar sigue bloqueado — ni la lectura (`can_manage_now`) ni la escritura (`PATCH`)
    se abren solo porque el tope de ventana existe."""
    template = _template(setup)
    _gym_class(setup, template, days=1)  # a ~24h: adentro de la ventana default (21)
    recurring = RecurringEnrollment.objects.create(
        student=setup['student'], class_template=template, start_date=timezone.localdate(),
    )
    _login(api_client, setup['student'])

    detail = api_client.get(f'/api/recurring-enrollments/{recurring.id}/')
    assert detail.status_code == 200, detail.content
    body = detail.json()
    assert body['next_class_start'] is not None
    assert body['can_manage_now'] is False
    assert body['manage_block_reason'] != ''

    patch_resp = api_client.patch(
        f'/api/recurring-enrollments/{recurring.id}/', {'is_active': False}, format='json',
    )
    assert patch_resp.status_code == 403, patch_resp.content
    recurring.refresh_from_db()
    assert recurring.is_active is True
