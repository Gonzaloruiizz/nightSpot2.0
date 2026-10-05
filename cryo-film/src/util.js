import * as THREE from 'three';

export const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
export const lerp = (a, b, t) => a + (b - a) * t;
export const smooth = (a, b, x) => { const t = clamp((x - a) / (b - a)); return t * t * (3 - 2 * t); };
export const ease = {
  inOut: t => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2),
  out: t => 1 - Math.pow(1 - t, 3),
  in: t => t * t * t,
  sine: t => -(Math.cos(Math.PI * t) - 1) / 2,
  lin: t => t,
};

export function rng(seed) {
  let a = seed >>> 0;
  return function () {
    a |= 0; a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const h1 = (n) => { const s = Math.sin(n * 127.1 + 311.7) * 43758.5453; return s - Math.floor(s); };
export function noise1(x, seed = 0) {
  const i = Math.floor(x), f = x - i, u = f * f * (3 - 2 * f);
  return lerp(h1(i + seed * 101.3), h1(i + 1 + seed * 101.3), u) * 2 - 1;
}
export const fbm1 = (x, seed = 0) => noise1(x, seed) * 0.57 + noise1(x * 2.13, seed + 3) * 0.29 + noise1(x * 4.37, seed + 7) * 0.14;

// Keyframed vector track: keys = [[time, [x,y,z]], ...]
export function vtrack(keys, t, fn = ease.inOut, out = new THREE.Vector3()) {
  if (t <= keys[0][0]) return out.fromArray(keys[0][1]);
  for (let i = 0; i < keys.length - 1; i++) {
    const [t0, a] = keys[i], [t1, b] = keys[i + 1];
    if (t <= t1) {
      const u = fn(clamp((t - t0) / (t1 - t0)));
      return out.set(lerp(a[0], b[0], u), lerp(a[1], b[1], u), lerp(a[2], b[2], u));
    }
  }
  return out.fromArray(keys[keys.length - 1][1]);
}
export function strack(keys, t, fn = ease.inOut) {
  if (t <= keys[0][0]) return keys[0][1];
  for (let i = 0; i < keys.length - 1; i++) {
    const [t0, a] = keys[i], [t1, b] = keys[i + 1];
    if (t <= t1) return lerp(a, b, fn(clamp((t - t0) / (t1 - t0))));
  }
  return keys[keys.length - 1][1];
}

// Heartbeat envelope: returns 0..1 spike shape for a given phase (beats)
export function beatShape(phase) {
  const f = phase - Math.floor(phase);
  return Math.exp(-Math.pow((f - 0.05) / 0.03, 2)) + 0.55 * Math.exp(-Math.pow((f - 0.2) / 0.035, 2));
}
