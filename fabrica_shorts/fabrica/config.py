"""Rutas de carpetas, lectura de ajustes.toml y del archivo .env."""
from __future__ import annotations

import os
import sys
import tomllib
from pathlib import Path

# Carpeta principal de la fábrica (fabrica_shorts/)
RAIZ = Path(__file__).resolve().parent.parent

CARPETA_GUIONES = RAIZ / "guiones"
CARPETA_SALIDA = RAIZ / "salida"
CARPETA_TRABAJO = RAIZ / ".trabajo"
CARPETA_CACHE = RAIZ / ".cache"
CARPETA_ASSETS = RAIZ / "assets"
CARPETA_FUENTES = CARPETA_ASSETS / "fuentes"
CARPETA_EMOJIS = CARPETA_ASSETS / "emojis"
CARPETA_MUSICA = CARPETA_ASSETS / "musica"
CARPETA_FONDOS = CARPETA_ASSETS / "fondos"
ARCHIVO_AJUSTES = RAIZ / "ajustes.toml"
ARCHIVO_ENV = RAIZ / ".env"

FUENTE_SUBTITULOS = CARPETA_FUENTES / "LuckiestGuy-Regular.ttf"
FUENTE_NOMBRES = CARPETA_FUENTES / "Anton-Regular.ttf"


def preparar_consola() -> None:
    """Evita errores al imprimir tildes y emojis en la consola de Windows."""
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def cargar_env() -> None:
    """Lee las claves del archivo .env (si existe) sin sobrescribir las del sistema."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    if ARCHIVO_ENV.exists():
        load_dotenv(ARCHIVO_ENV, override=False)


def leer_clave(nombre: str) -> str:
    """Devuelve una clave del .env o "" si no está puesta."""
    return os.environ.get(nombre, "").strip()


def cargar_ajustes() -> dict:
    with open(ARCHIVO_AJUSTES, "rb") as f:
        return tomllib.load(f)
