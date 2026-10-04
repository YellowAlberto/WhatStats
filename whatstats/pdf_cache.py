"""Caché en memoria para diferir la generación del PDF.

El PDF (renderizado de imágenes con matplotlib + maquetación con reportlab) es
la parte más lenta y pesada del análisis. En vez de generarlo siempre en
/analizar, guardamos aquí solo los agregados pequeños que necesita (nunca el
DataFrame completo ni los mensajes en crudo) y lo construimos bajo demanda
cuando el usuario pulsa "Generar informe PDF". Es una caché de corta
duración en memoria: se pierde si el proceso se reinicia (p. ej. tras estar
inactivo en el plan Free de Render), lo cual es aceptable aquí.
"""

import secrets

MAX_INFORMES_EN_CACHE = 5
CACHE_DATOS_PDF = {}  # token -> dict con los agregados necesarios para el PDF


def _guardar_datos_pdf_en_cache(datos):
    """Guarda los datos necesarios para generar el PDF y devuelve un token
    de un solo uso para recuperarlos después. Si hay demasiados informes en
    caché, descarta el más antiguo para no acumular memoria indefinidamente."""
    token = secrets.token_urlsafe(16)
    CACHE_DATOS_PDF[token] = datos
    if len(CACHE_DATOS_PDF) > MAX_INFORMES_EN_CACHE:
        token_mas_antiguo = next(iter(CACHE_DATOS_PDF))
        del CACHE_DATOS_PDF[token_mas_antiguo]
    return token
