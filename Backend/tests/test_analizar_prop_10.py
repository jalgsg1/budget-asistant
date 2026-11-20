# -*- coding: utf-8 -*-
"""Feature: invoice-analyze-api, Property 10: Sin archivos temporales residuales.

**Validates: Requirements 5.2**
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest

try:
    from fastapi.testclient import TestClient

    from api_pruebas.app import crear_app
except Exception as exc:  # noqa: BLE001
    pytest.skip(f"FastAPI no utilizable: {exc}", allow_module_level=True)

from hypothesis import HealthCheck, given, settings, strategies as st

from finanzas_mcp.models import OcrResult
from tests._dobles import FakeOcr

MAX_BYTES = 512
PNG = b"\x89PNG" + b"0" * 64
PDF = b"%PDF" + b"0" * 64

_JSON_OK = json.dumps({"merchant": "Tienda", "total": 10.5, "currency": "CRC"})


@st.composite
def _casos(draw):
    """Devuelve (nombre, contenido, ocr_resultados) de un caso exitoso o fallido."""
    tipo = draw(
        st.sampled_from(["exito_png", "exito_pdf", "excepcion", "json", "extension", "firma", "tamano"])
    )
    if tipo == "exito_png":
        return "f.png", PNG, [OcrResult(text=_JSON_OK, confidence=0.99)]
    if tipo == "exito_pdf":
        return "f.pdf", PDF, [OcrResult(text=_JSON_OK, confidence=0.99)]
    if tipo == "excepcion":
        exc = draw(st.sampled_from([RuntimeError, ValueError, OSError, KeyError, TypeError]))
        return "f.png", PNG, [exc(draw(st.text(max_size=20)))]
    if tipo == "json":
        texto = draw(st.sampled_from(["", "{", "no es json", "[1, 2]", "null", "42"]))
        return "f.png", PNG, [OcrResult(text=texto, confidence=0.99)]
    if tipo == "extension":
        ext = draw(st.sampled_from([".exe", ".txt", ".gif", ".zip", ""]))
        return "f" + ext, PNG, [OcrResult(text="{}", confidence=0.99)]
    if tipo == "firma":
        return "f.png", b"%PDF" + b"0" * 32, [OcrResult(text="{}", confidence=0.99)]
    relleno = draw(st.integers(min_value=1, max_value=200))
    return "f.png", PNG + b"0" * (MAX_BYTES + relleno), [OcrResult(text="{}", confidence=0.99)]


@pytest.fixture(scope="module")
def entorno(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("prop10")
    temp_dir = tmp / "temporal"
    temp_dir.mkdir()
    invoices = tmp / "facturas"
    mp = pytest.MonkeyPatch()
    mp.setenv("MCP_USER_ID", "usuario_test")
    mp.setenv("DB_PATH", str(tmp / "test.db"))
    mp.setenv("INVOICES_DIR", str(invoices))
    mp.setenv("TRACES_DIR", str(tmp / "traces"))
    mp.setenv("MAX_IMAGE_BYTES", str(MAX_BYTES))
    mp.setattr(tempfile, "tempdir", str(temp_dir))
    ocr = FakeOcr(OcrResult(text="{}", confidence=0.99))
    app = crear_app(extractor_ocr=lambda ruta: ocr(ruta))
    with TestClient(app) as c:
        yield c, ocr, temp_dir, invoices
    mp.undo()


def _listar(directorio):
    if not directorio.exists():
        return set()
    return {os.path.join(r, n) for r, _, ns in os.walk(directorio) for n in ns}


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(caso=_casos())
def test_sin_archivos_temporales_residuales(entorno, caso):
    """Feature: invoice-analyze-api, Property 10: Sin archivos temporales residuales"""
    cliente, ocr, temp_dir, invoices = entorno
    nombre, contenido, resultados = caso
    ocr.resultados = resultados
    ocr.llamadas.clear()
    antes_temp = _listar(temp_dir)
    antes_inv = _listar(invoices)

    r = cliente.post("/facturas/analizar", files={"archivo": (nombre, contenido, "application/octet-stream")})

    assert r.status_code == 200, r.text
    assert _listar(temp_dir) == antes_temp
    assert _listar(invoices) == antes_inv
    for args, _ in ocr.llamadas:
        assert not os.path.exists(args[0])
