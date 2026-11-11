# -*- coding: utf-8 -*-
"""POST /ocr — extracción OCR por ruta dentro de INVOICES_DIR o por subida de archivo."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, File, Form, Request, UploadFile

from api_pruebas.errores import ErrorEstandar, error_api
from api_pruebas.esquemas import OcrRespuesta

router = APIRouter()


@router.post(
    "/ocr",
    summary="Extraer datos de una factura con OCR",
    response_model=OcrRespuesta,
    responses={
        400: {"model": ErrorEstandar, "description": "Ruta inválida o imagen inválida"},
        413: {"model": ErrorEstandar, "description": "Archivo demasiado grande"},
        415: {"model": ErrorEstandar, "description": "Tipo de archivo no soportado"},
        422: {"model": ErrorEstandar, "description": "Debe enviarse exactamente uno de ruta o archivo"},
        502: {"model": ErrorEstandar, "description": "Fallo del servicio OCR"},
    },
)
def ocr(
    request: Request,
    ruta: Optional[str] = Form(None, description="Ruta relativa dentro de INVOICES_DIR"),
    archivo: Optional[UploadFile] = File(None, description="Imagen o PDF a subir"),
) -> OcrRespuesta:
    config = request.app.state.config
    servicios = request.app.state.servicios

    tiene_ruta = ruta is not None and ruta.strip() != ""
    tiene_archivo = archivo is not None and bool(archivo.filename)
    if tiene_ruta == tiene_archivo:
        raise error_api(
            "VALIDATION_ERROR",
            "Debe enviar exactamente uno de 'ruta' o 'archivo'.",
        )

    if tiene_ruta:
        return servicios.ocr_ruta(ruta)

    # Lectura acotada: max+1 bytes bastan para detectar el exceso sin cargar todo.
    contenido = archivo.file.read(config.max_upload_bytes + 1)
    if len(contenido) > config.max_upload_bytes:
        raise error_api(
            "FILE_TOO_LARGE",
            f"El archivo excede el tamaño máximo de {config.max_upload_bytes} bytes.",
        )
    _, respuesta = servicios.ocr_subida(archivo.filename, contenido)
    return respuesta
