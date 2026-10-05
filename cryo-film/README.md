# Proyecto Lázaro — cortometraje 3D

Escena de película: un humano criogenizado en una cámara frigorífica, conectado por cables, mientras
científicos le inyectan un suero experimental. La cámara sigue al medicamento por el torrente sanguíneo
hasta el núcleo de una célula, donde reescribe el ADN, y vuelve al exterior para ver cómo el cuerpo muta.

Hay dos versiones:

| Versión | Motor | Duración | Archivo |
|---|---|---|---|
| Estilizada (sci‑fi, con HUD) | Three.js (WebGL) renderizado fotograma a fotograma | 75 s | `proyecto_lazaro.mp4` |
| Fotorrealista (plano de película) | Blender Cycles (path tracing) | ~30 s | `proyecto_lazaro_fotorrealista.mp4` |

## Guion de planos (versión estilizada)

| Tiempo | Plano |
|---|---|
| 0–8 s | Plano general: instalación criogénica, niebla, tanques, científicos con traje de sala limpia |
| 8–14 s | Travelling sobre la cápsula: el rostro congelado tras el cristal escarchado |
| 14–20 s | Sobre el hombro del operador: se autoriza el protocolo y se abre la cápsula |
| 20–25 s | El brazo robótico desciende con el suero Λ‑9 |
| 25–29,5 s | Primerísimo plano: la aguja entra en el puerto del cuello y las venas se iluminan |
| 29,5–41 s | Dentro de la carótida: glóbulos rojos, flujo pulsátil y el enjambre de nanoportadores |
| 41–45,5 s | Llegada a la célula diana y paso a través de la membrana |
| 45,5–54 s | Núcleo: la doble hélice se abre y se reescribe |
| 54–61 s | De vuelta al rostro: la escarcha se funde y las venas brillantes se extienden |
| 61–66 s | Alarma: los científicos retroceden, el cuerpo convulsiona bajo la sábana |
| 66–69,5 s | Los ojos se iluminan… destello |
| 69,5–75 s | Título |

El latido (ECG en los monitores, pulsos del vaso sanguíneo, brillo de las venas y sonido) sale de la
misma curva de pulsaciones definida en `timeline.json`.

## Cómo regenerarlo

```sh
npm install                      # three.js + playwright
npx http-server -p 8123 -s -c-1 . &
node render.mjs frames 0 2 &     # dos procesos en paralelo
node render.mjs frames 1 2
./build_v1.sh                    # banda sonora + codificación MP4
```

`index.html` también se puede abrir en un navegador para verlo en tiempo real (`?t=30` congela un instante).

Versión fotorrealista (requiere el módulo `bpy` de Blender 5 para Python 3.11):

```sh
node export_lab.mjs photoreal/export 10 25.5 60     # exporta el laboratorio a glTF
python photoreal/scene.py <plano> 1 <n> 2            # establish|frozen|needle|blood|dna|mutation (12 fps)
python photoreal/make_audio_v2.py
python photoreal/assemble.py
```

## Créditos de recursos

- Cabeza escaneada "Lee Perry‑Smith" (CC BY 3.0, Infinite Realities) y maniquí "X Bot" (Mixamo), de los ejemplos de three.js.
- Fuentes Rajdhani, Share Tech Mono y Exo 2 (SIL Open Font License).
- Todo lo demás (geometría del laboratorio, sangre, ADN, shaders y sonido) es procedural.
