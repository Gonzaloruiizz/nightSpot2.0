"""Texto listo para copiar y pegar al subir cada vídeo a YouTube Shorts y TikTok."""
from __future__ import annotations

from pathlib import Path

from .guion import Guion

AVISO_SALUD = ("Vídeo de humor con fines informativos. Si quieres dejar el vaper, "
               "habla con un profesional de la salud.")


def crear_texto(guion: Guion, duracion: float, motor_voz: str, destino: Path) -> list[str]:
    """Escribe el .txt de publicación. Devuelve una lista de avisos (si los hay)."""
    avisos = []
    titulo = guion.titulo or guion.nombre.replace("_", " ").capitalize()
    if len(titulo) > 100:
        avisos.append(f"El título tiene {len(titulo)} caracteres (YouTube admite 100).")
    hashtags = guion.hashtags.strip()
    hashtags_tiktok = " ".join(h for h in hashtags.split() if h.lower() not in ("#shorts", "#short"))

    partes = [
        "════════ YOUTUBE SHORTS ════════",
        "TÍTULO:",
        titulo,
        "",
        "DESCRIPCIÓN:",
        guion.descripcion,
        "",
        hashtags,
        "",
        f"Fuentes: {guion.fuentes}" if guion.fuentes else "",
        AVISO_SALUD,
        "",
        "════════ TIKTOK ════════",
        "TEXTO:",
        f"{titulo} {hashtags_tiktok}".strip(),
        "",
        "════════ ANTES DE PUBLICAR ════════",
        "• Las voces son sintéticas (hechas con IA). En TikTok activa «Contenido generado por IA»",
        "  (Más opciones) al publicar. En YouTube, la casilla de «contenido alterado o sintético» es",
        "  para cosas que parecen reales; con dibujos y emojis normalmente no hace falta, pero si dudas, márcala.",
        "• YouTube → «¿Es contenido para niños?» → No.",
        f"• Duración: {duracion:.1f} s.",
    ]
    if motor_voz != "edge":
        partes.append("• ⚠️ ESTE VÍDEO LLEVA LA VOZ DE PRUEBA. No lo publiques: créalo otra vez con internet.")
    destino.write_text("\n".join(partes).replace("\n\n\n", "\n\n") + "\n", encoding="utf-8")
    return avisos
