"""Procedural soundtrack for "Proyecto Lázaro" (synced to timeline.json).

Everything is synthesised with numpy: drones, cryo hiss, servo motors,
injection, heartbeat (same bpm curve as the visuals), monitor beeps,
transitions, DNA shimmer, alarm and the final hit.
"""
import json, sys, os
import numpy as np
from scipy.signal import butter, sosfilt, fftconvolve

SR = 48000
HERE = os.path.dirname(os.path.abspath(__file__))
cfg = json.load(open(os.path.join(HERE, '..', 'timeline.json')))
DUR = cfg['duration']
N = int(DUR * SR)
t = np.arange(N) / SR
rng = np.random.default_rng(7)
L = np.zeros(N); R = np.zeros(N)


def sm(a, b, x):
    u = np.clip((x - a) / (b - a), 0, 1)
    return u * u * (3 - 2 * u)


def env(a, b, c, d):
    """trapezoid envelope over the whole timeline"""
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
    L[i:i + len(s)] += s * np.sqrt(0.5 * (1 - pan))
    R[i:i + len(s)] += s * np.sqrt(0.5 * (1 + pan))


def noise(n):
    return rng.standard_normal(n)


def brown(n):
    x = np.cumsum(noise(n)); x -= np.convolve(x, np.ones(4801) / 4801, mode='same'); return x / (np.abs(x).max() + 1e-9)


# ---------------------------------------------------------------- heart (same as JS)
keys = cfg['bpm']
def bpm(tt):
    return np.interp(tt, [k[0] for k in keys], [k[1] for k in keys])
b = bpm(t)
phase = np.zeros(N); started = False; p = 0.0
dt = 1 / SR
cum = np.cumsum(b / 60 * dt)
first = np.argmax(b > 0)
phase[first:] = cfg['heartStartPhase'] + cum[first:] - cum[first]
beats = []
fl = np.floor(phase)
idx = np.where((np.diff(fl) > 0) & (b[1:] > 0))[0]
for i in idx: beats.append(t[i])

def thump(freq0, freq1, dur, amp):
    n = int(dur * SR); tt = np.arange(n) / SR
    f = freq1 + (freq0 - freq1) * np.exp(-tt * 18)
    ph = 2 * np.pi * np.cumsum(f) / SR
    e = np.exp(-tt * 9) * (1 - np.exp(-tt * 400))
    return np.sin(ph) * e * amp

lub = thump(70, 38, 0.45, 1.0) + filt(noise(int(0.45 * SR)), 'lp', 180) * np.exp(-np.arange(int(0.45 * SR)) / SR * 25) * 0.3
dub = thump(85, 45, 0.35, 0.7)

# ---------------------------------------------------------------- 1. ambience: cold drone
drone = np.zeros(N)
for f, a in [(55, 0.5), (55.4, 0.35), (82.4, 0.25), (110.3, 0.12), (164.8, 0.06)]:
    drone += a * np.sin(2 * np.pi * f * t + rng.random() * 6)
saw = np.zeros(N)
for f in (55.2, 54.8, 110.1):
    saw += ((t * f) % 1 - 0.5)
saw = filt(saw, 'lp', 420) * (0.5 + 0.5 * np.sin(2 * np.pi * 0.07 * t))
lab_mask = env(0, 2.5, 28.6, 29.6) + env(53.8, 54.2, 69.2, 69.35)
add((drone * 0.22 + saw * 0.12) * lab_mask, gain=0.9)
# cryo hiss + vent
hiss = filt(noise(N), 'bp', (2500, 7000)) * 0.05 * lab_mask
vent = filt(noise(N), 'lp', 400) * 0.08 * lab_mask * (0.7 + 0.3 * np.sin(2 * np.pi * 0.11 * t))
add(hiss, pan=-0.2); add(vent, pan=0.3)
# soft "no pulse" monitor tone before the injection
for k in np.arange(3.0, 26.0, 2.5):
    n = int(0.18 * SR); tt = np.arange(n) / SR
    add(np.sin(2 * np.pi * 660 * tt) * np.exp(-tt * 8) * (1 - np.exp(-tt * 300)), k, 0.05, 0.4)

# ---------------------------------------------------------------- 2. lid opening (16.4)
n = int(4.0 * SR); tt = np.arange(n) / SR
burst = filt(noise(n), 'bp', (600, 9000)) * (np.exp(-tt * 1.2) * (1 - np.exp(-tt * 30)))
rumble = filt(noise(n), 'lp', 120) * np.exp(-tt * 0.9) * 2.0
add(burst * 0.35 + rumble * 0.3, 16.4, 1.0, 0.1)
clunk = thump(140, 60, 0.4, 0.8)
add(clunk, 16.35, 0.6)
# servo motor of the lid
n = int(3.2 * SR); tt = np.arange(n) / SR
servo = filt(((tt * (95 + 20 * tt)) % 1 - 0.5), 'bp', (150, 1600)) * sm(0, 0.2, tt) * (1 - sm(2.9, 3.2, tt))
add(servo * 0.12, 16.4, 1.0, -0.3)

# ---------------------------------------------------------------- 3. robot arm
def servo_move(start, dur, f0, f1, gain, pan):
    n = int(dur * SR); tt = np.arange(n) / SR
    f = f0 + (f1 - f0) * sm(0, dur, tt)
    ph = np.cumsum(f) / SR
    s = (ph % 1 - 0.5) + 0.5 * np.sin(2 * np.pi * ph * 2.01)
    s = filt(s, 'bp', (120, 2400)) * sm(0, 0.15, tt) * (1 - sm(dur - 0.2, dur, tt))
    s += filt(noise(n), 'bp', (3000, 8000)) * 0.08 * sm(0, 0.15, tt) * (1 - sm(dur - 0.2, dur, tt))
    add(s, start, gain, pan)
servo_move(19.6, 3.6, 140, 210, 0.16, 0.35)
servo_move(23.2, 1.7, 230, 160, 0.13, 0.2)
add(thump(300, 120, 0.12, 1.0), 23.15, 0.15, 0.2)
# injection: contact click + hydraulic push
n = int(0.08 * SR); tt = np.arange(n) / SR
add(filt(noise(n), 'hp', 2000) * np.exp(-tt * 80), 24.9, 0.5, 0.2)
add(thump(220, 90, 0.25, 1.0), 24.9, 0.35, 0.2)
n = int(3.6 * SR); tt = np.arange(n) / SR
push = filt(noise(n), 'bp', (300, 1800)) * sm(0, 0.3, tt) * (1 - sm(3.2, 3.6, tt)) * 0.25
tone = np.sin(2 * np.pi * np.cumsum(180 + 120 * tt / 3.6) / SR) * 0.08 * sm(0, 0.5, tt) * (1 - sm(3.0, 3.6, tt))
add(push + tone, 25.3, 1.0, 0.1)

# ---------------------------------------------------------------- 4. transitions (risers + impacts)
def riser(end, dur, gain, top=6000):
    n = int(dur * SR); tt = np.arange(n) / SR
    x = noise(n); out = np.zeros(n)
    seg = 2048
    for i in range(0, n, seg):
        fc = 200 + (top - 200) * (i / n) ** 2
        out[i:i + seg] = filt(x[i:i + seg], 'bp', (fc * 0.7, min(fc * 1.4, 20000)))
    out *= (tt / dur) ** 2
    sweep = np.sin(2 * np.pi * np.cumsum(80 + 900 * (tt / dur) ** 3) / SR) * (tt / dur) ** 3 * 0.3
    add(out * 0.6 + sweep, end - dur, gain)

def impact(at, gain, sub=45):
    n = int(3.0 * SR); tt = np.arange(n) / SR
    s = thump(sub * 2.2, sub, 3.0, 1.0) * 1.2
    s += filt(noise(n), 'lp', 3000) * np.exp(-tt * 6) * 0.6
    add(s, at, gain)

riser(29.5, 2.4, 0.5); impact(29.5, 0.6)
riser(41.0, 1.5, 0.35, 8000); impact(41.0, 0.35, 60)
riser(45.5, 1.0, 0.3, 9000); impact(45.5, 0.3, 70)
riser(54.0, 1.6, 0.45); impact(54.0, 0.7, 40)

# ---------------------------------------------------------------- 5. bloodstream
bm = env(29.4, 30.2, 40.8, 41.1)
under = filt(brown(N), 'lp', 260) * 0.9
flow = filt(noise(N), 'bp', (80, 500)) * 0.25
pulse_env = np.zeros(N)
for bt in beats:
    i = int(bt * SR); n = int(0.6 * SR)
    if i + n < N: pulse_env[i:i + n] += np.exp(-np.arange(n) / SR * 5)
add((under + flow * (0.4 + pulse_env)) * bm * 0.7, pan=0.0)
# bubbles / cell taps
for k in range(70):
    at = 29.6 + rng.random() * 11.2
    n = int(0.12 * SR); tt = np.arange(n) / SR
    f = 300 + rng.random() * 700
    add(np.sin(2 * np.pi * f * (1 + tt * 6) * tt) * np.exp(-tt * 40) * 0.08, at, 1.0, rng.uniform(-0.8, 0.8))
# nanocarrier shimmer
sh = np.zeros(N)
for f in (1318.5, 1760, 2093, 2637):
    sh += np.sin(2 * np.pi * f * t) * (0.5 + 0.5 * np.sin(2 * np.pi * (0.3 + f / 9000) * t))
add(sh * 0.012 * bm, pan=0.3)

# ---------------------------------------------------------------- 6. cell + DNA (crystalline)
cm = env(40.9, 41.5, 53.7, 54.0)
pad = np.zeros(N)
for f in (110, 164.8, 220, 277.2, 329.6):
    pad += np.sin(2 * np.pi * f * t + np.sin(2 * np.pi * 0.2 * t) * 0.5)
add(filt(pad, 'lp', 1200) * 0.05 * cm)
scale = [880, 987.8, 1174.7, 1318.5, 1568, 1760, 1975.5, 2349.3]
at = 41.2
while at < 53.6:
    f = scale[rng.integers(len(scale))] * (2 if rng.random() < 0.2 else 1)
    n = int(1.2 * SR); tt = np.arange(n) / SR
    note = (np.sin(2 * np.pi * f * tt) + 0.3 * np.sin(2 * np.pi * f * 2.76 * tt) * np.exp(-tt * 8)) * np.exp(-tt * 3.5) * (1 - np.exp(-tt * 500))
    add(note, at, 0.05 + 0.03 * sm(46, 52, at), rng.uniform(-0.7, 0.7))
    at += 0.24 - 0.12 * sm(46, 52, at)
# editing ticks (DNA rewrite), accelerating
at = 46.3
while at < 53.3:
    n = int(0.03 * SR); tt = np.arange(n) / SR
    add(filt(noise(n), 'hp', 4000) * np.exp(-tt * 200), at, 0.12, rng.uniform(-0.4, 0.4))
    at += 0.11 - 0.07 * sm(46, 53, at)

# ---------------------------------------------------------------- 7. heartbeat (whole film)
for bt in beats:
    if bt > 69.3: continue
    if 29.4 < bt < 41.0: g, lp = 1.0, 220      # inside the artery: big & muffled
    elif 41.0 <= bt < 54: g, lp = 0.45, 300
    else: g, lp = 0.55 + 0.35 * sm(54, 66, bt), 600
    add(filt(lub, 'lp', lp), bt + 0.02, g * 0.9)
    add(filt(dub, 'lp', lp), bt + 0.17, g * 0.6)
    if bt > 53.5:  # monitor beep
        n = int(0.11 * SR); tt = np.arange(n) / SR
        add(np.sin(2 * np.pi * 988 * tt) * (1 - np.exp(-tt * 400)) * np.exp(-tt * 18), bt + 0.04, 0.07, 0.5)

# ---------------------------------------------------------------- 8. mutation: tension + alarm
mm = env(54.0, 55.0, 69.2, 69.32)
cluster = np.zeros(N)
for f in (110, 116.5, 123.5, 146.8, 155.6, 220.0, 233.1):
    ph = 2 * np.pi * np.cumsum(f * (1 + 0.004 * np.sin(2 * np.pi * 0.3 * t + f))) / SR
    cluster += (ph / (2 * np.pi) % 1 - 0.5)
cluster = filt(cluster, 'lp', 900 + 2500 * 0) * (0.3 + 0.7 * sm(54, 69, t))
add(cluster * 0.05 * mm)
# shepard-like riser
sr = np.zeros(N)
for k in range(6):
    f = 55 * 2 ** ((k + sm(54, 69.3, t) * 2.5) % 6)
    w = np.exp(-((np.log2(f / 440)) ** 2) / 2)
    sr += np.sin(2 * np.pi * np.cumsum(f) / SR) * w
add(sr * 0.05 * mm * sm(56, 69, t))
# alarm whoops from 58.6
am = env(58.6, 58.7, 69.2, 69.3)
whoop_ph = (t - 58.6) % 1.0
fw = 520 + 420 * np.clip(whoop_ph / 0.7, 0, 1)
alarm = np.sign(np.sin(2 * np.pi * np.cumsum(fw) / SR)) * (whoop_ph < 0.75)
add(filt(alarm, 'bp', (400, 2500)) * am * 0.05, pan=-0.5)
# skin crackle (ice cracking / growths)
for k in range(140):
    at = 54.5 + rng.random() * 14.5
    n = int(0.05 * SR); tt = np.arange(n) / SR
    add(filt(noise(n), 'bp', (1500, 9000)) * np.exp(-tt * 90), at, 0.06 + 0.1 * sm(57, 68, at), rng.uniform(-0.6, 0.6))

# ---------------------------------------------------------------- 9. ending
impact(69.3, 1.1, 32)
n = int(0.6 * SR); tt = np.arange(n) / SR
add(filt(noise(n), 'hp', 1500) * np.exp(-tt * 5), 69.3, 0.5)
# title: deep tone + one last heartbeat (he lives)
n = int(5.5 * SR); tt = np.arange(n) / SR
tone = (np.sin(2 * np.pi * 41.2 * tt) + 0.4 * np.sin(2 * np.pi * 61.7 * tt) + 0.2 * np.sin(2 * np.pi * 82.4 * tt)) * sm(0, 0.8, tt) * (1 - sm(3.5, 5.4, tt))
add(tone * 0.18, 70.0)
add(lub, 72.6, 1.0); add(dub, 72.75, 0.75)

# ---------------------------------------------------------------- reverb + master
ir_n = int(2.6 * SR); tt = np.arange(ir_n) / SR
irL = noise(ir_n) * np.exp(-tt * 2.6); irR = noise(ir_n) * np.exp(-tt * 2.6)
irL = filt(irL, 'lp', 6000); irR = filt(irR, 'lp', 6000)
irL /= np.sqrt((irL ** 2).sum()); irR /= np.sqrt((irR ** 2).sum())
wetL = fftconvolve(L, irL)[:N]; wetR = fftconvolve(R, irR)[:N]
outL = L + wetL * 0.32; outR = R + wetR * 0.32
out = np.stack([outL, outR], 1)
out = filt(out.T, 'hp', 25).T if False else out
out /= np.abs(out).max() + 1e-9
out = np.tanh(out * 1.4) / np.tanh(1.4) * 0.92
# fade in/out
out[: int(0.5 * SR)] *= np.linspace(0, 1, int(0.5 * SR))[:, None]
out[-int(0.4 * SR):] *= np.linspace(1, 0, int(0.4 * SR))[:, None]
pcm = (out * 32767).astype(np.int16)
import wave
dst = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, 'soundtrack.wav')
with wave.open(dst, 'wb') as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm.tobytes())
print('wrote', dst, f'{len(beats)} heartbeats')
