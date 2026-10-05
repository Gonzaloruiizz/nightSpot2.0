import { clamp, smooth } from './util.js';

// Cinematic text overlays (HTML, captured with the frame)
const CUES = [
  { a: 1.4, b: 6.6, cls: 'loc', html: 'INSTALACIÓN CRIOGÉNICA ÁRTICA<br><span>SECTOR 7 · NIVEL −4 · 03:47 h</span>', type: true },
  { a: 8.6, b: 13.6, cls: 'hud', html: 'SUJETO K-17 · CRIOSTASIS: 2.847 DÍAS<br>TEMP. NÚCLEO −196,0 °C · ACTIVIDAD CEREBRAL: 0,00 %', type: true },
  { a: 14.6, b: 19.6, cls: 'hud', html: 'PROTOCOLO LÁZARO · FASE 3<br>APERTURA DE CÁPSULA AUTORIZADA', type: true },
  { a: 20.6, b: 24.2, cls: 'hud', html: 'SUERO Λ-9 · VECTOR DE TERAPIA GÉNICA<br>DOSIS 12 ml · INYECCIÓN CAROTÍDEA', type: true },
  { a: 30.4, b: 36.0, cls: 'hud', html: 'ARTERIA CARÓTIDA · AUMENTO ×12.000<br>NANOPORTADORES Λ-9: 2,4 × 10¹² · FLUJO ESTABLE', type: true },
  { a: 41.5, b: 45.2, cls: 'hud', html: 'CÉLULA DIANA · AUMENTO ×85.000<br>PENETRACIÓN DE MEMBRANA', type: true },
  { a: 46.5, b: 53.6, cls: 'hud', html: 'NÚCLEO CELULAR · CROMOSOMA 17<br>REESCRITURA DE ADN EN CURSO · <b id="bp">0</b> pb', type: true },
  { a: 55.0, b: 60.6, cls: 'hud warn', html: 'ALERTA · MUTACIÓN EPIDÉRMICA NO PREVISTA<br>TEMPERATURA CORPORAL EN ASCENSO', type: true },
  { a: 61.6, b: 65.8, cls: 'hud warn', html: 'ACTIVIDAD CARDÍACA: <b id="lpm">0</b> LPM<br>ACTIVIDAD CEREBRAL: <b id="eeg">0</b> %', type: true },
];

export function makeOverlay(root, heart) {
  const els = CUES.map(c => {
    const d = document.createElement('div'); d.className = 'cue ' + c.cls; d.innerHTML = c.html; root.appendChild(d);
    return { c, d };
  });
  const title = document.createElement('div'); title.className = 'title';
  title.innerHTML = '<div class="t1">PROYECTO LÁZARO</div><div class="t2">LA MUERTE SOLO FUE UNA PAUSA</div>';
  root.appendChild(title);
  const rec = document.createElement('div'); rec.className = 'rec'; root.appendChild(rec);

  return function update(t, shotId) {
    for (const { c, d } of els) {
      const vis = smooth(c.a, c.a + 0.5, t) * (1 - smooth(c.b - 0.5, c.b, t));
      d.style.opacity = vis.toFixed(3);
      d.style.display = vis > 0.001 ? 'block' : 'none';
      if (vis > 0 && c.type) {
        const total = d.textContent.length;
        const shown = Math.floor(clamp((t - c.a) / 1.4) * total);
        d.style.setProperty('--clip', `${(shown / total) * 100}%`);
      }
    }
    const bp = document.getElementById('bp'); if (bp) bp.textContent = Math.floor(smooth(46.5, 53.5, t) * 3215770).toLocaleString('es-ES');
    const lpm = document.getElementById('lpm'); if (lpm) lpm.textContent = Math.round(heart.bpm(t));
    const eeg = document.getElementById('eeg'); if (eeg) eeg.textContent = (smooth(61.5, 66, t) * 97.3).toFixed(1).replace('.', ',');
    const tv = smooth(70.2, 71.6, t) * (1 - smooth(74.0, 74.9, t));
    title.style.opacity = tv.toFixed(3);
    title.style.letterSpacing = (0.55 + 0.25 * smooth(70.0, 75, t)).toFixed(3) + 'em';
    title.style.display = tv > 0.001 ? 'flex' : 'none';
    // REC-style camera label in lab shots
    const labShot = ['wide', 'pod', 'console', 'robot', 'face', 'alarm'].includes(shotId);
    rec.style.display = labShot ? 'block' : 'none';
    if (labShot) {
      const cam = { wide: 'CAM 01', pod: 'CAM 04', console: 'CAM 02', robot: 'CAM 06', face: 'CAM 04', alarm: 'CAM 01' }[shotId];
      const s = Math.floor(t * 24);
      const tc = `03:47:${String(10 + Math.floor(t)).padStart(2, '0')}:${String(s % 24).padStart(2, '0')}`;
      rec.innerHTML = `<i style="opacity:${Math.floor(t * 1.5) % 2 ? 0.25 : 1}"></i>${cam} · ${tc}`;
    }
  };
}
