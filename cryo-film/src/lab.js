import * as THREE from 'three';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';
import * as SkeletonUtils from 'three/addons/utils/SkeletonUtils.js';
import { makeSkinMaterial } from './skin.js';
import { Billboards } from './particles.js';
import { NOISE } from './glsl.js';
import { wallTextures, floorTextures, quiltTexture, noiseTexture, smokePuff, glowSprite, screenCanvas } from './textures.js';
import { clamp, lerp, smooth, ease, rng, noise1, fbm1, vtrack } from './util.js';

const S_BODY = 0.052;                 // Lee Perry Smith object units -> meters
const BUST_POS = new THREE.Vector3(0.744, 1.085, 0);
const BED_Y = 0.95;
const SERUM = new THREE.Color(0.25, 1.0, 0.82);

// object space (LPS) -> world
function objToWorld(p) { return new THREE.Vector3(BUST_POS.x + p.y * S_BODY, BUST_POS.y + p.z * S_BODY, p.x * S_BODY); }
function dirToWorld(n) { return new THREE.Vector3(n.y, n.z, n.x).normalize(); }

function std(color, rough = 0.5, metal = 0, extra = {}) {
  return new THREE.MeshStandardMaterial({ color, roughness: rough, metalness: metal, ...extra });
}

// Emissive stripes travelling along TubeGeometry u-coordinate
function pulseCableMaterial(base, glow, speed, freq, width = 0.08) {
  const m = std(base, 0.45, 0.3);
  m.defines = { USE_UV: '' };
  m.userData.U = { uTime: { value: 0 }, uGlow: { value: new THREE.Color(glow) }, uAmp: { value: 1 } };
  m.onBeforeCompile = (sh) => {
    Object.assign(sh.uniforms, m.userData.U);
    sh.fragmentShader = sh.fragmentShader
      .replace('#include <common>', '#include <common>\nuniform float uTime; uniform vec3 uGlow; uniform float uAmp;')
      .replace('#include <emissivemap_fragment>', `#include <emissivemap_fragment>
        float ph = fract(vUv.x*${freq.toFixed(2)} - uTime*${speed.toFixed(2)});
        float band = smoothstep(${width.toFixed(3)}, 0.0, abs(ph-0.5)) ;
        totalEmissiveRadiance += uGlow * (band*2.5 + 0.08) * uAmp;`);
  };
  m.customProgramCacheKey = () => `pulse-${freq}-${speed}-${width}`;
  return m;
}

function tube(points, radius, mat, seg = 64, radial = 8) {
  const curve = new THREE.CatmullRomCurve3(points, false, 'catmullrom', 0.5);
  const m = new THREE.Mesh(new THREE.TubeGeometry(curve, seg, radius, radial, false), mat);
  m.castShadow = true; m.receiveShadow = true;
  return m;
}

function buildEnvironment(renderer) {
  const env = new THREE.Scene();
  const room = new THREE.Mesh(new THREE.BoxGeometry(20, 8, 20), new THREE.MeshBasicMaterial({ color: 0x0b131c, side: THREE.BackSide }));
  room.position.y = 3; env.add(room);
  const panel = (w, h, color, pos, rot) => {
    const m = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({ color, side: THREE.DoubleSide }));
    m.position.set(...pos); if (rot) m.rotation.set(...rot); env.add(m);
  };
  for (let i = -2; i <= 2; i++) panel(0.6, 6, new THREE.Color(0.9, 1.1, 1.3).multiplyScalar(2.2), [i * 2.2, 6.9, 0], [Math.PI / 2, 0, 0]);
  panel(6, 1.2, new THREE.Color(0.1, 0.6, 0.9).multiplyScalar(1.5), [0, 1.5, -9.9]);
  panel(4, 0.8, new THREE.Color(0.1, 0.5, 0.8).multiplyScalar(1.2), [9.9, 2.0, 0], [0, Math.PI / 2, 0]);
  panel(1.5, 0.6, new THREE.Color(1.0, 0.5, 0.2).multiplyScalar(1.5), [-9.9, 1.6, 3], [0, Math.PI / 2, 0]);
  const pm = new THREE.PMREMGenerator(renderer);
  const tex = pm.fromScene(env, 0.035).texture;
  pm.dispose();
  return tex;
}

// ---------------------------------------------------------------- glass lid
function glassMaterial() {
  return new THREE.ShaderMaterial({
    uniforms: { uTime: { value: 0 }, uFrost: { value: 1 }, uKey: { value: new THREE.Vector3(0.2, 4, 0.3) } },
    vertexShader: /* glsl */`
      varying vec3 vW; varying vec3 vN; varying vec3 vL;
      void main(){ vec4 w = modelMatrix*vec4(position,1.0); vW=w.xyz; vL=position; vN=normalize(mat3(modelMatrix)*normal); gl_Position=projectionMatrix*viewMatrix*w; }`,
    fragmentShader: /* glsl */`
      uniform float uTime, uFrost; uniform vec3 uKey;
      varying vec3 vW; varying vec3 vN; varying vec3 vL;
      ${NOISE}
      float ridge(vec3 p){ return 1.0 - abs(snoise(p)); }
      void main(){
        vec3 V = normalize(cameraPosition - vW);
        vec3 N = normalize(vN); if (dot(N,V) < 0.0) N = -N;
        float fres = pow(1.0 - max(dot(N,V),0.0), 4.0);
        vec3 R = reflect(-V, N);
        float strips = smoothstep(0.55, 0.85, R.y) * smoothstep(0.3, 0.9, sin(R.x*7.0 + R.z*2.0)*0.5+0.5);
        float hl = pow(max(dot(R, normalize(uKey - vW)), 0.0), 400.0);
        // frost: grows from the rim (low y) and the ends (|x| large); fern-like ridges
        float h = clamp(vL.y / 0.6, 0.0, 1.0);
        float ends = smoothstep(0.9, 1.2, abs(vL.x)) * 0.35;
        float haze = fbm3(vL*3.5);
        float mask = clamp(smoothstep(0.55, 0.0, h + haze*0.35) + ends*0.8, 0.0, 1.0) * uFrost;
        float fern = pow(ridge(vL*19.0), 10.0)*0.45 + pow(ridge(vL*47.0 + 4.0), 12.0)*0.35;
        float frost = mask * (0.3 + fern);
        float light = 0.45 + 0.55 * max(N.y, 0.0);
        vec3 col = vec3(0.5,0.72,0.95) * strips * 0.7 + vec3(0.9,0.97,1.0) * hl * 2.5;
        col += vec3(0.72,0.84,0.95) * frost * light * 0.55;
        float cond = (haze*0.5+0.5);
        col += vec3(0.6,0.75,0.9) * cond * 0.08 * uFrost;
        float a = 0.05 + fres*0.3 + strips*0.14 + frost*0.7 + hl*0.5 + cond*0.07*uFrost;
        gl_FragColor = vec4(col, clamp(a, 0.0, 0.92));
      }`,
    transparent: true, depthWrite: false, side: THREE.DoubleSide,
  });
}

// ---------------------------------------------------------------- sheet
function buildSheet(bust, mat) {
  const ray = new THREE.Raycaster();
  const down = new THREE.Vector3(0, -1, 0);
  const halfW = 0.40, xMin = -1.06, xMax = 0.69;
  const xEdge = (z) => 0.608 + 0.052 * smooth(0.07, 0.19, Math.abs(z));
  const NX = 170, NZ = 81;
  const dx = (xMax - xMin) / (NX - 1), dz = (2 * halfW) / (NZ - 1);
  const torso = [[0.69, 0.19, 0.18], [0.45, 0.20, 0.175], [0.3, 0.17, 0.158], [0.18, 0.155, 0.15], [0.05, 0.15, 0.168], [-0.08, 0.14, 0.17], [-0.13, 0.10, 0.15]];
  const torsoAt = (x) => {
    if (x > torso[0][0] || x < torso[torso.length - 1][0]) return null;
    for (let i = 0; i < torso.length - 1; i++) {
      const a = torso[i], b = torso[i + 1];
      if (x <= a[0] && x >= b[0]) { const u = (a[0] - x) / (a[0] - b[0]); return [lerp(a[1], b[1], u), lerp(a[2], b[2], u)]; }
    }
    return null;
  };
  const caps = [];
  for (const s of [-1, 1]) {
    caps.push([0.53, 0.215 * s, 0.25, 0.235 * s, 0.048]);
    caps.push([0.25, 0.235 * s, 0.0, 0.24 * s, 0.04]);
    caps.push([-0.02, 0.238 * s, -0.14, 0.232 * s, 0.03]);
    caps.push([-0.02, 0.09 * s, -0.42, 0.082 * s, 0.075]);
    caps.push([-0.42, 0.082 * s, -0.77, 0.078 * s, 0.052]);
  }
  const capTop = (x, z, c) => {
    const [ax, az, bx, bz, r] = c; const vx = bx - ax, vz = bz - az;
    const u = clamp(((x - ax) * vx + (z - az) * vz) / (vx * vx + vz * vz));
    const px = ax + vx * u - x, pz = az + vz * u - z, d2 = px * px + pz * pz;
    return d2 < r * r ? BED_Y + r + Math.sqrt(r * r - d2) : BED_Y;
  };
  bust.updateMatrixWorld(true);
  const H = new Float32Array(NX * NZ);
  for (let i = 0; i < NX; i++) for (let j = 0; j < NZ; j++) {
    const x = xMin + i * dx, z = -halfW + j * dz;
    let h = BED_Y;
    const tr = torsoAt(x);
    if (tr) { const [th, tw] = tr; const q = z / tw; if (Math.abs(q) < 1) h = Math.max(h, BED_Y + th * (0.5 + 0.5 * Math.sqrt(1 - q * q))); }
    for (const c of caps) h = Math.max(h, capTop(x, z, c));
    for (const s of [-1, 1]) { // feet pointing up
      const ddx = (x + 0.8) / 0.055, ddz = (z - 0.085 * s) / 0.048, d2 = ddx * ddx + ddz * ddz;
      if (d2 < 1) h = Math.max(h, BED_Y + 0.12 + 0.085 * Math.sqrt(1 - d2));
    }
    if (x > 0.5) {
      ray.set(new THREE.Vector3(x, 2, z), down);
      const hit = ray.intersectObject(bust, true)[0];
      if (hit) h = Math.max(h, hit.point.y);
    }
    H[i * NZ + j] = h;
  }
  const blur = (src, sig) => {
    const r = Math.ceil(sig * 2.5), w = []; let s = 0;
    for (let k = -r; k <= r; k++) { const v = Math.exp(-(k * k) / (2 * sig * sig)); w.push(v); s += v; }
    for (let k = 0; k < w.length; k++) w[k] /= s;
    const tmp = new Float32Array(src.length), out = new Float32Array(src.length);
    for (let i = 0; i < NX; i++) for (let j = 0; j < NZ; j++) { let a = 0; for (let k = -r; k <= r; k++) a += w[k + r] * src[clamp(i + k, 0, NX - 1) * NZ + j]; tmp[i * NZ + j] = a; }
    for (let i = 0; i < NX; i++) for (let j = 0; j < NZ; j++) { let a = 0; for (let k = -r; k <= r; k++) a += w[k + r] * tmp[i * NZ + clamp(j + k, 0, NZ - 1)]; out[i * NZ + j] = a; }
    return out;
  };
  const B1 = blur(H, 3.2);
  const C = new Float32Array(H.length);
  for (let k = 0; k < H.length; k++) C[k] = Math.max(B1[k], H[k] - 0.003);
  const C2 = blur(C, 1.2);

  // Build surface: central part (heightfield) + side drapes + foot drape
  const SIDE = 14, cols = NZ + 2 * SIDE;
  const pos = [], uv = [], bodyW = [], idx = [];
  const r = rng(77);
  const wrinkle = (x, z) => 0.0035 * Math.sin(x * 38 + Math.sin(z * 9) * 2.0) * (0.5 + 0.5 * Math.sin(z * 13 + x * 4));
  const sampleC = (x, j) => { const fi = clamp((x - xMin) / dx, 0, NX - 1.001), i0 = Math.floor(fi), f = fi - i0; return C2[i0 * NZ + j] * (1 - f) + C2[(i0 + 1) * NZ + j] * f; };
  const sampleH = (x, j) => { const fi = clamp((x - xMin) / dx, 0, NX - 1.001), i0 = Math.floor(fi), f = fi - i0; return H[i0 * NZ + j] * (1 - f) + H[(i0 + 1) * NZ + j] * f; };
  for (let i = 0; i < NX; i++) {
    const ui = i / (NX - 1);
    for (let c = 0; c < cols; c++) {
      let px, py, pz, w = 0;
      const jj = clamp(c - SIDE, 0, NZ - 1), zc = -halfW + jj * dz;
      const x = xMin + ui * (xEdge(zc) - xMin);
      if (c < SIDE || c >= SIDE + NZ) {
        const side = c < SIDE ? -1 : 1;
        const k = c < SIDE ? SIDE - c : c - (SIDE + NZ - 1); // 1..SIDE
        const top = sampleC(x, jj) + 0.006;
        const drop = k * 0.012;
        const bend = Math.min(k, 3) / 3;
        py = top - drop * bend;
        pz = side * (halfW + 0.006 + 0.012 * bend + 0.006 * Math.sin(x * 21 + k * 0.2) * (k / SIDE));
        px = x + 0.004 * Math.sin(x * 30) * (k / SIDE);
      } else {
        py = sampleC(x, jj) + 0.006 + wrinkle(x, zc);
        pz = zc; px = x;
        w = clamp((sampleH(x, jj) - BED_Y) / 0.05);
      }
      if (x < -0.98) py -= (x + 0.98) * (x + 0.98) * 14;
      pos.push(px, py, pz); uv.push(c / (cols - 1), ui); bodyW.push(w);
    }
  }
  for (let i = 0; i < NX - 1; i++) for (let c = 0; c < cols - 1; c++) {
    const a = i * cols + c, b = a + 1, d = a + cols, e = d + 1;
    idx.push(a, d, b, b, d, e);
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
  g.setAttribute('bodyW', new THREE.Float32BufferAttribute(bodyW, 1));
  g.setIndex(idx); g.computeVertexNormals();
  const mesh = new THREE.Mesh(g, mat);
  mesh.castShadow = true; mesh.receiveShadow = true;
  // hem along the top edge
  const hemPts = [];
  for (let c = 0; c < cols; c += 3) { const k = (NX - 1) * cols + c; hemPts.push(new THREE.Vector3(pos[k * 3] + 0.004, pos[k * 3 + 1] + 0.002, pos[k * 3 + 2])); }
  const hem = new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(hemPts), 80, 0.008, 8), mat);
  hem.castShadow = true;
  return { mesh, hem };
}

function sheetMaterial() {
  const tex = quiltTexture(512); tex.repeat.set(3, 5);
  const m = std(0x8797a5, 0.85, 0.0, { map: tex });
  m.userData.U = { uWrithe: { value: 0 }, uBreath: { value: 0 }, uTime: { value: 0 } };
  m.onBeforeCompile = (sh) => {
    Object.assign(sh.uniforms, m.userData.U);
    sh.vertexShader = sh.vertexShader
      .replace('#include <common>', '#include <common>\nattribute float bodyW; uniform float uWrithe, uBreath, uTime;')
      .replace('#include <begin_vertex>', `#include <begin_vertex>
        {
          vec2 p = position.xz;
          float chest = exp(-pow((p.x-0.42)/0.14,2.0) - pow(p.y/0.16,2.0));
          float br = uBreath * chest * 0.018;
          float w = 0.0;
          w += exp(-pow((p.x-0.30-0.05*sin(uTime*2.3))/0.10,2.0) - pow((p.y-0.06)/0.09,2.0)) * (0.5+0.5*sin(uTime*7.0));
          w += exp(-pow((p.x+0.06)/0.09,2.0) - pow((abs(p.y)-0.235)/0.06,2.0)) * (0.5+0.5*sin(uTime*11.0+1.3));
          w += exp(-pow((p.x+0.55)/0.18,2.0) - pow((abs(p.y)-0.08)/0.1,2.0)) * (0.5+0.5*sin(uTime*5.0+2.1));
          transformed.y += bodyW * (br + uWrithe * w * 0.03);
        }`);
  };
  m.customProgramCacheKey = () => 'sheet-v1';
  return m;
}

// ---------------------------------------------------------------- robot arm
function buildRobot() {
  const white = std(0xd5dbe1, 0.32, 0.25); white.name = 'RobotWhite';
  const dark = std(0x16191d, 0.45, 0.6); dark.name = 'RobotDark';
  const orange = std(0xff7a1a, 0.4, 0.1, { emissive: new THREE.Color(0xff5a00), emissiveIntensity: 0.25 });
  const L1 = 1.2, L2 = 1.1;
  const root = new THREE.Group();
  const mount = new THREE.Mesh(new THREE.CylinderGeometry(0.26, 0.26, 0.08, 32), dark); mount.position.y = -0.04; root.add(mount);
  const yaw = new THREE.Group(); root.add(yaw);
  const hub = new THREE.Mesh(new THREE.CylinderGeometry(0.18, 0.2, 0.18, 32), white); hub.position.y = -0.17; yaw.add(hub);
  const ring = new THREE.Mesh(new THREE.TorusGeometry(0.19, 0.012, 8, 40), orange); ring.rotation.x = Math.PI / 2; ring.position.y = -0.26; yaw.add(ring);
  const col = new THREE.Mesh(new THREE.CylinderGeometry(0.1, 0.12, 0.55, 24), white); col.position.y = -0.53; yaw.add(col);
  const shoulder = new THREE.Group(); shoulder.position.y = -0.75; yaw.add(shoulder);
  const sj = new THREE.Mesh(new THREE.CylinderGeometry(0.15, 0.15, 0.32, 32), dark); sj.rotation.x = Math.PI / 2; shoulder.add(sj);
  const sjr = new THREE.Mesh(new THREE.TorusGeometry(0.151, 0.01, 8, 40), orange); sjr.position.z = 0.1; shoulder.add(sjr);
  const upper = new THREE.Mesh(new RoundedBoxGeometry(L1, 0.2, 0.17, 3, 0.06), white); upper.position.x = L1 / 2; upper.castShadow = true; shoulder.add(upper);
  const stripe = new THREE.Mesh(new THREE.BoxGeometry(L1 * 0.6, 0.03, 0.175), dark); stripe.position.set(L1 / 2, 0.04, 0); shoulder.add(stripe);
  const elbow = new THREE.Group(); elbow.position.x = L1; shoulder.add(elbow);
  const ej = new THREE.Mesh(new THREE.CylinderGeometry(0.11, 0.11, 0.26, 32), dark); ej.rotation.x = Math.PI / 2; elbow.add(ej);
  const ejr = new THREE.Mesh(new THREE.TorusGeometry(0.111, 0.009, 8, 40), orange); ejr.position.z = 0.08; elbow.add(ejr);
  const fore = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.085, L2, 24), white); fore.rotation.z = -Math.PI / 2; fore.position.x = L2 / 2; fore.castShadow = true; elbow.add(fore);
  const wrist = new THREE.Group(); wrist.position.x = L2; elbow.add(wrist);
  const wj = new THREE.Mesh(new THREE.SphereGeometry(0.075, 24, 16), dark); wrist.add(wj);
  // injector tool (points along +x)
  const tool = new THREE.Group(); tool.name = 'RobotTool'; wrist.add(tool);
  const housing = new THREE.Mesh(new THREE.CylinderGeometry(0.055, 0.06, 0.16, 24), white); housing.rotation.z = -Math.PI / 2; housing.position.x = 0.13; tool.add(housing);
  const hr = new THREE.Mesh(new THREE.TorusGeometry(0.057, 0.006, 8, 30), orange); hr.rotation.y = Math.PI / 2; hr.position.x = 0.2; tool.add(hr);
  const vialGlass = new THREE.Mesh(new THREE.CylinderGeometry(0.042, 0.042, 0.15, 24, 1, true),
    new THREE.MeshStandardMaterial({ color: 0xbfe8ff, roughness: 0.05, metalness: 0.1, transparent: true, opacity: 0.25, depthWrite: false }));
  vialGlass.rotation.z = -Math.PI / 2; vialGlass.position.x = 0.285; tool.add(vialGlass);
  const fluidMat = new THREE.MeshStandardMaterial({ color: 0x0a2a22, emissive: SERUM, emissiveIntensity: 3.0, roughness: 0.2 }); fluidMat.name = 'Serum';
  const fluid = new THREE.Mesh(new THREE.CylinderGeometry(0.036, 0.036, 1, 20), fluidMat); fluid.name = 'SerumFluid';
  fluid.rotation.z = -Math.PI / 2; tool.add(fluid);
  const cage = new THREE.Group(); tool.add(cage);
  for (let k = 0; k < 4; k++) { const b = new THREE.Mesh(new THREE.BoxGeometry(0.15, 0.008, 0.008), dark); const a = k * Math.PI / 2 + 0.4; b.position.set(0.285, Math.cos(a) * 0.046, Math.sin(a) * 0.046); cage.add(b); }
  const nozzle = new THREE.Mesh(new THREE.CylinderGeometry(0.012, 0.045, 0.05, 24), dark); nozzle.rotation.z = -Math.PI / 2; nozzle.position.x = 0.385; tool.add(nozzle);
  const needle = new THREE.Mesh(new THREE.CylinderGeometry(0.0015, 0.0022, 0.06, 8), std(0xeeeeee, 0.1, 1.0)); needle.rotation.z = -Math.PI / 2; needle.position.x = 0.44; tool.add(needle);
  const tip = new THREE.Object3D(); tip.position.x = 0.47; tool.add(tip);
  const light = new THREE.PointLight(SERUM, 0.05, 0.6, 2); light.position.x = 0.29; tool.add(light);
  root.traverse(o => { if (o.isMesh) { o.castShadow = true; } });
  const TOOL_LEN = 0.47;
  const tmpQ = new THREE.Quaternion(), tmpQ2 = new THREE.Quaternion(), X = new THREE.Vector3(1, 0, 0);
  function solve(tipTarget, dir, serumLevel) {
    root.updateMatrixWorld(true);
    const W = tipTarget.clone().addScaledVector(dir, -TOOL_LEN);
    const S = new THREE.Vector3(); shoulder.getWorldPosition(S);
    const d = W.clone().sub(S);
    const psi = Math.atan2(-d.z, d.x);
    yaw.rotation.y = psi;
    const rr = Math.hypot(d.x, d.z), hh = d.y;
    let D = (rr * rr + hh * hh - L1 * L1 - L2 * L2) / (2 * L1 * L2);
    D = clamp(D, -1, 1);
    const a2 = -Math.acos(D);
    const a1 = Math.atan2(hh, rr) - Math.atan2(L2 * Math.sin(a2), L1 + L2 * Math.cos(a2));
    shoulder.rotation.z = a1;
    elbow.rotation.z = a2;
    wrist.rotation.z = 0;
    root.updateMatrixWorld(true);
    wrist.getWorldQuaternion(tmpQ);
    tmpQ2.setFromUnitVectors(X, dir.clone().normalize());
    tool.quaternion.copy(tmpQ.invert().multiply(tmpQ2));
    // fluid level
    const len = 0.14 * Math.max(0.02, serumLevel);
    fluid.scale.set(1, len, 1); fluid.position.x = 0.36 - len / 2;
    fluidMat.emissiveIntensity = 0.9 + serumLevel * 0.9;
    light.intensity = 0.01 + serumLevel * 0.03;
  }
  return { root, solve, tip, light, fluidMat };
}

// ---------------------------------------------------------------- scientists
function prepareScientist(src, suitMat, jointMat, visorMat, gownMat) {
  const o = SkeletonUtils.clone(src);
  o.traverse(m => {
    if (m.isMesh) {
      m.castShadow = true; m.receiveShadow = true; m.frustumCulled = false;
      m.material = m.name.includes('Joints') ? jointMat : suitMat;
    }
  });
  const head = o.getObjectByName('mixamorigHead');
  if (head && visorMat) {
    const hood = new THREE.Mesh(new THREE.SphereGeometry(13.5, 32, 24), suitMat);
    hood.scale.set(1.0, 1.18, 1.08); hood.position.set(0, 9, -1.5); head.add(hood);
    const visor = new THREE.Mesh(new THREE.SphereGeometry(13.9, 40, 24, Math.PI * 0.12, Math.PI * 0.76, Math.PI * 0.28, Math.PI * 0.34), visorMat);
    visor.scale.set(1.0, 1.18, 1.08); visor.position.set(0, 9, -1.0); head.add(visor);
    const lamp = new THREE.Mesh(new THREE.SphereGeometry(1.1, 8, 8), new THREE.MeshBasicMaterial({ color: new THREE.Color(0.4, 1.4, 1.6) }));
    lamp.position.set(10, 20, 7); head.add(lamp);
  }
  const spine = o.getObjectByName('mixamorigSpine2');
  if (spine && visorMat) {
    const pack = new THREE.Mesh(new RoundedBoxGeometry(26, 30, 12, 2, 4), jointMat); pack.position.set(0, 8, -16); spine.add(pack);
    const badge = new THREE.Mesh(new THREE.BoxGeometry(5, 2, 1), new THREE.MeshBasicMaterial({ color: new THREE.Color(0.3, 1.3, 1.5) })); badge.position.set(8, 10, 12); spine.add(badge);
  }
  const hips = o.getObjectByName('mixamorigHips');
  if (hips && gownMat) {
    const prof = [[15.5, 22], [16.5, 10], [18.5, -8], [21.5, -30], [24.5, -50], [24.0, -51.5]].map(([r, y]) => new THREE.Vector2(r, y));
    const gown = new THREE.Mesh(new THREE.LatheGeometry(prof, 40), gownMat); gown.castShadow = true; hips.add(gown);
  }
  return o;
}

// ---------------------------------------------------------------- screens
function drawECG(sc, t, heart, mode) {
  const { ctx: g, canvas: c } = sc; const W = c.width, H = c.height;
  g.fillStyle = '#020a0e'; g.fillRect(0, 0, W, H);
  g.strokeStyle = 'rgba(40,120,140,0.25)'; g.lineWidth = 1;
  for (let x = 0; x < W; x += 32) { g.beginPath(); g.moveTo(x, 0); g.lineTo(x, H); g.stroke(); }
  for (let y = 0; y < H; y += 32) { g.beginPath(); g.moveTo(0, y); g.lineTo(W, y); g.stroke(); }
  const bpm = heart.bpm(t);
  const alarm = mode === 'alarm';
  g.lineWidth = 3; g.strokeStyle = alarm ? '#ff5a4a' : '#5dffc8'; g.shadowColor = g.strokeStyle; g.shadowBlur = 10;
  g.beginPath();
  const span = 4.0;
  for (let x = 0; x <= W; x += 2) {
    const tt = t - span + (x / W) * span;
    let y = 0;
    if (heart.bpm(tt) > 0) {
      const ph = heart.phase(tt); const f = ph - Math.floor(ph);
      y = Math.exp(-Math.pow((f - 0.12) / 0.012, 2)) * 1.0 - Math.exp(-Math.pow((f - 0.15) / 0.012, 2)) * 0.35
        + 0.18 * Math.exp(-Math.pow((f - 0.4) / 0.05, 2)) + 0.08 * Math.exp(-Math.pow((f - 0.03) / 0.02, 2));
    }
    y += Math.sin(tt * 37) * 0.01;
    const py = H * 0.55 - y * H * 0.35;
    if (x === 0) g.moveTo(x, py); else g.lineTo(x, py);
  }
  g.stroke(); g.shadowBlur = 0;
  g.fillStyle = alarm ? '#ff6a5a' : '#7fffd8'; g.font = '28px ShareTech, monospace';
  g.fillText(bpm > 0 ? `${Math.round(bpm)} LPM` : 'SIN PULSO', 16, 36);
  g.font = '18px ShareTech, monospace'; g.fillStyle = 'rgba(160,230,255,0.8)';
  g.fillText('ECG · DERIV. II', W - 170, 30);
  if (alarm && Math.floor(t * 3) % 2 === 0) { g.fillStyle = 'rgba(255,60,40,0.85)'; g.fillRect(0, H - 34, W, 34); g.fillStyle = '#fff'; g.font = '22px ShareTech, monospace'; g.fillText('ALERTA · ANOMALÍA GENÉTICA', 16, H - 10); }
  sc.tex.needsUpdate = true;
}

function drawDNA(sc, t, progress) {
  const { ctx: g, canvas: c } = sc; const W = c.width, H = c.height;
  g.fillStyle = '#03080f'; g.fillRect(0, 0, W, H);
  const r = rng(Math.floor(t * 6) + 3);
  g.font = '17px ShareTech, monospace';
  const bases = 'ACGT';
  for (let row = 0; row < 9; row++) {
    let s = ''; for (let k = 0; k < 30; k++) s += bases[Math.floor(r() * 4)];
    const mutated = row / 9 < progress;
    g.fillStyle = mutated ? 'rgba(90,255,200,0.95)' : 'rgba(110,170,230,0.75)';
    g.fillText(s, 14, 30 + row * 22);
  }
  g.fillStyle = 'rgba(120,200,255,0.9)'; g.font = '20px ShareTech, monospace';
  g.fillText('SECUENCIA · CROM. 17', 14, H - 44);
  g.strokeStyle = 'rgba(120,200,255,0.6)'; g.strokeRect(14, H - 30, W - 28, 14);
  g.fillStyle = '#5dffc8'; g.fillRect(16, H - 28, (W - 32) * progress, 10);
  sc.tex.needsUpdate = true;
}

function drawTemp(sc, t, temp, label) {
  const { ctx: g, canvas: c } = sc; const W = c.width, H = c.height;
  g.fillStyle = '#020910'; g.fillRect(0, 0, W, H);
  g.fillStyle = 'rgba(120,200,255,0.85)'; g.font = '20px ShareTech, monospace';
  g.fillText(label, 16, 32);
  g.fillStyle = temp < -100 ? '#8fd8ff' : temp < 20 ? '#ffd27a' : '#ff8a5a';
  g.font = '64px ShareTech, monospace';
  const s = (temp >= 0 ? '+' : '−') + Math.abs(temp).toFixed(1).replace('.', ',') + '°C';
  g.fillText(s, 16, 110);
  g.fillStyle = 'rgba(120,200,255,0.5)'; g.fillRect(16, 130, W - 32, 2);
  g.font = '16px ShareTech, monospace'; g.fillStyle = 'rgba(160,220,255,0.75)';
  g.fillText('N2 LÍQ. · PRESIÓN 1,02 bar', 16, 160);
  g.fillText('SUJETO K-17 · CRIOSTASIS', 16, 184);
  sc.tex.needsUpdate = true;
}

function screenMesh(sc, w, h, boost = 1.6) {
  const m = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({ map: sc.tex, color: new THREE.Color(boost, boost, boost), toneMapped: false }));
  return m;
}

// ---------------------------------------------------------------- hologram helix
function buildHolo() {
  const g = new THREE.Group();
  const mat = new THREE.LineBasicMaterial({ color: new THREE.Color(0.3, 1.6, 2.0), transparent: true, opacity: 0.8, blending: THREE.AdditiveBlending, depthWrite: false });
  const pts = [];
  const N = 46, len = 0.55, rad = 0.07;
  for (let i = 0; i < N; i++) {
    const y = -len / 2 + (i / (N - 1)) * len, a = i * 0.42;
    const p1 = new THREE.Vector3(Math.cos(a) * rad, y, Math.sin(a) * rad), p2 = new THREE.Vector3(Math.cos(a + Math.PI) * rad, y, Math.sin(a + Math.PI) * rad);
    pts.push(p1, p2);
    if (i > 0) { const pa = i - 1, aa = pa * 0.42, yy = -len / 2 + (pa / (N - 1)) * len; pts.push(new THREE.Vector3(Math.cos(aa) * rad, yy, Math.sin(aa) * rad), p1, new THREE.Vector3(Math.cos(aa + Math.PI) * rad, yy, Math.sin(aa + Math.PI) * rad), p2); }
  }
  const lines = new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(pts), mat); g.add(lines);
  const cone = new THREE.Mesh(new THREE.CylinderGeometry(0.09, 0.02, 0.18, 24, 1, true), new THREE.MeshBasicMaterial({ color: new THREE.Color(0.1, 0.6, 0.8), transparent: true, opacity: 0.25, blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide }));
  cone.position.y = -0.38; g.add(cone);
  return { group: g, lines, mat };
}

// ================================================================= BUILD
export function buildLab(renderer, assets, heart) {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x010204);
  scene.fog = new THREE.FogExp2(0x0b1724, 0.075);
  scene.environment = buildEnvironment(renderer);
  scene.environmentIntensity = 0.55;

  const refs = {};
  // ------------------------------------------------ room
  const RW = 14, RD = 12, RH = 4.0;
  const fl = floorTextures(1024);
  fl.map.repeat.set(RW / 4, RD / 4); fl.roughnessMap.repeat.set(RW / 4, RD / 4);
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(RW, RD), std(0xffffff, 1.0, 0.55, { map: fl.map, roughnessMap: fl.roughnessMap }));
  floor.rotation.x = -Math.PI / 2; floor.receiveShadow = true; floor.name = 'Floor'; floor.material.name = 'FloorMat'; scene.add(floor);
  const wt = wallTextures(1024);
  const wallMat = (rep) => { const t = wt.clone(); t.needsUpdate = true; t.repeat.set(rep, 1); const m = std(0xffffff, 0.7, 0.35, { map: t }); m.name = 'WallMat'; return m; };
  const wallB = new THREE.Mesh(new THREE.PlaneGeometry(RW, RH), wallMat(RW / 4)); wallB.position.set(0, RH / 2, -RD / 2); scene.add(wallB);
  const wallF = new THREE.Mesh(new THREE.PlaneGeometry(RW, RH), wallMat(RW / 4)); wallF.position.set(0, RH / 2, RD / 2); wallF.rotation.y = Math.PI; scene.add(wallF);
  const wallL = new THREE.Mesh(new THREE.PlaneGeometry(RD, RH), wallMat(RD / 4)); wallL.position.set(-RW / 2, RH / 2, 0); wallL.rotation.y = Math.PI / 2; scene.add(wallL);
  const wallR = new THREE.Mesh(new THREE.PlaneGeometry(RD, RH), wallMat(RD / 4)); wallR.position.set(RW / 2, RH / 2, 0); wallR.rotation.y = -Math.PI / 2; scene.add(wallR);
  for (const w of [wallB, wallF, wallL, wallR]) w.receiveShadow = true;
  const ceil = new THREE.Mesh(new THREE.PlaneGeometry(RW, RD), std(0x07090c, 0.8, 0.4)); ceil.rotation.x = Math.PI / 2; ceil.position.y = RH; scene.add(ceil);
  // ceiling light panels + beams
  const panelMat = new THREE.MeshBasicMaterial({ color: new THREE.Color(0.75, 0.9, 1.1).multiplyScalar(2.2) }); panelMat.name = 'CeilingPanel';
  for (let i = -2; i <= 2; i++) for (const z of [-3.5, 3.5]) { const p = new THREE.Mesh(new THREE.PlaneGeometry(1.6, 0.18), panelMat); p.rotation.x = Math.PI / 2; p.position.set(i * 2.6, RH - 0.01, z); scene.add(p); }
  const beamMat = std(0x0d1116, 0.6, 0.6); beamMat.name = 'Beam';
  for (let i = -3; i <= 3; i++) { const b = new THREE.Mesh(new THREE.BoxGeometry(0.2, 0.3, RD), beamMat); b.position.set(i * 2.2, RH - 0.15, 0); scene.add(b); }
  const pipeMat = std(0x3a4652, 0.4, 0.8); pipeMat.name = 'Pipe';
  for (let k = 0; k < 4; k++) { const p = new THREE.Mesh(new THREE.CylinderGeometry(0.07 + k * 0.01, 0.07 + k * 0.01, RW, 16), pipeMat); p.rotation.z = Math.PI / 2; p.position.set(0, RH - 0.45 - k * 0.02, -RD / 2 + 0.4 + k * 0.22); p.castShadow = true; scene.add(p); }
  // frosted pipe collars
  // wall light strips
  const stripMat = new THREE.MeshBasicMaterial({ color: new THREE.Color(0.15, 0.85, 1.2).multiplyScalar(2.0) }); stripMat.name = 'StripLight';
  for (const z of [-RD / 2 + 0.02]) { const s = new THREE.Mesh(new THREE.PlaneGeometry(RW, 0.04), stripMat); s.position.set(0, 0.35, z); scene.add(s); }
  for (const x of [-RW / 2 + 0.02, RW / 2 - 0.02]) { const s = new THREE.Mesh(new THREE.PlaneGeometry(RD, 0.04), stripMat); s.position.set(x, 0.35, 0); s.rotation.y = x < 0 ? Math.PI / 2 : -Math.PI / 2; scene.add(s); }

  // ------------------------------------------------ pod
  const pod = new THREE.Group(); scene.add(pod);
  const gun = std(0x27303a, 0.32, 0.75); gun.name = 'Gunmetal';
  const gunLight = std(0x56616d, 0.28, 0.85); gunLight.name = 'GunmetalLight';
  const base = new THREE.Mesh(new RoundedBoxGeometry(2.5, 0.8, 1.2, 4, 0.07), gun); base.position.y = 0.46; pod.add(base);
  const kick = new THREE.Mesh(new THREE.BoxGeometry(2.2, 0.08, 1.0), std(0x050607, 0.6, 0.4)); kick.position.y = 0.04; pod.add(kick);
  const rim = new THREE.Mesh(new RoundedBoxGeometry(2.56, 0.08, 1.26, 3, 0.03), gunLight); rim.position.y = 0.88; pod.add(rim);
  const ledMat = new THREE.MeshBasicMaterial({ color: new THREE.Color(0.2, 1.4, 1.8).multiplyScalar(1.6) }); ledMat.name = 'LED';
  const led = new THREE.Mesh(new THREE.BoxGeometry(2.1, 0.012, 0.01), ledMat); led.position.set(0, 0.74, 0.606); pod.add(led);
  const led2 = led.clone(); led2.position.z = -0.606; pod.add(led2);
  const under = new THREE.Mesh(new THREE.BoxGeometry(2.15, 0.01, 0.96), ledMat); under.position.y = 0.085; pod.add(under);
  // side vents
  for (let k = 0; k < 9; k++) { const v = new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.012, 0.01), std(0x050608, 0.5, 0.3)); v.position.set(-0.95 + k * 0.05, 0.55, 0.605); pod.add(v); }
  const podScreen = screenCanvas(512, 200);
  const ps = screenMesh(podScreen, 0.42, 0.164, 1.4); ps.position.set(0.55, 0.52, 0.607); pod.add(ps);
  refs.podScreen = podScreen;
  const mattressMat = null; const mattress = new THREE.Mesh(new RoundedBoxGeometry(2.24, 0.08, 0.82, 3, 0.03), std(0x8fa8ba, 0.55, 0.0, { emissive: new THREE.Color(0.02, 0.06, 0.09) })); mattress.position.y = 0.91; mattress.receiveShadow = true; mattress.material.name = 'Mattress'; pod.add(mattress);
  const headrest = new THREE.Mesh(new RoundedBoxGeometry(0.3, 0.05, 0.28, 3, 0.02), std(0x7d95a8, 0.5, 0.0)); headrest.position.set(0.82, 0.965, 0); headrest.receiveShadow = true; headrest.material.name = 'Mattress'; pod.add(headrest);
  // connector block at head end
  const conn = new THREE.Mesh(new RoundedBoxGeometry(0.12, 0.16, 0.5, 2, 0.02), gunLight); conn.position.set(1.17, 0.97, 0); pod.add(conn);
  for (let k = 0; k < 6; k++) { const l = new THREE.Mesh(new THREE.BoxGeometry(0.005, 0.012, 0.012), new THREE.MeshBasicMaterial({ color: k % 3 === 0 ? new THREE.Color(2, 0.6, 0.15) : new THREE.Color(0.2, 1.6, 1.4) })); l.position.set(1.11, 1.01, -0.15 + k * 0.06); pod.add(l); }

  // lid
  const lidHinge = new THREE.Group(); lidHinge.position.set(0, 0.92, -0.6); pod.add(lidHinge);
  const lid = new THREE.Group(); lid.position.set(0, 0, 0.6); lidHinge.add(lid);
  const glassMat = glassMaterial(); refs.glassMat = glassMat;
  const shellGeo = new THREE.CylinderGeometry(0.6, 0.6, 2.42, 72, 1, true, 0, Math.PI); shellGeo.rotateZ(Math.PI / 2);
  const shell = new THREE.Mesh(shellGeo, glassMat); shell.name = 'GlassLid'; shell.renderOrder = 5; lid.add(shell);
  const capMat = gunLight;
  for (const sx of [-1, 1]) {
    const ring = new THREE.Mesh(new THREE.TorusGeometry(0.6, 0.035, 12, 48, Math.PI), capMat); ring.rotation.y = Math.PI / 2; ring.position.x = sx * 1.21; lid.add(ring);
    const capGeo = new THREE.CircleGeometry(0.6, 48, 0, Math.PI); capGeo.rotateY(Math.PI / 2); capGeo.translate(sx * 1.21, 0, 0);
    const cap = new THREE.Mesh(capGeo, glassMat); cap.name = 'GlassLid'; cap.renderOrder = 5; lid.add(cap);
  }
  for (const z of [-0.6, 0.6]) { const r = new THREE.Mesh(new THREE.BoxGeometry(2.48, 0.05, 0.06), capMat); r.position.set(0, 0.0, z); lid.add(r); }
  const spine = new THREE.Mesh(new THREE.BoxGeometry(2.42, 0.03, 0.08), capMat); spine.position.set(0, 0.6, 0); lid.add(spine);
  refs.lidHinge = lidHinge;

  // ------------------------------------------------ body
  const lps = assets.lps.clone(true);
  let bustMesh; lps.traverse(m => { if (m.isMesh) bustMesh = m; });
  const skin = makeSkinMaterial({ map: assets.lpsMap, normalMap: assets.lpsNormal });
  bustMesh.material = skin; bustMesh.name = 'Bust'; skin.name = 'Skin'; bustMesh.castShadow = true; bustMesh.receiveShadow = true;
  const bustOuter = new THREE.Group(); bustOuter.rotation.y = -Math.PI / 2; bustOuter.position.copy(BUST_POS);
  const bustInner = new THREE.Group(); bustInner.rotation.x = -Math.PI / 2; bustOuter.add(bustInner);
  bustMesh.position.set(0, 0, 0); bustMesh.scale.setScalar(S_BODY); bustInner.add(bustMesh);
  scene.add(bustOuter);
  refs.skin = skin; refs.bust = bustMesh;

  // find surface points (object space) by nearest vertex
  const P = bustMesh.geometry.attributes.position, Nn = bustMesh.geometry.attributes.normal;
  const nearest = (x, y, z) => {
    let best = 0, bd = 1e9;
    for (let i = 0; i < P.count; i++) { const d = (P.getX(i) - x) ** 2 + (P.getY(i) - y) ** 2 + (P.getZ(i) - z) ** 2; if (d < bd) { bd = d; best = i; } }
    return { p: new THREE.Vector3(P.getX(best), P.getY(best), P.getZ(best)), n: new THREE.Vector3(Nn.getX(best), Nn.getY(best), Nn.getZ(best)) };
  };
  const inj = nearest(1.3, -0.75, 0.15);
  skin.userData.U.uInj.value.copy(inj.p);
  const injW = objToWorld(inj.p), injN = dirToWorld(inj.n);
  refs.injWorld = injW; refs.injNormal = injN;

  // sheet
  const sheetMat = sheetMaterial(); refs.sheetMat = sheetMat;
  const sheet = buildSheet(bustMesh, sheetMat);
  sheet.mesh.name = 'Sheet'; sheet.hem.name = 'Sheet'; sheet.mesh.material.name = 'SheetMat'; scene.add(sheet.mesh, sheet.hem);

  // neck port
  const portG = new THREE.Group();
  const portBase = new THREE.Mesh(new THREE.CylinderGeometry(0.016, 0.019, 0.01, 24), gunLight); portBase.rotation.x = Math.PI / 2; portG.add(portBase);
  const portRingMat = new THREE.MeshBasicMaterial({ color: new THREE.Color(0.3, 1.5, 1.3) });
  const portRing = new THREE.Mesh(new THREE.TorusGeometry(0.012, 0.0025, 8, 24), portRingMat); portRing.position.z = 0.006; portG.add(portRing);
  const portWire = new THREE.Mesh(new THREE.BoxGeometry(0.006, 0.03, 0.004), std(0x111111, 0.5, 0.2)); portWire.position.set(0, 0.02, 0.0); portG.add(portWire);
  portG.name = 'Port'; portG.position.copy(injW).addScaledVector(injN, 0.004);
  portG.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), injN);
  scene.add(portG); refs.portRingMat = portRingMat;

  // electrodes + wires
  const eSpots = [[0, 3.0, 1.75], [1.75, 2.2, 0.6], [-1.75, 2.2, 0.6], [1.0, 3.3, 1.0], [-1.0, 3.3, 1.0], [1.7, -2.9, 0.75], [-1.7, -2.9, 0.75]];
  const elMat = std(0xc9d2db, 0.25, 0.9); elMat.name = 'Electrode';
  const elLed = [];
  const wireMats = [std(0x0e1013, 0.5, 0.2), std(0x1a2a3a, 0.5, 0.2), std(0x3a1010, 0.5, 0.2)];
  eSpots.forEach((s, k) => {
    const { p, n } = nearest(...s);
    const pw = objToWorld(p), nw = dirToWorld(n);
    const e = new THREE.Group();
    const disc = new THREE.Mesh(new THREE.CylinderGeometry(0.011, 0.013, 0.005, 20), elMat); disc.rotation.x = Math.PI / 2; e.add(disc);
    const lm = new THREE.MeshBasicMaterial({ color: new THREE.Color(0.3, 1.5, 1.6) });
    const l = new THREE.Mesh(new THREE.TorusGeometry(0.008, 0.0016, 6, 20), lm); l.position.z = 0.003; e.add(l);
    elLed.push(lm);
    e.position.copy(pw).addScaledVector(nw, 0.002); e.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), nw);
    scene.add(e);
    const z = pw.z;
    const end = new THREE.Vector3(1.12, 0.99, -0.12 + k * 0.04);
    const pts = [pw.clone().addScaledVector(nw, 0.003), pw.clone().addScaledVector(nw, 0.014)];
    if (pw.x < 0.66) pts.push(new THREE.Vector3(0.7, 1.13, z * 0.72), new THREE.Vector3(0.9, 1.1, Math.sign(z) * 0.115), new THREE.Vector3(1.02, 1.04, Math.sign(z) * 0.1));
    else pts.push(new THREE.Vector3(Math.max(pw.x + 0.02, 0.965), Math.min(pw.y + 0.012, 1.13), z * 0.8), new THREE.Vector3(1.03, 1.04, z * 0.6));
    pts.push(end);
    scene.add(tube(pts, 0.0022, wireMats[k % 3], 48, 5));
  });
  refs.elLed = elLed;

  // ------------------------------------------------ head-end tower
  const tower = new THREE.Group(); tower.position.set(1.85, 0, -0.05); scene.add(tower);
  const tw = new THREE.Mesh(new RoundedBoxGeometry(0.55, 2.3, 0.95, 3, 0.05), gun); tw.position.y = 1.15; tw.castShadow = true; tower.add(tw);
  for (let k = 0; k < 7; k++) { const s = new THREE.Mesh(new THREE.BoxGeometry(0.02, 0.012, 0.6), ledMat); s.position.set(-0.28, 0.4 + k * 0.22, 0); tower.add(s); }
  const ecg = screenCanvas(512, 288); refs.ecg = ecg;
  const ecgM = screenMesh(ecg, 0.62, 0.35, 1.8); ecgM.position.set(-0.05, 1.75, 0.56); ecgM.rotation.y = -0.35; tower.add(ecgM);
  const ecgFrame = new THREE.Mesh(new RoundedBoxGeometry(0.68, 0.41, 0.04, 2, 0.015), gunLight); ecgFrame.position.set(-0.04, 1.75, 0.535); ecgFrame.rotation.y = -0.35; tower.add(ecgFrame);
  const warm = new THREE.PointLight(0xff9a4a, 0.9, 3, 2); warm.position.set(-0.4, 1.0, 0.5); tower.add(warm);
  for (let k = 0; k < 5; k++) { const l = new THREE.Mesh(new THREE.SphereGeometry(0.012, 8, 8), new THREE.MeshBasicMaterial({ color: new THREE.Color(2.5, 0.9, 0.2) })); l.position.set(-0.28, 1.15 + k * 0.05, 0.35); tower.add(l); }
  // big cables tower <-> pod
  const cableMat = pulseCableMaterial(0x101418, SERUM, 0.35, 6, 0.06); cableMat.name = 'CableGlow';
  const cableMat2 = pulseCableMaterial(0x0c0f12, new THREE.Color(0.2, 0.6, 1.0), 0.25, 4, 0.05); cableMat2.name = 'CableGlowBlue';
  refs.cableMats = [cableMat, cableMat2];
  scene.add(tube([new THREE.Vector3(1.6, 0.55, 0.25), new THREE.Vector3(1.45, 0.3, 0.3), new THREE.Vector3(1.28, 0.45, 0.25), new THREE.Vector3(1.25, 0.7, 0.2)], 0.035, cableMat));
  scene.add(tube([new THREE.Vector3(1.6, 0.85, -0.2), new THREE.Vector3(1.42, 0.5, -0.25), new THREE.Vector3(1.27, 0.5, -0.3), new THREE.Vector3(1.25, 0.65, -0.3)], 0.03, cableMat2));
  // overhead cable bundle from ceiling into tower and pod back
  for (let k = 0; k < 5; k++) {
    const z0 = -0.5 + k * 0.08;
    scene.add(tube([new THREE.Vector3(1.75 + k * 0.03, RH, z0 - 1.2), new THREE.Vector3(1.7, 3.2, z0 - 0.9), new THREE.Vector3(1.65 + k * 0.02, 2.5, z0), new THREE.Vector3(1.7 + k * 0.03, 2.3, z0 + 0.1)], 0.02 + (k % 2) * 0.008, k % 2 ? cableMat2 : std(0x0b0d10, 0.5, 0.3)));
  }
  for (let k = 0; k < 4; k++) {
    const x0 = -0.8 + k * 0.5;
    scene.add(tube([new THREE.Vector3(x0, RH, -2.6), new THREE.Vector3(x0 + 0.1, 2.0, -1.6 + k * 0.05), new THREE.Vector3(x0 + 0.05, 0.6, -0.95), new THREE.Vector3(x0, 0.5, -0.62)], 0.028, k % 2 ? cableMat : std(0x0b0d10, 0.5, 0.3)));
  }
  // floor cables to console
  const floorCable = std(0x08090b, 0.55, 0.2); floorCable.name = 'Cable';
  for (let k = 0; k < 4; k++) {
    scene.add(tube([new THREE.Vector3(1.6, 0.2, 0.42), new THREE.Vector3(1.75, 0.03, 0.8 + k * 0.05), new THREE.Vector3(2.0 + k * 0.05, 0.03, 1.3), new THREE.Vector3(2.15, 0.03, 1.75 + k * 0.04), new THREE.Vector3(2.2, 0.25, 1.95)], 0.018, k === 1 ? cableMat : floorCable, 64, 6));
  }
  // IV rack with serum canisters
  const rack = new THREE.Group(); rack.position.set(-1.55, 0, -0.75); scene.add(rack);
  const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.015, 0.015, 2.0, 12), gunLight); pole.position.y = 1.0; rack.add(pole);
  const rbase = new THREE.Mesh(new THREE.CylinderGeometry(0.25, 0.28, 0.05, 24), gun); rbase.position.y = 0.025; rack.add(rbase);
  for (let k = 0; k < 3; k++) {
    const can = new THREE.Mesh(new THREE.CylinderGeometry(0.045, 0.045, 0.3, 20), new THREE.MeshStandardMaterial({ color: 0x0a2a24, emissive: SERUM, emissiveIntensity: 0.45, roughness: 0.15, transparent: true, opacity: 0.85 }));
    can.position.set(Math.cos(k * 2.1) * 0.12, 1.7, Math.sin(k * 2.1) * 0.12); rack.add(can);
  }
  scene.add(tube([new THREE.Vector3(-1.55, 1.55, -0.72), new THREE.Vector3(-1.4, 1.0, -0.6), new THREE.Vector3(-1.25, 0.75, -0.45), new THREE.Vector3(-1.2, 0.7, -0.3)], 0.008,
    pulseCableMaterial(0x0d1a18, SERUM, 0.6, 10, 0.1)));

  // ------------------------------------------------ console
  const consoleG = new THREE.Group(); consoleG.position.set(1.95, 0, 1.75); consoleG.rotation.y = 0.85; scene.add(consoleG);
  const desk = new THREE.Mesh(new RoundedBoxGeometry(1.3, 0.9, 0.6, 3, 0.04), gun); desk.position.y = 0.45; desk.castShadow = true; consoleG.add(desk);
  const top = new THREE.Mesh(new RoundedBoxGeometry(1.36, 0.05, 0.7, 2, 0.02), gunLight); top.position.set(0, 0.92, 0.02); top.rotation.x = 0.18; consoleG.add(top);
  const keys = new THREE.Mesh(new THREE.PlaneGeometry(0.9, 0.3), new THREE.MeshBasicMaterial({ color: new THREE.Color(0.1, 0.5, 0.7), transparent: true, opacity: 0.6 }));
  keys.position.set(0, 0.95, 0.12); keys.rotation.x = -Math.PI / 2 + 0.18; consoleG.add(keys);
  const dnaScreen = screenCanvas(512, 288), tempScreen = screenCanvas(512, 200);
  refs.dnaScreen = dnaScreen; refs.tempScreen = tempScreen;
  const sc1 = screenMesh(dnaScreen, 0.6, 0.34, 1.7); sc1.position.set(-0.33, 1.32, -0.18); sc1.rotation.set(-0.12, 0.25, 0); consoleG.add(sc1);
  const sc2 = screenMesh(tempScreen, 0.5, 0.2, 1.7); sc2.position.set(0.36, 1.25, -0.16); sc2.rotation.set(-0.12, -0.2, 0); consoleG.add(sc2);
  const sc3 = screenMesh(ecg, 0.5, 0.28, 1.5); sc3.position.set(0.32, 1.52, -0.2); sc3.rotation.set(-0.08, -0.2, 0); consoleG.add(sc3);
  for (const s of [sc1, sc2, sc3]) { s.rotation.y += Math.PI; }
  const scrLight = new THREE.PointLight(0x58b6ff, 1.2, 3.5, 2); scrLight.position.set(0, 1.35, 0.2); consoleG.add(scrLight);
  const holo = buildHolo(); holo.group.name = 'Holo'; holo.group.position.set(-0.05, 1.42, 0.05); consoleG.add(holo.group); refs.holo = holo;

  // ------------------------------------------------ robot
  const robot = buildRobot(); robot.root.name = 'Robot'; robot.root.position.set(1.0, RH, 1.25); scene.add(robot.root); refs.robot = robot;
  const rail = new THREE.Mesh(new THREE.BoxGeometry(0.25, 0.12, 4), std(0x1b2026, 0.4, 0.7)); rail.position.set(1.0, RH - 0.06, 0.2); scene.add(rail);

  // ------------------------------------------------ back-wall tanks
  const tankGlass = new THREE.ShaderMaterial({
    uniforms: { uTime: { value: 0 } },
    vertexShader: `varying vec3 vN; varying vec3 vW; varying vec2 vUv; void main(){ vUv=uv; vec4 w=modelMatrix*vec4(position,1.0); vW=w.xyz; vN=normalize(mat3(modelMatrix)*normal); gl_Position=projectionMatrix*viewMatrix*w; }`,
    fragmentShader: `uniform float uTime; varying vec3 vN; varying vec3 vW; varying vec2 vUv;
      void main(){ vec3 V=normalize(cameraPosition-vW); float f=pow(1.0-abs(dot(normalize(vN),V)),2.0);
        float grad = smoothstep(0.0,1.0,vUv.y); float bub = smoothstep(0.92,1.0, sin(vUv.x*80.0)*sin(vUv.y*40.0 - uTime*3.0));
        vec3 c = vec3(0.1,0.7,0.9)*(0.25+0.6*f) * (0.6+0.6*(1.0-grad)) + vec3(0.6,0.9,1.0)*bub*0.3;
        gl_FragColor = vec4(c, 0.18 + f*0.5); }`,
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
  });
  refs.tankGlass = tankGlass;
  const figMat = std(0x0d1820, 0.6, 0.2, { emissive: new THREE.Color(0.0, 0.05, 0.07) }); figMat.name = 'TankFigure';
  refs.tankFigures = [];
  for (let k = 0; k < 6; k++) {
    const x = -5 + k * 2;
    const g = new THREE.Group(); g.position.set(x, 0, -5.2); scene.add(g);
    const b = new THREE.Mesh(new THREE.CylinderGeometry(0.62, 0.66, 0.35, 32), gun); b.position.y = 0.175; g.add(b);
    const tp = new THREE.Mesh(new THREE.CylinderGeometry(0.62, 0.62, 0.3, 32), gun); tp.position.y = 2.95; g.add(tp);
    const gl = new THREE.Mesh(new THREE.CylinderGeometry(0.56, 0.56, 2.45, 32, 1, true), tankGlass); gl.name = 'TankGlass'; gl.position.y = 1.575; g.add(gl);
    const ring = new THREE.Mesh(new THREE.TorusGeometry(0.6, 0.015, 8, 40), ledMat); ring.rotation.x = Math.PI / 2; ring.position.y = 0.36; g.add(ring);
    const fig = prepareScientist(assets.xbot.scene, figMat, figMat, null, null);
    fig.position.y = 0.36; fig.scale.setScalar(0.92); fig.rotation.y = (k % 2 ? 0.2 : -0.2);
    g.add(fig); refs.tankFigures.push(fig);
    const pp = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.05, RH - 3.1, 12), pipeMat); pp.position.y = 3.1 + (RH - 3.1) / 2; g.add(pp);
  }
  const tankLight1 = new THREE.PointLight(0x37d8ff, 3.0, 7, 1.6); tankLight1.position.set(-3, 1.6, -4.4); scene.add(tankLight1);
  const tankLight2 = new THREE.PointLight(0x37d8ff, 3.0, 7, 1.6); tankLight2.position.set(3, 1.6, -4.4); scene.add(tankLight2);

  // ------------------------------------------------ scientists
  const suit = std(0xf2f6fa, 0.72, 0.0); suit.name = 'Suit';
  const joints = std(0xaeb9c4, 0.6, 0.1); joints.name = 'SuitJoints';
  const gownMat = std(0xe4edf4, 0.78, 0.0, { side: THREE.DoubleSide }); gownMat.name = 'Gown';
  const visor = std(0x050a0f, 0.08, 1.0, { emissive: new THREE.Color(0.0, 0.04, 0.05) }); visor.name = 'Visor';
  const clip = (name) => assets.xbot.animations.find(a => a.name === name);
  const mkSci = (pos, rotY) => {
    const o = prepareScientist(assets.xbot.scene, suit, joints, visor, gownMat);
    o.position.set(...pos); o.rotation.y = rotY; scene.add(o);
    const mixer = new THREE.AnimationMixer(o);
    const acts = {};
    for (const n of ['idle', 'walk', 'headShake', 'agree']) { acts[n] = mixer.clipAction(clip(n)); acts[n].play(); acts[n].setEffectiveWeight(n === 'idle' ? 1 : 0); }
    return { o, mixer, acts, bones: { la: o.getObjectByName('mixamorigLeftArm'), ra: o.getObjectByName('mixamorigRightArm'), lf: o.getObjectByName('mixamorigLeftForeArm'), rf: o.getObjectByName('mixamorigRightForeArm'), head: o.getObjectByName('mixamorigHead'), spine: o.getObjectByName('mixamorigSpine1') } };
  };
  // A: console operator (faces the pod across the console)
  const sciA = mkSci([2.42, 0, 2.18], 0.85 + Math.PI);
  // B: observer at the foot end with tablet
  const sciB = mkSci([-2.05, 0, 0.7], 1.9);
  const tablet = new THREE.Mesh(new RoundedBoxGeometry(24, 1.2, 17, 2, 0.6), std(0x0b0e12, 0.3, 0.6));
  const tabScreen = new THREE.Mesh(new THREE.PlaneGeometry(21, 14), new THREE.MeshBasicMaterial({ color: new THREE.Color(0.2, 0.9, 1.2) })); tabScreen.rotation.x = -Math.PI / 2; tabScreen.position.y = 0.7; tablet.add(tabScreen);
  sciB.bones.lh = sciB.o.getObjectByName('mixamorigLeftHand');
  sciB.tablet = tablet;
  // C: walks in from the back, ends behind the pod
  const sciC = mkSci([-4.2, 0, -2.7], 0.6);
  refs.sci = [sciA, sciB, sciC];

  // ------------------------------------------------ lights
  scene.add(new THREE.HemisphereLight(0x6d92bb, 0x0a0e14, 0.75));
  for (const [x, z] of [[-2.6, 2.2], [2.6, 2.6], [-2.6, -2.4], [3.0, -1.8]]) { const l = new THREE.PointLight(0xcfe4ff, 9, 9, 1.8); l.position.set(x, RH - 0.3, z); scene.add(l); }
  const podLight = new THREE.PointLight(0x9fdcff, 0.35, 1.6, 2); podLight.position.set(0.1, 1.42, 0.25); scene.add(podLight); refs.podLight = podLight;
  const key = new THREE.SpotLight(0xcfe6ff, 16, 0, 0.42, 0.65, 2);
  key.position.set(0.25, RH - 0.05, 0.2); key.target.position.set(0.2, 1.0, 0.0);
  key.castShadow = true; key.shadow.mapSize.set(1536, 1536); key.shadow.bias = -0.0004; key.shadow.normalBias = 0.01; key.shadow.camera.near = 1; key.shadow.camera.far = 6;
  scene.add(key, key.target); refs.key = key;
  const rimA = new THREE.SpotLight(0x3fd2ff, 26, 0, 0.5, 0.7, 2); rimA.position.set(-2.6, 2.6, -3.6); rimA.target.position.set(0.3, 1.0, 0); scene.add(rimA, rimA.target);
  const rimB = new THREE.SpotLight(0x46e0ff, 22, 0, 0.45, 0.7, 2); rimB.position.set(3.2, 2.4, -3.2); rimB.target.position.set(0.5, 1.0, 0); scene.add(rimB, rimB.target);
  const fill = new THREE.SpotLight(0x9fc4ff, 0, 0, 0.35, 0.8, 2); fill.position.set(0.9, 1.9, 1.3); fill.target.position.set(0.75, 1.15, 0.0); scene.add(fill, fill.target); refs.fill = fill;
  const injLight = new THREE.PointLight(SERUM, 0, 1.2, 2); injLight.position.copy(injW).addScaledVector(injN, 0.22).add(new THREE.Vector3(0, 0.12, 0)); scene.add(injLight); refs.injLight = injLight;
  const eyeLight = new THREE.PointLight(0x9ffff0, 0, 1.2, 2); eyeLight.position.copy(objToWorld(new THREE.Vector3(0, 1.7, 7.0))); scene.add(eyeLight); refs.eyeLight = eyeLight;
  const alarms = [];
  for (const p of [[-6.6, 3.4, -5.6], [6.6, 3.4, -5.6], [-6.6, 3.4, 5.6]]) {
    const a = new THREE.SpotLight(0xff2a1a, 0, 0, 0.5, 0.5, 1.5); a.position.set(...p); scene.add(a, a.target); alarms.push(a);
    const bulb = new THREE.Mesh(new THREE.SphereGeometry(0.08, 12, 12), new THREE.MeshBasicMaterial({ color: 0x220000 })); bulb.position.set(...p); scene.add(bulb); a.userData.bulb = bulb;
  }
  refs.alarms = alarms;
  const underGlow = new THREE.PointLight(0x2ad8ff, 1.6, 2.5, 2); underGlow.position.set(0, 0.12, 0.7); scene.add(underGlow);

  // ------------------------------------------------ volumetric shaft
  const shaftMat = new THREE.ShaderMaterial({
    uniforms: { uTime: { value: 0 }, uI: { value: 0.06 } },
    vertexShader: `varying vec3 vL; varying vec3 vW; varying vec3 vN; void main(){ vL=position; vec4 w=modelMatrix*vec4(position,1.0); vW=w.xyz; vN=normalize(mat3(modelMatrix)*normal); gl_Position=projectionMatrix*viewMatrix*w; }`,
    fragmentShader: `uniform float uTime, uI; varying vec3 vL; varying vec3 vW; varying vec3 vN; ${NOISE}
      void main(){ vec3 V=normalize(cameraPosition-vW); float edge=pow(abs(dot(normalize(vN),V)),1.6);
        float h = clamp((vL.y+1.5)/3.0,0.0,1.0); float dust = 0.6+0.4*snoise(vW*1.6+vec3(0.0,-uTime*0.15,uTime*0.05));
        float cd = smoothstep(0.6, 2.5, distance(cameraPosition, vW)); gl_FragColor = vec4(vec3(0.55,0.75,1.0)*uI*edge*dust*(0.35+0.65*h)*cd, 1.0); }`,
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.FrontSide,
  });
  const shaft = new THREE.Mesh(new THREE.CylinderGeometry(0.18, 1.35, 3.0, 48, 1, true), shaftMat);
  shaft.position.set(0.22, RH - 1.55, 0.12); shaft.name = 'Shaft'; scene.add(shaft); refs.shaftMat = shaftMat;

  // ------------------------------------------------ ground fog layers
  const fogTex = noiseTexture(512, 9, 3, 6, 1.8, -0.1);
  refs.fogLayers = [];
  for (let k = 0; k < 6; k++) {
    const t = fogTex.clone(); t.needsUpdate = true; t.repeat.set(2.2 + k * 0.3, 2.0 + k * 0.25);
    const m = new THREE.MeshBasicMaterial({ color: new THREE.Color(0.55, 0.72, 0.9), alphaMap: t, transparent: true, opacity: 0.16 - k * 0.018, depthWrite: false, fog: true });
    const p = new THREE.Mesh(new THREE.PlaneGeometry(RW - 0.2, RD - 0.2), m); p.rotation.x = -Math.PI / 2; p.position.y = 0.05 + k * 0.11; p.name = 'FogLayer'; scene.add(p);
    refs.fogLayers.push({ tex: t, k });
  }

  // vapour spilling from the pod, dust motes
  const puff = smokePuff(256, 4);
  const vapor = new Billboards(150, { map: puff, intensity: 1.0, nearFade: [0.15, 0.7] });
  vapor.mesh.renderOrder = 6; vapor.mesh.name = 'Particles'; scene.add(vapor.mesh); refs.vapor = vapor;
  const motes = new Billboards(260, { map: glowSprite(64), blending: THREE.AdditiveBlending, intensity: 1.0, nearFade: [0.2, 0.6] });
  motes.mesh.name = 'Particles'; scene.add(motes.mesh); refs.motes = motes;
  const steam = new Billboards(70, { map: puff, intensity: 1.0, nearFade: [0.18, 0.45] });
  steam.mesh.renderOrder = 7; steam.mesh.name = 'Particles'; scene.add(steam.mesh); refs.steam = steam;

  // sample points on the face (world) for steam
  const faceSamples = [];
  { const r = rng(91); for (let k = 0; k < 400 && faceSamples.length < 70; k++) { const i = Math.floor(r() * P.count); if (Nn.getZ(i) > 0.2 && P.getY(i) > -2.2) { const op = new THREE.Vector3(P.getX(i), P.getY(i), P.getZ(i)); faceSamples.push({ o: op, w: objToWorld(op), d: op.distanceTo(inj.p), r: r() }); } } }
  refs.faceSamples = faceSamples;

  // ================================================================= UPDATE
  const tipRest = new THREE.Vector3(1.25, 2.55, 1.55), dirRest = new THREE.Vector3(0.1, -1, 0.2).normalize();
  const hover = injW.clone().addScaledVector(injN, 0.2);
  const contact = injW.clone().addScaledVector(injN, 0.006);
  const retreat = injW.clone().addScaledVector(injN, 0.55).add(new THREE.Vector3(0.15, 0.35, 0.1));
  const dirInj = injN.clone().negate();
  const tmpV = new THREE.Vector3();

  function state(t) {
    const st = {};
    st.lid = ease.inOut(smooth(16.4, 19.6, t));
    st.serum = 1 - 0.85 * smooth(25.4, 28.8, t);
    st.local = smooth(25.8, 28.0, t);
    st.front = t < 53.5 ? lerp(-1.5, 0.9, smooth(25.6, 29, t)) : lerp(0.9, 10.5, ease.inOut(smooth(53.5, 66.5, t)));
    st.scale = smooth(57.0, 65.5, t);
    st.disp = smooth(58.0, 67.0, t);
    st.frost = 1 - 0.25 * smooth(54, 64, t);
    st.eye = ease.in(smooth(65.2, 69.2, t));
    st.alarm = t > 58.6 ? 1 : 0;
    st.breath = smooth(55, 58, t);
    st.writhe = smooth(61, 63, t) * (1 - 0.4 * smooth(66, 69, t));
    st.temp = t < 53.5 ? -196.0 + Math.sin(t * 0.7) * 0.05 : lerp(-196, 36.6, ease.inOut(smooth(53.5, 66, t)));
    st.dnaProg = smooth(46, 53.5, t);
    return st;
  }

  function update(t, cam, shotId) {
    const st = state(t);
    // lid
    lidHinge.rotation.x = -1.85 * st.lid;
    glassMat.uniforms.uTime.value = t;
    // robot
    let tipT, dirT;
    if (t < 19.6) { tipT = tipRest.clone(); dirT = dirRest.clone(); }
    else if (t < 23.2) { const u = ease.inOut(smooth(19.6, 23.2, t)); tipT = tipRest.clone().lerp(hover, u); dirT = dirRest.clone().lerp(dirInj, u).normalize(); }
    else if (t < 24.9) { const u = ease.inOut(smooth(23.2, 24.9, t)); tipT = hover.clone().lerp(contact, u); dirT = dirInj.clone(); }
    else if (t < 29.4) { tipT = contact.clone(); dirT = dirInj.clone(); }
    else { const u = ease.inOut(smooth(29.4, 33, t)); tipT = contact.clone().lerp(retreat, u); dirT = dirInj.clone(); }
    // micro tremor of the servo
    tipT.x += noise1(t * 3.1, 1) * 0.0012; tipT.y += noise1(t * 2.7, 2) * 0.0012;
    robot.solve(tipT, dirT, st.serum);
    // skin
    const U = skin.userData.U;
    U.uTime.value = t; U.uFrost.value = st.frost; U.uFront.value = st.front; U.uLocal.value = st.local;
    U.uScale.value = st.scale; U.uDisp.value = st.disp; U.uEye.value = st.eye;
    const hb = heart.bpm(t) > 0 ? heart.pulse(t) : 0;
    U.uPulse.value = hb;
    bustMesh.worldToLocal(U.uCam.value.copy(cam.position));
    // lights tied to the subject
    refs.injLight.intensity = st.local * (0.02 + 0.03 * hb) + smooth(54, 62, t) * (0.03 + 0.03 * hb);
    refs.eyeLight.intensity = st.eye * 0.05;
    portRingMat.color.setRGB(0.3, 1.5, 1.3).multiplyScalar(0.6 + st.local * 1.2 + hb * 0.6);
    // electrodes blink
    elLed.forEach((m, k) => { const on = (Math.floor(t * 2 + k * 0.37) % 2) === 0; m.color.setRGB(0.3, 1.5, 1.6).multiplyScalar(on ? 1.4 : 0.35); if (st.alarm) m.color.setRGB(2.0, 0.3, 0.2).multiplyScalar(on ? 1.2 : 0.3); });
    // sheet
    sheetMat.userData.U.uTime.value = t;
    sheetMat.userData.U.uBreath.value = st.breath * Math.sin(t * Math.PI * 2 / 3.2);
    sheetMat.userData.U.uWrithe.value = st.writhe;
    // cables
    for (const m of refs.cableMats) m.userData.U.uTime.value = t;
    scene.traverse(o => { if (o.isMesh && o.material.userData && o.material.userData.U && o.material.userData.U.uGlow) o.material.userData.U.uTime.value = t; });
    // screens (only redraw what is visible-ish to save time)
    drawECG(ecg, t, heart, st.alarm ? 'alarm' : 'ok');
    drawDNA(dnaScreen, t, st.dnaProg);
    drawTemp(tempScreen, t, st.temp, 'TEMP. NÚCLEO');
    drawTemp(podScreen, t, st.temp, 'CÁPSULA 01');
    // hologram
    holo.group.rotation.y = t * 0.6;
    holo.mat.opacity = 0.6 + 0.2 * Math.sin(t * 13) * Math.sin(t * 3.1);
    // tanks
    tankGlass.uniforms.uTime.value = t;
    // alarm lights
    alarms.forEach((a, k) => {
      a.intensity = st.alarm * 420;
      const ang = t * 4.2 + k * 2.1;
      a.target.position.set(a.position.x + Math.cos(ang) * 4, 0.5, a.position.z + Math.sin(ang) * 4 * (a.position.z > 0 ? -1 : 1));
      a.userData.bulb.material.color.setRGB(st.alarm ? 3 : 0.15, st.alarm ? 0.25 : 0.0, 0.0);
    });
    refs.key.intensity = 16 * (st.alarm ? 0.55 + 0.25 * (0.5 + 0.5 * Math.sin(t * 25)) : 1);
    shaftMat.uniforms.uTime.value = t;
    // fog layers drift
    refs.fogLayers.forEach(({ tex, k }) => { tex.offset.set(t * (0.004 + k * 0.0015), t * (0.002 - k * 0.001)); });
    // vapour: spills over the pod rim, more when the lid opens
    const spill = 0.35 + 0.65 * st.lid + (t > 16.4 && t < 21 ? 0.8 * Math.exp(-(t - 16.6) * 0.8) : 0);
    const r = rng(1234);
    for (let i = 0; i < vapor.count; i++) {
      const life = 4.5 + r() * 3, ph = r(), age = ((t / life + ph) % 1);
      const side = r() < 0.5 ? -1 : 1, along = (r() - 0.5) * 2.3;
      const z0 = side * 0.62, y0 = 0.92 + r() * 0.06;
      const fall = Math.min(age * 1.6, 1);
      const x = along + (r() - 0.5) * 0.3 * age;
      const y = y0 - fall * 0.85 + age * 0.05;
      const z = z0 + side * (0.15 * age + fall * fall * 0.9 * (0.5 + r()));
      const size = 0.35 + age * 1.4;
      const a = Math.sin(age * Math.PI) * 0.12 * spill;
      vapor.set(i, x, Math.max(0.05, y), z, size, a, r() * 6 + t * (r() - 0.5) * 0.3);
      vapor.setTint(i, 0.62, 0.78, 0.95);
    }
    vapor.commit();
    const r2 = rng(99);
    for (let i = 0; i < motes.count; i++) {
      const x0 = (r2() - 0.5) * 9, y0 = r2() * 3.6, z0 = (r2() - 0.5) * 8, sp = 0.02 + r2() * 0.05;
      const x = x0 + Math.sin(t * 0.2 + i) * 0.2, y = ((y0 - t * sp) % 3.6 + 3.6) % 3.6 + 0.1, z = z0 + Math.cos(t * 0.17 + i * 1.3) * 0.2;
      const tw = 0.5 + 0.5 * Math.sin(t * (1 + r2() * 3) + i);
      motes.set(i, x, y, z, 0.012 + r2() * 0.012, 0.35 * tw, 0);
      motes.setTint(i, 0.7, 0.85, 1.0);
    }
    motes.commit();
    // steam rising off the thawing skin
    for (let i = 0; i < steam.count; i++) {
      const fs = faceSamples[i % faceSamples.length];
      const passed = clamp((st.front - fs.d) / 2.0) * (t > 53 ? 1 : 0);
      const life = 1.8 + fs.r * 1.5, age = ((t / life + fs.r * 7.1) % 1);
      const p = fs.w;
      steam.set(i, p.x + age * 0.04 * Math.sin(i), p.y + 0.01 + age * 0.12, p.z + age * 0.03 * Math.cos(i * 1.7), 0.03 + age * 0.09, passed * Math.sin(age * Math.PI) * 0.12, i + t * 0.3);
      steam.setTint(i, 0.8, 0.9, 1.0);
    }
    steam.commit();
    // scientists
    updateScientists(t, st);
    // per-shot light tweaks
    fill.intensity = (shotId === 'face' || shotId === 'eyes' || shotId === 'inject' || shotId === 'pod') ? 0.7 : 0;
  }

  const qx = new THREE.Quaternion(), eul = new THREE.Euler();
  function addRot(bone, x, y, z) { if (!bone) return; eul.set(x, y, z); qx.setFromEuler(eul); bone.quaternion.multiply(qx); }
  function updateScientists(t, st) {
    const [A, B, C] = refs.sci;
    // A: typing / operating
    A.mixer.setTime(t);
    const typ = Math.sin(t * 9) * 0.05, typ2 = Math.sin(t * 11 + 1) * 0.05;
    addRot(A.bones.la, 0.0, 0.0, 0.0);
    addRot(A.bones.ra, 0.0, 0.0, 0.0);
    addRot(A.bones.la, 0.9, 0, 0.35); addRot(A.bones.lf, 0, 0, 0.0);
    addRot(A.bones.ra, 0.9, 0, -0.35);
    addRot(A.bones.lf, 0.0, 0.0, 1.25 + typ); addRot(A.bones.rf, 0.0, 0.0, -1.25 + typ2);
    addRot(A.bones.spine, 0.18, 0, 0);
    const back = smooth(61.2, 63.5, t) * 0.55;
    A.o.position.set(2.42 + Math.sin(0.85) * back, 0, 2.18 + Math.cos(0.85) * back);
    // B: holds tablet, looks at the pod; head shake when alarm
    const shake = smooth(61.5, 62.2, t) * (1 - smooth(65, 66, t));
    B.acts.idle.setEffectiveWeight(1 - shake); B.acts.headShake.setEffectiveWeight(shake);
    B.mixer.setTime(t);
    addRot(B.bones.la, 0.75, 0, 0.25); addRot(B.bones.lf, 0, 0, 1.5);
    addRot(B.bones.ra, 0.3, 0, -0.1);
    if (B.bones.lh && !B.tablet.parent) { B.bones.lh.add(B.tablet); B.tablet.position.set(0, 12, 5); B.tablet.rotation.set(0.2, 0, 1.5); }
    const backB = smooth(61.0, 63.5, t) * 0.4;
    B.o.position.set(-2.05 - backB * 0.7, 0, 0.7 + backB * 0.5);
    // C: walk in then stand behind the pod
    const walkU = smooth(0.6, 6.4, t);
    const walking = t > 0.6 && t < 6.6 ? 1 : 0;
    const wW = walking ? Math.min(smooth(0.4, 1.0, t), 1 - smooth(6.0, 6.6, t)) : 0;
    C.acts.walk.setEffectiveWeight(wW); C.acts.idle.setEffectiveWeight(1 - wW);
    C.mixer.setTime(t);
    const p0 = new THREE.Vector3(-4.6, 0, -2.9), p1 = new THREE.Vector3(-1.2, 0, -2.0), p2 = new THREE.Vector3(0.15, 0, -1.25);
    const u = walkU;
    const p = u < 0.6 ? p0.clone().lerp(p1, u / 0.6) : p1.clone().lerp(p2, (u - 0.6) / 0.4);
    C.o.position.copy(p);
    const head = u < 0.6 ? Math.atan2(p1.x - p0.x, p1.z - p0.z) : Math.atan2(p2.x - p1.x, p2.z - p1.z);
    C.o.rotation.y = lerp(head, 0.05, smooth(5.6, 7.2, t));
    if (t > 6.6) { addRot(C.bones.la, 0.4, 0, 0.5); addRot(C.bones.ra, 0.4, 0, -0.5); addRot(C.bones.lf, 0, 0, 1.2); addRot(C.bones.rf, 0, 0, -1.2); }
    const backC = smooth(61.4, 63.8, t) * 0.5;
    C.o.position.z -= backC;
    // frozen tank figures: fixed idle pose
    refs.tankFigures.forEach((f, k) => { if (!f.userData.posed) { const mx = new THREE.AnimationMixer(f); const a = mx.clipAction(clip('idle')); a.play(); mx.setTime(0.3 + k * 0.4); f.userData.posed = true; } });
  }

  return { scene, update, refs, state, objToWorld, injWorld: injW, injNormal: injN };
}
