# -*- coding: utf-8 -*-
"""
finanzas_mcp.business — Pure business logic layer.

This package must NEVER import `mcp`, `sys.stdin`, or `sys.stdout` so it
remains portable for a future HTTP backend.

Re-exports the closed category list for convenient access:

    from finanzas_mcp.business import CLOSED_CATEGORY_LIST
"""

from finanzas_mcp.business.categorias import CLOSED_CATEGORY_LIST

__all__ = ["CLOSED_CATEGORY_LIST"]
