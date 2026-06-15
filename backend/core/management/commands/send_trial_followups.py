"""Envía el email de seguimiento a los alumnos que asistieron a una clase de prueba.

Pensado para correr periódicamente (Scheduled Job de Railway, p.ej. cada 5 min).
Es IDEMPOTENTE: marca cada asistencia con ``trial_followup_sent_at`` y nunca
reenvía. Respeta multitenancy: cada organización usa su propia configuración y
solo se tocan sus clases/alumnos.

Variables disponibles en el asunto/cuerpo configurables:
{student_name}, {org_name}, {class_name}, {teacher_name}, {signup_link}.
"""
import logging
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core.models import Attendance, Enrollment, GymClass, TrialFollowupConfiguration

logger = logging.getLogger(__name__)

# "Asistió" = estuvo físicamente en la clase. Los ausentes/no-show no reciben el email.
ATTENDED_STATUSES = {Attendance.Status.PRESENT, Attendance.Status.LATE}


def _render(template, context):
    """Sustitución tolerante: reemplaza solo las variables conocidas y nunca
    falla por llaves sueltas en una plantilla escrita por el gimnasio."""
    text = template or ''
    for key, value in context.items():
        text = text.replace('{' + key + '}', str(value))
    return text


class Command(BaseCommand):
    help = 'Envía emails de seguimiento a alumnos que asistieron a una clase de prueba.'

    def add_arguments(self, parser):
        parser.add_argument('--org-id', type=int, default=None, help='Procesar solo esta organización.')
        parser.add_argument('--dry-run', action='store_true', help='No envía ni marca: solo muestra.')

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        org_id = options.get('org_id')
        now = timezone.now()

        configs = (
            TrialFollowupConfiguration.objects.filter(is_active=True)
            .select_related('organization')
        )
        if org_id:
            configs = configs.filter(organization_id=org_id)

        total_sent = 0
        total_errors = 0

        for config in configs:
            org = config.organization
            cutoff = now - timedelta(minutes=config.minutes_after_class_end)
            classes = GymClass.objects.filter(
                organization_id=org.id,
                status__in=[GymClass.Status.COMPLETED, GymClass.Status.COMPLETED_EARLY],
                end_datetime__lte=cutoff,
            ).select_related('teacher')

            base = settings.FRONTEND_URL.rstrip('/')
            signup_link = f'{base}/{org.slug}/clase-gratis'

            for gym_class in classes:
                trial_student_ids = set(
                    Enrollment.objects.filter(
                        gym_class=gym_class, is_trial=True, status='active',
                    ).values_list('student_id', flat=True)
                )
                if not trial_student_ids:
                    continue

                attendances = Attendance.objects.select_related('student').filter(
                    gym_class=gym_class,
                    student_id__in=trial_student_ids,
                    status__in=ATTENDED_STATUSES,
                    trial_followup_sent_at__isnull=True,
                )

                teacher = gym_class.teacher
                teacher_name = 'tu instructor'
                if teacher:
                    teacher_name = f'{teacher.first_name} {teacher.last_name}'.strip() or teacher.username

                for attendance in attendances:
                    student = attendance.student
                    if not student or not student.email:
                        continue

                    context = {
                        'student_name': student.first_name or student.username or '',
                        'org_name': org.name,
                        'class_name': gym_class.name,
                        'teacher_name': teacher_name,
                        'signup_link': signup_link,
                    }
                    subject = _render(config.email_subject, context)
                    body = _render(config.email_body, context)

                    if dry_run:
                        self.stdout.write(f'[DRY-RUN] {student.email} ← {gym_class.name}')
                        total_sent += 1
                        continue

                    try:
                        with transaction.atomic():
                            # Lock + re-chequeo: dos corridas en paralelo no duplican el envío.
                            locked = Attendance.objects.select_for_update().get(pk=attendance.pk)
                            if locked.trial_followup_sent_at is not None:
                                continue
                            send_mail(
                                subject=subject,
                                message=body,
                                from_email=settings.DEFAULT_FROM_EMAIL,
                                recipient_list=[student.email],
                                fail_silently=False,
                            )
                            locked.trial_followup_sent_at = timezone.now()
                            locked.save(update_fields=['trial_followup_sent_at', 'updated_at'])
                        total_sent += 1
                        logger.info('trial followup sent: %s class=%s', student.email, gym_class.id)
                        self.stdout.write(self.style.SUCCESS(f'✓ {student.email} ({gym_class.name})'))
                    except Exception as exc:  # noqa: BLE001
                        total_errors += 1
                        logger.error('trial followup error: %s %s', student.email, exc)
                        self.stderr.write(self.style.ERROR(f'✗ {student.email}: {exc}'))

        self.stdout.write(self.style.SUCCESS(f'Resumen: {total_sent} enviados, {total_errors} errores'))
