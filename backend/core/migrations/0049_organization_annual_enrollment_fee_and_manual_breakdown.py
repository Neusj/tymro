from decimal import Decimal

import django.core.validators
from django.db import migrations, models


def backfill_manual_payment_breakdown(apps, schema_editor):
    ManualPayment = apps.get_model('core', 'ManualPayment')
    ManualPayment.objects.update(plan_amount=models.F('amount'), enrollment_fee_amount=Decimal('0'))


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0048_organization_max_reservation_window_days'),
    ]

    operations = [
        migrations.AddField(
            model_name='organization',
            name='annual_enrollment_fee',
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                help_text='Matrícula anual del gimnasio. 0 = sin matrícula.',
                max_digits=10,
                validators=[django.core.validators.MinValueValidator(Decimal('0'))],
            ),
        ),
        migrations.AddField(
            model_name='manualpayment',
            name='enrollment_fee_amount',
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                help_text='Parte del cobro manual imputada a la matrícula anual.',
                max_digits=10,
                validators=[django.core.validators.MinValueValidator(Decimal('0'))],
            ),
        ),
        migrations.AddField(
            model_name='manualpayment',
            name='plan_amount',
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                help_text='Parte del cobro manual imputada al plan.',
                max_digits=10,
                validators=[django.core.validators.MinValueValidator(Decimal('0'))],
            ),
        ),
        migrations.RunPython(backfill_manual_payment_breakdown, migrations.RunPython.noop),
    ]
