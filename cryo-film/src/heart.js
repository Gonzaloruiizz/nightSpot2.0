import { beatShape } from './util.js';

export function makeHeart(cfg) {
  const keys = cfg.bpm;
  const bpm = (t) => {
    if (t <= keys[0][0]) return keys[0][1];
    for (let i = 0; i < keys.length - 1; i++) {
      const [t0, a] = keys[i], [t1, b] = keys[i + 1];
      if (t <= t1) return a + (b - a) * ((t - t0) / (t1 - t0));
    }
    return keys[keys.length - 1][1];
  };
  const dt = 1 / 480, N = Math.ceil((cfg.duration + 5) / dt);
  const ph = new Float64Array(N + 1);
  let p = 0, started = false;
  for (let i = 0; i <= N; i++) {
    const t = i * dt, b = bpm(t);
    if (b > 0 && !started) { started = true; p = cfg.heartStartPhase; }
    ph[i] = p; p += (b / 60) * dt;
  }
  const phase = (t) => { const x = Math.max(0, t) / dt, i = Math.min(N - 1, Math.floor(x)), f = x - i; return ph[i] + (ph[i + 1] - ph[i]) * f; };
  const pulse = (t) => (bpm(t) > 0 ? Math.min(1, beatShape(phase(t))) : 0);
  return { bpm, phase, pulse };
}
