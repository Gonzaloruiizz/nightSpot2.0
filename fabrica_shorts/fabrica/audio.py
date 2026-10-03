"""Audio final: voces a volumen de redes sociales + música de fondo que baja sola al hablar."""
from __future__ import annotations

import random
from pathlib import Path

from . import config, herramientas, musica

EXTENSIONES_AUDIO = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}


def _musica(duracion: float, ajustes: dict, trabajo: Path, semilla: int) -> list[str] | None:
    """Devuelve los argumentos de entrada de ffmpeg para la música (o None si no hay)."""
    m = ajustes.get("musica", {})
    if not m.get("activar", True):
        return None
    if m.get("origen", "dembow") == "carpeta":
        canciones = sorted(p for p in config.CARPETA_MUSICA.glob("*") if p.suffix.lower() in EXTENSIONES_AUDIO)
        if canciones:
            return ["-stream_loop", "-1", "-i", str(random.Random(semilla).choice(canciones))]
        print("   ℹ️  No hay beat propio en assets/musica: uso el dembow de la fábrica.")
    beat = trabajo / "dembow.wav"
    musica.componer_dembow(duracion, beat, semilla, float(m.get("bpm", 120)))
    return ["-i", str(beat)]


def mezclar(voz: Path, duracion: float, ajustes: dict, destino: Path, trabajo: Path,
            semilla: int = 0, con_musica: bool = True) -> None:
    # loudnorm deja la voz a -15 LUFS, el volumen típico de TikTok / Shorts
    cadena_voz = "loudnorm=I=-15:TP=-1.5:LRA=11,aresample=48000,aformat=channel_layouts=stereo,apad"
    entrada_musica = _musica(duracion, ajustes, trabajo, semilla) if con_musica else None
    if entrada_musica is None:
        herramientas.ffmpeg("-i", str(voz), "-af", cadena_voz, "-t", f"{duracion:.3f}",
                            "-ar", "48000", str(destino))
        return

    m = ajustes.get("musica", {})
    volumen = float(m.get("volumen", 1.0))
    final = max(0.0, duracion - 1.5)
    filtro = [
        f"[0:a]{cadena_voz},atrim=0:{duracion:.3f},asplit=2[voz][llave]",
        # Música a -20 LUFS: se oye bien pero queda por debajo de la voz (-15)
        f"[1:a]aresample=48000,aformat=channel_layouts=stereo,loudnorm=I=-20:TP=-3:LRA=11,"
        f"aresample=48000,volume={volumen:.2f},atrim=0:{duracion:.3f},"
        f"afade=t=in:d=0.6,afade=t=out:st={final:.3f}:d=1.5[mus]",
    ]
    if m.get("bajar_al_hablar", True):
        # "Ducking": cuando suena la voz, la música baja sola
        filtro.append("[mus][llave]sidechaincompress=threshold=0.03:ratio=4:attack=15:release=350[fondo]")
    else:
        filtro.append("[llave]anullsink;[mus]anull[fondo]")
    filtro.append("[voz][fondo]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[sal]")
    herramientas.ffmpeg("-i", str(voz), *entrada_musica, "-filter_complex", ";".join(filtro),
                        "-map", "[sal]", "-t", f"{duracion:.3f}", "-ar", "48000", str(destino))
