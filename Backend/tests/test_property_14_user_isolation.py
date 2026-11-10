"""
Property 14: User isolation invariant
Validates: Requirements 10.3

Asserts that `query` and `find_duplicates` never return records belonging to a
different user, regardless of how many transactions are inserted for each user.

Uses an in-memory SQLite database (`:memory:`) for full test isolation with no
external network or file-system dependencies.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from finanzas_mcp.db.repository import TransactionRepository
from finanzas_mcp.models import Transaction


# ---------------------------------------------------------------------------
# Strategy helpers
# ---------------------------------------------------------------------------

# Generate realistic ISO 8601 dates within a safe range so SQLite ordering works
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

_TOTAL_ST = st.floats(min_value=0.01, max_value=9_999_999.0, allow_nan=False, allow_infinity=False).map(
    lambda f: round(f, 2)
)


def _transaction_st(user_id: str) -> st.SearchStrategy[Transaction]:
    """Return a strategy that generates a Transaction fixed to *user_id*."""
    return st.builds(
        Transaction,
        user_id=st.just(user_id),
        comercio=_TEXT_ST,
        fecha=_DATE_ST,
        total=_TOTAL_ST,
        moneda=_MONEDA_ST,
        categoria=_TEXT_ST,
        subtotal=st.one_of(st.none(), _TOTAL_ST),
        iva=st.one_of(st.none(), _TOTAL_ST),
    )


def _distinct_user_ids() -> st.SearchStrategy[tuple[str, str]]:
    """Return a strategy that produces two distinct non-empty user IDs."""
    return st.tuples(_TEXT_ST, _TEXT_ST).filter(lambda pair: pair[0] != pair[1])


# ---------------------------------------------------------------------------
# In-memory repository fixture
# ---------------------------------------------------------------------------

class _InMemoryRepo(TransactionRepository):
    """TransactionRepository backed by a shared `:memory:` SQLite connection.

    The standard constructor opens a *file* connection; this subclass injects
    an already-open in-memory connection so tests are fully isolated and fast.
    """

    def __init__(self) -> None:
        # Bypass the parent __init__ — we wire up everything manually.
        self._db_path = ":memory:"
        self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._init_schema()


# ---------------------------------------------------------------------------
# Property 14 — user isolation
# ---------------------------------------------------------------------------

@settings(max_examples=100)
@given(
    users=_distinct_user_ids(),
    txs_a=st.lists(_transaction_st("__user_a__"), min_size=1, max_size=10),
    txs_b=st.lists(_transaction_st("__user_b__"), min_size=1, max_size=10),
)
def test_property_14_query_user_isolation(
    users: tuple[str, str],
    txs_a: list[Transaction],
    txs_b: list[Transaction],
) -> None:
    """
    **Property 14: User isolation invariant** — `query`

    **Validates: Requirements 10.3**

    For any two distinct users A and B, `repo.query({}, user_id=user_A)` must
    never return a record whose `user_id` is `user_B`, regardless of the
    transactions stored for either user.
    """
    user_a, user_b = users

    # Rebuild the user_id fields to match the generated distinct IDs
    txs_a = [
        Transaction(
            user_id=user_a,
            comercio=tx.comercio,
            fecha=tx.fecha,
            total=tx.total,
            moneda=tx.moneda,
            categoria=tx.categoria,
            subtotal=tx.subtotal,
            iva=tx.iva,
        )
        for tx in txs_a
    ]
    txs_b = [
        Transaction(
            user_id=user_b,
            comercio=tx.comercio,
            fecha=tx.fecha,
            total=tx.total,
            moneda=tx.moneda,
            categoria=tx.categoria,
            subtotal=tx.subtotal,
            iva=tx.iva,
        )
        for tx in txs_b
    ]

    repo = _InMemoryRepo()
    try:
        for tx in txs_a:
            repo.insert(tx)
        for tx in txs_b:
            repo.insert(tx)

        # --- assertion: querying as user_A must not leak user_B records ---
        results_a = repo.query({}, user_id=user_a)
        for record in results_a:
            assert record.user_id == user_a, (
                f"query returned record with user_id={record.user_id!r} "
                f"when querying as user_A={user_a!r}"
            )

        # --- assertion: querying as user_B must not leak user_A records ---
        results_b = repo.query({}, user_id=user_b)
        for record in results_b:
            assert record.user_id == user_b, (
                f"query returned record with user_id={record.user_id!r} "
                f"when querying as user_B={user_b!r}"
            )
    finally:
        repo.close()


@settings(max_examples=100)
@given(
    users=_distinct_user_ids(),
    txs_a=st.lists(_transaction_st("__user_a__"), min_size=1, max_size=10),
    txs_b=st.lists(_transaction_st("__user_b__"), min_size=1, max_size=10),
)
def test_property_14_find_duplicates_user_isolation(
    users: tuple[str, str],
    txs_a: list[Transaction],
    txs_b: list[Transaction],
) -> None:
    """
    **Property 14: User isolation invariant** — `find_duplicates`

    **Validates: Requirements 10.3**

    For any two distinct users A and B, `repo.find_duplicates(comercio, fecha,
    total, user_id=user_A)` must never return a record whose `user_id` is
    `user_B`, even when user_B has an identical (comercio, fecha, total) tuple.
    """
    user_a, user_b = users

    # Rebuild the user_id fields to match the generated distinct IDs
    txs_a = [
        Transaction(
            user_id=user_a,
            comercio=tx.comercio,
            fecha=tx.fecha,
            total=tx.total,
            moneda=tx.moneda,
            categoria=tx.categoria,
            subtotal=tx.subtotal,
            iva=tx.iva,
        )
        for tx in txs_a
    ]
    txs_b = [
        Transaction(
            user_id=user_b,
            comercio=tx.comercio,
            fecha=tx.fecha,
            total=tx.total,
            moneda=tx.moneda,
            categoria=tx.categoria,
            subtotal=tx.subtotal,
            iva=tx.iva,
        )
        for tx in txs_b
    ]

    repo = _InMemoryRepo()
    try:
        for tx in txs_a:
            repo.insert(tx)
        for tx in txs_b:
            repo.insert(tx)

        # For every transaction inserted for user_A, run find_duplicates as
        # user_A and ensure no user_B records are returned.
        for tx in txs_a:
            results = repo.find_duplicates(
                comercio=tx.comercio,
                fecha=tx.fecha,
                total=tx.total,
                user_id=user_a,
                limit=10,
            )
            for record in results:
                assert record.user_id == user_a, (
                    f"find_duplicates returned record with user_id={record.user_id!r} "
                    f"when searching as user_A={user_a!r} "
                    f"(comercio={tx.comercio!r}, fecha={tx.fecha!r}, total={tx.total})"
                )

        # Symmetrical check: user_B must not see user_A records
        for tx in txs_b:
            results = repo.find_duplicates(
                comercio=tx.comercio,
                fecha=tx.fecha,
                total=tx.total,
                user_id=user_b,
                limit=10,
            )
            for record in results:
                assert record.user_id == user_b, (
                    f"find_duplicates returned record with user_id={record.user_id!r} "
                    f"when searching as user_B={user_b!r} "
                    f"(comercio={tx.comercio!r}, fecha={tx.fecha!r}, total={tx.total})"
                )
    finally:
        repo.close()


@settings(max_examples=100)
@given(
    users=_distinct_user_ids(),
    shared_comercio=_TEXT_ST,
    shared_fecha=_DATE_ST,
    shared_total=_TOTAL_ST,
    moneda=_MONEDA_ST,
    categoria=_TEXT_ST,
)
def test_property_14_identical_tuple_cross_user_isolation(
    users: tuple[str, str],
    shared_comercio: str,
    shared_fecha: str,
    shared_total: float,
    moneda: str,
    categoria: str,
) -> None:
    """
    **Property 14: User isolation invariant** — worst-case identical tuples

    **Validates: Requirements 10.3**

    The hardest case for isolation: both users have an identical
    (comercio, fecha, total) tuple. `find_duplicates` for user_A must still
    never return user_B's record and vice versa.
    """
    user_a, user_b = users

    tx_a = Transaction(
        user_id=user_a,
        comercio=shared_comercio,
        fecha=shared_fecha,
        total=shared_total,
        moneda=moneda,
        categoria=categoria,
    )
    tx_b = Transaction(
        user_id=user_b,
        comercio=shared_comercio,
        fecha=shared_fecha,
        total=shared_total,
        moneda=moneda,
        categoria=categoria,
    )

    repo = _InMemoryRepo()
    try:
        repo.insert(tx_a)
        repo.insert(tx_b)

        # user_A searches for the shared tuple — must only see their own record
        results_a = repo.find_duplicates(
            comercio=shared_comercio,
            fecha=shared_fecha,
            total=shared_total,
            user_id=user_a,
            limit=10,
        )
        for record in results_a:
            assert record.user_id == user_a, (
                f"find_duplicates leaked user_B={user_b!r} record to user_A={user_a!r} "
                f"on identical (comercio, fecha, total) tuple"
            )

        # user_B searches for the shared tuple — must only see their own record
        results_b = repo.find_duplicates(
            comercio=shared_comercio,
            fecha=shared_fecha,
            total=shared_total,
            user_id=user_b,
            limit=10,
        )
        for record in results_b:
            assert record.user_id == user_b, (
                f"find_duplicates leaked user_A={user_a!r} record to user_B={user_b!r} "
                f"on identical (comercio, fecha, total) tuple"
            )
    finally:
        repo.close()
