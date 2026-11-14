"""Dobles de prueba compartidos (Req. 18.6, 19.10): ``FakeOcr`` y ``FakeClienteLlm``."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from finanzas_mcp.models import OcrResult

try:  # baseline/llm.py se crea en una tarea posterior
    from baseline.llm import RespuestaLlm  # type: ignore
except Exception:  # pragma: no cover
    @dataclass(frozen=True)
    class RespuestaLlm:  # type: ignore[no-redef]
        llamadas_herramienta: list[dict]
        tokens_entrada: int
        tokens_salida: int


class RelojFalso:
    """Reloj inyectable y monótono; ``avanzar`` simula el paso del tiempo."""

    def __init__(self, inicio: float = 0.0) -> None:
        self.ahora = float(inicio)

    def __call__(self) -> float:
        return self.ahora

    def avanzar(self, segundos: float) -> None:
        self.ahora += float(segundos)


class FakeOcr:
    """Callable que devuelve ``OcrResult`` configurables y cuenta las llamadas.

    ``resultados`` se consume en orden; el último se repite. Un elemento que
    sea una excepción (instancia o clase) se lanza en lugar de devolverse.
    """

    def __init__(self, resultados: Iterable[OcrResult | BaseException | type] | OcrResult | None = None) -> None:
        if resultados is None:
            resultados = [OcrResult(text="", confidence=1.0)]
        elif isinstance(resultados, OcrResult):
            resultados = [resultados]
        self.resultados = list(resultados)
        if not self.resultados:
            raise ValueError("FakeOcr requiere al menos un resultado")
        self.llamadas: list[Any] = []

    @property
    def n_llamadas(self) -> int:
        return len(self.llamadas)

    def __call__(self, *args: Any, **kwargs: Any) -> OcrResult:
        indice = min(len(self.llamadas), len(self.resultados) - 1)
        self.llamadas.append((args, kwargs))
        item = self.resultados[indice]
        if isinstance(item, BaseException) or (isinstance(item, type) and issubclass(item, BaseException)):
            raise item
        return item


class FakeClienteLlm:
    """Implementa ``ClienteLlm.invocar`` sin red.

    Cada elemento de ``guion`` describe una invocación (el último se repite):
      - ``RespuestaLlm``: se devuelve tal cual.
      - ``list[dict]``: llamadas de herramienta ``[{"nombre", "args"}]``.
      - excepción (instancia o clase): se lanza.
      - ``("bloquear", segundos, respuesta_o_lista)``: avanza el reloj
        inyectado ``segundos`` (sin dormir) y luego responde.
    """

    def __init__(
        self,
        guion: Iterable[Any] | None = None,
        reloj: RelojFalso | Callable[[], float] | None = None,
        tokens_entrada: int = 10,
        tokens_salida: int = 5,
    ) -> None:
        self.guion = list(guion) if guion is not None else [[]]
        if not self.guion:
            raise ValueError("FakeClienteLlm requiere al menos un elemento de guion")
        self.reloj = reloj
        self.tokens_entrada = tokens_entrada
        self.tokens_salida = tokens_salida
        self.llamadas: list[dict] = []

    @property
    def n_llamadas(self) -> int:
        return len(self.llamadas)

    def _respuesta(self, item: Any) -> RespuestaLlm:
        if isinstance(item, RespuestaLlm):
            return item
        return RespuestaLlm(
            llamadas_herramienta=list(item),
            tokens_entrada=self.tokens_entrada,
            tokens_salida=self.tokens_salida,
        )

    def invocar(self, system_prompt: str, imagen_b64: str, mime: str, herramienta: dict) -> RespuestaLlm:
        indice = min(len(self.llamadas), len(self.guion) - 1)
        self.llamadas.append(
            {"system_prompt": system_prompt, "imagen_b64": imagen_b64, "mime": mime, "herramienta": herramienta}
        )
        item = self.guion[indice]
        if isinstance(item, BaseException) or (isinstance(item, type) and issubclass(item, BaseException)):
            raise item
        if isinstance(item, tuple) and item and item[0] == "bloquear":
            _, segundos, resto = item
            if not hasattr(self.reloj, "avanzar"):
                raise ValueError("El bloqueo requiere un RelojFalso inyectado")
            self.reloj.avanzar(segundos)  # type: ignore[union-attr]
            item = resto
            if isinstance(item, BaseException):
                raise item
        return self._respuesta(item)
