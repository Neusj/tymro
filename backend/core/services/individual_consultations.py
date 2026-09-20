from dataclasses import dataclass
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from ..models import ConsultationDateChange, IndividualConsultation, Plan, TEACHER_ELIGIBLE_ROLES

User = get_user_model()


class ConsultationError(Exception):
    def __init__(self, message, code='consultation_invalid'):
        self.message, self.code = message, code
        super().__init__(message)


def _staff(actor):
    return actor and actor.organization_id and actor.role in TEACHER_ELIGIBLE_ROLES


def expire_due_consultations(organization_id, now=None):
    now = now or timezone.now()
    return IndividualConsultation.objects.filter(
        organization_id=organization_id,
        status__in=[IndividualConsultation.Status.AVAILABLE, IndividualConsultation.Status.SCHEDULED],
        expires_at__lt=now,
    ).update(status=IndividualConsultation.Status.EXPIRED, updated_at=now)


def create_consultation_from_payment(*, payment_transaction):
    """Materializa una sola consulta desde la transacción aprobada.

    La relación uno-a-uno con PaymentTransaction es la barrera de BD para los
    reintentos del webhook; no se introduce un identificador paralelo.
    """
    tx = payment_transaction
    product = tx.plan
    if not product or product.plan_type != Plan.PlanType.CONSULTATION:
        return None
    professional = product.consultation_professional
    if not professional or professional.organization_id != tx.organization_id or professional.role not in TEACHER_ELIGIBLE_ROLES or not professional.is_active:
        raise ConsultationError('El producto de consulta no tiene un profesional válido configurado.')
    now = timezone.now()
    consultation, _created = IndividualConsultation.objects.get_or_create(
        payment_transaction=tx,
        defaults={
            'organization_id': tx.organization_id, 'product': product, 'student': tx.user,
            'professional': professional, 'assigned_at': now,
            'expires_at': now + timedelta(days=product.duration_days),
            'expected_duration_minutes': product.consultation_duration_minutes,
            'status': IndividualConsultation.Status.AVAILABLE,
        },
    )
    return consultation


@transaction.atomic
def assign_consultation(*, actor, student_id, professional_id, product_id, agreed_at=None):
    if not actor or actor.role != 'gym_admin' or not actor.organization_id:
        raise ConsultationError('Solo el administrador puede asignar consultas.', 'forbidden')
    org_id = actor.organization_id
    product = Plan.objects.filter(id=product_id, organization_id=org_id, plan_type=Plan.PlanType.CONSULTATION, is_active=True).first()
    student = User.objects.filter(id=student_id, organization_id=org_id, role='student', is_active=True).first()
    professional = User.objects.filter(id=professional_id, organization_id=org_id, role__in=TEACHER_ELIGIBLE_ROLES, is_active=True).first()
    if not product: raise ConsultationError('El producto de consulta no está disponible.')
    if not student: raise ConsultationError('Alumno no encontrado en la organización.')
    if not professional: raise ConsultationError('Profesional no encontrado en la organización.')
    now = timezone.now()
    return IndividualConsultation.objects.create(
        organization_id=org_id, product=product, student=student, professional=professional,
        assigned_by=actor, assigned_at=now, expires_at=now + timedelta(days=product.duration_days),
        expected_duration_minutes=product.consultation_duration_minutes,
        agreed_at=agreed_at, status=IndividualConsultation.Status.SCHEDULED if agreed_at else IndividualConsultation.Status.AVAILABLE,
    )


def _can_manage(actor, consultation):
    return _staff(actor) and actor.organization_id == consultation.organization_id and (actor.role == 'gym_admin' or actor.id == consultation.professional_id)

def set_agreed_date(*, consultation_id, actor, agreed_at):
    # Persistir el vencimiento antes de abrir la transacción de la acción evita
    # que el 400 posterior revierta el historial de estado.
    IndividualConsultation.objects.filter(
        pk=consultation_id,
        status__in=[IndividualConsultation.Status.AVAILABLE, IndividualConsultation.Status.SCHEDULED],
        expires_at__lt=timezone.now(),
    ).update(status=IndividualConsultation.Status.EXPIRED, updated_at=timezone.now())
    return _set_agreed_date_locked(consultation_id=consultation_id, actor=actor, agreed_at=agreed_at)


@transaction.atomic
def _set_agreed_date_locked(*, consultation_id, actor, agreed_at):
    consultation = IndividualConsultation.objects.select_for_update().get(pk=consultation_id)
    if not _can_manage(actor, consultation): raise ConsultationError('No tienes permisos para modificar esta consulta.', 'forbidden')
    if consultation.status not in [consultation.Status.AVAILABLE, consultation.Status.SCHEDULED]: raise ConsultationError('La consulta ya no se puede reprogramar.')
    old = consultation.agreed_at
    consultation.agreed_at = agreed_at
    consultation.status = consultation.Status.SCHEDULED if agreed_at else consultation.Status.AVAILABLE
    consultation.save(update_fields=['agreed_at', 'status', 'updated_at'])
    ConsultationDateChange.objects.create(consultation=consultation, previous_agreed_at=old, new_agreed_at=agreed_at, changed_by=actor)
    return consultation


def start_consultation(*, consultation_id, actor, student_token):
    IndividualConsultation.objects.filter(
        pk=consultation_id,
        status__in=[IndividualConsultation.Status.AVAILABLE, IndividualConsultation.Status.SCHEDULED],
        expires_at__lt=timezone.now(),
    ).update(status=IndividualConsultation.Status.EXPIRED, updated_at=timezone.now())
    return _start_consultation_locked(consultation_id=consultation_id, actor=actor, student_token=student_token)


@transaction.atomic
def _start_consultation_locked(*, consultation_id, actor, student_token):
    consultation = IndividualConsultation.objects.select_for_update().select_related('student').get(pk=consultation_id)
    if not _can_manage(actor, consultation): raise ConsultationError('No tienes permisos para iniciar esta consulta.', 'forbidden')
    if str(consultation.student.student_qr_token) != str(student_token): raise ConsultationError('El QR no corresponde al alumno de esta consulta.', 'wrong_student')
    if consultation.status == consultation.Status.STARTED: raise ConsultationError('La consulta ya está iniciada.', 'already_started')
    if consultation.status not in [consultation.Status.AVAILABLE, consultation.Status.SCHEDULED]: raise ConsultationError('La consulta no está disponible para iniciar.')
    consultation.status, consultation.started_at, consultation.started_by = consultation.Status.STARTED, timezone.now(), actor
    consultation.save(update_fields=['status', 'started_at', 'started_by', 'updated_at'])
    return consultation


@transaction.atomic
def finish_consultation(*, consultation_id, actor):
    consultation = IndividualConsultation.objects.select_for_update().get(pk=consultation_id)
    if not _can_manage(actor, consultation): raise ConsultationError('No tienes permisos para finalizar esta consulta.', 'forbidden')
    if consultation.status == consultation.Status.FINISHED: raise ConsultationError('La consulta ya fue finalizada.', 'already_finished')
    if consultation.status != consultation.Status.STARTED: raise ConsultationError('La consulta debe estar iniciada antes de finalizarla.')
    now = timezone.now()
    consultation.status, consultation.finished_at, consultation.finished_by = consultation.Status.FINISHED, now, actor
    consultation.actual_duration_seconds = max(0, int((now - consultation.started_at).total_seconds()))
    consultation.save(update_fields=['status', 'finished_at', 'finished_by', 'actual_duration_seconds', 'updated_at'])
    return consultation
