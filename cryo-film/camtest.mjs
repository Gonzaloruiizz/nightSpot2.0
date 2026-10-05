// node camtest.mjs prefix '[[t,[px,py,pz],[tx,ty,tz],fov], ...]'
import { chromium } from 'playwright';
const [,, prefix, json] = process.argv;
const list = JSON.parse(json);
const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
const p = await b.newPage({ viewport: { width: 1920, height: 1080 } });
p.on('pageerror', e => console.log('err:', e.message)); p.on('console', m => { const s = m.text(); if (/error|ERROR/.test(s)) console.log('console:', s.slice(0, 600)); });
await p.goto('http://localhost:8123/index.html?render'); await p.waitForFunction(() => window.READY, null, { timeout: 600000 });
let i = 0;
for (const [t, pos, tgt, fov] of list) {
  await p.evaluate(([t, pos, tgt, fov]) => { window.setCam(pos ? { p: pos, t: tgt, fov } : null); window.renderAt(t); }, [t, pos, tgt, fov]);
  await p.screenshot({ path: `${prefix}_${i++}.jpg`, type: 'jpeg', quality: 85, clip: { x: 0, y: 138, width: 1920, height: 804 } });
}
await b.close();
