# -*- coding: utf-8 -*-
"""Pruebas unitarias R9 (filtros), R10 (aislamiento) y R11 (límites) + Tracer.

Requirements: 18.1, 18.2, 18.3. Sin red; SQLite en memoria.
"""

import contextlib
import io
import json
import os
import sqlite3
import tempfile
import unittest

from agent.agent import (StepCounter, StepLimitError, TokenCounter,
                         TokenLimitError)
from agent.tracer import Trace, TraceEntry, write_trace
from finanzas_mcp.business.transacciones import (DateRangeError, FilterError,
                                                 listar_transacciones)
from finanzas_mcp.db.repository import TransactionRepository
from finanzas_mcp.models import Transaction

PERMITIDOS = ["comercio", "fecha_desde", "fecha_hasta", "categoria", "moneda"]


class _MemRepo(TransactionRepository):
    def __init__(self):
        self._db_path = ":memory:"
        self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()


def _tx(user, comercio="Super X", fecha="2024-01-10"):
    return Transaction(user_id=user, comercio=comercio, fecha=fecha, total=100.0,
                       moneda="CRC", categoria="Alimentación")


class R9FiltrosTests(unittest.TestCase):
    def setUp(self):
        self.repo = _MemRepo()
        self.repo.insert(_tx("u1"))

    def test_filtro_permitido_conforme(self):
        r = listar_transacciones(self.repo, {"comercio": "Super X"}, "u1", PERMITIDOS, 90)
        self.assertEqual(len(r), 1)

    def test_filtro_no_permitido_rechazado(self):
        with self.assertRaises(FilterError) as cm:
            listar_transacciones(self.repo, {"user_id": "u2"}, "u1", PERMITIDOS, 90)
        self.assertEqual(cm.exception.error_code, "INVALID_FILTER")

    def test_rango_dentro_del_maximo_conforme(self):
        f = {"fecha_desde": "2024-01-01", "fecha_hasta": "2024-02-01"}
        self.assertEqual(len(listar_transacciones(self.repo, f, "u1", PERMITIDOS, 90)), 1)

    def test_rango_excedido_rechazado(self):
        f = {"fecha_desde": "2024-01-01", "fecha_hasta": "2024-12-31"}
        with self.assertRaises(DateRangeError):
            listar_transacciones(self.repo, f, "u1", PERMITIDOS, 90)


class R10AislamientoTests(unittest.TestCase):
    def setUp(self):
        self.repo = _MemRepo()
        self.repo.insert(_tx("u1"))
        self.repo.insert(_tx("u2", comercio="Otro"))

    def test_usuario_ve_solo_lo_suyo_conforme(self):
        r = listar_transacciones(self.repo, {}, "u1", PERMITIDOS, 90)
        self.assertEqual({t.user_id for t in r}, {"u1"})

    def test_no_se_expone_data_de_otro_usuario(self):
        r = listar_transacciones(self.repo, {"comercio": "Otro"}, "u1", PERMITIDOS, 90)
        self.assertEqual(r, [])

    def test_buscar_duplicados_aislado(self):
        self.assertEqual(self.repo.find_duplicates("Otro", "2024-01-10", 100.0, "u1"), [])
        self.assertEqual(len(self.repo.find_duplicates("Otro", "2024-01-10", 100.0, "u2")), 1)


class R11LimitesTests(unittest.TestCase):
    def test_pasos_dentro_del_limite(self):
        c = StepCounter(8)
        for _ in range(8):
            c.increment()
        self.assertEqual(c.count, 8)

    def test_paso_excedido_lanza(self):
        c = StepCounter(8)
        for _ in range(8):
            c.increment()
        with self.assertRaises(StepLimitError):
            c.increment()

    def test_tokens_bajo_limite(self):
        c = TokenCounter(100)
        self.assertEqual(c.add(99), 99)

    def test_tokens_en_limite_lanza(self):
        c = TokenCounter(100)
        with self.assertRaises(TokenLimitError):
            c.add(100)


class TracerTests(unittest.TestCase):
    def _trace(self):
        return Trace(trace_id="abcdef1234567890", user_id="u1", image_path="x.jpg",
                     entries=[TraceEntry(1, "ocr_imagen", "in", "out", "ocr_imagen",
                                         "2024-01-10T10:00:00")],
                     final_status="step_limit", termination_reason="step_limit",
                     created_at="2024-01-10T10:00:00.123")

    def test_escribe_json_correcto(self):
        with tempfile.TemporaryDirectory() as d:
            sub = os.path.join(d, "traces")
            write_trace(self._trace(), sub)
            files = os.listdir(sub)
            self.assertEqual(len(files), 1)
            self.assertTrue(files[0].endswith("_abcdef12.json"))
            with open(os.path.join(sub, files[0]), encoding="utf-8") as fh:
                data = json.load(fh)
            self.assertEqual(data["final_status"], "step_limit")
            self.assertEqual(data["entries"][0]["tool_called"], "ocr_imagen")

    def test_error_de_escritura_va_a_stderr_sin_lanzar(self):
        with tempfile.TemporaryDirectory() as d:
            bloqueo = os.path.join(d, "archivo")
            with open(bloqueo, "w") as fh:
                fh.write("x")
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                write_trace(self._trace(), os.path.join(bloqueo, "sub"))
            self.assertIn("[tracer] ERROR", err.getvalue())


if __name__ == "__main__":
    unittest.main()
