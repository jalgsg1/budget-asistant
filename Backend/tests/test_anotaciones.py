# -*- coding: utf-8 -*-
"""Propiedad 18 de eval/anotaciones.py: kappa de Cohen y acuerdo porcentual (Req. 12.6, 12.11)."""
import unittest
from collections import Counter

from hypothesis import given, settings, strategies as st

from eval.anotaciones import acuerdo_porcentual, kappa_cohen

SETTINGS = settings(max_examples=100, deadline=None)

ETIQUETAS = st.sampled_from(["comida", "transporte", "salud", "hogar", "ocio"])


@st.composite
def pares(draw, min_size=0):
    n = draw(st.integers(min_value=min_size, max_value=40))
    a = draw(st.lists(ETIQUETAS, min_size=n, max_size=n))
    b = draw(st.lists(ETIQUETAS, min_size=n, max_size=n))
    return a, b


def _pe_es_uno(a, b):
    n = len(a)
    ca, cb = Counter(a), Counter(b)
    return sum(ca[k] * cb[k] for k in set(ca) | set(cb)) == n * n


def _decimales(x, max_dec):
    return round(x, max_dec) == x


class TestPropiedad18KappaYAcuerdo(unittest.TestCase):
    """**Validates: Requirements 12.6, 12.11**"""

    @SETTINGS
    @given(pares())
    def test_acuerdo_rango_simetria_y_decimales(self, par):
        a, b = par
        r = acuerdo_porcentual(a, b)
        if not a:
            self.assertIsNone(r)
            return
        self.assertGreaterEqual(r, 0.0)
        self.assertLessEqual(r, 100.0)
        self.assertEqual(r, acuerdo_porcentual(b, a))
        self.assertTrue(_decimales(r, 2))

    @SETTINGS
    @given(st.lists(ETIQUETAS, min_size=1, max_size=40))
    def test_acuerdo_listas_iguales_es_100(self, a):
        self.assertEqual(acuerdo_porcentual(a, list(a)), 100.0)

    @SETTINGS
    @given(pares())
    def test_kappa_rango_simetria_e_indefinicion(self, par):
        a, b = par
        k = kappa_cohen(a, b)
        if not a or _pe_es_uno(a, b):
            self.assertIsNone(k)
            return
        self.assertIsNotNone(k)
        self.assertGreaterEqual(k, -1.0)
        self.assertLessEqual(k, 1.0)
        self.assertEqual(k, kappa_cohen(b, a))
        self.assertTrue(_decimales(k, 4))

    @SETTINGS
    @given(st.lists(ETIQUETAS, min_size=1, max_size=40))
    def test_kappa_listas_identicas(self, a):
        k = kappa_cohen(a, list(a))
        if _pe_es_uno(a, a):
            self.assertIsNone(k)
        else:
            self.assertEqual(k, 1.0)

    def test_casos_borde(self):
        self.assertIsNone(kappa_cohen([], []))
        self.assertIsNone(acuerdo_porcentual([], []))
        self.assertIsNone(kappa_cohen(["x", "x"], ["x", "x"]))
        self.assertEqual(kappa_cohen(["a", "b"], ["a", "b"]), 1.0)
        self.assertEqual(kappa_cohen(["a", "b"], ["b", "a"]), -1.0)
        with self.assertRaises(ValueError):
            kappa_cohen(["a"], [])
        with self.assertRaises(ValueError):
            acuerdo_porcentual(["a"], [])


if __name__ == "__main__":
    unittest.main()
