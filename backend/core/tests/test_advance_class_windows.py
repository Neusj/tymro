"""Task 2 — comando `advance_class_windows`: ejercita `run_advance_class_windows`
(`core/services/rolling_window.py`, Task 1) DE PUNTA A PUNTA a través de
`django.core.management.call_command`, en vez de llamar al servicio directo.

El comando es FINO a propósito (ver su docstring de módulo): estos tests no repiten los
casos de `test_rolling_window.py` (esos ya fijan el comportamiento de
`generate_instances_for_template_range` bajo la ventana), sino la ORQUESTACIÓN que agrega
el comando: avanzar el reloj día tras día, podar lo vacío, aislar fallas por serie/clase, y
el flag `--org-id`.

NO hay freezegun/time-machine en el venv: "avanzar el reloj" se simula parcheando
`django.utils.timezone.localdate` (los templates de este archivo importan `timezone` del
mismo módulo que `recurrence.py`, así que el parche los alcanza). `timezone.now()` queda
real a propósito — con el reloj corrido hacia adelante las instancias nuevas caen aún más
en el futuro, así que ningún chequeo de "clase ya empezada" interfiere.

Mapa de casos (los 6 del brief, `task-2-brief.md`, + 1 caso agregado en la ola de fixes de
revisión final — ver `task-2-report.md`, sección "Fixes de revisión final"):

1. `test_extends_window_after_clock_advances` — primera corrida materializa
   offsets {3,10,17}; tras avanzar el reloj +7 días, una segunda corrida agrega el offset
   24 (cap nuevo = 7+21=28), auto-inscrita y con su propio consumo.
2. `test_running_twice_with_same_clock_is_idempotent` — mismo reloj, dos corridas: mismo
   conteo de `GymClass`, mismo `classes_used`, cero inscripciones duplicadas.
3. `test_prune_matrix` — la matriz completa de qué se poda y qué no.
4. `test_reverse_path_defense` — a) el filtro real excluye una clase con consumo forzado
   (saldo intacto); b) forzando `_prune_candidates` por monkeypatch para que la incluya
   igual, se prueba que la poda pasa por el reverso de verdad (cero saldo fantasma).
5. `test_isolated_series_failure_does_not_block_other_templates` — una plantilla rota no
   tumba la corrida ni a la otra plantilla de la misma organización.
6. `test_org_id_scopes_to_one_organization` (+ `test_org_id_with_unknown_org_raises_command_error`)
   — `--org-id` no toca otras organizaciones NI en la extensión NI en la poda (una clase
   pasada y vacía de la organización B sobrevive a una corrida acotada a la A), y un id
   inexistente es `CommandError`.
7. `test_default_invocation_only_advances_active_organizations` — la invocación SIN
   `--org-id` (la que corre el cron real): única que ejercita el guard
   `Organization.objects.filter(is_active=True)`; la org activa materializa de punta a
   punta, la `is_active=False` queda intacta.

Task 2 (`task-2-brief.md`) agrega el guard parejo para `--org-id` contra una organización
inactiva y el flag `--include-inactive` que lo levanta a propósito:

8. `test_prune_matrix` (casos agregados) — `completed` pasada y vacía SÍ se poda (la regla
   es estado + historia, no "no es SCHEDULED"); `completed` pasada con
   `TeacherPaymentRecord` queda, igual que cualquier otro estado con historia.
9. `test_org_id_of_inactive_org_without_flag_is_skipped` — `--org-id` apuntando a una
   organización `is_active=False`, SIN `--include-inactive`: cero instancias, cero podas,
   cero consumo; el summary registra el salteo; el comando termina normal (sin
   `CommandError`).
10. `test_org_id_of_inactive_org_with_include_inactive_processes_it` — la misma
    organización con `--include-inactive`: materializa (instancias + enrollment +
    consumo) y poda la clase pasada vacía, exactamente como si estuviera activa.

La ola de fixes de la ventana rodante agrega el COLCHÓN de poda y el SYNC antes de podar
(ver `task-2-brief.md` de `rolling-window-grace-plan`):

11. `test_prune_respects_default_grace_window` — con el default 7, la clase vacía de hace 3
    días sobrevive y la de hace 10 se poda (una sola corrida, dos clases).
12. `test_prune_grace_window_is_configurable_per_org` — con `class_pruning_grace_days=1` la
    de hace 3 días sí se poda, y la de hace 12 horas no: el corte se mueve con la config.
13. `test_prune_grace_window_of_zero_prunes_as_soon_as_the_class_ends` — el 0 configurado es
    un colchón de CERO, no "sin configurar": la clase recién terminada se poda igual. Fija la
    diferencia entre `if days is None` y un `or` que trataría al 0 como ausente.
14. `test_locked_recheck_applies_the_grace_cutoff_too` — white-box del SEGUNDO predicado del
    colchón (el re-chequeo lockeado): forzando una candidata dentro de la gracia, el lock la
    rechaza y la clase sobrevive. Red contra revertir el cutoff en un solo lado del par.
15. `test_sync_failure_is_recorded_and_does_not_block_the_prune` — la fase 2 revienta entera:
    el error queda en `sync_errors` y la poda corre igual. Cubre también la mitad `SCHEDULED`
    del predicado de poda, inalcanzable por comando cuando el sync funciona.
16. `test_sync_before_prune_preserves_the_teacher_payment` — el job corre
    `sync_class_statuses` él mismo ANTES de podar: la clase vacía de una org CON regla de
    pago queda `completed` con su `TeacherPaymentRecord` (y por eso ya no es candidata),
    mientras la misma clase de una org SIN regla se poda en la misma corrida. El resultado
    dejó de depender de si alguien abrió el dashboard.

Los fixtures de los casos 3/4/6/9/10 usan `days_ago=10` desde entonces: con el colchón
default de 7, un `days_ago=3..5` dejaba de podarse por la razón equivocada y esos tests no
mirarían ya lo que dicen mirar (ver el docstring de `_past_class`).

El Prompt 2.5 (Task 1) le pone al MISMO robot una puerta HTTP para dispararlo a mano:
`POST /api/advance-class-windows/` → `AdvanceClassWindowsView` → `advance_windows_for_org`. La
sección 9 de abajo NO vuelve a mirar la mecánica de la ventana (eso ya lo fijan los 16 casos de
arriba, que entran por el comando): mira la PUERTA — quién puede empujarla y qué puede pedirle:

17. `test_gym_admin_advances_only_their_own_organization` — el gym_admin dispara, recibe
    `{'instances_created', 'pruned_count', 'errors'}` con los conteos reales, y la organización
    de al lado queda intacta (extensión Y poda).
18. `test_only_gym_admin_can_trigger_the_job` (parametrizado: manager/teacher/student/monitor) y
    `test_superadmin_cannot_trigger_the_job` — 403 y CERO efectos en la base.
19. `test_body_cannot_redirect_the_job_to_another_organization` — el body con
    `organization`/`org_id`/`include_inactive` apuntando a otra org: 200 igual, la org del actor
    avanza y la OTRA queda intacta (orden 8.3, la org es siempre la del actor).
20. `test_double_fire_is_idempotent` — doble click: mismos conteos de
    `GymClass`/`Enrollment`/`ConsumptionLog`/`classes_used`, y el segundo POST devuelve
    `instances_created == 0`.
21. `test_inactive_organization_cannot_trigger_the_job` — org del actor suspendida: 403 (y 404
    por el subdominio, que ni llega a la vista). El `include_inactive` del comando NO existe acá.
22. `test_unauthenticated_request_is_rejected` y
    `test_malformed_body_never_reaches_the_parser` — la puerta pide token, y el body ni se
    parsea porque la vista no lo lee nunca.
23. `test_errors_of_the_three_phases_reach_the_operator_flattened_and_sanitized` — las tres listas
    de errores del summary llegan aplanadas en `errors` y con 200 (no un 500), pero SANEADAS: solo
    el prefijo identificatorio, nunca la clase de la excepción ni su mensaje.
24. `test_the_endpoint_declares_its_own_throttle_scope` y
    `test_options_does_not_publish_the_docstring` — el freno de martilleo está declarado y el
    `OPTIONS` de DRF no publica el docstring de la vista (405).
"""
from datetime import time, timedelta
from io import StringIO

import pytest
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone
from rest_framework.throttling import ScopedRateThrottle

from core.models import (
    Attendance,
    Branch,
    ClassTemplate,
    ConsumptionLog,
    Enrollment,
    GymClass,
    Plan,
    RecurringEnrollment,
    StudentPlan,
    TeacherPaymentRecord,
    TeacherPaymentRule,
)
from core.services import rolling_window
from core.services.recurrence import generate_instances_for_template_range as real_generate_instances
from core.views import AdvanceClassWindowsView

pytestmark = pytest.mark.django_db

FIRST_OFFSET = 3
DEFAULT_WINDOW = 21


@pytest.fixture
def setup(make_organization, make_user):
    org = make_organization()
    teacher = make_user('teach-acw', organization=org, role='teacher')
    student = make_user('alu-acw', organization=org, role='student', email='alu-acw@gym.cl')
    branch = Branch.objects.create(organization=org, name='Sede')
    return {'org': org, 'teacher': teacher, 'student': student, 'branch': branch}


def _template(setup, *, first_offset=FIRST_OFFSET, name='Serie', org=None, branch=None, teacher=None):
    """Plantilla cuyo primer dictado cae a `first_offset` días de hoy (calco de
    `test_rolling_window.py::_template`, sin `end_date` — no hace falta acá)."""
    today = timezone.localdate()
    first = today + timedelta(days=first_offset)
    return ClassTemplate.objects.create(
        organization=org or setup['org'],
        branch=branch or setup['branch'],
        teacher=teacher or setup['teacher'],
        name=name,
        weekday=first.weekday(),
        start_time=time(10, 0),
        end_time=time(11, 0),
        capacity=20,
        start_date=today,
        end_date=None,
    )


def _student_plan(org, student, *, total_classes=50, classes_used=0):
    """Membresía vigente y holgada (calco de `test_rolling_window.py::_student_plan`): el
    tope de instancias tiene que ser el ÚNICO límite observable, nunca el saldo."""
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


def _instance_dates(template):
    return sorted(
        timezone.localtime(gym_class.start_datetime).date()
        for gym_class in GymClass.objects.filter(class_template=template)
    )


def _past_class(setup, *, days_ago, status=GymClass.Status.SCHEDULED, name='Suelta pasada'):
    """Instancia PASADA creada a mano (no se puede generar por plantilla dentro de la
    ventana): sin `class_template`, para cubrir también las clases sueltas del filtro.

    OJO con `days_ago`: la poda tiene un COLCHÓN de gracia por organización
    (`Organization.class_pruning_grace_days`, default 7 — ver `_pruning_cutoff`), así que una
    clase de hace 3 o 5 días NO es candidata con la config default. Los casos que quieran
    probar cualquier otra cosa que el colchón usan `days_ago>=10`, para que lo único que
    decida sea el criterio que ese test está mirando."""
    start = timezone.now() - timedelta(days=days_ago)
    return GymClass.objects.create(
        organization=setup['org'], branch=setup['branch'], teacher=setup['teacher'],
        name=name, start_datetime=start, end_datetime=start + timedelta(hours=1),
        capacity=20, status=status,
    )


def _future_class(setup, *, days_ahead, status=GymClass.Status.SCHEDULED, name='Suelta futura'):
    start = timezone.now() + timedelta(days=days_ahead)
    return GymClass.objects.create(
        organization=setup['org'], branch=setup['branch'], teacher=setup['teacher'],
        name=name, start_datetime=start, end_datetime=start + timedelta(hours=1),
        capacity=20, status=status,
    )


# ----------------------------------------------------------------------------------------
# 1. Extensión: avanzar el reloj empuja el tope y materializa la instancia siguiente.
# ----------------------------------------------------------------------------------------

def test_extends_window_after_clock_advances(setup, monkeypatch):
    org, student = setup['org'], setup['student']
    membership = _student_plan(org, student)
    template = _template(setup)
    RecurringEnrollment.objects.create(
        student=student, class_template=template,
        start_date=timezone.localdate(), student_plan=membership,
    )
    real_today = timezone.localdate()

    call_command('advance_class_windows', '--org-id', str(org.id))

    assert _instance_dates(template) == [real_today + timedelta(days=o) for o in (3, 10, 17)]
    first_enrollments = Enrollment.objects.filter(gym_class__class_template=template, status='active')
    assert first_enrollments.count() == 3
    assert all(e.student_plan_id == membership.id for e in first_enrollments)
    membership.refresh_from_db()
    assert membership.classes_used == 3
    assert ConsumptionLog.objects.filter(class_instance__class_template=template).count() == 3

    # "Avanzar el reloj" +7 días: solo `localdate` se parchea, `timezone.now()` sigue real.
    monkeypatch.setattr(timezone, 'localdate', lambda tz=None: real_today + timedelta(days=7))

    call_command('advance_class_windows', '--org-id', str(org.id))

    assert _instance_dates(template) == [real_today + timedelta(days=o) for o in (3, 10, 17, 24)]
    enrollments = Enrollment.objects.filter(gym_class__class_template=template, status='active')
    assert enrollments.count() == 4
    assert all(e.student_plan_id == membership.id for e in enrollments)
    new_instance = GymClass.objects.get(
        class_template=template,
        start_datetime__date=real_today + timedelta(days=24),
    )
    assert Enrollment.objects.filter(gym_class=new_instance, student=student, status='active').exists()
    membership.refresh_from_db()
    assert membership.classes_used == 4
    assert ConsumptionLog.objects.filter(class_instance__class_template=template).count() == 4
    assert ConsumptionLog.objects.filter(class_instance=new_instance, user=student).exists()


# ----------------------------------------------------------------------------------------
# 2. Idempotencia: mismo reloj, dos corridas seguidas.
# ----------------------------------------------------------------------------------------

def test_running_twice_with_same_clock_is_idempotent(setup):
    org, student = setup['org'], setup['student']
    membership = _student_plan(org, student)
    template = _template(setup)
    RecurringEnrollment.objects.create(
        student=student, class_template=template,
        start_date=timezone.localdate(), student_plan=membership,
    )

    call_command('advance_class_windows', '--org-id', str(org.id))
    call_command('advance_class_windows', '--org-id', str(org.id))

    assert GymClass.objects.filter(class_template=template).count() == 3
    assert Enrollment.objects.filter(gym_class__class_template=template, student=student).count() == 3
    membership.refresh_from_db()
    assert membership.classes_used == 3
    assert ConsumptionLog.objects.filter(class_instance__class_template=template).count() == 3


# ----------------------------------------------------------------------------------------
# 3. Poda — matriz completa de qué se borra y qué no.
#
# La regla en una línea (ver docstring de `_prune_candidates`): la clase pasó, nadie vino,
# nadie cobró. Eso incluye TANTO `scheduled` como `completed` pasadas y vacías —`completed`
# no es un cierre humano, lo pone el sync automático del dashboard—. `suspended`,
# `cancelled` y `completed_early` quedan afuera SIEMPRE porque son una decisión humana
# explícita (suspender, cancelar, cerrar antes de hora), no un hueco vacío del calendario.
# ----------------------------------------------------------------------------------------

def test_prune_matrix(setup):
    org, student, teacher = setup['org'], setup['student'], setup['teacher']

    # `days_ago=10` en todas: la matriz mira ESTADO + HISTORIA, así que todas tienen que estar
    # fuera del colchón de gracia (default 7) para que ninguna quede o se vaya por esa razón.
    scheduled_past_empty = _past_class(setup, days_ago=10, name='Vacia pasada')
    scheduled_past_with_enrollment = _past_class(setup, days_ago=10, name='Con inscripcion')
    Enrollment.objects.create(gym_class=scheduled_past_with_enrollment, student=student, status='cancelled')
    suspended_past_empty = _past_class(setup, days_ago=10, status=GymClass.Status.SUSPENDED, name='Suspendida pasada')
    future_scheduled_empty = _future_class(setup, days_ahead=5, name='Futura vacia')
    past_with_payment_record = _past_class(setup, days_ago=10, name='Con pago a profe')
    TeacherPaymentRecord.objects.create(teacher=teacher, class_instance=past_with_payment_record)
    past_with_attendance = _past_class(setup, days_ago=10, name='Con asistencia')
    Attendance.objects.create(gym_class=past_with_attendance, student=student)
    completed_past_empty = _past_class(
        setup, days_ago=10, status=GymClass.Status.COMPLETED, name='Completed vacia pasada',
    )
    completed_past_with_payment = _past_class(
        setup, days_ago=10, status=GymClass.Status.COMPLETED, name='Completed con pago a profe',
    )
    TeacherPaymentRecord.objects.create(teacher=teacher, class_instance=completed_past_with_payment)

    call_command('advance_class_windows', '--org-id', str(org.id))

    # scheduled + pasada + vacía -> BORRADA: la clase pasó, nadie vino, nadie cobró.
    assert not GymClass.objects.filter(pk=scheduled_past_empty.pk).exists()
    # pasada con 1 enrollment (aunque esté cancelled) -> queda.
    assert GymClass.objects.filter(pk=scheduled_past_with_enrollment.pk).exists()
    # suspended pasada y vacía -> queda: decisión humana explícita (suspender), no un hueco
    # vacío del calendario.
    assert GymClass.objects.filter(pk=suspended_past_empty.pk).exists()
    # futura vacía scheduled (dentro de ventana) -> queda (no es pasado).
    assert GymClass.objects.filter(pk=future_scheduled_empty.pk).exists()
    # pasada vacía pero con TeacherPaymentRecord -> queda.
    assert GymClass.objects.filter(pk=past_with_payment_record.pk).exists()
    # pasada vacía pero con Attendance -> queda.
    assert GymClass.objects.filter(pk=past_with_attendance.pk).exists()
    # completed + pasada + vacía -> BORRADA también: `completed` no es un cierre humano, lo
    # pone el sync automático apenas termina el horario; misma regla que `scheduled`.
    assert not GymClass.objects.filter(pk=completed_past_empty.pk).exists()
    # completed + pasada + con TeacherPaymentRecord -> queda, y el TPR sobrevive con ella:
    # hubo liquidación de ese dictado, es historia real aunque el estado sea automático.
    assert GymClass.objects.filter(pk=completed_past_with_payment.pk).exists()
    assert TeacherPaymentRecord.objects.filter(class_instance_id=completed_past_with_payment.pk).exists()


# ----------------------------------------------------------------------------------------
# 3.1 COLCHÓN de poda (`Organization.class_pruning_grace_days`, default 7): una clase vacía no
#     se borra apenas termina. El borrado es irreversible y el job corre a diario, así que sin
#     colchón la clase del viernes desaparecía el sábado a la mañana: adiós al backfill tardío
#     (pasar lista el lunes) y a cualquier chance de deshacer algo a mano.
# ----------------------------------------------------------------------------------------

def test_prune_respects_default_grace_window(setup):
    """Dos clases idénticas, vacías y pasadas, UNA sola corrida: la que terminó hace 3 días
    (DENTRO del colchón default) sobrevive; la de hace 10 días se poda. Antes del colchón las
    dos se borraban en el primer barrido posterior."""
    org = setup['org']
    assert org.class_pruning_grace_days == 7, 'este test se apoya en el default del modelo'
    inside_grace = _past_class(setup, days_ago=3, name='Vacia de hace 3 dias')
    outside_grace = _past_class(setup, days_ago=10, name='Vacia de hace 10 dias')

    call_command('advance_class_windows', '--org-id', str(org.id))

    assert GymClass.objects.filter(pk=inside_grace.pk).exists(), (
        'se podó una clase que terminó DENTRO del colchón de gracia'
    )
    assert not GymClass.objects.filter(pk=outside_grace.pk).exists()


def test_prune_grace_window_is_configurable_per_org(setup):
    """La misma clase de hace 3 días SÍ se poda con `class_pruning_grace_days=1`. Y en la misma
    corrida, una que terminó hace unas horas sigue a salvo: el corte es `now - grace`, no una
    constante ni un `>= 1 día` cualquiera."""
    org = setup['org']
    org.class_pruning_grace_days = 1
    org.save(update_fields=['class_pruning_grace_days'])
    outside_grace = _past_class(setup, days_ago=3, name='Vacia de hace 3 dias')
    inside_grace = _past_class(setup, days_ago=0.5, name='Vacia de hace 12 horas')

    call_command('advance_class_windows', '--org-id', str(org.id))

    assert not GymClass.objects.filter(pk=outside_grace.pk).exists(), (
        'con grace=1 una clase de hace 3 días tiene que podarse'
    )
    assert GymClass.objects.filter(pk=inside_grace.pk).exists()


def test_prune_grace_window_of_zero_prunes_as_soon_as_the_class_ends(setup):
    """`class_pruning_grace_days=0` es un valor VÁLIDO y significa "podar apenas termina" (el
    comportamiento anterior al colchón), no "usar el default".

    Este test existe por una razón puntual: `_pruning_cutoff` cae al default del modelo solo
    cuando el valor es `None`. Un `days = getattr(...) or default` —el reflejo obvio— haría que
    el 0 configurado se comportara como 7 en silencio, o sea que la org que pidió podar al día
    siguiente se quedara con una semana de basura y sin un solo error que lo delate. Con 0 la
    clase que terminó hace un rato ya es candidata."""
    org = setup['org']
    org.class_pruning_grace_days = 0
    org.save(update_fields=['class_pruning_grace_days'])
    just_ended = _past_class(setup, days_ago=0.25, name='Vacia terminada hace 5 horas')

    call_command('advance_class_windows', '--org-id', str(org.id))

    assert not GymClass.objects.filter(pk=just_ended.pk).exists(), (
        'con grace=0 la clase terminada tiene que podarse en el mismo barrido '
        '(¿el 0 cayó al default del modelo?)'
    )


def test_locked_recheck_applies_the_grace_cutoff_too(setup, monkeypatch):
    """WHITE-BOX del SEGUNDO predicado. El colchón vive en DOS lugares que tienen que moverse
    juntos: el filtro de candidatas (`_prune_candidates`) y el re-chequeo lockeado de adentro de
    la transacción del borrado. Los tests de caja negra de arriba solo pueden ver el primero —el
    más estricto de los dos gobierna el resultado—, así que revertir el cutoff SOLO en el lock
    pasaría inadvertido.

    Molde de `test_reverse_path_defense` (b): se fuerza `_prune_candidates` para que devuelva una
    clase vacía terminada hace 3 días, DENTRO del colchón default de 7. Si el lock aplica su
    cutoff, no la toma (`locked is None`) y la clase sobrevive; si alguien le dejara `now`, la
    borraría. El salteo es en silencio a propósito: no es un error, es el resultado correcto —de
    ahí el `0 podadas, 0 errores`."""
    org = setup['org']
    assert org.class_pruning_grace_days == 7, 'este test se apoya en el default del modelo'
    inside_grace = _past_class(setup, days_ago=3, name='Vacia de hace 3 dias forzada como candidata')
    monkeypatch.setattr(
        rolling_window, '_prune_candidates',
        lambda organization, now: GymClass.objects.filter(pk=inside_grace.pk),
    )
    out = StringIO()

    call_command('advance_class_windows', '--org-id', str(org.id), stdout=out)

    assert GymClass.objects.filter(pk=inside_grace.pk).exists(), (
        'el re-chequeo lockeado borró una clase dentro del colchón: ¿le quedó `now` en vez del cutoff?'
    )
    assert '0 podadas, 0 errores' in out.getvalue()


# ----------------------------------------------------------------------------------------
# 3.2 SYNC ANTES DE PODAR (determinismo). El flip a `completed` y el `TeacherPaymentRecord`
#     del profe los crea `sync_class_statuses`, que hasta ahora solo corría cuando alguien
#     abría el dashboard. El job lo corre él mismo en su fase 2: si la poda decidiera antes,
#     borraría la clase vacía y la liquidación de ese dictado no nacería NUNCA — el resultado
#     del job dependía del tráfico web.
# ----------------------------------------------------------------------------------------

def test_sync_before_prune_preserves_the_teacher_payment(setup, make_organization, make_user):
    """Dos orgs en la MISMA corrida, con la misma clase vacía `scheduled` de hace 10 días (o
    sea: nadie abrió la app desde que terminó, sigue sin cerrar).

    * La org CON regla de pago activa: el sync la cierra y le crea el `TeacherPaymentRecord`,
      así que la poda ya la ve con historia y NO la borra. Sin el sync-first, esa clase se
      borraba y el pago del profe se perdía en silencio.
    * La org SIN regla: el sync la cierra igual, no hay pago que crear, y la poda la borra.

    Las dos mitades juntas son el punto: el resultado lo decide la CONFIGURACIÓN de la org, no
    si alguien pasó por el dashboard antes del cron.
    """
    org_with_rule, teacher = setup['org'], setup['teacher']
    rule = TeacherPaymentRule.objects.create(
        organization=org_with_rule,
        payment_type=TeacherPaymentRule.PaymentType.FIXED_PER_CLASS,
        amount=12000,
        is_active=True,
    )
    rule.teachers.add(teacher)
    paid_class = _past_class(setup, days_ago=10, name='Vacia con regla de pago')

    org_without_rule = make_organization()
    setup_without_rule = {
        'org': org_without_rule,
        'branch': Branch.objects.create(organization=org_without_rule, name='Sede sin regla'),
        'teacher': make_user('teach-norule-acw', organization=org_without_rule, role='teacher'),
    }
    unpaid_class = _past_class(setup_without_rule, days_ago=10, name='Vacia sin regla de pago')

    call_command('advance_class_windows')  # barrido default: las dos orgs en la misma corrida.

    assert GymClass.objects.filter(pk=paid_class.pk).exists(), (
        'la poda borró una clase cuya liquidación acababa de nacer en el sync'
    )
    paid_class.refresh_from_db()
    assert paid_class.status == GymClass.Status.COMPLETED, 'el sync tiene que cerrarla el job mismo'
    assert TeacherPaymentRecord.objects.filter(class_instance=paid_class, teacher=teacher).exists()

    # Contraparte: sin regla de pago no hay nada que preservar y la poda hace su trabajo.
    assert not GymClass.objects.filter(pk=unpaid_class.pk).exists()
    assert not TeacherPaymentRecord.objects.filter(class_instance_id=unpaid_class.pk).exists()


def test_sync_failure_is_recorded_and_does_not_block_the_prune(setup, monkeypatch):
    """La fase 2 revienta entera (se parchea `sync_class_statuses` TAL COMO LO IMPORTA
    `rolling_window`) y la corrida tiene que seguir igual: el error queda registrado en
    `sync_errors` —visible en el conteo de errores del comando— y la fase 3 poda lo mismo que
    habría podado. Un sync roto no puede dejar a la organización sin limpieza, que es justamente
    por qué el try/except envuelve la FASE y no el loop de a una clase.

    Este test es además la ÚNICA cobertura de la mitad `SCHEDULED` del predicado de poda por la
    vía del comando: con la fase 2 sana, toda pasada `scheduled` sale de ahí como `completed`, así
    que el `SCHEDULED` del filtro queda inalcanzable. Es redundancia defensiva que paga
    exactamente en este escenario —el sync caído— y sin ella un sync roto significaría cero podas.
    """
    org = setup['org']
    past_empty = _past_class(setup, days_ago=10, name='Vacia pasada con el sync roto')

    def _boom(base_queryset):
        raise RuntimeError('sync boom')

    monkeypatch.setattr(rolling_window, 'sync_class_statuses', _boom)
    out = StringIO()

    call_command('advance_class_windows', '--org-id', str(org.id), stdout=out)

    # a) la corrida no explota (llegar acá ya lo prueba) y b) el error queda registrado.
    output = out.getvalue()
    assert 'RuntimeError' in output
    assert 'sync boom' in output
    # c) la poda corrió IGUAL: la clase seguía `scheduled` (nada la flipeó) y se borró lo mismo.
    assert not GymClass.objects.filter(pk=past_empty.pk).exists()
    assert '1 podadas, 1 errores' in output


# ----------------------------------------------------------------------------------------
# 4. Defensa del reverso: el filtro real protege, y hasta forzando el candidato el borrado
#    sigue pasando por el reverso de consumo (cero saldo fantasma).
# ----------------------------------------------------------------------------------------

def test_reverse_path_defense(setup, monkeypatch):
    org, student = setup['org'], setup['student']
    membership = _student_plan(org, student, classes_used=0)
    # `days_ago=10`: lo que tiene que excluirla en (a) es el `ConsumptionLog`, no el colchón de
    # gracia; y en (b) el re-chequeo lockeado de la poda también exige estar fuera del colchón,
    # así que con 3 días el candidato forzado se saltearía y el test probaría nada.
    forced_class = _past_class(setup, days_ago=10, name='Consumo forzado sin inscripcion')
    ConsumptionLog.objects.create(
        user=student, student_plan=membership, class_instance=forced_class, branch=setup['branch'],
    )
    StudentPlan.objects.filter(pk=membership.pk).update(classes_used=1)
    membership.refresh_from_db()
    assert membership.classes_used == 1

    # a) el filtro real (`_prune_candidates`) la excluye por tener un ConsumptionLog: el
    #    comando NO la borra y el saldo queda intacto.
    call_command('advance_class_windows', '--org-id', str(org.id))

    assert GymClass.objects.filter(pk=forced_class.pk).exists()
    assert ConsumptionLog.objects.filter(class_instance=forced_class).exists()
    membership.refresh_from_db()
    assert membership.classes_used == 1

    # b) white-box: se fuerza `_prune_candidates` (monkeypatch del módulo `rolling_window`)
    #    para que la incluya IGUAL. Si el borrado hiciera un `.delete()` a secas, el log
    #    quedaría huérfano y `classes_used` seguiría en 1 (saldo fantasma). Como pasa por
    #    `_delete_class_refunding_consumption`, el reverso corre de verdad.
    monkeypatch.setattr(
        rolling_window, '_prune_candidates',
        lambda organization, now: GymClass.objects.filter(pk=forced_class.pk),
    )

    call_command('advance_class_windows', '--org-id', str(org.id))

    assert not GymClass.objects.filter(pk=forced_class.pk).exists()
    assert not ConsumptionLog.objects.filter(class_instance_id=forced_class.pk).exists()
    membership.refresh_from_db()
    assert membership.classes_used == 0


# ----------------------------------------------------------------------------------------
# 5. Fallo aislado: una plantilla rota no tumba la corrida ni a la plantilla sana.
# ----------------------------------------------------------------------------------------

def test_isolated_series_failure_does_not_block_other_templates(setup, monkeypatch):
    org, student = setup['org'], setup['student']
    membership = _student_plan(org, student)
    boom_template = _template(setup, name='Serie rota')
    ok_template = _template(setup, name='Serie sana')
    RecurringEnrollment.objects.create(
        student=student, class_template=ok_template,
        start_date=timezone.localdate(), student_plan=membership,
    )

    def _boom_only_for_broken_template(template, *args, **kwargs):
        if template.id == boom_template.id:
            raise RuntimeError('boom')
        return real_generate_instances(template, *args, **kwargs)

    monkeypatch.setattr(rolling_window, 'generate_instances_for_template_range', _boom_only_for_broken_template)
    out = StringIO()

    call_command('advance_class_windows', '--org-id', str(org.id), stdout=out)

    assert not GymClass.objects.filter(class_template=boom_template).exists()
    assert GymClass.objects.filter(class_template=ok_template).count() == 3
    membership.refresh_from_db()
    assert membership.classes_used == 3
    assert ConsumptionLog.objects.filter(class_instance__class_template=ok_template).count() == 3
    output = out.getvalue()
    assert 'RuntimeError' in output
    assert 'boom' in output


# ----------------------------------------------------------------------------------------
# 6. `--org-id`: scoping a una sola organización + `CommandError` si no existe.
# ----------------------------------------------------------------------------------------

def test_org_id_scopes_to_one_organization(make_organization, make_user):
    """`--org-id` no toca a la otra organización en NINGUNA de las dos mitades del job: ni
    en la extensión (`template_b` no materializa) ni en la poda (`past_empty_b`, una clase
    pasada y vacía de la organización B, sobrevive a una corrida acotada a la A — antes de
    este test solo la extensión tenía red de regresión para el scoping; la mitad
    destructiva podía borrar cross-org en silencio sin que ningún test lo notara)."""
    org_a = make_organization()
    org_b = make_organization()
    branch_a = Branch.objects.create(organization=org_a, name='Sede A')
    branch_b = Branch.objects.create(organization=org_b, name='Sede B')
    teacher_a = make_user('teach-a-acw', organization=org_a, role='teacher')
    teacher_b = make_user('teach-b-acw', organization=org_b, role='teacher')
    setup_a = {'org': org_a, 'branch': branch_a, 'teacher': teacher_a}
    setup_b = {'org': org_b, 'branch': branch_b, 'teacher': teacher_b}
    template_a = _template(setup_a, name='Serie A')
    template_b = _template(setup_b, name='Serie B')
    # Fuera del colchón de gracia (default 7): lo único que la salva tiene que ser el scoping.
    past_empty_b = _past_class(setup_b, days_ago=10, name='Vacia pasada de la org B')

    call_command('advance_class_windows', '--org-id', str(org_a.id))

    assert GymClass.objects.filter(class_template=template_a).count() == 3
    assert not GymClass.objects.filter(class_template=template_b).exists()
    assert GymClass.objects.filter(pk=past_empty_b.pk).exists()


def test_org_id_with_unknown_org_raises_command_error(make_organization):
    org = make_organization()
    nonexistent_id = org.id + 999999

    with pytest.raises(CommandError):
        call_command('advance_class_windows', '--org-id', str(nonexistent_id))


# ----------------------------------------------------------------------------------------
# 7. Invocación DEFAULT (sin --org-id): la que corre el cron diario de verdad. Es la ÚNICA
#    invocación que ejercita `Organization.objects.filter(is_active=True)` — el guard que
#    evita cobrarle a un gimnasio suspendido. Ningún otro test de este archivo pasa por esa
#    rama, así que sin este test un guard roto (o borrado) pasaría inadvertido.
# ----------------------------------------------------------------------------------------

def test_default_invocation_only_advances_active_organizations(make_organization, make_user):
    """Dos orgs, una activa y una `is_active=False`, cada una con su propia serie +
    recurrencia + plan. Sin `--org-id` (la forma exacta del Scheduled Job de Railway): la
    activa materializa de punta a punta (instancias + enrollment + consumo); la inactiva
    queda intacta. Gotcha de la migración 0013 (org de fallback activa sembrada por el
    entrypoint): NUNCA se assertan conteos absolutos de `orgs_processed` ni de `GymClass`
    globales, solo lo que cuelga de LAS DOS orgs de este test."""
    active_org = make_organization()
    inactive_org = make_organization()
    inactive_org.is_active = False
    inactive_org.save(update_fields=['is_active'])

    active_branch = Branch.objects.create(organization=active_org, name='Sede activa')
    inactive_branch = Branch.objects.create(organization=inactive_org, name='Sede inactiva')
    active_teacher = make_user('teach-active-acw', organization=active_org, role='teacher')
    inactive_teacher = make_user('teach-inactive-acw', organization=inactive_org, role='teacher')
    active_student = make_user('alu-active-acw', organization=active_org, role='student', email='alu-active-acw@gym.cl')
    inactive_student = make_user('alu-inactive-acw', organization=inactive_org, role='student', email='alu-inactive-acw@gym.cl')

    active_setup = {'org': active_org, 'branch': active_branch, 'teacher': active_teacher}
    inactive_setup = {'org': inactive_org, 'branch': inactive_branch, 'teacher': inactive_teacher}

    active_membership = _student_plan(active_org, active_student)
    inactive_membership = _student_plan(inactive_org, inactive_student)
    active_template = _template(active_setup, name='Serie activa')
    inactive_template = _template(inactive_setup, name='Serie inactiva')
    RecurringEnrollment.objects.create(
        student=active_student, class_template=active_template,
        start_date=timezone.localdate(), student_plan=active_membership,
    )
    RecurringEnrollment.objects.create(
        student=inactive_student, class_template=inactive_template,
        start_date=timezone.localdate(), student_plan=inactive_membership,
    )

    call_command('advance_class_windows')  # SIN --org-id: la invocación real del cron.

    # La organización activa materializó su serie completa (instancias + enrollment + consumo).
    assert GymClass.objects.filter(class_template=active_template).count() == 3
    assert Enrollment.objects.filter(
        gym_class__class_template=active_template, student=active_student, status='active',
    ).count() == 3
    active_membership.refresh_from_db()
    assert active_membership.classes_used == 3
    assert ConsumptionLog.objects.filter(class_instance__class_template=active_template).count() == 3

    # La organización inactiva queda exactamente como estaba: el guard `is_active=True` la
    # excluyó del barrido automático.
    assert not GymClass.objects.filter(class_template=inactive_template).exists()
    inactive_membership.refresh_from_db()
    assert inactive_membership.classes_used == 0
    assert not ConsumptionLog.objects.filter(class_instance__class_template=inactive_template).exists()


# ----------------------------------------------------------------------------------------
# 8. Task 2 — el mismo guard de `is_active`, ahora también contra `--org-id` puntual, y el
#    flag `--include-inactive` que lo levanta a propósito.
# ----------------------------------------------------------------------------------------

def _inactive_org_setup(make_organization, make_user):
    """Org `is_active=False` con serie + recurrencia + plan + una clase pasada vacía y
    podable, para los dos tests de `--org-id` + `--include-inactive` de abajo."""
    org = make_organization()
    org.is_active = False
    org.save(update_fields=['is_active'])
    branch = Branch.objects.create(organization=org, name='Sede org inactiva')
    teacher = make_user('teach-inactive-flag-acw', organization=org, role='teacher')
    student = make_user(
        'alu-inactive-flag-acw', organization=org, role='student', email='alu-inactive-flag-acw@gym.cl',
    )
    org_setup = {'org': org, 'branch': branch, 'teacher': teacher}
    membership = _student_plan(org, student)
    template = _template(org_setup, name='Serie org inactiva')
    RecurringEnrollment.objects.create(
        student=student, class_template=template,
        start_date=timezone.localdate(), student_plan=membership,
    )
    # Fuera del colchón de gracia (default 7): lo único que decide si se poda o no tiene que
    # ser el guard de `is_active` / el flag `--include-inactive`.
    past_empty = _past_class(org_setup, days_ago=10, name='Vacia pasada org inactiva')
    return {
        'org': org, 'student': student, 'membership': membership,
        'template': template, 'past_empty': past_empty,
    }


def test_org_id_of_inactive_org_without_flag_is_skipped(make_organization, make_user):
    """`--org-id` apuntado a una organización inactiva, SIN `--include-inactive`: no la
    procesa. Cero instancias nuevas, cero podas (la clase pasada vacía sobrevive), cero
    consumo — y el comando termina normal, sin `CommandError`, con el salteo visible en la
    salida (WARNING con el id/nombre de la org y la pista de `--include-inactive`)."""
    ctx = _inactive_org_setup(make_organization, make_user)
    org, template, past_empty, membership = ctx['org'], ctx['template'], ctx['past_empty'], ctx['membership']
    out = StringIO()

    call_command('advance_class_windows', '--org-id', str(org.id), stdout=out)

    assert not GymClass.objects.filter(class_template=template).exists()
    assert GymClass.objects.filter(pk=past_empty.pk).exists()
    membership.refresh_from_db()
    assert membership.classes_used == 0
    assert not ConsumptionLog.objects.filter(class_instance__class_template=template).exists()
    output = out.getvalue()
    assert str(org.id) in output
    assert 'inactiva' in output
    assert '--include-inactive' in output


def test_org_id_of_inactive_org_with_include_inactive_processes_it(make_organization, make_user):
    """La misma organización inactiva, ahora CON `--include-inactive`: el flag fuerza la
    corrida igual que si estuviera activa — materializa la serie (instancias + enrollment +
    consumo) y poda la clase pasada vacía."""
    ctx = _inactive_org_setup(make_organization, make_user)
    org, student = ctx['org'], ctx['student']
    template, past_empty, membership = ctx['template'], ctx['past_empty'], ctx['membership']

    call_command('advance_class_windows', '--org-id', str(org.id), '--include-inactive')

    assert GymClass.objects.filter(class_template=template).count() == 3
    assert Enrollment.objects.filter(
        gym_class__class_template=template, student=student, status='active',
    ).count() == 3
    membership.refresh_from_db()
    assert membership.classes_used == 3
    assert ConsumptionLog.objects.filter(class_instance__class_template=template).count() == 3
    assert not GymClass.objects.filter(pk=past_empty.pk).exists()


# ==========================================================================================
# 9. Prompt 2.5 / Task 1 — ENDPOINT `POST /api/advance-class-windows/`.
#
#    El mismo robot, disparado a mano desde la app en vez de por el cron. Lo que estos tests
#    miran NO es la ventana (eso ya está fijado arriba, 16 casos por el comando) sino la
#    PUERTA: el botón dispara CONSUMO DE SALDO real y BORRADO IRREVERSIBLE de clases, así que
#    quién lo puede empujar y sobre QUÉ organización cae es la parte peligrosa.
#
#    Dos diferencias de fondo con el comando, y las dos son a propósito:
#      * la organización NO se elige: es SIEMPRE la del actor (orden 8.3). No hay `--org-id`
#        que valga, ni por body ni por query.
#      * no hay `--include-inactive`: una org suspendida no puede disparar el job desde la UI
#        (el override existe solo para el operador con acceso al shell).
# ==========================================================================================

ENDPOINT = '/api/advance-class-windows/'
PASSWORD = 'Passw0rd2026'


def _login(api_client, user):
    """Calco de `test_rolling_window.py:65-71`: login por email + subdominio en el Host.

    Se loguea de verdad (y no `force_authenticate`) para que el test atraviese el mismo camino
    que el navegador: `OrganizationMiddleware` resolviendo el tenant por el Host + token DRF. Un
    usuario de plataforma (superadmin, `organization=None`) va sin subdominio, que es el único
    contexto donde el login lo encuentra."""
    host = {'HTTP_HOST': f'{user.organization.subdomain}.localhost'} if user.organization_id else {}
    token = api_client.post(
        '/api/login/', {'email': user.email, 'password': PASSWORD}, format='json', **host
    ).json()['token']
    api_client.credentials(HTTP_AUTHORIZATION=f'Token {token}')


def _host_of(org):
    """Header Host del subdominio de `org` (el que usa el navegador), o nada para plataforma."""
    return {'HTTP_HOST': f'{org.subdomain}.localhost'} if org is not None else {}


def _endpoint_org(make_organization, make_user, suffix):
    """Organización lista para el endpoint: serie + recurrencia + membresía (→ 3 instancias
    materializables, offsets 3/10/17) y UNA clase pasada vacía fuera del colchón (→ 1 poda).

    O sea: una org donde el robot tiene trabajo VISIBLE en las dos mitades. Así el mismo fixture
    sirve para el caso feliz (avanzó: 3 creadas, 1 podada) y para los negativos (no avanzó: 0
    instancias, la clase pasada sigue viva, saldo sin tocar) — ver `_assert_advanced` /
    `_assert_untouched`. El `suffix` mantiene únicos los usernames cuando el test arma dos orgs."""
    org = make_organization()
    branch = Branch.objects.create(organization=org, name=f'Sede {suffix}')
    teacher = make_user(f'teach-ep-{suffix}', organization=org, role='teacher')
    student = make_user(f'alu-ep-{suffix}', organization=org, role='student')
    admin = make_user(f'admin-ep-{suffix}', organization=org, role='gym_admin')
    org_setup = {'org': org, 'branch': branch, 'teacher': teacher}
    membership = _student_plan(org, student)
    template = _template(org_setup, name=f'Serie {suffix}')
    RecurringEnrollment.objects.create(
        student=student, class_template=template,
        start_date=timezone.localdate(), student_plan=membership,
    )
    # `days_ago=10`: fuera del colchón de gracia default (7), para que lo único que decida si se
    # poda o no sea la puerta que estos tests están mirando.
    past_empty = _past_class(org_setup, days_ago=10, name=f'Vacia pasada {suffix}')
    return {
        'org': org, 'branch': branch, 'teacher': teacher, 'student': student, 'admin': admin,
        'membership': membership, 'template': template, 'past_empty': past_empty,
    }


def _assert_advanced(ctx):
    """El robot corrió de punta a punta sobre esta org: materializó la ventana (instancias +
    inscripción automática + CONSUMO de saldo) y podó la clase vacía pasada."""
    assert GymClass.objects.filter(class_template=ctx['template']).count() == 3
    assert Enrollment.objects.filter(
        gym_class__class_template=ctx['template'], student=ctx['student'], status='active',
    ).count() == 3
    ctx['membership'].refresh_from_db()
    assert ctx['membership'].classes_used == 3
    assert ConsumptionLog.objects.filter(class_instance__class_template=ctx['template']).count() == 3
    assert not GymClass.objects.filter(pk=ctx['past_empty'].pk).exists()


def _assert_untouched(ctx, why):
    """NADA pasó sobre esta org: ni una instancia nueva, ni un peso de saldo consumido, ni una
    clase borrada. Se chequean las TRES cosas y no solo el status code: el daño de este endpoint
    no está en la respuesta, está en la base (saldo del alumno y clases borradas)."""
    assert not GymClass.objects.filter(class_template=ctx['template']).exists(), why
    assert not Enrollment.objects.filter(gym_class__class_template=ctx['template']).exists(), why
    ctx['membership'].refresh_from_db()
    assert ctx['membership'].classes_used == 0, why
    assert not ConsumptionLog.objects.filter(student_plan=ctx['membership']).exists(), why
    assert GymClass.objects.filter(pk=ctx['past_empty'].pk).exists(), why


def test_gym_admin_advances_only_their_own_organization(api_client, make_organization, make_user):
    """El caso feliz Y el aislamiento, en el mismo test a propósito: dos organizaciones idénticas
    (serie + recurrencia + plan + una clase vacía podable cada una), el gym_admin de la A dispara,
    y la B tiene que quedar EXACTAMENTE como estaba.

    Van juntos porque el endpoint no recibe ninguna organización: el único testigo de que el
    scoping funciona es que la de al lado no se movió. La respuesta se compara COMPLETA (igualdad,
    no `in`) para fijar el contrato de tres claves: sin `org_id`/`org_name` ni el resto del summary
    interno, que serían ruido —y, en un endpoint multi-tenant, superficie de filtración— para el
    front."""
    ctx_a = _endpoint_org(make_organization, make_user, 'a')
    ctx_b = _endpoint_org(make_organization, make_user, 'b')
    _login(api_client, ctx_a['admin'])

    resp = api_client.post(ENDPOINT, {}, format='json', **_host_of(ctx_a['org']))

    assert resp.status_code == 200, resp.content
    assert resp.json() == {'instances_created': 3, 'pruned_count': 1, 'errors': []}
    _assert_advanced(ctx_a)
    _assert_untouched(ctx_b, 'el disparo de la org A alcanzó a la org B')


@pytest.mark.parametrize('role', ['manager', 'teacher', 'student', 'monitor'])
def test_only_gym_admin_can_trigger_the_job(api_client, make_organization, make_user, role):
    """Ni manager, ni teacher, ni student, ni monitor. El botón consume saldo de los alumnos y
    borra clases sin vuelta atrás: es una decisión de administración del gimnasio, no una lectura.

    Un test por rol (parametrizado) y no un loop dentro de uno: cada rol necesita su propio login
    y el throttle de `/api/login/` es 5/min por IP — la fixture autouse que limpia el caché corre
    entre TESTS, así que cinco logins dentro de un mismo test viven al borde del límite."""
    ctx = _endpoint_org(make_organization, make_user, 'role')
    actor = make_user(f'{role}-ep-acw', organization=ctx['org'], role=role)
    _login(api_client, actor)

    resp = api_client.post(ENDPOINT, {}, format='json', **_host_of(ctx['org']))

    assert resp.status_code == 403, resp.content
    _assert_untouched(ctx, f'el rol {role} disparó el robot')


def test_superadmin_cannot_trigger_the_job(api_client, make_organization, make_user):
    """El superadmin también 403, mismo racional que `ManualPaymentCreateView`: es rol de
    PLATAFORMA y no tiene organización, así que no hay org que anclar sin creerle al payload —y
    creerle sería exactamente el bug que este endpoint no puede tener, porque el job consume saldo
    y borra clases—. Su camino para esto es el comando (`--org-id`), que corre con acceso al shell
    y deja rastro en los logs del job, no un POST desde un navegador."""
    ctx = _endpoint_org(make_organization, make_user, 'super')
    superadmin = make_user('super-ep-acw', organization=None, role='superadmin')
    _login(api_client, superadmin)  # sin subdominio: el único contexto donde entra plataforma.

    resp = api_client.post(ENDPOINT, {}, format='json')

    assert resp.status_code == 403, resp.content
    _assert_untouched(ctx, 'el superadmin disparó el robot sobre una org ajena')


def test_body_cannot_redirect_the_job_to_another_organization(api_client, make_organization, make_user):
    """INYECCIÓN DE ORG. El body trae los tres nombres que un atacante probaría —los dos que
    usaría un serializer (`organization`, `org_id`) y el flag del comando (`include_inactive`)—
    apuntando a la organización B, que está ACTIVA y tiene trabajo pendiente (3 instancias por
    materializar + 1 clase podable).

    Que B esté activa es el punto: si la vista le pasara el `org_id` del body al servicio, B
    avanzaría y este test lo vería. Con B inactiva el resultado sería el mismo por la razón
    equivocada (el guard de `is_active`) y la trampa no probaría nada.

    Resultado esperado: 200 normal —el body no es un error, simplemente no existe— con los
    conteos de la org A, y B intacta: cero instancias, cero podas, saldo sin tocar."""
    ctx_a = _endpoint_org(make_organization, make_user, 'inj-a')
    ctx_b = _endpoint_org(make_organization, make_user, 'inj-b')
    assert ctx_b['org'].is_active, 'la org B tiene que estar activa para que la trampa sea real'
    _login(api_client, ctx_a['admin'])

    resp = api_client.post(
        ENDPOINT,
        {
            'organization': ctx_b['org'].id,
            'org_id': ctx_b['org'].id,
            'include_inactive': True,
        },
        format='json',
        **_host_of(ctx_a['org']),
    )

    assert resp.status_code == 200, resp.content
    assert resp.json() == {'instances_created': 3, 'pruned_count': 1, 'errors': []}
    _assert_advanced(ctx_a)
    _assert_untouched(ctx_b, 'el body redirigió el robot a la organización B')


def test_double_fire_is_idempotent(api_client, make_organization, make_user):
    """Doble click en el botón. La idempotencia ya la garantiza el servicio (la generación skipea
    duplicados y lo podado no vuelve a ser candidato), así que esto es la RED de la puerta: que
    exponerlo por HTTP no haya agregado una segunda inscripción, un segundo consumo ni un segundo
    borrado.

    Se comparan los conteos de la base ANTES/DESPUÉS del segundo POST —no solo la respuesta—
    porque el daño de un doble cobro vive en `classes_used`, no en el JSON."""
    ctx = _endpoint_org(make_organization, make_user, 'twice')
    membership, template = ctx['membership'], ctx['template']
    _login(api_client, ctx['admin'])
    host = _host_of(ctx['org'])

    first = api_client.post(ENDPOINT, {}, format='json', **host)

    assert first.status_code == 200, first.content
    assert first.json() == {'instances_created': 3, 'pruned_count': 1, 'errors': []}
    classes_after_first = GymClass.objects.filter(class_template=template).count()
    enrollments_after_first = Enrollment.objects.filter(gym_class__class_template=template).count()
    logs_after_first = ConsumptionLog.objects.filter(student_plan=membership).count()
    membership.refresh_from_db()
    used_after_first = membership.classes_used
    assert (classes_after_first, enrollments_after_first, logs_after_first, used_after_first) == (3, 3, 3, 3)

    second = api_client.post(ENDPOINT, {}, format='json', **host)

    assert second.status_code == 200, second.content
    # La segunda corrida no tiene NADA que hacer: ni instancias nuevas (ya están las 3 de la
    # ventana) ni podas (la única candidata ya se borró).
    assert second.json() == {'instances_created': 0, 'pruned_count': 0, 'errors': []}
    assert GymClass.objects.filter(class_template=template).count() == classes_after_first
    assert Enrollment.objects.filter(gym_class__class_template=template).count() == enrollments_after_first
    assert ConsumptionLog.objects.filter(student_plan=membership).count() == logs_after_first
    membership.refresh_from_db()
    assert membership.classes_used == used_after_first, 'el segundo click volvió a cobrar'


def test_inactive_organization_cannot_trigger_the_job(api_client, make_organization, make_user):
    """Organización suspendida: el botón no corre, ni siquiera con `include_inactive` en el body.

    El robot le DESCUENTA SALDO a los alumnos, así que un gimnasio suspendido no puede seguir
    consumiendo membresías por su cuenta (mismo guard que el barrido del comando). El override
    `--include-inactive` existe solo para el operador que arregla un calendario a mano desde el
    shell, sabiendo lo que cobra; por HTTP no hay forma de pedirlo.

    Se prueban las DOS capas, porque el token sobrevive a la suspensión (se emitió antes) y hay
    dos caminos de vuelta: por el subdominio de la org, `OrganizationMiddleware` corta con 404
    antes de que la vista exista; por un host de plataforma, el middleware no dice nada y el que
    corta es el guard de la vista con 403. Sin la segunda capa, ese segundo camino disparaba el
    job de una org suspendida."""
    ctx = _endpoint_org(make_organization, make_user, 'inactive')
    org = ctx['org']
    _login(api_client, ctx['admin'])  # el login pasa mientras la org está viva...
    org.is_active = False
    org.save(update_fields=['is_active'])

    # ...y el token sigue siendo válido después de suspenderla.
    by_platform_host = api_client.post(ENDPOINT, {'include_inactive': True}, format='json')
    by_subdomain = api_client.post(ENDPOINT, {}, format='json', **_host_of(org))

    assert by_platform_host.status_code == 403, by_platform_host.content
    assert by_subdomain.status_code == 404, by_subdomain.content
    _assert_untouched(ctx, 'una organización suspendida disparó el robot')


def test_unauthenticated_request_is_rejected(api_client, make_organization, make_user):
    """Sin token no hay puerta: 401, y ningún efecto. Red contra un `AllowAny` accidental —este
    endpoint sin autenticar sería un borrador de clases anónimo."""
    ctx = _endpoint_org(make_organization, make_user, 'anon')

    resp = api_client.post(ENDPOINT, {}, format='json', **_host_of(ctx['org']))

    assert resp.status_code == 401, resp.content
    _assert_untouched(ctx, 'un request sin autenticar disparó el robot')


def test_malformed_body_never_reaches_the_parser(api_client, make_organization, make_user):
    """Prueba directa de que la vista NO LEE `request.data`: se manda JSON roto.

    DRF parsea el body de forma perezosa —recién cuando alguien toca `request.data`—, así que un
    JSON inválido solo puede dar 400 si la vista lo lee. Que esto responda 200 es la evidencia de
    que no lo hace. Si mañana alguien le agrega un serializer de opciones al endpoint, este test
    se pone rojo y obliga a decidirlo a propósito en vez de reabrir sin querer la puerta de la
    org por payload."""
    ctx = _endpoint_org(make_organization, make_user, 'garbage')
    _login(api_client, ctx['admin'])

    resp = api_client.post(
        ENDPOINT, data='{"organization": ', content_type='application/json', **_host_of(ctx['org']),
    )

    assert resp.status_code == 200, resp.content
    assert resp.json() == {'instances_created': 3, 'pruned_count': 1, 'errors': []}
    _assert_advanced(ctx)


def test_errors_of_the_three_phases_reach_the_operator_flattened_and_sanitized(
    api_client, make_organization, make_user, monkeypatch,
):
    """Las TRES piezas del robot revientan en la misma corrida (extensión, sync y poda) y el
    endpoint sigue respondiendo 200 con las tres fallas en `errors` — GENÉRICAS.

    Tres cosas se fijan acá. Primero, que el aislamiento por pieza del servicio se vea desde HTTP:
    una serie corrupta no puede volverse un 500 opaco. Segundo, que el aplanado de la respuesta
    incluya las tres listas del summary (`extension_errors` + `sync_errors` + `prune_errors`): si
    alguna se olvidara, sus fallas desaparecerían en silencio y el botón diría "0 creadas, 0
    podadas, ningún error". Tercero —y es lo que este test vigila de verdad—: por HTTP viaja SOLO
    el prefijo identificatorio, nunca la clase de la excepción ni su mensaje. El servicio los
    formatea adentro de la línea (el cron los imprime para el operador) y un `IntegrityError` trae
    SQL y nombres de constraints; del otro lado de este endpoint hay un tenant. El detalle sigue
    disponible donde corresponde: `logger.exception` de cada fase."""
    ctx = _endpoint_org(make_organization, make_user, 'errors')

    def _boom_extension(template, *args, **kwargs):
        raise RuntimeError('extension boom con detalle interno')

    def _boom_sync(base_queryset):
        raise RuntimeError('sync boom con detalle interno')

    def _boom_prune(gym_class):
        raise RuntimeError('prune boom con detalle interno')

    monkeypatch.setattr(rolling_window, 'generate_instances_for_template_range', _boom_extension)
    monkeypatch.setattr(rolling_window, 'sync_class_statuses', _boom_sync)
    monkeypatch.setattr(rolling_window, '_delete_class_refunding_consumption', _boom_prune)
    _login(api_client, ctx['admin'])

    resp = api_client.post(ENDPOINT, {}, format='json', **_host_of(ctx['org']))

    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body['instances_created'] == 0
    assert body['pruned_count'] == 0
    # Una línea por fase, en el orden del pipeline (extender → sync → podar), con el prefijo que
    # le dice al gimnasio CUÁL de sus propias filas quedó afuera y nada más.
    assert body['errors'] == [
        f'plantilla {ctx["template"].id}: no se pudo procesar',
        f'sync {ctx["org"].id}: no se pudo procesar',
        f'clase {ctx["past_empty"].pk}: no se pudo procesar',
    ]
    # Ni la clase de la excepción ni su mensaje cruzan la puerta (se mira el body CRUDO, no solo
    # `errors`: la fuga podría aparecer en cualquier clave).
    raw = resp.content.decode()
    assert 'RuntimeError' not in raw
    assert 'boom' not in raw
    assert 'detalle interno' not in raw
    # Y nada se ejecutó a medias: la clase candidata sigue viva porque su borrado falló.
    assert GymClass.objects.filter(pk=ctx['past_empty'].pk).exists()


def test_the_endpoint_declares_its_own_throttle_scope():
    """El job es SÍNCRONO dentro del request: sin un freno propio, unos cuantos clicks ocupan los
    workers que sirven el resto de la app (prod es single-service, 3 workers). El scope y su rate se
    chequean por DECLARACIÓN y no simulando el límite real: el contador vive en el caché y un test
    que dispare N+1 requests es flaky —y con `LocMemCache` el conteo es por worker igual, así que
    el 6/hour es un freno de martilleo, no una garantía—."""
    assert AdvanceClassWindowsView.throttle_scope == 'advance_class_windows'
    assert ScopedRateThrottle in AdvanceClassWindowsView.throttle_classes
    assert settings.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']['advance_class_windows'] == '6/hour'


def test_options_does_not_publish_the_docstring(api_client, make_organization, make_user):
    """`OPTIONS` con la metadata default de DRF devuelve el docstring de la vista a cualquier
    usuario AUTENTICADO —de cualquier organización—, y este docstring documenta el flujo del
    operador de plataforma y el porqué de cada guarda. Con `metadata_class = None` DRF responde 405
    y no hay nada que leer. El endpoint solo habla POST."""
    ctx = _endpoint_org(make_organization, make_user, 'options')
    _login(api_client, ctx['admin'])

    resp = api_client.options(ENDPOINT, **_host_of(ctx['org']))

    assert resp.status_code == 405, resp.content
    body = resp.content.decode()
    assert 'ventana rodante' not in body
    assert 'superadmin' not in body
