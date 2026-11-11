"""
SQLite repository for gestor-facturas.

Intentionally free of any `mcp`, `sys.stdin`, or `sys.stdout` dependency so it
can be used by both the MCP server adapter and a future HTTP handler.

All file I/O uses UTF-8 encoding as required by the technical rules of the course.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from finanzas_mcp.models import Transaction

# Absolute path to the SQL schema file (same directory as this module).
_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


class TransactionRepository:
    """Provides CRUD operations for the `transactions` table in a SQLite database.

    Parameters
    ----------
    db_path:
        Filesystem path to the SQLite database file.  The file (and any parent
        directories) are created automatically if they do not yet exist.
    """

    def __init__(self, db_path: str) -> None:
        # Ensure parent directories exist.
        db_file = Path(db_path)
        db_file.parent.mkdir(parents=True, exist_ok=True)

        self._db_path = str(db_file)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row  # enables column-name access

        # Enforce foreign-key constraints and WAL mode for safer concurrent access.
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")

        self._init_schema()

    # ------------------------------------------------------------------
    # Schema initialisation
    # ------------------------------------------------------------------

    def _init_schema(self) -> None:
        """Read schema.sql and execute it to create tables and indexes if absent."""
        schema_sql = _SCHEMA_PATH.read_text(encoding="utf-8")
        self._conn.executescript(schema_sql)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def insert(self, tx: Transaction) -> int:
        """Insert *tx* into the database and return the new row id.

        The ``created_at`` field is set to the current UTC datetime in ISO 8601
        format if not already populated on the dataclass instance.

        Parameters
        ----------
        tx:
            Transaction to persist.  ``tx.id`` is ignored; the database assigns
            the primary key automatically.

        Returns
        -------
        int
            The ``rowid`` / ``id`` of the newly created row.
        """
        created_at = tx.created_at or _utcnow_iso()

        cursor = self._conn.execute(
            """
            INSERT INTO transactions
                (user_id, comercio, fecha, total, moneda, categoria, subtotal, iva, descripcion, created_at)
            VALUES
                (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tx.user_id,
                tx.comercio,
                tx.fecha,
                tx.total,
                tx.moneda,
                tx.categoria,
                tx.subtotal,
                tx.iva,
                tx.descripcion,
                created_at,
            ),
        )
        self._conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    def find_duplicates(
        self,
        comercio: str,
        fecha: str,
        total: float,
        user_id: str,
        limit: int = 10,
    ) -> list[Transaction]:
        """Return records that match *comercio*, *fecha*, and *total* for *user_id*.

        The result set is bounded by *limit* (maximum 10 by design — Property 7).

        Parameters
        ----------
        comercio:
            Merchant name to match (exact, case-sensitive).
        fecha:
            Date string to match (ISO 8601: YYYY-MM-DD).
        total:
            Transaction total to match.
        user_id:
            Only records belonging to this user are considered.
        limit:
            Upper bound on the number of results returned.  Callers should leave
            this at the default of 10 to enforce Property 7.

        Returns
        -------
        list[Transaction]
            Matching transactions, never more than *limit* entries.
        """
        # Clamp the limit defensively so callers cannot accidentally bypass
        # the design maximum of 10.
        effective_limit = min(limit, 10)

        rows = self._conn.execute(
            """
            SELECT id, user_id, comercio, fecha, total, moneda, categoria,
                   subtotal, iva, descripcion, created_at
            FROM   transactions
            WHERE  user_id  = ?
              AND  comercio = ?
              AND  fecha    = ?
              AND  total    = ?
            LIMIT  ?
            """,
            (user_id, comercio, fecha, total, effective_limit),
        ).fetchall()

        return [_row_to_transaction(row) for row in rows]

    def query(self, filters: dict[str, Any], user_id: str) -> list[Transaction]:
        """Return transactions for *user_id* matching the provided *filters*.

        Only the following filter keys are handled; unrecognised keys are silently
        ignored at this layer (the business layer enforces the whitelist before
        calling the repository).

        Supported filters
        -----------------
        comercio : str
            Exact merchant match.
        fecha_desde : str
            Inclusive lower bound on ``fecha`` (ISO 8601 date).
        fecha_hasta : str
            Inclusive upper bound on ``fecha`` (ISO 8601 date).
        categoria : str
            Exact category match.
        moneda : str
            Currency code (CRC or USD).

        Parameters
        ----------
        filters:
            Dict of filter key → value pairs.
        user_id:
            All results are restricted to this user (Property 14 — user isolation).

        Returns
        -------
        list[Transaction]
            Matching transactions ordered by ``fecha`` descending.
        """
        clauses: list[str] = ["user_id = ?"]
        params: list[Any] = [user_id]

        if "comercio" in filters:
            clauses.append("comercio = ?")
            params.append(filters["comercio"])

        if "fecha_desde" in filters:
            clauses.append("fecha >= ?")
            params.append(filters["fecha_desde"])

        if "fecha_hasta" in filters:
            clauses.append("fecha <= ?")
            params.append(filters["fecha_hasta"])

        if "categoria" in filters:
            clauses.append("categoria = ?")
            params.append(filters["categoria"])

        if "moneda" in filters:
            clauses.append("moneda = ?")
            params.append(filters["moneda"])

        where_clause = " AND ".join(clauses)
        sql = f"""
            SELECT id, user_id, comercio, fecha, total, moneda, categoria,
                   subtotal, iva, descripcion, created_at
            FROM   transactions
            WHERE  {where_clause}
            ORDER  BY fecha DESC
        """

        rows = self._conn.execute(sql, params).fetchall()
        return [_row_to_transaction(row) for row in rows]

    def eliminar_por_usuario(self, user_id: str) -> int:
        """Delete every transaction belonging to *user_id* and return the row count."""
        cursor = self._conn.execute(
            "DELETE FROM transactions WHERE user_id = ?", (user_id,)
        )
        self._conn.commit()
        return cursor.rowcount

    # ------------------------------------------------------------------
    # Resource management
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self._conn.close()

    def __enter__(self) -> "TransactionRepository":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()


# ------------------------------------------------------------------
# Private helpers
# ------------------------------------------------------------------

def _utcnow_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row_to_transaction(row: sqlite3.Row) -> Transaction:
    """Convert a :class:`sqlite3.Row` to a :class:`Transaction` dataclass."""
    return Transaction(
        id=row["id"],
        user_id=row["user_id"],
        comercio=row["comercio"],
        fecha=row["fecha"],
        total=row["total"],
        moneda=row["moneda"],
        categoria=row["categoria"],
        subtotal=row["subtotal"],
        iva=row["iva"],
        descripcion=row["descripcion"],
        created_at=row["created_at"],
    )
