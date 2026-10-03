"""Lee los guiones (.txt) y los convierte en frases y palabras.

Formato de un guion:

    # Las líneas que empiezan por # son comentarios
    TITULO: título para YouTube / TikTok
    GANCHO: frase grande que sale arriba al empezar
    DESCRIPCION: texto para la descripción
    HASHTAGS: #vaper #humor
    FUENTES: de dónde salen los datos

    FELLO: Klk mi gente. 🥭 ¡Mentira!
    YEFRI: Ay, don...

Trucos dentro de una frase:
  - Los emojis (🥭💀) NO se leen en voz alta: salen en un bocadillo en pantalla.
  - {Klk|qué lo que} → en pantalla pone "Klk" pero la voz dice "qué lo que".
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from .herramientas import ErrorFabrica

_BASE_EMOJI = "[☀-➿⬀-⯿\U0001F000-\U0001FAFF]️?[\U0001F3FB-\U0001F3FF]?"
EMOJI = re.compile(f"[\U0001F1E6-\U0001F1FF]{{2}}|{_BASE_EMOJI}(?:‍{_BASE_EMOJI})*")
PRONUNCIACION = re.compile(r"\{([^{}|]*)\|([^{}]*)\}")
CABECERAS = {
    "TITULO": "titulo", "GANCHO": "gancho", "DESCRIPCION": "descripcion",
    "HASHTAGS": "hashtags", "FUENTES": "fuentes",
}


@dataclass
class Palabra:
    mostrar: str            # cómo sale en el subtítulo
    decir: list[str]        # palabras que pronuncia la voz (normalmente una)
    inicio: float = 0.0     # segundos
    fin: float = 0.0


@dataclass
class Frase:
    personaje: str          # FELLO, YEFRI...
    texto: str              # tal cual está en el guion
    texto_voz: str = ""     # lo que se manda a la voz (sin emojis)
    emojis: list[str] = field(default_factory=list)
    palabras: list[Palabra] = field(default_factory=list)
    inicio: float = 0.0
    fin: float = 0.0


@dataclass
class Guion:
    archivo: Path
    nombre: str
    titulo: str = ""
    gancho: str = ""
    descripcion: str = ""
    hashtags: str = ""
    fuentes: str = ""
    frases: list[Frase] = field(default_factory=list)


def quitar_tildes(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


def normalizar(palabra: str) -> str:
    """'¿Tú' → 'tu', 'e'' → 'e'. Sirve para comparar lo escrito con lo que dijo la voz."""
    return re.sub(r"[^a-z0-9ñ]", "", quitar_tildes(palabra.lower().replace("ñ", "\0")).replace("\0", "ñ"))


def quitar_emojis(texto: str) -> str:
    return re.sub(r"\s{2,}", " ", EMOJI.sub(" ", texto)).strip()


def _tiene_letras(texto: str) -> bool:
    return any(c.isalnum() for c in texto)


def analizar_frase(personaje: str, texto: str) -> Frase:
    frase = Frase(personaje=personaje, texto=texto, emojis=EMOJI.findall(texto))
    sin_emojis = quitar_emojis(texto)
    frase.texto_voz = re.sub(r"\s{2,}", " ", PRONUNCIACION.sub(r"\2", sin_emojis)).strip()

    # Trozos: texto normal y grupos {mostrar|decir}
    crudas: list[Palabra] = []
    posicion = 0
    for m in PRONUNCIACION.finditer(sin_emojis):
        for w in sin_emojis[posicion:m.start()].split():
            crudas.append(Palabra(w, [w]))
        pegado_antes = m.start() > 0 and not sin_emojis[m.start() - 1].isspace()
        nueva = Palabra(m.group(1).strip(), m.group(2).split())
        if pegado_antes and crudas:          # p. ej. "¡{Klk|qué lo que}"
            crudas[-1].mostrar += nueva.mostrar
            crudas[-1].decir += nueva.decir
        else:
            crudas.append(nueva)
        posicion = m.end()
        siguiente = sin_emojis[posicion:].split(maxsplit=1)
        if siguiente and not sin_emojis[posicion:posicion + 1].isspace():
            # p. ej. "{Klk|qué lo que}," → la coma va pegada
            crudas[-1].mostrar += siguiente[0]
            crudas[-1].decir += [siguiente[0]]
            posicion += len(siguiente[0])
    for w in sin_emojis[posicion:].split():
        crudas.append(Palabra(w, [w]))

    # Signos sueltos ("—", "¡") se pegan a la palabra de al lado
    palabras: list[Palabra] = []
    pendiente = ""
    for p in crudas:
        if _tiene_letras(p.mostrar):
            p.mostrar = pendiente + p.mostrar
            pendiente = ""
            palabras.append(p)
        elif p.mostrar in ("—", "–", "-"):
            continue                         # los guiones largos no se ven bien en subtítulos
        elif p.mostrar in ("¿", "¡", "«", "(", "\"") or not palabras:
            pendiente += p.mostrar
        else:
            palabras[-1].mostrar += p.mostrar
    frase.palabras = palabras
    return frase


def leer_guion(archivo: Path, personajes: dict) -> Guion:
    guion = Guion(archivo=archivo, nombre=archivo.stem)
    ultima: tuple[str, list[str]] | None = None
    dialogos: list[tuple[str, list[str]]] = []
    lineas = archivo.read_text(encoding="utf-8-sig").splitlines()
    for numero, linea in enumerate(lineas, start=1):
        limpia = linea.strip()
        if not limpia or limpia.startswith("#"):
            continue
        m = re.match(r"^([A-Za-zÁÉÍÓÚÑáéíóúñ ]{2,20}):\s*(.*)$", limpia)
        clave = quitar_tildes(m.group(1).strip().upper()) if m else ""
        if m and clave in CABECERAS:
            setattr(guion, CABECERAS[clave], m.group(2).strip())
            ultima = None
        elif m and clave in personajes:
            ultima = (clave, [m.group(2).strip()])
            dialogos.append(ultima)
        elif m and clave == m.group(1).strip() and " " not in clave:
            validos = ", ".join(personajes)
            raise ErrorFabrica(
                f"{archivo.name}, línea {numero}: no conozco al personaje '{m.group(1)}'. "
                f"Los personajes son: {validos} (se crean en ajustes.toml).")
        elif ultima is not None:
            ultima[1].append(limpia)         # la frase sigue en la línea siguiente
        else:
            raise ErrorFabrica(f"{archivo.name}, línea {numero}: no sé quién dice esto: '{limpia[:40]}'")

    for personaje, trozos in dialogos:
        frase = analizar_frase(personaje, " ".join(trozos))
        if frase.palabras:
            guion.frases.append(frase)
    if not guion.frases:
        raise ErrorFabrica(f"{archivo.name}: el guion no tiene ninguna frase.")
    return guion
