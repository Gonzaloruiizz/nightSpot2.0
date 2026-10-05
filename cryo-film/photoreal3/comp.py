"""Compositing toolkit for the photoreal v3 pipeline (numpy + OpenCV, scene-linear float32).

Typical shot comp:
    P = load_exr('renders/face_frozen.exr')          # dict of passes, linear float32
    cam = load_cam('renders/face_frozen.json')
    for i in range(n):
        t = i / FPS
        img = P['Combined'][..., :3]
        img = warp25d(img, P['Depth'], cam, move=(dx, dy, dz), rot=(pan, tilt, roll))
        img = lens_blur(img, depth_warped, cam, focus=0.6, fstop=2.0)
        img = finish(img, frame=i)                    # bloom/halation, AgX, grade, CA, grain, vignette
        save_frame(img, out_dir, i)                  # 1920x1080 letterboxed JPEG
"""
import os, json, math
import numpy as np
import cv2
import OpenEXR

W, H = 1920, 804
FPS = 24


# ------------------------------------------------------------------ IO
def load_exr(path):
    """Multilayer / multipart EXR from Blender -> {pass_name: float32 array (H,W) or (H,W,C)}.
    Pass names: Combined (RGBA), Depth, Normal, Diffuse Color, Emission, Noisy Image, <custom AOVs>."""
    out = {}
    order = ['R', 'G', 'B', 'A', 'X', 'Y', 'Z', 'V']
    with OpenEXR.File(path, separate_channels=False) as f:
        for part in f.parts:
            pname = part.name().split('.')[-1] if '.' in part.name() else part.name()
            chans = part.channels
            if len(chans) == 1:
                arr = np.asarray(list(chans.values())[0].pixels, dtype=np.float32)
            else:
                keys = sorted(chans, key=lambda k: order.index(k.split('.')[-1]) if k.split('.')[-1] in order else 99)
                arr = np.stack([np.asarray(chans[k].pixels, dtype=np.float32) for k in keys], -1)
            if arr.ndim == 3 and arr.shape[-1] == 1:
                arr = arr[..., 0]
            out[pname] = arr
    if 'Depth' in out and out['Depth'].ndim == 3:
        out['Depth'] = out['Depth'][..., 0]
    return out


def load_cam(path):
    c = json.load(open(path))
    c['f_px'] = c['lens'] / c['sensor'] * c['w']
    return c


def fit(img, w=W, h=H):
    """Resize a pass (e.g. preview resolution) to the working resolution."""
    if img.shape[1] == w and img.shape[0] == h:
        return img
    return cv2.resize(img, (w, h), interpolation=cv2.INTER_LINEAR if img.ndim == 3 or img.dtype != np.float32 else cv2.INTER_NEAREST)


# ------------------------------------------------------------------ 2.5D camera
def warp25d(img, depth, cam, move=(0.0, 0.0, 0.0), rot=(0.0, 0.0, 0.0), zoom=1.0, extra=()):
    """Re-photograph a still from a slightly moved camera using its depth pass.

    move: camera translation in metres in camera space (x right, y up, z backwards; negative z = dolly in)
    rot:  (pan, tilt, roll) in radians.  zoom: focal length multiplier.
    extra: more arrays (masks, depth...) warped with the same mapping.  Returns img (and extras).
    Small moves only (parallax is approximated by an iterative inverse of the forward flow)."""
    h, w = depth.shape
    f = cam['f_px'] * (w / cam['w'])
    cx, cy = w / 2.0, h / 2.0
    uu, vv = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    Z = np.clip(depth, 1e-4, 1e4)
    X = (uu - cx) / f * Z
    Y = -(vv - cy) / f * Z
    tx, ty, tz = move
    pan, tilt, roll = rot
    cp, sp, ct, st, cr, sr = math.cos(pan), math.sin(pan), math.cos(tilt), math.sin(tilt), math.cos(roll), math.sin(roll)
    Ry = np.array([[cp, 0, sp], [0, 1, 0], [-sp, 0, cp]], np.float32)
    Rx = np.array([[1, 0, 0], [0, ct, -st], [0, st, ct]], np.float32)
    Rz = np.array([[cr, -sr, 0], [sr, cr, 0], [0, 0, 1]], np.float32)
    Rt = (Ry @ Rx @ Rz).T
    Px, Py, Pz = X - tx, Y - ty, -Z - tz
    Qx = Rt[0, 0] * Px + Rt[0, 1] * Py + Rt[0, 2] * Pz
    Qy = Rt[1, 0] * Px + Rt[1, 1] * Py + Rt[1, 2] * Pz
    Qz = Rt[2, 0] * Px + Rt[2, 1] * Py + Rt[2, 2] * Pz
    Qz = np.minimum(Qz, -1e-4)
    fu = cx + f * zoom * Qx / (-Qz)
    fv = cy - f * zoom * Qy / (-Qz)
    du, dv = fu - uu, fv - vv
    # iterative inverse of the forward flow
    su, sv = uu.copy(), vv.copy()
    for _ in range(4):
        su = uu - cv2.remap(du, su, sv, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        sv = vv - cv2.remap(dv, su, sv, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    out = cv2.remap(img, su, sv, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    if extra:
        ex = [cv2.remap(e, su, sv, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT) for e in extra]
        return (out, *ex)
    return out


def zoom_crop(img, zoom=1.0, center=(0.5, 0.5)):
    """Simple 2D push-in (no parallax)."""
    h, w = img.shape[:2]
    M = cv2.getRotationMatrix2D((center[0] * w, center[1] * h), 0, zoom)
    return cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)


# ------------------------------------------------------------------ depth of field
def _disc(r):
    r = max(0.5, r)
    k = int(math.ceil(r))
    y, x = np.mgrid[-k:k + 1, -k:k + 1]
    d = np.sqrt(x * x + y * y)
    ker = np.clip(r + 0.5 - d, 0, 1).astype(np.float32)
    return ker / ker.sum()


def coc_px(depth, cam, focus, fstop, w=W):
    """Thin-lens circle of confusion diameter in pixels."""
    f_m = cam['lens'] / 1000.0
    sensor_m = cam['sensor'] / 1000.0
    A = f_m / fstop
    z = np.clip(depth, 1e-4, 1e5)
    c = A * f_m * np.abs(z - focus) / (z * max(focus - f_m, 1e-4))
    return c / sensor_m * w


def lens_blur(img, depth, cam, focus, fstop, max_px=40, layers=9):
    """Layered disc-kernel depth of field (back-to-front), preserves bokeh shapes of highlights."""
    h, w = depth.shape
    coc = np.minimum(coc_px(depth, cam, focus, fstop, w), max_px)
    sign = np.where(depth < focus, -1.0, 1.0)
    sc = coc * sign
    edges = np.quantile(sc, np.linspace(0, 1, layers + 1))
    edges[0] -= 1e-3; edges[-1] += 1e-3
    acc = np.zeros((h, w, 3), np.float32)
    acc_a = np.zeros((h, w), np.float32)
    # far to near
    idx = sorted(range(layers), key=lambda i: -(edges[i] + edges[i + 1]))
    for i in idx:
        lo, hi = edges[i], edges[i + 1]
        m = ((sc >= lo) & (sc < hi)).astype(np.float32)
        if m.sum() < 1:
            continue
        r = float(np.abs(sc[m > 0]).mean()) / 2.0
        k = _disc(r)
        layer = img * m[..., None]
        if r > 0.6:
            layer = cv2.filter2D(layer, -1, k, borderType=cv2.BORDER_REFLECT)
            mb = cv2.filter2D(m, -1, k, borderType=cv2.BORDER_REFLECT)
        else:
            mb = m
        acc = layer + acc * (1 - mb[..., None])
        acc_a = mb + acc_a * (1 - mb)
    return acc + img * (1 - np.clip(acc_a, 0, 1))[..., None]


# ------------------------------------------------------------------ light effects
def bloom(img, threshold=1.0, strength=0.08, halation=0.06):
    """Physically motivated glow: soft bloom + warm film halation around highlights."""
    lum = img @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    bright = img * np.clip((lum - threshold) / max(threshold, 1e-3), 0, 4)[..., None]
    out = np.zeros_like(img)
    small = bright
    wsum = 0
    for i, s in enumerate([2, 4, 8, 16, 32]):
        small = cv2.resize(bright, (img.shape[1] // s, img.shape[0] // s), interpolation=cv2.INTER_AREA)
        small = cv2.GaussianBlur(small, (0, 0), 2.0)
        up = cv2.resize(small, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_LINEAR)
        wgt = 1.0 / (i + 1)
        out += up * wgt
        wsum += wgt
    out /= wsum
    hal = cv2.GaussianBlur(bright, (0, 0), 6.0) * np.array([1.0, 0.35, 0.12], np.float32)
    return img + out * strength + hal * halation


def add_glow(img, emit, strength=1.0, radius=12.0):
    """Extra glow from an emission pass (e.g. veins, serum)."""
    g = cv2.GaussianBlur(emit, (0, 0), radius) + cv2.GaussianBlur(emit, (0, 0), radius * 4) * 0.5
    return img + g * strength


# ------------------------------------------------------------------ view transform & grade
_SRGB_TO_2020 = np.array([[0.6274, 0.3293, 0.0433], [0.0691, 0.9195, 0.0113], [0.0164, 0.0880, 0.8956]], np.float32)
_2020_TO_SRGB = np.linalg.inv(_SRGB_TO_2020).astype(np.float32)
_INSET = np.array([[0.856627153315983, 0.0951212405381588, 0.0482516061458583],
                   [0.137318972929847, 0.761241990602591, 0.101439036467562],
                   [0.11189821299995, 0.0767994186031903, 0.811302368396859]], np.float32).T
_OUTSET = np.array([[1.1271005818144368, -0.11060664309660323, -0.016493938717834573],
                    [-0.1413297634984383, 1.157823702216272, -0.016493938717834257],
                    [-0.14132976349843826, -0.11060664309660294, 1.2519364065950405]], np.float32).T


def agx(img, exposure=0.0):
    c = img * (2.0 ** exposure)
    c = c @ _SRGB_TO_2020.T
    c = c @ _INSET
    c = np.maximum(c, 1e-10)
    c = (np.log2(c) + 12.47393) / (4.026069 + 12.47393)
    x = np.clip(c, 0, 1)
    x2 = x * x; x4 = x2 * x2
    c = 15.5 * x4 * x2 - 40.14 * x4 * x + 31.96 * x4 - 6.868 * x2 * x + 0.4298 * x2 + 0.1191 * x - 0.00232
    c = c @ _OUTSET
    c = np.power(np.maximum(c, 0), 2.2)
    c = c @ _2020_TO_SRGB.T
    return np.clip(c, 0, 1)   # display-linear


def grade(disp, lift=(0.0, 0.0, 0.0), gamma=(1.0, 1.0, 1.0), gain=(1.0, 1.0, 1.0), sat=1.0, contrast=1.0,
          shadow_tint=(0.0, 0.01, 0.02), high_tint=(0.02, 0.01, 0.0)):
    """Grade in display-referred space (0..1 linear display), returns 0..1 linear display."""
    c = disp
    lum = c @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    c = lum[..., None] + (c - lum[..., None]) * sat
    c = c + np.array(shadow_tint, np.float32) * (1 - np.clip(lum * 3, 0, 1))[..., None] + np.array(high_tint, np.float32) * np.clip((lum - 0.4) * 2, 0, 1)[..., None]
    c = np.clip(c, 0, None)
    # contrast around mid-grey in perceptual space
    p = np.power(c, 1 / 2.2)
    p = (p - 0.42) * contrast + 0.42
    p = np.array(gain, np.float32) * (p + np.array(lift, np.float32) * (1 - p))
    p = np.power(np.clip(p, 0, 1), 1 / np.array(gamma, np.float32))
    return np.power(p, 2.2)


def to_srgb8(disp):
    c = np.clip(disp, 0, 1)
    s = np.where(c <= 0.0031308, 12.92 * c, 1.055 * np.power(c, 1 / 2.4) - 0.055)
    return (s * 255 + 0.5).astype(np.uint8)


def chromatic(img, amount=0.0012):
    h, w = img.shape[:2]
    out = img.copy()
    for ch, s in ((0, 1 + amount), (2, 1 - amount)):
        M = cv2.getRotationMatrix2D((w / 2, h / 2), 0, s)
        out[..., ch] = cv2.warpAffine(img[..., ch], M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    return out


def vignette(img, amount=0.35):
    h, w = img.shape[:2]
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    r = np.sqrt(((x - w / 2) / (w / 2)) ** 2 * 1.0 + ((y - h / 2) / (h / 2)) ** 2 * 0.55)
    return img * (1 - amount * np.clip(r - 0.35, 0, 1) ** 1.5)[..., None]


def grain(srgb_float, frame, amount=0.045, size=1.2):
    """Film grain in display space (luminance weighted towards mid-tones)."""
    rng = np.random.default_rng(1000 + frame)
    h, w = srgb_float.shape[:2]
    n = rng.standard_normal((int(h / size), int(w / size), 1)).astype(np.float32)
    n = cv2.resize(n, (w, h), interpolation=cv2.INTER_LINEAR)[..., None] if n.shape[-1] == 1 else n
    if n.ndim == 2:
        n = n[..., None]
    lum = srgb_float.mean(-1, keepdims=True)
    wgt = 0.35 + 1.3 * lum * (1 - lum)
    return np.clip(srgb_float + n * amount * wgt, 0, 1)


def finish(lin, frame, exposure=0.0, look=None, bloom_t=1.0, bloom_s=0.08, halation=0.05, ca=0.0012, vig=0.35, grain_amt=0.04, fade=0.0, flash=0.0, flash_color=(1, 1, 1)):
    """Linear HDR -> graded sRGB uint8 frame (W x H). `look` = dict for grade()."""
    c = bloom(lin, bloom_t, bloom_s, halation)
    c = chromatic(c, ca)
    d = agx(c, exposure)
    d = grade(d, **(look or {}))
    d = vignette(d, vig)
    d = d * (1 - flash) + np.array(flash_color, np.float32) * flash
    d = d * (1 - fade)
    s = np.clip(np.where(d <= 0.0031308, 12.92 * d, 1.055 * np.power(np.clip(d, 0, 1), 1 / 2.4) - 0.055), 0, 1)
    s = grain(s, frame, grain_amt)
    return (s * 255 + 0.5).astype(np.uint8)


def save_frame(rgb8, out_dir, i):
    os.makedirs(out_dir, exist_ok=True)
    canvas = np.zeros((1080, 1920, 3), np.uint8)
    if rgb8.shape[1] != 1920 or rgb8.shape[0] != 804:
        rgb8 = cv2.resize(rgb8, (1920, 804), interpolation=cv2.INTER_LANCZOS4)
    canvas[138:942] = rgb8
    cv2.imwrite(os.path.join(out_dir, f'{i:04d}.jpg'), canvas[..., ::-1], [cv2.IMWRITE_JPEG_QUALITY, 94])


# ------------------------------------------------------------------ misc
def smooth(a, b, x):
    u = min(1.0, max(0.0, (x - a) / (b - a)))
    return u * u * (3 - 2 * u)


def ease(u):
    u = min(1.0, max(0.0, u))
    return u * u * (3 - 2 * u)


def sstep(a, b, arr):
    u = np.clip((arr - a) / (b - a), 0, 1)
    return u * u * (3 - 2 * u)


def noise2d(h, w, scale, seed=0, octaves=4):
    """Smooth value-noise field (H,W) in [0,1] for fog/steam/organic masks."""
    rng = np.random.default_rng(seed)
    out = np.zeros((h, w), np.float32)
    amp, tot = 1.0, 0.0
    for o in range(octaves):
        gh, gw = max(2, int(h / scale * 2 ** o) + 2), max(2, int(w / scale * 2 ** o) + 2)
        g = rng.random((gh, gw)).astype(np.float32)
        out += cv2.resize(g, (w, h), interpolation=cv2.INTER_CUBIC) * amp
        tot += amp
        amp *= 0.5
    return np.clip(out / tot, 0, 1)
