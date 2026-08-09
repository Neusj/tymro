from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0049_organization_annual_enrollment_fee_and_manual_breakdown'),
    ]

    operations = [
        migrations.AlterField(
            model_name='manualpayment',
            name='method',
            field=models.CharField(
                blank=True,
                choices=[
                    ('cash', 'Efectivo'),
                    ('transfer', 'Transferencia'),
                    ('card', 'Tarjeta'),
                    ('check', 'Cheque'),
                ],
                default='',
                help_text='Efectivo, transferencia, tarjeta o cheque. Vacio solo en filas historicas anteriores a P3.2.',
                max_length=16,
            ),
        ),
    ]
