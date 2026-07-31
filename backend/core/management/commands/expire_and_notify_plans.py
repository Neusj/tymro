"""Materializa el vencimiento de las membresías y avisa por correo (7.4, cierra #7).

Pensado para un Scheduled Job diario de Railway. Toda la lógica vive en
`core.services.plan_expiry_notifications`; acá solo van los argumentos y la salida.

    python manage.py expire_and_notify_plans            # corrida real
    python manage.py expire_and_notify_plans --dry-run  # muestra sin enviar ni mutar

Solo actúa sobre las organizaciones que activaron los avisos desde el admin: recién
desplegado, y hasta que alguien los active, no manda ni un correo.
"""
from django.core.management.base import BaseCommand

from core.services.plan_expiry_notifications import run_expiry_notifications


class Command(BaseCommand):
    help = 'Vence las membresías cuya fecha ya pasó y envía los avisos configurados.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--org-id', type=int, default=None,
            help='Procesar solo esta organización.',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='No envía correos ni modifica membresías: solo informa.',
        )

    def handle(self, *args, **options):
        summary = run_expiry_notifications(
            org_id=options.get('org_id'),
            dry_run=options['dry_run'],
        )

        for line in summary.lines:
            self.stdout.write(line)
        self.stdout.write(self.style.SUCCESS(
            f'Resumen: {summary.reminders_sent} recordatorios, '
            f'{summary.expiry_notices_sent} avisos de vencido, '
            f'{summary.plans_deactivated} membresías vencidas, '
            f'{summary.errors} errores'
        ))
