# -*- coding: utf-8 -*-
"""Feature: invoice-analyze-api, Property 3: Forma de la respuesta de análisis.

Para cualquier archivo válido, inválido o con OCR fallido, la respuesta es HTTP 200
con exactamente las claves ``campos``, ``campos_no_identificados``, ``validacion``
y ``advertencias``; ``validacion`` tiene ``valid`` y ``reglas`` y cada regla tiene
``regla``, ``valid``, ``code`` y ``message``; ``advertencias`` es lista de cadenas.

**Validates: Requirements 1.3, 3.1, 4.1**
"""

from __future__ import annotations

import json

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

try:  # FastAPI/Starlette incompatibles en algunos intérpretes: se omite el módulo.
    from fastapi.testclient import TestClient

    from api_pruebas.app import crear_app
except Exception as exc:  # noqa: BLE001
    pytest.skip(f"FastAPI no utilizable: {exc}", allow_module_level=True)

from finanzas_mcp.models import OcrResult
from tests._dobles import FakeOcr

CLAVES_RESPUESTA = {"campos", "campos_no_identificados", "validacion", "advertencias"}
CLAVES_REGLA = {"regla", "valid", "code", "message"}

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
JPG = b"\xff\xd8\xff\xe0" + b"0" * 64

_valor = st.one_of(
    st.none(),
    st.text(max_size=20),
    st.integers(min_value=-10**6, max_value=10**6),
    st.floats(allow_nan=False, allow_infinity=False, width=32),
)
_payload = st.dictionaries(
    st.sampled_from(
        ["comercio", "fecha", "total", "moneda", "categoria", "subtotal", "iva", "descripcion", "otro"]
    ),
    _valor,
    max_size=9,
)

_resultado_ocr = st.one_of(
    # OCR exitoso con JSON de objeto.
    st.builds(
        lambda p, c: OcrResult(text=json.dumps(p), confidence=c),
        _payload,
        st.floats(min_value=0.0, max_value=1.0),
    ),
    # JSON ilegible o que no es objeto.
    st.builds(lambda t: OcrResult(text=t, confidence=0.9), st.text(max_size=30)),
    st.just(OcrResult(text="[1, 2]", confidence=0.9)),
    # Excepción del extractor.
    st.sampled_from([RuntimeError("boom"), ValueError("x"), OSError("disco")]),
)

_archivo = st.one_of(
    st.just(("factura.png", PNG)),
    st.just(("factura.jpg", JPG)),
    st.just(("factura.exe", b"MZ" + b"0" * 10)),  # extensión no permitida
    st.just(("factura.png", b"no-es-png")),  # firma incorrecta
    st.just(("factura.png", PNG + b"0" * 5000)),  # excede max_upload_bytes
)


@pytest.fixture(scope="module")
def cliente_y_ocr(tmp_path_factory):
    base = tmp_path_factory.mktemp("prop03")
    mp = pytest.MonkeyPatch()
    mp.setenv("MCP_USER_ID", "usuario_test")
    mp.setenv("DB_PATH", str(base / "test.db"))
    mp.setenv("INVOICES_DIR", str(base / "facturas"))
    mp.setenv("TRACES_DIR", str(base / "traces"))
    mp.setenv("MAX_IMAGE_BYTES", "1000")
    actual: dict = {"ocr": FakeOcr()}
    app = crear_app(extractor_ocr=lambda ruta: actual["ocr"](ruta))
    with TestClient(app) as c:
        yield c, actual
    mp.undo()


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(archivo=_archivo, resultado=_resultado_ocr)
def test_forma_de_la_respuesta(cliente_y_ocr, archivo, resultado):
    """Feature: invoice-analyze-api, Property 3: Forma de la respuesta de análisis."""
    cliente, actual = cliente_y_ocr
    actual["ocr"] = FakeOcr([resultado])
    nombre, contenido = archivo

    r = cliente.post("/facturas/analizar", files={"archivo": (nombre, contenido)})

    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert set(cuerpo) == CLAVES_RESPUESTA
    assert isinstance(cuerpo["campos"], dict)
    assert isinstance(cuerpo["campos_no_identificados"], list)
    validacion = cuerpo["validacion"]
    assert set(validacion) == {"valid", "reglas"}
    assert isinstance(validacion["valid"], bool)
    assert isinstance(validacion["reglas"], list)
    for regla in validacion["reglas"]:
        assert set(regla) == CLAVES_REGLA
    assert isinstance(cuerpo["advertencias"], list)
    assert all(isinstance(a, str) for a in cuerpo["advertencias"])
