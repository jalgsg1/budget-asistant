# -*- coding: utf-8 -*-
"""Feature: invoice-analyze-api, Property 7: Advertencia de baja confianza.

**Validates: Requirements 4.2**
"""

from __future__ import annotations

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
MARCA = "Confianza OCR baja"

_unidad = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)


@pytest.fixture(scope="module")
def cliente_y_ocr(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("prop07")
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
@given(confianza=_unidad, umbral=_unidad)
def test_advertencia_baja_confianza_iff_menor_que_umbral(cliente_y_ocr, confianza, umbral):
    """Feature: invoice-analyze-api, Property 7: Advertencia de baja confianza"""
    cliente, ocr = cliente_y_ocr
    ocr.resultados = [OcrResult(text="{}", confidence=confianza)]
    ocr.llamadas.clear()

    policy = cliente.app.state.config.policy
    original = policy.umbral_confianza_ocr
    policy.umbral_confianza_ocr = umbral
    try:
        r = cliente.post("/facturas/analizar", files={"archivo": ("f.png", PNG, "image/png")})
    finally:
        policy.umbral_confianza_ocr = original

    assert r.status_code == 200, r.text
    hay_aviso = any(MARCA in a for a in r.json()["advertencias"])
    assert hay_aviso is (confianza < umbral)
