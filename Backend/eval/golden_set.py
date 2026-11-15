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
    RESULTADO_NO_COMPROMETER,
    RESULTADO_NO_REGISTRAR,
    RESULTADO_REGISTRAR,
    RESULTADOS_ADVERSARIALES,
    RESULTADOS_ESPERADOS,
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
    total: Decimal | None   # None solo en facturas con resultado_esperado "no_registrar"
    categoria: str
    dificultad: str
    resultado_esperado: str = RESULTADO_REGISTRAR


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

def validar_ground_truth(
    entradas: Sequence[Mapping[str, Any]],
    imagenes: Collection[str],
    resultados_permitidos: Collection[str] = RESULTADOS_ESPERADOS,
) -> list[ErrorValidacion]:
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
        resultado = e.get("resultado_esperado")
        if resultado not in (None, "") and resultado not in resultados_permitidos:
            errores.append(ErrorValidacion(
                nombre, f"resultado_esperado inválido (valores aceptados: {', '.join(resultados_permitidos)})"))
        # Una factura que el sistema debe rechazar solo necesita `dificultad`: sus datos no se usan.
        rechazo = resultado == RESULTADO_NO_REGISTRAR
        for campo in (("dificultad",) if rechazo else CAMPOS_GT[1:]):
            if campo not in e or e[campo] is None or e[campo] == "":
                errores.append(ErrorValidacion(nombre, f"campo requerido ausente o vacío: {campo}"))
        if not rechazo:
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
        resultado = e.get("resultado_esperado") or RESULTADO_REGISTRAR
        if resultado == RESULTADO_NO_REGISTRAR:
            # Los datos no se usan: pueden faltar o ser inválidos.
            total = None
            if _decimal_valido(e.get("total")):
                total = Decimal(str(e["total"]))
            casos.append(CasoLimpio(
                imagen=nombre, ruta=directorio / "images" / nombre,
                comercio=str(e.get("comercio") or ""), fecha=str(e.get("fecha") or ""),
                moneda=str(e.get("moneda") or ""), total=total,
                categoria=str(e.get("categoria") or ""), dificultad=e["dificultad"],
                resultado_esperado=resultado,
            ))
            continue
        casos.append(CasoLimpio(
            imagen=nombre, ruta=directorio / "images" / nombre,
            comercio=e["comercio"], fecha=e["fecha"], moneda=e["moneda"],
            total=Decimal(str(e["total"])),
            categoria=e["categoria"], dificultad=e["dificultad"],
            resultado_esperado=resultado,
        ))
    return sorted(casos, key=lambda c: c.imagen)


# ------------------------------------------------------- partición adversarial
#
# `adversarial_security/ground_truth.json` usa el mismo formato que el de la partición limpia
# (imagen, comercio, fecha, moneda, total, categoria, dificultad, resultado_esperado) y agrega
# campos propios del caso: `es_original` (original de un duplicado), `tipo`, `subtipo`,
# `variante`, `original_id`, `vector` y `condicion_compromiso`. En un caso de inyección el
# texto inyectado es el valor de `comercio`: se trata como dato, nunca como instrucción.

def _id_de(imagen: str) -> str:
    return Path(imagen).stem


def validar_entradas_adversariales(
    entradas: Sequence[Mapping[str, Any]], directorio: Path
) -> list[ErrorValidacion]:
    """Valida las entradas adversariales contra las imágenes de ``directorio/images``.

    Solo lectura (Req. 13.1-13.8, 14.1-14.4, 14.6, 14.8). Reporta todos los ofensivos."""
    directorio = Path(directorio)
    imagenes = _imagenes_en(directorio / "images")
    errores = list(validar_ground_truth(entradas, set(imagenes), RESULTADOS_ADVERSARIALES))

    ids_originales = {
        _id_de(e["imagen"]) for e in entradas
        if isinstance(e, Mapping) and e.get("es_original") is True and _no_vacio(e.get("imagen"))
    }
    por_subtipo: dict[str, int] = {}
    variantes: set[str] = set()
    imagenes_por_vector: dict[str, int] = {}
    condiciones: set[str] = set()

    for idx, e in enumerate(entradas):
        if not isinstance(e, Mapping):
            continue  # ya lo reportó validar_ground_truth
        img = e.get("imagen")
        nombre = Path(img).name if _no_vacio(img) else f"entrada[{idx}]"
        if _no_vacio(img) and nombre in imagenes:
            try:
                if (directorio / "images" / nombre).stat().st_size == 0:
                    errores.append(ErrorValidacion(nombre, f"el archivo está vacío: {nombre}"))
            except OSError:
                errores.append(ErrorValidacion(nombre, f"el archivo no es legible: {nombre}"))

        resultado = e.get("resultado_esperado")
        if e.get("es_original") is True:
            if resultado not in (None, "", RESULTADO_REGISTRAR):
                errores.append(ErrorValidacion(nombre, "un original debe tener resultado_esperado 'registrar'"))
            continue

        for campo in ("tipo", "subtipo", "resultado_esperado"):
            if not _no_vacio(e.get(campo)):
                errores.append(ErrorValidacion(nombre, f"campo requerido ausente o vacío: {campo}"))

        tipo, subtipo = e.get("tipo"), e.get("subtipo")
        if _no_vacio(tipo) and tipo not in TIPOS_CASO:
            errores.append(ErrorValidacion(nombre, f"tipo inválido: {tipo}"))

        if tipo == "integridad":
            if resultado not in (None, "") and resultado != RESULTADO_NO_REGISTRAR:
                errores.append(ErrorValidacion(nombre, "resultado_esperado debe ser 'no_registrar'"))
            if _no_vacio(subtipo):
                if subtipo not in SUBTIPOS_INTEGRIDAD:
                    errores.append(ErrorValidacion(nombre, f"subtipo de integridad inválido: {subtipo}"))
                else:
                    por_subtipo[subtipo] = por_subtipo.get(subtipo, 0) + 1
            if subtipo == "fecha_invalida":
                var = e.get("variante")
                if var in VARIANTES_FECHA:
                    variantes.add(var)
                elif var is not None:
                    errores.append(ErrorValidacion(nombre, f"variante de fecha inválida: {var}"))
            if subtipo == "factura_duplicada":
                oid = e.get("original_id")
                if not _no_vacio(oid):
                    errores.append(ErrorValidacion(nombre, "duplicado sin 'original_id'"))
                elif oid not in ids_originales:
                    errores.append(ErrorValidacion(nombre, f"el original '{oid}' no existe entre los originales"))
        elif tipo == "inyeccion":
            if resultado not in (None, "") and resultado != RESULTADO_NO_COMPROMETER:
                errores.append(ErrorValidacion(nombre, "resultado_esperado debe ser 'no_comprometer'"))
            vector = e.get("vector")
            if not _no_vacio(vector):
                errores.append(ErrorValidacion(nombre, "inyección sin 'vector'"))
            else:
                imagenes_por_vector[vector] = imagenes_por_vector.get(vector, 0) + 1
            cond = e.get("condicion_compromiso")
            if cond not in CONDICIONES_COMPROMISO:
                errores.append(ErrorValidacion(
                    nombre, f"condicion_compromiso debe ser una de {', '.join(CONDICIONES_COMPROMISO)}"))
            else:
                condiciones.add(cond)

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


def validar_particion_adversarial(directorio: Path) -> list[ErrorValidacion]:
    """Valida la partición adversarial completa (``ground_truth.json`` e imágenes). Solo lectura."""
    directorio = Path(directorio)
    gt, err = _leer_json(directorio / "ground_truth.json")
    if err:
        return [ErrorValidacion("ground_truth.json", err)]
    if not isinstance(gt, list):
        return [ErrorValidacion("ground_truth.json", "se esperaba una lista de objetos")]
    return validar_entradas_adversariales(gt, directorio)


def cargar_particion_adversarial(directorio: Path) -> tuple[list[CasoAdversarial], list[Original]]:
    """Carga casos y originales de ``ground_truth.json``. Asume validación previa."""
    directorio = Path(directorio)
    gt, err = _leer_json(directorio / "ground_truth.json")
    if err or not isinstance(gt, list):
        raise ValueError(f"ground_truth.json inválido: {err or 'no es una lista'}")
    casos: list[CasoAdversarial] = []
    originales: list[Original] = []
    for e in gt:
        nombre = Path(e["imagen"]).name
        ruta = directorio / "images" / nombre
        if e.get("es_original") is True:
            originales.append(Original(id=_id_de(nombre), ruta=ruta))
            continue
        inyeccion = e["tipo"] == "inyeccion"
        casos.append(CasoAdversarial(
            id=_id_de(nombre), archivo=nombre, ruta=ruta, tipo=e["tipo"], subtipo=e["subtipo"],
            resultado_esperado=e["resultado_esperado"],
            original_id=e.get("original_id"), variante=e.get("variante"), vector=e.get("vector"),
            texto_inyectado=e["comercio"] if inyeccion else None,
            condicion_compromiso=e.get("condicion_compromiso"),
            datos_esperados={
                "comercio": e["comercio"], "fecha": e["fecha"], "moneda": e["moneda"],
                "total": float(Decimal(str(e["total"]))),
            } if inyeccion else {},
        ))
    return sorted(casos, key=lambda c: c.archivo), originales
