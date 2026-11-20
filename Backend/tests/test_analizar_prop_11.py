# -*- coding: utf-8 -*-
"""Feature: invoice-analyze-api, Property 11: Análisis sin efectos secundarios.

**Validates: Requirements 6.1, 6.2, 6.3**
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

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

_texto = st.text(min_size=1, max_size=20)

_payload = st.fixed_dictionaries(
    {},
    optional={
        "comercio": _texto,
        "fecha": st.dates().map(lambda d: d.isoformat()),
        "total": st.floats(min_value=0.01, max_value=1e6, allow_nan=False),
        "moneda": st.sampled_from(["CRC", "USD", "EUR"]),
        "categoria": st.sampled_from(["alimentacion", "transporte", "otra", "invalida"]),
    },
)

_ocr_texto = st.one_of(
    _payload.map(json.dumps),
    st.just("no es json"),
    st.just("{}"),
)


def _filas(db: Path) -> int:
    if not db.exists():
        return 0
    con = sqlite3.connect(str(db))
    try:
        try:
            return con.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        except sqlite3.OperationalError:
            return 0
    finally:
        con.close()


def _contenido(directorio: Path) -> dict[str, bytes | None]:
    if not directorio.exists():
        return {}
    return {
        str(p.relative_to(directorio)): (p.read_bytes() if p.is_file() else None)
        for p in sorted(directorio.rglob("*"))
    }


@pytest.fixture(scope="module")
def entorno(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("prop11")
    mp = pytest.MonkeyPatch()
    rutas = {
        "db": tmp / "test.db",
        "traces": tmp / "traces",
        "batch": tmp / "batch_traces",
    }
    mp.setenv("MCP_USER_ID", "usuario_test")
    mp.setenv("DB_PATH", str(rutas["db"]))
    mp.setenv("INVOICES_DIR", str(tmp / "facturas"))
    mp.setenv("TRACES_DIR", str(rutas["traces"]))
    mp.setenv("BATCH_TRACES_DIR", str(rutas["batch"]))
    ocr = FakeOcr(OcrResult(text="{}", confidence=0.99))
    app = crear_app(extractor_ocr=lambda ruta: ocr(ruta))
    with TestClient(app) as c:
        yield c, ocr, rutas
    mp.undo()


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    texto=_ocr_texto,
    confianza=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    n=st.integers(min_value=1, max_value=4),
)
def test_analisis_sin_efectos_secundarios(entorno, texto, confianza, n):
    """Feature: invoice-analyze-api, Property 11: Análisis sin efectos secundarios"""
    cliente, ocr, rutas = entorno
    ocr.resultados = [OcrResult(text=texto, confidence=confianza)]

    filas_antes = _filas(rutas["db"])
    traces_antes = _contenido(rutas["traces"])
    batch_antes = _contenido(rutas["batch"])

    respuestas = []
    for _ in range(n):
        r = cliente.post(
            "/facturas/analizar",
            files={"archivo": ("f.png", PNG, "image/png")},
        )
        assert r.status_code == 200, r.text
        respuestas.append(r.json())

    assert _filas(rutas["db"]) == filas_antes
    assert _contenido(rutas["traces"]) == traces_antes
    assert _contenido(rutas["batch"]) == batch_antes
    assert all(resp == respuestas[0] for resp in respuestas)
