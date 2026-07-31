"""7.4 — Avisos de vencimiento por organización (cierra #7). SOLO por fecha.

Tres piezas: la config por organización (apagada por defecto), la tabla de idempotencia
y el comando `expire_and_notify_plans`.

Lo que estos tests blindan, en orden de importancia:

1. **Nadie recibe nada hasta que su organización lo active.** El job se despliega sobre
   alumnos reales; una config vacía tiene que ser inerte, incluida la materialización del
   `is_active`.
2. **La fecha de corte es la de Santiago, no la de UTC.** Con `USE_TZ=True` el servidor
   corre en UTC y `date.today()` adelanta el vencimiento hasta 4 horas: un plan que vence
   hoy en Chile se declararía vencido la noche anterior.
3. **El vencimiento es POR FECHA.** Quedarse sin clases (`EXHAUSTED`) no vence nada: son
   dos estados distintos en `describe_student_plan` y el correo de "venció" mentiría.
4. **Reejecutar el job no reenvía.** El scheduler corre varias veces al día.
"""
from datetime import date, datetime, timedelta, timezone as dt_timezone

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.utils import timezone

from core.models import (
    OrganizationExpiryNotificationConfig,
    Plan,
    PlanExpiryNotification,
    StudentPlan,
)

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()


def _plan(org, name='Pack 10', total_classes=10, unlimited=False):
    return Plan.objects.create(
        organization=org, name=name, plan_type='pack',
        total_classes=total_classes, unlimited_classes=unlimited,
        duration_days=30, price=30000,
    )


def _membership(student, plan, *, start_offset=-20, end_offset=3, classes_used=0,
                is_active=True, today=None):
    base = today or TODAY
    return StudentPlan.objects.create(
        user=student, plan=plan, organization_id=plan.organization_id,
        start_date=base + timedelta(days=start_offset),
        end_date=base + timedelta(days=end_offset),
        total_classes=plan.total_classes, unlimited_classes=plan.unlimited_classes,
        classes_used=classes_used, final_price=30000, is_active=is_active,
    )


def _config(org, *, days=(), expired_notice=False):
    return OrganizationExpiryNotificationConfig.objects.create(
        organization=org,
        reminder_days_before=list(days),
        send_expired_notice=expired_notice,
    )


@pytest.fixture
def gym(make_organization, make_user):
    org = make_organization('Gimnasio Uno')
    student = make_user(
        'maria', organization=org, role='student',
        email='maria@gym.cl', first_name='Maria', last_name='Soto',
    )
    return {'org': org, 'student': student, 'plan': _plan(org)}


# ---- Config por organización: apagada por defecto ----

def test_config_defaults_are_disabled(make_organization):
    config = OrganizationExpiryNotificationConfig.objects.create(
        organization=make_organization(),
    )

    assert config.reminder_days_before == []
    assert config.send_expired_notice is False


def test_config_rejects_non_positive_days(make_organization):
    config = OrganizationExpiryNotificationConfig(
        organization=make_organization(), reminder_days_before=[5, 0],
    )

    with pytest.raises(ValidationError):
        config.full_clean()


def test_config_rejects_duplicate_days(make_organization):
    config = OrganizationExpiryNotificationConfig(
        organization=make_organization(), reminder_days_before=[5, 5],
    )

    with pytest.raises(ValidationError):
        config.full_clean()


def test_config_rejects_days_over_the_cap(make_organization):
    config = OrganizationExpiryNotificationConfig(
        organization=make_organization(),
        reminder_days_before=[OrganizationExpiryNotificationConfig.MAX_DAYS_BEFORE + 1],
    )

    with pytest.raises(ValidationError):
        config.full_clean()


def test_config_normalizes_days_to_descending_order(make_organization):
    config = OrganizationExpiryNotificationConfig(
        organization=make_organization(), reminder_days_before=[3, 15, 7],
    )

    config.full_clean()

    assert config.reminder_days_before == [15, 7, 3]


# ---- Recordatorio "por vencer" ----

def test_reminder_is_sent_once_on_the_exact_offset(gym, mailoutbox):
    membership = _membership(gym['student'], gym['plan'], end_offset=3)
    _config(gym['org'], days=[10, 3])

    call_command('expire_and_notify_plans')

    assert len(mailoutbox) == 1
    assert mailoutbox[0].to == ['maria@gym.cl']
    assert PlanExpiryNotification.objects.filter(
        student_plan=membership,
        kind=PlanExpiryNotification.Kind.REMINDER,
        days_before=3,
    ).count() == 1


def test_reminder_is_not_resent_on_a_second_run(gym, mailoutbox):
    _membership(gym['student'], gym['plan'], end_offset=3)
    _config(gym['org'], days=[3])

    call_command('expire_and_notify_plans')
    call_command('expire_and_notify_plans')

    assert len(mailoutbox) == 1


def test_reminder_body_carries_plan_end_date_and_days_left(gym, mailoutbox):
    membership = _membership(gym['student'], gym['plan'], end_offset=3)
    _config(gym['org'], days=[3])

    call_command('expire_and_notify_plans')

    body = mailoutbox[0].body
    assert 'Maria' in body
    assert 'Pack 10' in body
    assert membership.end_date.strftime('%d-%m-%Y') in body
    assert '3' in body
    assert 'Gimnasio Uno' in body


def test_no_reminder_when_no_offset_matches(gym, mailoutbox):
    _membership(gym['student'], gym['plan'], end_offset=7)
    _config(gym['org'], days=[10, 3])

    call_command('expire_and_notify_plans')

    assert mailoutbox == []
    assert not PlanExpiryNotification.objects.exists()


# ---- Cruce de vencimiento ----

def test_expiry_crossing_deactivates_and_notifies_once(gym, mailoutbox):
    membership = _membership(gym['student'], gym['plan'], end_offset=-1)
    _config(gym['org'], expired_notice=True)

    call_command('expire_and_notify_plans')
    call_command('expire_and_notify_plans')

    membership.refresh_from_db()
    assert membership.is_active is False
    assert len(mailoutbox) == 1
    assert mailoutbox[0].to == ['maria@gym.cl']
    assert PlanExpiryNotification.objects.filter(
        student_plan=membership,
        kind=PlanExpiryNotification.Kind.EXPIRED,
        days_before=None,
    ).count() == 1


def test_expiry_materializes_without_email_when_notice_is_off(gym, mailoutbox):
    # La org activó solo recordatorios: el job sigue materializando el flag —que es una
    # consecuencia de la fecha, no del correo— pero no le escribe a nadie.
    membership = _membership(gym['student'], gym['plan'], end_offset=-1)
    _config(gym['org'], days=[3])

    call_command('expire_and_notify_plans')

    membership.refresh_from_db()
    assert membership.is_active is False
    assert mailoutbox == []


def test_stale_expired_plan_is_deactivated_but_not_emailed(gym, mailoutbox):
    # El aviso es del CRUCE, no del estado. Cuando un gimnasio activa la casilla arrastra
    # membresías vencidas hace meses con el flag todavía encendido; mandarles "tu plan
    # venció" hoy sería un correo masivo sobre un hecho viejo. El flag sí se materializa:
    # es una consecuencia de la fecha y no le llega a nadie.
    membership = _membership(gym['student'], gym['plan'], start_offset=-90, end_offset=-60)
    _config(gym['org'], expired_notice=True)

    call_command('expire_and_notify_plans')

    membership.refresh_from_db()
    assert membership.is_active is False
    assert mailoutbox == []
    assert not PlanExpiryNotification.objects.exists()


def test_expiry_notice_survives_a_few_days_of_job_downtime(gym, mailoutbox):
    # El scheduler puede caerse un fin de semana: el cruce sigue siendo reciente y el
    # aviso tiene que salir igual.
    from core.services.plan_expiry_notifications import EXPIRY_NOTICE_GRACE_DAYS

    _membership(gym['student'], gym['plan'], end_offset=-EXPIRY_NOTICE_GRACE_DAYS)
    _config(gym['org'], expired_notice=True)

    call_command('expire_and_notify_plans')

    assert len(mailoutbox) == 1


def test_failed_send_leaves_the_plan_retryable(gym, mailoutbox, monkeypatch):
    # Red de seguridad del ORDEN de las dos escrituras. Si el correo falla (Resend caído),
    # ni la fila de idempotencia ni el `is_active` pueden quedar escritos: si quedaran, el
    # alumno nunca se enteraría de que su plan venció.
    from core.services import plan_expiry_notifications as service

    def boom(**kwargs):
        raise RuntimeError('resend caido')

    monkeypatch.setattr(service, 'send_mail', boom)
    membership = _membership(gym['student'], gym['plan'], end_offset=-1)
    _config(gym['org'], expired_notice=True)

    call_command('expire_and_notify_plans')

    membership.refresh_from_db()
    assert membership.is_active is True
    assert not PlanExpiryNotification.objects.exists()

    # Restaurado el transporte, la corrida siguiente lo manda.
    monkeypatch.undo()
    call_command('expire_and_notify_plans')

    membership.refresh_from_db()
    assert len(mailoutbox) == 1
    assert membership.is_active is False


def test_already_deactivated_plan_is_not_notified(gym, mailoutbox):
    # `is_active=False` significa "ya salió de circulación": el cruce ya pasó (o fue una
    # baja manual) y avisar ahora sería un correo tardío por un hecho viejo.
    _membership(gym['student'], gym['plan'], end_offset=-30, is_active=False)
    _config(gym['org'], expired_notice=True)

    call_command('expire_and_notify_plans')

    assert mailoutbox == []


def test_exhausted_plan_inside_its_window_is_not_expired(gym, mailoutbox):
    # Sin clases pero con fecha vigente: `describe_student_plan` lo reporta EXHAUSTED, no
    # EXPIRED. 7.4 es date-only, así que no se toca.
    membership = _membership(gym['student'], gym['plan'], end_offset=10, classes_used=10)
    _config(gym['org'], days=[3], expired_notice=True)

    call_command('expire_and_notify_plans')

    membership.refresh_from_db()
    assert membership.is_active is True
    assert mailoutbox == []
    assert not PlanExpiryNotification.objects.exists()


# ---- Config inerte y aislamiento por organización ----

def test_empty_config_sends_nothing_and_mutates_nothing(gym, mailoutbox):
    expiring = _membership(gym['student'], gym['plan'], end_offset=3)
    expired = _membership(gym['student'], gym['plan'], end_offset=-1)
    _config(gym['org'])

    call_command('expire_and_notify_plans')

    expired.refresh_from_db()
    expiring.refresh_from_db()
    assert mailoutbox == []
    assert expired.is_active is True
    assert expiring.is_active is True
    assert not PlanExpiryNotification.objects.exists()


def test_organization_without_config_is_untouched(gym, mailoutbox):
    membership = _membership(gym['student'], gym['plan'], end_offset=-1)

    call_command('expire_and_notify_plans')

    membership.refresh_from_db()
    assert mailoutbox == []
    assert membership.is_active is True


def test_config_of_one_org_does_not_reach_another(gym, mailoutbox, make_organization, make_user):
    _membership(gym['student'], gym['plan'], end_offset=3)
    _config(gym['org'], days=[3])

    other = make_organization('Gimnasio Dos')
    other_student = make_user('pedro', organization=other, role='student', email='pedro@gym.cl')
    _membership(other_student, _plan(other), end_offset=3)

    call_command('expire_and_notify_plans')

    assert [r for m in mailoutbox for r in m.to] == ['maria@gym.cl']


def test_org_id_flag_restricts_the_run(gym, mailoutbox, make_organization, make_user):
    _membership(gym['student'], gym['plan'], end_offset=3)
    _config(gym['org'], days=[3])

    other = make_organization('Gimnasio Dos')
    other_student = make_user('pedro', organization=other, role='student', email='pedro@gym.cl')
    _membership(other_student, _plan(other), end_offset=3)
    _config(other, days=[3])

    call_command('expire_and_notify_plans', org_id=other.id)

    assert [r for m in mailoutbox for r in m.to] == ['pedro@gym.cl']


def test_student_without_email_is_skipped(gym, mailoutbox, make_user):
    silent = make_user('sinmail', organization=gym['org'], role='student', email='')
    _membership(silent, gym['plan'], end_offset=3)
    _config(gym['org'], days=[3])

    call_command('expire_and_notify_plans')

    assert mailoutbox == []
    # Sin destinatario no hay envío que registrar: si mañana carga su email, lo recibe.
    assert not PlanExpiryNotification.objects.exists()


# ---- Guardas de coherencia entre la membresía y a quién se le escribe ----

def test_student_moved_to_another_org_is_not_emailed(gym, mailoutbox, make_organization):
    # La membresía se queda en la organización que la vendió —`user` es CASCADE sobre el
    # usuario, no sobre la org— así que sigue siendo candidata. Pero el alumno ya es de
    # otra organización, y ahí el gym_admin del NUEVO tenant administra esa cuenta: puede
    # cambiarle el email y quedarse leyendo el nombre del plan y del gimnasio anterior.
    membership = _membership(gym['student'], gym['plan'], end_offset=-1)
    gym['student'].organization = make_organization('Gimnasio Dos')
    gym['student'].save(update_fields=['organization'])
    _config(gym['org'], days=[3], expired_notice=True)

    call_command('expire_and_notify_plans')

    membership.refresh_from_db()
    assert mailoutbox == []
    # El flag sí se materializa: es una consecuencia de la fecha y no le llega a nadie.
    assert membership.is_active is False


def test_plan_moved_to_another_org_is_not_emailed(gym, mailoutbox, make_organization):
    # `Plan.organization` es mutable y el modelo no tiene `clean()`. Si el plan se movió,
    # su `name` ya lo controla el otro tenant: mandarlo sería publicar en un correo de
    # esta organización un texto escrito por otra.
    membership = _membership(gym['student'], gym['plan'], end_offset=3)
    plan = gym['plan']
    plan.organization = make_organization('Gimnasio Dos')
    plan.save(update_fields=['organization'])
    _config(gym['org'], days=[3])

    call_command('expire_and_notify_plans')

    assert mailoutbox == []


def test_deactivated_account_is_not_emailed(gym, mailoutbox):
    # Cuenta deshabilitada: no puede ni entrar a la app. "Renueva para no perder tus
    # reservas" no tiene a quién servirle.
    _membership(gym['student'], gym['plan'], end_offset=3)
    gym['student'].is_active = False
    gym['student'].save(update_fields=['is_active'])
    _config(gym['org'], days=[3])

    call_command('expire_and_notify_plans')

    assert mailoutbox == []


def test_inactive_organization_sends_nothing(gym, mailoutbox):
    _membership(gym['student'], gym['plan'], end_offset=3)
    _config(gym['org'], days=[3])
    gym['org'].is_active = False
    gym['org'].save(update_fields=['is_active'])

    call_command('expire_and_notify_plans')

    assert mailoutbox == []


def test_student_without_a_name_is_not_greeted_with_the_internal_username(gym, mailoutbox, make_user):
    # `username` se autogenera como `uuid4().hex` (accounts/models.py: se dejó de pedir y
    # es opaco): usarlo de saludo manda "Hola 3f2a9c4e…" y publica un identificador
    # interno. Este alumno no tiene nombre ni apellido, que es cuando aparecía.
    anon = make_user(
        '9f8e7d6c5b4a3f2e1d0c9b8a7f6e5d4c', organization=gym['org'], role='student',
        email='anonima@gym.cl', first_name='', last_name='',
    )
    _membership(anon, gym['plan'], end_offset=3)
    _config(gym['org'], days=[3])

    call_command('expire_and_notify_plans')

    body = mailoutbox[0].body
    assert anon.username not in body
    assert 'Hola anonima,' in body  # la parte local del correo, legible


def test_a_broken_org_does_not_block_the_rest(gym, mailoutbox, make_organization, make_user):
    # Las organizaciones se recorren por id ascendente. Sin aislamiento, una config rota
    # deja sin avisos —en silencio y para siempre— a todos los tenants de id mayor.
    _membership(gym['student'], gym['plan'], end_offset=3)
    broken = _config(gym['org'], days=[3])
    OrganizationExpiryNotificationConfig.objects.filter(pk=broken.pk).update(
        reminder_days_before=['no-es-un-numero'],
    )

    healthy = make_organization('Gimnasio Dos')
    other_student = make_user('pedro', organization=healthy, role='student', email='pedro@gym.cl')
    _membership(other_student, _plan(healthy), end_offset=3)
    _config(healthy, days=[3])

    call_command('expire_and_notify_plans')

    assert [r for m in mailoutbox for r in m.to] == ['pedro@gym.cl']


# ---- Zona horaria ----

def test_expiry_uses_santiago_date_not_utc(gym, mailoutbox, monkeypatch):
    # 2026-01-01 02:00 UTC son todavía las 23:00 del 31-12-2025 en Santiago (UTC-3 en
    # verano). Un plan que termina el 31-12 sigue vigente; con `date.today()` sobre UTC el
    # job lo declararía vencido y le mandaría el correo un día antes.
    frozen = datetime(2026, 1, 1, 2, 0, tzinfo=dt_timezone.utc)
    monkeypatch.setattr(timezone, 'now', lambda: frozen)

    membership = StudentPlan.objects.create(
        user=gym['student'], plan=gym['plan'], organization_id=gym['org'].id,
        start_date=date(2025, 12, 1), end_date=date(2025, 12, 31),
        total_classes=10, classes_used=0, final_price=30000, is_active=True,
    )
    _config(gym['org'], expired_notice=True)

    call_command('expire_and_notify_plans')

    membership.refresh_from_db()
    assert membership.is_active is True
    assert mailoutbox == []


def test_reminder_offset_is_measured_from_the_santiago_date(gym, mailoutbox, monkeypatch):
    # Mismo instante: en Santiago es 31-12, así que un plan que termina el 01-01 está a
    # 1 día. Sobre UTC estaría a 0 y el recordatorio no saldría nunca.
    frozen = datetime(2026, 1, 1, 2, 0, tzinfo=dt_timezone.utc)
    monkeypatch.setattr(timezone, 'now', lambda: frozen)

    StudentPlan.objects.create(
        user=gym['student'], plan=gym['plan'], organization_id=gym['org'].id,
        start_date=date(2025, 12, 1), end_date=date(2026, 1, 1),
        total_classes=10, classes_used=0, final_price=30000, is_active=True,
    )
    _config(gym['org'], days=[1])

    call_command('expire_and_notify_plans')

    assert len(mailoutbox) == 1


# ---- Dry run ----

def test_dry_run_neither_sends_nor_mutates(gym, mailoutbox):
    expiring = _membership(gym['student'], gym['plan'], end_offset=3)
    expired = _membership(gym['student'], gym['plan'], end_offset=-1)
    _config(gym['org'], days=[3], expired_notice=True)

    call_command('expire_and_notify_plans', dry_run=True)

    expiring.refresh_from_db()
    expired.refresh_from_db()
    assert mailoutbox == []
    assert expired.is_active is True
    assert not PlanExpiryNotification.objects.exists()
