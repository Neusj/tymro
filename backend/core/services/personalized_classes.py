from dataclasses import dataclass
from datetime import datetime

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from ..models import (
    Attendance,
    AttendanceChangeLog,
    ConsumptionLog,
    PersonalizedClassSession,
    Plan,
    StudentPlan,
    TEACHER_ELIGIBLE_ROLES,
)
from .plans import describe_student_plan
from .reservations import _revert_consumption_logs


PERSONALIZED_NO_PLAN_MESSAGE = 'No tienes sesiones personalizadas disponibles.'
User = get_user_model()


class PersonalizedClassError(Exception):
    def __init__(self, message, code='personalized_class_invalid', extra=None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.extra = extra or {}


@dataclass(frozen=True)
class PersonalizedClassResult:
    session: PersonalizedClassSession
    attendance: Attendance
    consumption: ConsumptionLog
    remaining_classes: int | None
    created_attendance: bool


def _plan_covers_branch(student_plan, branch_id):
    plan_branch_id = getattr(getattr(student_plan, 'plan', None), 'branch_id', None)
    return not plan_branch_id or not branch_id or plan_branch_id == branch_id


def _m2m_contains_or_empty(manager, item_id):
    if not manager.exists():
        return True
    if item_id is None:
        return False
    return manager.filter(id=item_id).exists()


def _plan_allows_teacher(plan, teacher):
    if not plan.allowed_personalized_teachers.exists():
        return True
    if teacher is None:
        return False
    return plan.allowed_personalized_teachers.filter(id=teacher.id).exists()


def _plan_matches_session(student_plan, session):
    plan = student_plan.plan
    if plan.plan_type != Plan.PlanType.PERSONALIZED:
        return False
    if not _plan_covers_branch(student_plan, session.branch_id):
        return False
    if not _plan_allows_teacher(plan, session.teacher):
        return False
    if not _m2m_contains_or_empty(plan.compatible_disciplines, session.discipline_id):
        return False
    if not _m2m_contains_or_empty(plan.compatible_class_types, session.class_type_id):
        return False
    return True


def personalized_plan_candidates(student, session, on_date=None):
    target_date = on_date or timezone.localdate()
    queryset = (
        StudentPlan.objects
        .select_related('plan', 'user')
        .prefetch_related(
            'freezes',
            'plan__allowed_personalized_teachers',
            'plan__compatible_disciplines',
            'plan__compatible_class_types',
        )
        .filter(
            user=student,
            organization_id=session.organization_id,
            plan__plan_type=Plan.PlanType.PERSONALIZED,
        )
        .valid_on(target_date)
    )
    candidates = [
        student_plan
        for student_plan in queryset
        if describe_student_plan(student_plan, target_date).is_usable
        and _plan_matches_session(student_plan, session)
    ]
    # Determinístico: consume primero la membresía que vence antes; empate por inicio e id.
    return sorted(candidates, key=lambda item: (item.end_date, item.start_date, item.id))


def resolve_personalized_student_plan(student, session, on_date=None):
    candidates = personalized_plan_candidates(student, session, on_date=on_date)
    if not candidates:
        raise PersonalizedClassError(PERSONALIZED_NO_PLAN_MESSAGE, code='personalized_plan_unavailable')
    return candidates[0]


def validate_personalized_teacher(teacher):
    if not teacher or not teacher.organization_id:
        raise PersonalizedClassError('Solo profesores del gimnasio pueden iniciar clases personalizadas.')
    if teacher.role not in TEACHER_ELIGIBLE_ROLES:
        raise PersonalizedClassError('Solo profesores del gimnasio pueden iniciar clases personalizadas.')
    if not teacher.organization.personalized_classes_enabled:
        raise PersonalizedClassError('Las clases personalizadas no están habilitadas para esta organización.')
    return teacher


def _virtual_session_from_qr_payload(payload, teacher):
    expires_at = payload.get('expires_at')
    if timezone.is_naive(expires_at):
        expires_at = timezone.make_aware(expires_at, timezone.get_current_timezone())
    issued_at = payload.get('issued_at') or timezone.now().isoformat()
    try:
        issued_at = datetime.fromisoformat(issued_at)
    except (TypeError, ValueError):
        issued_at = timezone.now()
    if timezone.is_naive(issued_at):
        issued_at = timezone.make_aware(issued_at, timezone.get_current_timezone())
    return PersonalizedClassSession(
        organization=teacher.organization,
        organization_id=teacher.organization_id,
        branch_id=payload.get('branch_id'),
        teacher=teacher,
        teacher_id=teacher.id,
        discipline_id=payload.get('discipline_id'),
        class_type_id=payload.get('class_type_id'),
        qr_jti=payload.get('qr_jti'),
        qr_issued_at=issued_at,
        qr_expires_at=expires_at,
    )


@transaction.atomic
def finish_personalized_session(*, session_id, actor):
    session = (
        PersonalizedClassSession.objects
        .select_for_update(of=('self',))
        .select_related('organization', 'teacher', 'student', 'student_plan__plan', 'branch', 'discipline', 'class_type')
        .get(pk=session_id)
    )

    if not actor or not getattr(actor, 'organization_id', None):
        raise PersonalizedClassError('Solo profesores del gimnasio pueden finalizar clases personalizadas.')
    if actor.organization_id != session.organization_id:
        raise PersonalizedClassError('No tienes permisos para finalizar esta clase personalizada.', code='forbidden')
    if actor.role not in TEACHER_ELIGIBLE_ROLES:
        raise PersonalizedClassError('Solo profesores del gimnasio pueden finalizar clases personalizadas.', code='forbidden')
    if actor.role == 'teacher' and session.teacher_id != actor.id:
        raise PersonalizedClassError('Solo puedes finalizar clases personalizadas que dictas.', code='forbidden')
    if not session.organization.personalized_classes_enabled:
        raise PersonalizedClassError('Las clases personalizadas no estÃ¡n habilitadas para esta organizaciÃ³n.')
    if session.status == PersonalizedClassSession.Status.FINISHED:
        return session
    if session.status != PersonalizedClassSession.Status.CONFIRMED:
        raise PersonalizedClassError('La clase todavÃ­a no tiene alumno registrado.', code='not_confirmed')

    session.status = PersonalizedClassSession.Status.FINISHED
    session.finished_at = timezone.now()
    session.finished_by = actor
    session.save(update_fields=['status', 'finished_at', 'finished_by', 'updated_at'])
    return session


def _validate_personalized_session_staff_actor(actor, session, action):
    if not actor or not getattr(actor, 'organization_id', None):
        raise PersonalizedClassError(f'Solo profesores del gimnasio pueden {action} clases personalizadas.')
    if actor.organization_id != session.organization_id:
        raise PersonalizedClassError(f'No tienes permisos para {action} esta clase personalizada.', code='forbidden')
    if actor.role not in TEACHER_ELIGIBLE_ROLES:
        raise PersonalizedClassError(f'Solo profesores del gimnasio pueden {action} clases personalizadas.', code='forbidden')
    if actor.role == 'teacher' and session.teacher_id != actor.id:
        raise PersonalizedClassError(f'Solo puedes {action} clases personalizadas que dictas.', code='forbidden')
    if not session.organization.personalized_classes_enabled:
        raise PersonalizedClassError('Las clases personalizadas no estÃƒÂ¡n habilitadas para esta organizaciÃƒÂ³n.')


@transaction.atomic
def cancel_personalized_session(*, session_id, actor, reason=''):
    session = (
        PersonalizedClassSession.objects
        .select_for_update(of=('self',))
        .select_related('organization', 'teacher', 'student', 'student_plan__plan', 'branch', 'discipline', 'class_type')
        .get(pk=session_id)
    )

    _validate_personalized_session_staff_actor(actor, session, 'anular')
    if session.status == PersonalizedClassSession.Status.CANCELLED:
        return session
    if session.status not in {
        PersonalizedClassSession.Status.CONFIRMED,
        PersonalizedClassSession.Status.FINISHED,
    }:
        raise PersonalizedClassError('La clase todavia no tiene alumno registrado.', code='not_confirmed')

    now = timezone.now()
    _revert_consumption_logs(
        ConsumptionLog.objects.filter(
            personalized_session=session,
            student_plan__organization_id=session.organization_id,
        )
    )

    attendance = Attendance.objects.filter(
        personalized_session=session,
        student_id=session.student_id,
    ).select_for_update().first()
    if attendance is not None and attendance.status != Attendance.Status.ABSENT:
        previous_status = attendance.status
        attendance.status = Attendance.Status.ABSENT
        attendance.source = Attendance.Source.MANUAL
        attendance.marked_by = actor
        attendance.marked_at = now
        attendance.checked_at = now
        attendance.save(update_fields=['status', 'source', 'marked_by', 'marked_at', 'checked_at', 'updated_at'])
        AttendanceChangeLog.objects.create(
            attendance=attendance,
            previous_status=previous_status,
            new_status=Attendance.Status.ABSENT,
            changed_by=actor,
            changed_at=now,
            organization_id=session.organization_id,
            source=Attendance.Source.MANUAL,
        )

    session.status = PersonalizedClassSession.Status.CANCELLED
    session.cancelled_at = now
    session.cancelled_by = actor
    session.cancellation_reason = str(reason or '').strip()
    session.save(update_fields=['status', 'cancelled_at', 'cancelled_by', 'cancellation_reason', 'updated_at'])
    return session


@transaction.atomic
def confirm_personalized_qr(*, payload, student):
    now = timezone.now()
    teacher = (
        User.objects
        .select_related('organization')
        .filter(
            id=payload.get('teacher_id'),
            organization_id=payload.get('organization_id'),
            role__in=TEACHER_ELIGIBLE_ROLES,
            is_active=True,
        )
        .first()
    )
    if teacher is None:
        raise PersonalizedClassError('Profesor no habilitado para esta organizaciÃ³n.', code='teacher_not_allowed')
    if not teacher.organization.personalized_classes_enabled:
        raise PersonalizedClassError('Las clases personalizadas no estÃ¡n habilitadas para esta organizaciÃ³n.')
    if student.organization_id != teacher.organization_id:
        raise PersonalizedClassError('Este QR pertenece a otro gimnasio.', code='wrong_organization')
    if payload.get('expires_at') <= now:
        raise PersonalizedClassError('El QR expirÃ³. Pide al profesor generar uno nuevo.', code='expired_qr')
    if PersonalizedClassSession.objects.filter(qr_jti=payload.get('qr_jti')).exists():
        raise PersonalizedClassError('Este QR ya fue utilizado.', code='qr_reused')

    virtual_session = _virtual_session_from_qr_payload(payload, teacher)
    chosen_plan = resolve_personalized_student_plan(student, virtual_session, on_date=timezone.localdate(now))
    chosen_plan = (
        StudentPlan.objects
        .select_for_update()
        .select_related('plan', 'user')
        .prefetch_related(
            'freezes',
            'plan__allowed_personalized_teachers',
            'plan__compatible_disciplines',
            'plan__compatible_class_types',
        )
        .get(pk=chosen_plan.pk)
    )
    if not describe_student_plan(chosen_plan, timezone.localdate(now)).is_usable or not _plan_matches_session(chosen_plan, virtual_session):
        raise PersonalizedClassError(PERSONALIZED_NO_PLAN_MESSAGE, code='personalized_plan_unavailable')

    try:
        with transaction.atomic():
            session = PersonalizedClassSession.objects.create(
                organization=teacher.organization,
                branch_id=payload.get('branch_id'),
                teacher=teacher,
                student=student,
                student_plan=chosen_plan,
                discipline_id=payload.get('discipline_id'),
                class_type_id=payload.get('class_type_id'),
                qr_jti=payload.get('qr_jti'),
                qr_issued_at=virtual_session.qr_issued_at,
                qr_expires_at=payload.get('expires_at'),
                confirmed_by=student,
                confirmed_at=now,
                status=PersonalizedClassSession.Status.CONFIRMED,
            )
    except IntegrityError:
        raise PersonalizedClassError('Este QR ya fue utilizado.', code='qr_reused')

    try:
        consumption = ConsumptionLog.objects.create(
            user=student,
            student_plan=chosen_plan,
            personalized_session=session,
            branch_id=session.branch_id,
        )
    except IntegrityError:
        raise PersonalizedClassError('Este QR ya fue utilizado.', code='qr_reused')

    StudentPlan.objects.filter(pk=chosen_plan.pk).update(
        classes_used=F('classes_used') + 1,
        updated_at=timezone.now(),
    )
    chosen_plan.refresh_from_db(fields=['classes_used', 'updated_at'])

    attendance, created = Attendance.objects.update_or_create(
        personalized_session=session,
        student=student,
        defaults={
            'gym_class': None,
            'status': Attendance.Status.PRESENT,
            'source': Attendance.Source.QR,
            'marked_by': student,
            'marked_at': now,
            'checked_at': now,
        },
    )
    remaining = None if chosen_plan.unlimited_classes else max(
        (chosen_plan.total_classes or 0) - (chosen_plan.classes_used or 0),
        0,
    )
    return PersonalizedClassResult(
        session=session,
        attendance=attendance,
        consumption=consumption,
        remaining_classes=remaining,
        created_attendance=created,
    )


@transaction.atomic
def confirm_personalized_session(*, session_id, qr_jti, student):
    session = (
        PersonalizedClassSession.objects
        .select_for_update(of=('self',))
        .select_related('organization', 'teacher', 'branch', 'discipline', 'class_type')
        .get(pk=session_id)
    )
    now = timezone.now()

    if not session.organization.personalized_classes_enabled:
        raise PersonalizedClassError('Las clases personalizadas no están habilitadas para esta organización.')
    if session.qr_jti != qr_jti:
        raise PersonalizedClassError('QR inválido.', code='invalid_qr')
    if session.qr_expires_at <= now:
        raise PersonalizedClassError('El QR expiró. Pide al profesor generar uno nuevo.', code='expired_qr')
    if session.status != PersonalizedClassSession.Status.PENDING:
        raise PersonalizedClassError('Este QR ya fue utilizado.', code='qr_reused')
    if student.organization_id != session.organization_id:
        raise PersonalizedClassError('Este QR pertenece a otro gimnasio.', code='wrong_organization')
    if not session.teacher_id or session.teacher.organization_id != session.organization_id:
        raise PersonalizedClassError('Profesor no habilitado para esta organización.', code='teacher_not_allowed')
    if session.teacher.role not in TEACHER_ELIGIBLE_ROLES or not session.teacher.is_active:
        raise PersonalizedClassError('Profesor no habilitado para esta organización.', code='teacher_not_allowed')

    chosen_plan = resolve_personalized_student_plan(student, session, on_date=timezone.localdate(now))
    chosen_plan = (
        StudentPlan.objects
        .select_for_update()
        .select_related('plan', 'user')
        .prefetch_related(
            'freezes',
            'plan__allowed_personalized_teachers',
            'plan__compatible_disciplines',
            'plan__compatible_class_types',
        )
        .get(pk=chosen_plan.pk)
    )
    if not describe_student_plan(chosen_plan, timezone.localdate(now)).is_usable or not _plan_matches_session(chosen_plan, session):
        raise PersonalizedClassError(PERSONALIZED_NO_PLAN_MESSAGE, code='personalized_plan_unavailable')

    session.student = student
    session.student_plan = chosen_plan
    session.confirmed_by = student
    session.confirmed_at = now
    session.status = PersonalizedClassSession.Status.CONFIRMED
    session.save(update_fields=[
        'student', 'student_plan', 'confirmed_by', 'confirmed_at', 'status', 'updated_at',
    ])

    try:
        consumption = ConsumptionLog.objects.create(
            user=student,
            student_plan=chosen_plan,
            personalized_session=session,
            branch_id=session.branch_id,
        )
    except IntegrityError:
        raise PersonalizedClassError('Este QR ya fue utilizado.', code='qr_reused')

    StudentPlan.objects.filter(pk=chosen_plan.pk).update(
        classes_used=F('classes_used') + 1,
        updated_at=timezone.now(),
    )
    chosen_plan.refresh_from_db(fields=['classes_used', 'updated_at'])

    existing = Attendance.objects.filter(personalized_session=session, student=student).first()
    attendance, created = Attendance.objects.update_or_create(
        personalized_session=session,
        student=student,
        defaults={
            'gym_class': None,
            'status': Attendance.Status.PRESENT,
            'source': Attendance.Source.QR,
            'marked_by': student,
            'marked_at': now,
            'checked_at': now,
        },
    )
    if existing is not None and existing.status != Attendance.Status.PRESENT:
        AttendanceChangeLog.objects.create(
            attendance=attendance,
            previous_status=existing.status,
            new_status=Attendance.Status.PRESENT,
            changed_by=student,
            changed_at=now,
            organization_id=session.organization_id,
            source=Attendance.Source.QR,
        )

    remaining = None if chosen_plan.unlimited_classes else max(
        (chosen_plan.total_classes or 0) - (chosen_plan.classes_used or 0),
        0,
    )
    return PersonalizedClassResult(
        session=session,
        attendance=attendance,
        consumption=consumption,
        remaining_classes=remaining,
        created_attendance=created,
    )
