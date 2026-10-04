"""Pruebas de la lógica que no depende de Windows (se pueden correr en cualquier sistema).

    python -m pytest tests
"""

from __future__ import annotations

import asyncio
import os
import struct
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("ANTHROPIC_API_KEY", "clave-de-prueba")

import pytest
from anthropic import beta_tool

import herramientas as h
import rochi
from voz import limpiar_para_voz

PALABRAS = {"rochi", "rochy", "roshi"}


@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("Rochi, ¿estás ahí?", (True, "estás ahí?")),
        ("¿Rochi?", (True, "")),
        ("Rochi, ven acá", (True, "ven acá")),
        ("Oye Rochi, abre Opera", (True, "abre Opera")),
        ("Rochy pon música", (True, "pon música")),
        ("abre opera", (False, "abre opera")),
        ("el roshambo ese", (False, "el roshambo ese")),
    ],
)
def test_detectar_activacion(texto, esperado):
    assert rochi.detectar_activacion(texto, PALABRAS) == esperado


def test_saludos_sin_orden():
    for texto in ("Rochi, ¿estás ahí?", "¿Rochi?", "Rochi, ven acá", "Rochi"):
        llamado, orden = rochi.detectar_activacion(texto, PALABRAS)
        assert llamado and h.normalizar(orden) in rochi.SOLO_LLAMADA


def test_marca_de_tiempo():
    assert rochi.marca_de_tiempo(datetime(2026, 10, 4, 21, 34)) == "[domingo 4 de octubre, 21:34]"


def test_contenido_para_historial_sin_fallback():
    bloques = [SimpleNamespace(type="thinking"), SimpleNamespace(type="text")]
    assert rochi.contenido_para_historial(bloques) == bloques


def test_contenido_para_historial_con_fallback_quita_lo_anterior_menos_el_texto():
    pensar, texto, uso, corte, despues = (
        SimpleNamespace(type="thinking"),
        SimpleNamespace(type="text"),
        SimpleNamespace(type="tool_use"),
        SimpleNamespace(type="fallback"),
        SimpleNamespace(type="thinking"),
    )
    assert rochi.contenido_para_historial([pensar, texto, uso, corte, despues]) == [texto, corte, despues]


def test_normalizar():
    assert h.normalizar("¡Ábreme MSI-Center!") == "abreme msi center"


@pytest.mark.parametrize(
    "actual, valor, modo, esperado",
    [(40, -10, "relativo", 30), (95, 10, "relativo", 100), (5, -10, "relativo", 0), (40, 50, "absoluto", 50), (40, 150, "absoluto", 100)],
)
def test_calcular_volumen(actual, valor, modo, esperado):
    assert h.calcular_volumen(actual, valor, modo) == esperado


def test_mejor_coincidencia():
    apps = ["Steam Support Center", "Steam", "Discord", "MSI Center", "MSI Afterburner"]
    assert apps[h.mejor_coincidencia("steam", apps)] == "Steam"
    assert apps[h.mejor_coincidencia("msi center", apps)] == "MSI Center"
    assert apps[h.mejor_coincidencia("afterburner", apps)] == "MSI Afterburner"
    assert h.mejor_coincidencia("photoshop", apps) is None


def test_duracion_hablada():
    assert h.duracion_hablada(1200) == "20 minutos"
    assert h.duracion_hablada(3900) == "1 hora y 5 minutos"
    assert h.duracion_hablada(90) == "1 minuto y 30 segundos"
    assert h.duracion_hablada(5) == "5 segundos"


SALIDA_7ZIP = """
7-Zip 23.01 (x64) : Copyright (c) 1999-2023 Igor Pavlov : 2023-06-20

                       Compressing  |                  Decompressing
Dict     Speed Usage    R/U Rating  |      Speed Usage    R/U Rating
         KiB/s     %   MIPS   MIPS  |      KiB/s     %   MIPS   MIPS

22:      58123  1057   5348  56542  |     593180  1182   4280  50590
----------------------------------  | ------------------------------
Avr:     54759  1086   5290  57456  |     578918  1194   4222  50437
Tot:            1140   4756  53947
"""


def test_parsear_7zip():
    assert h.parsear_7zip(SALIDA_7ZIP) == {"total": 53947, "compresion": 57456, "descompresion": 50437}
    assert h.parsear_7zip("error") is None


def test_parsear_cinebench():
    assert h.parsear_cinebench("Rendering...\nCB 12345.67 (0.00)\n") == 12345.67
    assert h.parsear_cinebench("sin resultado") is None


ARBOL_LHM = {
    "Text": "Sensor",
    "Children": [{
        "Text": "MI-PC",
        "Children": [
            {"Text": "Intel Core i5-10600K", "Children": [
                {"Text": "Clocks", "Children": [{"Text": "Core #1", "Value": "4800,0 MHz", "Children": []}]},
                {"Text": "Temperatures", "Children": [
                    {"Text": "Core #1", "Value": "70.0 °C", "Children": []},
                    {"Text": "CPU Package", "Value": "72.0 °C", "Children": []},
                ]},
            ]},
            {"Text": "ASUS PRIME Z490", "Children": [
                {"Text": "Nuvoton NCT6798D", "Children": [
                    {"Text": "Fans", "Children": [{"Text": "Fan #2", "Value": "1180 RPM", "Children": []}]},
                    {"Text": "Controls", "Children": [{"Text": "Fan Control #2", "Value": "60.0 %", "Children": []}]},
                ]},
            ]},
            {"Text": "NVIDIA GeForce RTX 2060", "Children": [
                {"Text": "Temperatures", "Children": [{"Text": "GPU Core", "Value": "65.0 °C", "Children": []}]},
            ]},
        ],
    }],
}


def test_lhm_json():
    sensores = h.parsear_lhm_json(ARBOL_LHM)
    cpu = h.temperatura_cpu(sensores)
    assert cpu["nombre"] == "CPU Package" and cpu["valor"] == 72.0
    assert {"hardware": "Nuvoton NCT6798D", "tipo": "Fan", "nombre": "Fan #2", "valor": 1180.0, "id": ""} in sensores
    reloj = next(s for s in sensores if s["tipo"] == "Clock")
    assert reloj["valor"] == 4800.0 and h._es_cpu(reloj)
    assert not any(h._es_cpu(s) for s in sensores if s["hardware"].startswith("NVIDIA"))


def test_lhm_wmi():
    filas = [
        {"Name": "Core Max", "SensorType": "Temperature", "Value": 75.5, "Identifier": "/intelcpu/0/temperature/7"},
        {"Name": "GPU Core", "SensorType": "Temperature", "Value": 60, "Identifier": "/gpu-nvidia/0/temperature/0"},
    ]
    sensores = h.parsear_lhm_wmi(filas)
    assert h.temperatura_cpu(sensores)["valor"] == 75.5
    assert h.parsear_lhm_wmi(filas[0])[0]["hardware"] == "/intelcpu/0"


def test_parsear_rtss():
    tam_entrada, offset = h._ENTRADA_RTSS.size + 16, 64
    datos = bytearray(offset + 2 * tam_entrada)
    struct.pack_into("<5I", datos, 0, h.FIRMA_RTSS, 0x00020005, tam_entrada, offset, 2)
    h._ENTRADA_RTSS.pack_into(datos, offset, 1234, b"C:\\Games\\Cyberpunk2077.exe", 0, 1000, 2000, 144, 6944)
    assert h.parsear_rtss(bytes(datos)) == [
        {"pid": 1234, "nombre": "Cyberpunk2077.exe", "fps": 144.0, "t1": 2000, "frametime_ms": 6.944}
    ]
    assert h.parsear_rtss(b"\0" * 64) == []


@pytest.mark.parametrize(
    "comando",
    ["Remove-Item C:\\tesis -Recurse", "del archivo.txt", "format D:", "winget install Discord", "Copy-Item a b",
     "reg delete HKCU\\Software\\X", "Stop-Service wuauserv", "Set-MpPreference -DisableRealtimeMonitoring $true",
     "bcdedit /set x", "iex (irm https://x)"],
)
def test_comandos_peligrosos(comando):
    assert h.comando_peligroso(comando)


@pytest.mark.parametrize(
    "comando",
    ["Get-Process | Format-Table", "Get-Process chrome | Stop-Process", "Get-Date", "Get-ChildItem $env:USERPROFILE",
     "(Get-Process | Where-Object MainWindowTitle).CloseMainWindow()"],
)
def test_comandos_inofensivos(comando):
    assert h.comando_peligroso(comando) is None


def test_formatear_speedtest():
    datos = {"download": {"bandwidth": 115_000_000}, "upload": {"bandwidth": 116_625_000}, "ping": {"latency": 12.3},
             "server": {"name": "Claro", "location": "Santo Domingo"}, "isp": "Claro"}
    assert h.formatear_speedtest(datos) == (
        "Bajada 920 Mbps, subida 933 Mbps, ping 12 ms (servidor Claro, Santo Domingo). Proveedor: Claro."
    )


def test_limpiar_para_voz():
    assert limpiar_para_voz("**El CPU ta' en 72 °C** 🔥 `ok`") == "El CPU ta' en 72 grados ok"
    assert limpiar_para_voz("72°C y 65°") == "72 grados y 65 grados"


def test_esquemas_de_herramientas():
    """Todas las herramientas generan un esquema válido para la API (nombres exactos del prompt)."""
    nombres = {beta_tool(f).to_dict()["name"] for f in h.HERRAMIENTAS}
    assert {"abrir_aplicacion", "abrir_web", "apagar_equipo", "cancelar_apagado", "set_volumen", "media_control",
            "monitor_sistema", "lanzar_benchmark", "test_velocidad", "buscar_archivo", "abrir_archivo",
            "capturar_pantalla", "alarma", "ejecutar_comando"} == nombres
    volumen = beta_tool(h.set_volumen).to_dict()["input_schema"]
    assert volumen["properties"]["modo"]["enum"] == ["relativo", "absoluto", "silenciar", "activar_sonido"]


def test_servidor_mcp_registra_todo():
    import servidor_mcp

    herramientas_mcp = asyncio.run(servidor_mcp.servidor.list_tools())
    assert len(herramientas_mcp) == len(h.HERRAMIENTAS)


class ClienteFalso:
    """Imita client.beta.messages.create devolviendo respuestas preparadas."""

    def __init__(self, respuestas):
        self.respuestas = list(respuestas)
        self.peticiones = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._crear))

    def _crear(self, **parametros):
        self.peticiones.append({**parametros, "messages": list(parametros["messages"])})
        return self.respuestas.pop(0)


def _texto(t):
    return SimpleNamespace(type="text", text=t)


def _cerebro(respuestas):
    cerebro = rochi.Cerebro(h.config.cargar())
    cerebro.cliente = ClienteFalso(respuestas)
    llamadas = []

    def abrir_aplicacion(nombre: str) -> str:
        """Falsa."""
        llamadas.append(nombre)
        return f"Abrí {nombre}."

    cerebro.herramientas["abrir_aplicacion"] = beta_tool(abrir_aplicacion)
    return cerebro, llamadas


def test_cerebro_ejecuta_herramienta_y_habla():
    uso = SimpleNamespace(type="tool_use", id="t1", name="abrir_aplicacion", input={"nombre": "Opera"})
    cerebro, llamadas = _cerebro([
        SimpleNamespace(stop_reason="tool_use", content=[uso]),
        SimpleNamespace(stop_reason="end_turn", content=[_texto("Ya te lo abrí, compay.")]),
    ])
    dicho = []
    cerebro.atender("Abre Opera", dicho.append)

    assert llamadas == ["Opera"] and dicho == ["Ya te lo abrí, compay."]
    segunda = cerebro.cliente.peticiones[1]
    assert segunda["messages"][-1]["content"][0] == {"type": "tool_result", "tool_use_id": "t1", "content": "Abrí Opera."}
    assert segunda["fallbacks"] == "default" and segunda["output_config"] == {"effort": "low"}
    assert len(cerebro.historial) == 4


def test_cerebro_historial_solo_crece_y_rechazo_no_deja_rastro():
    cerebro, _ = _cerebro([
        SimpleNamespace(stop_reason="end_turn", content=[_texto("Ta' to.")]),
        SimpleNamespace(stop_reason="refusal", content=[]),
    ])
    dicho = []
    cerebro.atender("¿Qué lo qué?", dicho.append)
    antes = list(cerebro.historial)
    cerebro.atender("otra cosa", dicho.append)

    assert cerebro.historial == antes  # el rechazo se quita entero; lo anterior no se toca
    assert dicho == ["Ta' to.", "Compay, eso no me dio. Pídemelo de otra forma."]
    primera, segunda = cerebro.cliente.peticiones
    assert segunda["messages"][: len(primera["messages"])] == primera["messages"]


def test_cerebro_respuesta_cortada_no_deja_herramienta_a_medias():
    uso = SimpleNamespace(type="tool_use", id="t1", name="abrir_aplicacion", input={})
    cerebro, llamadas = _cerebro([SimpleNamespace(stop_reason="max_tokens", content=[uso])])
    dicho = []
    cerebro.atender("Abre algo", dicho.append)
    assert cerebro.historial == [] and llamadas == []
    assert dicho == ["Compay, me enredé con eso. Dímelo otra vez más clarito."]
