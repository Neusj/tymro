from django.core.management.base import BaseCommand

from core.models import Organization
from core.services.push_notifications import send_profile_completion_reminders


class Command(BaseCommand):
    help = 'Envia recordatorios push diarios por RUT/correo pendientes.'

    def add_arguments(self, parser):
        parser.add_argument('--organization-id', type=int, default=None)

    def handle(self, *args, **options):
        organization = None
        organization_id = options.get('organization_id')
        if organization_id:
            organization = Organization.objects.get(pk=organization_id)

        result = send_profile_completion_reminders(organization=organization)
        self.stdout.write(
            self.style.SUCCESS(
                f"Recordatorios push procesados: enviados={result['sent']} omitidos={result['skipped']}"
            )
        )
