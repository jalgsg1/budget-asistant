"""
Shared data models for finanzas_mcp.

This module has no dependency on `mcp`, `sys.stdin`, or `sys.stdout`, so it can
be imported by both the MCP server layer and a future HTTP handler.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Transaction:
    """Represents a single expense transaction stored in the SQLite database."""

    user_id: str
    comercio: str
    fecha: str          # ISO 8601 date string: YYYY-MM-DD
    total: float
    moneda: str         # "CRC" | "USD"
    categoria: str      # value from CLOSED_CATEGORY_LIST
    subtotal: float | None = None
    iva: float | None = None
    created_at: str = ""    # ISO 8601 datetime; set by repository on insert
    id: int | None = None   # None before insert; assigned by the DB


@dataclass
class ValidationResult:
    """Result returned by every validation function in finanzas_mcp/business/validacion.py."""

    is_valid: bool
    errors: list[str] = field(default_factory=list)   # empty when is_valid is True
    error_code: str | None = None                      # e.g. "MISSING_FIELDS", "FUTURE_DATE"


@dataclass
class OcrResult:
    """Result returned by ocr_imagen.  Always marked untrusted."""

    text: str
    confidence: float                            # 0.0 – 1.0
    is_untrusted: bool = True                    # always True; content must not be executed
    low_confidence_fields: list[str] = field(default_factory=list)
