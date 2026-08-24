from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0056_student_discount_benefit'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='PushPreference',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('push_enabled', models.BooleanField(default=False)),
                ('prompt_status', models.CharField(choices=[('undecided', 'Sin decidir'), ('dismissed', 'Postergado'), ('enabled', 'Activado'), ('blocked', 'Bloqueado')], default='undecided', max_length=16)),
                ('last_profile_reminder_sent_on', models.DateField(blank=True, null=True)),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='push_preferences', to='core.organization')),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='push_preference', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['user_id'],
                'indexes': [
                    models.Index(fields=['organization', 'push_enabled'], name='core_pushpr_organiz_71766b_idx'),
                    models.Index(fields=['prompt_status'], name='core_pushpr_prompt__50c2b6_idx'),
                ],
            },
        ),
        migrations.CreateModel(
            name='PushSubscription',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('endpoint', models.TextField(unique=True)),
                ('p256dh', models.TextField()),
                ('auth', models.TextField()),
                ('user_agent', models.TextField(blank=True, default='')),
                ('is_active', models.BooleanField(default=True)),
                ('deactivated_at', models.DateTimeField(blank=True, null=True)),
                ('last_error', models.TextField(blank=True, default='')),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='push_subscriptions', to='core.organization')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='push_subscriptions', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at', '-id'],
                'indexes': [
                    models.Index(fields=['organization', 'is_active'], name='core_pushsu_organiz_e2d178_idx'),
                    models.Index(fields=['user', 'is_active'], name='core_pushsu_user_id_35c075_idx'),
                ],
            },
        ),
        migrations.CreateModel(
            name='PushNotification',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('event_type', models.CharField(max_length=64)),
                ('dedupe_key', models.CharField(max_length=160)),
                ('title', models.CharField(max_length=120)),
                ('body', models.TextField()),
                ('data', models.JSONField(blank=True, default=dict)),
                ('status', models.CharField(choices=[('pending', 'Pendiente'), ('sent', 'Enviada'), ('skipped', 'Omitida'), ('failed', 'Fallida')], default='pending', max_length=16)),
                ('sent_at', models.DateTimeField(blank=True, null=True)),
                ('sent_count', models.PositiveIntegerField(default=0)),
                ('error', models.TextField(blank=True, default='')),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='push_notifications', to='core.organization')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='push_notifications', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at', '-id'],
                'indexes': [
                    models.Index(fields=['organization', 'event_type'], name='core_pushno_organiz_60b195_idx'),
                    models.Index(fields=['user', 'event_type'], name='core_pushno_user_id_1a2f4b_idx'),
                ],
            },
        ),
        migrations.AddConstraint(
            model_name='pushnotification',
            constraint=models.UniqueConstraint(fields=('organization', 'user', 'event_type', 'dedupe_key'), name='uniq_push_notification_event_per_user'),
        ),
    ]
