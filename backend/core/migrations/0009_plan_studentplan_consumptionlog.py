from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0008_holiday_source_type'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Plan',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('name', models.CharField(max_length=120)),
                ('plan_type', models.CharField(choices=[('monthly', 'Mensual'), ('pack', 'Pack'), ('single_class', 'Clase suelta'), ('trial', 'Trial'), ('giftcard', 'Giftcard')], max_length=20)),
                ('total_classes', models.IntegerField()),
                ('duration_days', models.IntegerField()),
                ('price', models.FloatField()),
                ('discount_percentage', models.FloatField(default=0)),
                ('is_public', models.BooleanField(default=True)),
                ('is_active', models.BooleanField(default=True)),
            ],
            options={
                'ordering': ['name'],
            },
        ),
        migrations.DeleteModel(
            name='StudentPlan',
        ),
        migrations.CreateModel(
            name='StudentPlan',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('start_date', models.DateField()),
                ('end_date', models.DateField()),
                ('total_classes', models.IntegerField()),
                ('classes_used', models.IntegerField(default=0)),
                ('discount_percentage', models.FloatField(default=0)),
                ('final_price', models.FloatField(blank=True, null=True)),
                ('is_active', models.BooleanField(default=True)),
                ('plan', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='student_plans', to='core.plan')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='student_plans', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-start_date'],
            },
        ),
        migrations.CreateModel(
            name='ConsumptionLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('consumed_at', models.DateTimeField(auto_now_add=True)),
                ('class_instance', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='consumption_logs', to='core.gymclass')),
                ('student_plan', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='consumption_logs', to='core.studentplan')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='consumption_logs', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-consumed_at'],
            },
        ),
    ]
