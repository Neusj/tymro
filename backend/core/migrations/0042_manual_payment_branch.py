"""Sucursal de la membresía en el cobro manual (`ManualPayment.branch`).

Registro histórico de dónde se cobró, derivado de `student_plan.branch` en la única puerta
de escritura (`services/manual_payments.record_manual_payment`).

Compatibilidad con producción: la columna es nullable y NO hay backfill. Las filas
existentes quedan en NULL = "sin sede registrada", que es literalmente lo que se sabe de
ellas. Un backfill desde `student_plan.branch` sería una invención retroactiva: la
membresía pudo cambiar de sede después del cobro, y esta columna existe justamente para
congelar el dato del momento. Nada lee esta columna todavía, así que NULL no cambia ningún
comportamiento.
"""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0041_payment_account_branch'),
    ]

    operations = [
        migrations.AddField(
            model_name='manualpayment',
            name='branch',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='manual_payments', to='core.branch'),
        ),
    ]
