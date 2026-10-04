"""Servidor MCP de Rochi: las mismas herramientas del PC para cualquier cliente MCP.

Sirve para usar las herramientas desde Claude Desktop, Claude Code u otro
cliente MCP sin pasar por el asistente de voz. Va por stdio:

    python servidor_mcp.py

Ojo: en stdio la salida estándar es el canal del protocolo; nada aquí debe
imprimir en stdout (los logs van a stderr).
"""

from __future__ import annotations

import logging
import sys

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

import config
import herramientas

ANOTACIONES = {
    "monitor_sistema": ToolAnnotations(read_only_hint=True),
    "buscar_archivo": ToolAnnotations(read_only_hint=True),
    "apagar_equipo": ToolAnnotations(destructive_hint=True),
    "ejecutar_comando": ToolAnnotations(destructive_hint=True, open_world_hint=True),
}

servidor = MCPServer(
    "rochi",
    instructions=(
        "Herramientas para controlar un PC con Windows 11: abrir programas y webs, volumen, multimedia, "
        "apagado, sensores, benchmarks, archivos, capturas, alarmas y PowerShell. "
        "Pide confirmación al usuario antes de apagar sin tiempo indicado o de ejecutar comandos delicados."
    ),
)
for funcion in herramientas.HERRAMIENTAS:
    servidor.add_tool(funcion, annotations=ANOTACIONES.get(funcion.__name__), structured_output=False)


def main() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        from voz import Voz

        # Las alarmas suenan con la voz de Rochi también cuando se usa por MCP.
        herramientas.registrar_notificador(Voz(config.cargar(), eco=False).hablar)
    except Exception:
        logging.getLogger("rochi.mcp").warning("Sin voz para las alarmas; usaré avisos de Windows", exc_info=True)
    servidor.run()


if __name__ == "__main__":
    main()
