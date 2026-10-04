"""Voz (texto a voz) y oído (voz a texto) de Rochi."""

from __future__ import annotations

import ctypes
import logging
import os
import re
import sys
import tempfile
import threading
import time
import unicodedata
from typing import Optional

log = logging.getLogger("rochi.voz")

_VOCES_ESPANOL = r"spanish|español|espanol|sabina|helena|laura|pablo|raul|elvira|alvaro"


def limpiar_para_voz(texto: str) -> str:
    """Quita lo que no se debe leer en voz alta: markdown, emojis y símbolos."""
    texto = re.sub(r"\s*°\s*(C\b)?", " grados", texto)
    texto = re.sub(r"[*_#`~>|\[\]{}]", " ", texto)
    texto = "".join(c for c in texto if unicodedata.category(c) not in ("So", "Sk", "Cs", "Co"))
    return " ".join(texto.split())


def reproducir_mp3(ruta: str) -> None:
    """Reproduce un MP3 con MCI de Windows (sin dependencias extra) y espera a que termine."""
    winmm = ctypes.windll.winmm
    alias = f"rochi{threading.get_ident()}"

    def mci(orden: str) -> None:
        error = winmm.mciSendStringW(orden, None, 0, None)
        if error:
            mensaje = ctypes.create_unicode_buffer(256)
            winmm.mciGetErrorStringW(error, mensaje, 255)
            raise OSError(f"MCI: {mensaje.value}")

    mci(f'open "{ruta}" type mpegvideo alias {alias}')
    try:
        mci(f"play {alias} wait")
    finally:
        winmm.mciSendStringW(f"close {alias}", None, 0, None)


class Voz:
    """Habla con voz neuronal dominicana (edge-tts) y cae a las voces SAPI de Windows si no hay internet."""

    def __init__(self, cfg: dict, mudo: bool = False, eco: bool = True):
        self.cfg = cfg["voz"]
        self.mudo = mudo
        self.eco = eco  # el servidor MCP lo apaga: su stdout es el canal del protocolo
        self._candado = threading.Lock()
        self._hablando = False
        self.ultimo_fin = 0.0

    def hablo_desde(self, momento: float) -> bool:
        """¿Rochi habló (o está hablando) desde ese momento? Sirve para no escucharse a sí mismo."""
        return self._hablando or self.ultimo_fin > momento

    def hablar(self, texto: str) -> None:
        texto = limpiar_para_voz(texto)
        if not texto:
            return
        if self.eco:
            print(f"Rochi: {texto}", flush=True)
        if self.mudo or sys.platform != "win32":
            return
        with self._candado:
            self._hablando = True
            try:
                if self.cfg["motor"] == "edge":
                    try:
                        self._hablar_edge(texto)
                        return
                    except Exception:
                        log.warning("edge-tts falló; uso las voces de Windows", exc_info=True)
                self._hablar_sapi(texto)
            finally:
                self._hablando = False
                self.ultimo_fin = time.monotonic()

    def _hablar_edge(self, texto: str) -> None:
        import edge_tts

        descriptor, ruta = tempfile.mkstemp(prefix="rochi_", suffix=".mp3")
        os.close(descriptor)
        try:
            edge_tts.Communicate(texto, self.cfg["voz_edge"], rate=self.cfg["velocidad"]).save_sync(ruta)
            reproducir_mp3(ruta)
        finally:
            try:
                os.remove(ruta)
            except OSError:
                pass

    def _hablar_sapi(self, texto: str) -> None:
        import comtypes
        import comtypes.client

        try:
            comtypes.CoInitialize()
        except OSError:
            pass
        sapi = comtypes.client.CreateObject("SAPI.SpVoice")
        preferida = self.cfg.get("voz_sapi", "").lower()
        voces = sapi.GetVoices()
        for i in range(voces.Count):
            voz = voces.Item(i)
            descripcion = voz.GetDescription()
            if (preferida and preferida in descripcion.lower()) or (not preferida and re.search(_VOCES_ESPANOL, descripcion, re.I)):
                sapi.Voice = voz
                break
        sapi.Speak(texto)


class Oido:
    """Escucha el micrófono y transcribe con Google (gratis, online) o faster-whisper (local, en la GPU)."""

    def __init__(self, cfg: dict, voz: Voz):
        import speech_recognition as sr

        self.sr = sr
        self.cfg = cfg["oido"]
        self.voz = voz
        self.reconocedor = sr.Recognizer()
        self.reconocedor.pause_threshold = self.cfg["pausa_seg"]
        self.reconocedor.dynamic_energy_threshold = True
        self.microfono = sr.Microphone(device_index=self.cfg["microfono"])
        with self.microfono as fuente:
            self.reconocedor.adjust_for_ambient_noise(fuente, duration=1.0)

        self._whisper = None
        if self.cfg["motor"] == "whisper":
            from faster_whisper import WhisperModel

            dispositivo = self.cfg["dispositivo_whisper"]
            tipo = {"cuda": "float16", "cpu": "int8"}.get(dispositivo, "default")
            log.info("Cargando Whisper '%s' en %s...", self.cfg["modelo_whisper"], dispositivo)
            self._whisper = WhisperModel(self.cfg["modelo_whisper"], device=dispositivo, compute_type=tipo)

    def escuchar(self, timeout: Optional[float] = None) -> Optional[str]:
        """Espera una frase. Devuelve None si no hubo nada (o si lo que entró fue la propia voz de Rochi)."""
        inicio = time.monotonic()
        with self.microfono as fuente:
            try:
                audio = self.reconocedor.listen(fuente, timeout=timeout, phrase_time_limit=self.cfg["limite_frase_seg"])
            except self.sr.WaitTimeoutError:
                return None
        if self.voz.hablo_desde(inicio):
            return None
        return self._transcribir(audio)

    def _transcribir(self, audio) -> Optional[str]:
        if self._whisper is not None:
            import numpy as np

            crudo = audio.get_raw_data(convert_rate=16000, convert_width=2)
            muestras = np.frombuffer(crudo, np.int16).astype(np.float32) / 32768.0
            segmentos, _ = self._whisper.transcribe(
                muestras,
                language=self.cfg["idioma"].split("-")[0],
                beam_size=1,
                vad_filter=True,
                initial_prompt="Rochi, ¿estás ahí?",  # ayuda a que escriba bien el nombre
            )
            return " ".join(s.text for s in segmentos).strip() or None
        try:
            return self.reconocedor.recognize_google(audio, language=self.cfg["idioma"])
        except self.sr.UnknownValueError:
            return None
        except self.sr.RequestError as error:
            log.warning("El reconocimiento de Google falló: %s", error)
            return None


class Teclado:
    """Entrada por texto para probar a Rochi sin micrófono (python rochi.py --texto)."""

    def escuchar(self, timeout: Optional[float] = None) -> Optional[str]:
        try:
            return input("Tú: ").strip() or None
        except EOFError:
            raise KeyboardInterrupt
