"""Comprueba que todo lo necesario está instalado.

Uso:  python comprobar.py      (en Windows: doble clic en comprobar.bat)
"""
import importlib
import sys

problemas = 0


def ok(texto):
    print(f"   ✅ {texto}")


def mal(texto, ayuda):
    global problemas
    problemas += 1
    print(f"   ❌ {texto}")
    print(f"      → {ayuda}")


def aviso(texto):
    print(f"   ⚠️  {texto}")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    print("\n=== Comprobando la fábrica de shorts ===\n")

    print("1) Python")
    version = sys.version.split()[0]
    if sys.version_info < (3, 11):
        mal(f"Tienes Python {version}", "Instala Python 3.12 desde https://www.python.org/downloads/")
        return 1
    ok(f"Python {version}")

    from fabrica import config, herramientas

    config.preparar_consola()
    config.cargar_env()

    print("\n2) Librerías de Python")
    for modulo, paquete in [("edge_tts", "edge-tts"), ("PIL", "Pillow"),
                            ("numpy", "numpy"), ("dotenv", "python-dotenv")]:
        try:
            importlib.import_module(modulo)
            ok(paquete)
        except ImportError:
            mal(f"Falta {paquete}", "Ejecuta instalar.bat (o: pip install -r requirements.txt)")

    print("\n3) ffmpeg")
    try:
        ruta = herramientas.ruta_ffmpeg()
        mayor, menor = herramientas.version_ffmpeg()
        ok(f"ffmpeg {mayor}.{menor} en {ruta}")
        herramientas.ruta_ffprobe()
        ok("ffprobe")
        filtros = herramientas.filtros_disponibles()
        necesarios = ["subtitles", "overlay", "gradients", "loudnorm", "sidechaincompress", "amix"]
        faltan = [f for f in necesarios if f not in filtros]
        if faltan:
            mal(f"A tu ffmpeg le faltan filtros: {', '.join(faltan)}",
                "Instala la versión completa: winget install Gyan.FFmpeg")
        else:
            ok("Filtros de vídeo y audio necesarios")
    except herramientas.ErrorFabrica as e:
        mal("ffmpeg no está listo", str(e))

    print("\n4) Tarjeta gráfica (NVENC)")
    try:
        from fabrica import render
        codificador = render.elegir_codificador("auto")
        if "NVENC" in codificador.nombre:
            ok("NVENC funciona: los vídeos se renderizan con la NVIDIA 🚀")
        else:
            aviso("NVENC no disponible: se usará el procesador (funciona igual, pero más lento).")
            print("      Si tienes una NVIDIA, actualiza su driver y vuelve a comprobar.")
    except herramientas.ErrorFabrica as e:
        mal("No se pudo probar el codificador", str(e))

    print("\n5) Tipografías")
    for fuente in (config.FUENTE_SUBTITULOS, config.FUENTE_NOMBRES):
        if fuente.exists():
            ok(fuente.name)
        else:
            mal(f"Falta {fuente.name}", "Vuelve a descargar el proyecto desde GitHub")

    print("\n6) Archivo .env (claves)")
    if config.ARCHIVO_ENV.exists():
        ok(".env encontrado (recuerda: nunca se sube a GitHub)")
    else:
        aviso("No hay .env. Ahora mismo no hace falta; instalar.bat lo crea solo.")

    print()
    if problemas:
        print(f"Hay {problemas} problema(s). Arréglalos siguiendo las flechas → y vuelve a comprobar.")
        return 1
    print("¡Todo listo! 🎬")
    return 0


if __name__ == "__main__":
    sys.exit(main())
