import * as THREE from 'three';
import { NOISE } from './glsl.js';
import { mergeVertices } from 'three/addons/utils/BufferGeometryUtils.js';
import { Billboards } from './particles.js';
import { glowSprite } from './textures.js';
import { clamp, lerp, smooth, ease, rng, noise1, fbm1 } from './util.js';

// Inside the carotid: a pulsing vessel full of red blood cells, with the
// glowing Λ-9 nanocarriers streaming through.
export function buildBlood(renderer, heart) {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0a0001);
  const FOG = new THREE.Color(0x0c0002);
  scene.fog = new THREE.FogExp2(FOG, 0.06);
  const SERUM = new THREE.Color(0.25, 1.0, 0.82);

  // ---------------------------------------------------------------- path
  const pts = [];
  for (let k = 0; k <= 16; k++) pts.push(new THREE.Vector3(Math.sin(k * 0.55) * 5.5 + Math.sin(k * 1.3) * 1.2, Math.cos(k * 0.41) * 3.5, k * 9));
  const curve = new THREE.CatmullRomCurve3(pts, false, 'centripetal');
  const L = curve.getLength();
  const R = 3.2;
  const TUB = 700;
  const tubeGeo = new THREE.TubeGeometry(curve, TUB, R, 72, false);
  const frames = { T: tubeGeo.tangents, N: tubeGeo.normals, B: tubeGeo.binormals };
  const frameAt = (s, out) => {
    const f = clamp(s, 0, 1) * TUB, i = Math.min(TUB - 1, Math.floor(f)), u = f - i;
    out.T.copy(frames.T[i]).lerp(frames.T[i + 1], u).normalize();
    out.N.copy(frames.N[i]).lerp(frames.N[i + 1], u).normalize();
    out.B.copy(frames.B[i]).lerp(frames.B[i + 1], u).normalize();
    return out;
  };
  const F = { T: new THREE.Vector3(), N: new THREE.Vector3(), B: new THREE.Vector3() };

  // ---------------------------------------------------------------- vessel wall
  const wallU = {
    uTime: { value: 0 }, uPulse: { value: 0 }, uCam: { value: new THREE.Vector3() },
    uSwarm: { value: new THREE.Vector3() }, uSwarmI: { value: 1 }, uFog: { value: FOG }, uLen: { value: L },
  };
  const wall = new THREE.Mesh(tubeGeo, new THREE.ShaderMaterial({
    uniforms: wallU,
    vertexShader: /* glsl */`
      uniform float uTime, uPulse, uLen; varying vec3 vW; varying vec3 vN; varying vec2 vUv;
      ${NOISE}
      void main(){
        vUv = uv;
        float s = uv.x * uLen;
        float wave = uPulse * (0.55 + 0.45 * sin(s * 0.35 - uTime * 6.0));
        float bump = snoise(vec3(uv.x * 140.0, uv.y * 7.0, 0.0)) * 0.18 + snoise(vec3(uv.x * 600.0, uv.y * 28.0, 3.0)) * 0.05;
        vec3 p = position + normal * (wave * 0.35 + bump);
        vec4 w = modelMatrix * vec4(p, 1.0); vW = w.xyz; vN = normalize(mat3(modelMatrix) * normal);
        gl_Position = projectionMatrix * viewMatrix * w;
      }`,
    fragmentShader: /* glsl */`
      uniform float uTime, uPulse, uSwarmI; uniform vec3 uCam, uSwarm, uFog; varying vec3 vW; varying vec3 vN; varying vec2 vUv;
      ${NOISE}
      void main(){
        vec3 N = -normalize(vN);
        vec3 V = normalize(uCam - vW);
        vec2 q = vec2(vUv.x * 900.0, vUv.y * 40.0);
        vec3 vo = voronoi3(vec3(q * 0.55, 0.0));
        float cells = smoothstep(0.0, 0.18, vo.y - vo.x);
        float fib = snoise(vec3(vUv.x * 60.0, vUv.y * 24.0, 1.0)) * 0.5 + 0.5;
        float vessels = 1.0 - smoothstep(0.0, 0.06, abs(snoise(vec3(vUv.x * 90.0, vUv.y * 9.0, 7.0))));
        vec3 base = mix(vec3(0.22, 0.008, 0.015), vec3(0.6, 0.09, 0.08), fib * 0.6 + 0.2);
        base *= 0.55 + 0.45 * cells;
        base = mix(base, vec3(0.25, 0.0, 0.03), vessels * 0.6);
        float d = distance(uCam, vW);
        float lamp = max(dot(N, V), 0.0) / (1.0 + d * d * 0.03);
        float sss = pow(1.0 - max(dot(N, V), 0.0), 2.0) * 0.35;
        vec3 col = base * (lamp * 1.1 + 0.05) + vec3(0.35, 0.02, 0.02) * sss;
        float ds = distance(uSwarm, vW);
        vec3 Ls = normalize(uSwarm - vW);
        col += base * vec3(0.3, 1.0, 0.85) * max(dot(N, Ls), 0.0) * 9.0 * uSwarmI / (1.0 + ds * ds * 0.7);
        col *= 1.0 + uPulse * 0.25;
        float f = 1.0 - exp(-0.06 * 0.06 * d * d);
        gl_FragColor = vec4(mix(col, uFog, f), 1.0);
      }`,
    side: THREE.BackSide,
  }));
  scene.add(wall);

  // ---------------------------------------------------------------- red blood cells
  const prof = [];
  const RR = 0.48;
  for (let k = 0; k <= 24; k++) {
    const x = k / 24, h = RR * Math.sqrt(Math.max(0, 1 - x * x)) * (0.0518 + 2.0026 * x * x - 1.122 * x * x * x * x) * 1.15;
    prof.push(new THREE.Vector2(x * RR, h));
  }
  for (let k = 24; k >= 0; k--) { const p = prof[k]; prof.push(new THREE.Vector2(p.x, -p.y)); }
  const rbcGeo = new THREE.LatheGeometry(prof.map(p => new THREE.Vector2(Math.max(p.x, 0.0001), p.y)), 40);
  rbcGeo.rotateX(Math.PI / 2);
  const rbcMat = new THREE.MeshStandardMaterial({ color: 0x9a0a14, roughness: 0.42, metalness: 0.0, emissive: new THREE.Color(0.09, 0.0, 0.005) });
  const NRBC = 520;
  const rbc = new THREE.InstancedMesh(rbcGeo, rbcMat, NRBC);
  rbc.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
  scene.add(rbc);
  const r1 = rng(5);
  const rbcData = [];
  for (let i = 0; i < NRBC; i++) {
    const rr = Math.sqrt(r1()) * (R - 0.75);
    rbcData.push({ s0: r1(), th: r1() * Math.PI * 2, r: rr, v: 5.2 * (1 - (rr / R) ** 2) + 1.4, ax: new THREE.Vector3(r1() - 0.5, r1() - 0.5, r1() - 0.5).normalize(), w: (r1() - 0.5) * 3, ph: r1() * 6, sc: 0.85 + r1() * 0.3 });
  }

  // white blood cells & platelets
  let wbcGeo = new THREE.IcosahedronGeometry(1, 5); wbcGeo.deleteAttribute('normal'); wbcGeo.deleteAttribute('uv'); wbcGeo = mergeVertices(wbcGeo);
  { const p = wbcGeo.attributes.position; const v = new THREE.Vector3(); for (let i = 0; i < p.count; i++) { v.fromBufferAttribute(p, i); const n = 1 + 0.08 * Math.sin(v.x * 9) * Math.sin(v.y * 8) * Math.sin(v.z * 7) + 0.05 * Math.sin(v.x * 23 + v.y * 17); v.multiplyScalar(n); p.setXYZ(i, v.x, v.y, v.z); } wbcGeo.computeVertexNormals(); }
  const wbcMat = new THREE.MeshStandardMaterial({ color: 0xe8d6c8, roughness: 0.6, emissive: new THREE.Color(0.08, 0.03, 0.03) });
  const wbcs = [];
  for (let k = 0; k < 4; k++) { const m = new THREE.Mesh(wbcGeo, wbcMat); m.scale.setScalar(0.9 + k * 0.1); scene.add(m); wbcs.push({ m, s0: 0.12 + k * 0.11, th: k * 2.1 + 0.5 }); }
  const NPL = 90;
  const plt = new THREE.InstancedMesh(new THREE.SphereGeometry(0.12, 10, 8), new THREE.MeshStandardMaterial({ color: 0xe8c890, roughness: 0.5, emissive: new THREE.Color(0.1, 0.06, 0.02) }), NPL);
  scene.add(plt);
  const pltData = []; for (let i = 0; i < NPL; i++) pltData.push({ s0: r1(), th: r1() * 6.28, r: Math.sqrt(r1()) * (R - 0.4), v: 2.5 + r1(), ph: r1() * 6 });

  // ---------------------------------------------------------------- nanocarriers (the serum)
  const NNP = 240;
  const npGeo = new THREE.IcosahedronGeometry(1, 2);
  const npMat = new THREE.MeshBasicMaterial({ color: new THREE.Color(0.12, 1.0, 0.72).multiplyScalar(1.6) });
  const nps = new THREE.InstancedMesh(npGeo, npMat, NNP); nps.instanceMatrix.setUsage(THREE.DynamicDrawUsage); scene.add(nps);
  const glow = new Billboards(NNP + 12, { map: glowSprite(64), blending: THREE.AdditiveBlending, intensity: 1.0, nearFade: [0.05, 0.3] });
  scene.add(glow.mesh);
  const npData = [];
  const r2 = rng(17);
  for (let i = 0; i < NNP; i++) npData.push({ off: new THREE.Vector3((r2() - 0.5) * 2, (r2() - 0.5) * 2, (r2() - 0.5) * 2).normalize().multiplyScalar(Math.pow(r2(), 0.6)), ds: r2() * 9 - 2, sw: 0.5 + r2() * 1.5, ph: r2() * 6.28, sz: 0.045 + r2() * 0.07 });
  // hero capsules: core + geodesic shell
  const heroes = [];
  const shellGeo = new THREE.EdgesGeometry(new THREE.IcosahedronGeometry(1, 1));
  const shellMat = new THREE.LineBasicMaterial({ color: new THREE.Color(0.2, 1.0, 0.8).multiplyScalar(1.4), transparent: true, opacity: 0.9, blending: THREE.AdditiveBlending, depthWrite: false });
  const coreMat = new THREE.MeshStandardMaterial({ color: 0x0a3a30, emissive: new THREE.Color(0.1, 1.0, 0.7), emissiveIntensity: 1.1, roughness: 0.2, metalness: 0.3 });
  const spikeGeo = new THREE.ConeGeometry(0.08, 0.35, 8); spikeGeo.translate(0, 1.05, 0);
  const spikeMat = new THREE.MeshStandardMaterial({ color: 0x9ff5e0, emissive: SERUM, emissiveIntensity: 0.8, roughness: 0.3 });
  const ico = new THREE.IcosahedronGeometry(1, 0); const icoP = ico.attributes.position;
  for (let k = 0; k < 7; k++) {
    const g = new THREE.Group();
    const core = new THREE.Mesh(new THREE.IcosahedronGeometry(0.62, 3), coreMat); g.add(core);
    const shell = new THREE.LineSegments(shellGeo, shellMat); g.add(shell);
    const spikes = new THREE.Group();
    const seen = new Set();
    for (let i = 0; i < icoP.count; i++) {
      const v = new THREE.Vector3().fromBufferAttribute(icoP, i).normalize(); const key = v.toArray().map(x => x.toFixed(2)).join();
      if (seen.has(key)) continue; seen.add(key);
      const sp = new THREE.Mesh(spikeGeo, spikeMat); sp.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), v); spikes.add(sp);
    }
    g.add(spikes);
    scene.add(g);
    heroes.push({ g, shell, core, ds: [1.2, 2.6, 4.0, 5.5, 7.5, 9.5, 12][k], th: k * 1.7 + 0.4, r: [1.1, 1.6, 0.9, 1.8, 1.3, 2.0, 1.0][k], sc: [0.32, 0.26, 0.3, 0.22, 0.28, 0.24, 0.3][k] });
  }
  // plasma specks
  const specks = new Billboards(420, { map: glowSprite(32), blending: THREE.AdditiveBlending, intensity: 1.0, nearFade: [0.1, 0.5], fog: { color: FOG, density: 0.045 } });
  scene.add(specks.mesh);
  const r3 = rng(29); const speckData = []; for (let i = 0; i < 420; i++) speckData.push({ s0: r3(), th: r3() * 6.28, r: Math.sqrt(r3()) * (R - 0.2), v: 2 + r3() * 2, sz: 0.02 + r3() * 0.04 });

  // lights
  scene.add(new THREE.HemisphereLight(0xff5a4a, 0x220004, 0.35));
  const camLight = new THREE.PointLight(0xffc8b8, 3.5, 14, 1.4); scene.add(camLight);
  const swarmLight = new THREE.PointLight(0x40ffd0, 14, 10, 1.6); scene.add(swarmLight);
  const fillLight = new THREE.PointLight(0xff3020, 3, 12, 1.5); scene.add(fillLight);

  // ---------------------------------------------------------------- update
  const tmpD = new THREE.Vector3(); const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), sc = new THREE.Vector3(), pos = new THREE.Vector3(), basis = new THREE.Matrix4();
  const T0 = 29.5, T1 = 41;
  const sCam = (t) => 0.035 + 0.43 * ((t - T0) / (T1 - T0)) + 0.012 * Math.sin((t - T0) * 0.6);
  const pointAt = (s, th, r, out) => { frameAt(s, F); curve.getPointAt(clamp(s, 0, 1), out); return out.addScaledVector(F.N, Math.cos(th) * r).addScaledVector(F.B, Math.sin(th) * r); };

  function update(t, cam) {
    const pulse = heart.pulse(t);
    const bpmNow = heart.bpm(t);
    wallU.uTime.value = t; wallU.uPulse.value = pulse;
    // camera
    const s = sCam(t);
    const end = smooth(39.4, 41, t);
    frameAt(s, F);
    curve.getPointAt(s, cam.position);
    const bob = new THREE.Vector3().addScaledVector(F.N, 0.9 + fbm1(t * 0.3, 3) * 0.4).addScaledVector(F.B, 0.5 + fbm1(t * 0.27, 4) * 0.5);
    cam.position.add(bob);
    // red cells: Poiseuille flow + surge on each beat
    const surge = heart.phase(t) * 0.9;
    for (let i = 0; i < NRBC; i++) {
      const d = rbcData[i];
      const dist = d.v * (t - T0) + d.v * surge * 0.6;
      const sc0 = ((d.s0 + dist / L) % 1 + 1) % 1;
      pointAt(sc0, d.th + Math.sin(t * 0.3 + d.ph) * 0.2, d.r, pos);
      const dc = pos.distanceTo(cam.position);
      if (dc < 1.6) pos.add(tmpD.subVectors(pos, cam.position).normalize().multiplyScalar(1.6 - dc));
      q.setFromAxisAngle(d.ax, d.ph + t * d.w);
      sc.setScalar(d.sc);
      m4.compose(pos, q, sc); rbc.setMatrixAt(i, m4);
    }
    rbc.instanceMatrix.needsUpdate = true;
    for (let i = 0; i < NPL; i++) { const d = pltData[i]; const s = ((d.s0 + d.v * (t - T0) / L) % 1 + 1) % 1; pointAt(s, d.th, d.r, pos); q.setFromEuler(new THREE.Euler(t + d.ph, d.ph, 0)); sc.set(1, 0.35, 0.8); m4.compose(pos, q, sc); plt.setMatrixAt(i, m4); }
    plt.instanceMatrix.needsUpdate = true;
    for (const w of wbcs) { const sw = w.s0 + 0.6 * (t - T0) / L; pointAt(sw, w.th + t * 0.05, R - 1.15, w.m.position); const dc = w.m.position.distanceTo(cam.position); if (dc < 2.4) w.m.position.add(tmpD.subVectors(w.m.position, cam.position).normalize().multiplyScalar(2.4 - dc)); w.m.rotation.set(t * 0.3, t * 0.2 + w.th, 0); }

    // swarm centre ahead of the camera
    const sSw = s + (3.6 + 1.2 * Math.sin((t - T0) * 0.5)) / L;
    const swarm = pointAt(sSw, 0.6 + (t - T0) * 0.15, 0.6, new THREE.Vector3());
    // at the end the swarm and camera dive into the wall
    const wallPt = pointAt(s + 7 / L, 2.2, R + 0.6, new THREE.Vector3());
    swarm.lerp(wallPt, ease.in(end) * 0.9);
    const look = pointAt(s + 9 / L, 0.4, 0.4, new THREE.Vector3()).lerp(swarm, 0.45 + 0.5 * end);
    cam.position.lerp(wallPt, ease.in(smooth(39.8, 41, t)) * 0.85);
    cam.up.copy(F.N).applyAxisAngle(F.T, 0.25 * Math.sin((t - T0) * 0.25));
    cam.lookAt(look);
    cam.fov = 58 + 8 * end;
    wallU.uCam.value.copy(cam.position); wallU.uSwarm.value.copy(swarm);
    camLight.position.copy(cam.position); swarmLight.position.copy(swarm);
    swarmLight.intensity = 6 + 6 * pulse; wallU.uSwarmI.value = 0.5 + 0.5 * pulse;
    fillLight.position.copy(pointAt(s + 14 / L, 3, 1.5, pos));

    // nanocarriers swirl around the swarm centre
    frameAt(sSw, F);
    for (let i = 0; i < NNP; i++) {
      const d = npData[i];
      const a = t * d.sw + d.ph;
      const o = d.off;
      const lx = (o.x * Math.cos(a) - o.y * Math.sin(a)) * 1.9, ly = (o.x * Math.sin(a) + o.y * Math.cos(a)) * 1.9, lz = o.z * 2.8 + d.ds;
      pos.copy(swarm).addScaledVector(F.N, lx).addScaledVector(F.B, ly).addScaledVector(F.T, lz);
      // stretch towards the wall at the end
      pos.lerp(wallPt, ease.in(end) * (0.4 + 0.5 * ((i * 7) % 10) / 10));
      sc.setScalar(d.sz * (1 + 0.35 * pulse));
      m4.compose(pos, q.identity(), sc); nps.setMatrixAt(i, m4);
      glow.set(i, pos.x, pos.y, pos.z, d.sz * 7, 0.16, 0); glow.setTint(i, 0.1, 1.0, 0.75);
    }
    nps.instanceMatrix.needsUpdate = true;
    heroes.forEach((h, k) => {
      const sh = s + (h.ds + 0.6 * Math.sin(t * 0.7 + k)) / L;
      pointAt(sh, h.th + t * 0.25, h.r, h.g.position);
      h.g.position.lerp(wallPt, ease.in(end) * 0.7);
      h.g.scale.setScalar(h.sc * (1 + 0.08 * pulse));
      h.g.rotation.set(t * 0.6 + k, t * 0.4 + k * 2, 0);
      h.shell.scale.setScalar(1.35 + 0.05 * Math.sin(t * 3 + k));
      const p = h.g.position; glow.set(NNP + k, p.x, p.y, p.z, h.sc * 6, 0.22, 0); glow.setTint(NNP + k, 0.1, 1.0, 0.75);
    });
    glow.commit();
    for (let i = 0; i < specks.count; i++) {
      const d = speckData[i]; const ss = ((d.s0 + d.v * (t - T0) / L) % 1 + 1) % 1;
      pointAt(ss, d.th, d.r, pos); specks.set(i, pos.x, pos.y, pos.z, d.sz, 0.35, 0); specks.setTint(i, 1.0, 0.45, 0.3);
    }
    specks.commit();
    return { swarm };
  }

  function shots(grade) {
    return {
      blood(t, u, cam) {
        return {
          scene, camSet: true, near: 0.03, far: 70,
          update: (tt, c) => update(tt, c),
          post: { ...grade, focus: 3.6, aperture: 3.0, maxCoC: 14, flash: Math.max(1 - smooth(29.5, 30.4, t), smooth(40.6, 41, t)), flashColor: [0.7, 1.0, 0.9], zoomBlur: smooth(39.8, 41, t) * 0.3 + (1 - smooth(29.5, 30.2, t)) * 0.25 },
        };
      },
    };
  }
  return { scene, update, shots };
}
