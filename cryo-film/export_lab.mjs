import { chromium } from 'playwright';
import fs from 'node:fs';
const out = process.argv[2]; const times = process.argv.slice(3).map(Number);
fs.mkdirSync(out, { recursive: true });
const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
const p = await b.newPage({ viewport: { width: 1920, height: 1080 } });
p.on('pageerror', e => console.log('err:', e.message));
p.on('console', m => { const s = m.text(); if (/GLTFExporter|error/i.test(s)) console.log('console:', s.slice(0, 200)); });
await p.goto('http://localhost:8123/index.html?render'); await p.waitForFunction(() => window.READY, null, { timeout: 600000 });
for (const t of times) {
  const r = await p.evaluate((t) => window.exportLab(t), t);
  fs.writeFileSync(`${out}/lab_${t}.glb`, Buffer.from(r.glb, 'base64'));
  fs.writeFileSync(`${out}/lab_${t}.json`, JSON.stringify(r.info, null, 1));
  console.log('exported', t, (r.glb.length * 0.75 / 1e6).toFixed(1), 'MB');
}
await b.close();
