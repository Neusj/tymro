"""Avisos de vencimiento por organización (7.4): config + registro de idempotencia.

La fila de config se crea para toda organización que exista AL APLICAR ESTA MIGRACIÓN,
pero con los defaults DESACTIVADOS —`reminder_days_before=[]`, `send_expired_notice=False`—.
Es a propósito: el job va a correr sobre alumnos reales apenas se despliegue, y no puede
salir ni un correo hasta que cada gimnasio active los avisos desde el admin. Crear las
filas apagadas (en vez de no crearlas) las deja listadas y editables en el admin desde el
minuto cero.

OJO: no hay hook en el alta de organización, así que los gimnasios onboardeados DESPUÉS
del deploy no tienen fila y no aparecen en ese listado —hay que crearles la config con el
"Add" del admin—. Falla del lado seguro (sin fila no se manda nada), pero la feature queda
invisible para los tenants nuevos hasta que alguien la cree. Automatizarlo es una decisión
pendiente: un `post_save` en `Organization` volvería universal la existencia de la fila.
"""
import django.db.models.deletion
from django.db import migrations, models


def create_disabled_configs(apps, schema_editor):
    Organization = apps.get_model('core', 'Organization')
    Config = apps.get_model('core', 'OrganizationExpiryNotificationConfig')

    configured = set(Config.objects.values_list('organization_id', flat=True))
    Config.objects.bulk_create([
        # Defaults explícitos y no implícitos: el modelo histórico de una migración no
        # corre `clean()`, así que lo que quede acá es exactamente lo que se persiste.
        Config(organization_id=org_id, reminder_days_before=[], send_expired_notice=False)
        for org_id in Organization.objects.values_list('id', flat=True)
        if org_id not in configured
    ])


def drop_configs(apps, schema_editor):
    # El rollback borra la tabla entera igual; esto solo la deja vacía primero para que
    # revertir la migración no dependa del orden de las operaciones.
    apps.get_model('core', 'OrganizationExpiryNotificationConfig').objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0030_studentplan_organization'),
    ]

    operations = [
        migrations.CreateModel(
            name='OrganizationExpiryNotificationConfig',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('reminder_days_before', models.JSONField(blank=True, default=list, help_text='Días de anticipación con que avisar el vencimiento, p. ej. [10, 3]. Vacío = no se envían recordatorios.')),
                ('send_expired_notice', models.BooleanField(default=False, help_text='¿Avisar al alumno el día en que su plan vence?')),
                ('organization', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='expiry_notification_config', to='core.organization')),
            ],
            options={
                'verbose_name': 'Configuración de avisos de vencimiento',
                'verbose_name_plural': 'Configuraciones de avisos de vencimiento',
            },
        ),
        migrations.CreateModel(
            name='PlanExpiryNotification',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('kind', models.CharField(choices=[('reminder', 'Por vencer'), ('expired', 'Vencido')], max_length=16)),
                ('days_before', models.PositiveIntegerField(blank=True, null=True)),
                ('sent_at', models.DateTimeField(auto_now_add=True)),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='plan_expiry_notifications', to='core.organization')),
                ('student_plan', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='expiry_notifications', to='core.studentplan')),
            ],
            options={
                'ordering': ['-sent_at'],
            },
        ),
        migrations.AddConstraint(
            model_name='planexpirynotification',
            constraint=models.UniqueConstraint(condition=models.Q(('days_before__isnull', False)), fields=('student_plan', 'kind', 'days_before'), name='uniq_plan_expiry_reminder_per_offset'),
        ),
        migrations.AddConstraint(
            model_name='planexpirynotification',
            constraint=models.UniqueConstraint(condition=models.Q(('days_before__isnull', True)), fields=('student_plan', 'kind'), name='uniq_plan_expiry_notice_without_offset'),
        ),
        migrations.RunPython(create_disabled_configs, drop_configs),
    ]
