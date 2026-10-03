"""Genera muestras de voces caribeñas para elegir la de cada personaje.

Uso:  python probar_voces.py      (en Windows: doble clic en probar_voces.bat)
Crea la carpeta salida/muestras_voces/ con un MP3 por voz. Escúchalos y copia
en ajustes.toml (voz, velocidad, tono) los que más te gusten para cada personaje.
Necesita internet (son las voces de Microsoft).
"""
from __future__ import annotations

import sys

from fabrica import config, herramientas, voz

FRASE = ("Qué lo que mi gente. ¿Tú cree que ese véiper e' aire con sabor a mango? "
         "¡Mentira! Eso trae nicotina, mi hijo.")

# (archivo, voz, velocidad, tono, para quién)
MUESTRAS = [
    ("01_emilio_normal", "es-DO-EmilioNeural", "+0%", "+0Hz", "dominicano, tal cual"),
    ("02_emilio_don_fello", "es-DO-EmilioNeural", "-6%", "-6Hz", "dominicano, más grave y lento (Don Fello)"),
    ("03_emilio_yefri", "es-DO-EmilioNeural", "+10%", "+8Hz", "dominicano, más joven y rápido (Yefri)"),
    ("04_victor_puerto_rico", "es-PR-VictorNeural", "+0%", "+0Hz", "puertorriqueño (caribeño)"),
    ("05_victor_yefri", "es-PR-VictorNeural", "+10%", "+6Hz", "puertorriqueño, más joven"),
    ("06_manuel_cuba", "es-CU-ManuelNeural", "+0%", "+0Hz", "cubano (caribeño)"),
    ("07_manuel_don_fello", "es-CU-ManuelNeural", "-6%", "-6Hz", "cubano, más grave"),
    ("08_sebastian_venezuela", "es-VE-SebastianNeural", "+0%", "+0Hz", "venezolano (caribeño)"),
    ("09_ramona_dominicana", "es-DO-RamonaNeural", "+0%", "+0Hz", "dominicana (mujer), por si quieres otro personaje"),
]


def main() -> int:
    config.preparar_consola()
    config.cargar_env()
    carpeta = config.CARPETA_SALIDA / "muestras_voces"
    carpeta.mkdir(parents=True, exist_ok=True)
    print("\n🎙️  Creando muestras de voces (necesita internet)…\n")
    hechas = 0
    for archivo, nombre_voz, velocidad, tono, descripcion in MUESTRAS:
        wav = carpeta / f"{archivo}.wav"
        try:
            voz._edge(FRASE, {"voz": nombre_voz, "velocidad": velocidad, "tono": tono}, wav)
            herramientas.ffmpeg("-i", str(wav), "-b:a", "160k", str(wav.with_suffix(".mp3")))
            wav.unlink()
            hechas += 1
            print(f"   ✅ {archivo}.mp3  →  {descripcion}")
            print(f"      voz = \"{nombre_voz}\"   velocidad = \"{velocidad}\"   tono = \"{tono}\"")
        except Exception as e:
            print(f"   ❌ {archivo}: {type(e).__name__} {e}")
    if not hechas:
        print("\nNo se pudo crear ninguna muestra. ¿Hay internet?")
        return 1
    print(f"\n📁 Escúchalas en: {carpeta}")
    print("Cuando elijas, abre ajustes.toml y copia voz / velocidad / tono en el personaje que quieras.")
    print("Después borra la caché de voces (carpeta .cache\\voz) si quieres rehacer vídeos ya creados.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
