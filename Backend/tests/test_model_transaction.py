"""Property 12: Round trip fila-modelo.

Feature: invoice-analyze-api, Property 12: Round trip fila-modelo
**Validates: Requirements 8.5**
"""
import sqlite3

from hypothesis import given, settings, strategies as st

from model.transaction import COLUMNAS, Transaction

_ESQUEMA = """
CREATE TABLE transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    comercio TEXT NOT NULL,
    fecha TEXT NOT NULL,
    total REAL NOT NULL,
    moneda TEXT NOT NULL,
    categoria TEXT NOT NULL,
    subtotal REAL,
    iva REAL,
    descripcion TEXT,
    created_at TEXT NOT NULL
)
"""

_texto = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters="\x00"),
    max_size=40,
)
_monto = st.floats(allow_nan=False, allow_infinity=False, width=64)

_transacciones = st.builds(
    Transaction,
    user_id=_texto,
    comercio=_texto,
    fecha=_texto,
    total=_monto,
    moneda=_texto,
    categoria=_texto,
    created_at=_texto,
    subtotal=st.none() | _monto,
    iva=st.none() | _monto,
    descripcion=st.none() | _texto,
    id=st.none() | st.integers(min_value=1, max_value=2**62),
)


def _fila_sqlite(tx: Transaction) -> sqlite3.Row:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(_ESQUEMA)
        datos = tx.to_dict()
        if datos["id"] is None:
            datos.pop("id")
        columnas = list(datos)
        conn.execute(
            f"INSERT INTO transactions ({', '.join(columnas)}) "
            f"VALUES ({', '.join('?' for _ in columnas)})",
            [datos[c] for c in columnas],
        )
        return conn.execute("SELECT * FROM transactions").fetchone()
    finally:
        conn.close()


@settings(max_examples=100, deadline=None)
@given(tx=_transacciones)
def test_round_trip_fila_modelo(tx: Transaction):
    """Feature: invoice-analyze-api, Property 12: Round trip fila-modelo."""
    original = tx.to_dict()
    assert tuple(original) == COLUMNAS

    # Fila sqlite3.Row real (por nombre)
    fila = _fila_sqlite(tx)
    reconstruida = Transaction.from_row(fila).to_dict()
    esperado = dict(original)
    if esperado["id"] is None:  # la base asigna el id autoincremental
        assert reconstruida["id"] is not None
        esperado["id"] = reconstruida["id"]
    assert reconstruida == esperado
    assert tuple(reconstruida) == COLUMNAS

    # dict por nombre y tupla en el orden de COLUMNAS
    assert Transaction.from_row(original).to_dict() == original
    assert Transaction.from_row(tuple(original[c] for c in COLUMNAS)).to_dict() == original
