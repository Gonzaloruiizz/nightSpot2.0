"""Carga de la configuración de Rochi.

Los valores por defecto viven aquí; el usuario solo tiene que poner en
config.json lo que quiera cambiar (se mezcla en profundidad con DEFECTO).
"""

from __future__ import annotations

import copy
import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

CARPETA = Path(__file__).resolve().parent
RUTA_CONFIG = Path(os.environ.get("ROCHI_CONFIG", CARPETA / "config.json"))

DEFECTO: dict[str, Any] = {
    # Cerebro (API de Claude)
    "modelo": "claude-opus-5-5",
    "esfuerzo": "low",  # low | medium | high | xhigh | max  ("" para no enviarlo)
    "fallbacks": True,  # reintento automático en otro modelo si el clasificador rechaza la petición
    "prompt_sistema": "system_prompt.md",
    # Activación y memoria de la conversación
    "activacion": {
        "palabras": ["rochi", "rochy", "roshi", "rochie", "ruchi", "rochis"],
        "ventana_conversacion_seg": 45,
        "memoria_min": 10,
    },
    # Voz de Rochi (texto a voz)
    "voz": {
        "motor": "edge",  # edge (voces neuronales, necesita internet) | sapi (voces de Windows, offline)
        "voz_edge": "es-DO-EmilioNeural",  # o es-DO-RamonaNeural
        "velocidad": "+8%",
        "voz_sapi": "",  # parte del nombre de una voz SAPI instalada, p. ej. "Sabina" o "Helena"
    },
    # Oído de Rochi (voz a texto)
    "oido": {
        "motor": "google",  # google (gratis, online) | whisper (local con faster-whisper, usa la GPU)
        "idioma": "es-DO",
        "modelo_whisper": "small",
        "dispositivo_whisper": "cuda",  # cuda | cpu | auto
        "microfono": None,  # índice del micrófono; None = el predeterminado de Windows
        "limite_frase_seg": 12,
        "pausa_seg": 0.8,
    },
    # Alias de aplicaciones: nombre hablado -> lista de destinos a probar en orden
    "apps": {
        "opera": [
            "%LOCALAPPDATA%\\Programs\\Opera\\launcher.exe",
            "%LOCALAPPDATA%\\Programs\\Opera\\opera.exe",
        ],
        "opera gx": ["%LOCALAPPDATA%\\Programs\\Opera GX\\launcher.exe"],
        "steam": ["steam://open/main"],
        "discord": ["discord://"],
        "spotify": ["spotify:"],
        "calculadora": ["calc.exe"],
        "bloc de notas": ["notepad.exe"],
        "explorador": ["explorer.exe"],
        "administrador de tareas": ["taskmgr.exe"],
        "configuracion": ["ms-settings:"],
        "panel de control": ["control.exe"],
    },
    # Alias de páginas web
    "webs": {
        "youtube": "https://www.youtube.com",
        "google": "https://www.google.com",
        "gmail": "https://mail.google.com",
        "twitch": "https://www.twitch.tv",
        "netflix": "https://www.netflix.com",
        "whatsapp": "https://web.whatsapp.com",
        "instagram": "https://www.instagram.com",
        "facebook": "https://www.facebook.com",
        "x": "https://x.com",
        "twitter": "https://x.com",
        "reddit": "https://www.reddit.com",
        "claude": "https://claude.ai",
    },
    # Rutas de programas externos ("" = buscar en las ubicaciones habituales)
    "rutas": {
        "siete_zip": "",
        "cinebench": "",
        "occt": "",
        "speedtest": "",
        "nvidia_smi": "",
    },
    # Comandos personalizados para OCCT (solo ediciones con línea de comandos). Vacío = solo abre OCCT.
    "occt_comandos": {"occt_cpu": "", "occt_power": ""},
    # Sensores: servidor web de LibreHardwareMonitor (Opciones > Remote Web Server)
    "lhm_url": "http://localhost:8085/data.json",
    "capturas_dir": "",  # "" = Imágenes\Capturas de pantalla\Rochi
    "comando_timeout_seg": 60,
}


def _mezclar(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    resultado = copy.deepcopy(base)
    for clave, valor in extra.items():
        if isinstance(valor, dict) and isinstance(resultado.get(clave), dict):
            resultado[clave] = _mezclar(resultado[clave], valor)
        else:
            resultado[clave] = valor
    return resultado


@lru_cache(maxsize=1)
def cargar() -> dict[str, Any]:
    if RUTA_CONFIG.exists():
        with open(RUTA_CONFIG, encoding="utf-8") as f:
            return _mezclar(DEFECTO, json.load(f))
    return copy.deepcopy(DEFECTO)
