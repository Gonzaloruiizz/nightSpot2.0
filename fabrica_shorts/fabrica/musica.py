"""Compone un beat de DEMBOW original (sin copyright) con matemáticas puras.

Lo que hace que suene a dembow (16 semicorcheas por compás, ~122 BPM):
    bombo 808:  X . . . X . . . X . . . X . . .   (cada tiempo)
    caja:       . . . X . . X . . . . X . . X .   ← el "pum-PÁ-pum-PÁ" del dembow (tresillo 3+3+2)
    bajo 808:   X . . X . . X . X . . X . . X .   (sigue el tresillo)
    hi-hats:    x x X x x x X x x x X x x x X x   (semicorcheas con acento a contratiempo)
    cencerro:   . . X . . . . . . . X . . . . .
    timbales:   repiques al final de cada 4 compases; redoble de caja cada 8
Encima, un riff corto de sintetizador que cambia en cada vídeo.
"""
from __future__ import annotations

import random
import wave
from pathlib import Path

import numpy as np

FRECUENCIA = 48000

# Acordes (La menor): raíz del bajo y notas del riff en Hz
PROGRESION = [
    (55.00, [440.00, 523.25, 659.25, 880.00]),    # Am
    (43.65, [349.23, 440.00, 523.25, 698.46]),    # F
    (65.41, [392.00, 523.25, 659.25, 783.99]),    # C
    (49.00, [392.00, 493.88, 587.33, 783.99]),    # G
]
BOMBO = [0, 4, 8, 12]
CAJA = [3, 6, 11, 14]
BAJO = [(0, 3), (3, 3), (6, 2), (8, 3), (11, 3), (14, 2)]   # (paso, duración en pasos)
CENCERRO = [2, 10]
RIFFS = [
    [0, 3, 6, 10, 12],
    [0, 3, 6, 8, 11, 14],
    [2, 3, 6, 10, 11, 14],
    [0, 2, 3, 6, 8, 10, 14],
]


def _t(segundos: float) -> np.ndarray:
    return np.arange(int(segundos * FRECUENCIA)) / FRECUENCIA


def _agudos(señal: np.ndarray, veces: int = 1) -> np.ndarray:
    """Filtro paso alto sencillo (deja el 'chis' del ruido)."""
    for _ in range(veces):
        señal = señal - np.concatenate(([0.0], señal[:-1]))
    return señal


def _suavizar(señal: np.ndarray, ancho: int) -> np.ndarray:
    return np.convolve(señal, np.ones(ancho) / ancho, mode="same")


def _normalizar(señal: np.ndarray) -> np.ndarray:
    return señal / max(1e-9, np.max(np.abs(señal)))


# ─── Instrumentos ───────────────────────────────────────────

def _bombo(azar) -> np.ndarray:
    t = _t(0.5)
    frecuencia = 50 + 120 * np.exp(-t * 30)               # cae de tono: el "pum"
    cuerpo = np.sin(2 * np.pi * np.cumsum(frecuencia) / FRECUENCIA) * np.exp(-t * 4.5)
    golpe = _agudos(azar.uniform(-1, 1, len(t))) * np.exp(-t * 900)
    return _normalizar(np.tanh(2.4 * cuerpo) + 0.35 * golpe)


def _caja(azar) -> np.ndarray:
    t = _t(0.22)
    ruido = _suavizar(_agudos(azar.uniform(-1, 1, len(t))), 3)
    tono = 0.7 * np.sin(2 * np.pi * 200 * t) * np.exp(-t * 28) + 0.35 * np.sin(2 * np.pi * 340 * t) * np.exp(-t * 40)
    palmada = sum(np.exp(-(t - d) * 130) * (t >= d) for d in (0.0, 0.009, 0.018))
    return _normalizar(0.8 * ruido * np.exp(-t * 20) + tono + 0.6 * ruido * palmada)


def _hat(azar, abierto: bool = False) -> np.ndarray:
    t = _t(0.25 if abierto else 0.045)
    return _normalizar(_agudos(azar.uniform(-1, 1, len(t)), 2) * np.exp(-t * (14 if abierto else 110)))


def _cencerro() -> np.ndarray:
    t = _t(0.2)
    onda = np.sign(np.sin(2 * np.pi * 560 * t)) + 0.8 * np.sign(np.sin(2 * np.pi * 845 * t))
    return _normalizar(_agudos(onda) * np.exp(-t * 18))


def _timbal(azar, frecuencia: float) -> np.ndarray:
    t = _t(0.3)
    f = frecuencia * (1 + 0.25 * np.exp(-t * 40))
    cuerpo = np.sin(2 * np.pi * np.cumsum(f) / FRECUENCIA) + 0.3 * np.sin(2 * np.pi * 2.3 * frecuencia * t)
    golpe = _agudos(azar.uniform(-1, 1, len(t))) * np.exp(-t * 300)
    return _normalizar(cuerpo * np.exp(-t * 11) + 0.4 * golpe)


def _bajo(frecuencia: float, segundos: float) -> np.ndarray:
    t = _t(segundos)
    f = frecuencia * (1 + 0.06 * np.exp(-t * 35))         # pequeño "deslizado" típico del 808
    fase = 2 * np.pi * np.cumsum(f) / FRECUENCIA
    s = np.sin(fase) + 0.3 * np.sin(2 * fase)
    s = np.tanh(2.0 * s) * np.exp(-t * 1.5)               # saturación: se oye hasta en el móvil
    s[:240] *= np.linspace(0, 1, 240)
    s[-480:] *= np.linspace(1, 0, 480)
    return s


def _sinte(frecuencia: float) -> np.ndarray:
    t = _t(0.28)
    sierra = sum(2 * (t * f - np.floor(t * f + 0.5)) for f in (frecuencia, frecuencia * 1.006))
    s = _suavizar(sierra, 6) * np.exp(-t * 8)
    s[:240] *= np.linspace(0, 1, 240)
    return _normalizar(s)


# ─── Composición ────────────────────────────────────────────

def _poner(pista: np.ndarray, sonido: np.ndarray, segundo: float, volumen: float, pan: float = 0.0) -> None:
    inicio = int(segundo * FRECUENCIA)
    if inicio >= len(pista):
        return
    trozo = sonido[: len(pista) - inicio] * volumen
    pista[inicio:inicio + len(trozo), 0] += trozo * np.sqrt((1 - pan) / 2)
    pista[inicio:inicio + len(trozo), 1] += trozo * np.sqrt((1 + pan) / 2)


def componer_dembow(duracion: float, destino: Path, semilla: int, bpm: float = 122) -> None:
    """Crea un WAV estéreo con un beat de dembow de la duración pedida."""
    elegir = random.Random(semilla)
    azar = np.random.default_rng(semilla)
    paso = 60 / bpm / 4                                    # una semicorchea
    compas = paso * 16
    n_compases = int(duracion / compas) + 2
    pista = np.zeros((int(n_compases * compas * FRECUENCIA), 2))

    bombo, caja, cencerro = _bombo(azar), _caja(azar), _cencerro()
    hats = [_hat(azar) for _ in range(4)]
    hat_abierto = _hat(azar, abierto=True)
    timbal_alto, timbal_bajo = _timbal(azar, 260), _timbal(azar, 175)
    # Riff de 2 compases (pegadizo), distinto en cada vídeo
    riff = [(p, elegir.randrange(4)) for p in elegir.choice(RIFFS)]
    riff += [(p + 16, elegir.randrange(4)) for p in elegir.choice(RIFFS)]

    for c in range(n_compases):
        base = c * compas
        raiz, notas = PROGRESION[(c // 2) % len(PROGRESION)]   # cada acorde dura 2 compases
        fin_de_frase = c % 4 == 3
        for p in BOMBO:
            _poner(pista, bombo, base + p * paso, 0.95)
        for p in CAJA:
            _poner(pista, caja, base + p * paso, 0.8)
        for p in range(16):                                     # hi-hats en semicorcheas
            acento = 0.85 if p % 4 == 2 else 0.5 if p % 4 == 0 else 0.32
            _poner(pista, hats[p % 4], base + p * paso, 0.22 * acento, pan=-0.3)
        if c % 2 == 1:
            _poner(pista, hat_abierto, base + 10 * paso, 0.12, pan=-0.3)
        for p in CENCERRO:
            _poner(pista, cencerro, base + p * paso, 0.12, pan=0.35)
        _poner(pista, timbal_alto, base + 15 * paso, 0.18, pan=0.2)
        if fin_de_frase:                                        # repique de timbales
            for k, p in enumerate((12, 13, 14, 15)):
                _poner(pista, timbal_alto if k % 2 else timbal_bajo, base + p * paso, 0.18 + 0.05 * k, pan=0.2)
        if c % 8 == 7:                                          # redoble de caja
            for k, p in enumerate(range(8, 16)):
                _poner(pista, caja, base + p * paso, 0.25 + 0.06 * k)
        for p, largo in BAJO:
            _poner(pista, _bajo(raiz, largo * paso), base + p * paso, 0.5)
        if c >= 1 and c % 8 not in (6, 7):                     # el riff entra en el compás 2
            for p, nota in riff:
                if (c % 2) * 16 <= p < (c % 2 + 1) * 16:
                    _poner(pista, _sinte(notas[nota]), base + (p % 16) * paso, 0.16, pan=0.15)

    pista = pista[: int((duracion + 0.5) * FRECUENCIA)]
    pista /= max(1e-9, np.max(np.abs(pista))) / 0.9
    datos = (pista * 32767).astype("<i2").tobytes()
    with wave.open(str(destino), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(FRECUENCIA)
        w.writeframes(datos)
