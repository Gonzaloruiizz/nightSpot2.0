"""Soundtrack for the photoreal v3 cut (39 s). Same synthesis palette as the stylised version."""
import os, sys, wave
import numpy as np
from scipy.signal import butter, sosfilt, fftconvolve

SR = 48000
# cut points (seconds): establish, frozen, needle, blood, dna, mutation, title
CUTS = dict(frozen=6.0, needle=12.0, blood=16.5, dna=22.5, mutation=28.0, title=35.0, end=39.0)
DUR = CUTS['end']
N = int(DUR * SR)
t = np.arange(N) / SR
rng = np.random.default_rng(11)
L = np.zeros(N); R = np.zeros(N)


def sm(a, b, x):
    u = np.clip((x - a) / (b - a), 0, 1); return u * u * (3 - 2 * u)


def env(a, b, c, d):
    return sm(a, b, t) * (1 - sm(c, d, t))


def filt(x, kind, f, order=2):
    if kind == 'bp':
        sos = butter(order, [f[0] / (SR / 2), f[1] / (SR / 2)], btype='band', output='sos')
    else:
        sos = butter(order, f / (SR / 2), btype=kind, output='sos')
    return sosfilt(sos, x)


def add(sig, start=0.0, gain=1.0, pan=0.0):
    i = int(start * SR)
    if i >= N: return
    s = sig[: N - i] * gain
    L[i:i + len(s)] += s * np.sqrt(0.5 * (1 - pan)); R[i:i + len(s)] += s * np.sqrt(0.5 * (1 + pan))


def noise(n):
    return rng.standard_normal(n)


def thump(f0, f1, dur, amp):
    n = int(dur * SR); tt = np.arange(n) / SR
    f = f1 + (f0 - f1) * np.exp(-tt * 18)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tt * 9) * (1 - np.exp(-tt * 400)) * amp


def riser(end, dur, gain, top=6000):
    n = int(dur * SR); tt = np.arange(n) / SR
    x = noise(n); out = np.zeros(n); seg = 2048
    for i in range(0, n, seg):
        fc = 200 + (top - 200) * (i / n) ** 2
        out[i:i + seg] = filt(x[i:i + seg], 'bp', (fc * 0.7, min(fc * 1.4, 20000)))
    out *= (tt / dur) ** 2
    add(out * 0.6 + np.sin(2 * np.pi * np.cumsum(80 + 900 * (tt / dur) ** 3) / SR) * (tt / dur) ** 3 * 0.3, end - dur, gain)


def impact(at, gain, sub=45):
    n = int(3.0 * SR); tt = np.arange(n) / SR
    add(thump(sub * 2.2, sub, 3.0, 1.2) + filt(noise(n), 'lp', 3000) * np.exp(-tt * 6) * 0.6, at, gain)


C = CUTS
lab = env(0, 1.5, C['blood'] - 0.1, C['blood']) + env(C['mutation'] - 0.05, C['mutation'] + 0.2, C['title'] - 0.05, C['title'])
drone = sum(a * np.sin(2 * np.pi * f * t + rng.random() * 6) for f, a in [(55, 0.5), (55.4, 0.35), (82.4, 0.25), (110.3, 0.12)])
saw = filt(sum(((t * f) % 1 - 0.5) for f in (55.2, 54.8, 110.1)), 'lp', 420) * (0.5 + 0.5 * np.sin(2 * np.pi * 0.07 * t))
add((drone * 0.22 + saw * 0.12) * lab)
add(filt(noise(N), 'bp', (2500, 7000)) * 0.045 * lab, pan=-0.2)
add(filt(noise(N), 'lp', 400) * 0.08 * lab, pan=0.3)
# ice creaks in the close-up of the frozen face
for k in range(26):
    at = C['frozen'] + rng.random() * (C['needle'] - C['frozen'] - 0.2)
    n = int(0.06 * SR); tt = np.arange(n) / SR
    add(filt(noise(n), 'bp', (1800, 9000)) * np.exp(-tt * 70), at, 0.05, rng.uniform(-0.5, 0.5))
for k in np.arange(1.0, C['needle'], 2.5):
    n = int(0.18 * SR); tt = np.arange(n) / SR
    add(np.sin(2 * np.pi * 660 * tt) * np.exp(-tt * 8) * (1 - np.exp(-tt * 300)), k, 0.04, 0.4)
# needle: servo, contact, hydraulic push
n = int(0.9 * SR); tt = np.arange(n) / SR
f = 200 - 50 * sm(0, 0.9, tt)
add(filt((np.cumsum(f) / SR) % 1 - 0.5, 'bp', (120, 2400)) * sm(0, 0.1, tt) * (1 - sm(0.7, 0.9, tt)), C['needle'], 0.1, 0.3)
add(thump(220, 90, 0.25, 1.0), C['needle'] + 0.8, 0.35, 0.2)
n = int(0.08 * SR); tt = np.arange(n) / SR
add(filt(noise(n), 'hp', 2000) * np.exp(-tt * 80), C['needle'] + 0.8, 0.5, 0.2)
n = int(3.4 * SR); tt = np.arange(n) / SR
add(filt(noise(n), 'bp', (300, 1800)) * sm(0, 0.3, tt) * (1 - sm(3.0, 3.4, tt)) * 0.25, C['needle'] + 0.9, 1.0, 0.1)
riser(C['blood'], 1.8, 0.5); impact(C['blood'], 0.6)
# heartbeat restarts inside the artery
beats = list(np.arange(C['blood'] + 0.4, C['dna'], 1.9)) + list(np.arange(C['dna'] + 0.2, C['mutation'], 1.5))
bt = C['mutation'] + 0.3; ibi = 1.1
while bt < C['title'] - 0.3:
    beats.append(bt); bt += ibi; ibi = max(0.38, ibi * 0.9)
lub = thump(70, 38, 0.45, 1.0); dub = thump(85, 45, 0.35, 0.7)
for b in beats:
    lp = 220 if b < C['mutation'] else 600
    g = 1.0 if b < C['dna'] else 0.6
    add(filt(lub, 'lp', lp), b, g * 0.9); add(filt(dub, 'lp', lp), b + 0.16, g * 0.6)
    if b > C['mutation']:
        n = int(0.11 * SR); tt = np.arange(n) / SR
        add(np.sin(2 * np.pi * 988 * tt) * (1 - np.exp(-tt * 400)) * np.exp(-tt * 18), b + 0.04, 0.07, 0.5)
# bloodstream
bm = env(C['blood'] - 0.1, C['blood'] + 0.6, C['dna'] - 0.2, C['dna'])
under = filt(np.cumsum(noise(N)), 'hp', 20); under = filt(under / np.abs(under).max(), 'lp', 260)
add((under * 0.9 + filt(noise(N), 'bp', (80, 500)) * 0.12) * bm * 0.7)
# DNA shimmer + editing ticks
cm = env(C['dna'] - 0.1, C['dna'] + 0.5, C['mutation'] - 0.2, C['mutation'])
add(filt(sum(np.sin(2 * np.pi * f * t) for f in (110, 164.8, 220, 277.2, 329.6)), 'lp', 1200) * 0.05 * cm)
scale = [880, 987.8, 1174.7, 1318.5, 1568, 1760, 1975.5, 2349.3]
at = C['dna'] + 0.1
while at < C['mutation'] - 0.3:
    f = scale[rng.integers(len(scale))]
    n = int(1.2 * SR); tt = np.arange(n) / SR
    add((np.sin(2 * np.pi * f * tt) + 0.3 * np.sin(2 * np.pi * f * 2.76 * tt) * np.exp(-tt * 8)) * np.exp(-tt * 3.5) * (1 - np.exp(-tt * 500)), at, 0.06, rng.uniform(-0.7, 0.7))
    at += 0.17
at = C['dna'] + 0.5
while at < C['mutation'] - 0.3:
    n = int(0.03 * SR); tt = np.arange(n) / SR
    add(filt(noise(n), 'hp', 4000) * np.exp(-tt * 200), at, 0.12, rng.uniform(-0.4, 0.4)); at += 0.07
riser(C['mutation'], 1.2, 0.4); impact(C['mutation'], 0.6, 40)
# mutation tension
mm = env(C['mutation'], C['mutation'] + 0.8, C['title'] - 0.1, C['title'])
cl = filt(sum(((np.cumsum(f * (1 + 0.004 * np.sin(2 * np.pi * 0.3 * t + f))) / SR) % 1 - 0.5) for f in (110, 116.5, 123.5, 146.8, 155.6, 220, 233.1)), 'lp', 900)
add(cl * 0.05 * mm * (0.3 + 0.7 * sm(C['mutation'], C['title'], t)))
for k in range(80):
    at = C['mutation'] + 0.3 + rng.random() * 5.5
    n = int(0.05 * SR); tt = np.arange(n) / SR
    add(filt(noise(n), 'bp', (1500, 9000)) * np.exp(-tt * 90), at, 0.06 + 0.08 * sm(C['mutation'], C['title'], at), rng.uniform(-0.6, 0.6))
riser(C['title'], 2.5, 0.45, 9000)
impact(C['title'], 1.1, 32)
n = int(3.5 * SR); tt = np.arange(n) / SR
add((np.sin(2 * np.pi * 41.2 * tt) + 0.4 * np.sin(2 * np.pi * 61.7 * tt)) * sm(0, 0.6, tt) * (1 - sm(2.4, 3.4, tt)) * 0.18, C['title'] + 0.3)
add(lub, C['title'] + 2.0, 1.0); add(dub, C['title'] + 2.15, 0.75)
# reverb + master
ir_n = int(2.4 * SR); tt = np.arange(ir_n) / SR
irs = [filt(noise(ir_n) * np.exp(-tt * 2.8), 'lp', 6000) for _ in range(2)]
irs = [i / np.sqrt((i ** 2).sum()) for i in irs]
out = np.stack([L + fftconvolve(L, irs[0])[:N] * 0.3, R + fftconvolve(R, irs[1])[:N] * 0.3], 1)
out /= np.abs(out).max() + 1e-9
out = np.tanh(out * 1.4) / np.tanh(1.4) * 0.92
out[: int(0.4 * SR)] *= np.linspace(0, 1, int(0.4 * SR))[:, None]
out[-int(0.3 * SR):] *= np.linspace(1, 0, int(0.3 * SR))[:, None]
dst = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), 'soundtrack_v3.wav')
with wave.open(dst, 'wb') as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes((out * 32767).astype(np.int16).tobytes())
print('wrote', dst)
