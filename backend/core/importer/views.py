"""Endpoints del importador de datos (/api/imports/...).

Acceso exclusivo gym_admin/superadmin (enforced aquí; el frontend es cosmético).
Multitenancy: la organización destino sale SIEMPRE de ``request.user`` (gym_admin)
o de un parámetro explícito ``organization`` (superadmin, que no tiene org propia).
El archivo subido jamás aporta la organización.
"""
from django.http import Http404, HttpResponse
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.models import CustomUser
from core.models import Organization
from core.permissions import IsSuperAdminOrGymAdmin

from . import specs  # noqa: F401  (registra los specs de entidades)
from .engine import (
    IMPORT_TOKEN_MAX_AGE,
    ImportCommitError,
    ImportFileError,
    run_commit,
    run_validate,
)
from .registry import UnknownEntityError, all_specs, get_spec
from .templates import build_template

XLSX_CONTENT_TYPE = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


def _field_payload(field):
    payload = {
        'attr': field.attr,
        'label': field.label,
        'type': field.kind,
        'required': field.required,
        'example': field.example,
        'max_length': field.max_length,
        'choices': [str(label) for label, _ in field.choices] or None,
        'help_text': field.help_text,
    }
    if field.kind == 'bool':
        payload['choices'] = ['Sí', 'No']
    if field.fk:
        payload['reference'] = {
            'label': field.fk.reference_label,
            'lookup': field.fk.lookup_field,
        }
    return payload


def _spec_payload(spec):
    return {
        'slug': spec.slug,
        'label': spec.label,
        'description': spec.description,
        'dependencies': list(spec.dependencies),
        'max_rows': spec.max_rows,
        'natural_key_labels': [spec.field_by_attr(attr).label for attr in spec.natural_key],
        'instructions': list(spec.instructions),
        'fields': [_field_payload(field) for field in spec.fields],
    }


class ImporterViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated, IsSuperAdminOrGymAdmin]
    lookup_field = 'entity'
    lookup_value_regex = r'[a-z0-9-]+'

    def _get_spec(self, entity, user):
        try:
            spec = get_spec(entity)
        except UnknownEntityError:
            raise Http404
        if spec.extra_permission and not spec.extra_permission(user):
            raise PermissionDenied('No tienes permiso para importar esta entidad.')
        return spec

    def _resolve_organization(self, request):
        """Regla #1: la org destino nunca viene del archivo ni se adivina."""
        user = request.user
        requested = request.query_params.get('organization') or request.data.get('organization')

        if user.role == CustomUser.Role.SUPERADMIN:
            if not requested:
                raise ValidationError({
                    'detail': "Como superadmin debes indicar la organización (parámetro 'organization').",
                })
            try:
                return Organization.objects.get(pk=int(requested))
            except (ValueError, TypeError, Organization.DoesNotExist):
                raise ValidationError({'detail': 'La organización indicada no existe.'}) from None

        if not user.organization_id:
            raise ValidationError({'detail': 'Tu usuario no tiene una organización asignada.'})
        if requested and str(requested) != str(user.organization_id):
            raise ValidationError({'detail': 'No puedes importar datos en otra organización.'})
        return user.organization

    @action(detail=False, methods=['get'])
    def entities(self, request):
        user = request.user
        visible = [
            spec for spec in all_specs()
            if not spec.extra_permission or spec.extra_permission(user)
        ]
        return Response({'entities': [_spec_payload(spec) for spec in visible]})

    @action(detail=True, methods=['get'])
    def template(self, request, entity=None):
        spec = self._get_spec(entity, request.user)
        organization = self._resolve_organization(request)
        workbook = build_template(spec, organization)
        response = HttpResponse(content_type=XLSX_CONTENT_TYPE)
        response['Content-Disposition'] = f'attachment; filename="plantilla_{spec.slug}.xlsx"'
        workbook.save(response)
        return response

    @action(detail=True, methods=['post'], parser_classes=[MultiPartParser])
    def validate(self, request, entity=None):
        spec = self._get_spec(entity, request.user)
        organization = self._resolve_organization(request)
        uploaded = request.FILES.get('file')
        try:
            report, token = run_validate(spec, organization, uploaded)
        except ImportFileError as exc:
            return Response(
                {'detail': exc.message, 'file_errors': [exc.message]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({
            'entity': spec.slug,
            'file_name': uploaded.name,
            'token': token,
            'token_expires_in_seconds': IMPORT_TOKEN_MAX_AGE,
            'summary': report.summary(),
            'can_commit': report.can_commit,
            'rows': report.rows_payload(),
        })

    @action(detail=True, methods=['post'], parser_classes=[MultiPartParser])
    def commit(self, request, entity=None):
        spec = self._get_spec(entity, request.user)
        organization = self._resolve_organization(request)
        uploaded = request.FILES.get('file')
        token = request.data.get('token')
        try:
            report, created = run_commit(spec, organization, uploaded, token, actor=request.user)
        except ImportFileError as exc:
            return Response({'detail': exc.message}, status=status.HTTP_400_BAD_REQUEST)
        except ImportCommitError as exc:
            return Response({
                'detail': 'No se importó ningún dato: corrige los errores y vuelve a intentarlo.',
                'summary': exc.report.summary(),
                'rows': exc.report.rows_payload(only_errors=True),
            }, status=status.HTTP_400_BAD_REQUEST)
        return Response({
            'entity': spec.slug,
            'created': created,
            'skipped_duplicates': report.duplicates_in_file + report.duplicates_in_db,
            'total_rows': report.total_rows,
            'summary': report.summary(),
        }, status=status.HTTP_201_CREATED)
