"""Montaje final del vídeo con ffmpeg: fondo + capas de imagen + subtítulos + audio."""
from __future__ import annotations

import os
import random
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from . import config, herramientas
from .herramientas import ErrorFabrica

EXTENSIONES_VIDEO = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}

# Colores de los fondos animados (se elige uno distinto según el vídeo)
PALETAS = [
    ("0x14002e", "0x5b0f8a", "0xff2e88"),
    ("0x001a33", "0x0a6ad9", "0x22c1c3"),
    ("0x1b0033", "0xff6a00", "0xc2185b"),
    ("0x0b1d26", "0x1f6f78", "0x00b09b"),
    ("0x220a3d", "0x6a3fd1", "0xf72585"),
    ("0x0d1b2a", "0x1b998b", "0xe4ff1a"),
]


@dataclass
class Codificador:
    nombre: str
    args: list[str]


@dataclass
class Capa:
    """Una imagen PNG encima del vídeo durante un rato.

    x / y pueden ser números o fórmulas de ffmpeg que usan t (segundos),
    W/H (tamaño del vídeo) y w/h (tamaño de la imagen).
    """
    imagen: Path
    x: str
    y: str
    inicio: float = 0.0
    fin: float | None = None
    fundido: float = 0.0


def _args_nvenc(calidad: int) -> list[str]:
    return ["-c:v", "h264_nvenc", "-preset", "p5", "-tune", "hq", "-rc", "vbr",
            "-cq", str(calidad), "-b:v", "0", "-maxrate", "14M", "-bufsize", "28M",
            "-profile:v", "high"]


def _args_cpu(calidad: int) -> list[str]:
    return ["-c:v", "libx264", "-preset", "medium", "-crf", str(calidad), "-profile:v", "high"]


def _funciona(args: list[str]) -> bool:
    """Hace una codificación de prueba de 0,3 s para ver si el codificador funciona de verdad."""
    try:
        herramientas.ffmpeg("-f", "lavfi", "-i", "color=c=black:s=320x576:r=30:d=0.3",
                            *args, "-pix_fmt", "yuv420p", "-f", "null", "-")
        return True
    except ErrorFabrica:
        return False


@lru_cache(maxsize=None)
def elegir_codificador(preferencia: str = "auto", calidad: int = 20) -> Codificador:
    """NVENC (NVIDIA) si funciona; si no, el procesador."""
    preferencia = preferencia.lower().strip()
    if preferencia in ("auto", "nvenc"):
        for args in (_args_nvenc(calidad), ["-c:v", "h264_nvenc", "-cq", str(calidad)]):
            if _funciona(args):
                return Codificador("NVENC (tarjeta NVIDIA) 🚀", args)
        if preferencia == "nvenc":
            raise ErrorFabrica(
                "Pediste NVENC pero no funciona. Actualiza el driver de NVIDIA "
                'o pon codificador = "auto" en ajustes.toml.')
    return Codificador("procesador (libx264)", _args_cpu(calidad))


def _fondo(duracion: float, semilla: int, ajustes: dict) -> tuple[list[str], str]:
    """Devuelve (argumentos de entrada, filtro) del fondo: un clip tuyo o un degradado animado."""
    v = ajustes["video"]
    ancho, alto, fps = v["ancho"], v["alto"], v["fps"]
    azar = random.Random(semilla)
    clips = sorted(p for p in config.CARPETA_FONDOS.glob("*") if p.suffix.lower() in EXTENSIONES_VIDEO)
    if clips:
        clip = azar.choice(clips)
        return (["-stream_loop", "-1", "-i", str(clip)],
                f"scale={ancho}:{alto}:force_original_aspect_ratio=increase,crop={ancho}:{alto},"
                f"fps={fps},eq=brightness=-0.12:saturation=1.15,setsar=1")
    c0, c1, c2 = azar.choice(PALETAS)
    # Se dibuja pequeño y se amplía: un degradado no pierde calidad y es mucho más rápido.
    fuente = (f"gradients=s={ancho // 4}x{alto // 4}:r={fps}:d={duracion:.3f}:n=3:"
              f"c0={c0}:c1={c1}:c2={c2}:speed=0.015:seed={semilla}")
    return ["-f", "lavfi", "-i", fuente], f"scale={ancho}:{alto}:flags=bicubic,setsar=1,format=yuv420p"


def renderizar(salida: Path, duracion: float, audio: Path, subtitulos: Path | None,
               capas: list[Capa], ajustes: dict, trabajo: Path, semilla: int = 0) -> Codificador:
    """Crea el MP4 final. Devuelve el codificador usado."""
    v = ajustes["video"]
    fps = v["fps"]
    codificador = elegir_codificador(ajustes["render"].get("codificador", "auto"),
                                     int(ajustes["render"].get("calidad", 20)))

    entradas, filtro_fondo = _fondo(duracion, semilla, ajustes)
    partes = [f"[0:v]{filtro_fondo}[v0]"]
    actual = "v0"
    for i, capa in enumerate(capas, start=1):
        entradas += ["-i", str(capa.imagen)]
        # loop = la imagen se lee una sola vez y se repite en memoria (rápido)
        cadena = f"[{i}:v]format=rgba,loop=loop=-1:size=1:start=0,setpts=N/{fps}/TB"
        if capa.fundido > 0:
            cadena += f",fade=t=in:st={capa.inicio:.3f}:d={capa.fundido:.3f}:alpha=1"
        partes.append(cadena + f"[c{i}]")
        fin = capa.fin if capa.fin is not None else duracion + 1
        partes.append(f"[{actual}][c{i}]overlay=x='{capa.x}':y='{capa.y}':"
                      f"enable='between(t,{capa.inicio:.3f},{fin:.3f})':format=auto[v{i}]")
        actual = f"v{i}"
    if subtitulos is not None:
        # Rutas relativas: así no hay líos con "C:\" en Windows.
        fuentes = os.path.relpath(config.CARPETA_FUENTES, trabajo).replace(os.sep, "/")
        partes.append(f"[{actual}]subtitles=filename={subtitulos.name}:fontsdir={fuentes}[vsub]")
        actual = "vsub"
    partes.append(f"[{actual}]format=yuv420p[vsal]")

    archivo_filtro = trabajo / "filtro.txt"
    archivo_filtro.write_text(";\n".join(partes), encoding="utf-8")
    if herramientas.version_ffmpeg() >= (7, 0):
        opcion_filtro = ["-/filter_complex", archivo_filtro.name]
    else:
        opcion_filtro = ["-filter_complex_script", archivo_filtro.name]

    indice_audio = len(capas) + 1
    herramientas.ffmpeg(
        *entradas, "-i", str(audio), *opcion_filtro,
        "-map", "[vsal]", "-map", f"{indice_audio}:a",
        "-t", f"{duracion:.3f}", "-r", str(fps),
        *codificador.args, "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart", str(salida),
        cwd=trabajo,
    )
    return codificador
