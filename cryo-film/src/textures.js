import * as THREE from 'three';
import { rng } from './util.js';

function canvas(w, h = w) { const c = document.createElement('canvas'); c.width = w; c.height = h; return c; }

// Tileable fbm value noise -> Float32Array in [0,1]
export function noiseField(size, seed = 1, baseCells = 4, octaves = 5, gain = 0.5) {
  const out = new Float32Array(size * size);
  let amp = 1, norm = 0, cells = baseCells;
  for (let o = 0; o < octaves; o++) {
    const r = rng(seed * 977 + o * 131);
    const lat = new Float32Array(cells * cells); for (let i = 0; i < lat.length; i++) lat[i] = r();
    for (let y = 0; y < size; y++) {
      const fy = (y / size) * cells, iy = Math.floor(fy), ty = fy - iy, sy = ty * ty * (3 - 2 * ty);
      for (let x = 0; x < size; x++) {
        const fx = (x / size) * cells, ix = Math.floor(fx), tx = fx - ix, sx = tx * tx * (3 - 2 * tx);
        const x0 = ix % cells, x1 = (ix + 1) % cells, y0 = iy % cells, y1 = (iy + 1) % cells;
        const a = lat[y0 * cells + x0], b = lat[y0 * cells + x1], c = lat[y1 * cells + x0], d = lat[y1 * cells + x1];
        out[y * size + x] += amp * ((a + (b - a) * sx) * (1 - sy) + (c + (d - c) * sx) * sy);
      }
    }
    norm += amp; amp *= gain; cells *= 2;
  }
  for (let i = 0; i < out.length; i++) out[i] /= norm;
  return out;
}

function toTexture(c, srgb = true, repeat = true) {
  const t = new THREE.CanvasTexture(c);
  if (srgb) t.colorSpace = THREE.SRGBColorSpace;
  if (repeat) t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.anisotropy = 4;
  return t;
}

export function glowSprite(size = 128) {
  const c = canvas(size), g = c.getContext('2d');
  const gr = g.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  gr.addColorStop(0, 'rgba(255,255,255,1)'); gr.addColorStop(0.2, 'rgba(255,255,255,0.55)');
  gr.addColorStop(0.5, 'rgba(255,255,255,0.12)'); gr.addColorStop(1, 'rgba(255,255,255,0)');
  g.fillStyle = gr; g.fillRect(0, 0, size, size);
  return toTexture(c, false, false);
}

export function smokePuff(size = 256, seed = 3) {
  const n = noiseField(size, seed, 4, 5, 0.55);
  const c = canvas(size), g = c.getContext('2d'), img = g.createImageData(size, size);
  for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
    const dx = (x + 0.5) / size * 2 - 1, dy = (y + 0.5) / size * 2 - 1, r = Math.sqrt(dx * dx + dy * dy);
    const fall = Math.max(0, 1 - r); const v = Math.max(0, n[y * size + x] * 1.6 - 0.45) * fall * fall;
    const i = (y * size + x) * 4; img.data[i] = img.data[i + 1] = img.data[i + 2] = 255; img.data[i + 3] = Math.min(255, v * 255 * 1.6);
  }
  g.putImageData(img, 0, 0);
  return toTexture(c, false, false);
}

// Grayscale tileable noise texture (linear), used for fog layers / alpha maps
export function noiseTexture(size = 512, seed = 7, cells = 4, octaves = 6, contrast = 1.6, bias = -0.3) {
  const n = noiseField(size, seed, cells, octaves, 0.55);
  const c = canvas(size), g = c.getContext('2d'), img = g.createImageData(size, size);
  for (let i = 0; i < n.length; i++) {
    const v = Math.max(0, Math.min(1, (n[i] - 0.5) * contrast + 0.5 + bias)) * 255;
    img.data[i * 4] = img.data[i * 4 + 1] = img.data[i * 4 + 2] = v; img.data[i * 4 + 3] = 255;
  }
  g.putImageData(img, 0, 0);
  return toTexture(c, false, true);
}

// Wall panels: albedo with seams, vents and frost creeping from the bottom
export function wallTextures(size = 1024) {
  const c = canvas(size), g = c.getContext('2d');
  const n = noiseField(size / 2, 11, 6, 6);
  g.fillStyle = '#1b222b'; g.fillRect(0, 0, size, size);
  const r = rng(5);
  const cols = 4, rows = 2, pw = size / cols, ph = size / rows;
  for (let j = 0; j < rows; j++) for (let i = 0; i < cols; i++) {
    const shade = 26 + Math.floor(r() * 10);
    g.fillStyle = `rgb(${shade},${shade + 6},${shade + 13})`;
    g.fillRect(i * pw + 6, j * ph + 6, pw - 12, ph - 12);
    // inner frame
    g.strokeStyle = 'rgba(0,0,0,0.6)'; g.lineWidth = 3; g.strokeRect(i * pw + 22, j * ph + 22, pw - 44, ph - 44);
    g.strokeStyle = 'rgba(160,190,220,0.08)'; g.lineWidth = 1; g.strokeRect(i * pw + 24, j * ph + 24, pw - 48, ph - 48);
    if (r() < 0.5) { // vent slots
      for (let k = 0; k < 7; k++) { g.fillStyle = 'rgba(0,0,0,0.75)'; g.fillRect(i * pw + 50, j * ph + 60 + k * 18, pw - 100, 8); }
    }
    // rivets
    g.fillStyle = 'rgba(200,220,240,0.12)';
    for (const [a, b] of [[14, 14], [pw - 14, 14], [14, ph - 14], [pw - 14, ph - 14]]) { g.beginPath(); g.arc(i * pw + a, j * ph + b, 3, 0, 7); g.fill(); }
  }
  // grime + frost
  const img = g.getImageData(0, 0, size, size);
  for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
    const k = (y * size + x) * 4; const v = n[(y >> 1) * (size / 2) + (x >> 1)];
    const frost = Math.max(0, Math.min(1, (y / size - 0.55) * 2.2 + (v - 0.5) * 1.8)) * 0.85;
    const grime = (v - 0.5) * 30;
    for (let ch = 0; ch < 3; ch++) {
      const base = img.data[k + ch] + grime;
      const fc = [205, 225, 240][ch];
      img.data[k + ch] = base * (1 - frost) + fc * frost;
    }
  }
  g.putImageData(img, 0, 0);
  return toTexture(c);
}

export function floorTextures(size = 1024) {
  const c = canvas(size), g = c.getContext('2d');
  const n = noiseField(size / 2, 21, 8, 6);
  g.fillStyle = '#0d1116'; g.fillRect(0, 0, size, size);
  const tiles = 4, tw = size / tiles;
  for (let j = 0; j < tiles; j++) for (let i = 0; i < tiles; i++) {
    g.fillStyle = (i + j) % 2 ? '#141a21' : '#11161c';
    g.fillRect(i * tw + 3, j * tw + 3, tw - 6, tw - 6);
    if ((i * 3 + j) % 5 === 0) { // grating tile
      g.fillStyle = '#06080a'; for (let k = 0; k < 16; k++) g.fillRect(i * tw + 14 + k * ((tw - 28) / 16), j * tw + 14, 6, tw - 28);
    }
  }
  const img = g.getImageData(0, 0, size, size);
  for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
    const k = (y * size + x) * 4; const v = n[(y >> 1) * (size / 2) + (x >> 1)];
    const ice = Math.max(0, (v - 0.58) * 3.0);
    for (let ch = 0; ch < 3; ch++) img.data[k + ch] = img.data[k + ch] * (1 - ice) + [120, 150, 175][ch] * ice + (v - 0.5) * 14;
  }
  g.putImageData(img, 0, 0);
  const rough = canvas(size / 2), rg = rough.getContext('2d'), rimg = rg.createImageData(size / 2, size / 2);
  for (let i = 0; i < n.length; i++) { const v = 90 + (1 - n[i]) * 150; rimg.data[i * 4] = rimg.data[i * 4 + 1] = rimg.data[i * 4 + 2] = v; rimg.data[i * 4 + 3] = 255; }
  rg.putImageData(rimg, 0, 0);
  return { map: toTexture(c), roughnessMap: toTexture(rough, false) };
}

export function quiltTexture(size = 512) {
  const c = canvas(size), g = c.getContext('2d');
  const n = noiseField(size, 33, 8, 5);
  const img = g.createImageData(size, size);
  for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
    const u = x / size * 6, v = y / size * 6;
    const d1 = Math.abs(((u + v) % 1 + 1) % 1 - 0.5), d2 = Math.abs(((u - v) % 1 + 1) % 1 - 0.5);
    const seam = Math.max(Math.exp(-Math.pow((0.5 - d1) / 0.02, 2)), Math.exp(-Math.pow((0.5 - d2) / 0.02, 2)));
    const nn = n[y * size + x];
    const k = (y * size + x) * 4; const base = 170 + (nn - 0.5) * 40 - seam * 70;
    img.data[k] = base * 0.86; img.data[k + 1] = base * 0.93; img.data[k + 2] = base; img.data[k + 3] = 255;
  }
  g.putImageData(img, 0, 0);
  return toTexture(c);
}

// Generic canvas-backed texture for in-world screens
export function screenCanvas(w, h) {
  const c = canvas(w, h); const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace;
  return { canvas: c, ctx: c.getContext('2d'), tex };
}
