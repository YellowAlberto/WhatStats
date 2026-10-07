"""Deduce el nombre del grupo (o contacto) a partir del nombre del archivo.

El texto del chat exportado NO incluye el nombre del grupo, pero WhatsApp lo
pone en el nombre del archivo: "Chat de WhatsApp con NOMBRE.txt" (Android),
"WhatsApp Chat - NOMBRE.zip" (iPhone), "WhatsApp Chat with NOMBRE.zip" (inglés)...
"""

import re

_PATRONES = [
    re.compile(r'^chat de whatsapp con (?P<n>.+)$', re.IGNORECASE),
    re.compile(r'^conversaci[oó]n de whatsapp con (?P<n>.+)$', re.IGNORECASE),
    re.compile(r'^whatsapp chat with (?P<n>.+)$', re.IGNORECASE),
    re.compile(r'^whatsapp chat\s*[-–—]\s*(?P<n>.+)$', re.IGNORECASE),
]
# Nombres de archivo genéricos que no aportan nada como título
_GENERICOS = {"chat", "_chat", "whatsapp chat", "whatsapp", "chat de whatsapp"}
_LONGITUD_MAXIMA = 80


def _sin_ruta_ni_extension(nombre):
    nombre = re.split(r'[\\/]', nombre or "")[-1].strip()
    nombre = re.sub(r'\.(txt|zip)$', '', nombre, flags=re.IGNORECASE)
    # Copias del navegador: "Chat de WhatsApp con X (1)"
    return re.sub(r'\s*\(\d+\)$', '', nombre).strip()


def nombre_chat_desde_archivo(*nombres):
    """Devuelve el nombre del grupo a partir de uno o varios nombres de archivo
    (se prueban en orden: el archivo subido y, si era un zip, el .txt de dentro).
    Devuelve None si no se puede deducir uno útil."""
    candidatos = [_sin_ruta_ni_extension(n) for n in nombres if n]
    candidatos = [c for c in candidatos if c]

    for candidato in candidatos:
        for patron in _PATRONES:
            m = patron.match(candidato)
            if m and m.group("n").strip():
                return m.group("n").strip()[:_LONGITUD_MAXIMA]

    # Archivo renombrado a mano (p. ej. "Clase 2B.txt"): se usa tal cual
    for candidato in candidatos:
        if candidato.lower().strip(" _-") not in _GENERICOS:
            return candidato[:_LONGITUD_MAXIMA]
    return None
