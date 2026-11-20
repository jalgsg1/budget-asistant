# -*- coding: utf-8 -*-
"""
api_pruebas/servicios.py — Servicios de negocio compartidos por HTTP y Pipeline.

Ningún método acepta ``user_id``: siempre se usa ``config.user_id``. Cada operación
abre su propio ``TransactionRepository`` (``with``). Nunca importa ``mcp``.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import unicodedata
import uuid
from pathlib import Path
from typing import Any, Callable, Iterable

from api_pruebas.config import Config
from api_pruebas.errores import ErrorApi, error_api, redactar
from agent.contenido_sospechoso import escanear
from api_pruebas.esquemas import (
    AnalisisFacturaRespuesta,
    OcrRespuesta,
    ReglaResultado,
    ValidacionRespuesta,
)
from finanzas_mcp.constantes import CAMPOS_OBLIGATORIOS as _CAMPOS_OBLIGATORIOS_MCP
from finanzas_mcp.business.categorias import CLOSED_CATEGORY_LIST
from finanzas_mcp.business.duplicados import buscar_duplicados as _buscar_duplicados
from finanzas_mcp.business.factura import ResultadoFactura, evaluar_factura
from finanzas_mcp.business.transacciones import (
    listar_transacciones as _listar_transacciones,
    registrar_transaccion as _registrar_transaccion,
)
from finanzas_mcp.db.repository import TransactionRepository
from finanzas_mcp.models import OcrResult, Transaction
from ocr_mcp.ocr_core import (
    ALLOWED_EXTENSIONS,
    OcrToolError,
    validar_ruta,
    wrap_untrusted,
)

ExtractorOcr = Callable[[str], OcrResult]

_log = logging.getLogger(__name__)

_FIRMAS: dict[str, tuple[bytes, ...]] = {
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".png": (b"\x89PNG",),
    ".pdf": (b"%PDF",),
}

_extractor_lock = threading.Lock()
_extractor_cache: dict[str | None, ExtractorOcr] = {}


def obtener_extractor_ocr(config: Config) -> ExtractorOcr:
    """Crea (una sola vez, bajo lock) el extractor basado en ``OcrClient``.

    ``OcrClient`` se importa de forma diferida: importa ``langchain_core`` al cargar.
    """
    clave = config.ocr_model
    with _extractor_lock:
        extractor = _extractor_cache.get(clave)
        if extractor is None:
            from ocr_mcp.ocr_client import OcrClient  # import diferido

            cliente = OcrClient(model=config.ocr_model)
            extractor = cliente.extract
            _extractor_cache[clave] = extractor
        return extractor


def _sin_acentos(texto: str) -> str:
    descompuesto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in descompuesto if not unicodedata.combining(c)).casefold().strip()


def _categoria_canonica(categoria: Any) -> Any:
    """Devuelve la categoría de la lista cerrada que coincide sin distinguir
    mayúsculas ni acentos ("alimentacion" -> "Alimentación"); si no hay, la deja igual."""
    if not isinstance(categoria, str):
        return categoria
    clave = _sin_acentos(categoria)
    for oficial in CLOSED_CATEGORY_LIST:
        if _sin_acentos(oficial) == clave:
            return oficial
    return categoria


CAMPOS_FACTURA: tuple[str, ...] = (
    "comercio",
    "fecha",
    "total",
    "moneda",
    "categoria",
    "subtotal",
    "iva",
    "descripcion",
)
CAMPOS_OBLIGATORIOS: tuple[str, ...] = _CAMPOS_OBLIGATORIOS_MCP


def _vacio(valor: Any) -> bool:
    return valor is None or (isinstance(valor, str) and not valor.strip())


def _repartir_campos(payload: dict) -> tuple[dict, list[str]]:
    """Reparte los Campos_Factura en ``campos`` y ``campos_no_identificados``.

    Respeta el orden de ``CAMPOS_FACTURA``, ignora claves ajenas, trata las cadenas en
    blanco como vacías y canonicaliza ``categoria`` contra ``CLOSED_CATEGORY_LIST``
    (si no pertenece, queda como no identificada).
    """
    payload = payload if isinstance(payload, dict) else {}
    campos: dict = {}
    no_identificados: list[str] = []
    for nombre in CAMPOS_FACTURA:
        valor = payload.get(nombre)
        if _vacio(valor):
            no_identificados.append(nombre)
            continue
        if nombre == "categoria":
            canonica = _categoria_canonica(valor)
            if canonica not in CLOSED_CATEGORY_LIST:
                no_identificados.append(nombre)
                continue
            valor = canonica
        campos[nombre] = valor
    return campos, no_identificados


def _reglas_validacion(campos: dict, no_identificados: list[str]) -> ValidacionRespuesta:
    """Aplica ``evaluar_factura`` y refuerza R1 si falta un Campo_Obligatorio.

    ``evaluar_factura`` rellena ``fecha`` con la fecha de hoy si falta, por lo que R1
    podría pasar; aquí se agrega R1 fallida cuando hay obligatorios sin identificar.
    """
    resultado = evaluar_factura(dict(campos))
    reglas = [
        ReglaResultado(
            regla=r.regla,
            valid=False,
            code=r.code,
            message=redactar(r.message),
        )
        for r in resultado.reglas
    ]
    faltantes = [c for c in CAMPOS_OBLIGATORIOS if c in no_identificados]
    if faltantes and not any(r.regla == "R1" for r in reglas):
        reglas.append(
            ReglaResultado(
                regla="R1",
                valid=False,
                code="MISSING_FIELDS",
                message=redactar(
                    "Campos obligatorios ausentes o vacíos: " + ", ".join(faltantes)
                ),
            )
        )
    return ValidacionRespuesta(valid=not reglas, reglas=reglas)


def _advertencias(ocr: OcrResult | None, umbral: float) -> list[str]:
    """Advertencias de baja confianza y de contenido sospechoso (texto redactado)."""
    if ocr is None:
        return []
    avisos: list[str] = []
    confianza = getattr(ocr, "confianza_ocr", None)
    if confianza is None:
        confianza = getattr(ocr, "confidence", None)
    if isinstance(confianza, (int, float)) and not isinstance(confianza, bool):
        if confianza < umbral:
            avisos.append(redactar(f"Confianza OCR baja ({confianza} < {umbral})."))
    if escanear(getattr(ocr, "text", None)).sospechoso:
        avisos.append(
            redactar(
                "Se detectó contenido sospechoso en la imagen; se trató solo como dato."
            )
        )
    return avisos


def _item_a_dict(item: Any) -> dict:
    if hasattr(item, "model_dump"):
        return item.model_dump()
    return dict(item)


class ServiciosNegocio:
    """Operaciones de negocio sobre la base y el OCR, siempre para ``config.user_id``."""

    def __init__(self, config: Config, extractor_ocr: ExtractorOcr | None = None) -> None:
        self.config = config
        self._extractor = extractor_ocr

    # ------------------------------------------------------------------
    def _repo(self) -> TransactionRepository:
        return TransactionRepository(str(self.config.db_path))

    def _get_extractor(self) -> ExtractorOcr:
        if self._extractor is not None:
            return self._extractor
        return obtener_extractor_ocr(self.config)

    # ------------------------------------------------------------------
    def validar(self, datos: dict) -> ResultadoFactura:
        return evaluar_factura(datos)

    def listar(self, filtros: dict) -> list[Transaction]:
        """Todas las filas del usuario que cumplen los filtros (sin límite propio)."""
        pol = self.config.policy_dict
        permitidos = list(
            pol.get(
                "allowed_filters",
                ["comercio", "fecha_desde", "fecha_hasta", "categoria", "moneda"],
            )
        )
        max_dias = int(pol.get("max_date_range_days", 90))
        # ValidationError (INVALID_DATE_FORMAT) se mapea a 400 en errores.mapear_excepcion.
        with self._repo() as repo:
            return _listar_transacciones(
                repo, dict(filtros), self.config.user_id, permitidos, max_dias
            )

    # ------------------------------------------------------------------
    def _nombre_publico(self, resuelta: Path) -> str:
        try:
            return resuelta.relative_to(self.config.invoices_dir.resolve()).as_posix()
        except ValueError:
            return resuelta.name

    def ocr_ruta(self, ruta: str) -> OcrRespuesta:
        resuelta = validar_ruta(
            ruta, str(self.config.invoices_dir), self.config.max_upload_bytes
        )
        extractor = self._get_extractor()
        try:
            resultado = extractor(str(resuelta))
        except OcrToolError:
            raise
        except Exception as exc:  # noqa: BLE001 - solo se expone el tipo
            raise OcrToolError(
                "OCR_FAILURE",
                redactar(f"Fallo en la extracción OCR ({type(exc).__name__})."),
            ) from None
        envuelto = json.loads(wrap_untrusted(resultado))
        envuelto["result"]["is_untrusted"] = True
        return OcrRespuesta(
            untrusted_content=True,
            is_untrusted=True,
            notice=envuelto["notice"],
            result=envuelto["result"],
            ruta=self._nombre_publico(resuelta),
        )

    def _validar_archivo(self, nombre: str, contenido: bytes) -> str:
        """Valida extensión (415), firma (415) y tamaño (413).

        Devuelve la extensión en minúsculas o lanza ``ErrorApi``.
        """
        ext = Path(nombre or "").suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise error_api(
                "UNSUPPORTED_MEDIA",
                "Extensión no permitida. Use: " + ", ".join(sorted(ALLOWED_EXTENSIONS)),
            )
        if not any(contenido.startswith(f) for f in _FIRMAS.get(ext, ())):
            raise error_api(
                "UNSUPPORTED_MEDIA", "El contenido no coincide con la extensión del archivo."
            )
        if len(contenido) > self.config.max_upload_bytes:
            raise error_api(
                "FILE_TOO_LARGE",
                f"El archivo excede el tamaño máximo de {self.config.max_upload_bytes} bytes.",
            )
        return ext

    def ocr_subida(self, nombre: str, contenido: bytes) -> tuple[Path, OcrRespuesta]:
        """Valida el archivo (415/413) antes de escribir nada y ejecuta el OCR."""
        ext = self._validar_archivo(nombre, contenido)
        destino_dir = self.config.invoices_dir
        destino_dir.mkdir(parents=True, exist_ok=True)
        destino = destino_dir / f"{uuid.uuid4()}{ext}"
        destino.write_bytes(contenido)
        return destino, self.ocr_ruta(destino.name)

    def _analisis(
        self, campos: dict, no_identificados: list[str], advertencias: list[str]
    ) -> AnalisisFacturaRespuesta:
        return AnalisisFacturaRespuesta(
            campos=campos,
            campos_no_identificados=no_identificados,
            validacion=_reglas_validacion(campos, no_identificados),
            advertencias=[redactar(a) for a in advertencias],
        )

    def _analisis_fallo(self, mensaje: str) -> AnalisisFacturaRespuesta:
        campos, no_identificados = _repartir_campos({})
        return self._analisis(campos, no_identificados, [mensaje])

    def analizar_subida(self, nombre: str, contenido: bytes) -> AnalisisFacturaRespuesta:
        """Analiza una factura sin persistir nada (ni base, ni trazas, ni INVOICES_DIR).

        Los fallos se devuelven dentro de la respuesta (HTTP 200).
        """
        try:
            ext = self._validar_archivo(nombre, contenido)
        except ErrorApi as exc:
            return self._analisis_fallo(redactar(str(exc.message)))

        ocr: OcrResult | None = None
        payload: Any = None
        fallo: str | None = None
        fd, ruta_tmp = tempfile.mkstemp(suffix=ext)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(contenido)
            try:
                ocr = self._get_extractor()(ruta_tmp)
            except OcrToolError as exc:
                fallo = redactar(str(getattr(exc, "message", None) or exc))
            except Exception as exc:  # noqa: BLE001 - solo se expone el tipo
                fallo = redactar(f"Fallo en la extracción OCR ({type(exc).__name__}).")
        finally:
            try:
                os.remove(ruta_tmp)
            except FileNotFoundError:
                pass
            except OSError:
                _log.warning("No se pudo borrar el archivo temporal del análisis.")

        if fallo is None:
            try:
                payload = json.loads(ocr.text)
            except (TypeError, ValueError) as exc:
                fallo = redactar(f"Fallo en la extracción OCR ({type(exc).__name__}).")
            else:
                if not isinstance(payload, dict):
                    fallo = redactar("Fallo en la extracción OCR (TypeError).")
        if fallo is not None:
            return self._analisis_fallo(fallo)

        campos, no_identificados = _repartir_campos(payload)
        umbral = self.config.policy.umbral_confianza_ocr
        return self._analisis(campos, no_identificados, _advertencias(ocr, umbral))

    # ------------------------------------------------------------------
    def reset(self) -> int:
        with self._repo() as repo:
            return repo.eliminar_por_usuario(self.config.user_id)

    def seed(self, items: Iterable[Any]) -> int:
        """Valida todos los elementos antes de insertar; si alguno falla, no inserta ninguno."""
        datos_lista = [_item_a_dict(i) for i in items]
        for idx, datos in enumerate(datos_lista):
            res = evaluar_factura(datos)
            if not res.valid:
                raise ErrorApi(
                    422,
                    res.first_error_code or "VALIDATION_ERROR",
                    redactar(f"Elemento {idx}: " + "; ".join(res.errors)),
                )
        with self._repo() as repo:
            for datos in datos_lista:
                subtotal = datos.get("subtotal")
                iva = datos.get("iva")
                repo.insert(
                    Transaction(
                        user_id=self.config.user_id,
                        comercio=datos["comercio"],
                        fecha=datos["fecha"],
                        total=float(datos["total"]),
                        moneda=str(datos["moneda"]).strip().upper(),
                        categoria=str(datos["categoria"]).strip(),
                        subtotal=float(subtotal) if subtotal is not None else None,
                        iva=float(iva) if iva is not None else None,
                        descripcion=datos.get("descripcion"),
                    )
                )
        return len(datos_lista)

    def _transaccion_validada(self, datos: dict) -> Transaction:
        datos = {**datos, "categoria": _categoria_canonica(datos.get("categoria"))}
        res = evaluar_factura(datos)
        if not res.valid:
            raise ErrorApi(
                422,
                res.first_error_code or "VALIDATION_ERROR",
                redactar("; ".join(res.errors)),
            )
        subtotal, iva = datos.get("subtotal"), datos.get("iva")
        return Transaction(
            user_id=self.config.user_id,
            comercio=datos["comercio"],
            fecha=datos["fecha"],
            total=float(datos["total"]),
            moneda=str(datos["moneda"]).strip().upper(),
            categoria=str(datos["categoria"]).strip(),
            subtotal=float(subtotal) if subtotal is not None else None,
            iva=float(iva) if iva is not None else None,
            descripcion=datos.get("descripcion"),
        )

    def crear(self, datos: dict) -> Transaction:
        """Valida (R1-R6) e inserta una transacción del usuario configurado."""
        tx = self._transaccion_validada(datos)
        with self._repo() as repo:
            tx.id = repo.insert(tx)
            return repo.get(tx.id, self.config.user_id)

    def actualizar(self, tx_id: int, datos: dict) -> Transaction:
        """Reemplaza los campos de una transacción existente (404 si no existe)."""
        tx = self._transaccion_validada(datos)
        with self._repo() as repo:
            if not repo.update(tx_id, tx):
                raise error_api("TRANSACTION_NOT_FOUND", "Transacción no encontrada.")
            return repo.get(tx_id, self.config.user_id)

    # ------------------------------------------------------------------
    # Internos: solo para el adaptador de herramientas del Pipeline (sin endpoint)
    # ------------------------------------------------------------------
    def duplicados(self, comercio: str, fecha: str, total: float) -> list[Transaction]:
        with self._repo() as repo:
            return _buscar_duplicados(
                repo, comercio, fecha, float(total), self.config.user_id
            )

    def registrar(
        self,
        datos: dict,
        token: str | None,
        high_token: str | None,
        confianza_ocr: float | None = None,
        contenido_sospechoso: bool | None = None,
    ) -> int:
        payload = {
            k: v
            for k, v in datos.items()
            if k
            not in (
                "confirmation_token",
                "high_amount_token",
                "user_id",
                "confianza_ocr",
                "contenido_sospechoso",
                "modo_hitl",
                "umbral_confianza_ocr",
            )
        }
        with self._repo() as repo:
            return _registrar_transaccion(
                repo,
                payload,
                token,
                high_token,
                self.config.policy_dict,
                self.config.user_id,
                confianza_ocr=confianza_ocr,
                contenido_sospechoso=contenido_sospechoso,
            )
