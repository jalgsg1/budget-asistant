# -*- coding: utf-8 -*-
"""
baseline/llm.py
---------------
Configuración y cliente LLM compartidos por los tres sistemas evaluados.

No importa ``ocr_mcp`` ni ``finanzas_mcp``: los baselines no dependen de
``ocr-mcp`` (Req. 9.4, 10.10). Los parámetros del modelo replican los de
``OcrClient`` (``max_tokens=1024``; temperatura 0 en OpenAI, omitida en
Anthropic).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

_CLAVES_PROVEEDOR = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}


@dataclass(frozen=True)
class ConfigLlm:
    proveedor: str  # "openai" | "anthropic"
    modelo: str  # OCR_MODEL
    api_key_var: str


class ConfigLlmError(Exception):
    """Configuración incompleta o inválida; el mensaje nombra cada variable."""


def resolver_config_llm(env: Mapping[str, str]) -> ConfigLlm:
    """Exige LLM_PROVIDER, OCR_MODEL y la clave del proveedor."""
    proveedor = (env.get("LLM_PROVIDER") or "").strip().lower()
    modelo = (env.get("OCR_MODEL") or "").strip()
    faltantes: list[str] = []
    if not proveedor:
        faltantes.append("LLM_PROVIDER")
    if not modelo:
        faltantes.append("OCR_MODEL")
    if proveedor and proveedor not in _CLAVES_PROVEEDOR:
        raise ConfigLlmError(
            f"LLM_PROVIDER inválido: '{proveedor}'. Use 'openai' o 'anthropic'."
            + (f" Faltan además: {', '.join(faltantes)}." if faltantes else "")
        )
    if proveedor:
        clave = _CLAVES_PROVEEDOR[proveedor]
        if not (env.get(clave) or "").strip():
            faltantes.append(clave)
    else:
        clave = ""
    if faltantes:
        raise ConfigLlmError(
            "Faltan variables de entorno: " + ", ".join(faltantes)
        )
    return ConfigLlm(proveedor=proveedor, modelo=modelo, api_key_var=clave)


@dataclass(frozen=True)
class RespuestaLlm:
    llamadas_herramienta: list[dict]  # [{"nombre": str, "args": dict}]
    tokens_entrada: int
    tokens_salida: int


class ClienteLlm(Protocol):
    def invocar(
        self, system_prompt: str, imagen_b64: str, mime: str, herramienta: dict
    ) -> RespuestaLlm: ...


class ClienteLangChain:
    """Implementación real con ``bind_tools``.

    Parameters
    ----------
    config:
        ``ConfigLlm`` resuelto con ``resolver_config_llm``.
    api_key:
        Clave del proveedor. Si es ``None`` se lee de ``config.api_key_var``.
    temperature:
        ``None``: 0 en OpenAI y omitida en Anthropic (igual que ``OcrClient``).
    """

    def __init__(
        self,
        config: ConfigLlm,
        api_key: str | None = None,
        temperature: float | None = None,
    ) -> None:
        import os

        self._config = config
        resolved_key = api_key or os.environ.get(config.api_key_var)
        if config.proveedor == "anthropic":
            from langchain_anthropic import ChatAnthropic  # import diferido

            extra: dict = {} if temperature is None else {"temperature": temperature}
            self._llm: Any = ChatAnthropic(
                model=config.modelo,
                api_key=resolved_key,  # type: ignore[arg-type]
                max_tokens=1024,
                **extra,
            )
        else:
            from langchain_openai import ChatOpenAI  # import diferido

            self._llm = ChatOpenAI(
                model=config.modelo,
                temperature=0 if temperature is None else temperature,
                api_key=resolved_key,  # type: ignore[arg-type]
                max_tokens=1024,
            )
        print(
            f"[baseline.llm] provider={config.proveedor} model={config.modelo}",
            file=sys.stderr,
        )

    def _media(self, imagen_b64: str, mime: str) -> dict:
        if self._config.proveedor == "anthropic":
            tipo = "document" if mime == "application/pdf" else "image"
            return {
                "type": tipo,
                "source": {"type": "base64", "media_type": mime, "data": imagen_b64},
            }
        return {
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{imagen_b64}", "detail": "high"},
        }

    def invocar(
        self, system_prompt: str, imagen_b64: str, mime: str, herramienta: dict
    ) -> RespuestaLlm:
        from langchain_core.messages import HumanMessage, SystemMessage

        mensajes = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=[self._media(imagen_b64, mime)]),
        ]
        respuesta = self._llm.bind_tools([herramienta]).invoke(mensajes)
        llamadas = [
            {"nombre": str(c.get("name", "")), "args": dict(c.get("args") or {})}
            for c in (getattr(respuesta, "tool_calls", None) or [])
        ]
        entrada = salida = 0
        uso = getattr(respuesta, "usage_metadata", None)
        if isinstance(uso, dict):
            try:
                entrada = int(uso.get("input_tokens") or 0)
                salida = int(uso.get("output_tokens") or 0)
            except (TypeError, ValueError):
                print("[baseline.llm] WARNING: usage_metadata inválido", file=sys.stderr)
        return RespuestaLlm(
            llamadas_herramienta=llamadas, tokens_entrada=entrada, tokens_salida=salida
        )
