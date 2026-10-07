"""Lectura y parseo del .txt exportado de WhatsApp."""

import re
import pandas as pd


def procesar_chat_whatsapp(contenido_bytes):
    """Función de lectura corregida y universal para procesar el chat sin residuos trim."""
    # EXPRESIONES REGULARES 100% LIMPIAS Y REVISADAS SIN RESIDUOS "TRIM"
    # La hora puede venir en formato 24h ("22:30") o 12h con AM/PM pegado o con
    # espacio ("10:30 PM", "10:30PM", "10:30 p. m."). Si no se captura ese
    # sufijo como parte de la hora, se cuela al principio del nombre del autor
    # (p. ej. "PM - Juan" se lee como autor "PM - Juan") y además pandas
    # interpreta mal la hora real (medianoche acaba pareciendo mediodía).
    SUFIJO_AMPM = r'(?:\s?[AaPp]\.?\s?[Mm]\.?)?'
    patrones = [
        r'^\[?(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4})(?:,\s|\s)(\d{1,2}:\d{2}(?::\d{2})?' + SUFIJO_AMPM + r')\]?\s(?:-\s)?([^:]+):\s(.*)$',
        r'^(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4})(?:,\s|\s|-|\s-)\s*(\d{1,2}:\d{2}(?::\d{2})?' + SUFIJO_AMPM + r')\s*-\s*([^:]+):\s(.*)$',
        r'^(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4})\s+(\d{1,2}:\d{2}' + SUFIJO_AMPM + r')\s+-\s+([^:]+):\s(.*)$'
    ]

    frases_sistema = [
        'cambiaste el nombre', 'cambiaste la descripción', 'cambiaste los ajustes',
        'creaste este grupo', 'añadió a', 'eliminó a', 'salió', 'unió', 'cambió el icono',
        'código de seguridad', 'mensajes temporales', 'creó el enlace'
    ]

    datos = []
    mensaje_actual = None
    # Probamos primero utf-8-sig para librarnos del BOM que añaden algunos exports de iOS
    try:
        texto_decodificado = contenido_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        texto_decodificado = contenido_bytes.decode("utf-8", errors="ignore")
    lineas = texto_decodificado.splitlines()

    for linea in lineas:
        linea_limpia = linea.strip()
        if not linea_limpia:
            continue

        match = None
        for patron in patrones:
            match = re.match(patron, linea_limpia)
            if match:
                break

        if match:
            fecha, hora, autor, texto = match.groups()
            autor_clean = autor.strip()

            if any(frase in autor_clean.lower() or frase in texto.lower() for frase in frases_sistema) or len(autor_clean) > 40:
                continue

            if mensaje_actual:
                datos.append(mensaje_actual)

            mensaje_actual = {
                'Fecha': fecha,
                'Hora': hora,
                'Autor': autor_clean,
                'Mensaje': texto.strip()
            }
        else:
            if mensaje_actual:
                mensaje_actual['Mensaje'] += " " + linea_limpia

    if mensaje_actual:
        datos.append(mensaje_actual)

    return pd.DataFrame(datos)
