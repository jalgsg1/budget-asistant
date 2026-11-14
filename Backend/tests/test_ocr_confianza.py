"""
Pruebas de la confianza de extracción de ocr_imagen.

Property 1: Confianzas OCR acotadas y coherentes
**Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5**

Property 2: El resultado OCR es siempre no confiable y conserva las claves antiguas
**Validates: Requirements 1.6, 1.7**

Ejemplo: los diagnósticos van a stderr y no a stdout
**Validates: Requirements 1.8**

Sin red ni LLM: se usa ``calcular_confianzas`` y ``OcrClient._parse_response``
sobre un cliente creado con ``__new__`` (no inicializa ningún modelo).
"""

from __future__ import annotations

import contextlib
import io
import json
import unittest

from hypothesis import given, settings
from hypothesis import strategies as st

from ocr_mcp.ocr_client import OcrClient
from ocr_mcp.ocr_core import (
    CAMPOS_CONFIANZA,
    CAMPOS_REQUERIDOS,
    calcular_confianzas,
    wrap_untrusted,
)

# ---------------------------------------------------------------------------
# Estrategias
# ---------------------------------------------------------------------------

_VALOR_EXTRAIDO = st.one_of(
    st.text(min_size=1, max_size=20),
    st.integers(min_value=0, max_value=10**6),
    st.floats(min_value=0, max_value=1e6, allow_nan=False, allow_infinity=False),
)
_VALOR_NO_EXTRAIDO = st.sampled_from([None, ""])

_CONF_VALIDA = st.floats(min_value=0.0, max_value=1.0, allow_nan=False)
_CONF_INVALIDA = st.one_of(
    st.floats(max_value=-1e-6, allow_nan=False, allow_infinity=True),
    st.floats(min_value=1.0001, allow_nan=False, allow_infinity=True),
    st.just(float("nan")),
    st.none(),
    st.text(max_size=5),
    st.booleans(),
    st.lists(st.integers(), max_size=2),
)
_CONF_ENTRADA = st.one_of(_CONF_VALIDA, _CONF_INVALIDA)

_CONF_AUSENTE = object()


@st.composite
def _casos(draw):
    """Devuelve (datos, cruda) con campos extraídos o no y confianzas válidas, inválidas o ausentes."""
    datos: dict = {}
    cruda: dict = {}
    for campo in CAMPOS_CONFIANZA:
        if draw(st.booleans()):
            datos[campo] = draw(_VALOR_EXTRAIDO)
        else:
            datos[campo] = draw(_VALOR_NO_EXTRAIDO)
        conf = draw(st.one_of(_CONF_ENTRADA, st.just(_CONF_AUSENTE)))
        if conf is not _CONF_AUSENTE:
            cruda[campo] = conf
    return datos, cruda


def _extraido(v: object) -> bool:
    return v is not None and v != ""


def _valida(v: object) -> bool:
    return (
        not isinstance(v, bool)
        and isinstance(v, (int, float))
        and v == v
        and 0.0 <= v <= 1.0
    )


def _a_lo_sumo_2_decimales(x: float) -> bool:
    return round(x, 2) == x


def _cliente() -> OcrClient:
    return OcrClient.__new__(OcrClient)


# ---------------------------------------------------------------------------
# Property 1
# ---------------------------------------------------------------------------

class TestProperty1ConfianzasAcotadas(unittest.TestCase):
    @settings(max_examples=200, deadline=None)
    @given(_casos())
    def test_calcular_confianzas_acotadas_y_coherentes(self, caso) -> None:
        datos, cruda = caso
        global_, por_campo, bajos = calcular_confianzas(datos, cruda)

        # 1.1: global en [0,1] con <= 2 decimales
        self.assertTrue(0.0 <= global_ <= 1.0)
        self.assertTrue(_a_lo_sumo_2_decimales(global_))

        extraidos = {c for c in CAMPOS_CONFIANZA if _extraido(datos[c])}

        # 1.5: solo los campos extraídos aparecen, y los no extraídos no son "bajos"
        self.assertEqual(set(por_campo), extraidos)
        for campo in CAMPOS_CONFIANZA:
            if campo not in extraidos:
                self.assertNotIn(campo, bajos)
        self.assertTrue(set(bajos) <= extraidos)

        for campo in extraidos:
            valor = por_campo[campo]
            # 1.2: acotado y con <= 2 decimales
            self.assertTrue(0.0 <= valor <= 1.0)
            self.assertTrue(_a_lo_sumo_2_decimales(valor))
            reportada = cruda.get(campo, _CONF_AUSENTE)
            if reportada is not _CONF_AUSENTE and _valida(reportada):
                self.assertEqual(valor, round(float(reportada), 2))
            else:
                # 1.3 y 1.4: ausente o inválida -> 0.0 y listado como baja
                self.assertEqual(valor, 0.0)
                self.assertIn(campo, bajos)

        # La global es la media de los requeridos (0.0 si no extraídos)
        esperado = round(
            sum(por_campo.get(c, 0.0) for c in CAMPOS_REQUERIDOS) / len(CAMPOS_REQUERIDOS),
            2,
        )
        self.assertEqual(global_, esperado)

    @settings(max_examples=100, deadline=None)
    @given(_casos())
    def test_parse_response_expone_confianzas_acotadas(self, caso) -> None:
        datos, cruda = caso
        payload = dict(datos)
        payload["confidence"] = {k: v for k, v in cruda.items()}
        raw = json.dumps(payload)
        with contextlib.redirect_stderr(io.StringIO()):
            res = _cliente()._parse_response(raw)

        self.assertIsNotNone(res.confianza_ocr)
        self.assertTrue(0.0 <= res.confianza_ocr <= 1.0)
        self.assertTrue(_a_lo_sumo_2_decimales(res.confianza_ocr))
        for campo, valor in res.confianza_campos.items():
            self.assertIn(campo, CAMPOS_CONFIANZA)
            self.assertTrue(0.0 <= valor <= 1.0)
            self.assertTrue(_a_lo_sumo_2_decimales(valor))
        extraidos = {c for c in CAMPOS_CONFIANZA if _extraido(datos[c])}
        self.assertEqual(set(res.confianza_campos), extraidos)

    def test_ejemplos_limite(self) -> None:
        datos = {"comercio": "X", "fecha": "2024-01-01", "total": 10, "moneda": "CRC",
                 "subtotal": None, "iva": ""}
        cruda = {"comercio": 1.0, "fecha": 1.5, "total": 0.0, "moneda": 1.0}
        global_, por_campo, bajos = calcular_confianzas(datos, cruda)
        self.assertEqual(por_campo, {"comercio": 1.0, "fecha": 0.0, "total": 0.0, "moneda": 1.0})
        self.assertEqual(bajos, ["fecha", "total"])
        self.assertEqual(global_, 0.5)


# ---------------------------------------------------------------------------
# Property 2
# ---------------------------------------------------------------------------

class TestProperty2NoConfiableYClavesAntiguas(unittest.TestCase):
    @settings(max_examples=100, deadline=None)
    @given(_casos(), st.booleans())
    def test_siempre_no_confiable_y_claves_antiguas(self, caso, json_valido) -> None:
        datos, cruda = caso
        if json_valido:
            raw = json.dumps({**datos, "confidence": cruda})
        else:
            raw = "esto no es JSON {"
        with contextlib.redirect_stderr(io.StringIO()):
            res = _cliente()._parse_response(raw)

        self.assertIs(res.is_untrusted, True)
        self.assertIsInstance(res.confidence, float)
        self.assertIsInstance(res.low_confidence_fields, list)

        envuelto = json.loads(wrap_untrusted(res))
        self.assertIs(envuelto["untrusted_content"], True)
        resultado = envuelto["result"]
        self.assertIs(resultado["is_untrusted"], True)
        for clave in ("text", "confidence", "low_confidence_fields",
                      "confianza_ocr", "confianza_campos"):
            self.assertIn(clave, resultado)

    def test_wrap_untrusted_fuerza_is_untrusted(self) -> None:
        res = _cliente()._parse_response("no json")
        res.is_untrusted = False
        self.assertIs(json.loads(wrap_untrusted(res))["result"]["is_untrusted"], True)


# ---------------------------------------------------------------------------
# Requisito 1.8: diagnósticos a stderr
# ---------------------------------------------------------------------------

class TestDiagnosticosEnStderr(unittest.TestCase):
    def _capturar(self, raw: str) -> tuple[str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            _cliente()._parse_response(raw)
        return out.getvalue(), err.getvalue()

    def test_json_invalido_escribe_en_stderr_y_no_en_stdout(self) -> None:
        out, err = self._capturar("no es json")
        self.assertEqual(out, "")
        self.assertIn("[ocr_client]", err)

    def test_json_valido_escribe_en_stderr_y_no_en_stdout(self) -> None:
        raw = json.dumps({"comercio": "X", "fecha": "2024-01-01", "total": 1,
                          "moneda": "CRC", "confidence": {"comercio": 0.9}})
        out, err = self._capturar(raw)
        self.assertEqual(out, "")
        self.assertIn("[ocr_client]", err)


if __name__ == "__main__":
    unittest.main()
