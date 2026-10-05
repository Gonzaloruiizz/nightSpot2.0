import * as THREE from 'three';
import { mergeVertices } from 'three/addons/utils/BufferGeometryUtils.js';
import { NOISE } from './glsl.js';
import { Billboards } from './particles.js';
import { glowSprite } from './textures.js';
import { clamp, lerp, smooth, ease, rng, fbm1, vtrack } from './util.js';

const SERUM = new THREE.Color(0.1, 1.0, 0.75);

function membraneMaterial(rim, inner, opts = {}) {
  return new THREE.ShaderMaterial({
    uniforms: { uTime: { value: 0 }, uRim: { value: new THREE.Color(rim) }, uInner: { value: new THREE.Color(inner) }, uHit: { value: new THREE.Vector3(0, 0, 1) }, uHitT: { value: -10 }, uAmp: { value: opts.amp ?? 0.35 }, uAlpha: { value: opts.alpha ?? 1 } },
    vertexShader: /* glsl */`
      uniform float uTime, uAmp; varying vec3 vN; varying vec3 vW; varying vec3 vL;
      ${NOISE}
      void main(){
        vec3 p = position;
        float n = snoise(normalize(p) * 2.2 + uTime * 0.08) * 0.6 + snoise(normalize(p) * 7.0 - uTime * 0.05) * 0.25;
        p += normal * n * uAmp;
        vL = normalize(position);
        vec4 w = modelMatrix * vec4(p, 1.0); vW = w.xyz; vN = normalize(mat3(modelMatrix) * normal);
        gl_Position = projectionMatrix * viewMatrix * w;
      }`,
    fragmentShader: /* glsl */`
      uniform float uTime, uHitT, uAlpha; uniform vec3 uRim, uInner, uHit; varying vec3 vN; varying vec3 vW; varying vec3 vL;
      ${NOISE}
      void main(){
        vec3 V = normalize(cameraPosition - vW);
        float f = 1.0 - abs(dot(normalize(vN), V));
        float fres = pow(f, 2.5);
        vec3 vo = voronoi3(vL * 26.0);
        float dots = 1.0 - smoothstep(0.05, 0.22, vo.x);
        float web = 1.0 - smoothstep(0.0, 0.06, vo.y - vo.x);
        vec3 col = uRim * fres * 1.15 + uInner * 0.06 + uRim * dots * 0.18 + uInner * web * 0.12;
        float d = acos(clamp(dot(vL, uHit), -1.0, 1.0));
        float age = uTime - uHitT;
        float ring = exp(-pow((d - age * 0.35) / 0.03, 2.0)) * exp(-age * 0.8) * step(0.0, age);
        float spot = exp(-d * d / 0.004) * smoothstep(0.0, 0.5, age) * step(0.0, age);
        col += vec3(0.2, 1.0, 0.8) * (ring * 0.7 + spot * 0.45);
        gl_FragColor = vec4(col * uAlpha, 1.0);
      }`,
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide,
  });
}

export function buildDNA(renderer, heart) {
  // ================================================================ CELL
  const cell = new THREE.Scene();
  cell.background = new THREE.Color(0x020109);
  const CF = new THREE.Color(0x05031a);
  cell.fog = new THREE.FogExp2(CF, 0.012);
  let memGeo = new THREE.IcosahedronGeometry(9, 7); memGeo.deleteAttribute('uv'); memGeo.deleteAttribute('normal'); memGeo = mergeVertices(memGeo); memGeo.computeVertexNormals();
  const memMat = membraneMaterial(0xc070ff, 0x5030c0, { amp: 0.4 });
  const membrane = new THREE.Mesh(memGeo, memMat); membrane.renderOrder = 3; cell.add(membrane);
  const nucMat = new THREE.ShaderMaterial({
    uniforms: { uTime: { value: 0 } },
    vertexShader: `varying vec3 vN; varying vec3 vW; varying vec3 vL; void main(){ vL=position; vec4 w=modelMatrix*vec4(position,1.0); vW=w.xyz; vN=normalize(mat3(modelMatrix)*normal); gl_Position=projectionMatrix*viewMatrix*w; }`,
    fragmentShader: `uniform float uTime; varying vec3 vN; varying vec3 vW; varying vec3 vL; ${NOISE}
      void main(){ vec3 V=normalize(cameraPosition-vW); float f=1.0-abs(dot(normalize(vN),V));
        float ch = fbm3(vL*1.4 + uTime*0.05); float strands = 1.0 - smoothstep(0.0, 0.08, abs(snoise(vL*2.5 + vec3(uTime*0.03))));
        vec3 c = vec3(0.12,0.05,0.35)*(0.4+0.6*ch) + vec3(0.6,0.35,1.0)*pow(f,2.0)*1.2 + vec3(0.4,0.6,1.0)*strands*0.35;
        gl_FragColor = vec4(c, 1.0); }`,
  });
  const nucleus = new THREE.Mesh(new THREE.SphereGeometry(3.6, 64, 48), nucMat); nucleus.position.set(0.6, 0.4, -0.8); cell.add(nucleus);
  const mitoMat = new THREE.MeshStandardMaterial({ color: 0xff7a4a, emissive: new THREE.Color(0.5, 0.15, 0.05), roughness: 0.5, transparent: true, opacity: 0.85 });
  const r0 = rng(41);
  for (let k = 0; k < 9; k++) {
    const m = new THREE.Mesh(new THREE.CapsuleGeometry(0.35, 1.1, 8, 16), mitoMat);
    const d = new THREE.Vector3(r0() - 0.5, r0() - 0.5, r0() - 0.5).normalize().multiplyScalar(5 + r0() * 2.5);
    m.position.copy(d); m.rotation.set(r0() * 6, r0() * 6, r0() * 6); cell.add(m);
  }
  const others = [];
  for (let k = 0; k < 9; k++) {
    const m = new THREE.Mesh(memGeo, membraneMaterial(k % 2 ? 0x9060ff : 0xd070e0, 0x302080, { amp: 0.3, alpha: 0.7 }));
    const a = k * 0.75 + 0.3; const r = 26 + (k % 3) * 12;
    m.position.set(Math.cos(a) * r, (r0() - 0.5) * 30, -Math.abs(Math.sin(a)) * r - 6); m.scale.setScalar(0.6 + r0() * 0.6);
    cell.add(m); others.push(m);
    const n = new THREE.Mesh(new THREE.SphereGeometry(3.4, 32, 24), nucMat); n.position.copy(m.position); n.scale.copy(m.scale); cell.add(n);
  }
  cell.add(new THREE.HemisphereLight(0x8a70ff, 0x100830, 1.0));
  const cellLight = new THREE.PointLight(0x40ffd0, 8, 20, 1.5); cell.add(cellLight);
  const dust = new Billboards(380, { map: glowSprite(48), blending: THREE.AdditiveBlending, nearFade: [0.2, 1.0], fog: { color: CF, density: 0.012 } });
  cell.add(dust.mesh);
  const dustD = []; for (let i = 0; i < 380; i++) dustD.push([(r0() - 0.5) * 80, (r0() - 0.5) * 50, (r0() - 0.5) * 80 - 5, r0()]);
  const stream = new Billboards(260, { map: glowSprite(48), blending: THREE.AdditiveBlending, nearFade: [0.1, 0.6] });
  cell.add(stream.mesh);
  const streamD = []; for (let i = 0; i < 260; i++) streamD.push([r0(), r0() * 6.28, Math.sqrt(r0()), r0()]);
  const HIT = new THREE.Vector3(0.12, 0.22, 1).normalize();
  memMat.uniforms.uHit.value.copy(HIT); memMat.uniforms.uHitT.value = 43.2;

  function updateCell(t, cam) {
    memMat.uniforms.uTime.value = t; nucMat.uniforms.uTime.value = t;
    for (const o of others) o.material.uniforms.uTime.value = t;
    vtrack([[41, [-3.5, 4.5, 40]], [44.0, [0.6, 1.6, 14.5]], [45.5, [1.2, 2.1, 4.5]]], t, ease.inOut, cam.position);
    const tgt = vtrack([[41, [0, 0, 0]], [44, [1.0, 1.9, 8.0]], [45.5, [0.6, 0.4, -0.8]]], t, ease.inOut, new THREE.Vector3());
    cam.position.x += fbm1(t * 0.4, 31) * 0.2; cam.position.y += fbm1(t * 0.35, 32) * 0.2;
    cam.lookAt(tgt); cam.fov = 45;
    const entry = HIT.clone().multiplyScalar(9.2);
    cellLight.position.copy(entry).add(new THREE.Vector3(0, 0, 2));
    cellLight.intensity = 2 + 3 * smooth(42.5, 43.5, t);
    for (let i = 0; i < dust.count; i++) { const d = dustD[i]; dust.set(i, d[0] + Math.sin(t * 0.2 + i) * 0.5, d[1] + Math.cos(t * 0.15 + i) * 0.5, d[2], 0.08 + d[3] * 0.18, 0.25 + 0.25 * Math.sin(t + i), 0); dust.setTint(i, 0.7, 0.55, 1.0); }
    dust.commit();
    // nanocarrier stream from behind the camera to the entry point, then spreading on the membrane
    const src = new THREE.Vector3(-6, 6, 46);
    for (let i = 0; i < stream.count; i++) {
      const [ph, th, rr, sp] = streamD[i];
      const u = ((t - 41) * (0.32 + sp * 0.12) + ph) % 1.3;
      let p;
      if (u < 1) {
        p = src.clone().lerp(entry, ease.in(u));
        const spread = (1 - u) * 3.5 + 0.3;
        p.x += Math.cos(th + t * 0.8) * rr * spread; p.y += Math.sin(th + t * 0.8) * rr * spread;
      } else {
        const k = (u - 1) / 0.3; // dive inside along the membrane normal
        p = entry.clone().addScaledVector(HIT, -k * 3.0);
        p.x += Math.cos(th) * rr * (0.4 + k * 2); p.y += Math.sin(th) * rr * (0.4 + k * 2);
      }
      const a = smooth(41, 41.6, t) * (u < 1 ? 1 : 1 - (u - 1) / 0.3);
      stream.set(i, p.x, p.y, p.z, 0.14 + sp * 0.16, 0.35 * a, 0); stream.setTint(i, SERUM.r, SERUM.g, SERUM.b);
    }
    stream.commit();
  }

  // ================================================================ DNA
  const dna = new THREE.Scene();
  dna.background = new THREE.Color(0x01020a);
  const DF = new THREE.Color(0x030619);
  dna.fog = new THREE.FogExp2(DF, 0.028);
  const NBP = 150, RISE = 0.34, RAD = 1.0, TWIST = Math.PI / 5, OFF = Math.PI * 0.78;
  const X0 = -NBP * RISE / 2;
  const front = (t) => lerp(-21, 6, ease.inOut(smooth(46.2, 53.2, t)));
  const bubble = (x, f) => Math.exp(-Math.pow((x - f) / 2.0, 2));
  const strandPt = (x, s, f, out) => {
    const a = (x - X0) / RISE * TWIST + (s ? OFF : 0);
    const r = RAD + bubble(x, f) * 1.15;
    return out.set(x, Math.cos(a) * r, Math.sin(a) * r);
  };
  // backbones (shader displaces them for the unzip bubble)
  const bbU = { uFront: { value: -30 }, uTime: { value: 0 }, uPulse: { value: 0 } };
  const bbMat = new THREE.MeshStandardMaterial({ color: 0x2a4fb8, roughness: 0.25, metalness: 0.35, emissive: new THREE.Color(0.02, 0.05, 0.15) });
  bbMat.onBeforeCompile = (sh) => {
    Object.assign(sh.uniforms, bbU);
    sh.vertexShader = sh.vertexShader.replace('#include <common>', '#include <common>\nuniform float uFront; varying float vX;')
      .replace('#include <begin_vertex>', `#include <begin_vertex>
        { float b = exp(-pow((position.x - uFront)/2.0, 2.0)); vec2 d = normalize(position.yz + 1e-5); transformed.yz += d * b * 1.15; vX = position.x; }`);
    sh.fragmentShader = sh.fragmentShader.replace('#include <common>', '#include <common>\nuniform float uFront, uTime, uPulse; varying float vX;')
      .replace('#include <emissivemap_fragment>', `#include <emissivemap_fragment>
        float ed = smoothstep(uFront + 0.5, uFront - 1.5, vX);
        float edge = exp(-pow((vX - uFront)/0.8, 2.0));
        totalEmissiveRadiance += mix(vec3(0.0), vec3(1.0, 0.5, 0.08) * (0.3 + 0.2*uPulse), ed) + vec3(0.2,1.0,0.8)*edge*0.6;
        diffuseColor.rgb = mix(diffuseColor.rgb, vec3(0.32,0.2,0.04), ed*0.8);`);
  };
  bbMat.customProgramCacheKey = () => 'dna-bb';
  for (const s of [0, 1]) {
    const pts = []; for (let i = 0; i <= NBP * 6; i++) { const x = X0 + i * RISE / 6; strandPt(x, s, -999, (pts[i] = new THREE.Vector3())); }
    const m = new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(pts), NBP * 6, 0.12, 10, false), bbMat); dna.add(m);
  }
  // phosphates & base pairs
  const phos = new THREE.InstancedMesh(new THREE.SphereGeometry(0.19, 16, 12), new THREE.MeshStandardMaterial({ color: 0x8fb0ff, roughness: 0.2, metalness: 0.5 }), NBP * 2);
  dna.add(phos);
  const rungGeo = new THREE.CylinderGeometry(0.085, 0.085, 1, 12, 1);
  const glowAttr = new THREE.InstancedBufferAttribute(new Float32Array(NBP * 2), 1);
  rungGeo.setAttribute('aGlow', glowAttr);
  const rungMat = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.35, metalness: 0.1 });
  rungMat.onBeforeCompile = (sh) => {
    sh.vertexShader = sh.vertexShader.replace('#include <common>', '#include <common>\nattribute float aGlow; varying float vGlow;').replace('#include <begin_vertex>', '#include <begin_vertex>\nvGlow = aGlow;');
    sh.fragmentShader = sh.fragmentShader.replace('#include <common>', '#include <common>\nvarying float vGlow;').replace('#include <emissivemap_fragment>', '#include <emissivemap_fragment>\ntotalEmissiveRadiance += vColor.rgb * vGlow;');
  };
  rungMat.customProgramCacheKey = () => 'dna-rung';
  const rungs = new THREE.InstancedMesh(rungGeo, rungMat, NBP * 2);
  dna.add(rungs);
  const BASE = { A: new THREE.Color(0.15, 0.45, 1.0), T: new THREE.Color(1.0, 0.75, 0.15), G: new THREE.Color(0.25, 0.9, 0.4), C: new THREE.Color(0.85, 0.25, 0.65) };
  const PAIR = { A: 'T', T: 'A', G: 'C', C: 'G' };
  const r1 = rng(73);
  const seq = []; for (let i = 0; i < NBP; i++) { const b = 'ATGC'[Math.floor(r1() * 4)]; const nb = r1() < 0.45 ? 'ATGC'[Math.floor(r1() * 4)] : b; seq.push({ b, nb, rr: r1() }); }
  for (let i = 0; i < NBP * 2; i++) rungs.setColorAt(i, new THREE.Color(1, 1, 1));
  // editing complex: orbiting particles + translucent clamp
  const clampMat = new THREE.ShaderMaterial({
    uniforms: { uTime: { value: 0 } },
    vertexShader: `varying vec3 vN; varying vec3 vW; void main(){ vec4 w=modelMatrix*vec4(position,1.0); vW=w.xyz; vN=normalize(mat3(modelMatrix)*normal); gl_Position=projectionMatrix*viewMatrix*w; }`,
    fragmentShader: `uniform float uTime; varying vec3 vN; varying vec3 vW; void main(){ vec3 V=normalize(cameraPosition-vW); float f=pow(1.0-abs(dot(normalize(vN),V)),2.0); gl_FragColor=vec4(vec3(0.1,0.9,0.7)*f*0.22, 1.0); }`,
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide,
  });
  const clampG = new THREE.Group(); dna.add(clampG);
  const torus = new THREE.Mesh(new THREE.TorusGeometry(2.1, 0.45, 24, 64), clampMat); torus.rotation.y = Math.PI / 2; clampG.add(torus);
  const torus2 = new THREE.Mesh(new THREE.TorusGeometry(2.3, 0.12, 12, 64), new THREE.MeshBasicMaterial({ color: new THREE.Color(0.08, 0.75, 0.55) })); torus2.rotation.y = Math.PI / 2; clampG.add(torus2);
  const orb = new Billboards(140, { map: glowSprite(48), blending: THREE.AdditiveBlending, nearFade: [0.1, 0.5] });
  dna.add(orb.mesh);
  const orbD = []; for (let i = 0; i < 140; i++) orbD.push([r1() * 6.28, 1.6 + r1() * 1.4, (r1() - 0.5) * 1.6, 0.6 + r1() * 1.8, r1()]);
  const sparks = new Billboards(160, { map: glowSprite(32), blending: THREE.AdditiveBlending, nearFade: [0.1, 0.4] });
  dna.add(sparks.mesh);
  const sparkD = []; for (let i = 0; i < 160; i++) sparkD.push([r1(), r1() * 6.28, r1() * 3.14, 0.5 + r1()]);
  const incoming = new Billboards(160, { map: glowSprite(48), blending: THREE.AdditiveBlending, nearFade: [0.1, 0.6], fog: { color: DF, density: 0.028 } });
  dna.add(incoming.mesh);
  const incD = []; for (let i = 0; i < 160; i++) incD.push([r1(), r1() * 6.28, 4 + r1() * 8, r1()]);
  // background chromatin helices
  const bgMat = new THREE.MeshStandardMaterial({ color: 0x3a2a90, emissive: new THREE.Color(0.08, 0.04, 0.25), roughness: 0.5 });
  for (let k = 0; k < 6; k++) {
    const pts = [], pts2 = [];
    const yy = (k - 2.5) * 7, zz = -14 - (k % 3) * 9, ang = (k % 2 ? 0.4 : -0.3);
    for (let i = 0; i <= 200; i++) { const x = -40 + i * 0.4, a = i * 0.4 * TWIST / RISE * 0.12; pts.push(new THREE.Vector3(x, yy + Math.cos(a) * 1.0 + x * ang * 0.3, zz + Math.sin(a))); pts2.push(new THREE.Vector3(x, yy + Math.cos(a + OFF) * 1.0 + x * ang * 0.3, zz + Math.sin(a + OFF))); }
    dna.add(new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(pts), 400, 0.13, 6), bgMat));
    dna.add(new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(pts2), 400, 0.13, 6), bgMat));
  }
  const dDust = new Billboards(300, { map: glowSprite(32), blending: THREE.AdditiveBlending, nearFade: [0.2, 1.0], fog: { color: DF, density: 0.028 } });
  dna.add(dDust.mesh);
  const dDustD = []; for (let i = 0; i < 300; i++) dDustD.push([(r1() - 0.5) * 70, (r1() - 0.5) * 40, (r1() - 0.5) * 50 - 5, r1()]);
  // lights
  dna.add(new THREE.HemisphereLight(0x7088ff, 0x0a0820, 0.6));
  const dKey = new THREE.DirectionalLight(0xbfd4ff, 1.8); dKey.position.set(3, 8, 6); dna.add(dKey);
  const dRim = new THREE.DirectionalLight(0x9a60ff, 2.2); dRim.position.set(-4, -3, -8); dna.add(dRim);
  const fLight = new THREE.PointLight(0x40ffd0, 10, 9, 1.6); dna.add(fLight);
  const goldLight = new THREE.PointLight(0xffb040, 0, 14, 1.4); dna.add(goldLight);

  const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), sc = new THREE.Vector3(), pA = new THREE.Vector3(), pB = new THREE.Vector3(), mid = new THREE.Vector3(), dir = new THREE.Vector3(), Y = new THREE.Vector3(0, 1, 0), tmp = new THREE.Vector3();
  const col = new THREE.Color();
  function updateDNA(t, cam) {
    const f = front(t), pulse = heart.pulse(t);
    bbU.uFront.value = f; bbU.uTime.value = t; bbU.uPulse.value = pulse;
    clampMat.uniforms.uTime.value = t;
    for (let i = 0; i < NBP; i++) {
      const x = X0 + i * RISE;
      strandPt(x, 0, f, pA); strandPt(x, 1, f, pB);
      sc.setScalar(1); m4.compose(pA, q.identity(), sc); phos.setMatrixAt(i * 2, m4); m4.compose(pB, q, sc); phos.setMatrixAt(i * 2 + 1, m4);
      const b = bubble(x, f);
      const gap = 0.04 + b * 0.9;
      mid.addVectors(pA, pB).multiplyScalar(0.5);
      const ed = clamp((f - x) / 1.2 + 0.2);       // 0 before the front, 1 after
      const flash = Math.exp(-Math.pow((x - f + 0.6) / 0.5, 2));
      const s = seq[i];
      for (const [k, P, base] of [[0, pA, ed > 0.5 ? s.nb : s.b], [1, pB, PAIR[ed > 0.5 ? s.nb : s.b]]]) {
        dir.subVectors(mid, P); const len = dir.length() - gap / 2; dir.normalize();
        tmp.copy(P).addScaledVector(dir, len / 2 + 0.1);
        q.setFromUnitVectors(Y, dir); sc.set(1, Math.max(0.05, len - 0.12), 1);
        m4.compose(tmp, q, sc); rungs.setMatrixAt(i * 2 + k, m4);
        col.copy(BASE[base]);
        if (ed > 0.5) col.lerp(s.rr < 0.5 ? new THREE.Color(0.1, 1.0, 0.7) : new THREE.Color(1.0, 0.55, 0.1), 0.8);
        rungs.setColorAt(i * 2 + k, col);
        glowAttr.array[i * 2 + k] = 0.06 + ed * (0.35 + 0.3 * pulse) + flash * 1.1;
      }
    }
    phos.instanceMatrix.needsUpdate = true; rungs.instanceMatrix.needsUpdate = true; rungs.instanceColor.needsUpdate = true; glowAttr.needsUpdate = true;
    clampG.position.set(f + 0.2, 0, 0); clampG.rotation.x = t * 1.5; clampG.scale.setScalar(1 + 0.06 * pulse);
    fLight.position.set(f, 1.5, 1.5); fLight.intensity = 2.5 + 2 * pulse;
    goldLight.position.set(f - 8, 3, 3); goldLight.intensity = 6 * smooth(47, 50, t);
    for (let i = 0; i < orb.count; i++) {
      const [a0, r, dx, w, s] = orbD[i]; const a = a0 + t * w;
      orb.set(i, f + dx, Math.cos(a) * r, Math.sin(a) * r, 0.08 + s * 0.1, 0.22, 0); orb.setTint(i, SERUM.r, SERUM.g, SERUM.b);
    }
    orb.commit();
    for (let i = 0; i < sparks.count; i++) {
      const [ph, th, phi, sp] = sparkD[i]; const age = ((t * 1.3 * sp + ph) % 1);
      const rr = age * 2.6;
      sparks.set(i, f - 0.3 + Math.cos(phi) * rr * 0.6, Math.sin(th) * Math.sin(phi) * rr, Math.cos(th) * Math.sin(phi) * rr, 0.05 * (1 - age) + 0.015, (1 - age) * 0.45, 0);
      sparks.setTint(i, 1.0, 0.85 - age * 0.3, 0.4 + age * 0.4);
    }
    sparks.commit();
    for (let i = 0; i < incoming.count; i++) {
      const [ph, th, rr, s] = incD[i]; const u = ((t - 45.5) * (0.25 + s * 0.2) + ph) % 1;
      const p = new THREE.Vector3(f - 14 + Math.cos(th) * rr, Math.sin(th) * rr + 4, -6 + Math.sin(th * 2) * 3).lerp(new THREE.Vector3(f, 0, 0), ease.in(u));
      incoming.set(i, p.x, p.y, p.z, 0.15 + s * 0.15, 0.5 * Math.sin(u * Math.PI), 0); incoming.setTint(i, SERUM.r, SERUM.g, SERUM.b);
    }
    incoming.commit();
    for (let i = 0; i < dDust.count; i++) { const d = dDustD[i]; dDust.set(i, d[0] + Math.sin(t * 0.2 + i) * 0.4, d[1] + Math.cos(t * 0.17 + i) * 0.4, d[2], 0.06 + d[3] * 0.14, 0.3, 0); dDust.setTint(i, 0.55, 0.6, 1.0); }
    dDust.commit();
    // camera: follow the editing front, slow orbit, then pull back to reveal
    const u = smooth(45.5, 54, t);
    const orbitA = lerp(0.9, -0.2, ease.sine(u));
    const dist = lerp(7.2, 6.0, smooth(45.5, 50, t)) + 13 * ease.inOut(smooth(51.2, 54, t));
    const lead = lerp(-2.2, -1.0, u);
    cam.position.set(f + lead - 3 * smooth(51.2, 54, t), Math.sin(orbitA) * dist * 0.55 + 0.8, Math.cos(orbitA) * dist);
    cam.position.x += fbm1(t * 0.4, 41) * 0.15; cam.position.y += fbm1(t * 0.37, 42) * 0.15;
    cam.lookAt(f + 0.6 + 2 * smooth(51.2, 54, t), 0, 0);
    cam.fov = 40;
    return { focus: cam.position.distanceTo(tmp.set(f, 0, 0)) };
  }

  function shots(grade) {
    return {
      cell(t, u, cam) {
        return { scene: cell, camSet: true, near: 0.05, far: 200, update: (tt, c) => updateCell(tt, c),
          post: { ...grade, focus: 12, aperture: 6, maxCoC: 16, flash: Math.max(1 - smooth(41, 41.6, t), smooth(45.2, 45.5, t)), flashColor: [0.85, 0.8, 1.0], zoomBlur: smooth(44.6, 45.5, t) * 0.25 } };
      },
      dna(t, u, cam) {
        const r = { scene: dna, camSet: true, near: 0.05, far: 150,
          post: { ...grade, focus: 5, aperture: 7, maxCoC: 18, flash: Math.max(1 - smooth(45.5, 46.1, t), smooth(53.6, 54, t)), flashColor: [0.9, 1.0, 1.0] } };
        r.update = (tt, c) => { r.post.focus = updateDNA(tt, c).focus; };
        return r;
      },
    };
  }
  return { cell, dna, shots, updateCell, updateDNA };
}
