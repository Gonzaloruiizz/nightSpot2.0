"""Imágenes de emojis (Noto Emoji de Google, licencia Apache 2.0).

Se guardan en assets/emojis/. Si falta alguno, se descarga una vez de GitHub.
"""
from __future__ import annotations

import urllib.request
from functools import lru_cache

from PIL import Image

from . import config

VERSION_NOTO = "v2.047"
URL = "https://raw.githubusercontent.com/googlefonts/noto-emoji/{version}/png/512/{nombre}"


def nombre_archivo(emoji: str) -> str:
    """'🧔🏽‍♂️' → 'emoji_u1f9d4_1f3fd_200d_2642.png' (como los llama Noto)."""
    return "emoji_u" + "_".join(f"{ord(c):04x}" for c in emoji if c != "️") + ".png"


@lru_cache(maxsize=None)
def imagen(emoji: str) -> Image.Image | None:
    """Devuelve el emoji como imagen 512×512 (o None si no se pudo conseguir)."""
    ruta = config.CARPETA_EMOJIS / nombre_archivo(emoji)
    if not ruta.exists():
        try:
            url = URL.format(version=VERSION_NOTO, nombre=ruta.name)
            with urllib.request.urlopen(url, timeout=20) as respuesta:
                datos = respuesta.read()
            config.CARPETA_EMOJIS.mkdir(parents=True, exist_ok=True)
            ruta.write_bytes(datos)
        except Exception:
            print(f"   ⚠️  No pude conseguir la imagen del emoji {emoji} (se omite).")
            return None
    return Image.open(ruta).convert("RGBA")
