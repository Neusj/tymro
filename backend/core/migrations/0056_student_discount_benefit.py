from django.db import migrations, models
import django.core.validators


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0055_studentplanfreeze'),
    ]

    operations = [
        migrations.AddField(
            model_name='organization',
            name='student_discount_percentage',
            field=models.FloatField(default=0, help_text='Descuento estudiante para planes mensuales. 0 = sin beneficio monetario.', validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(100)]),
        ),
        migrations.AddField(
            model_name='paymenttransaction',
            name='discount_amount',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10),
        ),
        migrations.AddField(
            model_name='paymenttransaction',
            name='discount_percentage',
            field=models.FloatField(default=0),
        ),
        migrations.AddField(
            model_name='paymenttransaction',
            name='discount_source',
            field=models.CharField(blank=True, default='', max_length=30),
        ),
        migrations.AddField(
            model_name='paymenttransaction',
            name='plan_original_amount',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10),
        ),
        migrations.AddField(
            model_name='studentplan',
            name='discount_source',
            field=models.CharField(blank=True, default='', max_length=30),
        ),
    ]
