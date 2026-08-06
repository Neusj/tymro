"""Instrumento del cobro manual (`ManualPayment.method`): efectivo o transferencia (P3.2).

Compatibilidad con producción: la columna es `blank=True, default=''` y esta migración NO
hace backfill. Las filas que ya existen desde 8.2/8.3 quedan en `''` = "método no
registrado", que es literalmente lo único que se sabe de ellas: pudieron cobrarse en
efectivo o por transferencia y no hay ninguna otra columna de la que inferirlo. Poner
`cash` por ser el caso más común en un gimnasio fabricaría historia y ensuciaría desde el
día uno el reporte de P3.4, que es la razón de ser de esta columna. Mismo criterio que
`0042_manual_payment_branch.py` con `branch`: nada lee esta columna hoy, así que `''` no
cambia ningún comportamiento existente.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0042_manual_payment_branch'),
    ]

    operations = [
        migrations.AddField(
            model_name='manualpayment',
            name='method',
            field=models.CharField(
                blank=True,
                choices=[('cash', 'Efectivo'), ('transfer', 'Transferencia')],
                default='',
                help_text='Efectivo o transferencia. Vacío solo en filas históricas anteriores a P3.2.',
                max_length=16,
            ),
        ),
    ]
