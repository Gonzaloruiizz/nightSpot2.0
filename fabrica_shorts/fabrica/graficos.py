"""Dibuja con Pillow las imágenes que van encima del vídeo y decide dónde y cuándo salen."""
from __future__ import annotations

import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from . import config, emojis
from .guion import EMOJI, Frase, Guion
from .render import Capa

# ─── Posiciones en pantalla (vídeo de 1080 × 1920) ───────────
CENTRO_X = {"izquierda": 290, "derecha": 790}
ARRIBA_TARJETA = 700          # donde empiezan los avatares
ARRIBA_GANCHO = 175           # debajo de los menús de TikTok / YouTube
ANCHO_GANCHO = 960
TAM_TARJETA = (420, 480)
ESCALA_INACTIVO = 0.8


def _fuente(ruta: Path, tamano: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(ruta), tamano)


def _color(hex_rgb: str) -> tuple[int, int, int]:
    h = hex_rgb.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _pegar_emoji(lienzo: Image.Image, emoji: str, centro: tuple[int, int], tamano: int, giro: float = 0) -> None:
    img = emojis.imagen(emoji)
    if img is None:
        return
    img = img.resize((tamano, tamano), Image.LANCZOS)
    if giro:
        img = img.rotate(giro, resample=Image.BICUBIC, expand=True)
    lienzo.alpha_composite(img, (centro[0] - img.width // 2, centro[1] - img.height // 2))


def _sombra(lienzo: Image.Image, forma, desplazamiento=(0, 10), radio=14, opacidad=130) -> None:
    capa = Image.new("RGBA", lienzo.size, (0, 0, 0, 0))
    ImageDraw.Draw(capa).ellipse(forma, fill=(0, 0, 0, opacidad))
    capa = capa.filter(ImageFilter.GaussianBlur(radio))
    lienzo.alpha_composite(capa, desplazamiento)


# ─── Tarjeta de personaje (avatar + nombre) ──────────────────

def tarjeta(personaje: dict, activo: bool) -> Image.Image:
    ancho, alto = TAM_TARJETA
    img = Image.new("RGBA", (ancho, alto), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    color = _color(personaje.get("color", "#FFFFFF"))
    cx, cy, radio = ancho // 2, 190, 165

    circulo = (cx - radio, cy - radio, cx + radio, cy + radio)
    _sombra(img, circulo)
    d.ellipse(circulo, fill=(*color, 255), outline=(255, 255, 255, 255), width=10)
    _pegar_emoji(img, personaje.get("avatar", "🙂"), (cx, cy + 10), 250)
    if personaje.get("sombrero"):
        _pegar_emoji(img, personaje["sombrero"], (cx - 8, cy - 118), 175, giro=12)
    if personaje.get("mano"):
        _pegar_emoji(img, personaje["mano"], (cx + 125, cy + 85), 120)

    fuente = _fuente(config.FUENTE_NOMBRES, 54)
    nombre = personaje.get("nombre", "").upper()
    ancho_texto = d.textlength(nombre, font=fuente)
    caja = (cx - ancho_texto / 2 - 30, 378, cx + ancho_texto / 2 + 30, 458)
    d.rounded_rectangle(caja, radius=40, fill=(15, 15, 20, 235), outline=(*color, 255), width=6)
    d.text((cx, 418), nombre, font=fuente, fill=(255, 255, 255, 255), anchor="mm")

    if not activo:
        # Apagado: menos color y algo transparente (sin oscurecer la piel)
        alfa = img.getchannel("A").point(lambda v: int(v * 0.8))
        rgb = ImageEnhance.Brightness(ImageEnhance.Color(img.convert("RGB")).enhance(0.45)).enhance(0.85)
        img = rgb.convert("RGBA")
        img.putalpha(alfa)
        img = img.resize((int(ancho * ESCALA_INACTIVO), int(alto * ESCALA_INACTIVO)), Image.LANCZOS)
    return img


# ─── Bocadillo con los emojis de la frase ────────────────────

def bocadillo(lista: list[str], cola_izquierda: bool) -> Image.Image:
    lista = lista[:3]
    tam, sep, margen, cola = 130, 18, 28, 42
    ancho = len(lista) * tam + (len(lista) - 1) * sep + 2 * margen
    alto = tam + 2 * margen
    img = Image.new("RGBA", (ancho + 20, alto + cola + 20), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    x_cola = int(ancho * (0.3 if cola_izquierda else 0.7)) + 10
    borde = (20, 20, 25, 255)
    d.rounded_rectangle((10, 10, ancho + 10, alto + 10), radius=48, fill=(255, 255, 255, 250), outline=borde, width=7)
    d.polygon([(x_cola - 26, alto + 4), (x_cola + 26, alto + 4), (x_cola, alto + cola + 8)],
              fill=(255, 255, 255, 250), outline=borde)
    d.line([(x_cola - 26, alto + 7), (x_cola, alto + cola + 8), (x_cola + 26, alto + 7)], fill=borde, width=7)
    d.rectangle((x_cola - 22, alto - 2, x_cola + 22, alto + 6), fill=(255, 255, 255, 250))
    for i, e in enumerate(lista):
        _pegar_emoji(img, e, (10 + margen + tam // 2 + i * (tam + sep), 10 + alto // 2), tam)
    return img


# ─── Gancho (frase grande de arriba, con emojis) ─────────────

def gancho(texto: str) -> Image.Image | None:
    if not texto.strip():
        return None
    piezas: list[str] = []
    posicion = 0
    for m in EMOJI.finditer(texto):
        piezas += texto[posicion:m.start()].upper().split()
        piezas.append(m.group(0))
        posicion = m.end()
    piezas += texto[posicion:].upper().split()

    for tamano in (96, 86, 76, 66, 58):
        fuente = _fuente(config.FUENTE_SUBTITULOS, tamano)
        espacio = fuente.getlength(" ")
        medida = lambda p: tamano * 1.15 if EMOJI.fullmatch(p) else fuente.getlength(p)
        lineas: list[list[str]] = [[]]
        ancho_linea = 0.0
        for p in piezas:
            w = medida(p)
            if lineas[-1] and ancho_linea + espacio + w > ANCHO_GANCHO:
                lineas.append([])
                ancho_linea = 0.0
            ancho_linea += (espacio if lineas[-1] else 0) + w
            lineas[-1].append(p)
        if len(lineas) <= 3:
            break

    alto_linea = int(tamano * 1.18)
    img = Image.new("RGBA", (1080, alto_linea * len(lineas) + 40), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for n, linea in enumerate(lineas):
        total = sum(medida(p) for p in linea) + espacio * (len(linea) - 1)
        x = (1080 - total) / 2
        y = 20 + n * alto_linea
        for p in linea:
            if EMOJI.fullmatch(p):
                _pegar_emoji(img, p, (int(x + tamano * 0.575), int(y + alto_linea / 2)), int(tamano * 1.1))
            else:
                d.text((x + 5, y + 7), p, font=fuente, fill=(0, 0, 0, 170))
                d.text((x, y), p, font=fuente, fill=(255, 225, 77, 255),
                       stroke_width=max(6, tamano // 11), stroke_fill=(0, 0, 0, 255))
            x += medida(p) + espacio
    return img


# ─── Humo que sube por el fondo ──────────────────────────────

def humo(semilla: int, alto: int = 1920) -> Image.Image:
    """Textura de humo que se repite sin cortes (dos veces de alto para poder deslizarla)."""
    azar = random.Random(semilla)
    capa = Image.new("L", (1080 // 4, alto // 4), 0)
    d = ImageDraw.Draw(capa)
    for _ in range(16):
        x, y = azar.randint(0, 270), azar.randint(0, alto // 4)
        rx, ry = azar.randint(25, 70), azar.randint(15, 45)
        brillo = azar.randint(40, 90)
        for dy in (-alto // 4, 0, alto // 4):   # copias arriba y abajo: así el corte no se nota
            d.ellipse((x - rx, y + dy - ry, x + rx, y + dy + ry), fill=brillo)
    capa = capa.filter(ImageFilter.GaussianBlur(14)).resize((1080, alto), Image.BICUBIC)
    img = Image.new("RGBA", (1080, alto * 2), (255, 255, 255, 0))
    alfa = Image.new("L", (1080, alto * 2), 0)
    alfa.paste(capa, (0, 0))
    alfa.paste(capa, (0, alto))
    img.putalpha(alfa.point(lambda v: int(v * 0.55)))
    return img


def barra_progreso(color: str = "#FFE14D") -> Image.Image:
    img = Image.new("RGBA", (1080, 14), (*_color(color), 255))
    ImageDraw.Draw(img).rectangle((0, 10, 1080, 14), fill=(0, 0, 0, 120))
    return img


# ─── Montaje de todas las capas ──────────────────────────────

def _intervalos(frases: list[Frase]) -> str:
    return "+".join(f"between(t,{f.inicio:.3f},{f.fin + 0.05:.3f})" for f in frases) or "0"


def crear_capas(guion: Guion, personajes: dict, duracion: float, trabajo: Path, semilla: int) -> list[Capa]:
    capas: list[Capa] = []

    def guardar(img: Image.Image, nombre: str) -> Path:
        ruta = trabajo / nombre
        img.save(ruta)
        return ruta

    # Humo de fondo subiendo despacio
    capas.append(Capa(guardar(humo(semilla), "humo.png"), x="0", y="-mod(t*45,1920)"))

    # Avatares: apagados cuando no hablan, grandes y botando cuando hablan
    for clave, p in personajes.items():
        frases = [f for f in guion.frases if f.personaje == clave]
        if not frases:
            continue
        cx = CENTRO_X.get(p.get("lado", "izquierda"), 290)
        activo, inactivo = tarjeta(p, True), tarjeta(p, False)
        centro_y = ARRIBA_TARJETA + TAM_TARJETA[1] // 2
        habla = _intervalos(frases)
        capas.append(Capa(guardar(inactivo, f"{clave}_inactivo.png"),
                          x=str(cx - inactivo.width // 2), y=str(centro_y - inactivo.height // 2),
                          activa=f"eq({habla},0)"))
        capas.append(Capa(guardar(activo, f"{clave}_activo.png"),
                          x=str(cx - activo.width // 2),
                          y=f"{ARRIBA_TARJETA}-16*abs(sin(t*9))", activa=habla))

    # Bocadillos con los emojis de cada frase, encima del que habla
    for n, frase in enumerate(guion.frases):
        if not frase.emojis:
            continue
        lado = personajes[frase.personaje].get("lado", "izquierda")
        img = bocadillo(frase.emojis, cola_izquierda=(lado == "izquierda"))
        x = min(max(20, CENTRO_X.get(lado, 290) - img.width // 2), 1060 - img.width)
        y0 = ARRIBA_TARJETA - img.height + 10
        capas.append(Capa(guardar(img, f"bocadillo_{n:02d}.png"), x=str(x),
                          y=f"{y0}+40*max(0,1-(t-{frase.inicio:.3f})/0.18)",
                          inicio=frase.inicio, fin=frase.fin + 0.15, fundido=0.15))

    # Gancho arriba (se ve desde el primer fotograma: sirve de miniatura)
    img = gancho(guion.gancho)
    if img is not None:
        capas.append(Capa(guardar(img, "gancho.png"), x="0", y=f"{ARRIBA_GANCHO}+6*sin(t*2.5)"))

    # Barra de progreso arriba del todo
    capas.append(Capa(guardar(barra_progreso(), "progreso.png"),
                      x=f"-w+w*t/{duracion:.3f}", y="0"))
    return capas
