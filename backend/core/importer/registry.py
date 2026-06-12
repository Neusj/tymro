"""Registro central de entidades importables (slug -> EntityImportSpec)."""


class UnknownEntityError(Exception):
    pass


_REGISTRY = {}


def register(spec):
    if spec.slug in _REGISTRY:
        raise ValueError(f'Spec duplicado para la entidad "{spec.slug}"')
    for field in spec.fields:
        if field.kind == 'fk' and (field.fk is None or not field.fk.org_field):
            raise ValueError(
                f'FK sin scoping de organización en "{spec.slug}.{field.attr}": '
                'toda FK debe declarar org_field (multitenancy regla #1)'
            )
        if field.attr == spec.org_field:
            raise ValueError(
                f'El spec "{spec.slug}" declara la columna "{field.attr}": la organización '
                'nunca se importa del archivo (multitenancy regla #1)'
            )
    declared = {}
    for field in spec.fields:
        if field.kind == 'fk' and field.fk:
            for dis_attr, _ in (field.fk.disambiguators or ()):
                if dis_attr not in declared:
                    raise ValueError(
                        f'Disambiguator "{dis_attr}" de "{spec.slug}.{field.attr}" debe ser '
                        'una columna declarada ANTES que la FK que lo usa'
                    )
                if declared[dis_attr] == 'fk':
                    raise ValueError(
                        f'Disambiguator "{dis_attr}" de "{spec.slug}.{field.attr}" no puede '
                        'ser otra FK'
                    )
        declared[field.attr] = field.kind
    for attr in spec.natural_key:
        if attr not in declared:
            raise ValueError(
                f'La clave natural de "{spec.slug}" usa "{attr}", que no es una columna '
                'declarada (no puede depender de valores de derive)'
            )
    if '__' in spec.org_field and spec.build_instance is None:
        raise ValueError(
            f'El spec "{spec.slug}" usa org_field con ruta ("{spec.org_field}") y por lo '
            'tanto requiere build_instance (el motor no puede fijar la organización directa)'
        )
    _REGISTRY[spec.slug] = spec
    return spec


def get_spec(slug):
    try:
        return _REGISTRY[slug]
    except KeyError:
        raise UnknownEntityError(slug) from None


def all_specs():
    return list(_REGISTRY.values())
