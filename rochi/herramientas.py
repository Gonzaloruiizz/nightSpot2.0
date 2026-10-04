"""Herramientas de Rochi: las acciones reales que puede hacer en Windows 11.

Cada función pública es una herramienta. Se usan desde dos sitios:
  - rochi.py (asistente de voz) las pasa a Claude con function calling.
  - servidor_mcp.py las expone como servidor MCP (Claude Desktop, etc.).

Los docstrings son la descripción que ve el modelo, así que se mantienen
cortos y precisos. Las funciones devuelven texto para que el modelo lo
resuma en voz; si algo falla lanzan ErrorHerramienta con un mensaje claro.

Los imports exclusivos de Windows se hacen dentro de cada función para que
el módulo se pueda importar (y probar) en cualquier sistema.
"""

from __future__ import annotations

import ctypes
import difflib
import json
import logging
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Literal, Optional

import config

log = logging.getLogger("rochi.herramientas")

_SIN_VENTANA = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_MARGEN_APAGADO_SEG = 5
_MAX_SALIDA = 3000


class ErrorHerramienta(Exception):
    """Fallo esperado de una herramienta; el mensaje se le pasa al modelo."""


# ---------------------------------------------------------------------------
# Utilidades generales
# ---------------------------------------------------------------------------


def _requiere_windows() -> None:
    if sys.platform != "win32":
        raise ErrorHerramienta("Esta herramienta solo funciona en Windows.")


def normalizar(texto: str) -> str:
    """Minúsculas, sin tildes ni signos, espacios simples."""
    sin_tildes = unicodedata.normalize("NFD", texto or "")
    sin_tildes = "".join(c for c in sin_tildes if unicodedata.category(c) != "Mn")
    return " ".join(re.sub(r"[^\w\s]", " ", sin_tildes.lower()).replace("_", " ").split())


def _decodificar(datos: bytes) -> str:
    try:
        return datos.decode("utf-8")
    except UnicodeDecodeError:
        return datos.decode("cp850", errors="replace")  # página OEM de la consola en español


def _correr(args: list[str] | str, timeout: float, ventana: bool = False) -> tuple[int, str, str]:
    programa = args.split()[0] if isinstance(args, str) else args[0]
    try:
        r = subprocess.run(
            args,
            capture_output=True,
            timeout=timeout,
            creationflags=0 if ventana else _SIN_VENTANA,
        )
    except subprocess.TimeoutExpired:
        raise ErrorHerramienta(f"'{Path(programa).name}' tardó más de {int(timeout)} segundos y lo corté.")
    except FileNotFoundError:
        raise ErrorHerramienta(f"No encontré el programa '{programa}'.")
    return r.returncode, _decodificar(r.stdout).strip(), _decodificar(r.stderr).strip()


def _powershell(script: str, timeout: float = 60) -> tuple[int, str, str]:
    """Ejecuta un script de PowerShell con salida en UTF-8."""
    prefijo = (
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8\n"
        "$OutputEncoding = [System.Text.Encoding]::UTF8\n"
        "$ProgressPreference = 'SilentlyContinue'\n"
    )
    # PowerShell 5.1 necesita BOM para leer bien un .ps1 con tildes.
    with tempfile.NamedTemporaryFile("w", suffix=".ps1", encoding="utf-8-sig", delete=False) as f:
        f.write(prefijo + script)
        ruta = f.name
    try:
        return _correr(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", ruta],
            timeout,
        )
    finally:
        try:
            os.remove(ruta)
        except OSError:
            pass


def _recortar(texto: str, limite: int = _MAX_SALIDA) -> str:
    return texto if len(texto) <= limite else texto[:limite] + f"\n[... recortado, {len(texto) - limite} caracteres más]"


def _numero(texto: object) -> Optional[float]:
    if isinstance(texto, (int, float)):
        return float(texto)
    m = re.search(r"-?\d+(?:[.,]\d+)?", str(texto or ""))
    return float(m.group().replace(",", ".")) if m else None


def duracion_hablada(segundos: float) -> str:
    segundos = int(round(segundos))
    horas, resto = divmod(segundos, 3600)
    minutos, segs = divmod(resto, 60)
    partes = []
    if horas:
        partes.append(f"{horas} hora" + ("s" if horas != 1 else ""))
    if minutos:
        partes.append(f"{minutos} minuto" + ("s" if minutos != 1 else ""))
    if segs and not horas:
        partes.append(f"{segs} segundo" + ("s" if segs != 1 else ""))
    if not partes:
        return "0 segundos"
    return partes[0] if len(partes) == 1 else ", ".join(partes[:-1]) + " y " + partes[-1]


def _buscar_exe(clave: str, candidatos: list[str], comando: str = "") -> Optional[str]:
    configurada = config.cargar()["rutas"].get(clave) or ""
    for ruta in [configurada, *candidatos]:
        if ruta:
            ruta = os.path.expandvars(ruta)
            if os.path.isfile(ruta):
                return ruta
    return shutil.which(comando) if comando else None


def _carpetas_usuario() -> dict[str, Path]:
    perfil = Path(os.environ.get("USERPROFILE", str(Path.home())))
    carpetas = {
        "escritorio": perfil / "Desktop",
        "documentos": perfil / "Documents",
        "descargas": perfil / "Downloads",
        "imagenes": perfil / "Pictures",
        "videos": perfil / "Videos",
        "musica": perfil / "Music",
    }
    claves = {
        "escritorio": "Desktop",
        "documentos": "Personal",
        "descargas": "{374DE290-123F-4565-9164-39C4925E467B}",
        "imagenes": "My Pictures",
        "videos": "My Video",
        "musica": "My Music",
    }
    try:
        import winreg

        ruta = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, ruta) as k:
            for nombre, valor in claves.items():
                try:
                    carpetas[nombre] = Path(os.path.expandvars(winreg.QueryValueEx(k, valor)[0]))
                except OSError:
                    pass
    except (ImportError, OSError):
        pass
    if os.environ.get("OneDrive"):
        carpetas["onedrive"] = Path(os.environ["OneDrive"])
    return carpetas


def puntuar_coincidencia(consulta: str, candidato: str) -> float:
    """Qué tan bien un nombre (de app, por ejemplo) coincide con lo que dijo el usuario."""
    c = normalizar(candidato)
    if not c or not consulta:
        return 0.0
    if c == consulta:
        return 1.0
    palabras = c.split()
    if c.startswith(consulta + " ") or consulta in palabras:
        return 0.92
    if all(p in palabras for p in consulta.split()):
        return 0.88
    if consulta in c:
        return 0.8
    return 0.85 * difflib.SequenceMatcher(None, consulta.replace(" ", ""), c.replace(" ", "")).ratio()


def mejor_coincidencia(consulta: str, nombres: list[str], minimo: float = 0.6) -> Optional[int]:
    """Índice del mejor candidato (a igual puntuación gana el nombre más corto) o None."""
    mejor, mejor_clave = None, (minimo, 0)
    for i, nombre in enumerate(nombres):
        clave = (puntuar_coincidencia(consulta, nombre), -len(nombre))
        if clave[0] >= minimo and clave > mejor_clave:
            mejor, mejor_clave = i, clave
    return mejor


# ---------------------------------------------------------------------------
# Avisos (alarmas)
# ---------------------------------------------------------------------------

_notificador: Optional[Callable[[str], None]] = None


def registrar_notificador(funcion: Callable[[str], None]) -> None:
    """El cliente de voz registra aquí su función de hablar para que las alarmas suenen con la voz de Rochi."""
    global _notificador
    _notificador = funcion


def _notificar(texto: str) -> None:
    if _notificador is not None:
        try:
            _notificador(texto)
            return
        except Exception:
            log.exception("El notificador falló; uso el aviso de Windows")
    if sys.platform == "win32":
        import winsound

        winsound.MessageBeep(0x40)
        # MB_OK | MB_ICONINFORMATION | MB_SYSTEMMODAL | MB_SETFOREGROUND
        ctypes.windll.user32.MessageBoxW(None, texto, "Rochi", 0x0 | 0x40 | 0x1000 | 0x10000)
    else:
        print(f"[Rochi] {texto}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Abrir aplicaciones y webs
# ---------------------------------------------------------------------------

_cache_inicio: tuple[float, list[tuple[str, str]]] = (0.0, [])


def _lanzar(destino: str) -> bool:
    """Intenta abrir un destino (ruta, URI o comando). Devuelve False si no existe."""
    destino = os.path.expandvars(destino.strip())
    try:
        if destino.lower().startswith("shell:"):
            subprocess.Popen(["explorer.exe", destino])
            return True
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]+:", destino):  # URI: steam://, spotify:, ms-settings:
            os.startfile(destino)
            return True
        if "\\" in destino or "/" in destino:
            if not os.path.exists(destino):
                return False
            os.startfile(destino)
            return True
        ejecutable = shutil.which(destino)
        if ejecutable:
            subprocess.Popen([ejecutable], creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
            return True
        os.startfile(destino)  # resuelve "App Paths" del registro (chrome, winword...)
        return True
    except OSError:
        return False


def _apps_menu_inicio() -> list[tuple[str, str]]:
    global _cache_inicio
    momento, apps = _cache_inicio
    if apps and time.monotonic() - momento < 600:
        return apps

    apps = []
    try:
        codigo, salida, _ = _powershell("Get-StartApps | Select-Object Name, AppID | ConvertTo-Json -Compress", 20)
        if codigo == 0 and salida:
            datos = json.loads(salida)
            for app in datos if isinstance(datos, list) else [datos]:
                if app.get("Name") and app.get("AppID"):
                    apps.append((app["Name"], "shell:AppsFolder\\" + app["AppID"]))
    except (ErrorHerramienta, ValueError):
        log.warning("Get-StartApps no respondió; busco accesos directos a mano")

    raices = [os.environ.get("ProgramData", ""), os.environ.get("APPDATA", "")]
    for raiz in filter(None, raices):
        programas = Path(raiz) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
        if programas.is_dir():
            apps.extend((lnk.stem, str(lnk)) for lnk in programas.rglob("*.lnk"))

    apps = [(n, d) for n, d in apps if not re.search(r"uninstall|desinstal", n, re.I)]
    _cache_inicio = (time.monotonic(), apps)
    return apps


def abrir_aplicacion(nombre: str) -> str:
    """Abre un programa instalado (Opera, Steam, Discord, Spotify, Medal, MSI Center, etc.).

    Busca en los alias de config.json, después en el menú Inicio de Windows
    (incluye apps de la Microsoft Store) y por último como comando directo.

    Args:
        nombre: Nombre del programa como lo dijo el usuario, por ejemplo "Opera" o "MSI Center".
    """
    _requiere_windows()
    consulta = normalizar(nombre)
    if not consulta:
        raise ErrorHerramienta("Falta el nombre de la aplicación.")

    alias = {normalizar(k): v for k, v in config.cargar()["apps"].items()}
    for destino in alias.get(consulta, []):
        if _lanzar(destino):
            return f"Abrí {nombre}."

    apps = _apps_menu_inicio()
    indice = mejor_coincidencia(consulta, [n for n, _ in apps])
    if indice is not None:
        encontrado, destino = apps[indice]
        if _lanzar(destino):
            return f"Abrí {encontrado}."

    for destino in (nombre, nombre + ".exe"):
        if _lanzar(destino):
            return f"Abrí {nombre}."
    raise ErrorHerramienta(f"No encontré ninguna aplicación llamada '{nombre}' en este PC.")


def abrir_web(url: str) -> str:
    """Abre una página en el navegador por defecto.

    Args:
        url: Dirección (youtube.com, https://...) o nombre de un sitio conocido ("YouTube"). Si no parece una web, se busca en Google.
    """
    texto = url.strip()
    webs = {normalizar(k): v for k, v in config.cargar()["webs"].items()}
    if normalizar(texto) in webs:
        destino = webs[normalizar(texto)]
    elif re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]+://", texto):
        destino = texto
    elif " " not in texto and "." in texto:
        destino = "https://" + texto
    else:
        destino = "https://www.google.com/search?q=" + urllib.parse.quote_plus(texto)
    if not webbrowser.open(destino):
        raise ErrorHerramienta("No pude abrir el navegador.")
    return f"Abrí {destino} en el navegador."


# ---------------------------------------------------------------------------
# Apagado, reinicio y suspensión
# ---------------------------------------------------------------------------

_suspension: Optional[threading.Timer] = None


def _suspender_ahora() -> None:
    global _suspension
    _suspension = None
    # SetSuspendState(hibernar=False, forzar=True, desactivar_eventos_despertar=False)
    ctypes.windll.powrprof.SetSuspendState(False, True, False)


def apagar_equipo(segundos: int = 0, tipo: Literal["apagado", "reiniciar", "suspender"] = "apagado") -> str:
    """Apaga, reinicia o suspende el PC, con cuenta atrás opcional.

    Siempre deja un margen mínimo de 5 segundos para poder confirmar en voz y cancelar.

    Args:
        segundos: Segundos de espera antes de actuar (20 minutos = 1200). 0 = de una vez.
        tipo: "apagado", "reiniciar" o "suspender".
    """
    global _suspension
    _requiere_windows()
    segundos = max(int(segundos), _MARGEN_APAGADO_SEG)
    if segundos > 315_360_000:
        raise ErrorHerramienta("Ese tiempo es demasiado largo.")

    if tipo == "suspender":
        if _suspension is not None:
            _suspension.cancel()
        _suspension = threading.Timer(segundos, _suspender_ahora)
        _suspension.daemon = True
        _suspension.start()
        accion = "Suspensión"
    else:
        codigo, salida, error = _correr(["shutdown", "/s" if tipo == "apagado" else "/r", "/t", str(segundos)], 15)
        if codigo == 1190:
            raise ErrorHerramienta("Ya hay un apagado o reinicio programado. Cancélalo primero.")
        if codigo != 0:
            raise ErrorHerramienta(f"Windows no aceptó el apagado (código {codigo}): {error or salida}")
        accion = "Apagado" if tipo == "apagado" else "Reinicio"

    hora = (datetime.now() + timedelta(seconds=segundos)).strftime("%H:%M")
    return f"{accion} programado en {duracion_hablada(segundos)}, a las {hora}. Se puede cancelar con cancelar_apagado."


def cancelar_apagado() -> str:
    """Cancela el apagado, reinicio o suspensión que esté en cuenta atrás."""
    global _suspension
    _requiere_windows()
    cancelados = []
    if _suspension is not None:
        _suspension.cancel()
        _suspension = None
        cancelados.append("la suspensión")
    codigo, _, _ = _correr(["shutdown", "/a"], 15)
    if codigo == 0:
        cancelados.append("el apagado o reinicio")
    if not cancelados:
        return "No había ningún apagado, reinicio ni suspensión programado."
    return "Cancelé " + " y ".join(cancelados) + "."


# ---------------------------------------------------------------------------
# Volumen y multimedia
# ---------------------------------------------------------------------------


def calcular_volumen(actual: int, valor: int, modo: str) -> int:
    nuevo = actual + valor if modo == "relativo" else valor
    return max(0, min(100, int(round(nuevo))))


def _volumen_endpoint():
    import comtypes

    try:
        comtypes.CoInitialize()  # cada hilo que usa COM tiene que inicializarlo
    except OSError:
        pass
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

    dispositivo = AudioUtilities.GetSpeakers()
    volumen = getattr(dispositivo, "EndpointVolume", None)
    if volumen is None:  # versiones antiguas de pycaw devuelven el IMMDevice directamente
        interfaz = dispositivo.Activate(IAudioEndpointVolume._iid_, comtypes.CLSCTX_ALL, None)
        volumen = ctypes.cast(interfaz, ctypes.POINTER(IAudioEndpointVolume))
    return volumen


def set_volumen(
    delta_o_nivel: int = 10,
    modo: Literal["relativo", "absoluto", "silenciar", "activar_sonido"] = "relativo",
) -> str:
    """Cambia el volumen maestro de Windows.

    Ejemplos: "bájale" -> (-10, "relativo"); "súbele" -> (10, "relativo");
    "ponlo a 50" -> (50, "absoluto"); "silencia el PC" -> modo "silenciar".

    Args:
        delta_o_nivel: En modo "relativo", cuánto subir (+) o bajar (-). En modo "absoluto", el nivel final de 0 a 100.
        modo: "relativo", "absoluto", "silenciar" o "activar_sonido".
    """
    _requiere_windows()
    volumen = _volumen_endpoint()
    actual = int(round(volumen.GetMasterVolumeLevelScalar() * 100))
    if modo == "silenciar":
        volumen.SetMute(1, None)
        return "Silencié el sonido."
    if modo == "activar_sonido":
        volumen.SetMute(0, None)
        return f"Quité el silencio. El volumen está en {actual}%."
    nuevo = calcular_volumen(actual, delta_o_nivel, modo)
    volumen.SetMasterVolumeLevelScalar(nuevo / 100, None)
    if nuevo > 0 and volumen.GetMute():
        volumen.SetMute(0, None)
    return f"Volumen de {actual}% a {nuevo}%."


_TECLAS_MEDIA = {"play": 0xB3, "pausa": 0xB3, "siguiente": 0xB0, "anterior": 0xB1, "detener": 0xB2}


def media_control(accion: Literal["play", "pausa", "siguiente", "anterior", "detener"]) -> str:
    """Controla la música o el vídeo que esté sonando (Spotify, YouTube, etc.) con las teclas multimedia.

    "play" y "pausa" usan la misma tecla de reproducir/pausar, así que alternan el estado.

    Args:
        accion: "play", "pausa", "siguiente", "anterior" o "detener".
    """
    _requiere_windows()
    tecla = _TECLAS_MEDIA[accion]
    user32 = ctypes.windll.user32
    user32.keybd_event(tecla, 0, 0x1, 0)  # KEYEVENTF_EXTENDEDKEY
    user32.keybd_event(tecla, 0, 0x1 | 0x2, 0)  # + KEYEVENTF_KEYUP
    return f"Mandé la tecla multimedia de '{accion}'."


# ---------------------------------------------------------------------------
# Monitorización
# ---------------------------------------------------------------------------

_GRUPOS_LHM = {
    "temperatures": "Temperature",
    "fans": "Fan",
    "controls": "Control",
    "load": "Load",
    "clocks": "Clock",
    "powers": "Power",
    "voltages": "Voltage",
    "data": "Data",
    "small data": "SmallData",
    "throughput": "Throughput",
    "levels": "Level",
    "factors": "Factor",
    "currents": "Current",
    "energy": "Energy",
}


def parsear_lhm_json(datos: dict) -> list[dict]:
    """Aplana el árbol de data.json del servidor web de LibreHardwareMonitor."""
    sensores: list[dict] = []

    def recorrer(nodo: dict, hardware: str, grupo: Optional[str]) -> None:
        texto = nodo.get("Text", "")
        hijos = nodo.get("Children") or []
        if not hijos:
            valor = _numero(nodo.get("Value"))
            if grupo and valor is not None:
                sensores.append({
                    "hardware": hardware,
                    "tipo": nodo.get("Type") or _GRUPOS_LHM.get(grupo.lower(), grupo),
                    "nombre": texto,
                    "valor": valor,
                    "id": nodo.get("SensorId", ""),
                })
            return
        if texto.lower() in _GRUPOS_LHM:
            nuevo_hardware, nuevo_grupo = hardware, texto
        else:
            nuevo_hardware, nuevo_grupo = texto, None
        for hijo in hijos:
            recorrer(hijo, nuevo_hardware, nuevo_grupo)

    recorrer(datos, "", None)
    return sensores


def parsear_lhm_wmi(datos: object) -> list[dict]:
    """Convierte la salida JSON de Get-CimInstance -ClassName Sensor al mismo formato."""
    filas = datos if isinstance(datos, list) else [datos]
    sensores = []
    for fila in filas:
        if not isinstance(fila, dict) or fila.get("Value") is None:
            continue
        identificador = fila.get("Identifier") or ""
        sensores.append({
            "hardware": identificador.rsplit("/", 2)[0],
            "tipo": fila.get("SensorType", ""),
            "nombre": fila.get("Name", ""),
            "valor": float(fila["Value"]),
            "id": identificador,
        })
    return sensores


def _es_cpu(sensor: dict) -> bool:
    if sensor["id"]:
        return sensor["id"].startswith(("/intelcpu", "/amdcpu"))
    hardware = sensor["hardware"]
    return bool(re.search(r"\b(core|ryzen|cpu|xeon|threadripper|pentium|celeron)\b", hardware, re.I)) and not re.search(
        r"radeon|geforce|nvidia|rtx|gtx|arc", hardware, re.I
    )


def temperatura_cpu(sensores: list[dict]) -> Optional[dict]:
    temps = [s for s in sensores if s["tipo"] == "Temperature" and _es_cpu(s)]
    for preferido in ("cpu package", "core max", "core (tctl/tdie)", "cpu (tctl/tdie)", "tctl/tdie", "tdie", "core average"):
        for s in temps:
            if s["nombre"].lower() == preferido:
                return s
    return max(temps, key=lambda s: s["valor"]) if temps else None


_cache_sensores: tuple[float, list[dict]] = (float("-inf"), [])


def _sensores_lhm() -> list[dict]:
    """Sensores de LibreHardwareMonitor, con una caché corta (más larga si no hay LHM, que probarlo es lento)."""
    global _cache_sensores
    momento, sensores = _cache_sensores
    if time.monotonic() - momento < (3 if sensores else 15):
        return sensores
    sensores = _leer_sensores_lhm()
    _cache_sensores = (time.monotonic(), sensores)
    return sensores


def _leer_sensores_lhm() -> list[dict]:
    url = config.cargar()["lhm_url"]
    if url:
        try:
            with urllib.request.urlopen(url, timeout=2) as respuesta:
                return parsear_lhm_json(json.load(respuesta))
        except (urllib.error.URLError, OSError, ValueError):
            pass
    if sys.platform == "win32":
        for espacio in ("root/LibreHardwareMonitor", "root/OpenHardwareMonitor"):
            try:
                codigo, salida, _ = _powershell(
                    f"Get-CimInstance -Namespace {espacio} -ClassName Sensor -ErrorAction Stop | "
                    "Select-Object Name, SensorType, Value, Identifier | ConvertTo-Json -Compress",
                    15,
                )
                if codigo == 0 and salida:
                    return parsear_lhm_wmi(json.loads(salida))
            except (ErrorHerramienta, ValueError):
                continue
    return []


_CAMPOS_GPU = ["name", "utilization.gpu", "temperature.gpu", "memory.used", "memory.total", "fan.speed", "power.draw", "clocks.gr"]


def _info_gpu() -> Optional[dict]:
    exe = _buscar_exe(
        "nvidia_smi",
        [r"%SystemRoot%\System32\nvidia-smi.exe", r"%ProgramFiles%\NVIDIA Corporation\NVSMI\nvidia-smi.exe"],
        "nvidia-smi",
    )
    if not exe:
        return None
    try:
        codigo, salida, _ = _correr([exe, "--query-gpu=" + ",".join(_CAMPOS_GPU), "--format=csv,noheader,nounits"], 10)
    except ErrorHerramienta:
        return None
    if codigo != 0 or not salida:
        return None
    valores = [v.strip() for v in salida.splitlines()[0].split(",")]
    info = dict(zip(_CAMPOS_GPU, valores))
    return {k: (v if k == "name" else _numero(v) if "N/A" not in v and "Not Supported" not in v else None) for k, v in info.items()}


def _fmt(valor: Optional[float], unidad: str, decimales: int = 0) -> str:
    return "sin dato" if valor is None else f"{valor:.{decimales}f}{unidad}"


def _texto_temperatura() -> str:
    sensores = _sensores_lhm()
    partes = []
    cpu = temperatura_cpu(sensores)
    if cpu:
        partes.append(f"CPU {cpu['valor']:.0f} °C ({cpu['nombre']})")
    else:
        partes.append(
            "CPU sin lectura: abre LibreHardwareMonitor como administrador con el servidor web activado "
            "(Options > Remote Web Server > Run)"
        )
    gpu = _info_gpu()
    if gpu and gpu.get("temperature.gpu") is not None:
        partes.append(f"GPU {gpu['temperature.gpu']:.0f} °C")
    else:
        temps_gpu = [s for s in sensores if s["tipo"] == "Temperature" and re.search(r"gpu", s["id"] or s["hardware"], re.I)]
        if temps_gpu:
            partes.append(f"GPU {temps_gpu[0]['valor']:.0f} °C")
    return "; ".join(partes) + "."


def _texto_abanicos() -> str:
    sensores = _sensores_lhm()
    rpm = [s for s in sensores if s["tipo"] == "Fan" and s["valor"] > 0]
    control = [s for s in sensores if s["tipo"] == "Control"]
    partes = [f"{s['nombre']} {s['valor']:.0f} RPM" for s in rpm[:6]]
    partes += [f"{s['nombre']} al {s['valor']:.0f}%" for s in control[:4]]
    gpu = _info_gpu()
    if gpu and gpu.get("fan.speed") is not None:
        partes.append(f"abanico de la GPU al {gpu['fan.speed']:.0f}%")
    if not partes:
        return "No tengo lectura de abanicos: hace falta LibreHardwareMonitor abierto como administrador."
    return "Abanicos: " + ", ".join(partes) + "."


def _top_procesos(clave: str, cantidad: int = 3) -> list[tuple[str, float]]:
    import psutil

    if clave == "cpu":
        procesos = list(psutil.process_iter(["name"]))
        for p in procesos:
            try:
                p.cpu_percent(None)
            except psutil.Error:
                pass
        time.sleep(1.0)
        nucleos = psutil.cpu_count() or 1
        datos = []
        for p in procesos:
            try:
                if p.pid and p.info["name"] not in ("System Idle Process", "Idle"):
                    datos.append((p.info["name"], p.cpu_percent(None) / nucleos))
            except psutil.Error:
                pass
    else:
        datos = []
        for p in psutil.process_iter(["name", "memory_info"]):
            try:
                datos.append((p.info["name"], p.info["memory_info"].rss / 2**30))
            except (psutil.Error, AttributeError):
                pass
    return sorted(datos, key=lambda d: d[1], reverse=True)[:cantidad]


def _texto_uso_cpu() -> str:
    import psutil

    psutil.cpu_percent(percpu=True)
    top = _top_procesos("cpu")  # tarda 1 segundo midiendo
    nucleos = psutil.cpu_percent(percpu=True)
    total = sum(nucleos) / len(nucleos)
    texto = f"CPU al {total:.0f}% (el núcleo más cargado al {max(nucleos):.0f}%)."
    if top:
        texto += " Lo que más consume: " + ", ".join(f"{n} {v:.0f}%" for n, v in top) + "."
    relojes = [s["valor"] for s in _sensores_lhm() if s["tipo"] == "Clock" and _es_cpu(s) and s["nombre"].startswith("Core")]
    if relojes:
        texto += f" Reloj máximo {max(relojes):.0f} MHz."
    return texto


def _texto_uso_gpu() -> str:
    gpu = _info_gpu()
    if not gpu:
        return "No pude leer la GPU: no encontré nvidia-smi (viene con el driver de NVIDIA)."
    memoria = ""
    if gpu.get("memory.used") is not None and gpu.get("memory.total"):
        memoria = f", VRAM {gpu['memory.used'] / 1024:.1f} de {gpu['memory.total'] / 1024:.1f} GB"
    return (
        f"{gpu['name']}: uso {_fmt(gpu.get('utilization.gpu'), '%')}, {_fmt(gpu.get('temperature.gpu'), ' °C')}"
        f"{memoria}, consumo {_fmt(gpu.get('power.draw'), ' W')}, reloj {_fmt(gpu.get('clocks.gr'), ' MHz')}, "
        f"abanico {_fmt(gpu.get('fan.speed'), '%')}."
    )


def _texto_ram() -> str:
    import psutil

    memoria = psutil.virtual_memory()
    texto = f"RAM: {memoria.used / 2**30:.1f} de {memoria.total / 2**30:.1f} GB en uso ({memoria.percent:.0f}%)."
    top = _top_procesos("ram")
    if top:
        texto += " Lo que más ocupa: " + ", ".join(f"{n} {v:.1f} GB" for n, v in top) + "."
    return texto


def _texto_red() -> str:
    import psutil

    antes = psutil.net_io_counters()
    time.sleep(1.0)
    despues = psutil.net_io_counters()
    bajada = (despues.bytes_recv - antes.bytes_recv) * 8 / 1e6
    subida = (despues.bytes_sent - antes.bytes_sent) * 8 / 1e6
    activas = [(n, s.speed) for n, s in psutil.net_if_stats().items() if s.isup and s.speed > 0]
    texto = f"Tráfico ahora mismo: {bajada:.1f} Mbps de bajada y {subida:.1f} Mbps de subida."
    if activas:
        nombre, velocidad = max(activas, key=lambda a: a[1])
        texto += f" Conexión principal: {nombre} con enlace a {velocidad} Mbps."
    return texto


FIRMA_RTSS = 0x52545353  # 'RTSS'
_ENTRADA_RTSS = struct.Struct("<I260sIIIII")  # pid, nombre, flags, time0, time1, frames, frametime(µs)


def parsear_rtss(datos: bytes) -> list[dict]:
    """Lee las entradas de aplicaciones de la memoria compartida de RivaTuner Statistics Server."""
    if len(datos) < 20:
        return []
    firma, version, tam_entrada, offset, cantidad = struct.unpack_from("<5I", datos, 0)
    if firma != FIRMA_RTSS or version < 0x00020000:
        return []
    entradas = []
    for i in range(cantidad):
        base = offset + i * tam_entrada
        if base + _ENTRADA_RTSS.size > len(datos):
            break
        pid, nombre, _, t0, t1, frames, frametime = _ENTRADA_RTSS.unpack_from(datos, base)
        if not pid:
            continue
        ruta = nombre.split(b"\0", 1)[0].decode("latin-1")
        fps = 1000.0 * frames / (t1 - t0) if t1 > t0 and frames else 0.0
        entradas.append({"pid": pid, "nombre": ruta.replace("\\", "/").rsplit("/", 1)[-1], "fps": fps, "t1": t1, "frametime_ms": frametime / 1000})
    return entradas


def _leer_rtss() -> Optional[list[dict]]:
    import mmap

    nombre = "RTSSSharedMemoryV2"
    try:
        with mmap.mmap(-1, 20, tagname=nombre, access=mmap.ACCESS_READ) as cabecera:
            firma, _, tam_entrada, offset, cantidad = struct.unpack("<5I", cabecera[:20])
        if firma != FIRMA_RTSS:
            return None
        total = offset + tam_entrada * cantidad
        with mmap.mmap(-1, total, tagname=nombre, access=mmap.ACCESS_READ) as memoria:
            return parsear_rtss(memoria[:total])
    except (OSError, ValueError, struct.error):
        return None


def _texto_fps() -> str:
    _requiere_windows()
    entradas = _leer_rtss()
    if entradas is None:
        return "No puedo medir FPS: abre RivaTuner Statistics Server (viene con MSI Afterburner) antes del juego."
    ahora = ctypes.windll.kernel32.GetTickCount()
    activas = [e for e in entradas if e["fps"] > 0 and ((ahora - e["t1"]) & 0xFFFFFFFF) < 5000]
    if not activas:
        return "RTSS está abierto pero ahora mismo ningún juego está pintando frames."
    pid = ctypes.c_ulong()
    ctypes.windll.user32.GetWindowThreadProcessId(ctypes.windll.user32.GetForegroundWindow(), ctypes.byref(pid))
    elegida = next((e for e in activas if e["pid"] == pid.value), max(activas, key=lambda e: e["fps"]))
    return f"{elegida['fps']:.0f} FPS en {elegida['nombre']} ({elegida['frametime_ms']:.1f} ms por frame)."


def _texto_resumen() -> str:
    import psutil

    memoria = psutil.virtual_memory()
    partes = [_texto_temperatura(), f"CPU al {psutil.cpu_percent(interval=0.5):.0f}%.", f"RAM al {memoria.percent:.0f}%."]
    gpu = _info_gpu()
    if gpu:
        partes.append(f"GPU al {_fmt(gpu.get('utilization.gpu'), '%')}.")
    return " ".join(partes)


def monitor_sistema(
    metrica: Literal["temperatura", "uso_cpu", "uso_gpu", "ram", "fps", "abanicos", "red", "resumen"],
) -> str:
    """Lee en vivo el estado del PC.

    La temperatura y los abanicos salen de LibreHardwareMonitor, la GPU de nvidia-smi
    y los FPS de RivaTuner Statistics Server.

    Args:
        metrica: "temperatura", "uso_cpu", "uso_gpu", "ram", "fps", "abanicos", "red" o "resumen" (un poco de todo).
    """
    funciones = {
        "temperatura": _texto_temperatura,
        "uso_cpu": _texto_uso_cpu,
        "uso_gpu": _texto_uso_gpu,
        "ram": _texto_ram,
        "fps": _texto_fps,
        "abanicos": _texto_abanicos,
        "red": _texto_red,
        "resumen": _texto_resumen,
    }
    return funciones[metrica]()


# ---------------------------------------------------------------------------
# Benchmarks y test de velocidad
# ---------------------------------------------------------------------------


def parsear_7zip(salida: str) -> Optional[dict]:
    total = re.search(r"^Tot:(.*)$", salida, re.M)
    if not total or not re.findall(r"\d+", total.group(1)):
        return None
    resultado = {"total": int(re.findall(r"\d+", total.group(1))[-1])}
    media = re.search(r"^Avr:(.*)$", salida, re.M)
    if media and "|" in media.group(1):
        compresion, descompresion = media.group(1).split("|", 1)
        if re.findall(r"\d+", compresion) and re.findall(r"\d+", descompresion):
            resultado["compresion"] = int(re.findall(r"\d+", compresion)[-1])
            resultado["descompresion"] = int(re.findall(r"\d+", descompresion)[-1])
    return resultado


def parsear_cinebench(salida: str) -> Optional[float]:
    puntuaciones = re.findall(r"\bCB\s+(\d+(?:[.,]\d+)?)", salida)
    return float(puntuaciones[-1].replace(",", ".")) if puntuaciones else None


def _benchmark_7zip() -> str:
    exe = _buscar_exe("siete_zip", [r"%ProgramFiles%\7-Zip\7z.exe", r"%ProgramFiles(x86)%\7-Zip\7z.exe"], "7z")
    if not exe:
        raise ErrorHerramienta("No encontré 7-Zip. Instálalo (winget install 7zip.7zip) o pon la ruta en config.json.")
    codigo, salida, error = _correr([exe, "b"], 900)
    resultado = parsear_7zip(salida)
    if codigo != 0 or not resultado:
        raise ErrorHerramienta(f"El benchmark de 7-Zip falló: {_recortar(error or salida, 500)}")
    texto = f"7-Zip: {resultado['total']} MIPS de puntuación total"
    if "compresion" in resultado:
        texto += f" (compresión {resultado['compresion']} MIPS, descompresión {resultado['descompresion']} MIPS)"
    return texto + "."


def _benchmark_cinebench() -> str:
    exe = _buscar_exe(
        "cinebench",
        [
            r"%ProgramFiles%\Maxon Cinebench\Cinebench.exe",
            r"%ProgramFiles%\Maxon\Cinebench\Cinebench.exe",
            r"%USERPROFILE%\Downloads\CinebenchR23\Cinebench.exe",
            r"C:\CinebenchR23\Cinebench.exe",
        ],
    )
    if not exe:
        raise ErrorHerramienta("No encontré Cinebench. Pon la ruta de Cinebench.exe en config.json (rutas > cinebench).")
    # Cinebench solo escribe el resultado en consola si se lanza con este truco de "parentconsole".
    # Va como cadena porque cmd no entiende el escapado de comillas que haría subprocess con una lista.
    codigo, salida, error = _correr(
        f'cmd.exe /c start /b /wait "parentconsole" "{exe}" g_CinebenchCpuXTest=true g_CinebenchMinimumTestDuration=1',
        1800,
        ventana=True,
    )
    puntuacion = parsear_cinebench(salida + "\n" + error)
    if puntuacion is None:
        raise ErrorHerramienta(
            "Cinebench terminó pero no me devolvió la puntuación por consola. Mírala en la ventana de Cinebench."
        )
    return f"Cinebench multinúcleo: {puntuacion:.0f} puntos."


def _benchmark_occt(prueba: str) -> str:
    personalizado = config.cargar()["occt_comandos"].get(prueba) or ""
    if personalizado:
        codigo, salida, error = _powershell(personalizado, 3600)
        if codigo != 0:
            raise ErrorHerramienta(f"El comando de OCCT falló: {_recortar(error or salida, 500)}")
        return _recortar(salida or "OCCT terminó sin mostrar salida.")
    exe = _buscar_exe("occt", [r"%ProgramFiles%\OCCT\OCCT.exe", r"%USERPROFILE%\Downloads\OCCT.exe", r"%USERPROFILE%\Desktop\OCCT.exe"])
    if not exe or not _lanzar(exe):
        raise ErrorHerramienta("No encontré OCCT. Pon la ruta de OCCT.exe en config.json (rutas > occt).")
    nombre = "CPU" if prueba == "occt_cpu" else "Power"
    return (
        f"Abrí OCCT, pero la edición gratuita no deja arrancar la prueba {nombre} ni leer el resultado "
        "automáticamente: el usuario tiene que darle a Start. Mientras corre puedo vigilar temperaturas."
    )


def lanzar_benchmark(prueba: Literal["cinebench", "occt_cpu", "occt_power", "7zip"]) -> str:
    """Corre un benchmark y devuelve el resultado. Tarda varios minutos: avisa al usuario antes de llamarla.

    Args:
        prueba: "cinebench" (multinúcleo), "occt_cpu", "occt_power" o "7zip".
    """
    _requiere_windows()
    if prueba == "7zip":
        return _benchmark_7zip()
    if prueba == "cinebench":
        return _benchmark_cinebench()
    return _benchmark_occt(prueba)


def formatear_speedtest(datos: dict) -> str:
    bajada = datos["download"]["bandwidth"] * 8 / 1e6
    subida = datos["upload"]["bandwidth"] * 8 / 1e6
    ping = datos.get("ping", {}).get("latency")
    texto = f"Bajada {bajada:.0f} Mbps, subida {subida:.0f} Mbps"
    if ping is not None:
        texto += f", ping {ping:.0f} ms"
    servidor = datos.get("server", {})
    if servidor.get("name"):
        texto += f" (servidor {servidor['name']}, {servidor.get('location', '')})"
    if datos.get("isp"):
        texto += f". Proveedor: {datos['isp']}"
    return texto + "."


def test_velocidad() -> str:
    """Hace un test de velocidad de internet con Speedtest de Ookla (tarda unos 30 segundos)."""
    exe = _buscar_exe(
        "speedtest",
        [r"%LOCALAPPDATA%\Microsoft\WinGet\Links\speedtest.exe", r"%ProgramFiles%\Ookla\Speedtest CLI\speedtest.exe"],
        "speedtest",
    )
    if exe:
        codigo, salida, _ = _correr([exe, "--format=json", "--accept-license", "--accept-gdpr"], 180)
        for linea in reversed(salida.splitlines()):
            try:
                datos = json.loads(linea)
            except ValueError:
                continue
            if codigo == 0 and isinstance(datos, dict) and "download" in datos:
                return formatear_speedtest(datos)
    try:
        import speedtest  # paquete speedtest-cli, por si no está el CLI oficial
    except ImportError:
        raise ErrorHerramienta("No tengo Speedtest. Instálalo con: winget install Ookla.Speedtest.CLI")
    prueba = speedtest.Speedtest(secure=True)
    prueba.get_best_server()
    bajada, subida = prueba.download(), prueba.upload()
    return f"Bajada {bajada / 1e6:.0f} Mbps, subida {subida / 1e6:.0f} Mbps, ping {prueba.results.ping:.0f} ms."


# ---------------------------------------------------------------------------
# Archivos y capturas
# ---------------------------------------------------------------------------

_IGNORAR_CARPETAS = {"appdata", "node_modules", "$recycle.bin", "__pycache__", "venv", ".git"}


def _buscar_en_indice(palabras: list[str], limite: int) -> Optional[list[str]]:
    condicion = " AND ".join(f"System.FileName LIKE '%{p}%'" for p in palabras)
    script = f"""
$con = New-Object -ComObject ADODB.Connection
$con.Open("Provider=Search.CollatorDSO;Extended Properties='Application=Windows';")
$rs = $con.Execute("SELECT TOP {limite} System.ItemPathDisplay FROM SYSTEMINDEX WHERE {condicion} ORDER BY System.DateModified DESC")
$rutas = @()
while (-not $rs.EOF) {{ $rutas += $rs.Fields.Item('System.ItemPathDisplay').Value; $rs.MoveNext() }}
$rs.Close(); $con.Close()
ConvertTo-Json -InputObject $rutas -Compress
"""
    try:
        codigo, salida, _ = _powershell(script, 20)
        if codigo != 0 or not salida:
            return None
        datos = json.loads(salida)
    except (ErrorHerramienta, ValueError):
        return None
    return [r for r in (datos if isinstance(datos, list) else [datos]) if isinstance(r, str)]


def _buscar_recorriendo(palabras: list[str], limite: int, segundos: float = 8.0) -> list[str]:
    buscadas = [normalizar(p) for p in palabras]
    fin = time.monotonic() + segundos
    encontrados: list[str] = []
    vistos: set[str] = set()
    for raiz in _carpetas_usuario().values():
        if not raiz.is_dir():
            continue
        for carpeta, subcarpetas, archivos in os.walk(raiz):
            subcarpetas[:] = [d for d in subcarpetas if not d.startswith(".") and d.lower() not in _IGNORAR_CARPETAS]
            for nombre in subcarpetas + archivos:
                if all(p in normalizar(nombre) for p in buscadas):
                    ruta = os.path.join(carpeta, nombre)
                    if ruta not in vistos:
                        vistos.add(ruta)
                        encontrados.append(ruta)
            if len(encontrados) >= limite or time.monotonic() > fin:
                return encontrados[:limite]
    return encontrados[:limite]


def buscar_archivo(nombre: str) -> str:
    """Busca archivos o carpetas del usuario por nombre (índice de Windows y carpetas personales).

    Devuelve las rutas completas; al usuario dile solo el nombre y la carpeta, no la ruta entera.

    Args:
        nombre: Parte del nombre, por ejemplo "tesis" o "factura luz".
    """
    _requiere_windows()
    palabras = re.sub(r"[^\w\s.\-]", " ", nombre).split()
    if not palabras:
        raise ErrorHerramienta("Dime qué nombre buscar.")
    limite = 10
    rutas = _buscar_en_indice(palabras, limite)
    if not rutas:
        rutas = _buscar_recorriendo(palabras, limite)
    if not rutas:
        return f"No encontré nada que se llame '{nombre}'."
    lineas = []
    for ruta in rutas[:limite]:
        try:
            fecha = datetime.fromtimestamp(os.path.getmtime(ruta)).strftime("%Y-%m-%d")
        except OSError:
            fecha = "?"
        tipo = "carpeta" if os.path.isdir(ruta) else "archivo"
        lineas.append(f"- {os.path.basename(ruta)} ({tipo}, modificado {fecha}): {ruta}")
    return f"Encontré {len(lineas)} resultado(s):\n" + "\n".join(lineas)


def abrir_archivo(ruta: str) -> str:
    """Abre un archivo o carpeta con su programa predeterminado. Usa una ruta devuelta por buscar_archivo.

    Args:
        ruta: Ruta completa del archivo o carpeta.
    """
    _requiere_windows()
    ruta = os.path.expandvars(os.path.expanduser(ruta.strip().strip('"')))
    if not os.path.exists(ruta):
        raise ErrorHerramienta(f"No existe '{ruta}'. Búscalo primero con buscar_archivo.")
    os.startfile(ruta)
    return f"Abrí {os.path.basename(ruta.rstrip(os.sep)) or ruta}."


def capturar_pantalla() -> str:
    """Hace una captura de todas las pantallas y la guarda como PNG. Devuelve dónde quedó."""
    _requiere_windows()
    from PIL import ImageGrab

    configurada = config.cargar()["capturas_dir"]
    carpeta = Path(os.path.expandvars(configurada)) if configurada else _carpetas_usuario()["imagenes"] / "Screenshots" / "Rochi"
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / f"Rochi_{datetime.now():%Y%m%d_%H%M%S}.png"
    ImageGrab.grab(all_screens=True).save(ruta)
    return f"Captura guardada como {ruta.name} en {carpeta}."


# ---------------------------------------------------------------------------
# Alarmas
# ---------------------------------------------------------------------------

_alarmas: list[threading.Timer] = []


def _sonar_alarma(mensaje: str) -> None:
    texto = f"¡Ey, compay! {mensaje}" if mensaje else "¡Ey, compay! Ya se cumplió el tiempo que me dijiste."
    _notificar(texto)


def alarma(minutos: float, mensaje: str = "") -> str:
    """Programa un aviso hablado dentro de X minutos (mientras Rochi siga abierto).

    Args:
        minutos: Minutos hasta el aviso (puede tener decimales, 0.5 = 30 segundos).
        mensaje: Lo que hay que recordarle al usuario, por ejemplo "saca la pizza del horno".
    """
    if not 0 < minutos <= 24 * 60:
        raise ErrorHerramienta("La alarma tiene que ser entre unos segundos y 24 horas.")
    segundos = minutos * 60
    temporizador = threading.Timer(segundos, _sonar_alarma, args=(mensaje.strip(),))
    temporizador.daemon = True
    temporizador.start()
    _alarmas[:] = [t for t in _alarmas if t.is_alive()] + [temporizador]
    hora = (datetime.now() + timedelta(seconds=segundos)).strftime("%H:%M")
    return f"Alarma puesta para dentro de {duracion_hablada(segundos)}, a las {hora}."


# ---------------------------------------------------------------------------
# Comandos libres de PowerShell
# ---------------------------------------------------------------------------

_PELIGROSOS = [
    (r"\b(remove-item|rm|del|erase|rd|rmdir|ri)\b", "borra archivos o carpetas"),
    (r"\b(clear-content|clear-recyclebin|clear-disk|format-volume|diskpart|initialize-disk|cipher)\b|\bformat(\.com)?\s+[a-z]:", "borra o formatea datos"),
    (r"\b(move-item|move|mv|copy-item|copy|cp|xcopy|robocopy|rename-item|ren)\b", "mueve, copia o renombra datos"),
    (r"\b(reg(\.exe)?\s+(add|delete|import|copy)|(new|set|remove|rename)-itemproperty)\b|hklm:|hkcu:|registry::", "toca el registro"),
    (r"\b((stop|start|set|new|remove|restart|suspend)-service|sc(\.exe)?\s+(config|delete|create|stop))\b", "toca servicios del sistema"),
    (r"\b(bcdedit|bcdboot|bootrec|reagentc)\b", "modifica el arranque"),
    (r"\b(set-mppreference|add-mppreference|netsh|set-netfirewall\w*|set-executionpolicy|disable-\w+|takeown|icacls|vssadmin)\b", "modifica la seguridad del sistema"),
    (r"\b(winget|choco|scoop|msiexec|install-\w+|uninstall-\w+|add-appxpackage|remove-appxpackage|setup\.exe)\b", "instala o desinstala software"),
    (r"\b(invoke-expression|iex|start-process\b.*-verb\s+runas)\b", "ejecuta código descargado o con privilegios"),
    (r"\b(shutdown|stop-computer|restart-computer)\b", "apaga o reinicia el equipo"),
]


def comando_peligroso(comando: str) -> Optional[str]:
    """Devuelve por qué un comando necesita confirmación, o None si es inofensivo."""
    for patron, motivo in _PELIGROSOS:
        if re.search(patron, comando, re.I):
            return motivo
    return None


def ejecutar_comando(comando: str, confirmado: bool = False) -> str:
    """Ejecuta un comando de PowerShell para cualquier acción que no cubran las demás herramientas.

    Si el comando borra, mueve o copia datos, toca el registro, servicios, arranque o seguridad,
    o instala software, se bloquea hasta que el usuario lo confirme.

    Args:
        comando: Comando o script de PowerShell.
        confirmado: Ponlo en true solo si el usuario acaba de decir explícitamente que sí a ESTE comando.
    """
    _requiere_windows()
    if not confirmado:
        motivo = comando_peligroso(comando)
        if motivo:
            return (
                f"NO EJECUTADO: este comando {motivo}. Explícale al usuario qué va a pasar, pídele confirmación "
                "y vuelve a llamar con confirmado=true solo si dice que sí."
            )
    codigo, salida, error = _powershell(comando, config.cargar()["comando_timeout_seg"])
    if codigo != 0:
        texto = f"El comando falló (código {codigo}): {error or salida or 'sin detalles'}"
        if re.search(r"access is denied|acceso denegado|elevat|elevaci|administra", error, re.I):
            texto += "\nNecesita permisos de administrador."
        raise ErrorHerramienta(_recortar(texto))
    return _recortar(salida or "Listo, el comando no devolvió salida.")


HERRAMIENTAS = [
    abrir_aplicacion,
    abrir_web,
    apagar_equipo,
    cancelar_apagado,
    set_volumen,
    media_control,
    monitor_sistema,
    lanzar_benchmark,
    test_velocidad,
    buscar_archivo,
    abrir_archivo,
    capturar_pantalla,
    alarma,
    ejecutar_comando,
]
