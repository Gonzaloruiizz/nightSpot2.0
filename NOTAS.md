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
| 3 | Guiones graciosos con datos reales (OMS/CDC/FDA) | ✅ Hecho (12 guiones) |
| 4 | Estilo visual (avatares, emojis, gancho) + dembow con "ducking" | ✅ Hecho |
| 5 | Fábrica por lotes: un clic = todos los vídeos + textos para publicar | ✅ Hecho |
| 6 | (Opcional) Inventar guiones nuevos con IA | 💤 Sin empezar |
| 7 | (Opcional) Subida automática a YouTube | 💤 Sin empezar |

### ⏳ Qué falta / próximos pasos
1. **Tú, en tu PC:** instalarlo (pasos de abajo) y hacer doble clic en **`probar_voces.bat`**: crea 9 muestras
   de voces dominicanas y caribeñas para que elijas la de Don Fello y la de Yefri (ver "🗣️ Sobre las voces").
2. **Música:** decidir cómo poner un dembow **real** (ver "🥁 Sobre la música"). El beat que compone la fábrica
   es solo un apaño: no suena a dembow de verdad.
3. (Opcional) **Fase 6:** inventar guiones nuevos automáticamente con IA (necesitaría una clave en `.env`).
4. (Opcional) **Fase 7:** subir solo a YouTube con la API oficial.
5. (Opcional) **Plan B de voz:** las mismas voces dominicanas por la vía oficial de Microsoft (Azure, gratis
   hasta 500.000 caracteres/mes), por si algún día la voz gratuita deja de funcionar.

---

## 🖥️ Cómo instalarlo en tu PC con Windows 11 (paso a paso)

> Solo se hace **una vez**. Donde pone "abre la Terminal": clic derecho en el botón de Inicio → **Terminal**.

**Paso 1 – Descargar el proyecto**
- Opción fácil: instala **GitHub Desktop** (https://desktop.github.com), inicia sesión y haz
  *File → Clone repository → `Gonzaloruiizz/nightSpot2.0`*. Arriba, en *Current branch*, elige
  `claude/short-video-factory-oz41b0`. Para traer las novedades: botón **Fetch origin** → **Pull origin**.
- Opción ZIP (la más rápida): con tu cuenta de GitHub abierta en el navegador, entra en
  https://github.com/Gonzaloruiizz/nightSpot2.0/archive/refs/heads/claude/short-video-factory-oz41b0.zip
  y descomprímelo (por ejemplo en `Documentos`).

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

**Paso 6 – Probar**
- Doble clic en **`probar_voces.bat`** → escucha las muestras de voces en `salida\muestras_voces`.
- Doble clic en **`probar_un_video.bat`** → crea solo el vídeo 01 (unos minutos) para ver cómo queda.

**Paso 7 – Crear todos los vídeos**
Doble clic en **`crear_videos.bat`**. Al terminar se abre sola la carpeta `salida` con los MP4.

> 💡 Si Windows dice "Windows protegió su PC" al abrir un `.bat`: pulsa **Más información → Ejecutar de todas
> formas**. Para que no salga más: antes de descomprimir el ZIP, clic derecho en el ZIP → **Propiedades** →
> marca **Desbloquear** → Aceptar.

---

## 🔁 Uso diario (el día a día de la fábrica)

1. **Escribe guiones nuevos** en `fabrica_shorts/guiones/` (copia la plantilla, ver más abajo).
2. **Doble clic en `crear_videos.bat`**. Solo crea los guiones que **todavía no tienen vídeo**;
   los ya hechos se saltan. Al final sale un **RESUMEN** con lo creado, avisos y errores.
3. En `fabrica_shorts/salida/` tienes, por cada guion:
   - `NN_nombre.mp4` → el vídeo para subir.
   - `NN_nombre.txt` → **título, descripción, hashtags y fuentes** listos para copiar y pegar en
     YouTube y TikTok, y recordatorios para publicar (etiqueta de IA, "no es para niños"…).

**Opciones** (abre la Terminal en la carpeta `fabrica_shorts` y escribe):

| Escribe | Qué hace |
|---|---|
| `crear_videos.bat` | Crea todos los vídeos que falten |
| `crear_videos.bat 01 03` | Solo los guiones con "01" o "03" en el nombre |
| `crear_videos.bat --forzar` | Vuelve a crear también los ya hechos (p. ej. tras cambiar `ajustes.toml`) |
| `crear_videos.bat 07 --forzar` | Rehace solo el 07 |
| `crear_videos.bat --sin-musica` | Sin dembow (para poner un sonido de TikTok al subir) |

- Si un vídeo sale con **`__VOZ_DE_PRUEBA`** en el nombre es que no había internet para la voz dominicana:
  **no lo publiques**. La próxima vez que ejecutes `crear_videos.bat` con internet se rehace solo y se
  borra el de prueba.
- Las voces se guardan en una caché: si solo cambias colores o música y usas `--forzar`, no se vuelven a pedir.

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

### Los 12 guiones que ya hay

| # | Tema | Dato real que explica | Fuente |
|---|---|---|---|
| 01 | ¿Aire con sabor a mango? 🥭 | No es vapor de agua: aerosol con nicotina, partículas y metales (níquel, estaño, plomo) | CDC |
| 02 | Cerebro en construcción 🚧 | El cerebro se forma hasta los ~25; la nicotina afecta atención, aprendizaje e impulsos | CDC |
| 03 | Un pod = una cajetilla 🚬 | Algunos pods traen tanta nicotina como 20 cigarrillos | CDC |
| 04 | Sabor algodón de azúcar 🍭 | Comer ≠ respirar; diacetilo y "pulmón de palomitas" | CDC, Allen et al. 2016 |
| 05 | Yefri perdió el vaper 😡 | Abstinencia: irritabilidad, ansiedad, falta de concentración | CDC |
| 06 | Vaper en el bolsillo 🔥 | Baterías que explotan y causan quemaduras | FDA, CDC |
| 07 | Corazón en dembow 🥁 | La nicotina sube el pulso y la presión | CDC, AHA |
| 08 | Nube en la guagua ☁️ | El aerosol que se bota lo respiran los demás | CDC |
| 09 | Cartuchos de la calle 🚑 | Brote EVALI 2019: 2.807 hospitalizaciones o muertes en EE. UU. | CDC |
| 10 | La cuenta del vaper 💸 | Humor sobre el gasto (sin datos médicos) | — |
| 11 | "Vapeo pa' no fumar" 🤔 | Los jóvenes que vapean tienen más probabilidad de acabar fumando | OMS, Soneji et al. 2017 |
| 12 | Yefri no duerme 😵 | La nicotina es un estimulante y empeora el sueño | NIDA |

> Los datos están redactados con cuidado para no exagerar: YouTube y TikTok penalizan la desinformación
> médica. Si escribes guiones nuevos, apunta siempre la fuente en `FUENTES:`.

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
> bloquea). En la nube se usa la **voz de respaldo en español sin internet** (Kokoro): se entiende bien,
> pero **sin acento dominicano**. La voz dominicana real sale en tu PC.

---

## 🎨 Cómo es cada vídeo

```
┌──────────────────────────────┐  ← barra de progreso (arriba del todo)
│  ¿AIRE CON SABOR A MANGO? 🥭  │  ← GANCHO (se ve desde el primer segundo: sirve de miniatura)
│                              │
│       KLK MI GENTE.          │  ← subtítulos: la palabra que suena, en el color del que habla
│                              │
│   ┌────────┐                 │  ← bocadillo con los emojis de la frase, sobre el que habla
│   │ 🥭  💀 │                 │
│   └───▽────┘                 │
│   (Don Fello)    (Yefri)     │  ← personajes 2D: boca sincronizada con la voz, parpadean,
│   guayabera      sudadera    │     el que habla brilla y bota un poco
│   DON FELLO      YEFRI       │
└──────────────────────────────┘
```

- **Personajes 2D** (`fabrica/personajes2d.py`), dibujados con código, sin imágenes de terceros:
  - **Don Fello**: señor de mediana edad, calvo con canas, bigote gris, gafas, guayabera; cejas de regañar.
  - **Yefri**: chamaco de 19 años, pelo rizo, gorra roja hacia atrás, sudadera, cadenita y el vaper en la mano.
  - 3 bocas (cerrada / entreabierta / abierta) elegidas **según el volumen de su voz** 15 veces por segundo,
    y parpadeo cada pocos segundos. Se miran el uno al otro.
- **Fondo:** degradado de colores en movimiento con humo que sube (cambia en cada vídeo).
  Si pones clips propios en `assets/fondos/`, se usan esos.
- **Música:** beat de **dembow original** compuesto por la fábrica, **sin copyright**, a 122 BPM:
  caja fuerte en el "pum-PÁ-pum-PÁ" del dembow (tresillo 3+3+2), bombo y bajo 808, hi-hats en semicorcheas,
  cencerro, repiques de timbal, redobles y un riff de sintetizador que cambia en cada vídeo.
  - Volumen medido: mientras hablan, la música queda **~13 dB por debajo de la voz** (se oye, pero no tapa);
    en las pausas sube. Se cambia en `ajustes.toml` → `[musica] volumen`.
  - ¿Prefieres un sonido de moda de TikTok? Crea el vídeo **sin música** (`crear_videos.bat --sin-musica`)
    y añade el sonido desde la app de TikTok al subirlo.
  - ¿Tienes un beat con licencia? Mételo en `assets/musica/` y se usa solo (ver "🥁 Sobre la música").

---

## 🗣️ Sobre las voces (importante)

- **Las voces que oyes en los vídeos de prueba de la nube NO son las de verdad.** Aquí la red bloquea la voz
  dominicana de Microsoft, así que se usa una voz de respaldo en español (Kokoro): se entiende, pero **no es
  natural ni dominicana**. Por eso esos vídeos llevan `__VOZ_DE_PRUEBA` en el nombre.
- **En tu PC, con internet**, se usa la voz neuronal **dominicana** de Microsoft (`es-DO-EmilioNeural`), que suena
  mucho más natural.
- Solo hay **una voz dominicana de hombre**; para que Don Fello y Yefri no suenen igual se cambia un poco el tono y
  la velocidad (cambios pequeños: los grandes suenan a robot). Otra opción es usar una voz **caribeña** (Puerto Rico,
  Cuba o Venezuela) para uno de los dos.
- **Para elegir: doble clic en `probar_voces.bat`.** Crea en `salida/muestras_voces/` 9 MP3 con la misma frase:
  Emilio (dominicano) normal / grave / joven, Víctor (Puerto Rico), Manuel (Cuba), Sebastián (Venezuela) y
  Ramona (dominicana, mujer). Copia en `ajustes.toml` la `voz`, `velocidad` y `tono` de las que te gusten.

## 🥁 Sobre la música (importante)

El beat que compone la fábrica sola es **solo un apaño**: hecho con matemáticas, sin instrumentos reales, **no suena
a dembow de verdad**. Para que suene a dembow auténtico hay dos caminos (los dos legales):

1. **Recomendado – música de la propia app:** crea los vídeos **sin música** (`crear_videos.bat --sin-musica`) y, al
   publicar, añade un dembow de verdad desde la biblioteca de sonidos de **TikTok** o de **YouTube Shorts**.
   Esa música ya está pagada por la plataforma, y además usar sonidos de moda ayuda a que el vídeo se vea más.
2. **Un beat tuyo con licencia:** compra/alquila un beat de dembow a un productor (busca "dembow type beat" con
   licencia que permita monetizar) o usa uno libre de derechos, y mete el MP3 en `fabrica_shorts/assets/musica/`.
   La fábrica lo usa sola (`origen = "carpeta"` en `ajustes.toml`) y lo baja cuando hablan.

⚠️ **Nunca** uses canciones descargadas de YouTube o Spotify: te silencian el vídeo o te quitan la monetización.

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
| `fabrica_shorts/assets/emojis/` | Imágenes de emojis para bocadillos y gancho (Noto Emoji de Google, licencia libre) |
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
| Vídeo con `__VOZ_DE_PRUEBA` | No había internet para la voz dominicana: lleva la voz de respaldo en español (sin acento). Conéctate y vuelve a crear ese vídeo |
| `comprobar.bat` dice "le faltan filtros" con ffmpeg 8 o 9 | Era una falsa alarma del comprobador (ffmpeg cambió el formato de su lista). Arreglado: ahora pregunta filtro por filtro. Si de verdad falla un vídeo por "subtitles", instala la versión completa: `winget install --id Gyan.FFmpeg -e` |
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
- **Fase 3** – 12 guiones con Yefri (chamaco de 19 años) y Don Fello (hombre de mediana edad que lo regaña),
  humor dominicano y datos con fuente. El 01 empieza con *"Klk mi gente. ¿Tú cree que ese vaper e' aire
  con sabor a mango? ¡Mentira! Eso trae nicotina…"*. Plantilla en `guiones/_PLANTILLA.txt`.
- **Fase 4** – Estilo y música:
  - `fabrica/graficos.py`: avatares (Don Fello 🧔🏽‍♂️☝🏽 / Yefri 🧑🏽🧢💨), el que habla se ilumina y bota;
    bocadillos con los emojis de cada frase; gancho con emojis; humo; barra de progreso.
  - `fabrica/emojis.py`: emojis Noto guardados en `assets/emojis/` (se descargan solos si falta alguno).
  - `fabrica/musica.py`: compone el dembow original. `fabrica/audio.py`: voz a -15 LUFS, música a -20 LUFS
    con "ducking" (baja sola al hablar), fundidos de entrada/salida y limitador.
  - Opción `--sin-musica`. Fondos más oscuros con viñeta para que se lea mejor.
- **Fase 5** – Fábrica por lotes:
  - `crear_videos.py` solo crea lo que falta (`--forzar` para rehacer), rehace solo los vídeos de prueba
    cuando vuelve la voz real, y termina con un resumen (creados, avisos, errores, tiempo).
  - `fabrica/publicacion.py`: un `.txt` por vídeo con título, descripción, hashtags, fuentes, aviso de salud
    y recordatorios de publicación. Avisa si el título pasa de 100 caracteres o el vídeo de 59 s.
  - El vídeo se crea en `.trabajo/` y solo se mueve a `salida/` al terminar: si cortas la fábrica a mitad,
    no queda un vídeo a medias que luego se dé por hecho. Sin `#shorts` en el texto de TikTok.
- **Mejora 1 (tras ver el primer vídeo)**:
  - La voz de prueba (robot en inglés) no se entendía → ahora el respaldo es **Kokoro**, una voz neuronal
    en español que funciona **sin internet** (Don Fello = `em_santa`, Yefri = `em_alex`). Orden con `auto`:
    dominicana → español sin internet → robot. El modelo (~120 MB) se descarga solo la primera vez que se necesita.
  - El beat no sonaba a dembow → `fabrica/musica.py` rehecho: caja en tresillo bien marcada, bombo/bajo 808
    con "deslizado", hi-hats en semicorcheas con acentos, cencerro, timbales, redobles y riff de sintetizador.
- **Mejora 2: personajes 2D** – Don Fello y Yefri pasan de emojis a **dibujos 2D** con boca sincronizada
  con la voz y parpadeo (`fabrica/personajes2d.py` + animación en `fabrica/graficos.py`, que ffmpeg monta como
  secuencia de imágenes). Nueva composición: gancho → subtítulos → bocadillo → personajes grandes abajo.
  En `ajustes.toml` cada personaje tiene `dibujo = "fello"` / `"yefri"`. La caché de voces solo depende de los
  ajustes de voz (cambiar colores o dibujos no obliga a regenerar voces).
- **Mejora 3: voces y música** – Las voces de la nube no eran naturales ni dominicanas (la nube no puede usar la
  voz dominicana): nuevo **`probar_voces.bat`** para escuchar y elegir voces dominicanas/caribeñas en el PC, y
  cambios de tono más suaves (Don Fello −6 Hz, Yefri +8 Hz). La música: `origen = "carpeta"` por defecto (si pones
  un beat real en `assets/musica/` se usa solo; si no, el beat compuesto) y guía para poner dembow de verdad.
- **Prueba en el PC de Windows** (Python 3.14, ffmpeg 9.0 Essentials, RTX 2060): ✅ librerías, ✅ NVENC,
  ✅ voz dominicana. El comprobador daba una falsa alarma de "faltan filtros" con ffmpeg 9 → corregido
  (`herramientas.tiene_filtro` pregunta a ffmpeg filtro por filtro).
