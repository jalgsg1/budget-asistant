# -*- coding: utf-8 -*-
"""Feature: invoice-analyze-api, Property 9: Respuesta de fallo uniforme.

**Validates: Requirements 4.4, 4.5**
"""

from __future__ import annotations

import pytest

try:
    from fastapi.testclient import TestClient

    from api_pruebas.app import crear_app
except Exception as exc:  # noqa: BLE001
    pytest.skip(f"FastAPI no utilizable: {exc}", allow_module_level=True)

from hypothesis import HealthCheck, given, settings, strategies as st

from api_pruebas.servicios import CAMPOS_FACTURA
from finanzas_mcp.models import OcrResult
from tests._dobles import FakeOcr

MAX_BYTES = 512
PNG = b"\x89PNG" + b"0" * 64

_mensaje = st.text(max_size=40)


class _ErrorPersonalizado(Exception):
    pass


_excepciones = st.tuples(
    st.sampled_from([RuntimeError, ValueError, OSError, KeyError, TypeError, _ErrorPersonalizado]),
    _mensaje,
).map(lambda t: t[0](t[1]))

_json_ilegible = st.one_of(
    st.just(""),
    st.just("{"),
    st.just("no es json"),
    st.just("[1, 2]"),
    st.just("null"),
    st.just("42"),
    st.text(max_size=30).filter(lambda s: not s.strip().startswith(("{", "[", '"')) and s.strip() not in {"null", "true", "false"}),
)

_nombre = st.text(alphabet="abcdefg", min_size=1, max_size=6)


@st.composite
def _fallos(draw):
    """Devuelve (nombre, contenido, ocr_resultados) de un caso de fallo."""
    tipo = draw(st.sampled_from(["excepcion", "json", "extension", "firma", "tamano"]))
    base = PNG
    if tipo == "excepcion":
        return "f.png", base, [draw(_excepciones)]
    if tipo == "json":
        return "f.png", base, [OcrResult(text=draw(_json_ilegible), confidence=0.99)]
    if tipo == "extension":
        ext = draw(st.sampled_from([".exe", ".txt", ".gif", ".bmp", ".zip", ""]))
        return draw(_nombre) + ext, base, [OcrResult(text="{}", confidence=0.99)]
    if tipo == "firma":
        ext, firma_ajena = draw(
            st.sampled_from(
                [(".png", b"%PDF"), (".pdf", b"\x89PNG"), (".jpg", b"\x89PNG"), (".jpeg", b"%PDF"), (".png", b"xxxx")]
            )
        )
        return draw(_nombre) + ext, firma_ajena + b"0" * 32, [OcrResult(text="{}", confidence=0.99)]
    relleno = draw(st.integers(min_value=1, max_value=200))
    return "f.png", PNG + b"0" * (MAX_BYTES + relleno), [OcrResult(text="{}", confidence=0.99)]


@pytest.fixture(scope="module")
def cliente_y_ocr(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("prop09")
    mp = pytest.MonkeyPatch()
    mp.setenv("MCP_USER_ID", "usuario_test")
    mp.setenv("DB_PATH", str(tmp / "test.db"))
    mp.setenv("INVOICES_DIR", str(tmp / "facturas"))
    mp.setenv("TRACES_DIR", str(tmp / "traces"))
    mp.setenv("MAX_IMAGE_BYTES", str(MAX_BYTES))
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
@given(caso=_fallos())
def test_respuesta_de_fallo_uniforme(cliente_y_ocr, caso):
    """Feature: invoice-analyze-api, Property 9: Respuesta de fallo uniforme"""
    cliente, ocr = cliente_y_ocr
    nombre, contenido, resultados = caso
    ocr.resultados = resultados
    ocr.llamadas.clear()

    r = cliente.post("/facturas/analizar", files={"archivo": (nombre, contenido, "application/octet-stream")})

    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["campos"] == {}
    assert set(cuerpo["campos_no_identificados"]) == set(CAMPOS_FACTURA)
    assert len(cuerpo["campos_no_identificados"]) == len(CAMPOS_FACTURA) == 8
    assert len(cuerpo["advertencias"]) >= 1
    assert all(isinstance(a, str) and a.strip() for a in cuerpo["advertencias"])
