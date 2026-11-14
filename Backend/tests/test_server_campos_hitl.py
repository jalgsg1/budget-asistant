# -*- coding: utf-8 -*-
"""Exposición de confianza_ocr / contenido_sospechoso en el servidor MCP (tarea 7.2).

Requisitos: 6.7, 6.9, 18.2, 18.3, 18.4.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import os
import tempfile
import unittest
from datetime import date, timedelta

from tests._sin_red import SinRedTestCase

_TMP = tempfile.mkdtemp()
os.environ.setdefault("DB_PATH", os.path.join(_TMP, "server_hitl.db"))

from mcp import types  # noqa: E402

from finanzas_mcp import server  # noqa: E402
from finanzas_mcp.db.repository import TransactionRepository  # noqa: E402


def _politica(modo: str) -> dict:
    return {
        "high_amount_threshold": {"CRC": 50000, "USD": 100},
        "modo_hitl": modo,
        "umbral_confianza_ocr": 0.75,
        "max_date_range_days": 90,
        "allowed_filters": ["comercio", "fecha_desde", "fecha_hasta", "categoria", "moneda"],
    }


def _args(**extra) -> dict:
    base = {
        "comercio": "Super Test",
        "fecha": (date.today() - timedelta(days=1)).isoformat(),
        "total": 10.0,
        "moneda": "USD",
        "categoria": "Alimentación",
        "confirmation_token": "auto:abc",
    }
    base.update(extra)
    return base


class ServidorCamposHitlTests(SinRedTestCase):
    def setUp(self) -> None:
        # El loop de asyncio en Windows abre un socketpair interno; se crea
        # antes de activar el bloqueo de red.
        self._loop = asyncio.new_event_loop()
        self.addCleanup(self._loop.close)
        super().setUp()
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self._repo_orig, self._pol_orig = server._repo, server._policy
        server._repo = TransactionRepository(os.path.join(self._dir.name, "t.db"))
        self.addCleanup(self._restaurar)

    def _restaurar(self) -> None:
        server._repo.close()
        server._repo, server._policy = self._repo_orig, self._pol_orig

    def _llamar(self, args: dict) -> tuple[types.CallToolResult, str]:
        handler = server.server.request_handlers[types.CallToolRequest]
        req = types.CallToolRequest(
            method="tools/call",
            params=types.CallToolRequestParams(name="registrar_transaccion", arguments=args),
        )
        salida = io.StringIO()
        with contextlib.redirect_stdout(salida):
            resultado = self._loop.run_until_complete(handler(req))
        return resultado.root, salida.getvalue()

    def test_schema_expone_campos_opcionales(self) -> None:
        handler = server.server.request_handlers[types.ListToolsRequest]
        tools = self._loop.run_until_complete(handler(types.ListToolsRequest(method="tools/list"))).root.tools
        tool = next(t for t in tools if t.name == "registrar_transaccion")
        props = tool.inputSchema["properties"]
        self.assertEqual(props["confianza_ocr"]["type"], "number")
        self.assertEqual(props["contenido_sospechoso"]["type"], "boolean")
        self.assertNotIn("confianza_ocr", tool.inputSchema["required"])
        self.assertNotIn("contenido_sospechoso", tool.inputSchema["required"])
        self.assertNotIn("modo_hitl", props)
        self.assertIn("confianza_ocr", tool.description)

    def test_politica_por_defecto_incluye_hitl(self) -> None:
        pol = server._load_policy(os.path.join(self._dir.name, "no_existe.json"))
        self.assertEqual(pol["modo_hitl"], "siempre")
        self.assertEqual(pol["umbral_confianza_ocr"], 0.75)

    def test_auto_en_modo_siempre_es_iserror(self) -> None:
        server._policy = _politica("siempre")
        res, stdout = self._llamar(_args(confianza_ocr=0.99, contenido_sospechoso=False))
        self.assertTrue(res.isError)
        self.assertIn("AUTOMATIC_TOKEN_NOT_ALLOWED", res.content[0].text)
        self.assertEqual(stdout, "")

    def test_modo_hitl_del_payload_se_ignora(self) -> None:
        server._policy = _politica("siempre")
        res, _ = self._llamar(
            _args(confianza_ocr=0.99, contenido_sospechoso=False,
                  modo_hitl="adaptativo", umbral_confianza_ocr=0.0)
        )
        self.assertTrue(res.isError)
        self.assertIn("AUTOMATIC_TOKEN_NOT_ALLOWED", res.content[0].text)

    def test_adaptativo_sin_campos_es_iserror_humano(self) -> None:
        server._policy = _politica("adaptativo")
        res, stdout = self._llamar(_args())
        self.assertTrue(res.isError)
        self.assertIn("HUMAN_CONFIRMATION_REQUIRED", res.content[0].text)
        self.assertEqual(stdout, "")

    def test_adaptativo_limpio_registra(self) -> None:
        server._policy = _politica("adaptativo")
        res, stdout = self._llamar(_args(confianza_ocr=0.9, contenido_sospechoso=False))
        self.assertFalse(res.isError)
        self.assertEqual(json.loads(res.content[0].text)["status"], "registrada")
        self.assertEqual(stdout, "")


if __name__ == "__main__":
    unittest.main()
