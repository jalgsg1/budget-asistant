# -*- coding: utf-8 -*-
"""Modelos pydantic de request y response de la API_Pruebas.

No importa nada de ``errores.py`` ni de ``mcp``.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, field_validator

MAX_CLAVES_RESPUESTAS_POR_IMAGEN = 100
MAX_RESPUESTAS_POR_LISTA = 50

Numero = Union[StrictFloat, StrictInt]
ListaRespuestas = Annotated[list[str], Field(max_length=MAX_RESPUESTAS_POR_LISTA)]


class ModeloEstricto(BaseModel):
    """Base de los requests: rechaza campos desconocidos (incluido user_id) y NaN/Inf."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


# --------------------------------------------------------------------------
# Requests
# --------------------------------------------------------------------------


class PipelineIn(ModeloEstricto):
    ruta: str
    respuestas: ListaRespuestas = Field(default_factory=list)


class SeedItem(ModeloEstricto):
    comercio: str
    fecha: str
    total: Numero
    moneda: str
    categoria: str
    subtotal: Optional[Numero] = None
    iva: Optional[Numero] = None
    descripcion: Optional[str] = None


class SeedIn(ModeloEstricto):
    transacciones: Optional[list[SeedItem]] = None


class BatchIn(ModeloEstricto):
    subcarpeta: str
    respuestas_por_defecto: ListaRespuestas = Field(default_factory=list)
    respuestas_por_imagen: dict[str, ListaRespuestas] = Field(default_factory=dict)
    auto_confirmar: bool = False
    confirmar_duplicados: bool = False

    @field_validator("respuestas_por_imagen")
    @classmethod
    def _limitar_claves(cls, v: dict[str, list[str]]) -> dict[str, list[str]]:
        if len(v) > MAX_CLAVES_RESPUESTAS_POR_IMAGEN:
            raise ValueError(
                f"respuestas_por_imagen admite como máximo "
                f"{MAX_CLAVES_RESPUESTAS_POR_IMAGEN} claves"
            )
        return v


# --------------------------------------------------------------------------
# Responses
# --------------------------------------------------------------------------


class ErrorEstandar(BaseModel):
    code: str
    message: str


class ReglaResultado(BaseModel):
    regla: str
    valid: bool
    code: Optional[str] = None
    message: Optional[str] = None


class ValidacionRespuesta(BaseModel):
    valid: bool
    reglas: list[ReglaResultado]


class AnalisisFacturaRespuesta(BaseModel):
    """Resultado de POST /facturas/analizar (no registra nada)."""

    campos: dict[str, Union[str, float]] = Field(default_factory=dict)
    campos_no_identificados: list[str] = Field(default_factory=list)
    validacion: ValidacionRespuesta
    advertencias: list[str] = Field(default_factory=list)


class OcrRespuesta(BaseModel):
    untrusted_content: Literal[True] = True
    is_untrusted: Literal[True] = True
    notice: str
    result: dict[str, Any]
    ruta: str


class TransaccionOut(BaseModel):
    id: Optional[int] = None
    user_id: str
    comercio: str
    fecha: str
    total: float
    moneda: str
    categoria: str
    subtotal: Optional[float] = None
    iva: Optional[float] = None
    descripcion: Optional[str] = None
    created_at: str = ""


class PipelineRespuesta(BaseModel):
    status: str
    termination_reason: str
    transaction_id: Optional[int] = None
    trace_id: str
    mensajes: list[str] = Field(default_factory=list)
    prompts: list[str] = Field(default_factory=list)


class TrazaResumen(BaseModel):
    trace_id: str
    created_at: str
    status: str


class ResetRespuesta(BaseModel):
    eliminadas: int


class SeedRespuesta(BaseModel):
    insertadas: int


# --------------------------------------------------------------------------
# Batch
# --------------------------------------------------------------------------

Clasificacion = Literal[
    "ok",
    "duplicada",
    "no_valida",
    "step_limit",
    "token_limit",
    "user_rejection",
    "error",
]


class ImagenResultado(BaseModel):
    archivo: str
    clasificacion: Clasificacion
    motivo: str
    detalle: Optional[str] = None
    status: Optional[str] = None
    termination_reason: Optional[str] = None
    trace_id: Optional[str] = None
    transaction_id: Optional[int] = None
    reglas_incumplidas: list[str] = Field(default_factory=list)
    duplicada_de: Optional[str] = None


class ConteoClasificaciones(BaseModel):
    ok: int = 0
    duplicada: int = 0
    no_valida: int = 0
    step_limit: int = 0
    token_limit: int = 0
    user_rejection: int = 0
    error: int = 0


class ReporteBatch(BaseModel):
    """Reporte de un Batch. No expone user_id."""

    batch_id: str
    subcarpeta: str
    fecha: str
    total: int
    conteos: ConteoClasificaciones
    imagenes: list[ImagenResultado]


class BatchResumen(BaseModel):
    batch_id: str
    fecha: str
    total: int
    conteos: ConteoClasificaciones


class BatchRespuesta(BaseModel):
    batch_id: str
    reporte: ReporteBatch
