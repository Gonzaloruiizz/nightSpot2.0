"""Audio final del vídeo: voces a volumen estándar de redes sociales."""
from __future__ import annotations

from pathlib import Path

from . import herramientas


def mezclar(voz: Path, duracion: float, ajustes: dict, destino: Path) -> None:
    # loudnorm deja la voz a -15 LUFS, el volumen típico de TikTok / Shorts
    herramientas.ffmpeg(
        "-i", str(voz),
        "-af", "loudnorm=I=-15:TP=-1.5:LRA=11,aresample=48000,apad",
        "-t", f"{duracion:.3f}", "-ac", "2", "-ar", "48000", str(destino))
