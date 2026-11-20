# -*- coding: utf-8 -*-
"""Feature: invoice-analyze-api, Property 2: Categoría fuera de la lista cerrada.

**Validates: Requirements 2.4**
"""

from __future__ import annotations

import json
import unicodedata

import pytest

try:
    from fastapi.testclient import TestClient

    from api_pruebas.app import crear_app
except Exception as exc:  # noqa: BLE001
    pytest.skip(f"FastAPI no utilizable: {exc}", allow_module_level=True)

from hypothesis import given, settings
from hypothesis import strategies as st

from finanzas_mcp.business.categorias import CLOSED_CATEGORY_LIST
from finanzas_mcp.models import OcrResult
from tests._dobles import FakeOcr

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 100


def _sin_acentos(texto: str) -> str:
    d = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in d if not unicodedata.combining(c)).casefold().strip()


_EQUIV = {_sin_acentos(c): c for c in CLOSED_CATEGORY_LIST}


def _variante(nombre: str, modo: str) -> str:
    base = nombre if modo != "sin_acentos" else "".join(
        c for c in unicodedata.normalize("NFKD", nombre) if not unicodedata.combining(c)
    )
    if modo == "upper":
        return nombre.upper()
    if modo == "lower":
        return nombre.lower()
    return base


validas = st.builds(
    _variante,
    st.sampled_from(CLOSED_CATEGORY_LIST),
    st.sampled_from(["igual", "upper", "lower", "sin_acentos"]),
)
cualquiera = st.one_of(
    validas,
    st.sampled_from(CLOSED_CATEGORY_LIST).map(lambda c: c + "x"),
    st.text(max_size=20),
)


@pytest.fixture(scope="module")
def entorno(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("prop02")
    mp = pytest.MonkeyPatch()
    mp.setenv("MCP_USER_ID", "usuario_test")
    mp.setenv("DB_PATH", str(tmp / "test.db"))
    mp.setenv("INVOICES_DIR", str(tmp / "facturas"))
    mp.setenv("TRACES_DIR", str(tmp / "traces"))
    actual = {"ocr": FakeOcr()}
    app = crear_app(extractor_ocr=lambda ruta: actual["ocr"](ruta))
    with TestClient(app) as cliente:
        yield cliente, actual
    mp.undo()


# Feature: invoice-analyze-api, Property 2: Categoría fuera de la lista cerrada
@settings(max_examples=100, deadline=None)
@given(categoria=cualquiera)
def test_categoria_fuera_de_lista_cerrada(entorno, categoria):
    cliente, actual = entorno
    payload = {"comercio": "Tienda", "fecha": "2024-01-15", "total": 100.0,
               "moneda": "CRC", "categoria": categoria}
    actual["ocr"] = FakeOcr(OcrResult(text=json.dumps(payload), confidence=0.95))
    r = cliente.post("/facturas/analizar", files={"archivo": ("f.png", PNG, "image/png")})
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    oficial = _EQUIV.get(_sin_acentos(categoria)) if categoria.strip() else None
    if oficial is not None:
        assert cuerpo["campos"].get("categoria") == oficial
        assert "categoria" not in cuerpo["campos_no_identificados"]
    else:
        assert "categoria" not in cuerpo["campos"]
        assert "categoria" in cuerpo["campos_no_identificados"]
