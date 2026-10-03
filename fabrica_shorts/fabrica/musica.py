"""Compone un beat de dembow ORIGINAL (sin copyright) con matemáticas puras.

Patrón clásico del dembow en 16 semicorcheas por compás:
    bombo:  x . . . x . . . x . . . x . . .   (en cada tiempo)
    caja:   . . . x . . x . . . . x . . x .   (el "tresillo" 3+3+2 del dembow)
    hi-hat: x . x . x . x . x . x . x . x .   (+ redobles al final de cada 4 compases)
Encima van un bajo 808 y una melodía corta que cambia en cada vídeo.
"""
from __future__ import annotations

import random
import wave
from pathlib import Path

import numpy as np

FRECUENCIA = 48000

# Acordes (La menor): raíz del bajo y notas de la melodía en Hz
PROGRESION = [
    (55.00, [440.00, 523.25, 659.25]),    # Am
    (43.65, [349.23, 440.00, 523.25]),    # F
    (65.41, [523.25, 659.25, 783.99]),    # C
    (49.00, [392.00, 493.88, 587.33]),    # G
]
BOMBO = [0, 4, 8, 12]
CAJA = [3, 6, 11, 14]
BAJO = [(0, 5), (6, 2), (8, 5), (14, 2)]     # (paso, duración en pasos)


def _t(segundos: float) -> np.ndarray:
    return np.arange(int(segundos * FRECUENCIA)) / FRECUENCIA


def _bombo() -> np.ndarray:
    t = _t(0.38)
    frecuencia = 48 + 110 * np.exp(-t * 28)              # cae de tono: el "pum"
    s = np.sin(2 * np.pi * np.cumsum(frecuencia) / FRECUENCIA) * np.exp(-t * 7.5)
    s[:200] += np.linspace(0.5, 0, 200)                  # golpe inicial
    return s


def _ruido_agudo(azar: np.random.Generator, n: int) -> np.ndarray:
    r = azar.uniform(-1, 1, n)
    return r - 0.9 * np.concatenate(([0.0], r[:-1]))     # filtro paso alto sencillo


def _caja(azar: np.random.Generator) -> np.ndarray:
    t = _t(0.2)
    return 0.6 * _ruido_agudo(azar, len(t)) * np.exp(-t * 24) + 0.45 * np.sin(2 * np.pi * 185 * t) * np.exp(-t * 32)


def _hat(azar: np.random.Generator) -> np.ndarray:
    t = _t(0.05)
    return _ruido_agudo(azar, len(t)) * np.exp(-t * 75)


def _bajo(frecuencia: float, segundos: float) -> np.ndarray:
    t = _t(segundos)
    s = np.sin(2 * np.pi * frecuencia * t) + 0.3 * np.sin(2 * np.pi * 2 * frecuencia * t)
    s = np.tanh(1.8 * s) * np.exp(-t * 1.8)              # saturación: se oye hasta en el móvil
    s[:240] *= np.linspace(0, 1, 240)
    s[-480:] *= np.linspace(1, 0, 480)
    return s


def _pluck(frecuencia: float) -> np.ndarray:
    t = _t(0.35)
    fase = t * frecuencia
    triangulo = 2 * np.abs(2 * (fase - np.floor(fase + 0.5))) - 1
    s = (triangulo + 0.3 * np.sin(2 * np.pi * 2 * frecuencia * t)) * np.exp(-t * 9)
    s[:96] *= np.linspace(0, 1, 96)
    return s


def _poner(pista: np.ndarray, sonido: np.ndarray, segundo: float, volumen: float, pan: float = 0.0) -> None:
    inicio = int(segundo * FRECUENCIA)
    if inicio >= len(pista):
        return
    trozo = sonido[: len(pista) - inicio] * volumen
    pista[inicio:inicio + len(trozo), 0] += trozo * np.sqrt((1 - pan) / 2)
    pista[inicio:inicio + len(trozo), 1] += trozo * np.sqrt((1 + pan) / 2)


def componer_dembow(duracion: float, destino: Path, semilla: int, bpm: float = 120) -> None:
    """Crea un WAV estéreo con un beat de dembow de la duración pedida."""
    azar_py = random.Random(semilla)
    azar = np.random.default_rng(semilla)
    paso = 60 / bpm / 4                                  # una semicorchea
    compas = paso * 16
    n_compases = int(duracion / compas) + 2
    pista = np.zeros((int(n_compases * compas * FRECUENCIA), 2))

    bombo, caja = _bombo(), _caja(azar)
    hats = [_hat(azar) for _ in range(4)]
    # Melodía de 2 compases que se repite (pegadiza), distinta en cada vídeo
    pasos_melodia = sorted(azar_py.sample([0, 2, 3, 5, 6, 8, 10, 11, 12, 14], 6))
    motivo = [(azar_py.choice(pasos_melodia), azar_py.randrange(3)) for _ in range(5)]
    motivo += [(p + 16, n) for p, n in motivo[:4]]

    for c in range(n_compases):
        base = c * compas
        raiz, notas = PROGRESION[c % len(PROGRESION)]
        for p in BOMBO:
            _poner(pista, bombo, base + p * paso, 1.0)
        for p in CAJA:
            _poner(pista, caja, base + p * paso, 0.55, pan=0.1)
        redoble = c % 4 == 3
        for p in range(16):
            if p % 2 == 0 or (redoble and p >= 12):
                acento = 0.32 if p % 4 == 2 else 0.2
                _poner(pista, hats[p % 4], base + p * paso, acento, pan=-0.35)
        for p, largo in BAJO:
            _poner(pista, _bajo(raiz * (2 if p == 14 else 1), largo * paso), base + p * paso, 0.5)
        if c >= 1:                                       # la melodía entra en el compás 2
            for p, nota in motivo:
                if (c % 2) * 16 <= p < (c % 2 + 1) * 16:
                    _poner(pista, _pluck(notas[nota]), base + (p % 16) * paso, 0.16, pan=0.3)

    pista = pista[: int((duracion + 0.5) * FRECUENCIA)]
    pista /= max(1e-9, np.max(np.abs(pista))) / 0.9
    datos = (pista * 32767).astype("<i2").tobytes()
    with wave.open(str(destino), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(FRECUENCIA)
        w.writeframes(datos)
