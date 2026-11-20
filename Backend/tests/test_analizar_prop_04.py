# -*- coding: utf-8 -*-
"""Feature: invoice-analyze-api, Property 4: La validación refleja a evaluar_factura.

**Validates: Requirements 3.2**
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
from finanzas_mcp.business.factura import evaluar_factura
from finanzas_mcp.constantes import CAMPOS_OBLIGATORIOS
from finanzas_mcp.models import OcrResult
from tests._dobles import FakeOcr

PNG = b"\x89PNG" + b"0" * 64

_texto = st.one_of(st.none(), st.just(""), st.just("   "), st.text(min_size=1, max_size=20))
_fecha = st.one_of(
    st.none(),
    st.dates().map(lambda d: d.isoformat()),
    st.just("31/12/2024"),
    st.just("no-es-fecha"),
    st.just(""),
)
_numero = st.one_of(
    st.none(),
    st.floats(min_value=-1000, max_value=1_000_000, allow_nan=False, allow_infinity=False),
    st.just(0),
)
_moneda = st.one_of(st.none(), st.sampled_from(["CRC", "USD", "crc", "EUR", "XXX", ""]))
_categoria = st.one_of(
    st.none(),
    st.sampled_from(list(CLOSED_CATEGORY_LIST)),
    st.sampled_from(list(CLOSED_CATEGORY_LIST)).map(str.upper),
    st.text(max_size=12),
)

_payload = st.fixed_dictionaries(
    {},
    optional={
        "comercio": _texto,
        "fecha": _fecha,
        "total": _numero,
        "moneda": _moneda,
        "categoria": _categoria,
        "subtotal": _numero,
        "iva": _numero,
        "descripcion": _texto,
    },
)


@pytest.fixture(scope="module")
def cliente_y_ocr(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("prop04")
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
@given(payload=_payload)
def test_validacion_refleja_evaluar_factura(cliente_y_ocr, payload):
    """Feature: invoice-analyze-api, Property 4: La validación refleja a evaluar_factura"""
    cliente, ocr = cliente_y_ocr
    ocr.resultados = [OcrResult(text=json.dumps(payload), confidence=0.99)]
    ocr.llamadas.clear()

    r = cliente.post("/facturas/analizar", files={"archivo": ("f.png", PNG, "image/png")})
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    campos = cuerpo["campos"]
    faltan_obligatorios = any(c in cuerpo["campos_no_identificados"] for c in CAMPOS_OBLIGATORIOS)

    esperado = evaluar_factura(dict(campos))
    fallidas = {(x.regla, x.code) for x in esperado.reglas}

    validacion = cuerpo["validacion"]
    assert validacion["valid"] is not (bool(fallidas) or faltan_obligatorios)
    obtenidas = {(x["regla"], x["code"]) for x in validacion["reglas"]}
    assert fallidas <= obtenidas
