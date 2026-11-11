# -*- coding: utf-8 -*-
"""Regresión de POST /ocr con subida de .jpg desde Swagger UI.

Antes, ``ruta`` y ``archivo`` eran ``Optional`` y el OpenAPI los publicaba como
``anyOf [string, null]``. Swagger UI no soporta ese esquema en multipart: rellenaba
``ruta`` con "string" y la enviaba junto al archivo, y la API respondía 422.
"""

from __future__ import annotations

import pytest

try:  # FastAPI/Starlette incompatibles en algunos intérpretes: se omite el módulo.
    from fastapi.testclient import TestClient

    from api_pruebas.app import crear_app
except Exception as exc:  # noqa: BLE001
    pytest.skip(f"FastAPI no utilizable: {exc}", allow_module_level=True)

from finanzas_mcp.models import OcrResult

JPG = b"\xff\xd8\xff\xe0" + b"0" * 100


@pytest.fixture()
def cliente(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_USER_ID", "usuario_test")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("INVOICES_DIR", str(tmp_path / "facturas"))
    monkeypatch.setenv("TRACES_DIR", str(tmp_path / "traces"))
    app = crear_app(extractor_ocr=lambda ruta: OcrResult(text="Factura", confidence=0.9))
    with TestClient(app) as c:
        yield c


def _form_schema(cliente):
    s = cliente.app.openapi()
    ref = s["paths"]["/ocr"]["post"]["requestBody"]["content"]["multipart/form-data"]["schema"]["$ref"]
    return s["components"]["schemas"][ref.split("/")[-1]]["properties"]


def test_esquema_sin_anyof_para_swagger(cliente):
    props = _form_schema(cliente)
    assert "anyOf" not in props["ruta"] and props["ruta"]["type"] == "string"
    assert "anyOf" not in props["archivo"] and props["archivo"]["type"] == "string"


def test_subida_jpg_ok(cliente):
    r = cliente.post("/ocr", files={"archivo": ("factura.jpg", JPG, "image/jpeg")})
    assert r.status_code == 200, r.text
    assert r.json()["is_untrusted"] is True


def test_subida_jpg_con_ruta_vacia_ok(cliente):
    # Lo que envía Swagger UI cuando el campo ruta queda vacío.
    r = cliente.post("/ocr", data={"ruta": ""}, files={"archivo": ("factura.jpg", JPG, "image/jpeg")})
    assert r.status_code == 200, r.text


def test_ruta_y_archivo_siguen_siendo_excluyentes(cliente):
    r = cliente.post("/ocr", data={"ruta": "a.jpg"}, files={"archivo": ("factura.jpg", JPG, "image/jpeg")})
    assert r.status_code == 422
    assert r.json()["code"] == "VALIDATION_ERROR"


def test_sin_ruta_ni_archivo_422(cliente):
    r = cliente.post("/ocr", data={})
    assert r.status_code == 422
