# -*- coding: utf-8 -*-
"""Rutas de procesamiento por lotes: ``/batch/run``, ``/batch`` y ``/batch/{batch_id}``."""

from __future__ import annotations

from fastapi import APIRouter, Request

from api_pruebas.batch import ejecutar_batch, leer_batch, listar_batches
from api_pruebas.esquemas import (
    BatchIn,
    BatchRespuesta,
    BatchResumen,
    ErrorEstandar,
    ReporteBatch,
)

router = APIRouter()


@router.post(
    "/batch/run",
    summary="Procesar todas las imágenes de una subcarpeta",
    response_model=BatchRespuesta,
    responses={
        400: {
            "model": ErrorEstandar,
            "description": "BATCH_PATH_VIOLATION, BATCH_NO_IMAGES, BATCH_TOO_MANY_IMAGES o BATCH_UNKNOWN_IMAGE",
        },
        403: {"model": ErrorEstandar, "description": "TEST_MODE_DISABLED"},
        404: {"model": ErrorEstandar, "description": "BATCH_FOLDER_NOT_FOUND"},
        422: {"model": ErrorEstandar, "description": "VALIDATION_ERROR"},
    },
)
def batch_run(req: BatchIn, request: Request) -> BatchRespuesta:
    return ejecutar_batch(request.app.state.servicios, request.app.state.config, req)


@router.get(
    "/batch",
    summary="Listar los lotes del usuario",
    response_model=list[BatchResumen],
)
def batch_listar(request: Request) -> list[BatchResumen]:
    return listar_batches(request.app.state.config)


@router.get(
    "/batch/{batch_id}",
    summary="Consultar el reporte de un lote",
    response_model=ReporteBatch,
    responses={
        400: {"model": ErrorEstandar, "description": "INVALID_BATCH_ID"},
        404: {"model": ErrorEstandar, "description": "BATCH_NOT_FOUND"},
    },
)
def batch_leer(batch_id: str, request: Request) -> ReporteBatch:
    return leer_batch(request.app.state.config, batch_id)
