// Render the film frame by frame with headless Chromium (SwiftShader WebGL).
// usage: node render.mjs <outDir> <worker> <workers> [port]
import { chromium } from 'playwright';
import fs from 'node:fs';
const [,, outDir = 'frames', worker = '0', workers = '1', port = '8123'] = process.argv;
fs.mkdirSync(outDir, { recursive: true });
const cfg = JSON.parse(fs.readFileSync('timeline.json', 'utf8'));
const total = Math.round(cfg.duration * cfg.fps);
const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
const p = await b.newPage({ viewport: { width: 1920, height: 1080 } });
p.on('pageerror', e => console.log('err:', e.message));
await p.goto(`http://localhost:${port}/index.html?render`);
await p.waitForFunction(() => window.READY, null, { timeout: 600000 });
const t0 = Date.now(); let n = 0;
for (let f = +worker; f < total; f += +workers) {
  const file = `${outDir}/${String(f).padStart(5, '0')}.jpg`;
  if (fs.existsSync(file)) continue;
  await p.evaluate((t) => window.renderAt(t), f / cfg.fps);
  await p.screenshot({ path: file + '.tmp.jpg', type: 'jpeg', quality: 94 });
  fs.renameSync(file + '.tmp.jpg', file);
  n++;
  if (n % 25 === 0) console.log(`worker ${worker}: frame ${f}/${total} · ${((Date.now() - t0) / n / 1000).toFixed(2)} s/frame`);
}
console.log(`worker ${worker} done (${n} frames, ${((Date.now() - t0) / 1000).toFixed(0)} s)`);
await b.close();
