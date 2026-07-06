from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import PaymentAccount
from core.services import payments


class Command(BaseCommand):
    help = 'Refrescar proactivamente tokens OAuth de pago próximos a vencer.'

    def handle(self, *args, **options):
        soon = timezone.now() + payments.REFRESH_MARGIN
        qs = PaymentAccount.objects.filter(
            status=PaymentAccount.STATUS_CONNECTED, token_expires_at__lte=soon)
        ok = 0
        for account in qs.iterator():
            try:
                payments.get_valid_access_token(account=account)
                ok += 1
            except Exception as exc:   # noqa: BLE001
                self.stderr.write(f'account {account.id}: {exc}')
        self.stdout.write(self.style.SUCCESS(f'Refrescadas {ok} cuentas.'))
