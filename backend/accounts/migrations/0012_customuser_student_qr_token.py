import uuid

from django.db import migrations, models


def assign_distinct_student_qr_tokens(apps, schema_editor):
    """Backfill seguro para PostgreSQL: un UUID nuevo por fila existente."""
    CustomUser = apps.get_model('accounts', 'CustomUser')
    # Incluye valores preexistentes por defensa ante una ejecución manual previa;
    # la migración normal de PostgreSQL es atómica, pero esto no asume ese hecho.
    used_tokens = set(
        CustomUser.objects.exclude(student_qr_token__isnull=True).values_list('student_qr_token', flat=True)
    )
    for user in CustomUser.objects.filter(student_qr_token__isnull=True).iterator():
        token = uuid.uuid4()
        while token in used_tokens:
            token = uuid.uuid4()
        used_tokens.add(token)
        CustomUser.objects.filter(pk=user.pk).update(student_qr_token=token)


class Migration(migrations.Migration):
    dependencies = [('accounts', '0011_teacher_payment_cycle')]

    operations = [
        migrations.AddField(
            model_name='customuser',
            name='student_qr_token',
            # No usar default+unique al agregar sobre PostgreSQL: el default se
            # materializa como un único valor para las filas históricas.
            field=models.UUIDField(null=True, editable=False),
        ),
        migrations.RunPython(assign_distinct_student_qr_tokens, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='customuser',
            name='student_qr_token',
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
    ]
