# -*- coding: utf-8 -*-
"""
Tracer — writes one JSON trace file per agent execution.

Each invocation of the invoice pipeline produces a ``Trace`` that records every
step taken, the tool called at each step, and the reason the run ended.  Traces
are written to ``{traces_dir}/{timestamp}_{trace_id[:8]}.json`` with UTF-8
encoding.

If the write fails for any reason, the error is logged to ``sys.stderr`` without
raising an exception so that a trace I/O problem never interrupts the user's
interaction (Requirement 14.3).
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class TraceEntry:
    """A single recorded step inside an agent execution.

    Attributes
    ----------
    step:
        Step number within the SKILL procedure (1–6 for the standard pipeline;
        may exceed 6 on retries counted by the step counter).
    action:
        Name of the action taken at this step (e.g. ``"ocr_imagen"``,
        ``"validar_factura"``, ``"user_confirmation"``).
    input_summary:
        Brief human-readable description of what was sent.  Must NOT contain
        the full OCR text to avoid storing potentially sensitive or large
        content in traces.
    output_summary:
        Brief human-readable description of what was received.
    tool_called:
        Name of the MCP tool invoked at this step, or ``None`` when no MCP
        call was made (e.g. a pure agent decision step).
    timestamp:
        ISO 8601 datetime string recording when this step occurred.
    """

    step: int
    action: str
    input_summary: str
    output_summary: str
    tool_called: Optional[str]
    timestamp: str


@dataclass
class Trace:
    """Complete execution record for a single invoice processing run.

    Attributes
    ----------
    trace_id:
        Unique identifier for this run, generated as a UUID4 string.
    user_id:
        Identifier of the user who initiated the run; taken from session
        context, never from agent payload.
    image_path:
        File-system path to the invoice image that was processed.
    entries:
        Ordered list of ``TraceEntry`` objects, one per step executed.
    final_status:
        High-level outcome of the run.  One of:

        * ``"success"`` — transaction successfully registered.
        * ``"validation_error"`` — a validation rule was not satisfied and
          the user chose not to correct it.
        * ``"step_limit"`` — the StepLimit of 8 was reached.
        * ``"token_limit"`` — the TokenLimit defined in ``politica.json``
          was reached.
        * ``"user_abort"`` — the user rejected the confirmation step.
    termination_reason:
        Free-text explanation when ``final_status`` is not ``"success"``,
        or ``None`` for successful runs.
    created_at:
        ISO 8601 datetime string recording when the trace was created.
    transaction_id:
        Database primary key of the persisted transaction, or ``None`` when
        the run did not result in a successful registration.
    """

    trace_id: str
    user_id: str
    image_path: str
    entries: list[TraceEntry] = field(default_factory=list)
    final_status: str = "success"
    termination_reason: Optional[str] = None
    created_at: str = ""
    transaction_id: Optional[int] = None
    # Optional fields added for the experimental evaluation (Req. 8.1, 8.5).
    # All have defaults so existing callers keep working.
    decision_hitl: Optional[dict] = None
    alertas_hitl: list[str] = field(default_factory=list)
    patrones_sospechosos: list[str] = field(default_factory=list)
    motivo_fallo_escaneo: Optional[str] = None
    ocr: Optional[dict] = None
    tokens_entrada: int = 0
    tokens_salida: int = 0


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------


def write_trace(trace: Trace, traces_dir: str) -> None:
    """Persist *trace* as a JSON file inside *traces_dir*.

    The filename follows the pattern ``{timestamp}_{trace_id[:8]}.json`` where
    *timestamp* is derived from ``trace.created_at`` with colons and periods
    replaced by hyphens so it is safe on all operating systems.

    If *traces_dir* does not exist it is created automatically.

    If writing fails for any reason (permissions, disk full, etc.) the error
    is printed to ``sys.stderr`` and the function returns silently — it must
    never raise, because a trace failure must not interrupt the user's
    interaction (Requirement 14.3).

    Parameters
    ----------
    trace:
        Completed ``Trace`` object to persist.
    traces_dir:
        Directory where the JSON file will be written.  Created if absent.
    """
    try:
        # Ensure the directory exists; exist_ok avoids a race condition.
        os.makedirs(traces_dir, exist_ok=True)

        # Build a filesystem-safe timestamp from the trace's created_at field.
        # Replace characters that are problematic on Windows/macOS/Linux (:, .).
        safe_ts = trace.created_at.replace(":", "-").replace(".", "-")

        # Use the first 8 characters of the trace ID for human-readability
        # while keeping filenames short.
        short_id = trace.trace_id[:8]

        filename = f"{safe_ts}_{short_id}.json"
        filepath = os.path.join(traces_dir, filename)

        # Serialize: convert nested dataclasses to dicts via dataclasses.asdict,
        # then write as pretty-printed JSON with UTF-8 encoding (project rule).
        payload = asdict(trace)
        with open(filepath, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)

    except Exception as exc:  # noqa: BLE001 — intentional broad catch
        # Log to stderr without re-raising.  The caller must not be interrupted
        # by a trace I/O failure (Requirement 14.3).
        print(
            f"[tracer] ERROR: could not write trace to '{traces_dir}': {exc}",
            file=sys.stderr,
        )
