# -*- coding: utf-8 -*-
"""
ocr_mcp/ocr_client.py
---------------------
Vision LLM wrapper for invoice OCR.

The ``OcrClient`` class encodes an invoice image as base64 and sends it to a
vision-capable LLM (OpenAI GPT-4o or Anthropic Claude) asking for structured JSON
extraction of invoice fields.

The returned ``OcrResult`` has ``is_untrusted=True`` unconditionally — this is
enforced by the ``OcrResult`` dataclass default and is never overridden here.
All diagnostic output goes to ``sys.stderr``; nothing is written to stdout.
"""

from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage

from finanzas_mcp.constantes import CATEGORIAS_CERRADAS
from finanzas_mcp.models import OcrResult
from ocr_mcp.ocr_core import calcular_confianzas

# ---------------------------------------------------------------------------
# Prompt engineering
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "You are an invoice data-extraction engine. "
    "You receive an image of a receipt or invoice and you return ONLY a valid "
    "JSON object — no markdown, no explanation, no extra text. "
    "The JSON must have exactly the following keys "
    "(use null for fields that are not present or unreadable):\n"
    "  comercio   - string: merchant / store name\n"
    "  fecha      - string: transaction date in YYYY-MM-DD format\n"
    "  total      - number: final amount paid\n"
    "  moneda     - string: currency code (CRC or USD only)\n"
    "  subtotal   - number or null: pre-tax subtotal\n"
    "  iva        - number or null: tax amount\n"
    "  categoria  - string or null: expense category; use EXACTLY one of: "
    + ", ".join(CATEGORIAS_CERRADAS)
    + " (null if none fits)\n"
    "  descripcion - string or null: brief description of the purchase\n"
    "In addition, include a 'confidence' object whose keys are those same "
    "field names and whose values are floats from 0.0 to 1.0 representing "
    "how confident you are in each extracted value (0.0 = not found / "
    "unreadable, 1.0 = fully confident).\n"
    "Example output skeleton (do NOT copy these values):\n"
    '{"comercio":"...", "fecha":"...", "total":..., "moneda":"...", '
    '"subtotal":..., "iva":..., "categoria":"...", "descripcion":"...", '
    '"confidence":{"comercio":0.95,"fecha":0.9,"total":0.99,"moneda":0.9,'
    '"subtotal":0.8,"iva":0.8,"categoria":0.6,"descripcion":0.7}}'
)

# Fields that are considered required for overall confidence computation.
_REQUIRED_FIELDS: list[str] = ["comercio", "fecha", "total", "moneda"]

# A field is considered "low confidence" when its individual score is below
# this threshold.
_LOW_CONFIDENCE_THRESHOLD: float = 0.75


# claude-3-5-sonnet-latest fue retirado por Anthropic (la API responde 404 NotFoundError).
_DEFAULT_MODELS = {"openai": "gpt-4o", "anthropic": "claude-sonnet-5-5"}
_KEY_ENV = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}


def resolve_provider(provider: str | None = None) -> str:
    """Elige el proveedor: argumento > LLM_PROVIDER > clave disponible > openai."""
    chosen = (provider or os.environ.get("LLM_PROVIDER") or "").strip().lower()
    if chosen:
        if chosen not in _KEY_ENV:
            raise ValueError(
                f"LLM_PROVIDER inválido: '{chosen}'. Use 'openai' o 'anthropic'."
            )
        return chosen
    if not os.environ.get("OPENAI_API_KEY") and os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    return "openai"


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class OcrClient:
    """Wraps a vision LLM call to extract structured data from an invoice image.

    Parameters
    ----------
    model:
        OpenAI model name that supports vision.  Defaults to ``"gpt-4o"``.
    api_key:
        OpenAI API key.  If not supplied, falls back to the ``OPENAI_API_KEY``
        environment variable (standard LangChain / OpenAI behaviour).
    temperature:
        LLM temperature.  If ``None`` (default), OpenAI uses 0 for maximum
        determinism and Anthropic omits the parameter: recent Claude models
        reject it with ``400 BadRequestError`` ("`temperature` is deprecated").

    Notes
    -----
    ``OcrResult.is_untrusted`` is *always* ``True`` — this invariant is
    enforced by the dataclass default and is **never** altered by this class
    (Requirement 1.5).
    """

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        temperature: float | None = None,
        provider: str | None = None,
    ) -> None:
        self._provider = resolve_provider(provider)
        model = model or _DEFAULT_MODELS[self._provider]
        key_var = _KEY_ENV[self._provider]
        resolved_key = api_key or os.environ.get(key_var)
        if not resolved_key:
            print(
                f"[ocr_client] WARNING: {key_var} is not set. "
                "LLM calls will fail unless the key is provided at runtime.",
                file=sys.stderr,
            )

        if self._provider == "anthropic":
            from langchain_anthropic import ChatAnthropic  # import diferido

            extra: dict = {} if temperature is None else {"temperature": temperature}
            self._llm = ChatAnthropic(
                model=model,
                api_key=resolved_key,  # type: ignore[arg-type]
                max_tokens=1024,
                **extra,
            )
        else:
            from langchain_openai import ChatOpenAI  # import diferido

            self._llm = ChatOpenAI(
                model=model,
                temperature=0 if temperature is None else temperature,
                api_key=resolved_key,  # type: ignore[arg-type]
                max_tokens=1024,
            )
        self._model = model
        self._ultimo_uso: dict[str, int] = {"entrada": 0, "salida": 0}
        print(
            f"[ocr_client] Initialized with provider={self._provider} model={model}",
            file=sys.stderr,
        )
    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract(self, image_path: str) -> OcrResult:
        """Extract invoice fields from an image file.

        Parameters
        ----------
        image_path:
            Absolute path to the image file (jpg, jpeg, png, or pdf).

        Returns
        -------
        OcrResult
            Structured extraction result.  ``is_untrusted`` is always ``True``.
            ``text`` contains the raw JSON string returned by the LLM.
            ``confidence`` is the mean confidence over the required fields.
            ``low_confidence_fields`` lists fields with confidence < 0.75.

        Raises
        ------
        FileNotFoundError
            If the image file does not exist.
        ValueError
            If the LLM response cannot be parsed as JSON.
        """
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"Image file not found: {image_path}")

        print(f"[ocr_client] Reading image: {path.name}", file=sys.stderr)
        image_data = self._encode_image(path)
        mime_type = self._mime_type(path)

        print(
            f"[ocr_client] Sending {len(image_data)} base64 chars to {self._model}",
            file=sys.stderr,
        )

        raw_response = self._call_llm(image_data, mime_type)
        print(f"[ocr_client] Raw LLM response length: {len(raw_response)}", file=sys.stderr)

        resultado = self._parse_response(raw_response)
        resultado.uso_tokens = dict(self._ultimo_uso)
        return resultado

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _encode_image(path: Path) -> str:
        """Return the image content as a base64-encoded ASCII string."""
        with open(path, "rb") as fh:
            return base64.standard_b64encode(fh.read()).decode("ascii")

    @staticmethod
    def _mime_type(path: Path) -> str:
        """Derive the MIME type from the file extension."""
        ext = path.suffix.lower()
        mime_map: dict[str, str] = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".pdf": "application/pdf",
        }
        return mime_map.get(ext, "image/jpeg")

    def _call_llm(self, image_data: str, mime_type: str) -> str:
        """Send the base64 image to the vision LLM and return the raw text."""
        if self._provider == "anthropic":
            if mime_type == "application/pdf":
                media = {
                    "type": "document",
                    "source": {"type": "base64", "media_type": mime_type, "data": image_data},
                }
            else:
                media = {
                    "type": "image",
                    "source": {"type": "base64", "media_type": mime_type, "data": image_data},
                }
        else:
            media = {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{mime_type};base64,{image_data}",
                    "detail": "high",
                },
            }
        message = HumanMessage(content=[{"type": "text", "text": _SYSTEM_PROMPT}, media])
        self._ultimo_uso = {"entrada": 0, "salida": 0}
        response = self._llm.invoke([message])
        uso = getattr(response, "usage_metadata", None)
        if isinstance(uso, dict):
            try:
                self._ultimo_uso = {
                    "entrada": int(uso.get("input_tokens") or 0),
                    "salida": int(uso.get("output_tokens") or 0),
                }
            except (TypeError, ValueError):
                print("[ocr_client] WARNING: usage_metadata inválido", file=sys.stderr)
        return str(response.content)

    def _parse_response(self, raw: str) -> OcrResult:
        """Parse the LLM JSON response into an ``OcrResult``.

        The function is tolerant of minor formatting issues (e.g. markdown
        code fences) but always returns ``is_untrusted=True``.
        """
        # Strip markdown code fences if present
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            # Remove opening fence (``` or ```json) and closing fence
            start = 1 if lines[0].startswith("```") else 0
            end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
            cleaned = "\n".join(lines[start:end])

        try:
            data: dict[str, Any] = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            print(
                f"[ocr_client] ERROR: could not parse LLM response as JSON: {exc}",
                file=sys.stderr,
            )
            print(f"[ocr_client] Raw response was: {raw[:500]}", file=sys.stderr)
            # Return a minimal OcrResult that signals failure via zero confidence
            return OcrResult(
                text=raw,
                confidence=0.0,
                is_untrusted=True,
                low_confidence_fields=_REQUIRED_FIELDS[:],
                confianza_ocr=0.0,
                confianza_campos={},
            )

        # Extract the per-field confidence map (default to 0.0 for missing entries)
        confidence_map: dict[str, float] = {}
        raw_conf = data.pop("confidence", {})
        confianza_global, confianza_campos, _ = calcular_confianzas(data, raw_conf)
        if isinstance(raw_conf, dict):
            for k, v in raw_conf.items():
                try:
                    confidence_map[k] = float(v)
                except (TypeError, ValueError):
                    confidence_map[k] = 0.0

        # Compute overall confidence as the mean over the required fields
        required_scores = [
            confidence_map.get(f, 0.0) for f in _REQUIRED_FIELDS
        ]
        overall_confidence = (
            sum(required_scores) / len(required_scores) if required_scores else 0.0
        )

        # Collect fields with low individual confidence
        all_fields = list(data.keys()) + [
            f for f in _REQUIRED_FIELDS if f not in data
        ]
        low_confidence_fields = [
            f
            for f in all_fields
            if confidence_map.get(f, 0.0) < _LOW_CONFIDENCE_THRESHOLD
        ]

        # Serialise the structured payload back to a JSON string for `text`
        text_payload = json.dumps(data, ensure_ascii=False)

        print(
            f"[ocr_client] Parsed OK — overall_confidence={overall_confidence:.3f}, "
            f"low_confidence_fields={low_confidence_fields}",
            file=sys.stderr,
        )

        return OcrResult(
            text=text_payload,
            confidence=round(overall_confidence, 4),
            is_untrusted=True,  # ALWAYS True — Requirement 1.5
            low_confidence_fields=low_confidence_fields,
            confianza_ocr=confianza_global,
            confianza_campos=confianza_campos,
        )
