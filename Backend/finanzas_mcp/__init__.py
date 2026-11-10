# -*- coding: utf-8 -*-
"""
finanzas_mcp — MCP server and business logic for gestor-facturas.

Public re-exports so callers can import from the package root when convenient:

    from finanzas_mcp import Transaction, ValidationResult, OcrResult
"""

from finanzas_mcp.models import OcrResult, Transaction, ValidationResult

__all__ = ["Transaction", "ValidationResult", "OcrResult"]
