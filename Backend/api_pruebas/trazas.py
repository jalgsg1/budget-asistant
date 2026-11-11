# -*- coding: utf-8 -*-
"""
api_pruebas/trazas.py — Consulta de trazas del Pipeline en disco.

``agent.tracer.write_trace`` escribe ``{created_at}_{trace_id[:8]}.json`` con el
``trace_id`` completo dentro del JSON. No hay índice: se recorre el directorio.
Ninguna ruta se construye con el ``trace_id`` recibido; solo se compara contra
nombres listados. Nunca importa ``mcp``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Iterable, Union

from api_pruebas.errores import error_api, redactar

PATRON_TRACE_ID = re.compile(r"^[A-Za-z0-9-]{1,64}$")

_MSG_NO_ENCONTRADA = "Traza no encontrada."

RutaLike = Union[str, Path]
# Lector de directorio inyectable: devuelve los archivos ``*.json`` candidatos.
ListarDirectorio = Callable[[Path], Iterable[Path]]


def listar_json_directorio(directorio: Path) -> list[Path]:
    """Lector por defecto: archivos ``*.json`` regulares (no symlink), ordenados."""
    try:
        hijos = sorted(directorio.glob("*.json"), key=lambda p: p.name)
        hijos = [p for p in hijos if p.name != "summary.json"]
    except OSError:
        return []
    salida = []
    for p in hijos:
        try:
            if p.is_file() and not p.is_symlink():
                salida.append(p)
        except OSError:
            continue
    return salida


def directorios_trazas(
    traces_dir: RutaLike, batch_traces_dir: RutaLike | None
) -> list[Path]:
    """``traces_dir`` más cada hijo directo válido de ``batch_traces_dir``.

    Hijos: nombre ``^[A-Za-z0-9-]{1,64}$``, directorio real (no symlink) cuyo
    ``resolve()`` queda dentro de ``batch_traces_dir.resolve()``. Sin recursión.
    """
    dirs = [Path(traces_dir)]
    if batch_traces_dir is None:
        return dirs
    base = Path(batch_traces_dir)
    try:
        base_real = base.resolve()
        hijos = sorted(base.iterdir(), key=lambda p: p.name)
    except OSError:
        return dirs
    for hijo in hijos:
        try:
            if (
                PATRON_TRACE_ID.fullmatch(hijo.name)
                and hijo.is_dir()
                and not hijo.is_symlink()
                and hijo.resolve().is_relative_to(base_real)
            ):
                dirs.append(hijo)
        except (OSError, ValueError):
            continue
    return dirs


def _cargar(ruta: Path) -> dict | None:
    """Lee un JSON objeto; ``None`` si es ilegible, inválido o sin ``trace_id``."""
    try:
        with open(ruta, encoding="utf-8") as fh:
            datos = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(datos, dict) or not datos.get("trace_id"):
        return None
    return datos


def listar_trazas(
    traces_dir: RutaLike,
    batch_traces_dir: RutaLike | None,
    user_id: str,
    listar_directorio: ListarDirectorio = listar_json_directorio,
) -> list[dict[str, Any]]:
    """Resumen de las trazas del usuario, de la más reciente a la más antigua."""
    resumenes = []
    rutas = [
        r
        for d in directorios_trazas(traces_dir, batch_traces_dir)
        for r in listar_directorio(d)
        if Path(r).name != "summary.json"
    ]
    for ruta in rutas:
        datos = _cargar(Path(ruta))
        if datos is None or datos.get("user_id") != user_id:
            continue
        resumenes.append(
            {
                "trace_id": str(datos["trace_id"]),
                "created_at": str(datos.get("created_at") or ""),
                "status": str(datos.get("final_status") or ""),
            }
        )
    resumenes.sort(key=lambda r: r["created_at"], reverse=True)
    return redactar(resumenes)


def leer_traza(
    traces_dir: RutaLike,
    batch_traces_dir: RutaLike | None,
    user_id: str,
    trace_id: str,
    listar_directorio: ListarDirectorio = listar_json_directorio,
) -> dict[str, Any]:
    """Devuelve la traza completa (redactada) si existe y es del usuario."""
    if not isinstance(trace_id, str) or not PATRON_TRACE_ID.fullmatch(trace_id):
        raise error_api("INVALID_TRACE_ID", "Identificador de traza inválido.")

    sufijo = f"_{trace_id[:8]}.json"
    for d in directorios_trazas(traces_dir, batch_traces_dir):
        for ruta in listar_directorio(d):
            ruta = Path(ruta)
            if ruta.name == "summary.json" or not ruta.name.endswith(sufijo):
                continue
            datos = _cargar(ruta)
            if (
                datos is not None
                and datos.get("trace_id") == trace_id
                and datos.get("user_id") == user_id
            ):
                return redactar(datos)
    raise error_api("TRACE_NOT_FOUND", _MSG_NO_ENCONTRADA)
