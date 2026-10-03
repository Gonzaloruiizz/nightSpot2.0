"""La cadena de montaje de UN vídeo: guion → voz → subtítulos → imagen → MP4."""
from __future__ import annotations

import shutil
import time
import zlib
from dataclasses import dataclass, field
from pathlib import Path

from . import audio, config, graficos, publicacion, render, subtitulos, voz
from .guion import leer_guion

SUFIJO_PRUEBA = "__VOZ_DE_PRUEBA"


@dataclass
class Resultado:
    video: Path
    duracion: float
    motor_voz: str
    codificador: str
    segundos: float
    avisos: list[str] = field(default_factory=list)


def salidas(nombre: str) -> tuple[Path, Path]:
    """(vídeo con voz real, vídeo con voz de prueba) de un guion."""
    return (config.CARPETA_SALIDA / f"{nombre}.mp4",
            config.CARPETA_SALIDA / f"{nombre}{SUFIJO_PRUEBA}.mp4")


def producir(archivo: Path, ajustes: dict, motor_voz: str = "auto", conservar: bool = False,
             con_musica: bool = True) -> Resultado:
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

    # 2) Audio final: voz + dembow de fondo
    print("   🥁 Música y mezcla", flush=True)
    semilla = zlib.crc32(guion.nombre.encode("utf-8"))
    pista_final = trabajo / "audio.wav"
    audio.mezclar(pista_voz, duracion, ajustes, pista_final, trabajo, semilla, con_musica)

    # 3) Subtítulos
    print("   💬 Subtítulos", flush=True)
    archivo_ass = trabajo / "subtitulos.ass"
    subtitulos.crear_ass(guion.frases, duracion, ajustes["personajes"], ajustes, archivo_ass)

    # 4) Gráficos: avatares, bocadillos, gancho, humo, barra de progreso
    print("   🎨 Gráficos", flush=True)
    capas = graficos.crear_capas(guion, ajustes["personajes"], duracion, trabajo, semilla)

    # 5) Montaje
    print("   🎬 Montando el vídeo…", flush=True)
    nombre = guion.nombre + ("" if motor == "edge" else SUFIJO_PRUEBA)
    salida = config.CARPETA_SALIDA / f"{nombre}.mp4"
    # Se crea aparte y se mueve al final: así nunca queda un vídeo a medias en "salida"
    temporal = trabajo / "video.mp4"
    codificador = render.renderizar(temporal, duracion, pista_final, archivo_ass, capas, ajustes, trabajo, semilla)
    temporal.replace(salida)

    # 6) Texto para publicar
    avisos = publicacion.crear_texto(guion, duracion, motor, salida.with_suffix(".txt"))
    if duracion > float(ajustes["video"].get("duracion_aviso", 59)):
        avisos.append(f"Dura {duracion:.0f} s: para Shorts/TikTok mejor menos de 60 s (acorta el guion).")
    if motor == "edge":   # ya hay versión buena: se borra la de prueba
        for viejo in (salidas(guion.nombre)[1], salidas(guion.nombre)[1].with_suffix(".txt")):
            viejo.unlink(missing_ok=True)

    if not conservar:
        shutil.rmtree(trabajo, ignore_errors=True)
    return Resultado(salida, duracion, motor, codificador.nombre, time.time() - reloj, avisos)
