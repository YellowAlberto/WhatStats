"""Constantes y patrones compartidos por varias partes del análisis."""

import re

# --- Patrones auxiliares reutilizados en varias partes del análisis ---
FRASES_MULTIMEDIA = [
    'multimedia omitido', 'imagen omitida', 'video omitido', 'audio omitido',
    'sticker omitido', 'gif omitido', 'documento omitido', 'contacto omitido',
    'media omitted', 'image omitted', 'video omitted', 'audio omitted',
    'sticker omitted', 'gif omitted', 'document omitted', 'contact card omitted',
    '<archivo adjunto>', '<attached:'
]

FRASES_ELIMINADO = [
    'this message was deleted', 'se eliminó este mensaje',
    'eliminaste este mensaje', 'you deleted this message'
]

PATRON_EMOJI = re.compile(
    "(?:"
    "[\U0001F300-\U0001F5FF"
    "\U0001F600-\U0001F64F"
    "\U0001F680-\U0001F6FF"
    "\U0001F900-\U0001FAFF"
    "\U00002600-\U000026FF"
    "\U00002700-\U000027BF"
    "\U0001F1E6-\U0001F1FF"
    "\U00002B00-\U00002BFF"
    "]"
    # Se agrupan junto al emoji base los modificadores de tono de piel
    # (\U0001F3FB-\U0001F3FF), el selector de variación "️" y el
    # conector ZWJ "‍" (emojis compuestos, ej. familias, 👍🏾), para
    # que no se cuenten como "emojis" sueltos independientes del emoji
    # al que pertenecen.
    "[\U0001F3FB-\U0001F3FF️‍]*"
    ")"
)

DIAS_SEMANA_ES = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']


EXPLICACIONES_GRAFICAS = {
    "ranking": "Ranking de los miembros que más mensajes han enviado en total. Es la foto más directa "
               "de quién sostiene la conversación del grupo.",
    "horas": "Distribución de mensajes según la hora del día. Permite ver si el grupo es más activo "
             "por la mañana, a mediodía o de madrugada.",
    "heatmap": "Cruce entre día de la semana y hora del día: cada celda indica cuántos mensajes se "
               "enviaron en ese tramo concreto, revelando rutinas semanales de actividad.",
    "matriz": "Matriz de afinidad cruzada: para cada miembro (fila), qué porcentaje de sus respuestas "
              "rápidas (menos de 15 minutos) van dirigidas a responder a cada otro miembro (columna).",
    "evolucion": "Evolución del volumen total de mensajes año a año, útil para ver si el grupo ha ido "
                 "creciendo, manteniéndose o perdiendo actividad con el tiempo.",
    "tiempo": "Tiempo medio que tarda cada miembro en responder cuando alguien más le escribe "
              "(solo se cuentan respuestas dentro de una ventana de 2 horas).",
    "fantasma": "Porcentaje de mensajes de cada miembro que se quedan sin respuesta de nadie durante "
                "más de 3 horas: una forma de medir quién suele quedar 'en visto'.",
    "multimedia": "Cantidad de fotos, vídeos, audios, stickers y documentos que ha compartido cada "
                  "miembro (contenido que no se puede analizar como texto).",
    "eliminados": "Cantidad de mensajes que cada miembro ha eliminado para todos después de enviarlos.",
    "longitud": "Longitud media, en caracteres, de los mensajes de texto de cada miembro: quién escribe "
                "párrafos y quién prefiere respuestas cortas.",
    "emojis": "Los emojis que más se repiten en las conversaciones de texto del grupo.",
    "palabras": "Frecuencia de aparición de una lista de palabras clave (elegidas por el usuario o por "
                "defecto) a lo largo de todo el historial del chat.",
    "burbujas": "Mapa de las 100 palabras más repetidas en el grupo (excluyendo multimedia y palabras "
                "vacías): cuanto más grande la burbuja, más veces se ha usado esa palabra.",
}
