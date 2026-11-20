# -*- coding: utf-8 -*-
"""Feature: invoice-analyze-api, Property 5: Campo obligatorio faltante invalida con R1.

**Validates: Requirements 3.3**
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

from finanzas_mcp.business.categorias import CLOSED_CATEGORY_LIST
from finanzas_mcp.constantes import CAMPOS_OBLIGATORIOS
from finanzas_mcp.models import OcrResult
from tests._dobles import FakeOcr

PNG = b"\x89PNG" + b"0" * 64

_valores_base = st.fixed_dictionaries(
    {
        "comercio": st.text(min_size=1, max_size=20).filter(lambda s: s.strip()),
        "fecha": st.dates().map(lambda d: d.isoformat()),
        "total": st.floats(min_value=0.01, max_value=1_000_000, allow_nan=False, allow_infinity=False),
        "moneda": st.sampled_from(["CRC", "USD"]),
        "categoria": st.sampled_from(list(CLOSED_CATEGORY_LIST)),
    }
)


@st.composite
def _payload_con_faltante(draw):
    payload = dict(draw(_valores_base))
    obligatorios = list(CAMPOS_OBLIGATORIOS)
    faltantes = draw(
        st.lists(st.sampled_from(obligatorios), min_size=1, max_size=len(obligatorios), unique=True)
    )
    for campo in faltantes:
        if draw(st.booleans()):
            payload.pop(campo, None)
        else:
            payload[campo] = draw(st.sampled_from([None, "", "   "]))
    return payload


@pytest.fixture(scope="module")
def cliente_y_ocr(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("prop05")
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
@given(payload=_payload_con_faltante())
def test_campo_obligatorio_faltante_invalida_con_r1(cliente_y_ocr, payload):
    """Feature: invoice-analyze-api, Property 5: Campo obligatorio faltante invalida con R1"""
    cliente, ocr = cliente_y_ocr
    ocr.resultados = [OcrResult(text=json.dumps(payload), confidence=0.99)]
    ocr.llamadas.clear()

    r = cliente.post("/facturas/analizar", files={"archivo": ("f.png", PNG, "image/png")})
    assert r.status_code == 200, r.text
    cuerpo = r.json()

    assert any(c in cuerpo["campos_no_identificados"] for c in CAMPOS_OBLIGATORIOS)
    validacion = cuerpo["validacion"]
    assert validacion["valid"] is False
    r1 = [x for x in validacion["reglas"] if x["regla"] == "R1"]
    assert r1 and all(x["valid"] is False for x in r1)
