"""P3.4 · Pieza 3 — rastro de ocupación de las clases vacías que la poda borra.

Tabla nueva y nada más: no hay backfill posible (las clases ya podadas se borraron y su
capacidad/horario no quedó en ninguna parte). El histórico de ocupación empieza a
construirse desde el primer `advance_class_windows` posterior a este deploy, y hasta
entonces el reporte mide solo sobre las clases vivas.
"""
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0044_payment_refund_tracking'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ClassOccupancySnapshot',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('source_class_id', models.BigIntegerField()),
                ('source', models.CharField(choices=[('prune', 'Poda de ventana rodante')], default='prune', max_length=20)),
                ('branch_name', models.CharField(blank=True, default='', max_length=150)),
                ('discipline_name', models.CharField(blank=True, default='', max_length=150)),
                ('teacher_name', models.CharField(blank=True, default='', max_length=200)),
                ('class_name', models.CharField(blank=True, default='', max_length=150)),
                ('start_datetime', models.DateTimeField()),
                ('end_datetime', models.DateTimeField()),
                ('capacity', models.PositiveIntegerField(default=0)),
                ('enrolled_count', models.PositiveIntegerField(default=0)),
                ('pruned_at', models.DateTimeField(default=django.utils.timezone.now)),
            ],
            options={
                'ordering': ['-start_datetime', '-id'],
            },
        ),
        migrations.AddField(
            model_name='classoccupancysnapshot',
            name='branch',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='class_occupancy_snapshots', to='core.branch'),
        ),
        migrations.AddField(
            model_name='classoccupancysnapshot',
            name='discipline',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='class_occupancy_snapshots', to='core.discipline'),
        ),
        migrations.AddField(
            model_name='classoccupancysnapshot',
            name='organization',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='class_occupancy_snapshots', to='core.organization'),
        ),
        migrations.AddField(
            model_name='classoccupancysnapshot',
            name='teacher',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='class_occupancy_snapshots', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddIndex(
            model_name='classoccupancysnapshot',
            index=models.Index(fields=['organization', 'start_datetime'], name='core_classo_organiz_b179e9_idx'),
        ),
        migrations.AddConstraint(
            model_name='classoccupancysnapshot',
            constraint=models.UniqueConstraint(fields=('organization', 'source_class_id'), name='uniq_occupancy_snapshot_per_class'),
        ),
    ]
