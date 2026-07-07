"""RUT chileno: dígito verificador (Módulo 11) + normalización canónica.

Fuente única de verdad para validar/normalizar el RUT del usuario. El frontend
tiene un espejo en ``frontend/src/utils/rut.js`` (mantener ambos en sync).

Canónico almacenado: sin puntos, con guion, K mayúscula (ej. ``26711486-2``).
El login NO usa el RUT: sigue siendo por email.
"""

_FACTORS = (2, 3, 4, 5, 6, 7)


def compute_dv(body: str) -> str:
    """Dígito verificador (Módulo 11) del cuerpo numérico. Devuelve '0'-'9' o 'K'.

    ``body`` debe ser solo dígitos; ValueError si no.
    """
    if not body or not body.isdigit():
        raise ValueError('El cuerpo del RUT debe ser numérico.')
    total = sum(int(digit) * _FACTORS[i % 6] for i, digit in enumerate(reversed(body)))
    remainder = 11 - (total % 11)
    if remainder == 11:
        return '0'
    if remainder == 10:
        return 'K'
    return str(remainder)


def clean_rut(value) -> str:
    """Normaliza a canónico (``NNNNNNNN-D``) y valida el dígito verificador.

    Quita puntos y espacios, pasa K a mayúscula y agrega el guion si falta.
    Lanza ``ValueError`` si el RUT es vacío, malformado o el DV no cuadra.
    """
    if value is None:
        raise ValueError('RUT vacío.')

    normalized = str(value).strip().upper().replace('.', '').replace(' ', '')
    if not normalized:
        raise ValueError('RUT vacío.')

    if '-' in normalized:
        parts = normalized.split('-')
        if len(parts) != 2:
            raise ValueError('RUT malformado.')
        body, dv = parts
    else:
        body, dv = normalized[:-1], normalized[-1]

    if not body or not body.isdigit():
        raise ValueError('El cuerpo del RUT debe ser numérico.')
    if dv not in '0123456789K':
        raise ValueError('Dígito verificador inválido.')

    if compute_dv(body) != dv:
        raise ValueError('El dígito verificador no corresponde al RUT.')

    return f'{body}-{dv}'


def is_valid_rut(value) -> bool:
    """True si ``value`` es un RUT válido (formato + Módulo 11). Nunca lanza."""
    try:
        clean_rut(value)
    except (ValueError, TypeError):
        return False
    return True
