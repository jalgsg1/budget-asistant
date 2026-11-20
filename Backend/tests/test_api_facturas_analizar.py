# -*- coding: utf-8 -*-
"""Pruebas de ejemplo de ``POST /facturas/analizar`` y del retiro de ``POST /validar``.

Validates: Requirements 1.1, 1.4, 5.1, 7.1, 7.2, 7.4, 7.5
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

try:
    from fastapi.testclient import TestClient

    from api_pruebas.app import crear_app
except Exception as exc:  # noqa: BLE001
    pytest.skip(f"FastAPI no utilizable: {exc}", allow_module_level=True)

from finanzas_mcp.models import OcrResult
from tests._dobles import FakeOcr

BACKEND = Path(__file__).resolve().parents[1]
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
CLAVES = {"campos", "campos_no_identificados", "validacion", "advertencias"}


@pytest.fixture()
def cliente(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_USER_ID", "usuario_test")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("INVOICES_DIR", str(tmp_path / "facturas"))
    monkeypatch.setenv("TRACES_DIR", str(tmp_path / "traces"))
    payload = {"comercio": "Auto Mercado", "total": 15200.0, "moneda": "CRC"}
    ocr = FakeOcr(OcrResult(text=json.dumps(payload), confidence=0.95))
    app = crear_app(extractor_ocr=lambda ruta: ocr(ruta))
    with TestClient(app) as c:
        yield c


def test_png_minimo_devuelve_200_con_cuatro_claves(cliente):
    r = cliente.post("/facturas/analizar", files={"archivo": ("f.png", PNG)})
    assert r.status_code == 200, r.text
    assert set(r.json()) == CLAVES


def test_sin_archivo_devuelve_422_validation_error(cliente):
    r = cliente.post("/facturas/analizar")
    assert r.status_code == 422
    assert r.json()["code"] == "VALIDATION_ERROR"


def test_openapi_contiene_analizar_y_no_validar(cliente):
    spec = cliente.get("/openapi.json").json()
    assert "/facturas/analizar" in spec["paths"]
    assert "AnalisisFacturaRespuesta" in json.dumps(spec["paths"]["/facturas/analizar"])
    assert "/validar" not in spec["paths"]


def test_post_validar_devuelve_404_estandar(cliente):
    r = cliente.post("/validar", json={})
    assert r.status_code == 404
    cuerpo = r.json()
    assert "code" in cuerpo and "message" in cuerpo


def test_rutas_existentes_siguen_registradas(cliente):
    rutas = set(cliente.get("/openapi.json").json()["paths"])
    for prefijo in ("/ocr", "/transacciones", "/pipeline", "/batch", "/trazas"):
        assert any(p.startswith(prefijo) for p in rutas), prefijo


def test_no_existen_factura_py_ni_facturain():
    assert not (BACKEND / "api_pruebas" / "rutas" / "factura.py").exists()
    for py in (BACKEND / "api_pruebas").rglob("*.py"):
        assert "FacturaIn" not in py.read_text(encoding="utf-8"), py
