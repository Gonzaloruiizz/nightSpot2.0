import * as THREE from 'three';
import { clamp, lerp, smooth, ease, fbm1, vtrack, strack } from './util.js';

const V = (x, y, z) => new THREE.Vector3(x, y, z);

// Grading presets
const GRADE = {
  lab: { exposure: 1.0, contrast: 1.08, sat: 0.92, lift: [0.0, 0.004, 0.01], gamma: [0.98, 1.0, 1.03], gain: [1.0, 1.0, 1.02], shadowTint: [0.0, 0.025, 0.05], highTint: [0.03, 0.012, -0.01], bloom: 0.75, bloomRadius: 0.6, bloomThreshold: 0.8, streak: 0.4 },
  blood: { exposure: 0.85, contrast: 1.12, sat: 1.05, lift: [0.01, 0.0, 0.0], gamma: [1.02, 0.98, 0.98], gain: [1.03, 0.98, 0.98], shadowTint: [0.03, 0.0, 0.005], highTint: [0.03, 0.015, 0.0], bloom: 0.85, bloomRadius: 0.7, bloomThreshold: 0.9, streak: 0.45, streakTint: [0.4, 1.0, 0.9] },
  dna: { exposure: 1.05, contrast: 1.1, sat: 1.05, lift: [0.0, 0.0, 0.012], gamma: [1.0, 1.0, 1.02], gain: [1.02, 1.0, 1.0], shadowTint: [0.008, 0.0, 0.04], highTint: [0.035, 0.02, 0.0], bloom: 0.75, bloomRadius: 0.65, bloomThreshold: 0.85, streak: 0.4, streakTint: [0.5, 0.8, 1.0] },
};

export function makeShots({ lab, blood, dna, heart, cfg }) {
  const shake = (t, amp, seed, out) => {
    out.x += fbm1(t * 0.45, seed) * amp; out.y += fbm1(t * 0.4, seed + 11) * amp * 0.8; out.z += fbm1(t * 0.43, seed + 23) * amp;
    return out;
  };
  const tmpP = new THREE.Vector3(), tmpT = new THREE.Vector3();
  const inj = lab.injWorld, injN = lab.injNormal;
  const faceC = lab.objToWorld(V(0, 1.5, 2.0));
  const eyesC = lab.objToWorld(V(-0.05, 1.62, 1.9));

  const shots = {
    wide(t, u, cam) {
      vtrack([[0, [-4.9, 3.25, 5.1]], [8, [-3.1, 2.05, 3.7]]], t, ease.sine, tmpP);
      vtrack([[0, [0.6, 0.6, -0.8]], [8, [0.35, 1.0, -0.1]]], t, ease.sine, tmpT);
      shake(t, 0.015, 1, tmpP);
      cam.fov = lerp(42, 36, ease.sine(u));
      return { scene: lab.scene, lab: true, post: { ...GRADE.lab, focus: tmpP.distanceTo(tmpT), aperture: 6, fade: 1 - smooth(0.2, 2.6, t) } };
    },
    pod(t, u, cam) {
      vtrack([[8, [-0.45, 1.72, 1.12]], [14, [0.56, 1.6, 0.72]]], t, ease.sine, tmpP);
      vtrack([[8, [0.05, 1.05, 0.0]], [14, [0.82, 1.18, 0.0]]], t, ease.sine, tmpT);
      shake(t, 0.006, 2, tmpP);
      cam.fov = 30;
      return { scene: lab.scene, lab: true, post: { ...GRADE.lab, focus: tmpP.distanceTo(tmpT), aperture: 14, maxCoC: 20 } };
    },
    console(t, u, cam) {
      vtrack([[14, [2.1, 1.78, 3.4]], [20, [1.82, 1.68, 2.95]]], t, ease.sine, tmpP);
      vtrack([[14, [0.6, 1.05, 0.0]], [20, [0.55, 1.12, 0.0]]], t, ease.sine, tmpT);
      shake(t, 0.01, 3, tmpP);
      cam.fov = 34;
      return { scene: lab.scene, lab: true, post: { ...GRADE.lab, focus: tmpP.distanceTo(tmpT) * 0.95, aperture: 9 } };
    },
    robot(t, u, cam) {
      const tip = new THREE.Vector3(); lab.refs.robot.tip.getWorldPosition(tip);
      vtrack([[20, [0.3, 1.5, 2.35]], [24.5, [0.72, 1.42, 1.6]]], t, ease.sine, tmpP);
      tmpT.copy(tip).lerp(inj, 0.3 + 0.45 * smooth(20, 24, t));
      shake(t, 0.008, 4, tmpP);
      cam.fov = 42;
      return { scene: lab.scene, lab: true, post: { ...GRADE.lab, focus: tmpP.distanceTo(tip), aperture: 8 } };
    },
    inject(t, u, cam) {
      const side = V(0.55, 0.42, 0.0);
      const start = inj.clone().addScaledVector(injN, 0.24).addScaledVector(side, 0.28);
      const mid = inj.clone().addScaledVector(injN, 0.16).addScaledVector(side, 0.16);
      const end = inj.clone().addScaledVector(injN, 0.012);
      const k = ease.in(smooth(27.6, 29.5, t));
      tmpP.copy(start).lerp(mid, ease.sine(smooth(24.5, 27.6, t))).lerp(end, k);
      tmpT.copy(inj);
      shake(t, 0.002 * (1 - k), 5, tmpP);
      cam.fov = lerp(30, 50, k);
      return { scene: lab.scene, lab: true, post: { ...GRADE.lab, focus: tmpP.distanceTo(inj), aperture: 4, maxCoC: 22, zoomBlur: k * 0.25, flash: smooth(29.0, 29.5, t), flashColor: [0.6, 1.0, 0.92] } };
    },
    face(t, u, cam) {
      const a = lerp(-0.55, 0.25, ease.sine(u));
      const r = 0.42;
      tmpP.set(faceC.x - 0.12 + Math.sin(a) * 0.08, faceC.y + 0.30 - 0.04 * u, faceC.z + r * Math.cos(a) * 0.9);
      tmpT.copy(faceC).add(V(-0.02, 0.0, 0.0));
      shake(t, 0.003, 6, tmpP);
      cam.fov = lerp(34, 30, u);
      return { scene: lab.scene, lab: true, post: { ...GRADE.lab, focus: tmpP.distanceTo(tmpT), aperture: 5, flash: 1 - smooth(54, 54.6, t), flashColor: [0.9, 1.0, 1.0] } };
    },
    alarm(t, u, cam) {
      vtrack([[61, [-0.75, 1.55, 2.25]], [66, [-0.12, 1.42, 1.62]]], t, ease.sine, tmpP);
      vtrack([[61, [0.55, 1.1, 0.0]], [66, [0.72, 1.15, 0.0]]], t, ease.sine, tmpT);
      shake(t, 0.012 + 0.01 * smooth(62, 66, t), 7, tmpP);
      cam.fov = 38;
      const pulseR = 0.5 + 0.5 * Math.sin(t * 4.2 * 2);
      return { scene: lab.scene, lab: true, post: { ...GRADE.lab, sat: 1.0, shadowTint: [0.05 + 0.04 * pulseR, 0.0, 0.01], highTint: [0.05, 0.0, -0.01], focus: tmpP.distanceTo(tmpT) * 0.9, aperture: 8 } };
    },
    eyes(t, u, cam) {
      const k = ease.sine(u);
      tmpP.copy(eyesC).add(V(-0.06 - 0.03 * k, 0.24 - 0.1 * k, 0.03));
      tmpT.copy(eyesC);
      shake(t, 0.0015 + 0.004 * smooth(67.5, 69.3, t), 8, tmpP);
      cam.fov = 32;
      return { scene: lab.scene, lab: true, up: [1, 0, 0], post: { ...GRADE.lab, bloom: 0.55, focus: tmpP.distanceTo(tmpT), aperture: 4, flash: smooth(69.05, 69.35, t), flashColor: [0.85, 1.0, 1.0], fade: smooth(69.38, 69.5, t) } };
    },
    title(t, u, cam) {
      return { scene: null, post: { fade: 1 } };
    },
  };
  if (blood) Object.assign(shots, blood.shots(GRADE.blood, shake));
  if (dna) Object.assign(shots, dna.shots(GRADE.dna, shake));

  function at(t) {
    for (const [id, a, b] of cfg.shots) if (t >= a && t < b) return { id, a, b, u: (t - a) / (b - a) };
    const s = cfg.shots[cfg.shots.length - 1]; return { id: s[0], a: s[1], b: s[2], u: 1 };
  }
  return {
    at,
    setup(t, cam) {
      const s = at(t);
      const fn = shots[s.id] || shots.wide;
      cam.up.set(0, 1, 0);
      const r = fn(t, s.u, cam);
      if (r.scene && !r.camSet) { if (r.up) cam.up.fromArray(r.up); cam.position.copy(tmpP); cam.lookAt(tmpT); if (r.roll) cam.rotateZ(r.roll); }
      cam.updateProjectionMatrix();
      r.id = s.id; r.u = s.u;
      return r;
    },
    tmpP, tmpT,
  };
}
