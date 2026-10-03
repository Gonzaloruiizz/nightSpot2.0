"""Dibuja con Pillow las imágenes que van encima del vídeo y decide dónde y cuándo salen."""
from __future__ import annotations

import random
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import config, emojis, personajes2d
from .guion import EMOJI, Frase, Guion
from .render import Capa

# ─── Posiciones en pantalla (vídeo de 1080 × 1920) ───────────
#   gancho (arriba) → subtítulos → bocadillo → personajes 2D (abajo)
ARRIBA_GANCHO = 175           # debajo de los menús de TikTok / YouTube
ANCHO_GANCHO = 960
ARRIBA_PERSONAJES = 920
IZQUIERDA_PERSONAJE = {"izquierda": 0, "derecha": 520}
CABEZA = (280, 90)            # centro de la cabeza (x) y su parte de arriba (y) dentro del dibujo
ALTO_NOMBRE = 1440            # etiqueta con el nombre, a la altura del pecho
FPS_BOCA = 15                 # cuántas veces por segundo se decide la boca


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


# ─── Personajes 2D animados ──────────────────────────────────

def _volumen_por_paso(pista_voz: Path, duracion: float) -> np.ndarray:
    """Volumen de la voz en cada paso de 1/FPS_BOCA segundos."""
    with wave.open(str(pista_voz), "rb") as w:
        muestras = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768
        frecuencia = w.getframerate()
    por_paso = frecuencia // FPS_BOCA
    pasos = int(np.ceil(duracion * FPS_BOCA))
    muestras = np.pad(muestras, (0, max(0, pasos * por_paso - len(muestras))))[: pasos * por_paso]
    return np.sqrt((muestras.reshape(pasos, por_paso) ** 2).mean(axis=1))


def animacion(clave: str, personaje: dict, frases: list[Frase], volumen: np.ndarray,
              trabajo: Path, semilla: int) -> Path:
    """Crea las imágenes del personaje y la lista (ffconcat) que dice cuál toca en cada momento.

    Boca: según el volumen de su voz (cerrada / entreabierta / abierta). Ojos: parpadeo cada pocos segundos.
    """
    dibujo = personaje.get("dibujo", clave.lower())
    for boca in (0, 1, 2):
        for ojos in (0, 1):
            personajes2d.dibujar(dibujo, boca, bool(ojos)).save(trabajo / f"{clave}_b{boca}_o{ojos}.png")

    pasos = len(volumen)
    bocas = np.zeros(pasos, dtype=int)
    for frase in frases:
        a, b = int(frase.inicio * FPS_BOCA), min(pasos, int(np.ceil(frase.fin * FPS_BOCA)))
        tramo = volumen[a:b]
        if len(tramo) == 0:
            continue
        nivel = tramo / max(1e-6, np.percentile(tramo, 90))
        bocas[a:b] = np.where(nivel > 0.55, 2, np.where(nivel > 0.18, 1, 0))

    azar = random.Random(semilla + len(clave))
    ojos = np.zeros(pasos, dtype=int)
    t = azar.uniform(1.0, 3.0)
    while t * FPS_BOCA < pasos:
        i = int(t * FPS_BOCA)
        ojos[i:i + 2] = 1                       # ojos cerrados ~0,13 s
        t += azar.uniform(2.5, 5.5)

    lineas = ["ffconcat version 1.0"]
    estado, inicio = (bocas[0], ojos[0]), 0
    for i in range(1, pasos + 1):
        nuevo = (bocas[i], ojos[i]) if i < pasos else None
        if nuevo != estado:
            lineas += [f"file '{clave}_b{estado[0]}_o{estado[1]}.png'", f"duration {(i - inicio) / FPS_BOCA:.4f}"]
            estado, inicio = nuevo, i
    lineas.append(f"file '{clave}_b0_o0.png'")
    lista = trabajo / f"{clave}_animacion.txt"
    lista.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    return lista


def resplandor(color: str) -> Image.Image:
    """Luz de color detrás del que habla."""
    img = Image.new("RGBA", (820, 820), (0, 0, 0, 0))
    ImageDraw.Draw(img).ellipse((170, 170, 650, 650), fill=(*_color(color), 150))
    return img.filter(ImageFilter.GaussianBlur(60))


def etiqueta_nombre(personaje: dict) -> Image.Image:
    fuente = _fuente(config.FUENTE_NOMBRES, 44)
    nombre = personaje.get("nombre", "").upper()
    color = _color(personaje.get("color", "#FFFFFF"))
    ancho = int(fuente.getlength(nombre)) + 56
    img = Image.new("RGBA", (ancho + 8, 76), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((4, 4, ancho + 4, 72), radius=34, fill=(15, 15, 20, 235), outline=(*color, 255), width=5)
    d.text((ancho / 2 + 4, 38), nombre, font=fuente, fill=(255, 255, 255, 255), anchor="mm")
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
        if len(lineas) <= 2:      # máximo 2 líneas para no pisar los bocadillos
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


def crear_capas(guion: Guion, personajes: dict, duracion: float, pista_voz: Path,
                trabajo: Path, semilla: int) -> list[Capa]:
    capas: list[Capa] = []

    def guardar(img: Image.Image, nombre: str) -> Path:
        ruta = trabajo / nombre
        img.save(ruta)
        return ruta

    # Humo de fondo subiendo despacio
    capas.append(Capa(guardar(humo(semilla), "humo.png"), x="0", y="-mod(t*45,1920)"))

    # Personajes 2D: luz detrás del que habla, boca sincronizada y un pequeño bote al hablar
    volumen = _volumen_por_paso(pista_voz, duracion)
    for n, (clave, p) in enumerate(personajes.items()):
        frases = [f for f in guion.frases if f.personaje == clave]
        if not frases:
            continue
        izquierda = IZQUIERDA_PERSONAJE.get(p.get("lado", "izquierda"), 0)
        habla = _intervalos(frases)
        luz = resplandor(p.get("color", "#FFFFFF"))
        capas.append(Capa(guardar(luz, f"{clave}_luz.png"), x=str(izquierda + CABEZA[0] - luz.width // 2),
                          y=str(ARRIBA_PERSONAJES + 260 - luz.height // 2), activa=habla))
        lista = animacion(clave, p, frases, volumen, trabajo, semilla)
        capas.append(Capa(lista, x=str(izquierda),
                          y=f"{ARRIBA_PERSONAJES}+4*sin(t*2+{n * 1.7:.1f})-9*abs(sin(t*7))*({habla})",
                          secuencia=True))
        nombre = etiqueta_nombre(p)
        capas.append(Capa(guardar(nombre, f"{clave}_nombre.png"),
                          x=str(izquierda + CABEZA[0] - nombre.width // 2), y=str(ALTO_NOMBRE)))

    # Bocadillos con los emojis de cada frase, encima de la cabeza del que habla
    for n, frase in enumerate(guion.frases):
        if not frase.emojis:
            continue
        lado = personajes[frase.personaje].get("lado", "izquierda")
        centro = IZQUIERDA_PERSONAJE.get(lado, 0) + CABEZA[0]
        img = bocadillo(frase.emojis, cola_izquierda=(lado == "izquierda"))
        x = min(max(20, centro - img.width // 2), 1060 - img.width)
        y0 = ARRIBA_PERSONAJES + CABEZA[1] - img.height + 4
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
