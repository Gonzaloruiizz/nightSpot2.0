"""Assemble photoreal v3: composited shot frames (out/<shot>/*.jpg, 1920x1080) + title card + soundtrack -> MP4."""
import os, sys, subprocess, shutil, glob
from PIL import Image, ImageDraw, ImageFont, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'out')
ORDER = [('lab', 6.0), ('frozen', 6.0), ('inject', 4.5), ('blood', 6.0), ('dna', 5.5), ('mutation', 7.0)]
FPS = 24
seq = os.path.join(HERE, 'tmp_seq'); shutil.rmtree(seq, ignore_errors=True); os.makedirs(seq)
k = 0
for shot, dur in ORDER:
    frames = sorted(glob.glob(os.path.join(OUT, shot, '*.jpg')))
    need = int(round(dur * FPS))
    if not frames:
        raise SystemExit(f'missing frames for {shot}')
    for i in range(need):   # pad/trim to the exact shot length
        os.symlink(frames[min(i, len(frames) - 1)], os.path.join(seq, f'{k:05d}.jpg')); k += 1
# title card (3.5 s on black + 0.5 s black)
f1 = ImageFont.truetype(os.path.join(HERE, '..', 'assets', 'fonts', 'Exo2-VF.ttf'), 92)
try:
    f1.set_variation_by_axes([200])
except Exception:
    pass
f2 = ImageFont.truetype(os.path.join(HERE, '..', 'assets', 'fonts', 'Rajdhani-Light.ttf'), 28)
def spaced(d, y, text, font, sp, fill):
    w = sum(d.textlength(c, font=font) for c in text) + sp * (len(text) - 1)
    x = (1920 - w) / 2
    for c in text:
        d.text((x, y), c, font=font, fill=fill); x += d.textlength(c, font=font) + sp
td = os.path.join(HERE, 'tmp_title'); shutil.rmtree(td, ignore_errors=True); os.makedirs(td)
for i in range(int(4.0 * FPS)):
    tt = i / FPS
    a = min(1, max(0, (tt - 0.6) / 1.0)) * min(1, max(0, (3.7 - tt) / 0.6))
    im = Image.new('RGB', (1920, 1080), 'black')
    glow = Image.new('RGB', (1920, 1080), 'black'); dg = ImageDraw.Draw(glow)
    spaced(dg, 438, 'PROYECTO LÁZARO', f1, 34 + tt * 4, (int(40 * a), int(230 * a), int(180 * a)))
    im = Image.blend(im, glow.filter(ImageFilter.GaussianBlur(18)), 0.7)
    d = ImageDraw.Draw(im)
    spaced(d, 438, 'PROYECTO LÁZARO', f1, 34 + tt * 4, (int(232 * a), int(250 * a), int(255 * a)))
    spaced(d, 578, 'LA MUERTE SOLO FUE UNA PAUSA', f2, 16, (int(127 * a), int(216 * a), int(232 * a)))
    p = os.path.join(td, f'{i:04d}.jpg'); im.save(p, quality=95)
    os.symlink(p, os.path.join(seq, f'{k:05d}.jpg')); k += 1
dst = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, '..', 'proyecto_lazaro_fotorrealista_v3.mp4')
audio = os.path.join(HERE, 'soundtrack_v3.wav')
br = sys.argv[2] if len(sys.argv) > 2 else '6000k'
for p in (1, 2):
    cmd = ['ffmpeg', '-y', '-loglevel', 'error', '-framerate', str(FPS), '-i', os.path.join(seq, '%05d.jpg')]
    if p == 2:
        cmd += ['-i', audio, '-c:a', 'aac', '-b:a', '192k', '-shortest', '-movflags', '+faststart']
    cmd += ['-c:v', 'libx264', '-preset', 'slow', '-b:v', br, '-pass', str(p), '-passlogfile', os.path.join(HERE, 'x264v3'), '-pix_fmt', 'yuv420p']
    cmd += (['-an', '-f', 'mp4', '/dev/null'] if p == 1 else [dst])
    subprocess.run(cmd, check=True)
print('wrote', dst, k, 'frames')
