"""Rochi: asistente de voz dominicano para Windows 11, con Claude como cerebro.

Uso:
    python rochi.py            # por voz (micrófono y altavoces)
    python rochi.py --texto    # escribiendo, para probar sin micrófono
    python rochi.py --mudo     # no habla, solo escribe las respuestas
    python rochi.py --microfonos   # lista los micrófonos (para "microfono" en config.json)
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from datetime import datetime
from typing import Callable

import anthropic
from anthropic import beta_tool

import config
import herramientas
from herramientas import normalizar
from voz import Oido, Teclado, Voz

log = logging.getLogger("rochi")

SALUDO = "Aquí estoy compay, ¿qué es lo que tú quieres que le haga loco?"
DESPEDIDA = "A la orden, compay. Cuando me necesites, me llamas."
# Lo que puede venir después del nombre sin que sea una orden ("Rochi, ¿estás ahí?", "Rochi, ven acá").
SOLO_LLAMADA = {"", "estas ahi", "tas ahi", "estas", "ahi", "ven aca", "ven aqui", "ven", "oye", "dime", "mira"}
DESPEDIDAS = {"eso es todo", "eso es to", "descansa", "vete a dormir", "ve a dormir", "nada mas", "ya esta", "ya ta"}

MAX_VUELTAS = 10  # llamadas al modelo por orden (cada ronda de herramientas cuenta una)
MAX_MENSAJES = 80  # al pasar de aquí se empieza una conversación nueva
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def detectar_activacion(texto: str, palabras: set[str]) -> tuple[bool, str]:
    """Devuelve (¿dijeron el nombre?, lo que viene después del nombre)."""
    for palabra in re.finditer(r"\w+", texto):
        if normalizar(palabra.group()) in palabras:
            return True, texto[palabra.end():].lstrip(" ,.;:!¡?¿-").strip()
    return False, texto.strip()


def marca_de_tiempo(ahora: datetime) -> str:
    return f"[{DIAS[ahora.weekday()]} {ahora.day} de {MESES[ahora.month - 1]}, {ahora:%H:%M}]"


def contenido_para_historial(contenido: list) -> list:
    """Prepara la respuesta del modelo para devolverla en el historial.

    Si hubo un cambio de modelo por fallback a mitad de respuesta, la API pide no
    devolver los bloques de pensamiento ni de herramienta anteriores al último
    bloque "fallback"; el texto sí se conserva.
    """
    cortes = [i for i, bloque in enumerate(contenido) if bloque.type == "fallback"]
    if not cortes:
        return list(contenido)
    corte = cortes[-1]
    return [b for i, b in enumerate(contenido) if i >= corte or b.type == "text"]


class Cerebro:
    """La conversación con Claude: un bucle de herramientas con historial que solo crece."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.cliente = anthropic.Anthropic()
        # Sin credenciales el SDK solo falla al hacer la primera petición; mejor avisar al arrancar.
        # (_token_cache es donde el SDK guarda los perfiles de `ant auth login`.)
        if self.cliente.api_key is None and self.cliente.auth_token is None and getattr(self.cliente, "_token_cache", None) is None:
            raise SystemExit('Falta la API key de Anthropic. Ponla con: setx ANTHROPIC_API_KEY "sk-ant-..." y abre otra terminal.')
        self.herramientas = {h.name: h for h in (beta_tool(f) for f in herramientas.HERRAMIENTAS)}
        # El sistema y las herramientas no cambian durante la sesión: así la caché de prompts aguanta.
        self.definiciones = [h.to_dict() for h in self.herramientas.values()]
        self.sistema = (config.CARPETA / cfg["prompt_sistema"]).read_text(encoding="utf-8")
        self.historial: list[dict] = []
        self.ultimo_uso = 0.0

    def _pedir(self):
        parametros = {
            "model": self.cfg["modelo"],
            "max_tokens": 16000,
            "system": self.sistema,
            "tools": self.definiciones,
            "messages": self.historial,
            "cache_control": {"type": "ephemeral"},
        }
        if self.cfg["esfuerzo"]:
            parametros["output_config"] = {"effort": self.cfg["esfuerzo"]}
        if self.cfg["fallbacks"]:
            # Si un clasificador de seguridad rechaza la petición (falso positivo), se repite en otro modelo.
            parametros["betas"] = ["server-side-fallback-2026-07-01"]
            parametros["fallbacks"] = "default"
        return self.cliente.beta.messages.create(**parametros)

    def _ejecutar(self, bloque) -> dict:
        log.info("-> %s(%s)", bloque.name, json.dumps(bloque.input, ensure_ascii=False))
        herramienta = self.herramientas.get(bloque.name)
        try:
            if herramienta is None:
                raise herramientas.ErrorHerramienta(f"No existe la herramienta '{bloque.name}'.")
            salida = str(herramienta.call(bloque.input))
            log.info("<- %s", salida[:300])
            return {"type": "tool_result", "tool_use_id": bloque.id, "content": salida}
        except Exception as error:
            detalle = f"{error} ({error.__cause__})" if error.__cause__ else str(error)
            log.warning("<- error en %s: %s", bloque.name, detalle)
            return {"type": "tool_result", "tool_use_id": bloque.id, "content": f"Error: {detalle}", "is_error": True}

    def atender(self, orden: str, decir: Callable[[str], None]) -> None:
        memoria = self.cfg["activacion"]["memoria_min"] * 60
        if time.monotonic() - self.ultimo_uso > memoria or len(self.historial) > MAX_MENSAJES:
            self.historial = []  # conversación nueva (nunca se editan turnos viejos de una conversación)
        inicio = len(self.historial)
        self.historial.append({"role": "user", "content": f"{marca_de_tiempo(datetime.now())}\n{orden}"})
        try:
            for _ in range(MAX_VUELTAS):
                respuesta = self._pedir()
                if respuesta.stop_reason == "refusal":
                    del self.historial[inicio:]
                    decir("Compay, eso no me dio. Pídemelo de otra forma.")
                    return
                if respuesta.stop_reason == "max_tokens":  # respuesta cortada: puede traer una herramienta a medias
                    del self.historial[inicio:]
                    decir("Compay, me enredé con eso. Dímelo otra vez más clarito.")
                    return
                contenido = contenido_para_historial(respuesta.content)
                self.historial.append({"role": "assistant", "content": contenido})
                texto = " ".join(b.text for b in contenido if b.type == "text").strip()
                if texto:
                    decir(texto)  # se dice antes de correr las herramientas ("eso tarda un chin...")
                usos = [b for b in contenido if b.type == "tool_use"]
                if respuesta.stop_reason != "tool_use" or not usos:
                    return
                self.historial.append({"role": "user", "content": [self._ejecutar(b) for b in usos]})
            decir("Compay, me enredé con eso. Dímelo otra vez más clarito.")
        except anthropic.AuthenticationError:
            self._fallo(inicio, decir, "Compay, no tengo la llave de la API de Claude. Revisa ANTHROPIC_API_KEY.")
        except anthropic.PermissionDeniedError:
            self._fallo(inicio, decir, "Compay, la llave de la API no tiene permiso para ese modelo.")
        except anthropic.NotFoundError:
            self._fallo(inicio, decir, f"Compay, el modelo {self.cfg['modelo']} no existe. Revisa el config.")
        except anthropic.RateLimitError:
            self._fallo(inicio, decir, "Me tienen frenao con tanta pregunta, compay. Dame un chin y vuelve.")
        except anthropic.BadRequestError as error:
            log.error("Petición rechazada: %s", error)
            self.historial = []  # si el historial quedó inválido, se empieza de cero
            decir("Compay, esa me salió mala. Repítemelo, que empecé de cero.")
        except anthropic.APIStatusError as error:
            self._fallo(inicio, decir, "El cerebro me dio un error, compay. Inténtalo en un chin.", error)
        except anthropic.APIConnectionError:
            self._fallo(inicio, decir, "Compay, no tengo internet para pensar. Revisa la conexión.")
        finally:
            self.ultimo_uso = time.monotonic()

    def _fallo(self, inicio: int, decir: Callable[[str], None], mensaje: str, error: Exception | None = None) -> None:
        if error is not None:
            log.error("Error de la API: %s", error)
        del self.historial[inicio:]  # quitar solo lo de esta orden; lo anterior queda intacto
        decir(mensaje)


def main() -> None:
    parser = argparse.ArgumentParser(description="Rochi, el asistente de voz de este PC.")
    parser.add_argument("--texto", action="store_true", help="escribir en vez de hablar por el micrófono")
    parser.add_argument("--mudo", action="store_true", help="no reproducir la voz, solo escribir las respuestas")
    parser.add_argument("--debug", action="store_true", help="mostrar más detalles en la consola")
    parser.add_argument("--microfonos", action="store_true", help="listar los micrófonos y salir")
    args = parser.parse_args()

    if args.microfonos:
        import speech_recognition as sr

        for indice, nombre in enumerate(sr.Microphone.list_microphone_names()):
            print(f"{indice}: {nombre}")
        return

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    for ruidoso in ("httpx", "httpx2", "anthropic"):
        logging.getLogger(ruidoso).setLevel(logging.WARNING)

    cfg = config.cargar()
    voz = Voz(cfg, mudo=args.mudo)
    herramientas.registrar_notificador(voz.hablar)
    cerebro = Cerebro(cfg)
    oido = Teclado() if args.texto else Oido(cfg, voz)
    palabras = {normalizar(p) for p in cfg["activacion"]["palabras"]}
    ventana = cfg["activacion"]["ventana_conversacion_seg"]

    # En modo texto todo lo que se escribe va para Rochi; por voz hace falta llamarlo por su nombre.
    activo_hasta = float("inf") if args.texto else 0.0
    print("Rochi está escuchando. Dile: \"Rochi, ¿estás ahí?\"  (Ctrl+C para salir)", flush=True)

    try:
        while True:
            restante = activo_hasta - time.monotonic()
            en_conversacion = restante > 0
            texto = oido.escuchar(timeout=restante if en_conversacion and not args.texto else None)
            if not texto:
                continue
            llamado, orden = detectar_activacion(texto, palabras)
            if not llamado and not en_conversacion:
                log.debug("Ignorado (no me llamaron): %s", texto)
                continue
            if not args.texto:
                log.info("Tú: %s", texto)

            if llamado and normalizar(orden) in SOLO_LLAMADA:
                voz.hablar(SALUDO)
            elif normalizar(orden) in DESPEDIDAS:
                voz.hablar(DESPEDIDA)
                if not args.texto:
                    activo_hasta = 0.0
                continue
            else:
                cerebro.atender(orden, voz.hablar)

            if not args.texto:
                activo_hasta = time.monotonic() + ventana
    except KeyboardInterrupt:
        print("\n¡Nos vemos, compay!")


if __name__ == "__main__":
    sys.exit(main())
