"""Crea los vídeos a partir de los guiones.

Uso (en Windows también vale doble clic en crear_videos.bat):
    python crear_videos.py                 → crea los guiones que aún no tienen vídeo
    python crear_videos.py 01 03           → solo los guiones cuyo nombre contiene "01" o "03"
    python crear_videos.py --forzar        → vuelve a crear también los que ya existen
    python crear_videos.py --voz prueba    → sin internet (voz de prueba)
    python crear_videos.py --sin-musica    → sin el dembow de fondo
"""
from __future__ import annotations

import argparse
import sys
import time

from fabrica import config
from fabrica.herramientas import ErrorFabrica


def main() -> int:
    config.preparar_consola()
    config.cargar_env()
    ajustes = config.cargar_ajustes()

    parser = argparse.ArgumentParser(description="Fábrica de shorts")
    parser.add_argument("filtros", nargs="*", help="parte del nombre de los guiones a crear")
    parser.add_argument("--forzar", action="store_true", help="rehace también los vídeos que ya existen")
    parser.add_argument("--voz", choices=["auto", "edge", "prueba"],
                        default=ajustes.get("voz", {}).get("motor", "auto"))
    parser.add_argument("--sin-musica", action="store_true",
                        help="sin música de fondo (p. ej. para poner un sonido de TikTok al subirlo)")
    parser.add_argument("--conservar", action="store_true", help="no borra los archivos intermedios")
    args = parser.parse_args()

    from fabrica import voz
    from fabrica.produccion import producir, salidas

    guiones = sorted(p for p in config.CARPETA_GUIONES.glob("*.txt") if not p.name.startswith("_"))
    if args.filtros:
        guiones = [g for g in guiones if any(f in g.stem for f in args.filtros)]

    # ¿Qué falta por hacer?
    voz_real_disponible = None
    pendientes, saltados = [], []
    for g in guiones:
        real, prueba = salidas(g.stem)
        if args.forzar or not (real.exists() or prueba.exists()):
            pendientes.append(g)
        elif real.exists():
            saltados.append(g)
        else:
            # Solo hay versión con voz de prueba: se rehace si ahora hay voz dominicana
            if voz_real_disponible is None:
                voz_real_disponible = args.voz != "prueba" and _hay_voz_real(voz)
            (pendientes if voz_real_disponible else saltados).append(g)

    print(f"\n🏭 Fábrica de shorts · {len(guiones)} guiones · {len(pendientes)} por crear · "
          f"{len(saltados)} ya hechos")
    if saltados and not args.forzar:
        print("   (para rehacer los ya hechos usa --forzar)")
    if not pendientes:
        print("\nNo hay nada nuevo que crear. ✨")
        return 0

    reloj = time.time()
    hechos, errores, avisos = [], [], []
    for numero, archivo in enumerate(pendientes, start=1):
        print(f"\n▶ [{numero}/{len(pendientes)}] {archivo.stem}")
        try:
            r = producir(archivo, ajustes, args.voz, args.conservar, con_musica=not args.sin_musica)
            hechos.append(r)
            print(f"   ✅ {r.video.name} · {r.duracion:.1f} s · voz: {r.motor_voz} · "
                  f"render: {r.codificador} · {r.segundos:.0f} s")
            for aviso in r.avisos:
                print(f"   ⚠️  {aviso}")
                avisos.append(f"{archivo.stem}: {aviso}")
        except ErrorFabrica as e:
            errores.append(archivo.stem)
            print(f"   ❌ {e}")
        except KeyboardInterrupt:
            print("\n⏹️  Parado por ti. Lo ya creado se queda guardado.")
            break

    minutos = (time.time() - reloj) / 60
    print("\n════════════════ RESUMEN ════════════════")
    print(f"✅ Creados: {len(hechos)}   ❌ Con error: {len(errores)}   ⏱️ {minutos:.1f} min")
    con_prueba = [r.video.name for r in hechos if r.motor_voz != "edge"]
    if con_prueba:
        print(f"⚠️  {len(con_prueba)} vídeo(s) con VOZ DE PRUEBA (no los publiques; repítelos con internet).")
    for aviso in avisos:
        print(f"⚠️  {aviso}")
    for nombre in errores:
        print(f"❌ {nombre}")
    print(f"📁 Vídeos y textos para publicar en: {config.CARPETA_SALIDA}")
    return 1 if errores else 0


def _hay_voz_real(voz) -> bool:
    try:
        voz.probar_voz_dominicana()
        return True
    except Exception:
        return False


if __name__ == "__main__":
    sys.exit(main())
