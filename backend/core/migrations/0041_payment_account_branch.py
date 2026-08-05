"""Cuentas de cobro por sucursal (`PaymentAccount.branch`) + trazabilidad en la transacción.

Compatibilidad con producción: las cuentas que ya existen quedan con `branch=NULL`, o sea
como cuenta PRINCIPAL de su organización, que es exactamente lo que eran hasta ahora. Sin
marcar ninguna sede, todas heredan esa cuenta y el cobro no cambia.

El `unique_together (organization, provider)` se reemplaza por un unique PARCIAL sobre
(organización, proveedor) `WHERE branch IS NULL`. Sobre los datos existentes —todos con
`branch NULL`— las dos reglas son equivalentes, así que el `AddConstraint` no puede fallar
en el `migrate` pre-deploy: el unique viejo ya garantizaba esa unicidad.
"""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0040_gymclass_uniq_class_instance_per_template_slot'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='paymentaccount',
            unique_together=set(),
        ),
        migrations.AddField(
            model_name='paymentaccount',
            name='branch',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='payment_accounts', to='core.branch'),
        ),
        migrations.AddField(
            model_name='paymenttransaction',
            name='branch',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='payment_transactions', to='core.branch'),
        ),
        migrations.AddField(
            model_name='paymenttransaction',
            name='payment_account',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='transactions', to='core.paymentaccount'),
        ),
        migrations.AddConstraint(
            model_name='paymentaccount',
            constraint=models.UniqueConstraint(condition=models.Q(('branch__isnull', True)), fields=('organization', 'provider'), name='uniq_main_payment_account_per_org'),
        ),
        migrations.AddConstraint(
            model_name='paymentaccount',
            constraint=models.UniqueConstraint(condition=models.Q(('branch__isnull', False)), fields=('organization', 'branch', 'provider'), name='uniq_branch_payment_account'),
        ),
    ]
