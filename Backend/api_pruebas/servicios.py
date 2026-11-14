# -*- coding: utf-8 -*-
"""
api_pruebas/servicios.py — Servicios de negocio compartidos por HTTP y Pipeline.

Ningún método acepta ``user_id``: siempre se usa ``config.user_id``. Cada operación
abre su propio ``TransactionRepository`` (``with``). Nunca importa ``mcp``.
"""

from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path
from typing import Any, Callable, Iterable

from api_pruebas.config import Config
from api_pruebas.errores import ErrorApi, error_api, redactar
from api_pruebas.esquemas import OcrRespuesta
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

    def ocr_subida(self, nombre: str, contenido: bytes) -> tuple[Path, OcrRespuesta]:
        """Valida extensión (415), firma (415) y tamaño (413) antes de escribir nada."""
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
        destino_dir = self.config.invoices_dir
        destino_dir.mkdir(parents=True, exist_ok=True)
        destino = destino_dir / f"{uuid.uuid4()}{ext}"
        destino.write_bytes(contenido)
        return destino, self.ocr_ruta(destino.name)

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
