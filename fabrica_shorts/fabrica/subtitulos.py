"""Subtítulos estilo TikTok (formato ASS): palabras grandes que se iluminan al decirlas."""
from __future__ import annotations

from pathlib import Path

from .guion import Frase

MAX_PALABRAS = 3        # palabras por golpe de subtítulo
MAX_LETRAS = 15         # para que quepa en una sola línea
FINAL_DE_FRASE = (".", "?", "!", "…", ",", ";", ":")
POSICION_SUBTITULOS = (540, 1335)


def color_ass(hex_rgb: str) -> str:
    """'#FFC93C' → '&H3CC9FF&' (ASS guarda los colores al revés: azul-verde-rojo)."""
    h = hex_rgb.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{b}{g}{r}&".upper()


def tiempo_ass(segundos: float) -> str:
    cs = max(0, round(segundos * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _limpiar(texto: str) -> str:
    return texto.replace("\\", "").replace("{", "(").replace("}", ")")


def _golpes(frase: Frase) -> list[list[int]]:
    """Agrupa las palabras de una frase en golpes cortos de subtítulo."""
    grupos: list[list[int]] = []
    actual: list[int] = []
    letras = 0
    for i, palabra in enumerate(frase.palabras):
        largo = len(palabra.mostrar)
        if actual and (len(actual) >= MAX_PALABRAS or letras + largo + 1 > MAX_LETRAS):
            grupos.append(actual)
            actual, letras = [], 0
        actual.append(i)
        letras += largo + 1
        if palabra.mostrar.endswith(FINAL_DE_FRASE):
            grupos.append(actual)
            actual, letras = [], 0
    if actual:
        grupos.append(actual)
    return grupos


CABECERA = """[Script Info]
ScriptType: v4.00+
PlayResX: {ancho}
PlayResY: {alto}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,Luckiest Guy,96,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,0,0,0,0,100,100,1,0,1,8,5,5,70,70,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def crear_ass(frases: list[Frase], duracion: float, personajes: dict, ajustes: dict, destino: Path) -> None:
    v = ajustes["video"]
    lineas = [CABECERA.format(ancho=v["ancho"], alto=v["alto"])]

    x, y = POSICION_SUBTITULOS
    for n, frase in enumerate(frases):
        color = color_ass(personajes[frase.personaje].get("color", "#FFE14D"))
        siguiente_frase = frases[n + 1].inicio if n + 1 < len(frases) else duracion
        grupos = _golpes(frase)
        for g, grupo in enumerate(grupos):
            fin_grupo = (frase.palabras[grupos[g + 1][0]].inicio if g + 1 < len(grupos)
                         else min(siguiente_frase, frase.fin + 0.4))
            for k, indice in enumerate(grupo):
                inicio = frase.palabras[indice].inicio
                fin = frase.palabras[grupo[k + 1]].inicio if k + 1 < len(grupo) else fin_grupo
                if fin - inicio < 0.01:
                    continue
                trozos = []
                for j in grupo:
                    palabra = _limpiar(frase.palabras[j].mostrar).upper()
                    if j == indice:   # la palabra que suena ahora: color del personaje y "pop"
                        trozos.append(r"{\c%s\fscx122\fscy122\t(0,100,\fscx110\fscy110)}%s{\c&HFFFFFF&\fscx100\fscy100}"
                                      % (color, palabra))
                    else:
                        trozos.append(palabra)
                texto = r"{\an5\pos(%d,%d)}" % (x, y) + " ".join(trozos)
                lineas.append(f"Dialogue: 1,{tiempo_ass(inicio)},{tiempo_ass(fin)},Sub,,0,0,0,,{texto}")

    destino.write_text("\n".join(lineas) + "\n", encoding="utf-8")
