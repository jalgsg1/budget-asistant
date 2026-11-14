"""eval/informes.py: escritura y lectura de resultados del paper (Req. 14.5, 17).

Genera ``resultados_paper.json`` (escritura atómica), la tabla comparativa en
Markdown y el bloque generado de ``security/injection_analysis.md``.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from eval.metricas import RegistroFactura, calcular_todo, comprometido

VERSION_RESULTADOS: str = "1"
MARCA_INICIO: str = "<!-- BENCH:INICIO -->"
MARCA_FIN: str = "<!-- BENCH:FIN -->"
SIN_DATO: str = "n/d"

ENCABEZADOS_TABLA: tuple[str, ...] = (
    "Sistema",
    "Integridad_FPA",
    "ASR",
    "Tasa_Friccion",
    "latencia promedio (ms)",
    "tokens de entrada promedio",
    "tokens de salida promedio",
)


class ResultadosInvalidosError(ValueError):
    """El archivo de resultados falta, no es JSON válido o no contiene registros."""


class MarcasBenchError(ValueError):
    """El documento no contiene las marcas BENCH en el orden esperado."""


# ---------------------------------------------------------------------------
# Escritura y lectura
# ---------------------------------------------------------------------------

def _escribir_texto_atomico(texto: str, ruta: Path) -> None:
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    fd, nombre_tmp = tempfile.mkstemp(dir=str(ruta.parent), prefix=ruta.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(texto)
            f.flush()
            os.fsync(f.fileno())
        os.replace(nombre_tmp, ruta)
    except BaseException:
        try:
            os.unlink(nombre_tmp)
        except OSError:
            pass
        raise


def escribir_json_atomico(obj: Mapping[str, Any], ruta: Path) -> None:
    """Escribe en un temporal del mismo directorio, hace fsync y reemplaza con os.replace.

    Un fallo conserva el archivo anterior y borra el temporal."""
    texto = json.dumps(obj, ensure_ascii=False, indent=2)
    _escribir_texto_atomico(texto + "\n", ruta)


def leer_resultados(ruta: Path) -> dict[str, Any]:
    """Lee resultados_paper.json. Lanza ResultadosInvalidosError si falta, no es JSON
    o no contiene registros por factura."""
    ruta = Path(ruta)
    if not ruta.is_file():
        raise ResultadosInvalidosError(f"el archivo de resultados no existe: {ruta}")
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            datos = json.load(f)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ResultadosInvalidosError(f"el archivo de resultados no es JSON válido: {ruta} ({type(exc).__name__})") from exc
    if not isinstance(datos, dict):
        raise ResultadosInvalidosError(f"el archivo de resultados no es un objeto JSON: {ruta}")
    registros = datos.get("registros")
    if not isinstance(registros, list) or not registros:
        raise ResultadosInvalidosError(f"el archivo de resultados no contiene registros por factura: {ruta}")
    return datos


def commit_actual() -> str | None:
    """Identificador del commit HEAD, o None ante cualquier fallo de git."""
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, encoding="utf-8", timeout=10, check=False,
        )
        if proc.returncode != 0:
            return None
        valor = proc.stdout.strip()
        return valor or None
    except Exception:
        return None


def _a_dict(r: Any) -> dict[str, Any]:
    return r.a_dict() if isinstance(r, RegistroFactura) else dict(r)


def construir_resultados(
    registros: Iterable[Any],
    parametros: Mapping[str, Any],
    proveedor: str,
    modelo: str,
    politica_respuestas: Mapping[str, Any],
    inicio_utc: str | None = None,
) -> dict[str, Any]:
    """Arma el objeto de resultados_paper.json a partir de los registros por factura."""
    lista = [_a_dict(r) for r in registros]
    todo = calcular_todo(lista)
    params = dict(parametros)
    params["politica_respuestas"] = dict(politica_respuestas)
    return {
        "version": VERSION_RESULTADOS,
        "inicio_utc": inicio_utc or datetime.now(timezone.utc).isoformat(),
        "commit": commit_actual(),
        "proveedor": proveedor,
        "modelo": modelo,
        "parametros": params,
        "registros": lista,
        "metricas": {s: d["metricas"] for s, d in todo.items()},
        "conteos": {s: d["conteos"] for s, d in todo.items()},
    }


# ---------------------------------------------------------------------------
# Tabla comparativa
# ---------------------------------------------------------------------------

def _valor(metrica: Any) -> float | None:
    if isinstance(metrica, Mapping):
        metrica = metrica.get("valor")
    if isinstance(metrica, bool) or not isinstance(metrica, (int, float)):
        return None
    return float(metrica)


def _fmt(valor: float | None, decimales: int) -> str:
    return SIN_DATO if valor is None else f"{valor:.{decimales}f}"


def formatear_tabla(metricas_por_sistema: Mapping[str, Any]) -> str:
    """Tabla Markdown: razones con 4 decimales, costos con 1, ``n/d`` para None.

    Acepta ``{sistema: {"metricas": {...}}}`` (salida de calcular_todo) o
    ``{sistema: {...metricas...}}``."""
    lineas = [
        "| " + " | ".join(ENCABEZADOS_TABLA) + " |",
        "|" + "|".join(["---"] * len(ENCABEZADOS_TABLA)) + "|",
    ]
    for sistema, datos in metricas_por_sistema.items():
        m = datos.get("metricas", datos) if isinstance(datos, Mapping) else {}
        costo = m.get("costo_operacional", {}) if isinstance(m, Mapping) else {}
        celdas = [
            str(sistema),
            _fmt(_valor(m.get("integridad_fpa")), 4),
            _fmt(_valor(m.get("asr")), 4),
            _fmt(_valor(m.get("tasa_friccion")), 4),
            _fmt(_valor(costo.get("latencia_ms")), 1),
            _fmt(_valor(costo.get("tokens_entrada")), 1),
            _fmt(_valor(costo.get("tokens_salida")), 1),
        ]
        lineas.append("| " + " | ".join(celdas) + " |")
    return "\n".join(lineas) + "\n"


# ---------------------------------------------------------------------------
# injection_analysis.md
# ---------------------------------------------------------------------------

def _celda(texto: Any) -> str:
    s = "" if texto is None else str(texto)
    return s.replace("\\", "\\\\").replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _campo(r: Any, nombre: str) -> Any:
    return r.get(nombre) if isinstance(r, Mapping) else getattr(r, nombre, None)


def _bloque_bench(registros: Iterable[Any]) -> str:
    casos = [r for r in registros if _campo(r, "tipo_caso") == "inyeccion"]
    lineas = [
        "| Sistema | Caso | Vector | Texto inyectado | Resultado |",
        "|---|---|---|---|---|",
    ]
    for r in sorted(casos, key=lambda x: (str(_campo(x, "sistema")), str(_campo(x, "id")))):
        vector = _campo(r, "vector") or _campo(r, "subtipo") or ""
        texto = _campo(r, "texto_inyectado") or ""
        try:
            veredicto = "comprometido" if comprometido(r) else "no_comprometido"
        except Exception:
            veredicto = "no_comprometido"
        lineas.append(
            f"| {_celda(_campo(r, 'sistema'))} | {_celda(_campo(r, 'id'))} | {_celda(vector)} "
            f"| {_celda(texto)} | {veredicto} |"
        )
    if len(lineas) == 2:
        lineas.append("| n/d | n/d | n/d | n/d | n/d |")
    return "\n".join(lineas)


def actualizar_injection_analysis(registros: Iterable[Any], ruta: Path) -> None:
    """Reescribe solo el bloque entre las marcas BENCH; el resto no se toca.

    Si las marcas faltan o están desordenadas lanza MarcasBenchError sin modificar el archivo."""
    ruta = Path(ruta)
    with open(ruta, "r", encoding="utf-8", newline="") as f:
        contenido = f.read()
    i = contenido.find(MARCA_INICIO)
    j = contenido.find(MARCA_FIN)
    if i < 0 or j < 0 or j < i + len(MARCA_INICIO):
        raise MarcasBenchError(f"{ruta} no contiene {MARCA_INICIO} seguida de {MARCA_FIN}")
    nl = "\r\n" if "\r\n" in contenido else "\n"
    bloque = _bloque_bench(list(registros)).replace("\n", nl)
    nuevo = contenido[: i + len(MARCA_INICIO)] + nl + bloque + nl + contenido[j:]
    _escribir_texto_atomico(nuevo, ruta)
