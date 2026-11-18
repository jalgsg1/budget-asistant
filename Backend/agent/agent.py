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

import hashlib
import json
import math
import re
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Callable, Mapping, Optional, Protocol

from agent.constantes import (
    ALLOWED_FIELDS as _ALLOWED_FIELDS,
    ESTADO_ABORTO_USUARIO,
    ESTADO_ERROR_VALIDACION,
    ESTADO_EXITO,
    ESTADO_LIMITE_PASOS,
    ESTADO_LIMITE_TOKENS,
    OCR_REQUIRED_FIELDS,
    OPTIONAL_FIELDS as _OPTIONAL_FIELDS,
    RAZON_EXITO,
    RAZON_FALLO_VALIDACION,
    RAZON_LIMITE_PASOS,
    RAZON_LIMITE_TOKENS,
    RAZON_RECHAZO_USUARIO,
    REQUIRED_FIELDS as _REQUIRED_FIELDS,
)
from agent.contenido_sospechoso import ResultadoEscaneo, escanear, evidencia
from agent.hitl import (
    PROMPT_ALERTAS,
    PROMPT_MONTO_ALTO,
    PROMPT_REGISTRAR,
    EntradaAlertas,
    decidir_hitl,
    evaluar_alertas,
    generar_token_automatico,
)
from agent.tracer import Trace, TraceEntry, write_trace
from finanzas_mcp.business.categorias import CLOSED_CATEGORY_LIST
from finanzas_mcp.business.hitl import PoliticaHitlError, resolver_parametros_hitl  # noqa: F401

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
    modo_hitl: str = "siempre"
    umbral_confianza_ocr: float = 0.75

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
    """Lee ``politica.json`` (UTF-8) y construye la ``Policy``.

    Lanza ``PoliticaHitlError`` si ``modo_hitl`` o ``umbral_confianza_ocr`` son inválidos.
    """
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    hitl = resolver_parametros_hitl(raw)
    return Policy(
        modo_hitl=hitl.modo_hitl,
        umbral_confianza_ocr=hitl.umbral_confianza_ocr,
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

REQUIRED_FIELDS = _REQUIRED_FIELDS
OPTIONAL_FIELDS = _OPTIONAL_FIELDS
ALLOWED_FIELDS = _ALLOWED_FIELDS
_NUMERIC = {"total", "subtotal", "iva"}
_DEFECTOS = {"subtotal": lambda: 0.0, "fecha": lambda: date.today().isoformat()}
_OCR_REQUIRED = OCR_REQUIRED_FIELDS
_MAX_TEXT = 200
_YES = {"si", "sí", "s", "yes", "y"}
_NO = {"no", "n", "cancelar", "cancel"}


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
        self._ocr_sel: Optional[dict] = None
        self._ocr_calls = 0
        self._escaneo = ResultadoEscaneo(False, (), None)
        self._datos_extraidos: dict = {}
        self._n_duplicados = 0
        self._token_auto = False
        self._reset_auditoria()

    def _reset_auditoria(self) -> None:
        self._etapa = "extraer"
        self._seq = 0
        self._bloqueadas: list[dict] = []
        self._descartados: list[str] = []
        self._correcciones: list[dict] = []
        self._texto_info: dict = {}
        self._registro: Optional[dict] = None

    # -- API -----------------------------------------------------------------

    def run(self, image_path: str) -> PipelineResult:
        self._trace = Trace(
            trace_id=str(uuid.uuid4()), user_id=self._user_id,
            image_path=image_path, created_at=_now(),
        )
        self._ocr_sel = None
        self._ocr_calls = 0
        self._escaneo = ResultadoEscaneo(False, (), None)
        self._datos_extraidos = {}
        self._n_duplicados = 0
        self._token_auto = False
        self._reset_auditoria()
        status, reason, message, tx_id, datos = ESTADO_ERROR_VALIDACION, RAZON_FALLO_VALIDACION, "", None, {}
        try:
            datos = self._step1_extraer(image_path)
            self._etapa = "validar"
            self._step2_3_validar(datos)
            self._etapa = "duplicados"
            self._step4_duplicados(datos)
            self._etapa = "confirmar"
            token, high_token = self._step5_confirmar(datos)
            self._etapa = "registrar"
            tx_id = self._step6_registrar(datos, token, high_token)
            status, reason = ESTADO_EXITO, RAZON_EXITO
            message = f"Transacción registrada con id={tx_id}."
        except StepLimitError as exc:
            status, reason, message = ESTADO_LIMITE_PASOS, RAZON_LIMITE_PASOS, str(exc)
        except TokenLimitError as exc:
            status, reason, message = ESTADO_LIMITE_TOKENS, RAZON_LIMITE_TOKENS, str(exc)
        except _Stop as stop:
            reason, message = stop.reason, stop.message
            status = ESTADO_ABORTO_USUARIO if reason == RAZON_RECHAZO_USUARIO else ESTADO_ERROR_VALIDACION
        except PolicyError as exc:
            reason, message = RAZON_FALLO_VALIDACION, f"Política: {exc}"

        if status != ESTADO_EXITO:
            message = f"{message} La transacción NO fue guardada."
        self._etapa = "fin"
        self._log("termination", "", message, None)
        self._construir_auditoria(datos, status)
        self._trace.final_status = status
        self._trace.termination_reason = reason
        self._trace.transaction_id = tx_id
        self._io.notify(message)
        if self._traces_dir:
            write_trace(self._trace, self._traces_dir)
        return PipelineResult(status, reason, message, tx_id, dict(datos), self._trace)

    # -- Infraestructura -----------------------------------------------------

    def _log(self, action: str, inp: str, out: str, tool: Optional[str],
             duracion_ms: Optional[int] = None, datos: Optional[dict] = None) -> None:
        self._seq += 1
        self._trace.entries.append(TraceEntry(
            step=self._steps.count, action=action, input_summary=inp[:300],
            output_summary=out[:300], tool_called=tool, timestamp=_now(),
            seq=self._seq, etapa=self._etapa, duracion_ms=duracion_ms, datos=datos,
        ))

    def _call(self, name: str, args: dict, confirmed: bool = False) -> Any:
        """Llama una herramienta aplicando política, límites y traza."""
        if name not in self._policy.allowed_tools or name not in self._tools:
            self._bloquear(name, "no_permitida")
            raise PolicyError(f"herramienta '{name}' no permitida")
        if name in self._policy.confirmation_tools and not confirmed:
            self._bloquear(name, "sin_confirmacion")
            raise PolicyError(f"herramienta '{name}' requiere confirmación explícita")
        self._steps.increment()
        t0 = time.perf_counter()
        try:
            result = normalize_tool_result(self._tools[name](args))
        except ToolError as err:
            self._log(name, _summ(args), f"error {err.code}", name, _ms(t0),
                      {"servidor": "finanzas_mcp", "herramienta": name,
                       "argumentos": _args_traza(args), "error": err.code})
            self._tokens.add(self._estimate(args, err.code))
            raise
        self._log(name, _summ(args), "ok", name, _ms(t0), _datos_mcp(name, args, result))
        self._tokens.add(self._estimate(args, result))
        return result

    def _bloquear(self, name: str, motivo: str) -> None:
        """Registra un intento de usar una herramienta fuera de política (indicio de manipulación)."""
        self._bloqueadas.append({"herramienta": name, "motivo": motivo, "etapa": self._etapa})
        self._log("policy_blocked", f"herramienta={name}", motivo, None)

    def _ask(self, prompt: str, action: str) -> Optional[str]:
        """Pide dato al usuario; cuenta como paso de decisión."""
        self._steps.increment()
        t0 = time.perf_counter()
        answer = self._io.ask(prompt)
        answer = answer.strip() if isinstance(answer, str) else None
        answer = answer or None
        self._log(action, prompt, "respuesta" if answer else "sin respuesta", None, _ms(t0))
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
        umbral = self._policy.umbral_confianza_ocr
        ocr = self._ocr(image_path)
        self._ocr_calls = 1
        self._set_ocr_block(ocr)
        if _es_bajo(ocr, umbral):
            self._log("ocr_retry", "confianza baja", "reintento", None)
            try:
                segundo = self._ocr(image_path)
            except ToolError:
                # Req. 4.4: se conserva el primer resultado.
                self._ocr_calls += 1
            else:
                self._ocr_calls += 1
                ocr = _seleccionar(ocr, segundo)
            self._set_ocr_block(ocr)
        self._ocr_sel = ocr
        datos = _map_fields(ocr["text"])
        self._escanear(ocr["text"])
        if _es_bajo(ocr, umbral):
            low = [f for f in ocr["low"] if f in ALLOWED_FIELDS] or [
                f for f in _OCR_REQUIRED if datos.get(f) is None
            ]
            for f in low:
                self._clarify(datos, f)
        self._datos_extraidos = dict(datos)  # D5: antes de los pasos 2 y 3
        return datos

    def _set_ocr_block(self, ocr: dict) -> None:
        self._trace.ocr = {
            "confianza_ocr": ocr["confianza"],
            "llamadas_ocr": self._ocr_calls,
            "umbral_confianza_ocr": self._policy.umbral_confianza_ocr,
        }

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
        glob = res.get("confianza_ocr") if isinstance(res, dict) else None
        confianza = float(glob) if _es_numero(glob) else conf
        campos_raw = res.get("confianza_campos") if isinstance(res, dict) else None
        campos = {str(k): float(v) for k, v in campos_raw.items() if _es_numero(v)} \
            if isinstance(campos_raw, dict) else {}
        uso = res.get("uso_tokens") if isinstance(res, dict) else None
        if isinstance(uso, dict):
            for clave, attr in (("entrada", "tokens_entrada"), ("salida", "tokens_salida")):
                n = uso.get(clave)
                if _es_numero(n) and n > 0:
                    setattr(self._trace, attr, getattr(self._trace, attr) + int(n))
        return {"text": text if isinstance(text, str) else "", "confidence": conf,
                "low": low, "is_untrusted": True, "confianza": confianza, "campos": campos}

    def _clarify(self, datos: dict, f: str) -> None:
        shown = datos.get(f)
        ans = self._ask(
            f"Baja confianza en '{f}' (valor leído como dato: {shown!r}). "
            f"Escriba el valor correcto o Enter para dejarlo: ", "clarify_field",
        )
        if ans is None:
            if datos.get(f) is None:
                if f in _DEFECTOS:
                    self._aplicar_defecto(datos, f)
                    return
                raise _Stop(RAZON_FALLO_VALIDACION, f"No se aclaró el campo '{f}'.")
            return
        value = _coerce(f, ans)
        if value is None:
            if f in _DEFECTOS:
                self._aplicar_defecto(datos, f)
                return
            raise _Stop(RAZON_FALLO_VALIDACION, f"Valor inválido para '{f}'.")
        self._corregir(datos, f, value)

    def _aplicar_defecto(self, datos: dict, f: str) -> None:
        """subtotal -> 0 y fecha -> hoy, para que el agente no falle por estos campos."""
        self._corregir(datos, f, _DEFECTOS[f]())
        self._log("default_aplicado", f, f"{f}={datos[f]}", None)

    def _corregir(self, datos: dict, f: str, nuevo: Any) -> None:
        """Asigna un valor dado por el usuario y deja constancia de lo que había leído el OCR."""
        previo = datos.get(f)
        if previo != nuevo:
            self._correcciones.append({
                "campo": f, "valor_ocr": previo, "valor_usuario": nuevo, "etapa": self._etapa,
            })
        datos[f] = nuevo

    def _escanear(self, text: str) -> None:
        self._escaneo = escanear(text)
        self._trace.patrones_sospechosos = list(self._escaneo.ids)
        self._trace.motivo_fallo_escaneo = self._escaneo.motivo_fallo
        self._texto_info = {
            "longitud": len(text) if isinstance(text, str) else 0,
            "sha256": hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()
            if isinstance(text, str) else None,
        }
        self._descartados = _campos_descartados(text)
        evid = evidencia(text, self._escaneo.ids)
        if self._escaneo.sospechoso:
            self._log("suspicious_data_detected", "contenido OCR",
                      "tratado como dato; no ejecutado", None,
                      datos={"patrones": list(self._escaneo.ids), "evidencia": evid,
                             "campos_descartados": self._descartados})

    def _construir_auditoria(self, datos: dict, status: str) -> None:
        """Resume en la traza qué pasó con la factura y si hay indicios de que una inyección surtió efecto."""
        llamadas = [e.tool_called for e in self._trace.entries if e.tool_called]
        conteo = {n: llamadas.count(n) for n in dict.fromkeys(llamadas)}
        indicios: list[str] = []
        for n in conteo:
            if n not in _HERRAMIENTAS_PIPELINE:
                indicios.append(f"herramienta fuera del pipeline: {n}")
        for n, maximo in _MAX_LLAMADAS.items():
            if conteo.get(n, 0) > maximo:
                indicios.append(f"{n} llamada {conteo[n]} veces (máximo {maximo})")
        for b in self._bloqueadas:
            indicios.append(f"intento bloqueado por política: {b['herramienta']} ({b['motivo']})")
        if self._registro is not None:
            extra = sorted(set(self._registro) - _CAMPOS_REGISTRO)
            if extra:
                indicios.append(f"el registro incluyó campos no permitidos: {extra}")
        sospechoso = bool(self._escaneo.sospechoso)
        if indicios:
            veredicto = "indicios_de_ejecucion"
        elif sospechoso:
            veredicto = "detectada_sin_efecto"
        else:
            veredicto = "sin_indicios"
        self._trace.seguridad = {
            "veredicto_inyeccion": veredicto,
            "indicios_de_ejecucion": indicios,
            "contenido_sospechoso": sospechoso,
            "patrones": list(self._escaneo.ids),
            "evidencia": evidencia(
                (self._ocr_sel or {}).get("text", ""), self._escaneo.ids,
            ),
            "campos_ocr_descartados": list(self._descartados),
            "texto_ocr": dict(self._texto_info),
            "herramientas_invocadas": conteo,
            "herramientas_bloqueadas": list(self._bloqueadas),
            "hitl_solicitado": bool((self._trace.decision_hitl or {}).get("hitl_solicitado")),
            "token_automatico": self._token_auto,
        }
        self._trace.factura = {
            "datos_ocr": dict(self._datos_extraidos),
            "correcciones_usuario": list(self._correcciones),
            "datos_finales": _payload(datos) if datos else {},
            "registro_enviado": self._registro,
            "n_duplicados": self._n_duplicados,
            "resultado": status,
            "transaction_id": self._trace.transaction_id,
        }

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
                raise _Stop(RAZON_FALLO_VALIDACION, f"Validación fallida: {err.message}")
            for f in missing:
                if f in _DEFECTOS:
                    self._aplicar_defecto(datos, f)
                else:
                    self._ask_field(datos, f)
        elif code == "INVALID_CURRENCY":
            self._ask_field(datos, "moneda", "Moneda inválida. Use CRC o USD")
        elif code in ("INVALID_DATE_FORMAT", "FUTURE_DATE"):
            self._aplicar_defecto(datos, "fecha")
        elif code == "INVALID_CATEGORY":
            self._select_category(datos)
        elif code == "ARITHMETIC_INCONSISTENCY":
            self._fix_arithmetic(datos)
        else:
            raise _Stop(RAZON_FALLO_VALIDACION, f"Validación fallida: {err.message or code}")

    def _ask_field(self, datos: dict, f: str, hint: str = "") -> None:
        if f == "categoria":
            return self._select_category(datos)
        ans = self._ask(f"{hint or 'Falta el campo'} '{f}': ", "ask_field")
        value = _coerce(f, ans) if ans else None
        if value is None:
            raise _Stop(RAZON_FALLO_VALIDACION, f"No se obtuvo un valor válido para '{f}'.")
        self._corregir(datos, f, value)

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
            raise _Stop(RAZON_FALLO_VALIDACION, "No se seleccionó una categoría válida.")
        self._corregir(datos, "categoria", chosen)

    def _fix_arithmetic(self, datos: dict) -> None:
        # subtotal -> 0 por defecto; sin subtotal e iva juntos el servidor no evalúa la aritmética.
        self._aplicar_defecto(datos, "subtotal")
        datos["iva"] = None

    def _fix_arithmetic_manual(self, datos: dict) -> None:
        ans = self._ask(
            f"Incoherencia: subtotal={datos.get('subtotal')} + iva={datos.get('iva')} "
            f"!= total={datos.get('total')}. ¿Qué campo es incorrecto y debe corregirse "
            f"(subtotal/iva/total)? ",
            "arithmetic_choice",
        )
        target = ans.lower() if ans else None
        if target not in ("subtotal", "iva", "total"):
            raise _Stop(RAZON_FALLO_VALIDACION, "No se aclaró la incoherencia aritmética.")
        self._ask_field(datos, target, "Valor correcto para")

    # -- Paso 4: Duplicados --------------------------------------------------

    def _step4_duplicados(self, datos: dict) -> bool:
        # user_id lo inyecta el servidor desde la sesión; no se envía en el payload.
        res = self._call("buscar_duplicados",
                         {k: datos[k] for k in ("comercio", "fecha", "total")})
        if isinstance(res, dict):
            res = res.get("duplicados", res.get("result", []))
        matches = res if isinstance(res, list) else []
        self._n_duplicados = len(matches)
        if not matches:
            return False
        if self._policy.modo_hitl == "adaptativo":
            # D6: sin pregunta aquí; POSSIBLE_DUPLICATE sale en la solicitud única del paso 5.
            self._log("duplicates_found", "", f"n_duplicados={len(matches)}", None)
            return True
        lines = "\n".join(
            f"  - {m.get('comercio')} | {m.get('fecha')} | {m.get('total')} {m.get('moneda', '')}"
            for m in matches if isinstance(m, dict)
        )
        if not self._confirm(f"Posibles duplicados:\n{lines}\n¿Registrar de todos modos? (si/no): ",
                             "duplicate_confirmation"):
            raise _Stop(RAZON_RECHAZO_USUARIO, "El usuario no confirmó continuar tras detectar duplicados.")
        return True

    # -- Paso 5: Confirmación ------------------------------------------------

    def _evaluar_alertas(self, datos: dict) -> tuple[str, ...]:
        ocr = self._ocr_sel or {"confianza": None, "campos": {}, "low": []}
        umbral = self._policy.umbral_confianza_ocr
        legado = not ocr["campos"] and ocr["confianza"] is not None and _es_bajo(ocr, umbral)
        ext = self._datos_extraidos
        entrada = EntradaAlertas(
            confianza_global=ocr["confianza"],
            confianza_campos=dict(ocr["campos"]),
            ocr_bajo_legado=legado,
            umbral_confianza_ocr=umbral,
            total=datos.get("total"),
            moneda=datos.get("moneda"),
            umbrales_monto=dict(self._policy.high_amount_threshold),
            subtotal_extraido=ext.get("subtotal"),
            iva_extraido=ext.get("iva"),
            total_extraido=ext.get("total"),
            n_duplicados=self._n_duplicados,
            contenido_sospechoso=self._escaneo.sospechoso,
        )
        return evaluar_alertas(entrada)

    def _step5_confirmar(self, datos: dict) -> tuple[Optional[str], Optional[str]]:
        """Decide HITL. Ya no se pide ningún token de confirmación al usuario."""
        alertas = self._evaluar_alertas(datos)
        modo = self._policy.modo_hitl
        decision = decidir_hitl(modo, alertas)
        # Se registran antes de preguntar para conservarlas ante un rechazo (Req. 5.10).
        self._trace.alertas_hitl = list(alertas)
        self._trace.decision_hitl = decision.a_dict()
        self._log("decision_hitl", f"modo_hitl={modo}", decision.razon, None)

        if modo == "adaptativo" and decision.hitl_solicitado:
            self._confirmar_alertas(datos, alertas)
        return None, None

    def _confirmar_alertas(self, datos: dict, alertas: tuple[str, ...]) -> None:
        """Confirmación si/no consolidada con todas las alertas (sin token)."""
        lista = "\n".join(f"  - {a}" for a in alertas)
        if not self._confirm(
            f"{PROMPT_ALERTAS}:\n{lista}\n"
            f"Revise la factura ({datos.get('total')} {datos.get('moneda')}). "
            "¿Registrar? (si/no): ",
            "hitl_alerts_confirmation",
        ):
            raise _Stop(RAZON_RECHAZO_USUARIO, "El usuario rechazó o no respondió la solicitud de Alertas HITL.")
    # -- Paso 6: Registrar ---------------------------------------------------

    def _step6_registrar(self, datos: dict, token: Optional[str], high_token: Optional[str]) -> Optional[int]:
        args = _payload(datos)
        if self._ocr_sel is not None:
            args["confianza_ocr"] = self._ocr_sel["confianza"]
        args["contenido_sospechoso"] = bool(self._escaneo.sospechoso)
        # Sin tokens de confirmación: solo qué se envió al servidor.
        self._registro = {k: v for k, v in args.items() if "token" not in k}
        try:
            res = self._call("registrar_transaccion", args, confirmed=True)
        except ToolError as err:
            raise _Stop(RAZON_FALLO_VALIDACION, f"El servidor rechazó el registro: {err.message or err.code}")
        return res.get("id") if isinstance(res, dict) else None


# ---------------------------------------------------------------------------
# Utilidades puras
# ---------------------------------------------------------------------------


_HERRAMIENTAS_PIPELINE = frozenset(
    {"ocr_imagen", "validar_factura", "buscar_duplicados", "registrar_transaccion"})
_MAX_LLAMADAS = {"ocr_imagen": 2, "buscar_duplicados": 1, "registrar_transaccion": 1}
_CAMPOS_REGISTRO = frozenset(ALLOWED_FIELDS) | {"confianza_ocr", "contenido_sospechoso"}


def _ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


def _campos_descartados(text: str) -> list[str]:
    """Claves del JSON del OCR que no están en la lista blanca (ignoradas por el agente)."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    return sorted(str(k)[:40] for k in data if k not in ALLOWED_FIELDS)[:20]


def _es_numero(v: Any) -> bool:
    """Número finito real (excluye ``bool`` y NaN/inf)."""
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _es_bajo(ocr: dict, umbral: float) -> bool:
    """Confianza baja.  Con mapa por campo usa global y campos requeridos;
    con OCR legado (sin ``campos``) conserva la regla anterior."""
    if ocr["campos"]:
        if ocr["confianza"] < umbral:
            return True
        return any(ocr["campos"][f] < umbral for f in _OCR_REQUIRED if f in ocr["campos"])
    return ocr["confianza"] < umbral or bool(ocr["low"])


def _seleccionar(primero: dict, segundo: dict) -> dict:
    """Mayor confianza global; en empate, el primero (Req. 4.2)."""
    return segundo if segundo["confianza"] > primero["confianza"] else primero


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


def _args_traza(args: dict) -> dict:
    """Argumentos enviados al servidor MCP, sin tokens y con valores acotados."""
    return {k: (v if isinstance(v, (int, float, bool)) or v is None else str(v)[:100])
            for k, v in args.items() if "token" not in k}


def _datos_mcp(name: str, args: dict, result: Any) -> dict:
    """Detalle de una llamada a finanzas_mcp. El resultado del OCR solo se resume (sin texto)."""
    if name == "ocr_imagen" or not isinstance(result, (dict, list)):
        res: Any = {"claves": sorted(result)} if isinstance(result, dict) else type(result).__name__
    else:
        texto = json.dumps(result, default=str, ensure_ascii=False)
        res = json.loads(texto) if len(texto) <= 1000 else {"truncado": True}
    return {"servidor": "finanzas_mcp", "herramienta": name,
            "argumentos": _args_traza(args), "resultado": res}


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
