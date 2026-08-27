from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('core', '0061_personalized_session_cancel'),
    ]

    operations = [
        migrations.AddField(
            model_name='enrollment',
            name='created_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='created_enrollments',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
