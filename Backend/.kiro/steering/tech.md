---
inclusion: always
---

# Reglas técnicas del curso

Estas reglas aplican a todo el código de este proyecto. Si una tarea parece pedir algo que las contradice, detente y pregunta en lugar de romperlas.

## Lenguaje y dependencias

- Python 3.12 o superior.
- Todo archivo se lee y escribe con `encoding="utf-8"`.
- Docker.
- En parámetros y firmas de funciones, utiliza siempre anotaciones de tipos de dato (`type hints`).

## Servidores MCP

- Protocolo MCP Streamable HTTP o stdio.
- Al arrancar, fuerza UTF-8 en la entrada y la salida estándar:
  `sys.stdin.reconfigure(encoding="utf-8")` y `sys.stdout.reconfigure(encoding="utf-8")`.
- **La salida estándar es exclusiva del protocolo.** Nunca uses `print()` hacia stdout.
  Todo mensaje de depuración va a `sys.stderr`.
- Un error de negocio se devuelve como resultado con `isError: true` y un texto que explica
  la regla incumplida. Un error nunca debe tumbar el servidor.

## Pruebas y Evaluación Experimental

- Pruebas unitarias y de reglas de negocio (`R1`–`R11`) con `unittest` de la biblioteca estándar, ubicadas en la carpeta `tests/`.
- Cada regla de negocio tiene al menos una prueba que la cumple y otra que la incumple.
- Las pruebas unitarias se ejecutan con `python -m unittest discover -s tests -v` y no deben depender de llamadas externas pagas si no es necesario.
- Los scripts de experimentación, *baselines* y *benchmark* científico (que ejecutan llamadas reales al LLM sobre el Golden Set) se ubican en `eval/` y `baseline/`, separados de `tests/`.
