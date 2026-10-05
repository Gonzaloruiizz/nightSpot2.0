import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { GLTFExporter } from 'three/addons/exporters/GLTFExporter.js';
import { buildLab } from './lab.js';
import { buildBlood } from './blood.js';
import { buildDNA } from './dna.js';
import { Post } from './post.js';
import { makeShots } from './shots.js';
import { makeHeart } from './heart.js';
import { makeOverlay } from './overlay.js';

const q = new URLSearchParams(location.search);
const cfg = await (await fetch('timeline.json')).json();
const W = cfg.width, H = cfg.height;

// fit the 1920x1080 stage into the window for live preview
const stage = document.getElementById('stage');
const fit = () => { const s = Math.min(innerWidth / 1920, innerHeight / 1080); stage.style.transform = `translate(${(innerWidth - 1920 * s) / 2}px, ${(innerHeight - 1080 * s) / 2}px) scale(${s})`; };
if (!q.has('render')) { fit(); addEventListener('resize', fit); }

const canvas = document.getElementById('gl');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: false, preserveDrawingBuffer: true, powerPreference: 'high-performance' });
renderer.setPixelRatio(1); renderer.setSize(W, H, false);
renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.NoToneMapping;

const gltf = new GLTFLoader();
const tl = new THREE.TextureLoader();
const [lpsG, xbot, lpsMap, lpsNormal] = await Promise.all([
  gltf.loadAsync('assets/LeePerrySmith.glb'), gltf.loadAsync('assets/Xbot.glb'),
  tl.loadAsync('assets/Map-COL.jpg'), tl.loadAsync('assets/Infinite-Level_02_Tangent_SmoothUV.jpg'),
]);
lpsMap.colorSpace = THREE.SRGBColorSpace; lpsMap.flipY = false; lpsNormal.flipY = false;
await document.fonts.load('22px ShareTech'); await document.fonts.load('300 46px Rajdhani'); await document.fonts.load('200 96px Exo2');

const heart = makeHeart(cfg);
const lab = buildLab(renderer, { lps: lpsG.scene, xbot, lpsMap, lpsNormal }, heart);
const blood = buildBlood(renderer, heart);
const dna = buildDNA(renderer, heart);
const shots = makeShots({ lab, blood, dna, heart, cfg });
const post = new Post(renderer, W, H);
const camera = new THREE.PerspectiveCamera(35, W / H, 0.01, 120);
const overlay = makeOverlay(document.getElementById('overlay'), heart);
const blackScene = new THREE.Scene(); blackScene.background = new THREE.Color(0);

let camOverride = null;
function renderAt(t) {
  const s = shots.setup(t, camera);
  if (camOverride) { camera.position.set(...camOverride.p); camera.lookAt(...camOverride.t); camera.fov = camOverride.fov; s.post = { ...(s.post || {}), focus: camera.position.distanceTo(new THREE.Vector3(...camOverride.t)), fade: 0, flash: 0 }; }
  camera.near = s.near ?? 0.01; camera.far = s.far ?? 60; camera.updateProjectionMatrix();
  if (s.lab) lab.update(t, camera, s.id);
  if (s.update) { s.update(t, camera); camera.updateProjectionMatrix(); }
  const p = { ...(s.post || {}), frame: Math.round(t * cfg.fps) };
  post.render(s.scene || blackScene, camera, p);
  overlay(t, s.id);
  return s.id;
}
window.renderAt = renderAt;
window.CFG = cfg;
window.setCam = (c) => { camOverride = c; };
// Export the lab (geometry + materials) at time t for the photoreal Blender version
window.exportLab = async (t) => {
  renderAt(t);
  const hidden = [];
  lab.scene.traverse(o => { if (['Particles', 'FogLayer', 'Shaft', 'Holo'].includes(o.name) || o.isLight) { if (o.visible) { o.visible = false; hidden.push(o); } } });
  const buf = await new GLTFExporter().parseAsync(lab.scene, { binary: true, onlyVisible: true, maxTextureSize: 1024 });
  hidden.forEach(o => (o.visible = true));
  let b64 = ''; const u8 = new Uint8Array(buf); for (let i = 0; i < u8.length; i += 32768) b64 += String.fromCharCode.apply(null, u8.subarray(i, i + 32768));
  const R = lab.refs, w2 = (v) => v.toArray();
  const tip = new THREE.Vector3(); R.robot.tip.getWorldPosition(tip);
  const info = { inj: w2(lab.injWorld), injN: w2(lab.injNormal), eyeL: w2(lab.objToWorld(R.skin.userData.U.uEyeL.value)), eyeR: w2(lab.objToWorld(R.skin.userData.U.uEyeR.value)), face: w2(lab.objToWorld(new THREE.Vector3(0, 1.5, 2.0))), tip: w2(tip), injObj: w2(R.skin.userData.U.uInj.value) };
  return { glb: btoa(b64), info };
};

// warm up: compile every scene once
for (const t of [1, 30, 43, 47, 55]) renderAt(t);
window.READY = true;

if (q.has('t')) renderAt(parseFloat(q.get('t')));
else if (!q.has('render')) {
  const t0 = performance.now() / 1000 - (parseFloat(q.get('start')) || 0);
  const loop = () => { const t = (performance.now() / 1000 - t0) % cfg.duration; renderAt(t); requestAnimationFrame(loop); };
  loop();
}
