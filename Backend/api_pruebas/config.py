"""Configuración interna mínima de la API_Pruebas.

Lee variables de entorno (y ``.env`` vía python-dotenv, sin override: el
entorno del proceso prevalece). Nunca guarda ni serializa claves de API.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from dotenv import load_dotenv

from agent.agent import Policy, load_policy
from finanzas_mcp.business.hitl import PoliticaHitlError

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent

DEFAULT_MAX_BYTES = 10 * 1024 * 1024
DEFAULT_BATCH_MAX = 100


class ConfigError(Exception):
    """Configuración inválida; el mensaje nombra la variable afectada."""


@dataclass(frozen=True)
class Config:
    db_path: Path
    invoices_dir: Path
    user_id: str
    traces_dir: Path
    batch_traces_dir: Path
    batch_max_images: int
    test_mode: bool
    test_db_allowlist: tuple[Path, ...]
    ocr_model: str | None
    policy: Policy
    policy_dict: dict
    max_upload_bytes: int


def _resolver(valor: str) -> Path:
    p = Path(valor).expanduser()
    if not p.is_absolute():
        p = BACKEND_DIR / p
    return Path(os.path.normpath(p))


def _entero(env: Mapping[str, str], nombre: str, default: int, minimo: int, maximo: int | None) -> int:
    crudo = (env.get(nombre) or "").strip()
    if not crudo:
        return default
    try:
        valor = int(crudo)
    except ValueError:
        raise ConfigError(f"{nombre} debe ser un entero") from None
    if valor < minimo or (maximo is not None and valor > maximo):
        rango = f"entre {minimo} y {maximo}" if maximo is not None else f">= {minimo}"
        raise ConfigError(f"{nombre} debe ser un entero {rango}")
    return valor


def cargar_config(env: Mapping[str, str] = os.environ) -> Config:
    if env is os.environ:
        load_dotenv(BACKEND_DIR / ".env", override=False)
        load_dotenv(REPO_DIR / ".env", override=False)

    user_id = (env.get("MCP_USER_ID") or "").strip()
    if not user_id:
        raise ConfigError("MCP_USER_ID es obligatoria y no puede estar vacía")

    db_path = _resolver((env.get("DB_PATH") or "").strip() or "./data/facturas.db")
    invoices_dir = _resolver((env.get("INVOICES_DIR") or "").strip() or "./facturas")
    traces_dir = _resolver((env.get("TRACES_DIR") or "").strip() or "traces")
    batch_raw = (env.get("BATCH_TRACES_DIR") or "").strip()
    batch_traces_dir = _resolver(batch_raw) if batch_raw else traces_dir / "batch"

    batch_max = _entero(env, "BATCH_MAX_IMAGES", DEFAULT_BATCH_MAX, 1, DEFAULT_BATCH_MAX)
    max_bytes = _entero(env, "MAX_IMAGE_BYTES", DEFAULT_MAX_BYTES, 1, None)

    allow_raw = env.get("API_TEST_DB_ALLOWLIST") or ""
    partes = [p.strip() for chunk in allow_raw.split(";") for p in chunk.split(os.pathsep)]
    allowlist = tuple(_resolver(p) for p in dict.fromkeys(partes) if p)

    politica_path = BACKEND_DIR / "politica.json"
    try:
        policy = load_policy(str(politica_path))
        with open(politica_path, encoding="utf-8") as fh:
            policy_dict = json.load(fh)
    except PoliticaHitlError as exc:
        raise ConfigError(f"Política HITL inválida en politica.json: {exc}") from None
    except (OSError, ValueError) as exc:
        raise ConfigError(f"No se pudo leer politica.json: {type(exc).__name__}") from None

    return Config(
        db_path=db_path,
        invoices_dir=invoices_dir,
        user_id=user_id,
        traces_dir=traces_dir,
        batch_traces_dir=batch_traces_dir,
        batch_max_images=batch_max,
        test_mode=(env.get("API_TEST_MODE") or "").strip().lower() == "true",
        test_db_allowlist=allowlist,
        ocr_model=(env.get("OCR_MODEL") or "").strip() or None,
        policy=policy,
        policy_dict=policy_dict,
        max_upload_bytes=max_bytes,
    )
