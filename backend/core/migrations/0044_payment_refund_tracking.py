"""P3.4 · Pieza 0 — dinero cobrado y dinero devuelto en `PaymentTransaction`.

Agrega `collected_at`, `refunded_at`, `refunded_amount` y los dos índices que usa la
reportería de ingresos, y BACKFILLEA `collected_at` sobre lo ya cobrado: sin el backfill el
reporte arrancaría con un histórico en cero y el ingreso de todo lo vendido hasta hoy
quedaría invisible.
"""
from django.db import migrations, models


def backfill_collected_at(apps, schema_editor):
    """`collected_at` = cuándo entró la plata, para las filas anteriores a P3.4.

    Se toma `processed_at` cuando existe (es el instante exacto en que el webhook aplicó el
    cobro) y `updated_at` cuando no, que es el caso raro pero real de la tx COBRADA cuya
    activación de membresía falló (`plan_org_mismatch`): la plata entró igual y el reporte
    tiene que verla. Se filtra por `status='approved'` porque es el único estado que
    significa "cobrado" en las filas viejas.

    OJO con el histórico irrecuperable: una fila que se cobró y DESPUÉS se devolvió tiene
    hoy `status='refunded'` y ya perdió el rastro de haber estado aprobada (era justo el
    agujero que P3.4 cierra). Esas filas quedan sin `collected_at` a propósito: inventarles
    un cobro sin poder inventar también la devolución haría que el neto histórico mintiera
    hacia arriba. Son las devoluciones ocurridas antes de este deploy y no hay dato local
    para reconstruirlas.
    """
    PaymentTransaction = apps.get_model('core', 'PaymentTransaction')
    PaymentTransaction.objects.filter(
        status='approved', collected_at__isnull=True, processed_at__isnull=False,
    ).update(collected_at=models.F('processed_at'))
    PaymentTransaction.objects.filter(
        status='approved', collected_at__isnull=True, processed_at__isnull=True,
    ).update(collected_at=models.F('updated_at'))


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0043_manual_payment_method'),
    ]

    operations = [
        migrations.AddField(
            model_name='paymenttransaction',
            name='collected_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='paymenttransaction',
            name='refunded_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='paymenttransaction',
            name='refunded_amount',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10),
        ),
        migrations.AddIndex(
            model_name='paymenttransaction',
            index=models.Index(fields=['organization', 'collected_at'],
                               name='core_paymen_organiz_64dc93_idx'),
        ),
        migrations.AddIndex(
            model_name='paymenttransaction',
            index=models.Index(fields=['organization', 'refunded_at'],
                               name='core_paymen_organiz_fb1117_idx'),
        ),
        # `migrations.RunPython.noop` en la reversa: bajar la migración borra las columnas,
        # así que no hay nada que desandar.
        migrations.RunPython(backfill_collected_at, migrations.RunPython.noop),
    ]
