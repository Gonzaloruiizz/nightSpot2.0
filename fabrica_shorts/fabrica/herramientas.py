"""Ayudantes para encontrar y ejecutar ffmpeg / ffprobe."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

from . import config

EXT = ".exe" if os.name == "nt" else ""


class ErrorFabrica(Exception):
    """Error con un mensaje pensado para que lo entienda cualquiera."""


@lru_cache(maxsize=None)
def ruta_ffmpeg() -> str:
    propia = config.leer_clave("FFMPEG_PATH").strip('"')
    if propia:
        ruta = Path(propia)
        if ruta.is_dir():
            ruta = ruta / f"ffmpeg{EXT}"
        if ruta.is_file():
            return str(ruta)
        raise ErrorFabrica(f"En el archivo .env, FFMPEG_PATH apunta a '{ruta}', pero ahí no hay ffmpeg.")
    encontrado = shutil.which("ffmpeg")
    if not encontrado:
        raise ErrorFabrica(
            "No encuentro ffmpeg. En Windows instálalo con:  winget install Gyan.FFmpeg\n"
            "   y después cierra y vuelve a abrir la ventana."
        )
    return encontrado


@lru_cache(maxsize=None)
def ruta_ffprobe() -> str:
    hermano = Path(ruta_ffmpeg()).with_name(f"ffprobe{EXT}")
    if hermano.is_file():
        return str(hermano)
    encontrado = shutil.which("ffprobe")
    if not encontrado:
        raise ErrorFabrica("No encuentro ffprobe (viene junto a ffmpeg). Reinstala ffmpeg.")
    return encontrado


def ejecutar(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Ejecuta un programa. Si falla, lanza ErrorFabrica con las últimas líneas del error."""
    resultado = subprocess.run(
        [str(a) for a in args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if resultado.returncode != 0:
        cola = "\n".join(resultado.stderr.strip().splitlines()[-15:])
        raise ErrorFabrica(f"Falló '{Path(args[0]).name}':\n{cola}")
    return resultado


def ffmpeg(*args, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return ejecutar([ruta_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", *args], cwd=cwd)


@lru_cache(maxsize=None)
def version_ffmpeg() -> tuple[int, int]:
    """Versión de ffmpeg, p. ej. (7, 1). Las compilaciones de desarrollo cuentan como muy nuevas."""
    texto = ejecutar([ruta_ffmpeg(), "-version"]).stdout.splitlines()[0]
    m = re.search(r"version\s+n?(\d+)\.(\d+)", texto)
    if m:
        return int(m.group(1)), int(m.group(2))
    return 99, 0


@lru_cache(maxsize=None)
def tiene_filtro(nombre: str) -> bool:
    """¿Este ffmpeg tiene el filtro? (se pregunta uno a uno: el formato de la lista cambia entre versiones)."""
    salida = ejecutar([ruta_ffmpeg(), "-hide_banner", "-h", f"filter={nombre}"])
    texto = (salida.stdout + salida.stderr).strip()
    return texto.startswith(f"Filter {nombre}")


def duracion(ruta: Path) -> float:
    """Duración en segundos de un audio o vídeo."""
    salida = ejecutar([
        ruta_ffprobe(), "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(ruta),
    ]).stdout.strip()
    return float(salida)
