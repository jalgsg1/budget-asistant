# -*- coding: utf-8 -*-
"""Pruebas unitarias para las reglas R1–R4 (Requirements 18.1, 18.2, 18.3).

Las funciones de validación son puras (sin LLM, MCP ni E/S), por lo que no
requieren mocks; ninguna prueba toca dependencias externas.
"""

import unittest
from datetime import date, timedelta

from finanzas_mcp.business.validacion import (
    validar_aritmetica,
    validar_campos_obligatorios,
    validar_fecha,
    validar_moneda,
)


def _datos_validos() -> dict:
    return {
        "comercio": "Super Central",
        "fecha": "2024-01-15",
        "total": 113.0,
        "moneda": "CRC",
        "categoria": "Alimentación",
    }


class TestR1CamposObligatorios(unittest.TestCase):
    def test_conforme_todos_presentes(self):
        r = validar_campos_obligatorios(_datos_validos())
        self.assertTrue(r.is_valid)

    def test_conforme_total_cero(self):
        d = _datos_validos()
        d["total"] = 0.0
        self.assertTrue(validar_campos_obligatorios(d).is_valid)

    def test_no_conforme_campo_ausente(self):
        d = _datos_validos()
        del d["comercio"]
        r = validar_campos_obligatorios(d)
        self.assertFalse(r.is_valid)
        self.assertEqual(r.error_code, "MISSING_FIELDS")

    def test_no_conforme_campo_vacio_o_none(self):
        for campo, valor in (("moneda", "   "), ("categoria", ""), ("total", None)):
            with self.subTest(campo=campo):
                d = _datos_validos()
                d[campo] = valor
                r = validar_campos_obligatorios(d)
                self.assertFalse(r.is_valid)
                self.assertEqual(r.error_code, "MISSING_FIELDS")
                self.assertIn(campo, r.errors[0])


class TestR2Fecha(unittest.TestCase):
    def test_conforme_fecha_pasada(self):
        self.assertTrue(validar_fecha("2024-01-15").is_valid)

    def test_conforme_fecha_hoy(self):
        self.assertTrue(validar_fecha(date.today().isoformat()).is_valid)

    def test_no_conforme_formato_invalido(self):
        for f in ("15/01/2024", "2024-13-40", "ayer", ""):
            with self.subTest(fecha=f):
                r = validar_fecha(f)
                self.assertFalse(r.is_valid)
                self.assertEqual(r.error_code, "INVALID_DATE_FORMAT")

    def test_no_conforme_fecha_futura(self):
        futura = (date.today() + timedelta(days=1)).isoformat()
        r = validar_fecha(futura)
        self.assertFalse(r.is_valid)
        self.assertEqual(r.error_code, "FUTURE_DATE")


class TestR3Moneda(unittest.TestCase):
    def test_conforme_crc_y_usd(self):
        for m in ("CRC", "USD"):
            with self.subTest(moneda=m):
                self.assertTrue(validar_moneda(m).is_valid)

    def test_no_conforme_moneda_no_soportada(self):
        for m in ("EUR", "MXN", "colones"):
            with self.subTest(moneda=m):
                r = validar_moneda(m)
                self.assertFalse(r.is_valid)
                self.assertEqual(r.error_code, "INVALID_CURRENCY")

    def test_no_conforme_vacia(self):
        r = validar_moneda("")
        self.assertFalse(r.is_valid)
        self.assertEqual(r.error_code, "INVALID_CURRENCY")


class TestR4Aritmetica(unittest.TestCase):
    def test_conforme_suma_exacta(self):
        self.assertTrue(validar_aritmetica(100.0, 13.0, 113.0).is_valid)

    def test_conforme_dentro_de_tolerancia(self):
        self.assertTrue(validar_aritmetica(100.0, 13.0, 113.005).is_valid)
        self.assertTrue(validar_aritmetica(100.0, 13.0, 112.995).is_valid)

    def test_no_conforme_fuera_de_tolerancia(self):
        r = validar_aritmetica(100.0, 13.0, 120.0)
        self.assertFalse(r.is_valid)
        self.assertEqual(r.error_code, "ARITHMETIC_INCONSISTENCY")

    def test_no_conforme_justo_sobre_tolerancia(self):
        r = validar_aritmetica(100.0, 13.0, 113.05)
        self.assertFalse(r.is_valid)
        self.assertEqual(r.error_code, "ARITHMETIC_INCONSISTENCY")


if __name__ == "__main__":
    unittest.main()
