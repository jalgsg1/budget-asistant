# -*- coding: utf-8 -*-
"""
Pruebas unitarias para las reglas R5–R8 (duplicados, categoría, monto alto,
token de confirmación) y para la revalidación de `registrar_transaccion`
con datos que se saltaron `validar_factura`.

Requirements: 18.1, 18.2, 18.3
"""

from __future__ import annotations

import sqlite3
import unittest

from finanzas_mcp.business.categorias import CLOSED_CATEGORY_LIST
from finanzas_mcp.business.duplicados import buscar_duplicados
from finanzas_mcp.business.transacciones import (
    ValidationError,
    registrar_transaccion,
)
from finanzas_mcp.business.validacion import (
    validar_categoria,
    validar_monto_alto,
    validar_token_confirmacion,
)
from finanzas_mcp.db.repository import TransactionRepository
from finanzas_mcp.models import Transaction


class _InMemoryRepo(TransactionRepository):
    """Repositorio SQLite en memoria para aislamiento total."""

    def __init__(self) -> None:
        self._db_path = ":memory:"
        self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._init_schema()


POLICY = {"high_amount_threshold": {"CRC": 500000, "USD": 1000}}


def _datos(**over):
    base = {
        "comercio": "Super X",
        "fecha": "2024-01-15",
        "total": 113.0,
        "moneda": "USD",
        "categoria": CLOSED_CATEGORY_LIST[0],
        "subtotal": 100.0,
        "iva": 13.0,
    }
    base.update(over)
    return base


class TestR5Duplicados(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = _InMemoryRepo()

    def tearDown(self) -> None:
        self.repo.close()

    def _insert(self, user_id="u1", total=50.0):
        self.repo.insert(Transaction(
            user_id=user_id, comercio="Tienda", fecha="2024-02-01",
            total=total, moneda="USD", categoria=CLOSED_CATEGORY_LIST[0],
        ))

    def test_conforme_sin_duplicados(self) -> None:
        self.assertEqual(
            buscar_duplicados(self.repo, "Tienda", "2024-02-01", 50.0, "u1"), []
        )

    def test_no_conforme_con_duplicado(self) -> None:
        self._insert()
        res = buscar_duplicados(self.repo, "Tienda", "2024-02-01", 50.0, "u1")
        self.assertEqual(len(res), 1)

    def test_duplicado_de_otro_usuario_no_cuenta(self) -> None:
        self._insert(user_id="u2")
        self.assertEqual(
            buscar_duplicados(self.repo, "Tienda", "2024-02-01", 50.0, "u1"), []
        )

    def test_limite_maximo_10(self) -> None:
        for _ in range(15):
            self._insert()
        res = buscar_duplicados(self.repo, "Tienda", "2024-02-01", 50.0, "u1", limit=100)
        self.assertEqual(len(res), 10)


class TestR6Categoria(unittest.TestCase):
    def test_conforme(self) -> None:
        for cat in CLOSED_CATEGORY_LIST:
            self.assertTrue(validar_categoria(cat).is_valid)

    def test_no_conforme(self) -> None:
        r = validar_categoria("CategoriaInventada")
        self.assertFalse(r.is_valid)
        self.assertEqual(r.error_code, "INVALID_CATEGORY")

    def test_vacia(self) -> None:
        self.assertEqual(validar_categoria("").error_code, "INVALID_CATEGORY")


class TestR7MontoAlto(unittest.TestCase):
    def test_conforme_bajo_umbral_sin_token(self) -> None:
        self.assertTrue(validar_monto_alto(100.0, 1000.0, None).is_valid)

    def test_conforme_igual_umbral_sin_token(self) -> None:
        self.assertTrue(validar_monto_alto(1000.0, 1000.0, None).is_valid)

    def test_conforme_sobre_umbral_con_token(self) -> None:
        self.assertTrue(validar_monto_alto(1500.0, 1000.0, "tok").is_valid)

    def test_no_conforme_sobre_umbral_sin_token(self) -> None:
        r = validar_monto_alto(1500.0, 1000.0, None)
        self.assertFalse(r.is_valid)
        self.assertEqual(r.error_code, "HIGH_AMOUNT_CONFIRMATION_REQUIRED")

    def test_no_conforme_token_en_blanco(self) -> None:
        self.assertFalse(validar_monto_alto(1500.0, 1000.0, "   ").is_valid)


class TestR8Token(unittest.TestCase):
    def test_conforme(self) -> None:
        self.assertTrue(validar_token_confirmacion("abc").is_valid)

    def test_no_conforme_none_vacio_blanco(self) -> None:
        for t in (None, "", "   "):
            r = validar_token_confirmacion(t)
            self.assertFalse(r.is_valid)
            self.assertEqual(r.error_code, "MISSING_CONFIRMATION_TOKEN")


class TestRevalidacionRegistrar(unittest.TestCase):
    """Datos que se saltaron validar_factura deben ser rechazados al registrar."""

    def setUp(self) -> None:
        self.repo = _InMemoryRepo()

    def tearDown(self) -> None:
        self.repo.close()

    def _count(self) -> int:
        return len(self.repo.query(filters={}, user_id="u1"))

    def test_conforme_se_persiste(self) -> None:
        tx_id = registrar_transaccion(self.repo, _datos(), "tok", None, POLICY, "u1")
        self.assertIsInstance(tx_id, int)
        self.assertEqual(self._count(), 1)

    def test_categoria_invalida_rechazada(self) -> None:
        with self.assertRaises(ValidationError) as cm:
            registrar_transaccion(
                self.repo, _datos(categoria="Inventada"), "tok", None, POLICY, "u1"
            )
        self.assertEqual(cm.exception.result.error_code, "INVALID_CATEGORY")
        self.assertEqual(self._count(), 0)

    def test_monto_alto_sin_token_rechazado(self) -> None:
        with self.assertRaises(ValidationError) as cm:
            registrar_transaccion(
                self.repo,
                _datos(total=5000.0, subtotal=4424.78, iva=575.22),
                "tok", None, POLICY, "u1",
            )
        self.assertEqual(
            cm.exception.result.error_code, "HIGH_AMOUNT_CONFIRMATION_REQUIRED"
        )
        self.assertEqual(self._count(), 0)

    def test_monto_alto_con_token_aceptado(self) -> None:
        registrar_transaccion(
            self.repo,
            _datos(total=5000.0, subtotal=4424.78, iva=575.22),
            "tok", "tok-alto", POLICY, "u1",
        )
        self.assertEqual(self._count(), 1)

    def test_sin_token_confirmacion_rechazado(self) -> None:
        for t in (None, ""):
            with self.assertRaises(ValidationError) as cm:
                registrar_transaccion(self.repo, _datos(), t, None, POLICY, "u1")
            self.assertEqual(
                cm.exception.result.error_code, "MISSING_CONFIRMATION_TOKEN"
            )
        self.assertEqual(self._count(), 0)

    def test_user_id_del_payload_ignorado(self) -> None:
        registrar_transaccion(
            self.repo, _datos(user_id="atacante"), "tok", None, POLICY, "u1"
        )
        self.assertEqual(self._count(), 1)
        self.assertEqual(self.repo.query(filters={}, user_id="atacante"), [])


if __name__ == "__main__":
    unittest.main()
