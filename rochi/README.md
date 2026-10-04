# Rochi: asistente de voz dominicano para Windows 11

Rochi es un asistente de voz estilo Jarvis que vive en el PC, habla con acento
dominicano y ejecuta acciones reales: abre programas y webs, controla el volumen y
la música, apaga o suspende el equipo, lee temperaturas, abanicos y FPS, corre
benchmarks, hace test de velocidad, busca archivos, hace capturas, pone alarmas y
ejecuta PowerShell. El cerebro es Claude (API de Anthropic) con *function calling*.
Las mismas herramientas también se pueden usar como **servidor MCP**.

## Cómo funciona

```
micrófono → oído (Google es-DO o Whisper local)
          → ¿dijo "Rochi"? → saludo literal (lo dice el programa, sin pasar por la API)
          → orden → Claude + herramientas (bucle de function calling)
          → respuesta → voz (edge-tts es-DO-EmilioNeural, o SAPI de Windows)
```

| Archivo | Qué hace |
|---|---|
| `rochi.py` | Programa principal: activación por nombre, ventana de conversación y bucle con Claude |
| `herramientas.py` | Las 14 herramientas de Windows (los nombres exactos del prompt) |
| `servidor_mcp.py` | Expone las herramientas por MCP (Claude Desktop, Claude Code…) |
| `voz.py` | Texto a voz y voz a texto |
| `system_prompt.md` | Tu prompt de sistema, tal cual, más una sección 10 con notas del cliente de voz |
| `config.py` / `config.ejemplo.json` | Configuración por defecto y ejemplo para personalizar |
| `tests/` | Pruebas de la lógica que no depende de Windows |

## Requisitos

- Windows 11 con Python 3.11 o superior (64 bits).
- Una API key de Anthropic (https://console.anthropic.com).
- Micrófono y cascos (con altavoces, Rochi se puede escuchar a sí mismo).
- Opcional, según la herramienta:

| Para | Necesitas |
|---|---|
| Temperatura de CPU y abanicos | [LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor) abierto **como administrador** con *Options → Remote Web Server → Run* (puerto 8085) |
| FPS | RivaTuner Statistics Server abierto (viene con MSI Afterburner) |
| GPU | `nvidia-smi` (viene con el driver de NVIDIA) |
| Test de velocidad | `winget install Ookla.Speedtest.CLI` |
| Benchmark 7-Zip | `winget install 7zip.7zip` |
| Cinebench / OCCT | La ruta del `.exe` en `config.json` (`rutas`) |

## Instalación

En PowerShell, dentro de la carpeta `rochi`:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy config.ejemplo.json config.json      # opcional: edítalo a tu gusto
setx ANTHROPIC_API_KEY "sk-ant-..."       # luego cierra y abre la terminal
```

## Uso

```powershell
.\iniciar_rochi.bat              # o: python rochi.py
python rochi.py --texto          # escribiendo, para probar sin micrófono
python rochi.py --texto --mudo   # sin voz, solo texto
python rochi.py --microfonos     # lista los micrófonos (para "microfono" en config.json)
```

- Di **"Rochi, ¿estás ahí?"** y te responde *"Aquí estoy compay, ¿qué es lo que tú
  quieres que le haga loco?"*. Luego dale la orden.
- También puedes decirlo de una vez: "Rochi, abre Opera".
- Después de cada respuesta tienes 45 segundos para seguir hablando sin repetir el
  nombre (para contestar "¿de una vez o le pongo un tiempo?", por ejemplo). Pasado
  ese tiempo, vuelve a ignorar todo lo que no empiece por "Rochi".
- "Eso es todo" o "descansa" cierran la conversación antes de tiempo.
- Rochi recuerda la conversación durante 10 minutos; después empieza de cero.

## Configuración

Todo es opcional; en `config.json` solo pones lo que quieras cambiar (los valores
por defecto están en `config.py`).

| Clave | Para qué |
|---|---|
| `modelo`, `esfuerzo` | Modelo de Claude y nivel de esfuerzo (ver abajo) |
| `fallbacks` | Reintento automático en otro modelo si un filtro de seguridad rechaza la orden por error |
| `activacion.palabras` | Cómo puede transcribir el nombre el reconocedor ("rochi", "rochy", "roshi"…) |
| `activacion.ventana_conversacion_seg` / `memoria_min` | Ventana sin nombre y memoria de la conversación |
| `voz.voz_edge` | `es-DO-EmilioNeural` (hombre) o `es-DO-RamonaNeural` (mujer) |
| `voz.motor` | `edge` (voz neuronal, necesita internet) o `sapi` (voces de Windows, offline) |
| `oido.motor` | `google` (gratis, online) o `whisper` (local en la RTX 2060; instala `faster-whisper` y `numpy`) |
| `apps` / `webs` | Alias: nombre hablado → programa o web |
| `rutas` | Rutas de 7-Zip, Cinebench, OCCT, Speedtest y nvidia-smi si no están en el sitio habitual |
| `occt_comandos` | Si tu OCCT tiene línea de comandos (ediciones de pago), el comando de cada prueba |
| `lhm_url` | Dirección del servidor web de LibreHardwareMonitor |

### Modelo, coste y velocidad

- Por defecto usa `claude-opus-5-5` con `esfuerzo: "low"`, que en voz da respuestas
  rápidas sin perder la cabeza con las herramientas. Si quieres más rapidez o menos
  coste puedes poner `"modelo": "claude-sonnet-5-5"`.
- El prompt de sistema y las herramientas no cambian durante la sesión y van con
  caché de prompts, así que cada orden solo paga completo lo nuevo.
- **Fallbacks activados** (`"fallbacks": true`): si el clasificador de seguridad de la
  API rechaza una orden por error (le puede pasar con algún comando de PowerShell),
  la API la repite sola en otro modelo. Si no lo quieres, pon `"fallbacks": false`.

## Usarlo como servidor MCP

Las mismas 14 herramientas se pueden usar desde cualquier cliente MCP. Por ejemplo,
en Claude Desktop (`%APPDATA%\Claude\claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "rochi": {
      "command": "C:\\ruta\\a\\rochi\\.venv\\Scripts\\python.exe",
      "args": ["C:\\ruta\\a\\rochi\\servidor_mcp.py"]
    }
  }
}
```

O en Claude Code: `claude mcp add rochi -- C:\ruta\a\rochi\.venv\Scripts\python.exe C:\ruta\a\rochi\servidor_mcp.py`

## Seguridad

- **Apagado**: siempre deja al menos 5 segundos de margen para poder cancelar. Ojo:
  con cuenta atrás, Windows cierra los programas a la fuerza al llegar a cero, así
  que guarda lo que estés haciendo.
- **`ejecutar_comando`**: además de lo que diga el prompt, el código bloquea los
  comandos que borran, mueven o copian datos, tocan el registro, servicios,
  arranque o seguridad, o instalan software, hasta que Claude repite la llamada con
  `confirmado=true` después de que tú digas que sí. Es una red de seguridad, no un
  aislamiento: los comandos corren con los permisos de tu usuario.
- **Privacidad**: con `oido.motor = "google"`, todo lo que capta el micrófono
  (también conversaciones que no van para Rochi) se manda a Google para
  transcribirlo y ver si dijiste "Rochi". Con `whisper` el audio no sale del PC.
  Las órdenes que sí van para Rochi se mandan a la API de Anthropic.

## Limitaciones conocidas

- **No está probado en Windows.** La lógica se probó en Linux (pruebas de
  `tests/` y el bucle completo contra una API simulada), pero las partes que tocan
  Windows (volumen, teclas multimedia, apagado, memoria de RTSS, Cinebench, voz)
  necesitan tu prueba real.
- **Cinebench**: el resultado se lee por consola con el truco `parentconsole` de
  Maxon. Si tu versión no lo escribe ahí, Rochi te lo dice y lo miras en la ventana.
- **OCCT gratis** no deja arrancar pruebas por línea de comandos: Rochi lo abre y
  tú le das a Start (puede vigilar las temperaturas mientras).
- **Play y pausa** usan la misma tecla multimedia, así que alternan.
- **Alarmas**: se pierden si cierras Rochi.
- **Mientras corre un benchmark** (varios minutos) Rochi no escucha.
- Con Claude Opus 5.5, las notas largas que el modelo escribe entre herramientas
  llegan como pensamiento oculto; Rochi solo dice en voz los avisos cortos (como
  "eso tarda un chin"), que es lo que pide el prompt.

## Pruebas

```powershell
pip install pytest
python -m pytest tests
```
