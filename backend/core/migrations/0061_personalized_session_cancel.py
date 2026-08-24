from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0060_delete_unused_personalized_qr_sessions'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='personalizedclasssession',
            name='cancelled_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='personalizedclasssession',
            name='cancellation_reason',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='personalizedclasssession',
            name='cancelled_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='cancelled_personalized_class_sessions',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name='personalizedclasssession',
            name='status',
            field=models.CharField(
                choices=[
                    ('pending', 'Pendiente'),
                    ('confirmed', 'Confirmada'),
                    ('finished', 'Dictada'),
                    ('cancelled', 'Anulada'),
                ],
                default='pending',
                max_length=20,
            ),
        ),
    ]
