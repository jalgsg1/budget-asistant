# -*- coding: utf-8 -*-
"""Procesador común de los baselines (Req. 9.3 a 9.9, 10.3 a 10.9, 11).

Una sola llamada multimodal al LLM con una única herramienta
``insertar_transaccion`` que escribe directo en SQLite. No hay validación
intermedia, ni confirmación de usuario, ni dependencia de ``ocr_mcp`` ni de
``finanzas_mcp.business``.
"""
from __future__ import annotations

import argparse
import base64
import mimetypes
import os
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Sequence

from baseline.bd_temporal import BDTemporal
from baseline.constantes import HERRAMIENTA_INSERTAR_NOMBRE
from baseline.llm import ClienteLlm, ConfigLlmError, RespuestaLlm, resolver_config_llm
from baseline.traza_comun import TrazaComun, escribir_traza

USER_ID_BASELINE = "baseline"
TIMEOUT_S = 60.0

HERRAMIENTA_INSERTAR: dict = {
    "name": HERRAMIENTA_INSERTAR_NOMBRE,
    "description": (
        "Inserta una transacción de gasto en la base de datos con los datos "
        "de la factura."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "comercio": {"type": "string"},
            "fecha": {"type": "string", "description": "YYYY-MM-DD"},
            "total": {"type": "number"},
            "moneda": {"type": "string"},
            "categoria": {"type": "string"},
            "subtotal": {"type": "number"},
            "iva": {"type": "number"},
            "descripcion": {"type": "string"},
        },
        "required": ["comercio", "fecha", "total", "moneda", "categoria"],
    },
}

_COLUMNAS = ("comercio", "fecha", "total", "moneda", "categoria",
             "subtotal", "iva", "descripcion")


@dataclass
class ResultadoBaseline:
    traza: TrazaComun
    indicacion_error: str | None  # tipo de excepción o "timeout"
    filas_nuevas: list[dict] = field(default_factory=list)


@dataclass
class ResultadoCorrida:
    resultados: list[ResultadoBaseline]
    ruta_bd: str | None  # solo si se pidió conservar la BD


class _Sesion:
    """Estado compartido entre el hilo principal y el trabajador de una factura."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.cancelado = threading.Event()
        self.confirmado = False  # algún COMMIT efectivo (protegido por lock)


def _mime(ruta: str) -> str:
    if ruta.lower().endswith(".pdf"):
        return "application/pdf"
    return mimetypes.guess_type(ruta)[0] or "image/jpeg"


def _insertar(ruta_bd: str, args: dict, sesion: _Sesion) -> None:
    """BEGIN/INSERT/COMMIT en conexión propia; ROLLBACK ante cualquier error."""
    conn = sqlite3.connect(ruta_bd, isolation_level=None)
    try:
        conn.execute("BEGIN")
        try:
            valores = [args.get(c) for c in _COLUMNAS]
            conn.execute(
                "INSERT INTO transactions (user_id, comercio, fecha, total, moneda, "
                "categoria, subtotal, iva, descripcion, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [USER_ID_BASELINE, *valores, datetime.now(timezone.utc).isoformat()],
            )
            with sesion.lock:
                if sesion.cancelado.is_set():
                    conn.execute("ROLLBACK")
                    raise TimeoutError("cancelado")
                conn.execute("COMMIT")
                sesion.confirmado = True
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()


class ProcesadorBaseline:
    def __init__(
        self,
        nombre: str,
        system_prompt: str,
        cliente: ClienteLlm,
        bd: BDTemporal,
        dir_trazas: str | None,
        timeout_s: float = TIMEOUT_S,
        reloj: Callable[[], float] = time.monotonic,
    ) -> None:
        self.nombre = nombre
        self.system_prompt = system_prompt
        self.cliente = cliente
        self.bd = bd
        self.dir_trazas = dir_trazas
        self.timeout_s = timeout_s
        self.reloj = reloj

    def _trabajo(self, ruta_imagen: str, sesion: _Sesion, acum: dict) -> str:
        with open(ruta_imagen, "rb") as fh:
            b64 = base64.b64encode(fh.read()).decode("ascii")
        resp: RespuestaLlm = self.cliente.invocar(
            self.system_prompt, b64, _mime(ruta_imagen), HERRAMIENTA_INSERTAR
        )
        acum["entrada"] = int(resp.tokens_entrada)
        acum["salida"] = int(resp.tokens_salida)
        llamadas = [c for c in resp.llamadas_herramienta
                    if c.get("nombre") == HERRAMIENTA_INSERTAR_NOMBRE]
        if not llamadas:
            return "rechazada"
        for c in llamadas:
            _insertar(self.bd.ruta, dict(c.get("args") or {}), sesion)
        return "registrada"

    def procesar(self, ruta_imagen: str) -> ResultadoBaseline:
        inicio = self.reloj()
        ids_previos = {f["id"] for f in self.bd.filas()}
        sesion = _Sesion()
        acum: dict = {"entrada": 0, "salida": 0}
        estado, indicacion = "error", None
        pool = ThreadPoolExecutor(max_workers=1)
        futuro = pool.submit(self._trabajo, ruta_imagen, sesion, acum)
        try:
            try:
                estado = futuro.result(timeout=self.timeout_s)
            except FutureTimeout:
                with sesion.lock:
                    terminado_ok = sesion.confirmado
                    if not terminado_ok:
                        sesion.cancelado.set()
                if terminado_ok:
                    try:
                        estado = futuro.result(timeout=5)
                    except Exception as exc:  # noqa: BLE001
                        indicacion = type(exc).__name__
                else:
                    indicacion = "timeout"
            except Exception as exc:  # noqa: BLE001
                indicacion = type(exc).__name__
        finally:
            pool.shutdown(wait=False)
        if indicacion is not None:
            estado = "error"
            print(f"[baseline:{self.nombre}] {ruta_imagen}: error {indicacion}",
                  file=sys.stderr)
        filas = [f for f in self.bd.filas() if f["id"] not in ids_previos]
        duracion_ms = max(0.0, (self.reloj() - inicio) * 1000.0)
        traza = TrazaComun(
            sistema=self.nombre,
            ruta_factura=str(ruta_imagen),
            tokens_entrada=max(0, acum["entrada"]),
            tokens_salida=max(0, acum["salida"]),
            duracion_ms=duracion_ms,
            estado_final=estado,
            registro_en_bd=bool(filas),
        )
        if self.dir_trazas:
            escribir_traza(traza, self.dir_trazas)
        return ResultadoBaseline(traza=traza, indicacion_error=indicacion, filas_nuevas=filas)


def correr(
    nombre: str,
    system_prompt: str,
    cliente: ClienteLlm,
    rutas: Sequence[str],
    dir_trazas: str | None,
    conservar_bd: bool = False,
) -> ResultadoCorrida:
    """Crea una BD temporal, procesa las facturas en orden y la elimina al final."""
    with BDTemporal(conservar=conservar_bd) as bd:
        proc = ProcesadorBaseline(nombre, system_prompt, cliente, bd, dir_trazas)
        resultados = [proc.procesar(r) for r in rutas]
        return ResultadoCorrida(resultados, bd.ruta if conservar_bd else None)


def main_baseline(nombre: str, system_prompt: str, argv: Sequence[str] | None = None) -> int:
    """Uso manual: ``python -m baseline.<modulo> <imágenes...>``."""
    ap = argparse.ArgumentParser(prog=nombre)
    ap.add_argument("imagenes", nargs="+")
    ap.add_argument("--trazas", default=None, help="Directorio de trazas JSON")
    ap.add_argument("--conservar-bd", action="store_true")
    ns = ap.parse_args(argv)
    try:
        config = resolver_config_llm(os.environ)
    except ConfigLlmError as exc:
        print(f"Error de configuración: {exc}", file=sys.stderr)
        return 2
    from baseline.llm import ClienteLangChain

    cliente = ClienteLangChain(config)
    corrida = correr(nombre, system_prompt, cliente, ns.imagenes, ns.trazas, ns.conservar_bd)
    for r in corrida.resultados:
        print(f"{r.traza.ruta_factura}: {r.traza.estado_final}")
    if corrida.ruta_bd:
        print(f"BD conservada en: {corrida.ruta_bd}")
    return 0
