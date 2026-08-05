"""Avanza la ventana rodante de materialización de series y poda las clases vacías que
quedaron atrás (Task 2 de rolling-window). Comando FINO, calcado del molde de
`expire_and_notify_plans`: toda la lógica vive en
`core.services.rolling_window.run_advance_class_windows` — acá solo van los argumentos y
la impresión del resumen.

Pensado para un Scheduled Job DIARIO de Railway:

    python manage.py advance_class_windows                                # todas las orgs activas
    python manage.py advance_class_windows --org-id 3                     # solo esa organización (se saltea si está inactiva)
    python manage.py advance_class_windows --org-id 3 --include-inactive  # fuerza la corrida aunque esté inactiva

ADVERTENCIA: el guard de `is_active` es PAREJO en las tres formas de invocación. Sin
`--include-inactive`, una organización inactiva se SALTEA siempre —tanto en el barrido
default como apuntando `--org-id` a su id puntual—: se loguea un WARNING y queda registrada
en el resumen, sin cortar la corrida (exit 0, nunca `CommandError`). El override es el
flag: `--include-inactive` fuerza el procesamiento de organizaciones inactivas (todas, si
no hay `--org-id`; o solo la puntual, si la hay). Ejecutarlo con este flag a mano contra un
gimnasio suspendido materializa clases nuevas y le descuenta saldo REAL a sus alumnos igual
que si la organización estuviera activa —es la corrida manual de un operador que necesita
arreglar el calendario de una org suspendida a propósito, no un modo gratis—.
"""
from django.core.management.base import BaseCommand, CommandError

from core.models import Organization
from core.services.rolling_window import run_advance_class_windows


class Command(BaseCommand):
    help = 'Extiende la ventana rodante de clases y poda las vacías pasadas.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--org-id', type=int, default=None,
            help='Procesar solo esta organización (se saltea si está inactiva; ver --include-inactive).',
        )
        parser.add_argument(
            '--include-inactive', action='store_true',
            help='Procesar también organizaciones inactivas; sin este flag se saltean.',
        )

    def handle(self, *args, **options):
        org_id = options.get('org_id')
        include_inactive = options['include_inactive']
        try:
            result = run_advance_class_windows(org_id=org_id, include_inactive=include_inactive)
        except Organization.DoesNotExist:
            raise CommandError(f'Organización {org_id} no existe')

        for org_summary in result['org_summaries']:
            errors_count = (
                len(org_summary['extension_errors'])
                + len(org_summary['sync_errors'])
                + len(org_summary['prune_errors'])
            )
            self.stdout.write(
                f"org {org_summary['org_id']} ({org_summary['org_name']}): "
                f"{org_summary['instances_created']} clases creadas, "
                f"{org_summary['pruned_count']} podadas, "
                f"{errors_count} errores"
            )

        for skipped in result['skipped_inactive']:
            self.stdout.write(self.style.WARNING(
                f"org {skipped['org_id']} ({skipped['org_name']}): "
                f"inactiva — salteada (usar --include-inactive)"
            ))

        for error in result['errors']:
            self.stdout.write(self.style.WARNING(error))

        summary_line = (
            f"Resumen: {result['orgs_processed']} organizaciones, "
            f"{result['instances_created']} clases creadas, "
            f"{result['pruned_count']} podadas, "
            f"{len(result['errors'])} errores"
        )
        # Un error no puede tumbar el cron (rolling_window.py ya lo aisló por org/plantilla/
        # clase): se informa con WARNING pero el comando termina con exit 0 igual.
        if result['errors']:
            self.stdout.write(self.style.WARNING(summary_line))
        else:
            self.stdout.write(self.style.SUCCESS(summary_line))
