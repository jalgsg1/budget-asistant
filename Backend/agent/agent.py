# -*- coding: utf-8 -*-
"""
Agente de gestor-facturas.

Contiene:

* Carga de ``politica.json`` y contadores de límites (Tarea 10.1; el archivo
  no existía en disco al ejecutar la 10.2, por lo que se incluye aquí).
* El pipeline SKILL de seis pasos (Tarea 10.2):
  Extraer -> Validar -> Aritmética -> Duplicados -> Confirmar -> Registrar.

Diseño para pruebas
-------------------
El pipeline no importa ``mcp`` ni ``langchain``.  Las herramientas se inyectan
como un diccionario ``{nombre: callable(dict) -> resultado}`` y la interacción
con el usuario mediante un objeto con ``ask``/``notify`` (``UserIO``).  Una
herramienta que falla por regla de negocio debe lanzar ``ToolError`` (ver
``normalize_tool_result`` para adaptar respuestas MCP con ``isError``).

Seguridad (R10)
---------------
Todo el contenido de ``OcrResult`` es dato no confiable.  Solo se extraen de él
valores para una lista blanca de campos, con tipo y longitud acotados.  Nunca
se interpola en prompts, nunca se usa para elegir herramientas ni para
modificar el flujo.  El texto OCR completo no se guarda en la traza.
"""

from __future__ import annotations

import json
import re
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Optional, Protocol

from agent.tracer import Trace, TraceEntry, write_trace
from finanzas_mcp.business.categorias import CLOSED_CATEGORY_LIST

# ---------------------------------------------------------------------------
# Errores
# ---------------------------------------------------------------------------


class StepLimitError(Exception):
    """Se superó el StepLimit configurado."""


class TokenLimitError(Exception):
    """Se alcanzó el TokenLimit configurado."""


class PolicyError(Exception):
    """Se intentó usar una herramienta no permitida por la política."""


class ToolError(Exception):
    """Una herramienta devolvió ``isError`` (violación de regla de negocio)."""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


class _Stop(Exception):
    """Interna: termina el pipeline sin registrar."""

    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        self.message = message
        super().__init__(message)


# ---------------------------------------------------------------------------
# Política y contadores (Tarea 10.1)
# ---------------------------------------------------------------------------

_PERMITIDA = "permitida"
_REQUIERE_CONFIRMACION = "requiere_confirmacion"


@dataclass
class Policy:
    tools: dict[str, str] = field(default_factory=dict)
    step_limit: int = 8
    token_limit: int = 4000
    high_amount_threshold: dict[str, float] = field(default_factory=dict)
    max_date_range_days: int = 90
    allowed_filters: list[str] = field(default_factory=list)

    @property
    def allowed_tools(self) -> set[str]:
        return {n for n, p in self.tools.items() if p in (_PERMITIDA, _REQUIERE_CONFIRMACION)}

    @property
    def confirmation_tools(self) -> set[str]:
        return {n for n, p in self.tools.items() if p == _REQUIERE_CONFIRMACION}

    @property
    def denied_tools(self) -> set[str]:
        return {n for n, p in self.tools.items() if p not in (_PERMITIDA, _REQUIERE_CONFIRMACION)}


def load_policy(path: str) -> Policy:
    """Lee ``politica.json`` (UTF-8) y construye la ``Policy``."""
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    return Policy(
        tools=dict(raw.get("tools", {})),
        step_limit=int(raw.get("step_limit", 8)),
        token_limit=int(raw.get("token_limit", 4000)),
        high_amount_threshold={k: float(v) for k, v in raw.get("high_amount_threshold", {}).items()},
        max_date_range_days=int(raw.get("max_date_range_days", 90)),
        allowed_filters=list(raw.get("allowed_filters", [])),
    )


class StepCounter:
    """Cuenta pasos; permite ``limit`` pasos y lanza al intentar el siguiente."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.count = 0

    def increment(self) -> int:
        if self.count >= self.limit:
            raise StepLimitError(f"StepLimit de {self.limit} pasos alcanzado.")
        self.count += 1
        return self.count


class TokenCounter:
    """Acumula tokens; lanza al alcanzar o superar ``limit``."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.total = 0

    def add(self, tokens: int) -> int:
        self.total += max(0, int(tokens))
        if self.total >= self.limit:
            raise TokenLimitError(f"TokenLimit de {self.limit} tokens alcanzado.")
        return self.total


# ---------------------------------------------------------------------------
# Interfaces inyectables
# ---------------------------------------------------------------------------


class UserIO(Protocol):
    def ask(self, prompt: str) -> Optional[str]:
        """Pide una respuesta; ``None`` o vacío = sin respuesta."""

    def notify(self, message: str) -> None:
        """Muestra un mensaje al usuario."""


@dataclass
class PipelineResult:
    status: str                      # success | validation_error | step_limit | token_limit | user_abort
    termination_reason: str          # success | validation_failure | step_limit | token_limit | user_rejection
    message: str = ""
    transaction_id: Optional[int] = None
    datos: dict = field(default_factory=dict)
    trace: Optional[Trace] = None


def normalize_tool_result(raw: Any) -> Any:
    """Adapta una respuesta MCP a dato Python o lanza ``ToolError``.

    Acepta: dict/list ya parseado, JSON en ``str``, o ``{"isError": True,
    "content": [{"text": "[CODE] mensaje"}]}``.
    """
    if isinstance(raw, dict) and raw.get("isError"):
        content = raw.get("content") or [{}]
        text = str((content[0] or {}).get("text", "")) if isinstance(content, list) else str(content)
        m = re.match(r"\s*\[([A-Z_]+)\]\s*(.*)", text, re.S)
        raise ToolError(m.group(1) if m else "TOOL_ERROR", m.group(2) if m else text)
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except ValueError:
            return raw
    return raw


# ---------------------------------------------------------------------------
# Constantes del pipeline
# ---------------------------------------------------------------------------

REQUIRED_FIELDS = ("comercio", "fecha", "total", "moneda", "categoria")
OPTIONAL_FIELDS = ("subtotal", "iva", "descripcion")
ALLOWED_FIELDS = REQUIRED_FIELDS + OPTIONAL_FIELDS
_NUMERIC = {"total", "subtotal", "iva"}
_OCR_REQUIRED = ("comercio", "fecha", "total", "moneda")
LOW_CONFIDENCE_THRESHOLD = 0.75
_MAX_TEXT = 200
_YES = {"si", "sí", "s", "yes", "y"}
_NO = {"no", "n", "cancelar", "cancel"}

_INJECTION_PATTERNS = [
    re.compile(p, re.I)
    for p in (
        r"\bsystem\s*:",
        r"ignore\s+(all\s+)?(previous|prior)\s+instructions",
        r"ignora\s+(las\s+)?instrucciones",
        r"\b(drop|delete|insert|update)\s+\w*\s*(table|from|into)\b",
        r"\bselect\b.+\bfrom\b",
        r"[A-Za-z0-9+/]{40,}={0,2}",  # posible payload base64
        r"\b(transfer|exfiltrate|reveal)\b",
    )
]


def _default_token_estimate(*parts: Any) -> int:
    return sum(len(json.dumps(p, ensure_ascii=False, default=str)) for p in parts) // 4 + 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class InvoicePipeline:
    """Ejecuta los seis pasos del SKILL para una imagen de factura."""

    def __init__(
        self,
        tools: Mapping[str, Callable[[dict], Any]],
        io: UserIO,
        policy: Policy,
        user_id: str,
        traces_dir: Optional[str] = None,
        estimate_tokens: Callable[..., int] = _default_token_estimate,
    ) -> None:
        self._tools = tools
        self._io = io
        self._policy = policy
        self._user_id = user_id
        self._traces_dir = traces_dir
        self._estimate = estimate_tokens
        self._steps = StepCounter(policy.step_limit)
        self._tokens = TokenCounter(policy.token_limit)
        self._trace = Trace(trace_id="", user_id=user_id, image_path="")

    # -- API -----------------------------------------------------------------

    def run(self, image_path: str) -> PipelineResult:
        self._trace = Trace(
            trace_id=str(uuid.uuid4()), user_id=self._user_id,
            image_path=image_path, created_at=_now(),
        )
        status, reason, message, tx_id, datos = "validation_error", "validation_failure", "", None, {}
        try:
            datos = self._step1_extraer(image_path)
            self._step2_3_validar(datos)
            self._step4_duplicados(datos)
            token, high_token = self._step5_confirmar(datos)
            tx_id = self._step6_registrar(datos, token, high_token)
            status, reason = "success", "success"
            message = f"Transacción registrada con id={tx_id}."
        except StepLimitError as exc:
            status, reason, message = "step_limit", "step_limit", str(exc)
        except TokenLimitError as exc:
            status, reason, message = "token_limit", "token_limit", str(exc)
        except _Stop as stop:
            reason, message = stop.reason, stop.message
            status = "user_abort" if reason == "user_rejection" else "validation_error"
        except PolicyError as exc:
            reason, message = "validation_failure", f"Política: {exc}"

        if status != "success":
            message = f"{message} La transacción NO fue guardada."
        self._log("termination", "", message, None)
        self._trace.final_status = status
        self._trace.termination_reason = reason
        self._trace.transaction_id = tx_id
        self._io.notify(message)
        if self._traces_dir:
            write_trace(self._trace, self._traces_dir)
        return PipelineResult(status, reason, message, tx_id, dict(datos), self._trace)

    # -- Infraestructura -----------------------------------------------------

    def _log(self, action: str, inp: str, out: str, tool: Optional[str]) -> None:
        self._trace.entries.append(TraceEntry(
            step=self._steps.count, action=action, input_summary=inp[:300],
            output_summary=out[:300], tool_called=tool, timestamp=_now(),
        ))

    def _call(self, name: str, args: dict, confirmed: bool = False) -> Any:
        """Llama una herramienta aplicando política, límites y traza."""
        if name not in self._policy.allowed_tools or name not in self._tools:
            raise PolicyError(f"herramienta '{name}' no permitida")
        if name in self._policy.confirmation_tools and not confirmed:
            raise PolicyError(f"herramienta '{name}' requiere confirmación explícita")
        self._steps.increment()
        try:
            result = normalize_tool_result(self._tools[name](args))
        except ToolError as err:
            self._log(name, _summ(args), f"error {err.code}", name)
            self._tokens.add(self._estimate(args, err.code))
            raise
        self._log(name, _summ(args), "ok", name)
        self._tokens.add(self._estimate(args, result))
        return result

    def _ask(self, prompt: str, action: str) -> Optional[str]:
        """Pide dato al usuario; cuenta como paso de decisión."""
        self._steps.increment()
        answer = self._io.ask(prompt)
        answer = answer.strip() if isinstance(answer, str) else None
        answer = answer or None
        self._log(action, prompt, "respuesta" if answer else "sin respuesta", None)
        self._tokens.add(self._estimate(prompt, answer))
        return answer

    def _confirm(self, prompt: str, action: str) -> bool:
        ans = self._ask(prompt, action)
        return ans is not None and ans.lower() in _YES

    def _token(self, prompt: str, action: str) -> Optional[str]:
        """Token explícito: cualquier texto no vacío que no sea una negativa."""
        ans = self._ask(prompt, action)
        if ans is None or ans.lower() in _NO:
            return None
        return ans

    # -- Paso 1: Extraer -----------------------------------------------------

    def _step1_extraer(self, image_path: str) -> dict:
        ocr = self._ocr(image_path)
        if _is_low(ocr):
            self._log("ocr_retry", "confianza baja", "reintento", None)
            ocr = self._ocr(image_path)
        datos = _map_fields(ocr["text"])
        self._flag_injection(ocr["text"], datos)
        if _is_low(ocr):
            low = [f for f in ocr["low"] if f in ALLOWED_FIELDS] or [
                f for f in _OCR_REQUIRED if datos.get(f) is None
            ]
            for f in low:
                self._clarify(datos, f)
        return datos

    def _ocr(self, image_path: str) -> dict:
        raw = self._call("ocr_imagen", {"ruta": image_path})
        # R10: se marca siempre como no confiable, sin importar lo que declare.
        res = raw.get("result", raw) if isinstance(raw, dict) else {}
        text = res.get("text", "") if isinstance(res, dict) else ""
        try:
            conf = float(res.get("confidence", 0.0))
        except (TypeError, ValueError):
            conf = 0.0
        low = res.get("low_confidence_fields", [])
        low = [str(x) for x in low] if isinstance(low, list) else []
        return {"text": text if isinstance(text, str) else "", "confidence": conf,
                "low": low, "is_untrusted": True}

    def _clarify(self, datos: dict, f: str) -> None:
        shown = datos.get(f)
        ans = self._ask(
            f"Baja confianza en '{f}' (valor leído como dato: {shown!r}). "
            f"Escriba el valor correcto o Enter para dejarlo: ", "clarify_field",
        )
        if ans is None:
            if datos.get(f) is None:
                raise _Stop("validation_failure", f"No se aclaró el campo '{f}'.")
            return
        value = _coerce(f, ans)
        if value is None:
            raise _Stop("validation_failure", f"Valor inválido para '{f}'.")
        datos[f] = value

    def _flag_injection(self, text: str, datos: dict) -> None:
        values = [text] + [v for v in datos.values() if isinstance(v, str)]
        if any(p.search(v) for v in values for p in _INJECTION_PATTERNS):
            self._log("suspicious_data_detected", "contenido OCR", "tratado como dato; no ejecutado", None)

    # -- Pasos 2 y 3: Validar / Aritmética -----------------------------------

    def _step2_3_validar(self, datos: dict) -> None:
        while True:
            if datos.get("categoria") not in CLOSED_CATEGORY_LIST:
                self._select_category(datos)  # R6: antes de validar_factura
            try:
                self._call("validar_factura", _payload(datos))
                return
            except ToolError as err:
                self._fix(datos, err)

    def _fix(self, datos: dict, err: ToolError) -> None:
        code = err.code
        if code == "MISSING_FIELDS":
            missing = [f for f in REQUIRED_FIELDS if datos.get(f) in (None, "")]
            if not missing:
                raise _Stop("validation_failure", f"Validación fallida: {err.message}")
            for f in missing:
                self._ask_field(datos, f)
        elif code == "INVALID_CURRENCY":
            self._ask_field(datos, "moneda", "Moneda inválida. Use CRC o USD")
        elif code in ("INVALID_DATE_FORMAT", "FUTURE_DATE"):
            self._ask_field(datos, "fecha", "Fecha inválida o futura. Use YYYY-MM-DD")
        elif code == "INVALID_CATEGORY":
            self._select_category(datos)
        elif code == "ARITHMETIC_INCONSISTENCY":
            self._fix_arithmetic(datos)
        else:
            raise _Stop("validation_failure", f"Validación fallida: {err.message or code}")

    def _ask_field(self, datos: dict, f: str, hint: str = "") -> None:
        if f == "categoria":
            return self._select_category(datos)
        ans = self._ask(f"{hint or 'Falta el campo'} '{f}': ", "ask_field")
        value = _coerce(f, ans) if ans else None
        if value is None:
            raise _Stop("validation_failure", f"No se obtuvo un valor válido para '{f}'.")
        datos[f] = value

    def _select_category(self, datos: dict) -> None:
        options = "\n".join(f"  {i}. {c}" for i, c in enumerate(CLOSED_CATEGORY_LIST, 1))
        ans = self._ask(f"Categoría no reconocida o ambigua. Elija una:\n{options}\nSelección: ", "select_category")
        chosen = None
        if ans:
            if ans.isdigit() and 1 <= int(ans) <= len(CLOSED_CATEGORY_LIST):
                chosen = CLOSED_CATEGORY_LIST[int(ans) - 1]
            else:
                chosen = next((c for c in CLOSED_CATEGORY_LIST if c.lower() == ans.lower()), None)
        if chosen is None:
            raise _Stop("validation_failure", "No se seleccionó una categoría válida.")
        datos["categoria"] = chosen

    def _fix_arithmetic(self, datos: dict) -> None:
        ans = self._ask(
            f"Incoherencia: subtotal={datos.get('subtotal')} + iva={datos.get('iva')} "
            f"!= total={datos.get('total')}. ¿Qué campo es incorrecto y debe corregirse "
            f"(subtotal/iva/total)? ",
            "arithmetic_choice",
        )
        target = ans.lower() if ans else None
        if target not in ("subtotal", "iva", "total"):
            raise _Stop("validation_failure", "No se aclaró la incoherencia aritmética.")
        self._ask_field(datos, target, "Valor correcto para")

    # -- Paso 4: Duplicados --------------------------------------------------

    def _step4_duplicados(self, datos: dict) -> bool:
        # user_id lo inyecta el servidor desde la sesión; no se envía en el payload.
        res = self._call("buscar_duplicados",
                         {k: datos[k] for k in ("comercio", "fecha", "total")})
        if isinstance(res, dict):
            res = res.get("duplicados", res.get("result", []))
        matches = res if isinstance(res, list) else []
        if not matches:
            return False
        lines = "\n".join(
            f"  - {m.get('comercio')} | {m.get('fecha')} | {m.get('total')} {m.get('moneda', '')}"
            for m in matches if isinstance(m, dict)
        )
        if not self._confirm(f"Posibles duplicados:\n{lines}\n¿Registrar de todos modos? (si/no): ",
                             "duplicate_confirmation"):
            raise _Stop("user_rejection", "El usuario no confirmó continuar tras detectar duplicados.")
        return True

    # -- Paso 5: Confirmación ------------------------------------------------

    def _step5_confirmar(self, datos: dict) -> tuple[str, Optional[str]]:
        high_token = None
        threshold = self._policy.high_amount_threshold.get(datos["moneda"])
        if threshold is not None and datos["total"] > threshold:
            high_token = self._token(
                f"Monto alto: {datos['total']} {datos['moneda']} (umbral {threshold}). "
                "Escriba el token de confirmación de monto alto (o 'no'): ",
                "high_amount_confirmation",
            )
            if high_token is None:
                raise _Stop("user_rejection", "No se proporcionó la confirmación de monto alto.")
        token = self._token("Escriba el token de confirmación para registrar (o 'no'): ",
                            "confirmation_token")
        if token is None:
            raise _Stop("user_rejection", "No se proporcionó el token de confirmación.")
        return token, high_token

    # -- Paso 6: Registrar ---------------------------------------------------

    def _step6_registrar(self, datos: dict, token: str, high_token: Optional[str]) -> Optional[int]:
        args = _payload(datos)
        args["confirmation_token"] = token
        if high_token is not None:
            args["high_amount_token"] = high_token
        try:
            res = self._call("registrar_transaccion", args, confirmed=True)
        except ToolError as err:
            raise _Stop("validation_failure", f"El servidor rechazó el registro: {err.message or err.code}")
        return res.get("id") if isinstance(res, dict) else None


# ---------------------------------------------------------------------------
# Utilidades puras
# ---------------------------------------------------------------------------


def _is_low(ocr: dict) -> bool:
    return ocr["confidence"] < LOW_CONFIDENCE_THRESHOLD or bool(ocr["low"])


def _clean(s: str) -> str:
    return re.sub(r"[\x00-\x1f\x7f]", " ", s).strip()[:_MAX_TEXT]


def _coerce(f: str, value: Any) -> Any:
    """Convierte a tipo esperado; ``None`` si no es válido o está vacío."""
    if value is None or isinstance(value, bool):
        return None
    if f in _NUMERIC:
        try:
            return float(str(value).replace(",", "").strip()) if not isinstance(value, (int, float)) else float(value)
        except ValueError:
            return None
    if not isinstance(value, str):
        return None
    value = _clean(value)
    return value or None


def _map_fields(text: str) -> dict:
    """Mapea el texto OCR (JSON) a la lista blanca de campos.  Todo lo demás se ignora."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    out = {f: _coerce(f, data.get(f)) for f in ALLOWED_FIELDS}
    return {k: v for k, v in out.items() if v is not None}


def _payload(datos: dict) -> dict:
    return {k: datos[k] for k in ALLOWED_FIELDS if datos.get(k) is not None}


def _summ(args: dict) -> str:
    """Resumen sin valores de texto libre (evita guardar contenido OCR en la traza)."""
    parts = [f"keys={sorted(k for k in args if 'token' not in k)}"]
    for k in ("total", "moneda"):
        if k in args:
            parts.append(f"{k}={str(args[k])[:20]}")
    if any("token" in k for k in args):
        parts.append("token=<provisto>")
    return " ".join(parts)


if __name__ == "__main__":  # pragma: no cover
    print("Use agent.main (tarea 12) para ejecutar el pipeline.", file=sys.stderr)
