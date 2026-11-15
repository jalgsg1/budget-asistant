"""Constantes centralizadas del paquete baseline.

Solo biblioteca estándar. No importa ``finanzas_mcp``, ``ocr_mcp``, ``agent``,
``api_pruebas``, ``mcp`` ni ``eval``: los valores se escriben de nuevo aquí y
``tests/test_constantes.py`` vigila que coincidan con los de otros paquetes.
"""
from __future__ import annotations

ESTADOS_FINALES: tuple[str, ...] = ("registrada", "rechazada", "usuario_rechazo", "limite", "error")

CAMPOS: tuple[str, ...] = (
    "sistema", "ruta_factura", "tokens_entrada", "tokens_salida",
    "duracion_ms", "estado_final", "registro_en_bd",
)

HERRAMIENTA_INSERTAR_NOMBRE: str = "insertar_transaccion"

SISTEMA_NAIVE: str = "baseline_naive"
SISTEMA_PROMPT_GUARDED: str = "baseline_prompt_guarded"
SISTEMA_ARQUITECTURA: str = "arquitectura_mcp"

# Estado del pipeline del agente -> estado final de la traza común.
ESTADO_AGENTE_A_FINAL: dict[str, str] = {
    "success": "registrada",
    "validation_error": "rechazada",
    "user_abort": "usuario_rechazo",
    "step_limit": "limite",
    "token_limit": "limite",
}
