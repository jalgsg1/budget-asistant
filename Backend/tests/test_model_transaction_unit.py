"""Pruebas unitarias de model.Transaction (Requisitos 8.1, 8.2, 8.3, 8.4)."""

from __future__ import annotations

import dataclasses
import sqlite3
import subprocess
import sys
import unittest
from pathlib import Path

RAIZ: Path = Path(__file__).resolve().parent.parent
SCHEMA: Path = RAIZ / "finanzas_mcp" / "db" / "schema.sql"

if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from model import Transaction  # noqa: E402

# Requisito 8.3: opcionales (el resto es obligatorio).
OPCIONALES: frozenset[str] = frozenset(
    {"id", "subtotal", "iva", "descripcion", "created_at"}
)


def _columnas_db() -> list[tuple[str, int]]:
    """Devuelve (nombre, notnull) según PRAGMA table_info(transactions)."""
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(SCHEMA.read_text(encoding="utf-8"))
        return [(f[1], f[3]) for f in conn.execute("PRAGMA table_info(transactions)")]
    finally:
        conn.close()


class TestModelTransaction(unittest.TestCase):
    def test_paquete_model_importable(self) -> None:
        """8.1"""
        self.assertTrue((RAIZ / "model" / "__init__.py").is_file())

    def test_campos_coinciden_con_pragma(self) -> None:
        """8.2"""
        db = [n for n, _ in _columnas_db()]
        campos = [f.name for f in dataclasses.fields(Transaction)]
        self.assertEqual(sorted(campos), sorted(db))

    def test_opcionalidad_segun_8_3(self) -> None:
        """8.3"""
        for f in dataclasses.fields(Transaction):
            tiene_default = (
                f.default is not dataclasses.MISSING
                or f.default_factory is not dataclasses.MISSING
            )
            self.assertEqual(tiene_default, f.name in OPCIONALES, f.name)

    def test_obligatorios_son_not_null_en_db(self) -> None:
        """8.3: coherencia con la nulabilidad de la tabla."""
        notnull = {n: nn for n, nn in _columnas_db()}
        for nombre in set(notnull) - OPCIONALES:
            self.assertEqual(notnull[nombre], 1, nombre)
        for nombre in ("subtotal", "iva", "descripcion"):
            self.assertEqual(notnull[nombre], 0, nombre)

    def test_import_sin_mcp_ni_finanzas_mcp(self) -> None:
        """8.4"""
        codigo = (
            "import sys, model, model.transaction; "
            "bad = [m for m in sys.modules if m.split('.')[0] in ('mcp','finanzas_mcp')]; "
            "sys.exit(1 if bad else 0)"
        )
        r = subprocess.run(
            [sys.executable, "-c", codigo],
            cwd=RAIZ, capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_estructura_repositorio_no_falla_con_model(self) -> None:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "tests/test_estructura_repositorio.py"],
            cwd=RAIZ, capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
