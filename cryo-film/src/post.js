import * as THREE from 'three';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { FullScreenQuad } from 'three/addons/postprocessing/Pass.js';
import { FXAAShader } from 'three/addons/shaders/FXAAShader.js';

const VS = `varying vec2 vUv; void main(){ vUv=uv; gl_Position=vec4(position.xy,0.0,1.0); }`;

export class Post {
  constructor(renderer, W, H) {
    this.r = renderer; this.W = W; this.H = H;
    const hf = { type: THREE.HalfFloatType, minFilter: THREE.LinearFilter, magFilter: THREE.LinearFilter };
    this.rtScene = new THREE.WebGLRenderTarget(W, H, { ...hf, depthTexture: new THREE.DepthTexture(W, H, THREE.FloatType) });
    this.rtHalf = new THREE.WebGLRenderTarget(W >> 1, H >> 1, hf);
    this.rtDOF = new THREE.WebGLRenderTarget(W, H, hf);
    this.rtStreak = new THREE.WebGLRenderTarget(W >> 2, H >> 2, hf);
    this.rtLDR = new THREE.WebGLRenderTarget(W, H, { minFilter: THREE.LinearFilter, magFilter: THREE.LinearFilter });
    this.rtLDR2 = new THREE.WebGLRenderTarget(W, H, { minFilter: THREE.LinearFilter, magFilter: THREE.LinearFilter });
    this.bloom = new UnrealBloomPass(new THREE.Vector2(W, H), 0.7, 0.55, 0.85);
    this.quad = new FullScreenQuad();

    const DEPTH = `
      uniform float uNear, uFar, uFocus, uAperture, uMaxCoC;
      float linZ(float d){ float z=d*2.0-1.0; return 2.0*uNear*uFar/(uFar+uNear-z*(uFar-uNear)); }
      float coc(float z){ return clamp(uAperture*abs(1.0/uFocus-1.0/z), 0.0, uMaxCoC); }`;
    this.dofBlur = new THREE.ShaderMaterial({
      uniforms: { tColor: { value: null }, tDepth: { value: null }, uPx: { value: new THREE.Vector2(2 / W, 2 / H) }, uNear: { value: 0.1 }, uFar: { value: 100 }, uFocus: { value: 2 }, uAperture: { value: 0 }, uMaxCoC: { value: 16 } },
      vertexShader: VS,
      fragmentShader: `uniform sampler2D tColor, tDepth; uniform vec2 uPx; varying vec2 vUv; ${DEPTH}
        void main(){
          float cz = linZ(texture2D(tDepth, vUv).r);
          float cs = coc(cz) * 0.5;               // in half-res pixels
          vec3 col = texture2D(tColor, vUv).rgb; float tot = 1.0;
          float rad = 1.0;
          for (int i = 0; i < 56; i++) {
            float ang = float(i) * 2.39996323;
            vec2 tc = vUv + vec2(cos(ang), sin(ang)) * uPx * rad;
            vec3 sc = texture2D(tColor, tc).rgb;
            float sz = linZ(texture2D(tDepth, tc).r);
            float ss = coc(sz) * 0.5;
            if (sz > cz) ss = clamp(ss, 0.0, cs * 2.0);
            float m = smoothstep(rad - 0.5, rad + 0.5, ss);
            col += mix(col / tot, sc, m); tot += 1.0;
            rad += 1.6 / rad;
            if (rad > uMaxCoC * 0.5) break;
          }
          gl_FragColor = vec4(col / tot, 1.0);
        }`,
    });
    this.dofComp = new THREE.ShaderMaterial({
      uniforms: { tColor: { value: null }, tBlur: { value: null }, tDepth: { value: null }, uNear: { value: 0.1 }, uFar: { value: 100 }, uFocus: { value: 2 }, uAperture: { value: 0 }, uMaxCoC: { value: 16 } },
      vertexShader: VS,
      fragmentShader: `uniform sampler2D tColor, tBlur, tDepth; varying vec2 vUv; ${DEPTH}
        void main(){
          float c = coc(linZ(texture2D(tDepth, vUv).r));
          vec3 s = texture2D(tColor, vUv).rgb, b = texture2D(tBlur, vUv).rgb;
          gl_FragColor = vec4(mix(s, b, smoothstep(0.6, 3.0, c)), 1.0);
        }`,
    });
    this.streak = new THREE.ShaderMaterial({
      uniforms: { tBright: { value: null }, uPx: { value: 1 / (W >> 1) } },
      vertexShader: VS,
      fragmentShader: `uniform sampler2D tBright; uniform float uPx; varying vec2 vUv;
        void main(){ vec3 s = vec3(0.0); float tw = 0.0;
          for (int i = -24; i <= 24; i++){ float f = float(i); float w = exp(-abs(f)*0.11); s += texture2D(tBright, vUv + vec2(f*uPx*9.0, 0.0)).rgb * w; tw += w; }
          gl_FragColor = vec4(s / tw, 1.0); }`,
    });
    this.grade = new THREE.ShaderMaterial({
      uniforms: {
        tColor: { value: null }, tStreak: { value: null },
        uExposure: { value: 1 }, uContrast: { value: 1.05 }, uSat: { value: 1 },
        uLift: { value: new THREE.Vector3(0, 0, 0) }, uGamma: { value: new THREE.Vector3(1, 1, 1) }, uGain: { value: new THREE.Vector3(1, 1, 1) },
        uShadowTint: { value: new THREE.Vector3(0.0, 0.03, 0.05) }, uHighTint: { value: new THREE.Vector3(0.04, 0.02, 0.0) },
        uStreak: { value: 0.35 }, uStreakTint: { value: new THREE.Color(0.35, 0.65, 1.0) },
      },
      vertexShader: VS,
      fragmentShader: `uniform sampler2D tColor, tStreak; uniform float uExposure, uContrast, uSat, uStreak;
        uniform vec3 uLift, uGamma, uGain, uShadowTint, uHighTint, uStreakTint; varying vec2 vUv;
        vec3 rrt(vec3 v){ vec3 a=v*(v+0.0245786)-0.000090537; vec3 b=v*(0.983729*v+0.4329510)+0.238081; return a/b; }
        vec3 aces(vec3 c){ const mat3 I=mat3(vec3(0.59719,0.07600,0.02840),vec3(0.35458,0.90834,0.13383),vec3(0.04823,0.01566,0.83777));
          const mat3 O=mat3(vec3(1.60475,-0.10208,-0.00327),vec3(-0.53108,1.10813,-0.07276),vec3(-0.07367,-0.00605,1.07602));
          c = I*c; c = rrt(c); c = O*c; return clamp(c,0.0,1.0); }
        void main(){
          vec3 c = texture2D(tColor, vUv).rgb;
          c += texture2D(tStreak, vUv).rgb * uStreakTint * uStreak;
          c *= uExposure / 0.6;
          c = aces(c);
          c = pow(max(c, 0.0), vec3(1.0/2.2));
          float l = dot(c, vec3(0.2126,0.7152,0.0722));
          c = mix(vec3(l), c, uSat);
          c += uShadowTint * (1.0 - smoothstep(0.0, 0.5, l)) + uHighTint * smoothstep(0.5, 1.0, l);
          c = (c - 0.5) * uContrast + 0.5;
          c = uGain * (c + uLift * (1.0 - c));
          c = pow(max(c, 0.0), 1.0 / uGamma);
          gl_FragColor = vec4(clamp(c, 0.0, 1.0), 1.0);
        }`,
    });
    this.fxaa = new THREE.ShaderMaterial(FXAAShader);
    this.fxaa.uniforms.resolution.value.set(1 / W, 1 / H);
    this.final = new THREE.ShaderMaterial({
      uniforms: { tColor: { value: null }, uCA: { value: 0.0015 }, uGrain: { value: 0.06 }, uVignette: { value: 0.35 }, uFade: { value: 0 }, uFlash: { value: 0 }, uFlashColor: { value: new THREE.Color(0.8, 1, 1) }, uFrame: { value: 0 }, uAspect: { value: W / H }, uBlur: { value: 0 } },
      vertexShader: VS,
      fragmentShader: `uniform sampler2D tColor; uniform float uCA, uGrain, uVignette, uFade, uFlash, uFrame, uAspect, uBlur; uniform vec3 uFlashColor; varying vec2 vUv;
        float h(vec2 p){ return fract(sin(dot(p, vec2(12.9898,78.233)) + uFrame*0.6180339) * 43758.5453); }
        void main(){
          vec2 d = vUv - 0.5; float r2 = dot(d*vec2(uAspect,1.0), d*vec2(uAspect,1.0));
          vec2 off = d * (uCA * (1.0 + r2 * 6.0));
          vec3 c;
          if (uBlur > 0.0) {
            c = vec3(0.0); for (int i = 0; i < 12; i++){ float f = float(i)/11.0; vec2 uv = 0.5 + d * (1.0 - uBlur * f); c += vec3(texture2D(tColor, uv + off).r, texture2D(tColor, uv).g, texture2D(tColor, uv - off).b); } c /= 12.0;
          } else {
            c = vec3(texture2D(tColor, vUv + off).r, texture2D(tColor, vUv).g, texture2D(tColor, vUv - off).b);
          }
          c *= 1.0 - uVignette * smoothstep(0.15, 1.1, r2);
          c = mix(c, uFlashColor, uFlash);
          float g = h(vUv * 1000.0) + h(vUv * 517.0 + 3.1) - 1.0;
          c += g * uGrain * (0.35 + 0.65 * (1.0 - dot(c, vec3(0.33))));
          c *= 1.0 - uFade;
          gl_FragColor = vec4(c, 1.0);
        }`,
    });
  }

  pass(mat, target) { this.quad.material = mat; this.r.setRenderTarget(target); this.quad.render(this.r); }

  render(scene, camera, p) {
    const r = this.r;
    r.setRenderTarget(this.rtScene); r.clear(); r.render(scene, camera);
    let src = this.rtScene;
    if (p.aperture > 0) {
      for (const m of [this.dofBlur, this.dofComp]) {
        m.uniforms.uNear.value = camera.near; m.uniforms.uFar.value = camera.far;
        m.uniforms.uFocus.value = p.focus; m.uniforms.uAperture.value = p.aperture; m.uniforms.uMaxCoC.value = p.maxCoC ?? 18;
        m.uniforms.tDepth.value = this.rtScene.depthTexture;
      }
      this.dofBlur.uniforms.tColor.value = this.rtScene.texture; this.pass(this.dofBlur, this.rtHalf);
      this.dofComp.uniforms.tColor.value = this.rtScene.texture; this.dofComp.uniforms.tBlur.value = this.rtHalf.texture; this.pass(this.dofComp, this.rtDOF);
      src = this.rtDOF;
    }
    this.bloom.strength = p.bloom ?? 0.7; this.bloom.radius = p.bloomRadius ?? 0.55; this.bloom.threshold = p.bloomThreshold ?? 0.85;
    this.bloom.render(r, null, src, 0, false);
    this.streak.uniforms.tBright.value = this.bloom.renderTargetBright.texture; this.pass(this.streak, this.rtStreak);
    const G = this.grade.uniforms;
    G.tColor.value = src.texture; G.tStreak.value = this.rtStreak.texture;
    G.uExposure.value = p.exposure ?? 1; G.uContrast.value = p.contrast ?? 1.05; G.uSat.value = p.sat ?? 1;
    G.uLift.value.fromArray(p.lift ?? [0, 0, 0]); G.uGamma.value.fromArray(p.gamma ?? [1, 1, 1]); G.uGain.value.fromArray(p.gain ?? [1, 1, 1]);
    G.uShadowTint.value.fromArray(p.shadowTint ?? [0.0, 0.025, 0.045]); G.uHighTint.value.fromArray(p.highTint ?? [0.035, 0.015, 0.0]);
    G.uStreak.value = p.streak ?? 0.35;
    if (p.streakTint) G.uStreakTint.value.setRGB(...p.streakTint);
    this.pass(this.grade, this.rtLDR);
    this.fxaa.uniforms.tDiffuse.value = this.rtLDR.texture; this.pass(this.fxaa, this.rtLDR2);
    const F = this.final.uniforms;
    F.tColor.value = this.rtLDR2.texture; F.uCA.value = p.ca ?? 0.0015; F.uGrain.value = p.grain ?? 0.055; F.uVignette.value = p.vignette ?? 0.4;
    F.uFade.value = p.fade ?? 0; F.uFlash.value = p.flash ?? 0; F.uFrame.value = p.frame ?? 0; F.uBlur.value = p.zoomBlur ?? 0;
    if (p.flashColor) F.uFlashColor.value.setRGB(...p.flashColor);
    this.pass(this.final, null);
  }
}
