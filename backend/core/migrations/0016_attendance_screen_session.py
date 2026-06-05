from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0015_alter_gymclass_status_labels'),
    ]

    operations = [
        migrations.AddField(
            model_name='organization',
            name='attendance_screen_session_code',
            field=models.CharField(blank=True, max_length=16, null=True, unique=True),
        ),
        migrations.AddField(
            model_name='organization',
            name='attendance_screen_session_expires_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
