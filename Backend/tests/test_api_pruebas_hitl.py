# -*- coding: utf-8 -*-
"""Integración de ``api_pruebas`` con la decisión HITL (spec evaluacion-experimental-paper, tarea 12.4).

Sin red: el OCR se simula con ``FakeOcr`` y las herramientas del Pipeline son
las locales (no se define ``FINANZAS_MCP_URL`` ni ``OCR_MCP_URL``).

**Validates: Requirements 3.1, 8.1, 18.3, 18.4, 18.5, 18.6**
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

try:  # FastAPI/Starlette incompatibles en algunos intérpretes: se omite el módulo.
    from fastapi.testclient import TestClient

    from api_pruebas.app import crear_app
except Exception as exc:  # noqa: BLE001
    pytest.skip(f"FastAPI no utilizable: {exc}", allow_module_level=True)

from api_pruebas.esquemas import BatchRespuesta, PipelineRespuesta
from finanzas_mcp.models import OcrResult

JPG = b"\xff\xd8\xff\xe0" + b"0" * 100
BACKEND = Path(__file__).resolve().parent.parent
CAMPOS_PIPELINE = {"status", "termination_reason", "transaction_id", "trace_id", "mensajes", "prompts"}
CAMPOS_REPORTE = {"batch_id", "subcarpeta", "fecha", "total", "conteos", "imagenes"}
CAMPOS_IMAGEN = {
    "archivo", "clasificacion", "motivo", "detalle", "status", "termination_reason",
    "trace_id", "transaction_id", "reglas_incumplidas", "duplicada_de",
}


def _ocr_factura(total: float) -> OcrResult:
    datos = {"comercio": "Super X", "fecha": "2024-01-10", "total": total,
             "moneda": "CRC", "categoria": "Alimentación"}
    return OcrResult(text=json.dumps(datos, ensure_ascii=False), confidence=0.99, confianza_ocr=0.99)


@pytest.fixture()
def cliente(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_USER_ID", "usuario_test")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("INVOICES_DIR", str(tmp_path / "facturas"))
    monkeypatch.setenv("TRACES_DIR", str(tmp_path / "traces"))
    monkeypatch.delenv("BATCH_TRACES_DIR", raising=False)
    monkeypatch.delenv("FINANZAS_MCP_URL", raising=False)
    monkeypatch.delenv("OCR_MCP_URL", raising=False)
    lote = tmp_path / "facturas" / "lote"
    lote.mkdir(parents=True)
    for i, nombre in enumerate(("a.jpg", "b.jpg", "c.jpg"), start=1):
        (lote / nombre).write_bytes(JPG)
    (tmp_path / "facturas" / "uno.jpg").write_bytes(JPG)

    contador = {"n": 0}

    def extractor(_ruta: str) -> OcrResult:
        contador["n"] += 1
        return _ocr_factura(100.0 * contador["n"])  # totales distintos: sin duplicados

    app = crear_app(extractor_ocr=extractor)
    with TestClient(app) as c:
        yield c


def _decisiones(traza: dict) -> list[dict]:
    return [e for e in traza["entries"] if e["action"] == "decision_hitl"]


def test_politica_en_modo_siempre():
    politica = json.loads((BACKEND / "politica.json").read_text(encoding="utf-8"))
    assert politica["modo_hitl"] == "siempre"


def test_pipeline_run_traza_contiene_decision_hitl(cliente):
    r = cliente.post("/pipeline/run", json={"ruta": "uno.jpg", "respuestas": ["tok"]})
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert set(cuerpo) == CAMPOS_PIPELINE == set(PipelineRespuesta.model_fields)
    assert cuerpo["status"] == "success"
    assert any("token de confirmación para registrar" in p for p in cuerpo["prompts"])

    t = cliente.get(f"/trazas/{cuerpo['trace_id']}")
    assert t.status_code == 200, t.text
    traza = t.json()
    assert len(_decisiones(traza)) == 1
    assert traza["decision_hitl"]["hitl_solicitado"] is True


def test_batch_run_cada_traza_contiene_decision_hitl(cliente):
    r = cliente.post("/batch/run", json={"subcarpeta": "lote", "respuestas_por_defecto": ["tok"]})
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert set(cuerpo) == set(BatchRespuesta.model_fields) == {"batch_id", "reporte"}
    reporte = cuerpo["reporte"]
    assert set(reporte) == CAMPOS_REPORTE
    assert reporte["total"] == 3 and len(reporte["imagenes"]) == 3

    for imagen in reporte["imagenes"]:
        assert set(imagen) == CAMPOS_IMAGEN
        assert imagen["clasificacion"] == "ok", imagen
        t = cliente.get(f"/trazas/{imagen['trace_id']}")
        assert t.status_code == 200, t.text
        assert len(_decisiones(t.json())) == 1


def test_esquemas_openapi_sin_campos_hitl_nuevos(cliente):
    esquemas = cliente.app.openapi()["components"]["schemas"]
    assert set(esquemas["PipelineRespuesta"]["properties"]) == CAMPOS_PIPELINE
    assert set(esquemas["ReporteBatch"]["properties"]) == CAMPOS_REPORTE
    assert set(esquemas["ImagenResultado"]["properties"]) == CAMPOS_IMAGEN
