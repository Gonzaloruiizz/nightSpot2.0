"""Voces: convierte cada frase en audio y sabe en qué momento se dice cada palabra.

Motores (con "auto" se prueban en este orden):
  edge   → voz DOMINICANA de Microsoft (es-DO-EmilioNeural). Gratis, necesita internet.
  kokoro → voz neuronal en español SIN internet (Kokoro, licencia libre). No tiene acento
           dominicano, pero se entiende bien. Respaldo y pruebas en la nube.
           La primera vez descarga el modelo (~120 MB) a .cache/modelos.
  robot  → último recurso: voz robótica (o silencio) solo para probar.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import sys
import urllib.request
import wave
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path

from . import config, herramientas
from .guion import Frase, normalizar
from .herramientas import ErrorFabrica

FRECUENCIA = 48000
CARPETA_CACHE_VOZ = config.CARPETA_CACHE / "voz"
CARPETA_MODELOS = config.CARPETA_CACHE / "modelos"
URL_KOKORO = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/{}"
ARCHIVOS_KOKORO = ("kokoro-v1.0.int8.onnx", "voices-v1.0.bin")
ORDEN_MOTORES = {"auto": ["edge", "kokoro", "robot"], "edge": ["edge"], "prueba": ["kokoro", "robot"]}


@dataclass
class AudioFrase:
    wav: Path
    duracion: float
    marcas: list[tuple[str, float, float]]   # (palabra dicha, inicio, fin) en segundos
    motor: str


# ─── Motores ───────────────────────────────────────────────────

LIMITE_EDGE = 45   # segundos máximos de espera por frase (para no quedarse colgado sin internet)


def _edge(texto: str, personaje: dict, destino: Path) -> list[tuple[str, float, float]]:
    import edge_tts

    audio = bytearray()
    marcas = []

    async def descargar():
        comunicacion = edge_tts.Communicate(
            texto, personaje["voz"], rate=personaje.get("velocidad", "+0%"),
            pitch=personaje.get("tono", "+0Hz"), boundary="WordBoundary")
        async for trozo in comunicacion.stream():
            if trozo["type"] == "audio":
                audio.extend(trozo["data"])
            elif trozo["type"] == "WordBoundary":
                inicio = trozo["offset"] / 1e7          # viene en unidades de 100 ns
                marcas.append((trozo["text"], inicio, inicio + trozo["duration"] / 1e7))

    async def con_limite():
        await asyncio.wait_for(descargar(), timeout=LIMITE_EDGE)

    try:
        if sys.platform == "win32" and sys.version_info >= (3, 12):
            # En Windows este tipo de bucle evita mensajes de error falsos al terminar
            asyncio.run(con_limite(), loop_factory=asyncio.SelectorEventLoop)
        else:
            asyncio.run(con_limite())
    except asyncio.TimeoutError:
        raise ErrorFabrica(f"La voz de Microsoft no respondió en {LIMITE_EDGE} s (¿hay internet?).") from None
    if not audio:
        raise ErrorFabrica("La voz de Microsoft no devolvió audio.")
    mp3 = destino.with_suffix(".mp3")
    mp3.write_bytes(audio)
    herramientas.ffmpeg("-i", str(mp3), "-ac", "1", "-ar", str(FRECUENCIA), str(destino))
    mp3.unlink()
    return marcas


def _factor_tono(personaje: dict) -> float:
    m = re.match(r"([+-]?\d+)\s*Hz", personaje.get("tono", "+0Hz"))
    hz = int(m.group(1)) if m else 0
    return min(1.35, max(0.75, 1 + hz / 130))


@lru_cache(maxsize=1)
def _modelo_kokoro():
    from kokoro_onnx import Kokoro

    CARPETA_MODELOS.mkdir(parents=True, exist_ok=True)
    for nombre in ARCHIVOS_KOKORO:
        ruta = CARPETA_MODELOS / nombre
        if not ruta.exists():
            print(f"   ⬇️  Descargando la voz sin internet ({nombre}). Solo pasa la primera vez…", flush=True)
            parcial = ruta.with_name(ruta.name + ".parcial")
            urllib.request.urlretrieve(URL_KOKORO.format(nombre), parcial)
            parcial.replace(ruta)
    return Kokoro(str(CARPETA_MODELOS / ARCHIVOS_KOKORO[0]), str(CARPETA_MODELOS / ARCHIVOS_KOKORO[1]))


def _kokoro(texto: str, personaje: dict, destino: Path) -> list[tuple[str, float, float]]:
    import numpy as np

    modelo = _modelo_kokoro()
    voz = personaje.get("voz_respaldo", "em_alex")
    velocidad = float(personaje.get("velocidad_respaldo", 1.0))
    # Se genera por trozos (entre signos de puntuación) para saber dónde empieza cada trozo
    trozos = [t for t in re.split(r"(?<=[,.;:!?…])\s+", texto) if normalizar(t)]
    piezas, marcas, cursor, frecuencia = [], [], 0.0, 24000
    for trozo in trozos:
        muestras, frecuencia = modelo.create(trozo, voice=voz, speed=velocidad, lang="es")
        sonido = np.flatnonzero(np.abs(muestras) > 0.01)
        if len(sonido):
            margen = int(0.03 * frecuencia)
            muestras = muestras[max(0, sonido[0] - margen): sonido[-1] + margen]
        duracion = len(muestras) / frecuencia
        palabras = [w for w in trozo.split() if normalizar(w)]
        marcas += [(w, cursor + a, cursor + b) for w, a, b in _marcas_proporcionales(palabras, duracion)]
        pausa = 0.28 if trozo.rstrip()[-1] in ".!?…" else 0.16 if trozo.rstrip()[-1] in ",;:" else 0.06
        piezas += [muestras, np.zeros(int(pausa * frecuencia), dtype=muestras.dtype)]
        cursor += duracion + pausa
    if not piezas:
        raise ErrorFabrica("La voz sin internet no generó audio.")
    crudo = destino.with_name(destino.stem + "_24k.wav")
    with wave.open(str(crudo), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(frecuencia)
        w.writeframes((np.clip(np.concatenate(piezas), -1, 1) * 32767).astype("<i2").tobytes())
    herramientas.ffmpeg("-i", str(crudo), "-ac", "1", "-ar", str(FRECUENCIA), str(destino))
    crudo.unlink()
    return marcas


def _robot(texto: str, personaje: dict, destino: Path) -> list[tuple[str, float, float]]:
    palabras = [w for w in texto.split() if normalizar(w)]
    if "flite" in herramientas.filtros_disponibles():
        archivo_texto = destino.with_suffix(".txt")
        archivo_texto.write_text(texto, encoding="utf-8")
        f = _factor_tono(personaje)
        herramientas.ffmpeg(
            "-f", "lavfi", "-i", f"flite=textfile={archivo_texto.name}:voice=kal16",
            "-af", f"aresample={FRECUENCIA},asetrate={FRECUENCIA * f:.0f},aresample={FRECUENCIA},atempo={1 / f:.4f}",
            "-ac", "1", "-ar", str(FRECUENCIA), destino.name, cwd=destino.parent)
        archivo_texto.unlink()
    else:
        segundos = 0.4 + 0.33 * len(palabras)
        herramientas.ffmpeg("-f", "lavfi", "-i", f"anullsrc=r={FRECUENCIA}:cl=mono",
                            "-t", f"{segundos:.2f}", str(destino))
    return _marcas_proporcionales(palabras, _duracion_wav(destino))


def _marcas_proporcionales(palabras: list[str], duracion: float) -> list[tuple[str, float, float]]:
    """Reparte el tiempo entre las palabras según lo largas que son."""
    if not palabras:
        return []
    pesos = [len(normalizar(w)) + 1 for w in palabras]
    total = sum(pesos)
    util = max(0.1, duracion - 0.1)
    marcas, t = [], 0.05
    for w, peso in zip(palabras, pesos):
        d = util * peso / total
        marcas.append((w, t, t + d * 0.9))
        t += d
    return marcas


MOTORES = {"edge": _edge, "kokoro": _kokoro, "robot": _robot}
NOMBRES = {"edge": "dominicana", "kokoro": "en español sin internet", "robot": "robot"}


# ─── Utilidades de audio ───────────────────────────────────────

def _duracion_wav(ruta: Path) -> float:
    with wave.open(str(ruta), "rb") as w:
        return w.getnframes() / w.getframerate()


def _recortar_final(ruta: Path, hasta: float) -> None:
    """Quita el silencio largo que algunas voces dejan al final."""
    with wave.open(str(ruta), "rb") as w:
        params = w.getparams()
        datos = w.readframes(min(w.getnframes(), int(hasta * w.getframerate())))
    with wave.open(str(ruta), "wb") as w:
        w.setparams(params)
        w.writeframes(datos)


# ─── API principal ─────────────────────────────────────────────

def sintetizar(texto: str, personaje: dict, motor: str) -> AudioFrase:
    """Audio de una frase, usando la caché si ya se hizo antes con el mismo texto y voz."""
    CARPETA_CACHE_VOZ.mkdir(parents=True, exist_ok=True)
    clave = "|".join([motor, json.dumps(personaje, sort_keys=True, ensure_ascii=False), texto])
    nombre = hashlib.sha1(clave.encode("utf-8")).hexdigest()[:16]
    wav = CARPETA_CACHE_VOZ / f"{motor}_{nombre}.wav"
    datos = wav.with_suffix(".json")
    if wav.exists() and datos.exists():
        marcas = [tuple(m) for m in json.loads(datos.read_text(encoding="utf-8"))]
        return AudioFrase(wav, _duracion_wav(wav), marcas, motor)

    temporal = wav.with_name(f"tmp_{wav.name}")
    try:
        marcas = MOTORES[motor](texto, personaje, temporal)
        if marcas:
            fin_voz = max(m[2] for m in marcas) + 0.25
            if _duracion_wav(temporal) > fin_voz:
                _recortar_final(temporal, fin_voz)
        temporal.replace(wav)
    finally:
        temporal.unlink(missing_ok=True)
    datos.write_text(json.dumps(marcas, ensure_ascii=False), encoding="utf-8")
    return AudioFrase(wav, _duracion_wav(wav), marcas, motor)


def alinear(frase: Frase, audio: AudioFrase) -> None:
    """Pone a cada palabra del subtítulo su momento exacto (segundos dentro de la frase)."""
    dichas = [(i, normalizar(w)) for i, p in enumerate(frase.palabras) for w in p.decir if normalizar(w)]
    marcas = [(normalizar(t), a, b) for t, a, b in audio.marcas if normalizar(t)]
    tiempos: list[tuple[float, float] | None] = [None] * len(dichas)
    emparejador = SequenceMatcher(None, [d for _, d in dichas], [m[0] for m in marcas], autojunk=False)
    for bloque in emparejador.get_matching_blocks():
        for k in range(bloque.size):
            _, a, b = marcas[bloque.b + k]
            tiempos[bloque.a + k] = (a, b)

    # Las palabras que no se emparejaron se reparten entre sus vecinas
    k = 0
    while k < len(tiempos):
        if tiempos[k] is not None:
            k += 1
            continue
        fin_hueco = k
        while fin_hueco < len(tiempos) and tiempos[fin_hueco] is None:
            fin_hueco += 1
        desde = tiempos[k - 1][1] if k > 0 else 0.05
        hasta = tiempos[fin_hueco][0] if fin_hueco < len(tiempos) else audio.duracion - 0.05
        hasta = max(hasta, desde + 0.05 * (fin_hueco - k))
        trozos = [m for _, m in dichas[k:fin_hueco]]
        for j, (_, a, b) in enumerate(_marcas_proporcionales(trozos, hasta - desde)):
            tiempos[k + j] = (desde + a - 0.05, desde + b - 0.05)
        k = fin_hueco

    anterior = 0.0
    for i, palabra in enumerate(frase.palabras):
        propios = [t for (indice, _), t in zip(dichas, tiempos) if indice == i and t is not None]
        if propios:
            palabra.inicio = max(anterior, min(t[0] for t in propios))
            palabra.fin = max(palabra.inicio + 0.05, max(t[1] for t in propios))
        else:
            palabra.inicio = palabra.fin = anterior
        anterior = palabra.inicio


def crear_pista(frases: list[Frase], ajustes: dict, motor_pedido: str, destino: Path) -> tuple[float, str]:
    """Crea la pista de voz completa (todas las frases seguidas).

    Rellena los tiempos de frases y palabras (en segundos del vídeo).
    Devuelve (duración de la pista, motor usado).
    """
    personajes = ajustes["personajes"]
    pausa = float(ajustes.get("voz", {}).get("pausa_entre_frases", 0.22))
    motores = ORDEN_MOTORES.get(motor_pedido, ORDEN_MOTORES["auto"])
    audios: list[AudioFrase] = []
    for motor in motores:
        audios = []
        try:
            for numero, frase in enumerate(frases, start=1):
                nombre = personajes[frase.personaje]["nombre"]
                print(f"   🎙️  Voz {numero}/{len(frases)} ({nombre}, voz {NOMBRES[motor]})", flush=True)
                audios.append(sintetizar(frase.texto_voz, personajes[frase.personaje], motor))
            break
        except Exception as error:
            if motor == motores[-1]:
                raise ErrorFabrica(f"No se pudo crear la voz: {error}") from error
            siguiente = NOMBRES[motores[motores.index(motor) + 1]]
            print(f"   ⚠️  La voz {NOMBRES[motor]} no está disponible ({type(error).__name__}). "
                  f"Uso la voz {siguiente}.", flush=True)

    with wave.open(str(destino), "wb") as salida:
        salida.setnchannels(1)
        salida.setsampwidth(2)
        salida.setframerate(FRECUENCIA)
        cursor = 0.0
        for frase, audio in zip(frases, audios):
            alinear(frase, audio)
            frase.inicio = cursor
            frase.fin = cursor + audio.duracion
            for palabra in frase.palabras:
                palabra.inicio += cursor
                palabra.fin += cursor
            with wave.open(str(audio.wav), "rb") as entrada:
                if (entrada.getnchannels(), entrada.getsampwidth(), entrada.getframerate()) != (1, 2, FRECUENCIA):
                    raise ErrorFabrica(f"Formato de audio inesperado en {audio.wav.name}")
                salida.writeframes(entrada.readframes(entrada.getnframes()))
            salida.writeframes(b"\x00\x00" * int(pausa * FRECUENCIA))
            cursor = frase.fin + pausa
    return cursor, motor


def probar_voz_dominicana() -> int:
    """Pide a Microsoft una frase corta. Devuelve cuántas palabras llegaron sincronizadas."""
    config.CARPETA_CACHE.mkdir(parents=True, exist_ok=True)
    destino = config.CARPETA_CACHE / "prueba_voz.wav"
    try:
        return len(_edge("Qué lo que, esto es una prueba.", {"voz": "es-DO-EmilioNeural"}, destino))
    finally:
        destino.unlink(missing_ok=True)
