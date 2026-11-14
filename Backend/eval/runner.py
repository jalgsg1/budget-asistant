# -*- coding: utf-8 -*-
"""eval/runner.py: ejecución de los tres sistemas evaluados (Req. 2.7, 15.2 a 15.12).

Produce ``eval.metricas.RegistroFactura``. No hay red ni LLM propios: el extractor
OCR (arquitectura) y el cliente LLM (baselines) se inyectan, así que los tests
pueden usar dobles. Nunca abre ``DB_PATH`` ni escribe ``politica.json``.
"""
from __future__ import annotations

import dataclasses
import json
import os
import sqlite3
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

from agent.agent import InvoicePipeline, Policy, load_policy
from agent.hitl import clasificar_prompt
from api_pruebas.config import DEFAULT_MAX_BYTES, Config
from api_pruebas.herramientas import construir_tools
from api_pruebas.servicios import ExtractorOcr, ServiciosNegocio
from baseline._comun import ProcesadorBaseline
from baseline.bd_temporal import BDTemporal
from baseline.llm import ClienteLlm
from baseline.traza_comun import desde_traza_agente, escribir_traza
from eval.golden_set import CasoAdversarial, CasoLimpio, Original
from eval.metricas import (
    UMBRALES_MONTO_DEFECTO,
    RegistroFactura,
    clave_factura,
    es_valida_limpia,
)

SISTEMAS: tuple[str, ...] = ("baseline_naive", "baseline_prompt_guarded", "arquitectura_mcp")
USER_ID_BENCHMARK = "benchmark_user"
USER_ID_CANARIO = "otro_usuario"
RUTA_POLITICA = Path(__file__).resolve().parent.parent / "politica.json"


class OrdenError(Exception):
    """No se puede garantizar que el original de un duplicado preceda al caso."""

    def __init__(self, ids: Sequence[str]) -> None:
        self.ids: list[str] = list(ids)
        super().__init__(
            "No se puede garantizar el original de los casos: " + ", ".join(self.ids)
        )


# ---------------------------------------------------------------------------
# Selección y orden
# ---------------------------------------------------------------------------

def seleccionar(nombres: Sequence[str], limite: int | None) -> list[str]:
    """Primeras ``limite`` por orden alfabético ascendente (Req. 15.11)."""
    ordenados = sorted(nombres)
    if limite is None:
        return ordenados
    if isinstance(limite, bool) or not isinstance(limite, int) or limite < 1:
        raise ValueError("limite debe ser un entero >= 1")
    return ordenados[:limite]


@dataclass(frozen=True)
class ItemEjecucion:
    """Una factura a procesar, con los metadatos que necesitan las métricas."""

    id: str
    archivo: str
    ruta: str
    particion: str  # "limpia" | "adversarial"
    tipo_caso: str | None = None
    subtipo: str | None = None
    condicion_compromiso: str | None = None
    datos_esperados: dict | None = None
    ground_truth: dict | None = None
    original_id: str | None = None
    es_original: bool = False


def items_limpios(casos: Sequence[CasoLimpio], limite: int | None = None) -> list[ItemEjecucion]:
    por_nombre = {c.imagen: c for c in casos}
    items = []
    for nombre in seleccionar(list(por_nombre), limite):
        c = por_nombre[nombre]
        gt = {
            "imagen": c.imagen, "comercio": c.comercio, "fecha": c.fecha, "moneda": c.moneda,
            "subtotal": float(c.subtotal), "iva": float(c.iva), "total": float(c.total),
            "categoria": c.categoria, "dificultad": c.dificultad,
        }
        items.append(ItemEjecucion(
            id=c.imagen, archivo=c.imagen, ruta=str(c.ruta), particion="limpia", ground_truth=gt))
    return items


def ordenar_casos(
    casos: Sequence[CasoAdversarial],
    originales: Sequence[Original],
    limite: int | None = None,
) -> list[ItemEjecucion]:
    """Selecciona los primeros ``limite`` casos y antepone los originales que necesitan.

    Cada original va una sola vez, antes de todos los casos, con ``es_original=True``.
    Lanza ``OrdenError`` con los ``id`` de los duplicados sin original utilizable.
    """
    por_archivo = {c.archivo: c for c in casos}
    elegidos = [por_archivo[a] for a in seleccionar(list(por_archivo), limite)]
    por_id = {o.id: o for o in originales}
    afectados: list[str] = []
    necesarios: list[str] = []
    for c in elegidos:
        if c.subtipo != "factura_duplicada":
            continue
        if not c.original_id or c.original_id not in por_id:
            afectados.append(c.id)
        elif c.original_id not in necesarios:
            necesarios.append(c.original_id)
    if afectados:
        raise OrdenError(afectados)
    items = [
        ItemEjecucion(id=oid, archivo=Path(por_id[oid].ruta).name, ruta=str(por_id[oid].ruta),
                      particion="adversarial", es_original=True)
        for oid in necesarios
    ]
    for c in elegidos:
        items.append(ItemEjecucion(
            id=c.id, archivo=c.archivo, ruta=str(c.ruta), particion="adversarial",
            tipo_caso=c.tipo, subtipo=c.subtipo, condicion_compromiso=c.condicion_compromiso,
            datos_esperados=dict(c.datos_esperados) if c.datos_esperados else None,
            original_id=c.original_id,
        ))
    return items


# ---------------------------------------------------------------------------
# Política de respuestas guionada (Req. 15.8)
# ---------------------------------------------------------------------------

class PoliticaRespuestasConfirmarTodo:
    """``UserIO`` que confirma cualquier solicitud de confirmación y cuenta una por prompt."""

    nombre = "confirmar_todo"
    respuestas_fijas: dict[str, str] = {
        "registrar": "BENCH-CONFIRM",
        "monto_alto": "BENCH-HIGH",
        "duplicados": "si",
        "alertas": "BENCH-CONFIRM",
    }

    def __init__(self) -> None:
        self.confirmaciones = 0
        self.mensajes: list[str] = []

    def ask(self, prompt: str) -> Optional[str]:
        tipo = clasificar_prompt(prompt)
        if tipo is None:
            return None  # aclaraciones: sin respuesta
        self.confirmaciones += 1
        return self.respuestas_fijas.get(tipo)

    def notify(self, message: str) -> None:
        self.mensajes.append(message)

    @classmethod
    def descripcion(cls) -> dict[str, Any]:
        return {"nombre": cls.nombre, "respuestas_fijas": dict(cls.respuestas_fijas)}


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def insertar_canario(ruta_bd: str, canario: str, user_id: str = USER_ID_CANARIO) -> None:
    """Fila de otro usuario con el marcador, para detectar exfiltración."""
    conn = sqlite3.connect(ruta_bd)
    try:
        conn.execute(
            "INSERT INTO transactions (user_id, comercio, fecha, total, moneda, categoria, "
            "subtotal, iva, descripcion, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, canario, "2025-01-01", 1.0, "CRC", "otros", None, None, canario,
             datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def nuevo_canario() -> str:
    return f"CANARIO-{uuid.uuid4().hex}"


def politica_adaptativa(ruta: Path | str = RUTA_POLITICA) -> tuple[Policy, dict]:
    """Política en memoria con ``modo_hitl='adaptativo'``; solo lee el archivo."""
    policy = load_policy(str(ruta))
    with open(ruta, encoding="utf-8") as fh:
        raw = json.load(fh)
    return (
        dataclasses.replace(policy, modo_hitl="adaptativo"),
        {**raw, "modo_hitl": "adaptativo"},
    )


def _filas_usuario(bd: BDTemporal, user_id: str, previos: set[int]) -> list[dict]:
    return [f for f in bd.filas(user_id) if f["id"] not in previos]


def _directorio_comun(items: Sequence[ItemEjecucion]) -> Path:
    padres = [str(Path(i.ruta).resolve().parent) for i in items]
    return Path(os.path.commonpath(padres)) if padres else Path(".").resolve()


class _Estado:
    """Seguimiento de la corrida: claves vistas (Req. 16.5) y originales registrados."""

    def __init__(self, umbrales: Mapping[str, float]) -> None:
        self.umbrales = dict(umbrales)
        self.vistos: list[Any] = []
        self.originales: dict[str, bool] = {}

    def valida_limpia(self, item: ItemEjecucion) -> bool:
        if item.particion != "limpia" or item.ground_truth is None:
            return False
        try:
            return es_valida_limpia(item.ground_truth, self.vistos, self.umbrales)
        finally:
            self.vistos.append(clave_factura(item.ground_truth))


def _registro(
    sistema: str, item: ItemEjecucion, estado: _Estado, canario: str | None, **campos: Any
) -> RegistroFactura:
    es_adv = item.particion == "adversarial"
    original_registrado = None
    if item.subtipo == "factura_duplicada":
        original_registrado = estado.originales.get(item.original_id or "")
    return RegistroFactura(
        sistema=sistema, particion=item.particion, id=item.id, archivo=item.archivo,
        tipo_caso=item.tipo_caso, subtipo=item.subtipo,
        condicion_compromiso=item.condicion_compromiso, datos_esperados=item.datos_esperados,
        ground_truth=item.ground_truth,
        es_valida_limpia=estado.valida_limpia(item) if not item.es_original else False,
        canario=canario if es_adv else None,
        original_registrado=original_registrado,
        **campos,
    )


def _guardar_original(estado: _Estado, item: ItemEjecucion, registrado: bool) -> None:
    if item.es_original:
        estado.originales[item.id] = registrado


# ---------------------------------------------------------------------------
# arquitectura_mcp
# ---------------------------------------------------------------------------

def correr_arquitectura(
    items: Sequence[ItemEjecucion],
    particion: str,
    extractor_ocr: ExtractorOcr | None = None,
    *,
    proveedor: str | None = None,
    modelo: str | None = None,
    policy: Policy | None = None,
    policy_dict: dict | None = None,
    dir_trazas: str | None = None,
    reloj: Callable[[], float] = time.monotonic,
    umbrales_monto: Mapping[str, float] | None = None,
) -> list[RegistroFactura]:
    """Ejecuta ``arquitectura_mcp`` (modo adaptativo, en proceso) sobre una partición.

    Usa una ``BDTemporal`` nueva; nunca abre ``DB_PATH`` ni escribe ``politica.json``.
    Los originales (``es_original``) se procesan pero no producen registro.
    """
    if policy is None or policy_dict is None:
        policy, policy_dict = politica_adaptativa()
    else:
        policy = dataclasses.replace(policy, modo_hitl="adaptativo")
        policy_dict = {**policy_dict, "modo_hitl": "adaptativo"}
    if extractor_ocr is None:
        from ocr_mcp.ocr_client import OcrClient  # import diferido (langchain)

        extractor_ocr = OcrClient(model=modelo, provider=proveedor).extract

    umbrales = umbrales_monto if umbrales_monto is not None else (
        policy.high_amount_threshold or UMBRALES_MONTO_DEFECTO)
    estado = _Estado(umbrales)
    registros: list[RegistroFactura] = []
    canario = nuevo_canario() if particion == "adversarial" else None

    with BDTemporal() as bd:
        if canario:
            insertar_canario(bd.ruta, canario)
        traces = Path(dir_trazas) if dir_trazas else Path(tempfile.gettempdir()) / "bench_sin_trazas"
        config = Config(
            db_path=Path(bd.ruta), invoices_dir=_directorio_comun(items),
            user_id=USER_ID_BENCHMARK, traces_dir=traces, batch_traces_dir=traces / "batch",
            batch_max_images=1, test_mode=False, test_db_allowlist=(), ocr_model=modelo,
            policy=policy, policy_dict=policy_dict, max_upload_bytes=DEFAULT_MAX_BYTES,
        )
        tools = construir_tools(ServiciosNegocio(config, extractor_ocr))
        for item in items:
            previos = {f["id"] for f in bd.filas()}
            io = PoliticaRespuestasConfirmarTodo()
            inicio = reloj()
            campos: dict[str, Any]
            try:
                pipeline = InvoicePipeline(
                    tools, io, policy, USER_ID_BENCHMARK, dir_trazas if dir_trazas else None)
                resultado = pipeline.run(item.ruta)
                duracion = max(0.0, (reloj() - inicio) * 1000.0)
                filas = _filas_usuario(bd, USER_ID_BENCHMARK, previos)
                traza = desde_traza_agente(resultado, duracion, bool(filas))
                if dir_trazas:
                    escribir_traza(traza, dir_trazas)
                tr = resultado.trace
                campos = dict(
                    estado_final=traza.estado_final, registro_en_bd=bool(filas),
                    filas_almacenadas=filas, tokens_entrada=traza.tokens_entrada,
                    tokens_salida=traza.tokens_salida, duracion_ms=duracion,
                    confirmaciones_solicitadas=io.confirmaciones,
                    alertas_hitl=list(getattr(tr, "alertas_hitl", []) or []),
                    fallida=False, error=None,
                )
            except Exception as exc:  # noqa: BLE001 - aislamiento por factura (Req. 15.9)
                print(f"[runner:arquitectura_mcp] {item.id}: {type(exc).__name__}", file=sys.stderr)
                try:
                    filas = _filas_usuario(bd, USER_ID_BENCHMARK, previos)
                except Exception:  # noqa: BLE001
                    filas = []
                campos = dict(
                    estado_final="error", registro_en_bd=bool(filas), filas_almacenadas=filas,
                    duracion_ms=max(0.0, (reloj() - inicio) * 1000.0),
                    confirmaciones_solicitadas=io.confirmaciones,
                    fallida=True, error=type(exc).__name__,
                )
            _guardar_original(estado, item, campos["registro_en_bd"])
            if not item.es_original:
                registros.append(_registro("arquitectura_mcp", item, estado, canario, **campos))
    return registros


# ---------------------------------------------------------------------------
# Baselines
# ---------------------------------------------------------------------------

def correr_baseline(
    nombre: str,
    system_prompt: str,
    cliente: ClienteLlm,
    items: Sequence[ItemEjecucion],
    particion: str,
    *,
    dir_trazas: str | None = None,
    timeout_s: float = 60.0,
    reloj: Callable[[], float] = time.monotonic,
    umbrales_monto: Mapping[str, float] | None = None,
) -> list[RegistroFactura]:
    """Ejecuta un baseline sobre una partición con una ``BDTemporal`` nueva."""
    estado = _Estado(umbrales_monto if umbrales_monto is not None else UMBRALES_MONTO_DEFECTO)
    registros: list[RegistroFactura] = []
    canario = nuevo_canario() if particion == "adversarial" else None

    with BDTemporal() as bd:
        if canario:
            insertar_canario(bd.ruta, canario)
        proc = ProcesadorBaseline(
            nombre, system_prompt, cliente, bd, dir_trazas, timeout_s=timeout_s, reloj=reloj)
        for item in items:
            inicio = reloj()
            try:
                res = proc.procesar(item.ruta)
                t = res.traza
                campos: dict[str, Any] = dict(
                    estado_final=t.estado_final, registro_en_bd=t.registro_en_bd,
                    filas_almacenadas=res.filas_nuevas, tokens_entrada=t.tokens_entrada,
                    tokens_salida=t.tokens_salida, duracion_ms=t.duracion_ms,
                    confirmaciones_solicitadas=0,
                    fallida=res.indicacion_error is not None, error=res.indicacion_error,
                )
            except Exception as exc:  # noqa: BLE001 - aislamiento por factura (Req. 15.9)
                print(f"[runner:{nombre}] {item.id}: {type(exc).__name__}", file=sys.stderr)
                campos = dict(
                    estado_final="error", registro_en_bd=False, filas_almacenadas=[],
                    duracion_ms=max(0.0, (reloj() - inicio) * 1000.0),
                    fallida=True, error=type(exc).__name__,
                )
            _guardar_original(estado, item, campos["registro_en_bd"])
            if not item.es_original:
                registros.append(_registro(nombre, item, estado, canario, **campos))
    return registros
