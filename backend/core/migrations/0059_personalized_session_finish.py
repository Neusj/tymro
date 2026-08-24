from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0058_personalized_classes'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='personalizedclasssession',
            name='finished_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='personalizedclasssession',
            name='finished_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='finished_personalized_class_sessions',
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
                ],
                default='pending',
                max_length=20,
            ),
        ),
        migrations.AddIndex(
            model_name='personalizedclasssession',
            index=models.Index(
                fields=['organization', 'status', 'finished_at'],
                name='core_person_organiz_2e3d35_idx',
            ),
        ),
    ]
