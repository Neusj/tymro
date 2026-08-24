"""Avisos de vencimiento de membresías (7.4). Motor del comando `expire_and_notify_plans`.

QUÉ DECIDE ESTE MÓDULO Y QUÉ NO
-------------------------------
No decide cuándo una membresía está vigente ni cuántos días le quedan: eso lo responde
`core.services.plans` —`StudentPlanQuerySet.valid_on` para seleccionar y
`describe_student_plan` para leer el estado— y acá se consume tal cual. Si el número de
días del correo saliera de una resta hecha en este archivo, el aviso podría contradecir a
la pantalla que el alumno ve al abrir la app.

Lo que sí decide:

1. **El día de corte es el de Santiago.** `timezone.localdate()`, nunca `date.today()`:
   con `USE_TZ=True` el proceso corre en UTC y entre las 20:00 y la medianoche chilena la
   fecha UTC ya avanzó, así que un plan que vence hoy se declararía vencido anoche.
2. **Vencer es una cuestión de FECHA.** Quedarse sin clases es `EXHAUSTED`, un estado
   distinto y con su propia ventana todavía abierta; 7.4 no lo toca.
3. **Una organización sin config activa no se toca**, ni siquiera para materializar el
   `is_active`. El job se despliega sobre alumnos reales y el opt-in es por gimnasio.
4. **Un aviso se manda una sola vez.** La prueba de que ya salió es la fila en
   `PlanExpiryNotification`, no la hora de la corrida: el scheduler pasa varias veces al
   día y las corridas se solapan.
"""
import logging
from dataclasses import dataclass, field
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from core.models import (
    OrganizationExpiryNotificationConfig,
    PlanExpiryNotification,
    StudentPlan,
)
from core.services.membership_freezes import complete_due_membership_freezes
from core.services.plans import PlanStatus, describe_student_plan

logger = logging.getLogger(__name__)

DATE_FORMAT = '%d-%m-%Y'

# Cuán viejo puede ser el cruce para que el aviso de "venció" todavía tenga sentido.
#
# El aviso es del CRUCE, no del estado. Sin esta ventana, el día en que un gimnasio marca
# la casilla en el admin recibe el correo TODA membresía vencida que haya quedado con
# `is_active=True` —hay años de esas: `activate_student_plan` deja el flag encendido para
# siempre y nada lo apagaba hasta ahora—, o sea un envío masivo a exalumnos sobre planes
# que vencieron hace meses. El margen igual absorbe que el scheduler se caiga un fin de
# semana largo. La materialización del flag NO usa esta ventana: apagar `is_active` es una
# consecuencia de la fecha y no le llega a nadie.
EXPIRY_NOTICE_GRACE_DAYS = 3


@dataclass
class RunSummary:
    reminders_sent: int = 0
    expiry_notices_sent: int = 0
    plans_deactivated: int = 0
    freezes_completed: int = 0
    errors: int = 0
    lines: list = field(default_factory=list)

    def note(self, message):
        self.lines.append(message)


def _student_name(student):
    """Saludo del correo. NUNCA `username`: se autogenera como `uuid4().hex`
    (`accounts.CustomUser.save`), así que caer ahí manda "Hola 3f2a9c4e…" y de paso
    publica un identificador interno."""
    return (
        (student.first_name or '').strip()
        or student.get_full_name().strip()
        or (student.email or '').split('@')[0]
        or 'de nuevo'
    )


def _email_recipient(membership, organization, summary):
    """Casilla a la que ESTA organización puede escribirle por esta membresía, o `None`.

    El queryset ya acotó la membresía por `organization_id`, pero el correo se arma
    dereferenciando dos FK que ese filtro no cubre —`user` y `plan`—, y ninguna de las dos
    está atada a la organización de la membresía:

    * `StudentPlan.user` es CASCADE sobre el USUARIO, no sobre la org. Un alumno movido de
      la organización A a la B conserva vivas las membresías que le vendió A, pero su
      cuenta pasa a estar administrada por el gym_admin de B —que puede cambiarle el
      email—. Seguir escribiendo dejaría el nombre del gimnasio A, el del plan y su fecha
      de vencimiento en una casilla que controla otro tenant.
    * `Plan.organization` es mutable y `Plan` no tiene `clean()`. Si el plan se movió, su
      `name` lo escribe ahora la otra organización.

    Es el agujero multitenant recurrente del repo —scopear por la FK propia sin
    intersectar `organization_id`— y `services/reservations.py` lo blinda igual.

    La guarda decide solo el ENVÍO. Materializar `is_active` sigue su curso: es una
    consecuencia de la fecha y no le llega a nadie.
    """
    student = membership.user
    if student.organization_id != organization.id:
        summary.note(
            f'omitido: el alumno {student.id} ya no pertenece a la organización '
            f'{organization.id} (membresía {membership.id})'
        )
        return None
    if membership.plan.organization_id != organization.id:
        summary.note(
            f'omitido: el plan {membership.plan_id} no es de la organización '
            f'{organization.id} (membresía {membership.id})'
        )
        return None
    if not student.is_active:
        summary.note(f'omitido: cuenta deshabilitada {student.id} (membresía {membership.id})')
        return None
    if not student.email:
        summary.note(f'sin email: alumno {student.id} (membresía {membership.id})')
        return None
    return student.email


def _days_phrase(days):
    return '1 día' if days == 1 else f'{days} días'


def _reminder_email(*, state, student, plan_name, org_name):
    subject = f'Tu plan en {org_name} vence en {_days_phrase(state.days_to_expiry)}'
    body = (
        f'Hola {_student_name(student)},\n\n'
        f'Tu plan "{plan_name}" en {org_name} vence el '
        f'{state.expiry_date.strftime(DATE_FORMAT)}: te quedan '
        f'{_days_phrase(state.days_to_expiry)}.\n\n'
        'Si quieres seguir entrenando, renueva antes de esa fecha para no perder '
        'tus reservas.\n\n'
        f'— Equipo {org_name}'
    )
    return subject, body


def _expired_email(*, state, student, plan_name, org_name):
    subject = f'Tu plan en {org_name} venció'
    body = (
        f'Hola {_student_name(student)},\n\n'
        f'Tu plan "{plan_name}" en {org_name} venció el '
        f'{state.expiry_date.strftime(DATE_FORMAT)}.\n\n'
        'Para volver a reservar clases necesitas renovarlo. '
        'Escríbenos y lo activamos.\n\n'
        f'— Equipo {org_name}'
    )
    return subject, body


def _deliver(*, student_plan, organization, kind, days_before, subject, body, recipient):
    """Registra el aviso y lo envía, o devuelve False si ya se había mandado.

    El `get_or_create` y el `send_mail` van en la MISMA transacción a propósito: si el
    envío falla, la fila de idempotencia se va con el rollback y la próxima corrida
    reintenta. Al revés —marcar primero, mandar después— un error de Resend perdería el
    aviso para siempre, porque la fila ya diría que salió.

    Dos consecuencias asumidas de ese orden, para que nadie las descubra depurando:

    * La transacción queda abierta durante la llamada HTTPS a Resend (timeout de Anymail:
      30 s) con la fila del índice único tomada, así que una corrida solapada espera ahí
      en vez de duplicar. Es el comportamiento buscado, pero es un lock sostenido por una
      llamada de red.
    * Si el envío sale bien y el COMMIT falla, el aviso se reenvía. Se prefiere un correo
      repetido antes que uno perdido.
    """
    with transaction.atomic():
        _, created = PlanExpiryNotification.objects.get_or_create(
            student_plan=student_plan,
            kind=kind,
            days_before=days_before,
            defaults={'organization_id': organization.id},
        )
        if not created:
            return False
        send_mail(
            subject=subject,
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient],
            fail_silently=False,
        )
    return True


def _send_reminders(config, today, dry_run, summary):
    organization = config.organization
    offsets = config.reminder_days_before
    if not offsets:
        return

    # Un solo SELECT para todos los offsets: las fechas de fin que caen justo en un
    # umbral. El scope por organización va en el filtro, no en el join del plan.
    target_dates = [today + timedelta(days=offset) for offset in offsets]
    memberships = (
        StudentPlan.objects
        .filter(organization_id=organization.id, end_date__in=target_dates)
        .valid_on(today)
        .select_related('user', 'plan')
        # El estado incluye el eje de pago, que sale de estas dos FKs inversas. El job no lo
        # usa, pero lo paga igual al leer el estado: sin prefetch es una consulta por membresía.
        .prefetch_related('origin_transactions', 'manual_payments')
    )

    for membership in memberships:
        state = describe_student_plan(membership, today)
        # `valid_on` ya filtró la ventana; esto solo blinda contra que las dos mitades de
        # la fuente única se separen. Un plan agotado o con matrícula impaga SÍ recibe el
        # recordatorio: su ventana sigue abierta y va a vencer igual.
        if not state.passes_valid_on or state.days_to_expiry not in offsets:
            continue

        recipient = _email_recipient(membership, organization, summary)
        if recipient is None:
            continue

        if dry_run:
            summary.reminders_sent += 1
            # El id y no el email: un `--dry-run` sobre toda la organización imprimiría si
            # no la base de correos de sus alumnos en los logs de Railway.
            summary.note(
                f'[DRY-RUN] recordatorio {state.days_to_expiry}d → alumno '
                f'{membership.user_id} (membresía {membership.id})'
            )
            continue

        subject, body = _reminder_email(
            state=state, student=membership.user,
            plan_name=membership.plan.name, org_name=organization.name,
        )
        try:
            if _deliver(
                student_plan=membership, organization=organization,
                kind=PlanExpiryNotification.Kind.REMINDER,
                days_before=state.days_to_expiry,
                subject=subject, body=body, recipient=recipient,
            ):
                summary.reminders_sent += 1
                logger.info(
                    'plan expiry reminder sent: plan=%s days=%s',
                    membership.id, state.days_to_expiry,
                )
        except Exception as exc:  # noqa: BLE001
            # Solo la CLASE de la excepción: los errores del backend de correo suelen
            # traer la dirección del destinatario adentro del mensaje.
            summary.errors += 1
            logger.exception('plan expiry reminder error: plan=%s', membership.id)
            summary.note(
                f'error recordatorio membresía {membership.id}: {exc.__class__.__name__}'
            )


def _expire(config, today, dry_run, summary):
    organization = config.organization

    # Candidatos: los que la fuente única dejó de cubrir POR FECHA y todavía arrastran el
    # flag encendido. `is_active=False` queda fuera adrede —ya salieron de circulación,
    # sea por una corrida anterior o por una baja manual— y `end_date__lt` deja fuera a los
    # agotados, que siguen dentro de su ventana.
    memberships = (
        StudentPlan.objects
        .filter(organization_id=organization.id, is_active=True, end_date__lt=today)
        .select_related('user', 'plan')
        .prefetch_related('origin_transactions', 'manual_payments')   # mismo N+1 que en los recordatorios
    )

    for membership in memberships:
        state = describe_student_plan(membership, today)
        if state.status != PlanStatus.EXPIRED:
            continue

        recent_crossing = state.days_to_expiry >= -EXPIRY_NOTICE_GRACE_DAYS
        recipient = None
        if config.send_expired_notice and recent_crossing:
            recipient = _email_recipient(membership, organization, summary)
        notify = recipient is not None

        if dry_run:
            summary.plans_deactivated += 1
            if notify:
                summary.expiry_notices_sent += 1
            summary.note(f'[DRY-RUN] vencida membresía {membership.id} (aviso={notify})')
            continue

        subject, body = (None, None)
        if notify:
            subject, body = _expired_email(
                state=state, student=membership.user,
                plan_name=membership.plan.name, org_name=organization.name,
            )

        try:
            if notify and _deliver(
                student_plan=membership, organization=organization,
                kind=PlanExpiryNotification.Kind.EXPIRED,
                days_before=None,
                subject=subject, body=body, recipient=recipient,
            ):
                summary.expiry_notices_sent += 1
                logger.info('plan expiry notice sent: plan=%s', membership.id)

            # La materialización va DESPUÉS del aviso: si se apagara el flag primero, un
            # envío fallido se perdería para siempre —el candidato ya no calificaría en la
            # próxima corrida, que exige `is_active=True`—. Con este orden, una excepción
            # de `_deliver` salta al `except` sin apagar nada y la membresía entera se
            # reintenta mañana. El reintento no es eterno: pasados
            # `EXPIRY_NOTICE_GRACE_DAYS` el cruce deja de ser reciente, `notify` cae a
            # False y la membresía se materializa sin correo.
            StudentPlan.objects.filter(pk=membership.pk, is_active=True).update(
                is_active=False, updated_at=timezone.now(),
            )
            summary.plans_deactivated += 1
        except Exception as exc:  # noqa: BLE001
            summary.errors += 1
            logger.exception('plan expiry notice error: plan=%s', membership.id)
            summary.note(
                f'error vencimiento membresía {membership.id}: {exc.__class__.__name__}'
            )


def run_expiry_notifications(*, today=None, org_id=None, dry_run=False):
    """Procesa todas las organizaciones con avisos activos. Devuelve un `RunSummary`."""
    today = today or timezone.localdate()
    summary = RunSummary()

    try:
        summary.freezes_completed = complete_due_membership_freezes(
            today=today,
            org_id=org_id,
            dry_run=dry_run,
        )
        if summary.freezes_completed:
            prefix = '[DRY-RUN] ' if dry_run else ''
            summary.note(f'{prefix}{summary.freezes_completed} congelamiento(s) cerrados automáticamente')
    except Exception as exc:  # noqa: BLE001
        summary.errors += 1
        logger.exception('membership freeze completion failed')
        summary.note(f'error cerrando congelamientos: {exc.__class__.__name__}')

    configs = (
        OrganizationExpiryNotificationConfig.objects
        # Una organización suspendida no le escribe a nadie con su marca.
        .filter(organization__is_active=True)
        .select_related('organization')
        .order_by('organization_id')
    )
    if org_id is not None:
        configs = configs.filter(organization_id=org_id)

    for config in configs:
        if not config.is_enabled:
            continue
        # Una organización no puede tumbar a las demás. El recorrido es por
        # `organization_id` ascendente y determinista: sin esta guarda, un tenant con la
        # config corrupta —`reminder_days_before` no es un `IntegerField`, y `clean()`
        # solo corre desde el form del admin— dejaría a TODOS los de id mayor sin avisos,
        # en silencio y en cada corrida.
        try:
            _send_reminders(config, today, dry_run, summary)
            _expire(config, today, dry_run, summary)
        except Exception as exc:  # noqa: BLE001
            summary.errors += 1
            logger.exception('expiry run failed for org=%s', config.organization_id)
            summary.note(
                f'organización {config.organization_id} omitida: {exc.__class__.__name__}'
            )
    return summary
