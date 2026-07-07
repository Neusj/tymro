"""Utilidad de RUT chileno: Módulo 11 (dígito verificador) + normalización canónica.

Canónico = sin puntos, con guion, K mayúscula (ej. 26711486-2). Vive en
accounts/rut.py porque el RUT es un atributo del usuario (accounts.CustomUser).

DVs usados aquí calculados a mano con Módulo 11:
  12345678 -> 5, 26711486 -> 2 (invariante), 11111111 -> 1, 20347878 -> K.
"""
import pytest

from accounts.rut import clean_rut, compute_dv, is_valid_rut


class TestComputeDv:
    @pytest.mark.parametrize('body,dv', [
        ('12345678', '5'),
        ('26711486', '2'),
        ('11111111', '1'),
        ('20347878', 'K'),
    ])
    def test_modulo_11(self, body, dv):
        assert compute_dv(body) == dv


class TestCleanRut:
    def test_strips_dots_keeps_hyphen(self):
        assert clean_rut('12.345.678-5') == '12345678-5'

    def test_adds_hyphen_when_missing(self):
        assert clean_rut('123456785') == '12345678-5'

    def test_uppercases_k(self):
        assert clean_rut('20.347.878-k') == '20347878-K'

    def test_trims_surrounding_spaces(self):
        assert clean_rut('  12345678-5  ') == '12345678-5'

    def test_canonical_is_idempotent(self):
        canonical = clean_rut('12.345.678-5')
        assert clean_rut(canonical) == canonical == '12345678-5'

    @pytest.mark.parametrize('bad', [
        '12345678-9',   # dígito verificador incorrecto (real es 5)
        '12345678-0',
        '20347878-2',   # el DV real es K
        'not-a-rut',
        '',
        '   ',
        '1-2-3',        # más de un guion
        'K',            # sin cuerpo
        '1234567a-5',   # letra en el cuerpo
    ])
    def test_invalid_raises_valueerror(self, bad):
        with pytest.raises(ValueError):
            clean_rut(bad)

    def test_none_raises_valueerror(self):
        with pytest.raises(ValueError):
            clean_rut(None)


class TestIsValidRut:
    @pytest.mark.parametrize('value', [
        '12.345.678-5',
        '12345678-5',
        '123456785',
        '20347878-K',
        '20.347.878-k',
        '26711486-2',
    ])
    def test_valid(self, value):
        assert is_valid_rut(value) is True

    @pytest.mark.parametrize('value', [
        '12345678-9',
        'not-a-rut',
        '',
        None,
    ])
    def test_invalid(self, value):
        assert is_valid_rut(value) is False
