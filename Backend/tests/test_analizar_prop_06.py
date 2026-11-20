# -*- coding: utf-8 -*-
"""Feature: invoice-analyze-api, Property 6: Redacción de secretos.

**Validates: Requirements 3.4, 4.4, 4.5**
"""

from __future__ import annotations

import json

import pytest

try:
    from fastapi.testclient import TestClient

    from api_pruebas.app import crear_app
except Exception as exc:  # noqa: BLE001
    pytest.skip(f"FastAPI no utilizable: {exc}", allow_module_level=True)

from hypothesis import HealthCheck, given, settings, strategies as st

from finanzas_mcp.models import OcrResult
from tests._dobles import FakeOcr

PNG = b"\x89PNG" + b"0" * 64

_secreto = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=8, max_size=30).map(
    lambda s: "sk-" + s
)
_prefijo = st.text(alphabet="abc XYZ", max_size=5)
_nombre_var = st.sampled_from(["OPENAI_API_KEY", "ANTHROPIC_API_KEY"])
# Dónde aparece el secreto: campo del OCR, mensaje de excepción o texto ilegible.
_modo = st.sampled_from(["comercio", "descripcion", "fecha", "excepcion", "ilegible", "obligatorio_vacio"])


@pytest.fixture(scope="module")
def cliente_y_ocr(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("prop06")
    mp = pytest.MonkeyPatch()
    mp.setenv("MCP_USER_ID", "usuario_test")
    mp.setenv("DB_PATH", str(tmp / "test.db"))
    mp.setenv("INVOICES_DIR", str(tmp / "facturas"))
    mp.setenv("TRACES_DIR", str(tmp / "traces"))
    ocr = FakeOcr(OcrResult(text="{}", confidence=0.99))
    app = crear_app(extractor_ocr=lambda ruta: ocr(ruta))
    with TestClient(app) as c:
        yield c, ocr
    mp.undo()


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(secreto=_secreto, var=_nombre_var, modo=_modo, prefijo=_prefijo, confianza=st.floats(0.0, 1.0))
def test_respuesta_no_contiene_secretos(cliente_y_ocr, monkeypatch, secreto, var, modo, prefijo, confianza):
    """Feature: invoice-analyze-api, Property 6: Redacción de secretos"""
    cliente, ocr = cliente_y_ocr
    monkeypatch.setenv(var, secreto)
    texto = f"{prefijo}{secreto}"

    payload = {
        "comercio": "Tienda",
        "fecha": "2024-05-01",
        "total": 100.0,
        "moneda": "CRC",
        "categoria": "Alimentación",
    }
    if modo == "excepcion":
        resultado = RuntimeError(f"fallo con clave {texto}")
    elif modo == "ilegible":
        resultado = OcrResult(text=f"no-json {texto}", confidence=confianza)
    else:
        if modo == "obligatorio_vacio":
            payload["comercio"] = ""
            payload["descripcion"] = texto
        else:
            payload[modo] = texto
        resultado = OcrResult(text=json.dumps(payload), confidence=confianza)
    ocr.resultados = [resultado]
    ocr.llamadas.clear()

    r = cliente.post("/facturas/analizar", files={"archivo": ("f.png", PNG, "image/png")})
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert secreto not in json.dumps(cuerpo["validacion"], ensure_ascii=False)
    assert secreto not in json.dumps(cuerpo["advertencias"], ensure_ascii=False)


@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(secreto=_secreto, var=_nombre_var, nombre=st.sampled_from(["f.exe", "f.txt", "f"]))
def test_error_de_archivo_no_contiene_secretos(cliente_y_ocr, monkeypatch, secreto, var, nombre):
    """Feature: invoice-analyze-api, Property 6: Redacción de secretos (archivo inválido)"""
    cliente, _ = cliente_y_ocr
    monkeypatch.setenv(var, secreto)
    r = cliente.post(
        "/facturas/analizar",
        files={"archivo": (f"{secreto}_{nombre}", PNG, "application/octet-stream")},
    )
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert secreto not in json.dumps(cuerpo["validacion"], ensure_ascii=False)
    assert secreto not in json.dumps(cuerpo["advertencias"], ensure_ascii=False)
