// Render specific times to PNG for previewing: node shot.mjs out_prefix t1 t2 ...
import { chromium } from 'playwright';
const [,, prefix, ...times] = process.argv;
const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
const p = await b.newPage({ viewport: { width: 1920, height: 1080 } });
p.on('console', m => { const s = m.text(); if (!s.includes('GPU stall')) console.log('console:', s); });
p.on('pageerror', e => console.log('err:', e.message));
let t0 = Date.now();
await p.goto('http://localhost:8123/index.html?render'); await p.waitForFunction(() => window.READY, null, { timeout: 600000 });
console.log('ready in', Date.now() - t0, 'ms');
for (const t of times) {
  t0 = Date.now();
  await p.evaluate((t) => window.renderAt(t), parseFloat(t));
  await p.screenshot({ path: `${prefix}_${t}.jpg`, type: 'jpeg', quality: 88 });
  console.log('t=', t, Date.now() - t0, 'ms');
}
await b.close();
