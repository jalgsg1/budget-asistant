# -*- coding: utf-8 -*-
"""Carga y validación (solo lectura) del Golden Set.

Los validadores nunca abren archivos del Golden Set para escritura y reportan
todos los ofensivos, no solo el primero (Req. 12.10, 13.8, 14.8).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Collection, Mapping, Sequence

from finanzas_mcp.business.categorias import CLOSED_CATEGORY_LIST

from eval.constantes import (  # noqa: F401
    CAMPOS_DECIMALES,
    CAMPOS_GT,
    CONDICIONES_COMPROMISO,
    DIFICULTADES,
    EXTENSIONES,
    MIN_IMAGENES_POR_VECTOR,
    MIN_VECTORES,
    MINIMO_POR_SUBTIPO_INTEGRIDAD,
    MINIMOS_DIFICULTAD,
    SUBTIPOS_INTEGRIDAD,
    TIPOS_CASO,
    TOTAL_DIFICILES,
    TOTAL_IMAGENES,
    TOTAL_LIMPIA,
    VARIANTES_FECHA,
)

_RE_FECHA = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RE_MONEDA = re.compile(r"^[A-Z]{3}$")


@dataclass(frozen=True)
class ErrorValidacion:
    nombre: str      # archivo, entrada o id ofensivo
    motivo: str


@dataclass(frozen=True)
class CasoLimpio:
    imagen: str
    ruta: Path
    comercio: str
    fecha: str
    moneda: str
    total: Decimal
    categoria: str
    dificultad: str


@dataclass(frozen=True)
class Original:
    id: str
    ruta: Path


@dataclass(frozen=True)
class CasoAdversarial:
    id: str
    archivo: str
    ruta: Path
    tipo: str
    subtipo: str
    resultado_esperado: str
    original_id: str | None = None
    variante: str | None = None
    vector: str | None = None
    texto_inyectado: str | None = None
    condicion_compromiso: str | None = None
    datos_esperados: Mapping[str, Any] = field(default_factory=dict)


# ----------------------------------------------------------------- utilidades

def _leer_json(ruta: Path) -> tuple[Any, str | None]:
    try:
        with open(ruta, "r", encoding="utf-8") as fh:
            return json.load(fh), None
    except FileNotFoundError:
        return None, "archivo inexistente"
    except (OSError, ValueError) as exc:
        return None, f"no se puede leer: {exc}"


def _decimal_valido(valor: Any) -> bool:
    if isinstance(valor, bool) or not isinstance(valor, (int, float, str)):
        return False
    try:
        d = Decimal(str(valor).strip())
    except (InvalidOperation, ValueError):
        return False
    if not d.is_finite() or d < 0:
        return False
    return d.as_tuple().exponent >= -2  # type: ignore[operator]


def _fecha_real(valor: Any) -> bool:
    if not isinstance(valor, str) or not _RE_FECHA.match(valor):
        return False
    try:
        date.fromisoformat(valor)
    except ValueError:
        return False
    return True


def _no_vacio(valor: Any) -> bool:
    return isinstance(valor, str) and bool(valor.strip())


def _imagenes_en(directorio: Path) -> list[str]:
    if not directorio.is_dir():
        return []
    return sorted(p.name for p in directorio.iterdir() if p.is_file() and p.suffix.lower() in EXTENSIONES)


# ------------------------------------------------------------ partición limpia

def validar_ground_truth(entradas: Sequence[Mapping[str, Any]], imagenes: Collection[str]) -> list[ErrorValidacion]:
    """Valida formato, unicidad y correspondencia 1:1 entre entradas e imágenes (Req. 12.3, 12.4, 12.9)."""
    errores: list[ErrorValidacion] = []
    vistos: dict[str, int] = {}
    for idx, e in enumerate(entradas):
        if not isinstance(e, Mapping):
            errores.append(ErrorValidacion(f"entrada[{idx}]", "la entrada no es un objeto"))
            continue
        img = e.get("imagen")
        nombre = Path(img).name if _no_vacio(img) else f"entrada[{idx}]"
        if not _no_vacio(img):
            errores.append(ErrorValidacion(nombre, "campo 'imagen' ausente o vacío"))
        else:
            vistos[nombre] = vistos.get(nombre, 0) + 1
            if nombre not in imagenes:
                errores.append(ErrorValidacion(nombre, "la entrada referencia una imagen inexistente"))
        for campo in CAMPOS_GT[1:]:
            if campo not in e or e[campo] is None or e[campo] == "":
                errores.append(ErrorValidacion(nombre, f"campo requerido ausente o vacío: {campo}"))
        com = e.get("comercio")
        if _no_vacio(com) and len(com) > 100:
            errores.append(ErrorValidacion(nombre, "comercio excede 100 caracteres"))
        if e.get("fecha") not in (None, "") and not _fecha_real(e.get("fecha")):
            errores.append(ErrorValidacion(nombre, "fecha inválida (se espera YYYY-MM-DD real)"))
        mon = e.get("moneda")
        if mon not in (None, "") and not (isinstance(mon, str) and _RE_MONEDA.match(mon)):
            errores.append(ErrorValidacion(nombre, "moneda inválida (3 letras mayúsculas)"))
        for campo in CAMPOS_DECIMALES:
            if e.get(campo) not in (None, "") and not _decimal_valido(e.get(campo)):
                errores.append(ErrorValidacion(nombre, f"{campo} debe ser decimal no negativo con 2 decimales"))
        cat = e.get("categoria")
        if cat not in (None, "") and cat not in CLOSED_CATEGORY_LIST:
            errores.append(ErrorValidacion(nombre, "categoria fuera del catálogo cerrado"))
        dif = e.get("dificultad")
        if dif not in (None, "") and dif not in DIFICULTADES:
            errores.append(ErrorValidacion(nombre, "dificultad inválida"))
    for nombre, n in vistos.items():
        if n > 1:
            errores.append(ErrorValidacion(nombre, f"la imagen tiene {n} entradas (debe tener exactamente una)"))
    for img in sorted(set(imagenes) - set(vistos)):
        errores.append(ErrorValidacion(img, "la imagen no tiene entrada en ground_truth.json"))
    return errores


def validar_particion_limpia(directorio: Path) -> list[ErrorValidacion]:
    """Valida la partición limpia completa. Solo lectura."""
    directorio = Path(directorio)
    errores: list[ErrorValidacion] = []
    imagenes = _imagenes_en(directorio / "images")
    if not imagenes:
        errores.append(ErrorValidacion("images", "no hay imágenes en la partición limpia"))

    gt, err = _leer_json(directorio / "ground_truth.json")
    entradas: list[Mapping[str, Any]] = []
    if err:
        errores.append(ErrorValidacion("ground_truth.json", err))
    elif not isinstance(gt, list):
        errores.append(ErrorValidacion("ground_truth.json", "se esperaba una lista de objetos"))
    else:
        entradas = gt
        errores.extend(validar_ground_truth(entradas, set(imagenes)))

    if len(imagenes) != TOTAL_IMAGENES:
        errores.append(ErrorValidacion("images", f"se esperaban {TOTAL_IMAGENES} imágenes, hay {len(imagenes)}"))

    difs = [e.get("dificultad") for e in entradas if isinstance(e, Mapping)]
    n_limpia = sum(1 for d in difs if d == "limpia")
    n_dificil = sum(1 for d in difs if d in MINIMOS_DIFICULTAD)
    if difs and n_limpia != TOTAL_LIMPIA:
        errores.append(ErrorValidacion("ground_truth.json", f"se esperaban {TOTAL_LIMPIA} 'limpia', hay {n_limpia}"))
    if difs and n_dificil != TOTAL_DIFICILES:
        errores.append(ErrorValidacion(
            "ground_truth.json", f"se esperaban {TOTAL_DIFICILES} con dificultad distinta de 'limpia', hay {n_dificil}"))
    for clase, minimo in MINIMOS_DIFICULTAD.items():
        n = sum(1 for d in difs if d == clase)
        if difs and n < minimo:
            errores.append(ErrorValidacion("ground_truth.json", f"clase '{clase}': mínimo {minimo}, hay {n}"))

    # Dos anotaciones independientes que cubran las mismas imágenes (Req. 12.5)
    cubiertas: list[set[str]] = []
    for i in (1, 2):
        nombre = f"anotaciones_anotador_{i}.json"
        datos, err = _leer_json(directorio / nombre)
        if err:
            errores.append(ErrorValidacion(nombre, err))
            continue
        if not isinstance(datos, list):
            errores.append(ErrorValidacion(nombre, "se esperaba una lista de objetos"))
            continue
        nombres = [Path(str(d.get("imagen"))).name for d in datos if isinstance(d, Mapping) and d.get("imagen")]
        if len(nombres) != len(datos) or len(set(nombres)) != len(nombres):
            errores.append(ErrorValidacion(nombre, "entradas sin imagen o con imagen repetida"))
        cubiertas.append(set(nombres))
    esperadas = set(imagenes)
    for i, c in enumerate(cubiertas, start=1):
        if c != esperadas:
            faltan = sorted(esperadas - c)
            sobran = sorted(c - esperadas)
            errores.append(ErrorValidacion(
                f"anotaciones_anotador_{i}.json", f"no cubre las mismas imágenes (faltan {faltan}, sobran {sobran})"))
    return errores


def cargar_particion_limpia(directorio: Path) -> list[CasoLimpio]:
    """Carga los casos limpios ordenados por nombre de archivo. Asume validación previa."""
    directorio = Path(directorio)
    gt, err = _leer_json(directorio / "ground_truth.json")
    if err or not isinstance(gt, list):
        raise ValueError(f"ground_truth.json inválido: {err or 'no es una lista'}")
    casos = []
    for e in gt:
        nombre = Path(e["imagen"]).name
        casos.append(CasoLimpio(
            imagen=nombre, ruta=directorio / "images" / nombre,
            comercio=e["comercio"], fecha=e["fecha"], moneda=e["moneda"],
            total=Decimal(str(e["total"])),
            categoria=e["categoria"], dificultad=e["dificultad"],
        ))
    return sorted(casos, key=lambda c: c.imagen)


# ------------------------------------------------------- partición adversarial

def _archivo_valido(directorio: Path, archivo: Any) -> str | None:
    """None si el archivo existe, no está vacío y queda dentro del directorio; si no, el motivo."""
    if not _no_vacio(archivo):
        return "campo 'archivo' ausente o vacío"
    try:
        base = directorio.resolve()
        ruta = (directorio / archivo).resolve()
        ruta.relative_to(base)
    except (ValueError, OSError):
        return "el archivo queda fuera de la partición adversarial"
    if not ruta.is_file():
        return f"el archivo no existe: {archivo}"
    try:
        if ruta.stat().st_size == 0:
            return f"el archivo está vacío: {archivo}"
    except OSError:
        return f"el archivo no es legible: {archivo}"
    return None


def validar_manifiesto(manifiesto: Mapping[str, Any], directorio: Path) -> list[ErrorValidacion]:
    """Valida el manifiesto adversarial (Req. 13.1-13.8, 14.1-14.4, 14.6, 14.8). Solo lectura."""
    directorio = Path(directorio)
    errores: list[ErrorValidacion] = []
    if not isinstance(manifiesto, Mapping) or not isinstance(manifiesto.get("casos"), list):
        return [ErrorValidacion("adversarial_manifest.json", "se esperaba un objeto con la lista 'casos'")]

    originales = manifiesto.get("originales") or []
    ids_orig: set[str] = set()
    if not isinstance(originales, list):
        errores.append(ErrorValidacion("originales", "se esperaba una lista"))
        originales = []
    for idx, o in enumerate(originales):
        oid = o.get("id") if isinstance(o, Mapping) else None
        nombre = oid if _no_vacio(oid) else f"originales[{idx}]"
        if not isinstance(o, Mapping) or not _no_vacio(oid):
            errores.append(ErrorValidacion(nombre, "original sin 'id'"))
            continue
        if oid in ids_orig:
            errores.append(ErrorValidacion(nombre, "id de original repetido"))
        ids_orig.add(oid)
        motivo = _archivo_valido(directorio, o.get("archivo"))
        if motivo:
            errores.append(ErrorValidacion(nombre, motivo))

    ids_vistos: set[str] = set()
    por_subtipo: dict[str, int] = {}
    variantes: set[str] = set()
    imagenes_por_vector: dict[str, int] = {}
    condiciones: set[str] = set()

    for idx, c in enumerate(manifiesto["casos"]):
        if not isinstance(c, Mapping):
            errores.append(ErrorValidacion(f"casos[{idx}]", "el caso no es un objeto"))
            continue
        cid = c.get("id")
        nombre = cid if _no_vacio(cid) else f"casos[{idx}]"
        for campo in ("id", "archivo", "tipo", "subtipo", "resultado_esperado"):
            if not _no_vacio(c.get(campo)):
                errores.append(ErrorValidacion(nombre, f"campo requerido ausente o vacío: {campo}"))
        if _no_vacio(cid):
            if cid in ids_vistos:
                errores.append(ErrorValidacion(nombre, "id repetido en el manifiesto"))
            ids_vistos.add(cid)
        if _no_vacio(c.get("archivo")):
            motivo = _archivo_valido(directorio, c.get("archivo"))
            if motivo:
                errores.append(ErrorValidacion(nombre, motivo))

        tipo, subtipo = c.get("tipo"), c.get("subtipo")
        if _no_vacio(tipo) and tipo not in TIPOS_CASO:
            errores.append(ErrorValidacion(nombre, f"tipo inválido: {tipo}"))

        if tipo == "integridad":
            if c.get("resultado_esperado") not in (None, "") and c.get("resultado_esperado") != "no_registrar":
                errores.append(ErrorValidacion(nombre, "resultado_esperado debe ser 'no_registrar'"))
            if _no_vacio(subtipo):
                if subtipo not in SUBTIPOS_INTEGRIDAD:
                    errores.append(ErrorValidacion(nombre, f"subtipo de integridad inválido: {subtipo}"))
                else:
                    por_subtipo[subtipo] = por_subtipo.get(subtipo, 0) + 1
            if subtipo == "fecha_invalida":
                var = c.get("variante")
                if var in VARIANTES_FECHA:
                    variantes.add(var)
                elif var is not None:
                    errores.append(ErrorValidacion(nombre, f"variante de fecha inválida: {var}"))
            if subtipo == "factura_duplicada":
                oid = c.get("original_id")
                if not _no_vacio(oid):
                    errores.append(ErrorValidacion(nombre, "duplicado sin 'original_id'"))
                elif oid not in ids_orig:
                    errores.append(ErrorValidacion(nombre, f"el original '{oid}' no existe en 'originales'"))
        elif tipo == "inyeccion":
            if c.get("resultado_esperado") not in (None, "") and c.get("resultado_esperado") != "no_comprometer":
                errores.append(ErrorValidacion(nombre, "resultado_esperado debe ser 'no_comprometer'"))
            vector = c.get("vector")
            if not _no_vacio(vector):
                errores.append(ErrorValidacion(nombre, "inyección sin 'vector'"))
            else:
                imagenes_por_vector[vector] = imagenes_por_vector.get(vector, 0) + 1
            if not _no_vacio(c.get("texto_inyectado")):
                errores.append(ErrorValidacion(nombre, "inyección sin 'texto_inyectado'"))
            cond = c.get("condicion_compromiso")
            if cond not in CONDICIONES_COMPROMISO:
                errores.append(ErrorValidacion(
                    nombre, f"condicion_compromiso debe ser una de {', '.join(CONDICIONES_COMPROMISO)}"))
            else:
                condiciones.add(cond)
            if not isinstance(c.get("datos_esperados"), Mapping) or not c.get("datos_esperados"):
                errores.append(ErrorValidacion(nombre, "inyección sin 'datos_esperados'"))

    # Mínimos globales (integridad)
    for sub in SUBTIPOS_INTEGRIDAD:
        n = por_subtipo.get(sub, 0)
        if n < MINIMO_POR_SUBTIPO_INTEGRIDAD:
            errores.append(ErrorValidacion(sub, f"mínimo {MINIMO_POR_SUBTIPO_INTEGRIDAD} casos, hay {n}"))
    for var in VARIANTES_FECHA:
        if var not in variantes:
            errores.append(ErrorValidacion("fecha_invalida", f"falta al menos un caso con variante '{var}'"))

    # Mínimos globales (inyección)
    if len(imagenes_por_vector) < MIN_VECTORES:
        errores.append(ErrorValidacion(
            "vectores", f"mínimo {MIN_VECTORES} vectores distintos, hay {len(imagenes_por_vector)}"))
    for vec, n in sorted(imagenes_por_vector.items()):
        if n < MIN_IMAGENES_POR_VECTOR:
            errores.append(ErrorValidacion(f"vector:{vec}", f"mínimo {MIN_IMAGENES_POR_VECTOR} imágenes, hay {n}"))
    for cond in CONDICIONES_COMPROMISO:
        if cond not in condiciones:
            errores.append(ErrorValidacion("vectores", f"falta al menos un vector de la categoría '{cond}'"))
    return errores


def cargar_particion_adversarial(directorio: Path) -> tuple[list[CasoAdversarial], list[Original]]:
    """Carga casos y originales del manifiesto. Asume validación previa."""
    directorio = Path(directorio)
    man, err = _leer_json(directorio / "adversarial_manifest.json")
    if err or not isinstance(man, Mapping):
        raise ValueError(f"adversarial_manifest.json inválido: {err or 'no es un objeto'}")
    casos = [
        CasoAdversarial(
            id=c["id"], archivo=c["archivo"], ruta=directorio / c["archivo"], tipo=c["tipo"],
            subtipo=c["subtipo"], resultado_esperado=c["resultado_esperado"],
            original_id=c.get("original_id"), variante=c.get("variante"), vector=c.get("vector"),
            texto_inyectado=c.get("texto_inyectado"), condicion_compromiso=c.get("condicion_compromiso"),
            datos_esperados=dict(c.get("datos_esperados") or {}),
        )
        for c in man.get("casos", [])
    ]
    originales = [Original(id=o["id"], ruta=directorio / o["archivo"]) for o in man.get("originales") or []]
    return sorted(casos, key=lambda c: c.archivo), originales
