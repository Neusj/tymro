from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0066_organization_allow_started_class_substitution'),
    ]

    operations = [
        migrations.AddField(
            model_name='gymclass',
            name='reactivated_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='gymclass',
            name='reactivated_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='reactivated_classes',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
