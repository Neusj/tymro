import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import Q, UniqueConstraint
from django.db.models.functions import Lower


class CustomUser(AbstractUser):
    class Role(models.TextChoices):
        # Los labels (segundo valor) son la ÚNICA fuente de verdad de la etiqueta
        # legible del rol: se exponen vía get_role_display() (serializer role_display)
        # y accounts/roles.py ROLE_LABELS. Mantener en español.
        SUPERADMIN = 'superadmin', 'Superadministrador'
        GYM_ADMIN = 'gym_admin', 'Administrador'
        MANAGER = 'manager', 'Gerente'
        MONITOR = 'monitor', 'Monitor'
        TEACHER = 'teacher', 'Profesor'
        STUDENT = 'student', 'Alumno'

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.STUDENT)
    organization = models.ForeignKey(
        'core.Organization',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='users',
    )
    branch = models.ForeignKey(
        'core.Branch',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='users',
    )
    phone = models.CharField(max_length=40, blank=True)
    profile_image = models.ImageField(upload_to='users/profile_images/', blank=True, null=True)
    is_active_member = models.BooleanField(default=True)
    email_verified = models.BooleanField(default=False)
    has_used_trial = models.BooleanField(default=False)

    class Meta:
        constraints = [
            # Email único POR organización (case-insensitive). Permite el mismo email
            # en ORG A y ORG B; lo rechaza dentro de la misma org.
            UniqueConstraint(
                Lower('email'),
                'organization',
                condition=Q(organization__isnull=False) & ~Q(email=''),
                name='uniq_email_per_org',
            ),
            # Usuarios de plataforma (superadmin, organization NULL): email único GLOBAL
            # entre ellos. unique_together no validaría con org NULL, por eso va aparte.
            UniqueConstraint(
                Lower('email'),
                condition=Q(organization__isnull=True) & ~Q(email=''),
                name='uniq_email_platform',
            ),
        ]

    def save(self, *args, **kwargs):
        # `username` sigue siendo el USERNAME_FIELD de Django (único global), pero
        # ya no se pide: se auto-genera opaco. uuid4().hex pasa el validador de
        # username de Django (a diferencia de '{org}:{email}', que tiene ':' inválido).
        if not self.username:
            self.username = uuid.uuid4().hex
        super().save(*args, **kwargs)

    def __str__(self):
        return self.get_full_name() or self.email or self.username
