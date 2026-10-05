import * as THREE from 'three';
import { NOISE, BUMP } from './glsl.js';

// Skin material for the frozen subject: frost, thaw front, glowing veins,
// crystalline scales and growths that spread from the injection point.
export function makeSkinMaterial({ map, normalMap }) {
  const U = {
    uTime: { value: 0 },
    uFrost: { value: 1 },
    uFront: { value: -2 },      // radius (object units) of the mutation front
    uLocal: { value: 0 },       // local glow around the injection port
    uVein: { value: 1 },
    uScale: { value: 0 },
    uDisp: { value: 0 },
    uPulse: { value: 0 },
    uEye: { value: 0 },
    uInj: { value: new THREE.Vector3() },
    uEyeL: { value: new THREE.Vector3(0.62, 1.62, 1.9) },
    uEyeR: { value: new THREE.Vector3(-0.72, 1.62, 1.9) },
    uCam: { value: new THREE.Vector3() },
    uObjScale: { value: 0.052 },
    uVeinColor: { value: new THREE.Color(0.08, 1.0, 0.72) },
    uEyeColor: { value: new THREE.Color(0.55, 1.0, 0.95) },
  };
  const mat = new THREE.MeshStandardMaterial({ map, normalMap, normalScale: new THREE.Vector2(0.9, 0.9), roughness: 0.52, metalness: 0.0 });
  mat.userData.U = U;

  const COMMON = /* glsl */`
    uniform float uTime, uFrost, uFront, uLocal, uVein, uScale, uDisp, uPulse, uEye, uObjScale;
    uniform vec3 uInj, uEyeL, uEyeR, uCam, uVeinColor, uEyeColor;
    varying vec3 vObj; varying vec3 vObjN;
    ${NOISE}
    float frontDist(vec3 p){ return distance(p, uInj) + snoise(p*0.55+3.0)*0.9; }
    // growth height (object units) behind the front
    float growth(vec3 p){
      float d = frontDist(p);
      float m = smoothstep(uFront-0.6, uFront-3.0, d) * uDisp;
      if (m <= 0.0) return 0.0;
      float r = 1.0 - abs(snoise(p*0.42 + vec3(3.1,7.7,1.3)));
      return pow(r, 5.0) * 0.2 * m;
    }
  `;

  mat.onBeforeCompile = (sh) => {
    Object.assign(sh.uniforms, U);
    sh.vertexShader = sh.vertexShader
      .replace('#include <common>', '#include <common>\n' + COMMON)
      .replace('#include <begin_vertex>', `#include <begin_vertex>
        vObj = position; vObjN = normal;
        transformed += normal * growth(position);`);
    sh.fragmentShader = sh.fragmentShader
      .replace('#include <common>', '#include <common>\n' + COMMON + BUMP + `
        float gFrost, gScale, gAlive; vec3 gEmit; float gH;`)
      .replace('#include <map_fragment>', `#include <map_fragment>
        {
          vec3 p = vObj;
          float d = frontDist(p);
          // ---------- frozen look ----------
          vec3 skin = diffuseColor.rgb;
          float lum = dot(skin, vec3(0.3,0.59,0.11));
          vec3 frozen = mix(skin, vec3(lum)*vec3(0.74,0.86,1.0), 0.82) * 0.82 + vec3(0.03,0.05,0.08);
          gAlive = smoothstep(uFront+0.4, uFront-1.2, d);           // thawed region
          vec3 alive = mix(skin, vec3(lum), 0.35) * vec3(1.0, 0.9, 0.9);
          vec3 c = mix(frozen, alive, gAlive);
          float fn = snoise(p*5.5)*0.6 + snoise(p*13.0)*0.4;
          float rime = smoothstep(-0.1, 0.6, fn + vObjN.z*0.35 - 0.1);
          gFrost = uFrost * (0.35 + 0.65*rime) * (1.0 - gAlive);
          c = mix(c, vec3(0.8,0.88,0.96), gFrost*0.42);
          // ---------- scales ----------
          gScale = 0.0; gH = 0.0; gEmit = vec3(0.0);
          float scaleMask = smoothstep(-0.15, 0.35, snoise(p*0.38 + 7.0) + 0.15 - smoothstep(1.6, 2.4, p.z)*smoothstep(2.6, 1.6, abs(p.y-1.4))*0.5);
          float sm = smoothstep(uFront-1.6, uFront-4.0, d) * uScale * scaleMask;
          if (sm > 0.001) {
            vec3 v = voronoi3(p*3.2);
            float edge = v.y - v.x;
            float border = 1.0 - smoothstep(0.02, 0.09, edge);
            vec3 V = normalize(uCam - p);
            float hue = fract(v.z*0.35 + dot(normalize(vObjN), V)*0.9 + 0.55);
            vec3 iri = 0.5 + 0.5*cos(6.2831*(hue + vec3(0.0,0.33,0.67)));
            float fr = pow(1.0 - abs(dot(normalize(vObjN), V)), 2.0);
            vec3 scaleCol = mix(vec3(0.05,0.075,0.085), vec3(0.32,0.42,0.46), v.z*0.6) + iri*fr*0.22;
            c = mix(c, mix(scaleCol, vec3(0.008,0.015,0.02), border), sm);
            gScale = sm;
            gH += smoothstep(0.0, 0.22, edge) * 0.045 * sm;
            gEmit += uVeinColor * border * sm * (0.12 + 0.3*uPulse);
          }
          // ---------- veins ----------
          vec3 w = p*0.9 + 0.45*vec3(snoise(p*0.5), snoise(p*0.5+17.0), snoise(p*0.5+31.0));
          float n1 = abs(snoise(w));
          float n2 = abs(snoise(w*2.6 + 5.0));
          float line = (1.0 - smoothstep(0.0, 0.055, n1)) + 0.6*(1.0 - smoothstep(0.0, 0.05, n2));
          float halo = (1.0 - smoothstep(0.0, 0.28, n1)) * 0.25;
          float inside = smoothstep(uFront, uFront-1.0, d);
          float rim = exp(-pow((d-uFront)/0.45, 2.0));
          float local = uLocal * exp(-pow(distance(p, uInj)/1.2, 2.0));
          float vein = (line*0.8 + halo) * (inside*(0.13+0.25*uPulse) + rim*0.7 + local*0.6) * uVein;
          gEmit += uVeinColor * vein;
          c *= 1.0 - min(line*inside*0.35, 0.5);   // dark vein traces on the skin
          gH -= line * 0.012 * (inside + local);   // veins raised
          // ---------- eyes ----------
          float e = exp(-pow(distance(p,uEyeL)/0.38,2.0)) + exp(-pow(distance(p,uEyeR)/0.38,2.0));
          gEmit += uEyeColor * e * uEye * 0.9;
          gEmit += uEyeColor * (exp(-pow(distance(p,uEyeL)/1.3,2.0)) + exp(-pow(distance(p,uEyeR)/1.3,2.0))) * uEye * 0.22;
          // frost glints
          float gl = smoothstep(0.78, 0.95, snoise(p*24.0)) * smoothstep(0.35, 0.9, snoise(p*6.0 + uCam*1.8));
          gEmit += vec3(0.8,0.9,1.0) * gl * gFrost * 0.5;
          diffuseColor.rgb = c;
        }`)
      .replace('#include <roughnessmap_fragment>', `#include <roughnessmap_fragment>
        roughnessFactor = mix(roughnessFactor, 0.8, gFrost);
        roughnessFactor = mix(roughnessFactor, 0.22, gScale);`)
      .replace('#include <metalnessmap_fragment>', `#include <metalnessmap_fragment>
        metalnessFactor = mix(metalnessFactor, 0.45, gScale*0.8);`)
      .replace('#include <normal_fragment_maps>', `#include <normal_fragment_maps>
        {
          float h = (gH + growth(vObj)) * uObjScale;
          normal = bumpNormal(-vViewPosition, normal, h, faceDirection);
        }`)
      .replace('#include <emissivemap_fragment>', `#include <emissivemap_fragment>
        totalEmissiveRadiance += gEmit;`);
  };
  mat.customProgramCacheKey = () => 'skin-v1';
  return mat;
}
