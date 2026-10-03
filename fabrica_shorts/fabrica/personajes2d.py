"""Personajes 2D dibujados con código (estilo dibujo animado).

Cada personaje se dibuja en un lienzo de 560 × 1000 (busto: cabeza y torso) con
3 bocas (0 = cerrada, 1 = entreabierta, 2 = abierta) y ojos abiertos o cerrados.
Se dibuja al doble de tamaño y se reduce: así los bordes quedan suaves.
"""
from __future__ import annotations

from functools import lru_cache

from PIL import Image, ImageChops, ImageDraw

ANCHO, ALTO = 560, 1000
S = 2                                   # sobre-muestreo
CONTORNO = (34, 22, 26, 255)
GROSOR = 6


def _curva(p0, p1, p2, p3, n: int = 24) -> list[tuple[float, float]]:
    """Curva de Bézier cúbica → lista de puntos."""
    puntos = []
    for i in range(n + 1):
        t = i / n
        a, b, c, d = (1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t ** 2, t ** 3
        puntos.append((a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0],
                       a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1]))
    return puntos


class Lienzo:
    def __init__(self):
        self.img = Image.new("RGBA", (ANCHO * S, ALTO * S), (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.img)

    @staticmethod
    def _p(puntos):
        return [(x * S, y * S) for x, y in puntos]

    @staticmethod
    def _c(caja):
        return tuple(v * S for v in caja)

    def _pintar(self, relleno, dibujar):
        """Los colores semitransparentes se pintan en una capa aparte para que se mezclen bien."""
        if relleno is not None and len(relleno) == 4 and relleno[3] < 255:
            capa = Image.new("RGBA", self.img.size, (0, 0, 0, 0))
            dibujar(ImageDraw.Draw(capa))
            self.img.alpha_composite(capa)
        else:
            dibujar(self.d)

    def elipse(self, caja, relleno, borde=CONTORNO, grosor=GROSOR):
        self._pintar(relleno, lambda d: d.ellipse(self._c(caja), fill=relleno,
                                                  outline=borde if grosor else None, width=grosor * S))

    def rect(self, caja, radio, relleno, borde=CONTORNO, grosor=GROSOR):
        self._pintar(relleno, lambda d: d.rounded_rectangle(self._c(caja), radius=radio * S, fill=relleno,
                                                            outline=borde if grosor else None, width=grosor * S))

    def poligono(self, puntos, relleno, borde=CONTORNO, grosor=GROSOR):
        if relleno is not None:
            self._pintar(relleno, lambda d: d.polygon(self._p(puntos), fill=relleno))
        if grosor:
            self.linea(list(puntos) + [puntos[0], puntos[1]], borde, grosor)

    def linea(self, puntos, color=CONTORNO, grosor=GROSOR):
        def dibujar(d):
            d.line(self._p(puntos), fill=color, width=grosor * S, joint="curve")
            r = grosor * S / 2
            for x, y in (self._p(puntos)[0], self._p(puntos)[-1]):     # puntas redondeadas
                d.ellipse((x - r, y - r, x + r, y + r), fill=color)
        self._pintar(color, dibujar)

    def arco(self, caja, inicio, fin, color=CONTORNO, grosor=GROSOR):
        self.d.arc(self._c(caja), inicio, fin, fill=color, width=grosor * S)

    def dentro_de(self, forma, dibujar):
        """Dibuja algo recortado dentro de una forma (para sombras y brillos)."""
        mascara = Image.new("L", self.img.size, 0)
        forma(ImageDraw.Draw(mascara))
        capa = Image.new("RGBA", self.img.size, (0, 0, 0, 0))
        dibujar(ImageDraw.Draw(capa))
        capa.putalpha(ImageChops.multiply(capa.getchannel("A"), mascara))
        self.img.alpha_composite(capa)

    def terminar(self) -> Image.Image:
        return self.img.resize((ANCHO, ALTO), Image.LANCZOS)


def _ojo(l: Lienzo, cx, cy, mirar: int, cerrado: bool, parpado: float, piel, piel_sombra):
    """Ojo con pupila que mira hacia un lado (mirar = -1 izquierda, 1 derecha)."""
    ancho, alto = 34, 27
    caja = (cx - ancho, cy - alto, cx + ancho, cy + alto)
    if cerrado:
        l.arco((cx - ancho, cy - 14, cx + ancho, cy + 14), 15, 165, CONTORNO, 6)
        return
    l.elipse(caja, (255, 255, 255, 255), grosor=5)
    px = cx + 12 * mirar
    l.elipse((px - 15, cy - 15, px + 15, cy + 15), (52, 30, 20, 255), grosor=0)
    l.elipse((px - 8, cy - 8, px + 8, cy + 8), (12, 8, 8, 255), grosor=0)
    l.elipse((px - 9, cy - 11, px - 2, cy - 4), (255, 255, 255, 255), grosor=0)
    if parpado > 0:   # párpado de arriba (mirada seria o relajada)
        corte = cy - alto + 2 * alto * parpado
        l.dentro_de(lambda m: m.ellipse(Lienzo._c(caja), fill=255),
                    lambda c: c.rectangle(Lienzo._c((cx - ancho - 5, cy - alto - 5, cx + ancho + 5, corte)), fill=piel))
        l.linea([(cx - ancho + 2, corte), (cx + ancho - 2, corte)], CONTORNO, 5)
    else:
        l.elipse(caja, None, grosor=5)


def _boca(l: Lienzo, cx, cy, boca: int, ancho: int, sonrisa: int = 0):
    oscuro, lengua, dientes = (70, 18, 24, 255), (226, 98, 110, 255), (255, 255, 255, 255)
    if boca == 0:
        l.linea(_curva((cx - ancho, cy), (cx - ancho / 3, cy + 6 - sonrisa),
                       (cx + ancho / 3, cy + 6 - sonrisa * 2), (cx + ancho, cy - sonrisa * 2)), CONTORNO, 6)
        return
    alto = 18 if boca == 1 else 42
    caja = (cx - ancho * (0.75 if boca == 1 else 0.9), cy - alto / 2 + 4, cx + ancho * (0.75 if boca == 1 else 0.9), cy + alto / 2 + 8)
    l.elipse(caja, oscuro, grosor=5)
    forma = lambda m: m.ellipse(Lienzo._c(caja), fill=255)
    l.dentro_de(forma, lambda c: c.rectangle(Lienzo._c((caja[0], caja[1], caja[2], caja[1] + 9)), fill=dientes))
    if boca == 2:
        l.dentro_de(forma, lambda c: c.ellipse(Lienzo._c((cx - 22, caja[3] - 20, cx + 22, caja[3] + 12)), fill=lengua))
    l.elipse(caja, None, grosor=5)


# ─── DON FELLO ───────────────────────────────────────────────

def _don_fello(boca: int, ojos_cerrados: bool) -> Image.Image:
    l = Lienzo()
    piel, piel_sombra = (190, 126, 84, 255), (160, 100, 64, 255)
    camisa, camisa_sombra = (242, 230, 200, 255), (214, 198, 160, 255)
    canas, canas_sombra = (178, 176, 172, 255), (128, 126, 124, 255)

    # Torso con guayabera (barriga incluida)
    torso = (_curva((228, 460), (150, 470), (60, 500), (40, 610))
             + _curva((40, 610), (15, 760), (5, 900), (0, 1010))
             + [(560, 1010)]
             + _curva((560, 1010), (555, 900), (545, 760), (520, 610))
             + _curva((520, 610), (500, 500), (410, 470), (332, 460)))
    l.poligono(torso, camisa)
    l.dentro_de(lambda m: m.polygon(Lienzo._p(torso), fill=255),
                lambda c: c.ellipse(Lienzo._c((400, 520, 760, 1150)), fill=camisa_sombra))
    for x in (150, 182, 378, 410):                                   # pliegues de la guayabera
        l.linea([(x, 660), (x - 4 if x < 280 else x + 4, 1000)], camisa_sombra, 5)
    l.linea([(280, 560), (280, 1005)], camisa_sombra, 5)
    for y in (640, 740, 840, 940):                                   # botones
        l.elipse((272, y - 8, 288, y + 8), (250, 246, 236, 255), grosor=3)
    for x0 in (95, 355):                                              # bolsillos
        l.rect((x0, 700, x0 + 110, 800), 10, None, camisa_sombra, 5)
        l.linea([(x0, 725), (x0 + 110, 725)], camisa_sombra, 5)

    # Cuello y cuello de la camisa
    l.rect((222, 380, 338, 500), 30, piel)
    l.dentro_de(lambda m: m.rectangle(Lienzo._c((222, 380, 338, 500)), fill=255),
                lambda c: c.ellipse(Lienzo._c((200, 360, 360, 450)), fill=piel_sombra))
    l.poligono([(280, 560), (215, 465), (232, 455)], piel, grosor=0)
    l.poligono([(280, 565), (200, 455), (170, 500), (238, 560)], (250, 244, 228, 255), grosor=5)
    l.poligono([(280, 565), (360, 455), (390, 500), (322, 560)], (250, 244, 228, 255), grosor=5)

    # Orejas y cabeza
    for x0 in (112, 404):
        l.elipse((x0, 235, x0 + 44, 315), piel)
        l.elipse((x0 + 12, 255, x0 + 32, 295), piel_sombra, grosor=0)
    cabeza = (132, 88, 428, 438)
    l.elipse(cabeza, piel)
    l.dentro_de(lambda m: m.ellipse(Lienzo._c(cabeza), fill=255),
                lambda c: c.ellipse(Lienzo._c((290, 60, 520, 470)), fill=piel_sombra))
    l.elipse(cabeza, None)
    l.elipse((205, 112, 285, 150), (255, 255, 255, 90), grosor=0)   # brillo de la calva

    # Canas a los lados (mechones)
    for lado in (-1, 1):
        for dx, cy, rx, ry in ((132, 190, 30, 34), (146, 236, 30, 36), (136, 282, 24, 30)):
            cx = 280 + lado * dx
            l.elipse((cx - rx, cy - ry, cx + rx, cy + ry), canas, grosor=5)
        for dx, y0, y1 in ((128, 182, 206), (142, 228, 252)):
            l.linea([(280 + lado * dx, y0), (280 + lado * (dx + 8), y1)], canas_sombra, 4)

    # Cejas serias (más bajas por dentro: está regañando)
    l.poligono([(178, 200), (258, 222), (256, 238), (176, 220)], canas_sombra, grosor=4)
    l.poligono([(302, 222), (382, 200), (384, 220), (304, 238)], canas_sombra, grosor=4)

    # Ojos (miran a la derecha, hacia Yefri) y gafas
    _ojo(l, 222, 268, 1, ojos_cerrados, 0.28, piel, piel_sombra)
    _ojo(l, 338, 268, 1, ojos_cerrados, 0.28, piel, piel_sombra)
    marco = (60, 40, 32, 255)
    for x0 in (172, 288):
        l.rect((x0, 230, x0 + 100, 306), 22, (220, 240, 255, 45), marco, 6)
        l.linea([(x0 + 18, 290), (x0 + 40, 246)], (255, 255, 255, 120), 4)
    l.linea([(272, 260), (288, 260)], marco, 6)
    l.linea([(172, 258), (140, 252)], marco, 6)
    l.linea([(388, 258), (420, 252)], marco, 6)

    # Nariz, mejillas, boca y bigote
    l.elipse((246, 282, 320, 342), piel_sombra)
    l.elipse((262, 316, 276, 328), (110, 60, 40, 255), grosor=0)
    l.elipse((292, 316, 306, 328), (110, 60, 40, 255), grosor=0)
    l.elipse((170, 320, 220, 350), (230, 120, 110, 70), grosor=0)
    l.elipse((350, 320, 400, 350), (230, 120, 110, 70), grosor=0)
    _boca(l, 283, 382, boca, 34, sonrisa=-3)
    bigote = (_curva((280, 344), (245, 334), (205, 340), (196, 372))
              + _curva((196, 372), (225, 366), (250, 366), (280, 358))
              + _curva((280, 358), (310, 366), (335, 366), (368, 372))
              + _curva((368, 372), (358, 340), (318, 334), (284, 344)))
    l.poligono(bigote, canas, grosor=5)
    l.linea([(240, 352), (262, 348)], canas_sombra, 4)
    l.linea([(302, 348), (324, 352)], canas_sombra, 4)
    return l.terminar()


# ─── YEFRI ───────────────────────────────────────────────────

def _yefri(boca: int, ojos_cerrados: bool) -> Image.Image:
    l = Lienzo()
    piel, piel_sombra = (141, 88, 56, 255), (116, 70, 44, 255)
    sudadera, sudadera_sombra = (34, 170, 160, 255), (24, 128, 121, 255)
    pelo, gorra, gorra_sombra = (28, 20, 18, 255), (230, 57, 70, 255), (178, 34, 48, 255)

    # Torso con sudadera
    torso = (_curva((235, 470), (160, 480), (80, 505), (62, 610))
             + _curva((62, 610), (45, 760), (40, 900), (35, 1010))
             + [(525, 1010)]
             + _curva((525, 1010), (520, 900), (515, 760), (498, 610))
             + _curva((498, 610), (480, 505), (400, 480), (325, 470)))
    l.poligono(torso, sudadera)
    l.dentro_de(lambda m: m.polygon(Lienzo._p(torso), fill=255),
                lambda c: c.ellipse(Lienzo._c((-200, 520, 170, 1150)), fill=sudadera_sombra))
    l.rect((150, 820, 410, 960), 30, None, sudadera_sombra, 6)          # bolsillo canguro
    # Capucha alrededor del cuello
    capucha = _curva((170, 470), (170, 600), (390, 600), (390, 470))
    l.poligono(capucha + [(330, 470), (230, 470)], sudadera_sombra, grosor=6)
    # Cuello
    l.rect((230, 390, 330, 500), 30, piel)
    l.dentro_de(lambda m: m.rectangle(Lienzo._c((230, 390, 330, 500)), fill=255),
                lambda c: c.ellipse(Lienzo._c((210, 370, 350, 455)), fill=piel_sombra))
    # Cadena de oro y cordones
    l.linea(_curva((238, 470), (250, 545), (310, 545), (322, 470)), (242, 193, 78, 255), 7)
    for x0, x1 in ((246, 236), (314, 324)):
        l.linea([(x0, 560), (x1, 690)], (245, 245, 245, 255), 7)
        l.rect((x1 - 8, 688, x1 + 8, 716), 4, (210, 210, 210, 255), grosor=3)

    # Orejas (con arete) y cabeza
    for x0 in (124, 392):
        l.elipse((x0, 245, x0 + 44, 320), piel)
        l.elipse((x0 + 12, 262, x0 + 32, 300), piel_sombra, grosor=0)
    l.elipse((134, 312, 150, 328), (250, 214, 90, 255), grosor=3)
    cabeza = (145, 120, 415, 440)
    l.elipse(cabeza, piel)
    l.dentro_de(lambda m: m.ellipse(Lienzo._c(cabeza), fill=255),
                lambda c: c.ellipse(Lienzo._c((-60, 80, 200, 480)), fill=piel_sombra))
    l.elipse(cabeza, None)

    # Pelo rizo a los lados (patillas)
    for cx, cy in ((150, 200), (138, 232), (148, 262), (410, 200), (422, 232), (412, 262)):
        l.elipse((cx - 22, cy - 22, cx + 22, cy + 22), pelo, grosor=4)

    # Gorra roja hacia atrás
    cupula = _curva((132, 212), (120, 40), (440, 40), (428, 212))
    l.poligono(cupula, gorra, grosor=6)
    l.dentro_de(lambda m: m.polygon(Lienzo._p(cupula), fill=255),
                lambda c: c.ellipse(Lienzo._c((300, 20, 560, 260)), fill=gorra_sombra))
    l.poligono(cupula, None, grosor=6)
    l.linea([(280, 96), (280, 200)], gorra_sombra, 4)
    l.elipse((268, 80, 292, 96), gorra_sombra, grosor=4)                # botón de arriba
    # Apertura de atrás (se ve el pelo) y tira del cierre
    arco_pelo = _curva((236, 214), (236, 150), (324, 150), (324, 214))
    l.poligono(arco_pelo, pelo, grosor=5)
    for cx in (256, 280, 304):
        l.elipse((cx - 13, 168, cx + 13, 194), (52, 38, 34, 255), grosor=0)
    l.rect((236, 192, 324, 206), 5, (240, 240, 240, 255), grosor=4)
    l.rect((126, 200, 434, 226), 12, gorra_sombra, grosor=6)            # banda de la gorra

    # Cejas relajadas
    l.linea(_curva((188, 238), (205, 228), (232, 228), (250, 236)), pelo, 11)
    l.linea(_curva((310, 236), (328, 228), (355, 228), (372, 238)), pelo, 11)

    # Ojos medio cerrados (tranquilo) mirando a la izquierda, hacia Don Fello
    _ojo(l, 220, 280, -1, ojos_cerrados, 0.42, piel, piel_sombra)
    _ojo(l, 340, 280, -1, ojos_cerrados, 0.42, piel, piel_sombra)

    # Nariz, boca con sonrisa de lado y una nubecita de vaper
    l.arco((262, 300, 300, 346), 300, 120 + 360, piel_sombra, 6)
    l.elipse((265, 330, 277, 340), (90, 52, 34, 255), grosor=0)
    l.elipse((285, 330, 297, 340), (90, 52, 34, 255), grosor=0)
    _boca(l, 280, 388, boca, 32, sonrisa=4)

    # Mano con el vaper (abajo a la izquierda): la manga sube desde abajo hasta la mano
    manga = _curva((40, 1010), (50, 920), (60, 840), (78, 790)) + _curva((160, 785), (170, 850), (175, 930), (180, 1010))
    l.poligono(manga, sudadera, grosor=6)
    l.dentro_de(lambda m: m.polygon(Lienzo._p(manga), fill=255),
                lambda c: c.rectangle(Lienzo._c((150, 760, 200, 1010)), fill=sudadera_sombra))
    l.poligono(manga, None, grosor=6)
    l.rect((70, 780, 172, 812), 12, sudadera_sombra, grosor=6)                          # puño
    l.rect((104, 640, 150, 790), 14, (60, 63, 74, 255), grosor=6)                       # vaper
    l.rect((110, 700, 144, 716), 6, (255, 79, 216, 255), grosor=0)                      # luz
    l.rect((114, 616, 140, 646), 8, (30, 30, 36, 255), grosor=5)                        # boquilla
    for k, y in enumerate((730, 758, 786)):                                             # dedos
        l.elipse((86 - k * 2, y - 16, 130 - k * 2, y + 16), piel, grosor=5)
    l.elipse((132, 742, 168, 776), piel, grosor=5)                                      # pulgar
    for cx, cy, r in ((120, 590, 22), (140, 560, 28), (112, 530, 20)):                  # humo
        l.elipse((cx - r, cy - r, cx + r, cy + r), (235, 235, 245, 200), grosor=0)
    return l.terminar()


DIBUJOS = {"fello": _don_fello, "yefri": _yefri}


@lru_cache(maxsize=None)
def dibujar(nombre: str, boca: int, ojos_cerrados: bool) -> Image.Image:
    return DIBUJOS[nombre](boca, ojos_cerrados)
