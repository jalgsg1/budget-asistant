# -*- coding: utf-8 -*-
"""POST /facturas/analizar — OCR + validación de una factura subida, sin registrarla."""

from __future__ import annotations

from fastapi import APIRouter, File, Request, UploadFile

from api_pruebas.errores import ErrorEstandar
from api_pruebas.esquemas import AnalisisFacturaRespuesta

router = APIRouter()


@router.post(
    "/facturas/analizar",
    summary="Analizar una factura sin registrarla",
    response_model=AnalisisFacturaRespuesta,
    responses={
        422: {"model": ErrorEstandar, "description": "Falta la parte 'archivo'"},
    },
)
def analizar_factura(
    request: Request,
    archivo: UploadFile = File(..., description="Imagen o PDF de la factura"),
) -> AnalisisFacturaRespuesta:
    config = request.app.state.config
    servicios = request.app.state.servicios

    # Lectura acotada: max+1 bytes bastan para detectar el exceso sin cargar todo.
    # El exceso de tamaño se reporta como advertencia (HTTP 200) en el servicio.
    contenido = archivo.file.read(config.max_upload_bytes + 1)
    return servicios.analizar_subida(archivo.filename or "", contenido)
