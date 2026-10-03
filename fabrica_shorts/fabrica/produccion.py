"""La cadena de montaje de UN vídeo: guion → voz → subtítulos → imagen → MP4."""
from __future__ import annotations

import shutil
import time
import zlib
from dataclasses import dataclass
from pathlib import Path

from . import audio, config, render, subtitulos, voz
from .guion import leer_guion

SUFIJO_PRUEBA = "__VOZ_DE_PRUEBA"


@dataclass
class Resultado:
    video: Path
    duracion: float
    motor_voz: str
    codificador: str
    segundos: float


def producir(archivo: Path, ajustes: dict, motor_voz: str = "auto", conservar: bool = False) -> Resultado:
    reloj = time.time()
    guion = leer_guion(archivo, ajustes["personajes"])
    trabajo = config.CARPETA_TRABAJO / guion.nombre
    shutil.rmtree(trabajo, ignore_errors=True)
    trabajo.mkdir(parents=True)
    config.CARPETA_SALIDA.mkdir(exist_ok=True)

    # 1) Voces
    pista_voz = trabajo / "voz.wav"
    duracion_voz, motor = voz.crear_pista(guion.frases, ajustes, motor_voz, pista_voz)
    duracion = duracion_voz + float(ajustes["video"].get("cola_final", 0.8))

    # 2) Audio final
    pista_final = trabajo / "audio.wav"
    audio.mezclar(pista_voz, duracion, ajustes, pista_final)

    # 3) Subtítulos
    print("   💬 Subtítulos", flush=True)
    archivo_ass = trabajo / "subtitulos.ass"
    subtitulos.crear_ass(guion.frases, guion.gancho, duracion, ajustes["personajes"], ajustes, archivo_ass)

    # 4) Montaje
    print("   🎬 Montando el vídeo…", flush=True)
    semilla = zlib.crc32(guion.nombre.encode("utf-8"))
    nombre = guion.nombre + ("" if motor == "edge" else SUFIJO_PRUEBA)
    salida = config.CARPETA_SALIDA / f"{nombre}.mp4"
    codificador = render.renderizar(salida, duracion, pista_final, archivo_ass, [], ajustes, trabajo, semilla)

    if not conservar:
        shutil.rmtree(trabajo, ignore_errors=True)
    return Resultado(salida, duracion, motor, codificador.nombre, time.time() - reloj)
