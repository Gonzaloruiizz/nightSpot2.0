"""Crea los vídeos a partir de los guiones.

Uso (en Windows también vale doble clic en crear_videos.bat):
    python crear_videos.py                 → crea todos los guiones de la carpeta guiones/
    python crear_videos.py 01 03           → solo los guiones cuyo nombre contiene "01" o "03"
    python crear_videos.py --voz prueba    → sin internet (voz de prueba)
    python crear_videos.py --sin-musica    → sin el dembow de fondo
"""
from __future__ import annotations

import argparse
import sys

from fabrica import config
from fabrica.herramientas import ErrorFabrica


def main() -> int:
    config.preparar_consola()
    config.cargar_env()
    ajustes = config.cargar_ajustes()

    parser = argparse.ArgumentParser(description="Fábrica de shorts")
    parser.add_argument("filtros", nargs="*", help="parte del nombre de los guiones a crear")
    parser.add_argument("--voz", choices=["auto", "edge", "prueba"],
                        default=ajustes.get("voz", {}).get("motor", "auto"))
    parser.add_argument("--sin-musica", action="store_true",
                        help="sin música de fondo (p. ej. para poner un sonido de TikTok al subirlo)")
    parser.add_argument("--conservar", action="store_true", help="no borra los archivos intermedios")
    args = parser.parse_args()

    from fabrica.produccion import producir

    guiones = sorted(p for p in config.CARPETA_GUIONES.glob("*.txt") if not p.name.startswith("_"))
    if args.filtros:
        guiones = [g for g in guiones if any(f in g.stem for f in args.filtros)]
    if not guiones:
        print("No hay guiones que crear en la carpeta 'guiones'.")
        return 0

    errores = 0
    for numero, archivo in enumerate(guiones, start=1):
        print(f"\n▶ [{numero}/{len(guiones)}] {archivo.stem}")
        try:
            r = producir(archivo, ajustes, args.voz, args.conservar, con_musica=not args.sin_musica)
            print(f"   ✅ {r.video.name} · {r.duracion:.1f} s · voz: {r.motor_voz} · "
                  f"render: {r.codificador} · {r.segundos:.0f} s")
        except ErrorFabrica as e:
            errores += 1
            print(f"   ❌ {e}")
    return 1 if errores else 0


if __name__ == "__main__":
    sys.exit(main())
