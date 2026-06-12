"""Resolución de FK por texto (nombre/email) SIEMPRE dentro de la organización.

Regla de multitenancy: nunca se resuelve un objeto de otra organización; un
texto que no matchea (o matchea más de uno) es un error de fila, jamás un
fallback global.
"""
from django.apps import apps


class FKResolutionError(Exception):
    def __init__(self, message):
        self.message = message
        super().__init__(message)


def _base_queryset(fk, organization):
    model = apps.get_model(fk.model)
    qs = model.objects.all()
    if fk.filters:
        qs = qs.filter(**fk.filters)
    if fk.org_field:
        qs = qs.filter(**{fk.org_field: organization})
    return qs


def resolve_fk(fk, raw_value, organization, extra_filters=None):
    """Devuelve la instancia que matchea ``raw_value`` (iexact + trim) en la org.

    ``extra_filters`` viene de los disambiguators del spec (otras columnas de
    la misma fila, ej. tipo de plan) y reduce el conjunto antes de decidir.
    """
    value = str(raw_value).strip()
    label = fk.reference_label or 'valor'
    queryset = _base_queryset(fk, organization).filter(
        **{f'{fk.lookup_field}__iexact': value}
    )
    if extra_filters:
        queryset = queryset.filter(**extra_filters)
    matches = list(queryset[:2])
    if not matches:
        raise FKResolutionError(
            f"No se encontró {label} '{value}' en tu organización. "
            'Revisa la hoja "Referencias" de la plantilla.'
        )
    if len(matches) > 1:
        hint = f' {fk.ambiguity_hint}' if fk.ambiguity_hint else ' Usa un nombre que identifique uno solo.'
        raise FKResolutionError(
            f"Hay más de un {label} llamado '{value}'.{hint}"
        )
    return matches[0]


def reference_values(fk, organization):
    """Valores válidos de la org para la hoja Referencias y los dropdowns."""
    return list(
        _base_queryset(fk, organization)
        .order_by(fk.lookup_field)
        .values_list(fk.lookup_field, flat=True)
    )
