"""Assemble the photoreal cut: 12 fps Cycles renders -> motion-interpolated 24 fps,
upscale, transitions, title card, film grain, letterbox and soundtrack."""
import os, subprocess, glob, shutil, sys
from PIL import Image, ImageDraw, ImageFont, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
FR = os.path.join(HERE, 'frames')
TMP = os.path.join(HERE, 'tmp'); os.makedirs(TMP, exist_ok=True)
ORDER = [('establish', 4.5), ('frozen', 4.0), ('needle', 3.5), ('blood', 4.5), ('dna', 4.5), ('mutation', 6.0)]
FADES = {  # (fade-in color, fade-in dur, fade-out color, fade-out dur)
    'establish': ('black', 1.2, None, 0), 'frozen': (None, 0, None, 0), 'needle': (None, 0, 'white', 0.25),
    'blood': ('white', 0.35, None, 0), 'dna': ('white', 0.2, 'white', 0.2), 'mutation': ('white', 0.25, 'white', 0.35),
}


def run(cmd):
    print(' '.join(cmd[:6]), '...'); subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


segs = []
for shot, dur in ORDER:
    src = sorted(glob.glob(os.path.join(FR, shot, '*.jpg')))
    seq = os.path.join(TMP, shot); shutil.rmtree(seq, ignore_errors=True); os.makedirs(seq)
    for i, f in enumerate(src + [src[-1]] * 3):  # pad: minterpolate drops the tail
        os.symlink(f, os.path.join(seq, f'{i:04d}.jpg'))
    vf = ['minterpolate=fps=24:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1', 'scale=1920:804:flags=lanczos', 'unsharp=5:5:0.6']
    fi, fid, fo, fod = FADES[shot]
    if fi: vf.append(f'fade=t=in:st=0:d={fid}:color={fi}')
    if fo: vf.append(f'fade=t=out:st={dur - fod:.3f}:d={fod}:color={fo}')
    out = os.path.join(TMP, f'{shot}.mp4')
    run(['ffmpeg', '-y', '-framerate', '12', '-i', os.path.join(seq, '%04d.jpg'), '-vf', ','.join(vf), '-t', str(dur), '-r', '24',
         '-c:v', 'libx264', '-preset', 'medium', '-crf', '14', '-pix_fmt', 'yuv420p', out])
    segs.append(out)

# title card
td = os.path.join(TMP, 'title'); shutil.rmtree(td, ignore_errors=True); os.makedirs(td)
f1 = ImageFont.truetype(os.path.join(HERE, '..', 'assets', 'fonts', 'Exo2-VF.ttf'), 92)
try: f1.set_variation_by_axes([200])
except Exception: pass
f2 = ImageFont.truetype(os.path.join(HERE, '..', 'assets', 'fonts', 'Rajdhani-Light.ttf'), 28)
def spaced(d, y, text, font, sp, fill):
    w = sum(d.textlength(c, font=font) for c in text) + sp * (len(text) - 1)
    x = (1920 - w) / 2
    for c in text:
        d.text((x, y), c, font=font, fill=fill); x += d.textlength(c, font=font) + sp
for i in range(int(3.5 * 24)):
    tt = i / 24
    a = min(1, max(0, (tt - 0.5) / 1.0)) * min(1, max(0, (3.4 - tt) / 0.6))
    im = Image.new('RGB', (1920, 804), 'black')
    glow = Image.new('RGB', (1920, 804), 'black'); dg = ImageDraw.Draw(glow)
    spaced(dg, 300, 'PROYECTO LÁZARO', f1, 34 + tt * 4, (int(60 * a), int(255 * a), int(210 * a)))
    glow = glow.filter(ImageFilter.GaussianBlur(18))
    im = Image.blend(im, glow, 0.8)
    d = ImageDraw.Draw(im)
    spaced(d, 300, 'PROYECTO LÁZARO', f1, 34 + tt * 4, (int(232 * a), int(250 * a), int(255 * a)))
    spaced(d, 440, 'LA MUERTE SOLO FUE UNA PAUSA', f2, 16, (int(127 * a), int(216 * a), int(232 * a)))
    im.save(os.path.join(td, f'{i:04d}.jpg'), quality=95)
tout = os.path.join(TMP, 'title.mp4')
run(['ffmpeg', '-y', '-framerate', '24', '-i', os.path.join(td, '%04d.jpg'), '-c:v', 'libx264', '-crf', '14', '-pix_fmt', 'yuv420p', tout])
segs.append(tout)

lst = os.path.join(TMP, 'list.txt')
open(lst, 'w').write(''.join(f"file '{s}'\n" for s in segs))
cat = os.path.join(TMP, 'concat.mp4')
run(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', lst, '-c', 'copy', cat])
audio = os.path.join(HERE, 'soundtrack_v2.wav')
dst = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, '..', 'proyecto_lazaro_fotorrealista.mp4')
run(['ffmpeg', '-y', '-i', cat, '-i', audio, '-vf', 'noise=alls=7:allf=t+u,vignette=PI/5,pad=1920:1080:0:138:black',
     '-c:v', 'libx264', '-preset', 'slow', '-crf', '20', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', '-c:a', 'aac', '-b:a', '224k', '-shortest', dst])
print('wrote', dst)
