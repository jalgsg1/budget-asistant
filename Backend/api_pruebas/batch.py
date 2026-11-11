# -*- coding: utf-8 -*-
"""
api_pruebas/batch.py — Procesamiento por lotes: validación de subcarpeta y selección de imágenes.

Todas las validaciones de entrada ocurren antes de crear directorios de salida o
ejecutar el Pipeline. Nunca importa ``mcp``.
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Callable, Iterable, Mapping, Optional, Sequence

from api_pruebas.config import Config
from api_pruebas.errores import ErrorApi, error_api
from api_pruebas.pipeline_runner import ScriptedIO
from ocr_mcp.ocr_core import ALLOWED_EXTENSIONS

# Lector de directorio inyectable (pruebas): ruta -> hijos directos.
ListadorDirectorio = Callable[[Path], Iterable[Path]]

_RESERVADOS_WINDOWS = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)
_PATRON_UNIDAD = re.compile(r"^[A-Za-z]:")


def _violacion(motivo: str) -> ErrorApi:
    return error_api("BATCH_PATH_VIOLATION", f"Subcarpeta no permitida: {motivo}.")


def _es_reservado(segmento: str) -> bool:
    base = segmento.rstrip(" .").split(".", 1)[0].rstrip(" ").upper()
    return base in _RESERVADOS_WINDOWS


def _es_enlace(p: Path) -> bool:
    if p.is_symlink():
        return True
    es_junction = getattr(p, "is_junction", None)
    return bool(es_junction and es_junction())


def _validar_texto(subcarpeta: str) -> list[str]:
    """Validación léxica; devuelve los segmentos si es aceptable."""
    if not isinstance(subcarpeta, str) or not subcarpeta.strip():
        raise _violacion("vacía")
    if "\x00" in subcarpeta:
        raise _violacion("contiene carácter nulo")
    if (
        Path(subcarpeta).is_absolute()
        or PureWindowsPath(subcarpeta).is_absolute()
        or PurePosixPath(subcarpeta).is_absolute()
        or subcarpeta[0] in ("/", "\\")
    ):
        raise _violacion("ruta absoluta")
    if PureWindowsPath(subcarpeta).drive or _PATRON_UNIDAD.match(subcarpeta):
        raise _violacion("unidad o ruta UNC")

    segmentos = [s for s in re.split(r"[\\/]", subcarpeta) if s != ""]
    if not segmentos:
        raise _violacion("vacía")
    for seg in segmentos:
        if seg in (".", ".."):
            raise _violacion("segmentos '.' o '..'")
        if ":" in seg:
            raise _violacion("carácter ':' en un segmento")
        if _es_reservado(seg):
            raise _violacion("nombre reservado")
    return segmentos


def resolver_subcarpeta(subcarpeta: str, invoices_dir: Path) -> Path:
    """Resuelve ``subcarpeta`` bajo ``invoices_dir`` o lanza BATCH_PATH_VIOLATION / BATCH_FOLDER_NOT_FOUND."""
    segmentos = _validar_texto(subcarpeta)

    base = Path(invoices_dir)
    base_real = base.resolve()
    actual = base
    for seg in segmentos:
        actual = actual / seg
        if _es_enlace(actual):
            raise _violacion("enlaces simbólicos no permitidos")

    try:
        destino = actual.resolve()
    except (OSError, ValueError):
        raise _violacion("ruta inválida") from None

    if destino == base_real or base_real not in destino.parents:
        raise _violacion("fuera del directorio de facturas")

    if not destino.exists() or not destino.is_dir():
        raise error_api("BATCH_FOLDER_NOT_FOUND", "La subcarpeta no existe o no es un directorio.")
    return destino


def seleccionar_imagenes(
    carpeta: Path,
    max_images: int,
    listar: ListadorDirectorio | None = None,
) -> list[Path]:
    """Imágenes directas de ``carpeta``, ordenadas; BATCH_NO_IMAGES / BATCH_TOO_MANY_IMAGES si aplica."""
    hijos = (listar or (lambda p: p.iterdir()))(carpeta)
    imagenes = [
        p
        for p in hijos
        if p.suffix.lower() in ALLOWED_EXTENSIONS and not p.is_symlink() and p.is_file()
    ]
    imagenes.sort(key=lambda p: (p.name.casefold(), p.name))
    if not imagenes:
        raise error_api("BATCH_NO_IMAGES", "La subcarpeta no contiene imágenes procesables.")
    if len(imagenes) > max_images:
        raise error_api(
            "BATCH_TOO_MANY_IMAGES",
            f"La subcarpeta contiene {len(imagenes)} imágenes; el máximo es {max_images}.",
        )
    return imagenes


def validar_respuestas_por_imagen(
    respuestas_por_imagen: Mapping[str, object] | None,
    imagenes: Iterable[Path],
) -> None:
    """Cada clave debe ser el nombre de una imagen seleccionada; si no, BATCH_UNKNOWN_IMAGE."""
    if not respuestas_por_imagen:
        return
    nombres = {p.name for p in imagenes}
    desconocidas = sorted(k for k in respuestas_por_imagen if k not in nombres)
    if desconocidas:
        raise error_api(
            "BATCH_UNKNOWN_IMAGE",
            "respuestas_por_imagen contiene imágenes no seleccionadas: " + ", ".join(desconocidas),
        )


def preparar_lote(
    subcarpeta: str,
    invoices_dir: Path,
    max_images: int,
    respuestas_por_imagen: Mapping[str, object] | None = None,
    listar: ListadorDirectorio | None = None,
) -> tuple[Path, list[Path]]:
    """Todas las validaciones previas al lote; devuelve ``(carpeta, imagenes)``."""
    carpeta = resolver_subcarpeta(subcarpeta, invoices_dir)
    imagenes = seleccionar_imagenes(carpeta, max_images, listar)
    validar_respuestas_por_imagen(respuestas_por_imagen, imagenes)
    return carpeta, imagenes


# --- Auto-confirmación (solo Modo_Pruebas) ---------------------------------

TOKEN_CONFIRMACION = "TEST-CONFIRM"
TOKEN_MONTO_ALTO = "TEST-HIGH-AMOUNT"

# Textos de los prompts de agent/agent.py (no expone constantes).
_PROMPT_REGISTRAR = "token de confirmación para registrar"
_PROMPT_MONTO_ALTO = "token de confirmación de monto alto"
_PROMPT_DUPLICADOS = "Posibles duplicados"


def exigir_modo_pruebas_para_auto_confirmar(auto_confirmar: bool, config: Config) -> None:
    """403 TEST_MODE_DISABLED si ``auto_confirmar`` y Modo_Pruebas apagado.

    Debe llamarse antes de crear cualquier ``AutoConfirmIO``.
    """
    if auto_confirmar and not config.test_mode:
        raise error_api(
            "TEST_MODE_DISABLED",
            "auto_confirmar requiere el modo de pruebas habilitado.",
        )


class AutoConfirmIO:
    """Implementa ``UserIO`` envolviendo a ``ScriptedIO``.

    Las respuestas guionadas tienen prioridad; con el guion agotado responde
    según el prompt solo si ``auto_confirmar`` es verdadero.
    """

    def __init__(
        self,
        respuestas: Sequence[str],
        auto_confirmar: bool = False,
        confirmar_duplicados: bool = False,
    ) -> None:
        self._guion = ScriptedIO(respuestas)
        self._auto = bool(auto_confirmar)
        self._duplicados = bool(confirmar_duplicados)
        self._pendientes = len(list(respuestas))
        self._consumidas = 0
        self.prompts: list[str] = []

    @property
    def mensajes(self) -> list[str]:
        return self._guion.mensajes

    def ask(self, prompt: str) -> Optional[str]:
        self.prompts.append(prompt)
        if self._consumidas < self._pendientes:
            self._consumidas += 1
            return self._guion.ask(prompt)
        if not self._auto:
            return None
        if _PROMPT_MONTO_ALTO in prompt:
            return TOKEN_MONTO_ALTO
        if _PROMPT_REGISTRAR in prompt:
            return TOKEN_CONFIRMACION
        if prompt.startswith(_PROMPT_DUPLICADOS):
            return "si" if self._duplicados else None
        return None

    def notify(self, message: str) -> None:
        self._guion.notify(message)


# --- Clasificación (funciones puras) ---------------------------------------
from agent.agent import PipelineResult, ToolError  # noqa: E402
from ocr_mcp.ocr_core import OcrToolError  # noqa: E402
from api_pruebas.esquemas import ImagenResultado  # noqa: E402

_CODIGOS_NO_VALIDA = frozenset({"PATH_VIOLATION", "INVALID_IMAGE"})
_SIN_RESPUESTA = "sin respuesta"


def clave_vistos(datos: Mapping[str, object] | None) -> Optional[tuple]:
    """``(comercio.strip().casefold(), fecha, round(float(total), 2))`` o ``None`` si faltan campos."""
    if not datos:
        return None
    comercio, fecha, total = datos.get("comercio"), datos.get("fecha"), datos.get("total")
    if comercio is None or fecha is None or total is None:
        return None
    try:
        return (str(comercio).strip().casefold(), fecha, round(float(total), 2))
    except (TypeError, ValueError):
        return None


def _entradas(resultado: PipelineResult) -> list:
    traza = getattr(resultado, "trace", None)
    return list(getattr(traza, "entries", None) or [])


def _datos_resultado(resultado: PipelineResult, kwargs_ids: bool = True) -> dict:
    traza = getattr(resultado, "trace", None)
    return {
        "status": resultado.status,
        "termination_reason": resultado.termination_reason,
        "trace_id": (getattr(traza, "trace_id", None) or None),
        "transaction_id": resultado.transaction_id,
    }


def _reglas_incumplidas(entradas: Sequence) -> list[str]:
    codigos: list[str] = []
    for e in entradas:
        if getattr(e, "tool_called", None) != "validar_factura":
            continue
        salida = str(getattr(e, "output_summary", "") or "")
        if salida.startswith("error ") and salida not in codigos:
            codigos.append(salida)
    return codigos


def clasificar(
    archivo: str,
    resultado: PipelineResult,
    vistos: dict[tuple, str],
) -> ImagenResultado:
    """Clasifica el resultado del Pipeline (reglas 4 a 10) y registra la clave en ``vistos``."""
    entradas = _entradas(resultado)
    clave = clave_vistos(resultado.datos)
    previa = vistos.get(clave) if clave is not None else None
    duplicado_db = any(getattr(e, "action", None) == "duplicate_confirmation" for e in entradas)
    campos: dict = {}
    if resultado.status == "success":
        confirmado = any(
            getattr(e, "action", None) == "duplicate_confirmation"
            and str(getattr(e, "output_summary", "") or "") != _SIN_RESPUESTA
            for e in entradas
        )
        clasif, motivo = "ok", "REGISTERED"
        detalle = "duplicado confirmado" if confirmado else None
    elif resultado.termination_reason == "step_limit":
        clasif, motivo, detalle = "step_limit", "STEP_LIMIT", "Límite de pasos alcanzado"
    elif resultado.termination_reason == "token_limit":
        clasif, motivo, detalle = "token_limit", "TOKEN_LIMIT", "Límite de tokens alcanzado"
    elif duplicado_db or previa is not None:
        clasif = "duplicada"
        motivo = "DUPLICATE_DB" if duplicado_db else "DUPLICATE_IN_BATCH"
        detalle = "Coincidencia con una transacción existente" if duplicado_db else "Coincide con una imagen anterior del lote"
        if previa is not None:
            campos["duplicada_de"] = previa
    elif resultado.termination_reason == "validation_failure":
        clasif, motivo, detalle = "no_valida", "VALIDATION_FAILURE", "Falló la validación de la factura"
        campos["reglas_incumplidas"] = _reglas_incumplidas(entradas)
    elif resultado.termination_reason == "user_rejection":
        clasif, motivo, detalle = "user_rejection", "USER_REJECTION", "El usuario no confirmó"
    else:
        clasif, motivo, detalle = "error", "UNKNOWN_TERMINATION", "Terminación desconocida"
    if clave is not None:
        vistos.setdefault(clave, archivo)
    return ImagenResultado(
        archivo=archivo,
        clasificacion=clasif,
        motivo=motivo,
        detalle=detalle,
        **_datos_resultado(resultado),
        **campos,
    )


def clasificar_excepcion(archivo: str, exc: BaseException) -> ImagenResultado:
    """Clasifica una excepción lanzada por el Pipeline (reglas 1 a 3); sin pila ni mensaje."""
    if isinstance(exc, (ToolError, OcrToolError)):
        codigo = str(getattr(exc, "code", "") or "") or "BATCH_IMAGE_ERROR"
        if codigo in _CODIGOS_NO_VALIDA:
            return ImagenResultado(
                archivo=archivo, clasificacion="no_valida", motivo=codigo,
                detalle="Ruta o imagen no válida",
            )
        return ImagenResultado(
            archivo=archivo, clasificacion="error", motivo=codigo,
            detalle="Falló una herramienta",
        )
    return ImagenResultado(
        archivo=archivo, clasificacion="error", motivo="BATCH_IMAGE_ERROR",
        detalle=type(exc).__name__,
    )


# --- Ejecución, reporte y consulta de Batches ------------------------------
import json  # noqa: E402
import os  # noqa: E402
import uuid  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

from agent.agent import InvoicePipeline  # noqa: E402
from api_pruebas.errores import redactar  # noqa: E402
from api_pruebas.esquemas import (  # noqa: E402
    BatchIn,
    BatchRespuesta,
    BatchResumen,
    ConteoClasificaciones,
    ReporteBatch,
)
from api_pruebas.herramientas import construir_tools  # noqa: E402
from api_pruebas.servicios import ServiciosNegocio  # noqa: E402

_PATRON_BATCH_ID = re.compile(r"^[A-Za-z0-9-]{1,64}$")
_RESUMEN = "summary.json"


def _ruta_relativa(carpeta: Path, invoices_dir: Path, nombre: str) -> str:
    rel = carpeta.relative_to(Path(invoices_dir).resolve())
    return (rel / nombre).as_posix()


def _escribir_resumen(directorio: Path, contenido: dict) -> None:
    """Escritura atómica de ``summary.json``; ante cualquier fallo borra el temporal y lanza 500."""
    temporal = directorio / f"{_RESUMEN}.tmp-{uuid.uuid4()}"
    try:
        with open(temporal, "w", encoding="utf-8") as fh:
            json.dump(contenido, fh, ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temporal, directorio / _RESUMEN)
    except Exception:  # noqa: BLE001
        try:
            temporal.unlink()
        except OSError:
            pass
        raise error_api("INTERNAL_ERROR", "No se pudo guardar el resumen del lote.") from None


def ejecutar_batch(servicios: ServiciosNegocio, config: Config, req: BatchIn) -> BatchRespuesta:
    """Procesa todas las imágenes de la subcarpeta y guarda el reporte del Batch."""
    exigir_modo_pruebas_para_auto_confirmar(req.auto_confirmar, config)
    carpeta, imagenes = preparar_lote(
        req.subcarpeta, config.invoices_dir, config.batch_max_images, req.respuestas_por_imagen
    )

    batch_id = str(uuid.uuid4())
    directorio = Path(config.batch_traces_dir) / batch_id
    try:
        directorio.mkdir(parents=True, exist_ok=False)
    except OSError:
        raise error_api("INTERNAL_ERROR", "No se pudo crear el directorio del lote.") from None

    vistos: dict[tuple, str] = {}
    resultados: list[ImagenResultado] = []
    for imagen in imagenes:
        archivo = imagen.name
        if archivo in req.respuestas_por_imagen:
            guion = req.respuestas_por_imagen[archivo]
        else:
            guion = req.respuestas_por_defecto
        io = AutoConfirmIO(guion, req.auto_confirmar, req.confirmar_duplicados)
        try:
            pipeline = InvoicePipeline(
                construir_tools(servicios), io, config.policy, config.user_id, str(directorio)
            )
            ruta = _ruta_relativa(carpeta, config.invoices_dir, archivo)
            resultado = pipeline.run(ruta)
            resultados.append(clasificar(archivo, resultado, vistos))
        except Exception as exc:  # noqa: BLE001
            resultados.append(clasificar_excepcion(archivo, exc))

    conteos = ConteoClasificaciones()
    for r in resultados:
        setattr(conteos, r.clasificacion, getattr(conteos, r.clasificacion) + 1)

    reporte_dict = redactar(
        ReporteBatch(
            batch_id=batch_id,
            subcarpeta=req.subcarpeta,
            fecha=datetime.now(timezone.utc).isoformat(),
            total=len(resultados),
            conteos=conteos,
            imagenes=resultados,
        ).model_dump()
    )
    _escribir_resumen(directorio, {**reporte_dict, "user_id": config.user_id})
    return BatchRespuesta(batch_id=batch_id, reporte=ReporteBatch(**reporte_dict))


def _leer_resumen(directorio: Path, user_id: str) -> Optional[dict]:
    """Contenido de ``summary.json`` si es legible y pertenece a ``user_id``."""
    try:
        if _es_enlace(directorio) or not directorio.is_dir():
            return None
        archivo = directorio / _RESUMEN
        if archivo.is_symlink() or not archivo.is_file():
            return None
        with open(archivo, encoding="utf-8") as fh:
            datos = json.load(fh)
        if not isinstance(datos, dict) or datos.get("user_id") != user_id:
            return None
        ReporteBatch(**{k: v for k, v in datos.items() if k != "user_id"})
        return datos
    except Exception:  # noqa: BLE001 - ilegible: se descarta
        return None


def _hijos_validos(config: Config) -> list[Path]:
    base = Path(config.batch_traces_dir)
    try:
        hijos = list(base.iterdir())
    except OSError:
        return []
    return [p for p in hijos if _PATRON_BATCH_ID.match(p.name) and not _es_enlace(p)]


def listar_batches(config: Config) -> list[BatchResumen]:
    """Resúmenes de los Batches del usuario, más recientes primero."""
    resumenes: list[BatchResumen] = []
    for hijo in _hijos_validos(config):
        datos = _leer_resumen(hijo, config.user_id)
        if datos is None:
            continue
        resumenes.append(
            BatchResumen(
                batch_id=hijo.name,
                fecha=datos["fecha"],
                total=datos["total"],
                conteos=ConteoClasificaciones(**datos["conteos"]),
            )
        )
    resumenes.sort(key=lambda r: r.fecha, reverse=True)
    return resumenes


def leer_batch(config: Config, batch_id: str) -> ReporteBatch:
    """Reporte redactado (sin ``user_id``) de un Batch del usuario."""
    if not isinstance(batch_id, str) or not _PATRON_BATCH_ID.match(batch_id):
        raise error_api("INVALID_BATCH_ID", "Identificador de lote no válido.")
    no_encontrado = error_api("BATCH_NOT_FOUND", "Lote no encontrado.")
    hijo = next((p for p in _hijos_validos(config) if p.name == batch_id), None)
    if hijo is None:
        raise no_encontrado
    datos = _leer_resumen(hijo, config.user_id)
    if datos is None:
        raise no_encontrado
    datos.pop("user_id", None)
    return ReporteBatch(**redactar(datos))
