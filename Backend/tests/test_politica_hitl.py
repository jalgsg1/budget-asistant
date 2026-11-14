# -*- coding: utf-8 -*-
"""Property 3: Validación de parámetros HITL de la política.

**Validates: Requirements 2.1, 2.2, 2.3, 2.5, 2.6, 2.8, 3.4**
Ejemplos y política del repositorio: Requirements 2.4, 19.6.
"""

import json
import math
import unittest
from pathlib import Path

from hypothesis import given, settings, strategies as st

from finanzas_mcp.business.hitl import (
    MODOS_HITL,
    PoliticaHitlError,
    resolver_parametros_hitl,
)

POLITICA_PATH = Path(__file__).resolve().parent.parent / "politica.json"

# Valores JSON arbitrarios (None, bool, int, float, str, listas, objetos).
_json_scalar = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(),
    st.floats(allow_nan=True, allow_infinity=True),
    st.text(),
)
_json_values = st.recursive(
    _json_scalar,
    lambda c: st.one_of(st.lists(c, max_size=3), st.dictionaries(st.text(), c, max_size=3)),
    max_leaves=5,
)


def _umbral_valido(v) -> bool:
    return (
        not isinstance(v, bool)
        and isinstance(v, (int, float))
        and math.isfinite(v)
        and 0.0 <= v <= 1.0
    )


class TestPropiedadModoHitl(unittest.TestCase):
    @settings(max_examples=100)
    @given(valor=_json_values)
    def test_modo_aceptado_sii_valor_permitido(self, valor):
        raw = {"modo_hitl": valor, "umbral_confianza_ocr": 0.5}
        if isinstance(valor, str) and valor in MODOS_HITL:
            self.assertEqual(resolver_parametros_hitl(raw).modo_hitl, valor)
        else:
            with self.assertRaises(PoliticaHitlError) as cm:
                resolver_parametros_hitl(raw)
            msg = str(cm.exception)
            self.assertIn("modo_hitl", msg)
            self.assertIn("siempre", msg)
            self.assertIn("adaptativo", msg)

    def test_modo_ausente_usa_siempre(self):
        self.assertEqual(
            resolver_parametros_hitl({"umbral_confianza_ocr": 0.5}).modo_hitl, "siempre"
        )


class TestPropiedadUmbralOcr(unittest.TestCase):
    @settings(max_examples=100)
    @given(valor=st.one_of(_json_values, st.floats(min_value=-2, max_value=3)))
    def test_umbral_aceptado_sii_numero_finito_en_rango(self, valor):
        raw = {"modo_hitl": "siempre", "umbral_confianza_ocr": valor}
        if _umbral_valido(valor):
            self.assertEqual(
                resolver_parametros_hitl(raw).umbral_confianza_ocr, float(valor)
            )
        else:
            with self.assertRaises(PoliticaHitlError) as cm:
                resolver_parametros_hitl(raw)
            msg = str(cm.exception)
            self.assertIn("umbral_confianza_ocr", msg)
            self.assertIn("0.0", msg)
            self.assertIn("1.0", msg)

    def test_umbral_ausente_se_rechaza(self):
        with self.assertRaises(PoliticaHitlError) as cm:
            resolver_parametros_hitl({"modo_hitl": "siempre"})
        self.assertIn("umbral_confianza_ocr", str(cm.exception))


class TestEjemplosLimites(unittest.TestCase):
    def test_limites_validos(self):
        for v in (0.0, 1.0):
            r = resolver_parametros_hitl({"umbral_confianza_ocr": v})
            self.assertEqual(r.umbral_confianza_ocr, v)

    def test_fuera_de_rango_rechazado(self):
        for v in (-0.01, 1.01):
            with self.assertRaises(PoliticaHitlError):
                resolver_parametros_hitl({"umbral_confianza_ocr": v})

    def test_no_numericos_rechazados(self):
        for v in (True, False, "0.5", None, float("nan"), float("inf")):
            with self.assertRaises(PoliticaHitlError):
                resolver_parametros_hitl({"umbral_confianza_ocr": v})

    def test_modo_invalido_rechazado(self):
        for v in ("Siempre", "", "nunca", None, 1):
            with self.assertRaises(PoliticaHitlError):
                resolver_parametros_hitl({"modo_hitl": v, "umbral_confianza_ocr": 0.5})


class TestPoliticaDelRepositorio(unittest.TestCase):
    def test_politica_json_tiene_modo_siempre(self):
        raw = json.loads(POLITICA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(raw["modo_hitl"], "siempre")
        params = resolver_parametros_hitl(raw)
        self.assertEqual(params.modo_hitl, "siempre")


if __name__ == "__main__":
    unittest.main()
