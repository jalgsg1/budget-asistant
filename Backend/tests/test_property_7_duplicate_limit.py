"""
Property 7: Duplicate detection result bound
Validates: Requirements 6.2, 10.3

Asserts that `find_duplicates` never returns more than 10 records regardless of
how many matching rows exist in the database.

Uses an in-memory SQLite database (`:memory:`) for full test isolation with no
external network or file-system dependencies.
"""

from __future__ import annotations

import sqlite3
import unittest

from hypothesis import given, settings
from hypothesis import strategies as st

from finanzas_mcp.db.repository import TransactionRepository
from finanzas_mcp.models import Transaction


# ---------------------------------------------------------------------------
# Strategy helpers (mirror conventions from test_property_14_user_isolation.py)
# ---------------------------------------------------------------------------

_DATE_ST = st.dates(
    min_value=__import__("datetime").date(2000, 1, 1),
    max_value=__import__("datetime").date(2030, 12, 31),
).map(lambda d: d.isoformat())

_MONEDA_ST = st.sampled_from(["CRC", "USD"])

_TEXT_ST = st.text(
    alphabet=st.characters(
        whitelist_categories=("Lu", "Ll", "Nd"),
        whitelist_characters=" _-",
    ),
    min_size=1,
    max_size=40,
)

_TOTAL_ST = st.floats(
    min_value=0.01,
    max_value=9_999_999.0,
    allow_nan=False,
    allow_infinity=False,
).map(lambda f: round(f, 2))


# ---------------------------------------------------------------------------
# In-memory repository (same pattern as Property 14 tests)
# ---------------------------------------------------------------------------

class _InMemoryRepo(TransactionRepository):
    """TransactionRepository backed by a shared `:memory:` SQLite connection.

    Bypasses the file-based constructor so each test run gets a fully isolated,
    ephemeral database without touching the filesystem.
    """

    def __init__(self) -> None:
        self._db_path = ":memory:"
        self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._init_schema()


# ---------------------------------------------------------------------------
# Property 7 — duplicate detection result bound
# ---------------------------------------------------------------------------

class TestProperty7DuplicateLimit(unittest.TestCase):
    """Property 7: Duplicate detection result bound — Validates: Requirements 6.2, 10.3"""

    @settings(max_examples=100)
    @given(
        n=st.integers(min_value=1, max_value=50),
        comercio=_TEXT_ST,
        fecha=_DATE_ST,
        total=_TOTAL_ST,
        moneda=_MONEDA_ST,
        categoria=_TEXT_ST,
        user_id=_TEXT_ST,
    )
    def test_property_7_find_duplicates_result_bound(
        self,
        n: int,
        comercio: str,
        fecha: str,
        total: float,
        moneda: str,
        categoria: str,
        user_id: str,
    ) -> None:
        """
        **Property 7: Duplicate detection result bound**

        **Validates: Requirements 6.2, 10.3**

        For any number *n* of matching records inserted (1 ≤ n ≤ 50),
        `find_duplicates` must return at most 10 results.  This is true even when
        the caller passes `limit=10` explicitly (the default) because the repository
        enforces that maximum defensively.
        """
        repo = _InMemoryRepo()
        try:
            # Insert *n* records all sharing the same (comercio, fecha, total, user_id)
            for _ in range(n):
                repo.insert(
                    Transaction(
                        user_id=user_id,
                        comercio=comercio,
                        fecha=fecha,
                        total=total,
                        moneda=moneda,
                        categoria=categoria,
                    )
                )

            result = repo.find_duplicates(
                comercio=comercio,
                fecha=fecha,
                total=total,
                user_id=user_id,
                limit=10,
            )

            # --- primary assertion: result is bounded by 10 ---
            self.assertLessEqual(
                len(result), 10,
                f"find_duplicates returned {len(result)} records but must return at most 10 "
                f"(inserted {n} matching rows for user_id={user_id!r})"
            )

            # --- secondary assertion: all returned records belong to the queried user ---
            for record in result:
                self.assertEqual(
                    record.user_id, user_id,
                    f"find_duplicates returned record with user_id={record.user_id!r} "
                    f"but was queried as user_id={user_id!r}"
                )
        finally:
            repo.close()

    @settings(max_examples=100)
    @given(
        n=st.integers(min_value=11, max_value=50),
        comercio=_TEXT_ST,
        fecha=_DATE_ST,
        total=_TOTAL_ST,
        moneda=_MONEDA_ST,
        categoria=_TEXT_ST,
        user_id=_TEXT_ST,
    )
    def test_property_7_find_duplicates_hard_cap_above_10(
        self,
        n: int,
        comercio: str,
        fecha: str,
        total: float,
        moneda: str,
        categoria: str,
        user_id: str,
    ) -> None:
        """
        **Property 7: Duplicate detection result bound** — hard-cap variant

        **Validates: Requirements 6.2, 10.3**

        Specifically exercises the case where more than 10 matching rows exist
        (11 ≤ n ≤ 50).  Even in this scenario the result list must never exceed 10
        entries, confirming the LIMIT clause is enforced unconditionally.
        """
        repo = _InMemoryRepo()
        try:
            for _ in range(n):
                repo.insert(
                    Transaction(
                        user_id=user_id,
                        comercio=comercio,
                        fecha=fecha,
                        total=total,
                        moneda=moneda,
                        categoria=categoria,
                    )
                )

            result = repo.find_duplicates(
                comercio=comercio,
                fecha=fecha,
                total=total,
                user_id=user_id,
                limit=10,
            )

            self.assertLessEqual(
                len(result), 10,
                f"find_duplicates returned {len(result)} records (inserted {n} > 10 matching rows); "
                f"hard cap of 10 was not enforced for user_id={user_id!r}"
            )

            for record in result:
                self.assertEqual(
                    record.user_id, user_id,
                    f"find_duplicates returned record with user_id={record.user_id!r} "
                    f"but was queried as user_id={user_id!r}"
                )
        finally:
            repo.close()


if __name__ == "__main__":
    unittest.main()
