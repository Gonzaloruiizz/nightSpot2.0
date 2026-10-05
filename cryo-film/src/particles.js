import * as THREE from 'three';

// Camera-facing instanced quads with per-instance position/size/alpha/rotation/tint.
// Deterministic: caller fills the arrays every frame.
export class Billboards {
  constructor(count, { map, blending = THREE.NormalBlending, intensity = 1, nearFade = [0.05, 0.4], fog = null } = {}) {
    this.count = count;
    const g = new THREE.InstancedBufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute([-0.5, -0.5, 0, 0.5, -0.5, 0, 0.5, 0.5, 0, -0.5, 0.5, 0], 3));
    g.setAttribute('uv', new THREE.Float32BufferAttribute([0, 0, 1, 0, 1, 1, 0, 1], 2));
    g.setIndex([0, 1, 2, 0, 2, 3]);
    this.offset = new THREE.InstancedBufferAttribute(new Float32Array(count * 3), 3);
    this.data = new THREE.InstancedBufferAttribute(new Float32Array(count * 4), 4); // size, alpha, rot, unused
    this.tint = new THREE.InstancedBufferAttribute(new Float32Array(count * 3).fill(1), 3);
    for (const a of [this.offset, this.data, this.tint]) a.setUsage(THREE.DynamicDrawUsage);
    g.setAttribute('offset', this.offset); g.setAttribute('data', this.data); g.setAttribute('tint', this.tint);
    g.instanceCount = count;
    this.material = new THREE.ShaderMaterial({
      uniforms: {
        map: { value: map }, uIntensity: { value: intensity }, uNear: { value: new THREE.Vector2(...nearFade) },
        uFogColor: { value: new THREE.Color(fog ? fog.color : 0x000000) }, uFogDensity: { value: fog ? fog.density : 0 },
      },
      vertexShader: /* glsl */`
        attribute vec3 offset; attribute vec4 data; attribute vec3 tint;
        uniform vec2 uNear; varying vec2 vUv; varying float vA; varying vec3 vC; varying float vDepth;
        void main(){
          vec4 mv = modelViewMatrix * vec4(offset, 1.0);
          float c = cos(data.z), s = sin(data.z);
          mv.xy += mat2(c, s, -s, c) * position.xy * data.x;
          gl_Position = projectionMatrix * mv;
          vUv = uv; vC = tint; vDepth = -mv.z;
          vA = data.y * smoothstep(uNear.x, uNear.y, -mv.z);
        }`,
      fragmentShader: /* glsl */`
        uniform sampler2D map; uniform float uIntensity; uniform vec3 uFogColor; uniform float uFogDensity;
        varying vec2 vUv; varying float vA; varying vec3 vC; varying float vDepth;
        void main(){
          vec4 t = texture2D(map, vUv);
          float a = t.a * vA;
          if (a < 0.002) discard;
          float f = 1.0 - exp(-uFogDensity * uFogDensity * vDepth * vDepth);
          vec3 col = mix(vC * t.rgb * uIntensity, uFogColor, f);
          gl_FragColor = vec4(col, a);
        }`,
      transparent: true, depthWrite: false, blending,
    });
    this.mesh = new THREE.Mesh(g, this.material);
    this.mesh.frustumCulled = false;
  }
  set(i, x, y, z, size, alpha, rot = 0) {
    this.offset.array[i * 3] = x; this.offset.array[i * 3 + 1] = y; this.offset.array[i * 3 + 2] = z;
    this.data.array[i * 4] = size; this.data.array[i * 4 + 1] = alpha; this.data.array[i * 4 + 2] = rot;
  }
  setTint(i, r, g, b) { this.tint.array[i * 3] = r; this.tint.array[i * 3 + 1] = g; this.tint.array[i * 3 + 2] = b; }
  commit() { this.offset.needsUpdate = true; this.data.needsUpdate = true; this.tint.needsUpdate = true; }
}
