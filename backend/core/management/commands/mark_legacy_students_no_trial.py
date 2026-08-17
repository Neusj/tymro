from datetime import datetime, time

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime


def _parse_cutoff(value):
    if not value:
        return timezone.now()

    parsed_datetime = parse_datetime(value)
    if parsed_datetime is not None:
        if timezone.is_naive(parsed_datetime):
            return timezone.make_aware(parsed_datetime, timezone.get_current_timezone())
        return parsed_datetime

    parsed_date = parse_date(value)
    if parsed_date is not None:
        naive = datetime.combine(parsed_date, time.min)
        return timezone.make_aware(naive, timezone.get_current_timezone())

    raise CommandError('Formato invalido para --before. Usa ISO 8601, por ejemplo 2026-08-17T12:00:00.')


class Command(BaseCommand):
    help = (
        'Marca alumnos legacy como no elegibles para clase de prueba gratis '
        '(trial_eligible=False).'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--before',
            default=None,
            help=(
                'Fecha/hora de corte por date_joined. Si se omite, usa el momento actual. '
                'Ejemplo: 2026-08-17T12:00:00'
            ),
        )
        parser.add_argument(
            '--org-id',
            type=int,
            default=None,
            help='Procesar solo una organizacion.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Informa cuantos alumnos cambiaria, sin modificar datos.',
        )

    def handle(self, *args, **options):
        User = get_user_model()
        cutoff = _parse_cutoff(options.get('before'))

        queryset = User.objects.filter(
            role=User.Role.STUDENT,
            organization__isnull=False,
            trial_eligible=True,
            date_joined__lt=cutoff,
        )
        org_id = options.get('org_id')
        if org_id is not None:
            queryset = queryset.filter(organization_id=org_id)

        total = queryset.count()
        scope = f'org_id={org_id}' if org_id is not None else 'todas las organizaciones'
        self.stdout.write(
            f'Alumnos legacy elegibles antes de {cutoff.isoformat()} ({scope}): {total}'
        )

        if options['dry_run']:
            self.stdout.write('DRY-RUN: no se modificaron alumnos.')
            return

        updated = queryset.update(trial_eligible=False)
        self.stdout.write(self.style.SUCCESS(
            f'Alumnos marcados sin clase gratis: {updated}'
        ))
