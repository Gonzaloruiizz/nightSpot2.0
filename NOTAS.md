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
| 1 | Render vertical 1080×1920 con NVENC (NVIDIA) o procesador | ⏳ Falta |
| 2 | Voces dominicanas + subtítulos palabra a palabra | ⏳ Falta |
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

---

## ☁️ Cómo se usa aquí en la nube (Linux)

```
cd fabrica_shorts
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python comprobar.py
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

---

## 📜 Historial

- **Fase 0** – Carpetas, `.gitignore` (protege `.env`), `.env.example`, `ajustes.toml`, tipografías
  gratuitas, `instalar.bat` / `comprobar.bat` para Windows y `comprobar.py`.
