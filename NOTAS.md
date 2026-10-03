# 📒 NOTAS – Fábrica de Shorts "El Vaper con Don Fello y Yefri"

Fábrica automática de vídeos cortos verticales (9:16) para **YouTube Shorts** y **TikTok**
sobre los efectos del vaper, en clave de humor y con acento dominicano.

- **Personajes:** **Yefri** (el chamaco que vapea) y **Don Fello** (el hombre de mediana edad que lo regaña).
- **Voz:** voces dominicanas de Microsoft (`es-DO-EmilioNeural`) con distinto tono para cada uno.
- **Música:** beat de dembow **original** compuesto por la fábrica (sin copyright), que baja solo cuando hablan.
- **Todo está en la carpeta** [`fabrica_shorts/`](fabrica_shorts/). La web NightSpot (`index.html`) no se toca.
- **Rama de GitHub:** `claude/short-video-factory-oz41b0`

---

## ✅ Estado del proyecto

| Fase | Qué es | Estado |
|---|---|---|
| 0 | Estructura base, `.env`, instalador de Windows, comprobador | ✅ Hecho |
| 1 | Render vertical 1080×1920 con NVENC (NVIDIA) o procesador | ✅ Hecho |
| 2 | Voces dominicanas + subtítulos palabra a palabra | ✅ Hecho |
| 3 | Guiones graciosos con datos reales (OMS/CDC/FDA) | ⏳ Falta |
| 4 | Estilo visual (avatares, emojis, gancho) + dembow con "ducking" | ⏳ Falta |
| 5 | Fábrica por lotes: un clic = todos los vídeos + textos para publicar | ⏳ Falta |
| 6 | (Opcional) Inventar guiones nuevos con IA | 💤 Sin empezar |
| 7 | (Opcional) Subida automática a YouTube | 💤 Sin empezar |

---

## 🖥️ Cómo instalarlo en tu PC con Windows 11 (paso a paso)

> Solo se hace **una vez**. Donde pone "abre la Terminal": clic derecho en el botón de Inicio → **Terminal**.

**Paso 1 – Descargar el proyecto**
- Opción fácil: instala **GitHub Desktop** (https://desktop.github.com), inicia sesión y haz
  *File → Clone repository → `Gonzaloruiizz/nightSpot2.0`*. Arriba, en *Current branch*, elige
  `claude/short-video-factory-oz41b0`. Para traer las novedades: botón **Fetch origin** → **Pull origin**.
- Opción ZIP: en la web de GitHub elige la rama `claude/short-video-factory-oz41b0`, botón verde
  **Code → Download ZIP**, y descomprímelo (por ejemplo en `Documentos`).

**Paso 2 – Instalar Python** (abre la Terminal y pega):
```
winget install Python.Python.3.12
```
(o desde https://www.python.org/downloads/ marcando la casilla **"Add python.exe to PATH"**).

**Paso 3 – Instalar ffmpeg** (en la Terminal):
```
winget install Gyan.FFmpeg
```
Después **cierra la Terminal y ábrela otra vez** para que Windows lo encuentre.

**Paso 4 – Actualizar el driver de NVIDIA**
Abre la app **NVIDIA** (o GeForce Experience) → Controladores → Descargar e instalar el último.
Esto es lo que permite renderizar con tu RTX 2060 (NVENC), que es mucho más rápido.

**Paso 5 – Instalar la fábrica**
Entra en la carpeta `fabrica_shorts` y haz **doble clic en `instalar.bat`**.
Al final te sale una lista con ✅ / ❌. Si todo está en ✅, ¡listo!
(Puedes volver a comprobarlo cuando quieras con doble clic en `comprobar.bat`).

**Paso 6 – Crear los vídeos**
Doble clic en **`crear_videos.bat`**. Al terminar se abre sola la carpeta `salida` con los MP4.
- Solo algunos guiones: abre la Terminal en la carpeta `fabrica_shorts` y escribe
  `crear_videos.bat 01 03` (crea solo los que tienen "01" o "03" en el nombre).
- Si un vídeo sale con `__VOZ_DE_PRUEBA` en el nombre es que no había internet para la voz dominicana.

---

## ✍️ Cómo escribir un guion

Copia `fabrica_shorts/guiones/_PLANTILLA.txt`, ponle otro nombre (p. ej. `13_mi_idea.txt`) y edítalo con el Bloc de notas:

```
TITULO: título para YouTube/TikTok
GANCHO: frase grande que sale arriba
DESCRIPCION: texto de la descripción
HASHTAGS: #vaper #humor #dominicano
FUENTES: de dónde salen los datos

FELLO: {Klk|qué lo que} mi gente. ¿Tú cree que ese vaper e' aire con sabor a mango? 🥭 ¡Mentira!
YEFRI: Ay, don Fello, pero e' que huele rico. 😋
```

- Cada frase empieza por **`FELLO:`** o **`YEFRI:`** (en mayúsculas).
- Los **emojis no se leen** en voz alta: salen en pantalla.
- **`{lo que se ve|lo que se dice}`** sirve para arreglar pronunciaciones. Ejemplo: `{Klk|qué lo que}`
  enseña "KLK" en el subtítulo, pero la voz dice "qué lo que". Úsalo si la voz lee algo raro.
- Los archivos que empiezan por `_` (como la plantilla) **no** se convierten en vídeo.
- Ideal: **90-110 palabras** (30-45 segundos).

---

## ☁️ Cómo se usa aquí en la nube (Linux)

```
cd fabrica_shorts
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python comprobar.py
.venv/bin/python crear_videos.py            # todos los guiones
.venv/bin/python crear_videos.py 01         # solo el 01
```

> ⚠️ Aquí en la nube la red no deja pasar la voz dominicana (usa una conexión que este entorno
> bloquea). En la nube se usa una **voz de prueba**; la voz dominicana real sale en tu PC.

---

## 🔑 Claves y contraseñas (`.env`)

- Las claves van **solo** en `fabrica_shorts/.env`. Ese archivo **nunca se sube a GitHub** (está en `.gitignore`).
- `fabrica_shorts/.env.example` es la plantilla (sin claves). `instalar.bat` la copia como `.env` la primera vez.
- **Ahora mismo no hace falta ninguna clave**: la voz dominicana es gratis.

---

## 📁 Qué hay en cada carpeta

| Carpeta / archivo | Para qué sirve |
|---|---|
| `fabrica_shorts/ajustes.toml` | Ajustes que puedes cambiar con el Bloc de notas (voces, colores, calidad…) |
| `fabrica_shorts/guiones/` | Los guiones, uno por vídeo (archivos `.txt`) |
| `fabrica_shorts/assets/fuentes/` | Tipografías gratuitas (Luckiest Guy y Anton) |
| `fabrica_shorts/assets/musica/` | (Opcional) tu música sin copyright. No se sube a GitHub |
| `fabrica_shorts/assets/fondos/` | (Opcional) tus clips de fondo. No se sube a GitHub |
| `fabrica_shorts/salida/` | Aquí aparecen los vídeos terminados. No se sube a GitHub |
| `fabrica_shorts/fabrica/` | El código (no hace falta tocarlo) |

---

## 🛠️ Problemas frecuentes

| Problema | Solución |
|---|---|
| "No encuentro Python" | Reinstala Python marcando **Add python.exe to PATH** |
| "No encuentro ffmpeg" | `winget install Gyan.FFmpeg` y **reabre** la Terminal. Si sigue, pon la ruta en `.env` → `FFMPEG_PATH=` |
| La voz pronuncia mal una palabra | En el guion usa `{palabra|cómo se dice}`, p. ej. `{vaper|véiper}` |
| Vídeo con `__VOZ_DE_PRUEBA` | No había internet para la voz dominicana. Conéctate y vuelve a crear ese vídeo |
| "NVENC no disponible" en tu PC | Actualiza el driver de NVIDIA y vuelve a abrir `comprobar.bat`. Mientras tanto se usa el procesador (va más lento, pero funciona) |

---

## 📜 Historial

- **Fase 0** – Carpetas, `.gitignore` (protege `.env`), `.env.example`, `ajustes.toml`, tipografías
  gratuitas, `instalar.bat` / `comprobar.bat` para Windows y `comprobar.py`.
- **Fase 1** – Motor de render (`fabrica/render.py`): fondo animado (o tus clips), capas de imágenes
  animadas, subtítulos y audio → MP4 1080×1920 a 30 fps. Detecta NVENC haciendo una **prueba real**
  (no basta con que ffmpeg diga que lo tiene); si falla, usa el procesador (libx264).
  `comprobar.py` ahora también dice si tu NVIDIA está lista. Se elige en `ajustes.toml` → `[render] codificador`.
- **Fase 2** – Voces y subtítulos:
  - `fabrica/guion.py` lee los guiones (personajes, emojis, truco `{se ve|se dice}`).
  - `fabrica/voz.py`: voz dominicana de Microsoft (`edge-tts`) con el momento exacto de cada palabra;
    Yefri suena más agudo y rápido, Don Fello más grave. Guarda cada frase en una **caché** (`.cache/`)
    para no volver a pedirla. Si no hay internet, **voz de prueba** y el vídeo se marca `__VOZ_DE_PRUEBA`.
    Nunca se queda colgado: máximo 45 s de espera por frase.
  - `fabrica/subtitulos.py`: subtítulos grandes de 1-3 palabras; la palabra que suena se ilumina con el
    color del personaje y hace un pequeño "pop".
  - `crear_videos.py` / `crear_videos.bat`: crean los vídeos de la carpeta `guiones/`.
