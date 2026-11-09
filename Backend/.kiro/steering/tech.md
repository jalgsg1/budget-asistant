---
inclusion: always
---

# Reglas técnicas del curso

Estas reglas aplican a todo el código de este proyecto. Si una tarea parece pedir algo que las contradice, detente y pregunta en lugar de romperlas.

## Lenguaje y dependencias

- Python 3.12 o superior.
- Todo archivo se lee y escribe con `encoding="utf-8"`.
- Docker
- En parametros, utiliza siempre tipos de dato

## Servidores MCP

- Protocolo MCP sobre stdio: JSON-RPC 2.0, **un mensaje JSON por línea**.
- Al arrancar, fuerza UTF-8 en la entrada y la salida estándar:
  `sys.stdin.reconfigure(encoding="utf-8")` y `sys.stdout.reconfigure(encoding="utf-8")`.
- **La salida estándar es exclusiva del protocolo.** Nunca uses `print()` hacia stdout.
  Todo mensaje de depuración va a `sys.stderr`.
- Un error de negocio se devuelve como resultado con `isError: true` y un texto que explica
  la regla incumplida. Un error nunca debe tumbar el servidor.

## Pruebas

- Pruebas con `unittest` de la biblioteca estándar, en la carpeta `tests/`.
- Cada regla de negocio tiene al menos una prueba que la cumple y otra que la incumple.
- Se ejecutan con `python -m unittest discover -s tests -v`.
