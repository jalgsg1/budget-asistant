# -*- coding: utf-8 -*-
"""Rutas ``/transacciones``: GET (listar), POST (crear) y PUT (reemplazar). No importa ``mcp``."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query, Request

from api_pruebas.esquemas import ErrorEstandar, SeedItem, TransaccionOut

router = APIRouter()


def _salida(tx) -> TransaccionOut:
    return TransaccionOut(
        id=tx.id,
        user_id=tx.user_id,
        comercio=tx.comercio,
        fecha=tx.fecha,
        total=tx.total,
        moneda=tx.moneda,
        categoria=tx.categoria,
        subtotal=tx.subtotal,
        iva=tx.iva,
        descripcion=tx.descripcion,
        created_at=tx.created_at,
    )


@router.get(
    "/transacciones",
    summary="Listar transacciones del usuario configurado",
    response_model=list[TransaccionOut],
    responses={
        400: {
            "model": ErrorEstandar,
            "description": "Filtro no permitido, rango de fechas excedido o fecha inválida.",
        },
    },
)
def listar_transacciones(
    request: Request,
    comercio: Optional[str] = Query(None, description="Filtra por comercio."),
    fecha_desde: Optional[str] = Query(None, description="Fecha inicial (YYYY-MM-DD)."),
    fecha_hasta: Optional[str] = Query(None, description="Fecha final (YYYY-MM-DD)."),
    categoria: Optional[str] = Query(None, description="Filtra por categoría."),
    moneda: Optional[str] = Query(None, description="Filtra por moneda."),
) -> list[TransaccionOut]:
    # Se reenvían todas las claves recibidas (no solo las declaradas) para que
    # un filtro desconocido llegue a la política y produzca 400 INVALID_FILTER.
    filtros = dict(request.query_params)
    servicios = request.app.state.servicios
    filas = servicios.listar(filtros)
    return [
        _salida(tx) for tx in filas
    ]


@router.post(
    "/transacciones",
    summary="Crear una transacción",
    status_code=201,
    response_model=TransaccionOut,
    responses={422: {"model": ErrorEstandar, "description": "Datos inválidos (reglas de factura)."}},
)
def crear_transaccion(cuerpo: SeedItem, request: Request) -> TransaccionOut:
    tx = request.app.state.servicios.crear(cuerpo.model_dump())
    return _salida(tx)


@router.put(
    "/transacciones/{tx_id}",
    summary="Actualizar una transacción existente (reemplazo completo)",
    response_model=TransaccionOut,
    responses={
        404: {"model": ErrorEstandar, "description": "Transacción no encontrada."},
        422: {"model": ErrorEstandar, "description": "Datos inválidos (reglas de factura)."},
    },
)
def actualizar_transaccion(tx_id: int, cuerpo: SeedItem, request: Request) -> TransaccionOut:
    tx = request.app.state.servicios.actualizar(tx_id, cuerpo.model_dump())
    return _salida(tx)
