import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('accounts', '0011_teacher_payment_cycle')]

    operations = [
        migrations.AddField(
            model_name='customuser',
            name='student_qr_token',
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
    ]
