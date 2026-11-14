"""BD SQLite temporal y aislada para los baselines (Req. 11.1 a 11.4).

Solo lee como texto ``finanzas_mcp/db/schema.sql``; no importa código de negocio
ni toca la base definida por ``DB_PATH``.
"""
from __future__ import annotations

import shutil
import sqlite3
import tempfile
from pathlib import Path

RUTA_SCHEMA = Path(__file__).resolve().parent.parent / "finanzas_mcp" / "db" / "schema.sql"


class BDTemporalError(Exception):
    """No se pudo crear la BD temporal."""


class BDTemporal:
    """Crea una BD SQLite nueva en un directorio temporal propio."""

    def __init__(self, conservar: bool = False) -> None:
        self.conservar = conservar
        self.ruta: str = ""
        self._dir: str | None = None

    def _limpiar(self) -> None:
        if self._dir and not self.conservar:
            shutil.rmtree(self._dir, ignore_errors=True)

    def __enter__(self) -> "BDTemporal":
        try:
            esquema = RUTA_SCHEMA.read_text(encoding="utf-8")
            self._dir = tempfile.mkdtemp(prefix="bd_temporal_")
            ruta = str(Path(self._dir) / "baseline.db")
            conn = sqlite3.connect(ruta)
            try:
                conn.executescript(esquema)
                conn.commit()
            finally:
                conn.close()
            self.ruta = ruta
        except (OSError, sqlite3.Error) as exc:
            self._limpiar()
            raise BDTemporalError(
                f"No se pudo crear la BD temporal: {type(exc).__name__}: {exc}"
            ) from exc
        return self

    def __exit__(self, *exc: object) -> None:
        self._limpiar()

    def _conectar(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.ruta)
        conn.row_factory = sqlite3.Row
        return conn

    def filas(self, user_id: str | None = None) -> list[dict]:
        conn = self._conectar()
        try:
            if user_id is None:
                cur = conn.execute("SELECT * FROM transactions ORDER BY id")
            else:
                cur = conn.execute(
                    "SELECT * FROM transactions WHERE user_id = ? ORDER BY id", (user_id,)
                )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    def contar(self) -> int:
        conn = self._conectar()
        try:
            return int(conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0])
        finally:
            conn.close()
