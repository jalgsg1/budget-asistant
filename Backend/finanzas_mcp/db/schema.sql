-- SQLite schema for gestor-facturas
-- All text fields stored as TEXT; dates stored as ISO 8601 strings (YYYY-MM-DD).

CREATE TABLE IF NOT EXISTS transactions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     TEXT    NOT NULL,
    comercio    TEXT    NOT NULL,
    fecha       TEXT    NOT NULL,               -- ISO 8601 date: YYYY-MM-DD
    total       REAL    NOT NULL,
    moneda      TEXT    NOT NULL CHECK(moneda IN ('CRC', 'USD')),
    categoria   TEXT    NOT NULL,
    subtotal    REAL,                           -- optional
    iva         REAL,                           -- optional
    descripcion TEXT,                           -- optional free-text from invoice
    created_at  TEXT    NOT NULL                -- ISO 8601 datetime
);

-- Fast look-up by user (used by every query)
CREATE INDEX IF NOT EXISTS idx_tx_user
    ON transactions(user_id);

-- Composite index used by find_duplicates to detect (comercio, fecha, total) matches
-- within a user's scope efficiently.
CREATE INDEX IF NOT EXISTS idx_tx_duplicados
    ON transactions(comercio, fecha, total, user_id);
