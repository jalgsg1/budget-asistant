# -*- coding: utf-8 -*-
"""
api_pruebas/errores.py — Errores de la API, mapeo uniforme y redacción de secretos.

Una única tabla convierte excepciones en ``(http_status, code, message)``. La usan
los handlers HTTP y el adaptador de herramientas del Pipeline. Nunca importa ``mcp``.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from agent.agent import ToolError
from finanzas_mcp.business.transacciones import (
    DateRangeError,
    FilterError,
    ValidationError,
)
from ocr_mcp.ocr_core import OcrToolError

LOGGER_NAME = "api_pruebas"
logger = logging.getLogger(LOGGER_NAME)

MENSAJE_INTERNO = "Error interno del servidor."

# ---------------------------------------------------------------------------
# Redacción de secretos
# ---------------------------------------------------------------------------

_PATRON_CLAVE = re.compile(r"sk-[A-Za-z0-9_-]{16,}")
_MIN_LARGO_SECRETO = 8
_MASCARA = "***"


def _secretos_entorno() -> list[str]:
    """Valores de variables ``*_API_KEY`` con 8+ caracteres, más largos primero."""
    valores = {
        v.strip()
        for k, v in os.environ.items()
        if k.upper().endswith("_API_KEY") and len(v.strip()) >= _MIN_LARGO_SECRETO
    }
    return sorted(valores, key=len, reverse=True)


def _redactar_texto(texto: str, secretos: list[str]) -> str:
    for s in secretos:
        texto = texto.replace(s, _MASCARA)
    return _PATRON_CLAVE.sub(_MASCARA, texto)


def _redactar(obj: Any, secretos: list[str]) -> Any:
    if isinstance(obj, str):
        return _redactar_texto(obj, secretos)
    if isinstance(obj, dict):
        return {
            (_redactar_texto(k, secretos) if isinstance(k, str) else k): _redactar(v, secretos)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_redactar(v, secretos) for v in obj]
    if isinstance(obj, tuple):
        return tuple(_redactar(v, secretos) for v in obj)
    return obj


def redactar(obj: Any) -> Any:
    """Devuelve una copia de ``obj`` con claves de API sustituidas por ``***``."""
    return _redactar(obj, _secretos_entorno())


class FiltroRedaccion(logging.Filter):
    """``logging.Filter`` que aplica ``redactar`` al mensaje de cada registro."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        try:
            record.msg = redactar(record.getMessage())
            record.args = None
            if record.exc_info:
                record.exc_info = None
                record.exc_text = None
        except Exception:  # pragma: no cover - nunca bloquear el log
            record.msg = _MASCARA
            record.args = None
        return True


def configurar_logging() -> None:
    """Instala ``FiltroRedaccion`` en el logger ``api_pruebas`` (idempotente)."""
    if not any(isinstance(f, FiltroRedaccion) for f in logger.filters):
        logger.addFilter(FiltroRedaccion())


configurar_logging()

# ---------------------------------------------------------------------------
# Modelos y excepción de la API
# ---------------------------------------------------------------------------


class ErrorEstandar(BaseModel):
    """Cuerpo uniforme de todas las respuestas de error."""

    code: str
    message: str


class ErrorApi(Exception):
    """Error de la API con estado HTTP, código estable y mensaje."""

    def __init__(self, status: int, code: str, message: str) -> None:
        self.status = status
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


# Códigos de error "de la API" (status HTTP fijo por código).
CODIGOS_API: dict[str, int] = {
    # Subida
    "FILE_TOO_LARGE": 413,
    "UNSUPPORTED_MEDIA": 415,
    # Trazas
    "INVALID_TRACE_ID": 400,
    "TRACE_NOT_FOUND": 404,
    # Modo pruebas
    "TEST_MODE_DISABLED": 403,
    "TEST_DB_NOT_ALLOWED": 403,
    # Batch
    "BATCH_PATH_VIOLATION": 400,
    "BATCH_FOLDER_NOT_FOUND": 404,
    "BATCH_NO_IMAGES": 400,
    "BATCH_TOO_MANY_IMAGES": 400,
    "BATCH_UNKNOWN_IMAGE": 400,
    "INVALID_BATCH_ID": 400,
    "BATCH_NOT_FOUND": 404,
    # Transacciones
    "TRANSACTION_NOT_FOUND": 404,
    # Genéricos
    "VALIDATION_ERROR": 422,
    "INTERNAL_ERROR": 500,
}


def error_api(code: str, message: str) -> ErrorApi:
    """Construye un ``ErrorApi`` con el status asociado a ``code``."""
    return ErrorApi(CODIGOS_API[code], code, message)


# ---------------------------------------------------------------------------
# Tabla única de mapeo excepción -> (http_status, code, message)
# ---------------------------------------------------------------------------

_OCR_400 = frozenset({"PATH_VIOLATION", "INVALID_IMAGE"})
_OCR_502 = frozenset({"OCR_FAILURE"})


def _status_codigo_herramienta(code: str) -> int:
    if code in _OCR_400:
        return 400
    if code in _OCR_502:
        return 502
    return 422


def mapear_excepcion(exc: BaseException) -> tuple[int, str, str]:
    """Convierte ``exc`` en ``(http_status, code, message)`` con mensaje redactado."""
    if isinstance(exc, ErrorApi):
        status, code, msg = exc.status, exc.code, exc.message
    elif isinstance(exc, ValidationError):
        code = exc.result.error_code or "VALIDATION_ERROR"
        msg = "; ".join(exc.result.errors) or str(exc)
        # Fecha inválida en filtros del listado es error de entrada (400).
        status = 400 if code == "INVALID_DATE_FORMAT" else 422
    elif isinstance(exc, FilterError):
        status, code, msg = 400, "INVALID_FILTER", str(exc)
    elif isinstance(exc, DateRangeError):
        status, code, msg = 400, "DATE_RANGE_EXCEEDED", str(exc)
    elif isinstance(exc, OcrToolError):
        code = exc.code
        status = _status_codigo_herramienta(code)
        msg = str(exc)
    elif isinstance(exc, ToolError):
        code = exc.code
        status = _status_codigo_herramienta(code)
        msg = exc.message or str(exc)
    else:
        return 500, "INTERNAL_ERROR", MENSAJE_INTERNO
    return status, code, redactar(msg)


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def _respuesta(status: int, code: str, message: str) -> JSONResponse:
    cuerpo = ErrorEstandar(code=code, message=message).model_dump()
    return JSONResponse(status_code=status, content=cuerpo)


async def manejar_error_api(request: Request, exc: ErrorApi) -> JSONResponse:
    status, code, msg = mapear_excepcion(exc)
    return _respuesta(status, code, msg)


async def manejar_error_negocio(request: Request, exc: Exception) -> JSONResponse:
    status, code, msg = mapear_excepcion(exc)
    return _respuesta(status, code, msg)


async def manejar_validacion_request(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """422 con ``loc`` y ``msg`` de cada error; nunca repite el valor recibido."""
    partes = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", ()))
        partes.append(f"{loc}: {err.get('msg', 'valor inválido')}")
    mensaje = redactar("; ".join(partes) or "Solicitud inválida.")
    return _respuesta(422, "VALIDATION_ERROR", mensaje)


_CODIGOS_HTTP = {
    400: "BAD_REQUEST",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    413: "FILE_TOO_LARGE",
    415: "UNSUPPORTED_MEDIA",
}


async def manejar_http_exception(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    code = _CODIGOS_HTTP.get(exc.status_code, f"HTTP_{exc.status_code}")
    detalle = exc.detail if isinstance(exc.detail, str) else code
    return _respuesta(exc.status_code, code, redactar(detalle))


async def manejar_excepcion(request: Request, exc: Exception) -> JSONResponse:
    """500 con mensaje fijo y sin pila; solo se registra el tipo de la excepción."""
    logger.error("Error no controlado: %s", type(exc).__name__)
    return _respuesta(500, "INTERNAL_ERROR", MENSAJE_INTERNO)


def registrar_handlers(app: FastAPI) -> None:
    """Registra todos los handlers de error en ``app``."""
    app.add_exception_handler(ErrorApi, manejar_error_api)
    for tipo in (ValidationError, FilterError, DateRangeError, OcrToolError, ToolError):
        app.add_exception_handler(tipo, manejar_error_negocio)
    app.add_exception_handler(RequestValidationError, manejar_validacion_request)
    app.add_exception_handler(StarletteHTTPException, manejar_http_exception)
    app.add_exception_handler(Exception, manejar_excepcion)
