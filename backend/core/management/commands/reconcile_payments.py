from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import PaymentTransaction
from core.services import payments


class Command(BaseCommand):
    help = 'Reconciliar transacciones pendientes contra el proveedor de pago (backstop de webhooks).'

    def add_arguments(self, parser):
        parser.add_argument('--minutes', type=int, default=10,
                            help='Antigüedad mínima (min) de la transacción para reconciliar.')

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(minutes=options['minutes'])
        qs = PaymentTransaction.objects.filter(
            status__in=['pending', 'in_process'], processed_at__isnull=True,
            created_at__lte=cutoff, provider_payment_id__isnull=False,
        )
        done = 0
        for tx in qs.iterator():
            try:
                payments.reconcile_transaction(tx=tx)
                done += 1
            except Exception as exc:   # noqa: BLE001 - loguear y continuar con el resto
                self.stderr.write(f'tx {tx.id}: {exc}')
        self.stdout.write(self.style.SUCCESS(f'Reconciliadas {done} transacciones.'))
