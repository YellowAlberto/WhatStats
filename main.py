import re
import os
import io
import base64
import secrets
import datetime
from collections import Counter
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg') # Evita bloqueos en servidores web
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import seaborn as sns

import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image as RLImage, PageBreak, HRFlowable
)

from fastapi import FastAPI, File, UploadFile, Request, Form
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# --- Cargar variables de entorno desde un archivo .env (si existe) ---
# FastAPI/uvicorn NO leen el .env automáticamente: hay que cargarlo explícitamente
# con python-dotenv para que os.environ vea las claves definidas ahí.
try:
    from dotenv import load_dotenv
    load_dotenv()  # busca un archivo .env en el directorio de trabajo (o superiores)
except ImportError:
    print("[Aviso] python-dotenv no está instalado: el archivo .env no se cargará "
          "automáticamente. Instálalo con `pip install python-dotenv` o exporta "
          "la variable GEMINI_API_KEY manualmente en el entorno.")

# --- Cliente de la API de Gemini (Google) para el resumen generado por IA ---
# Requiere la variable de entorno GEMINI_API_KEY (o GOOGLE_API_KEY) y `pip install google-genai`.
# Si no está disponible, el informe se genera igualmente sin el resumen de IA.
CLIENTE_GEMINI = None
try:
    from google import genai as google_genai
    from google.genai import types as google_genai_types

    _clave_gemini = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not _clave_gemini:
        print("[Aviso] No se ha encontrado GEMINI_API_KEY ni GOOGLE_API_KEY en el entorno. "
              "Comprueba que tu archivo .env está en el mismo directorio desde el que "
              "arrancas el servidor y que la variable se llama exactamente así.")
    else:
        CLIENTE_GEMINI = google_genai.Client(api_key=_clave_gemini)
        print("[Info] Cliente de Gemini inicializado correctamente "
              f"(clave terminada en ...{_clave_gemini[-4:]}).")
except Exception as e:
    print(f"[Aviso] No se pudo inicializar el cliente de Gemini: {e}")
    CLIENTE_GEMINI = None


app = FastAPI(title="Analizador de WhatsApp Completo")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

os.makedirs("static", exist_ok=True)

# =============================================================================
# CACHÉ EN MEMORIA PARA DIFERIR LA GENERACIÓN DEL PDF
# =============================================================================
# El PDF (llamada a Gemini + renderizado de imágenes con matplotlib + maquetación
# con reportlab) es la parte más lenta y pesada del análisis. En vez de generarlo
# siempre en /analizar, guardamos aquí solo los agregados pequeños que necesita
# (nunca el DataFrame completo ni los mensajes en crudo) y lo construimos bajo
# demanda cuando el usuario pulsa "Generar informe PDF". Es una caché de corta
# duración en memoria: se pierde si el proceso se reinicia (p. ej. tras estar
# inactivo en el plan Free de Render), lo cual es aceptable aquí.
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
    "["
    "\U0001F300-\U0001F5FF"
    "\U0001F600-\U0001F64F"
    "\U0001F680-\U0001F6FF"
    "\U0001F900-\U0001FAFF"
    "\U00002600-\U000026FF"
    "\U00002700-\U000027BF"
    "\U0001F1E6-\U0001F1FF"
    "\U00002B00-\U00002BFF"
    "]"
)

DIAS_SEMANA_ES = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']


def procesar_chat_whatsapp(contenido_bytes):
    """Función de lectura corregida y universal para procesar el chat sin residuos trim."""
    # EXPRESIONES REGULARES 100% LIMPIAS Y REVISADAS SIN RESIDUOS "TRIM"
    patrones = [
        r'^\[?(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4})(?:,\s|\s)(\d{1,2}:\d{2})(?::\d{2})?\]?\s(?:-\s)?([^:]+):\s(.*)$',
        r'^(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4})(?:,\s|\s|-|\s-)\s*(\d{1,2}:\d{2})(?::\d{2})?\s*-\s*([^:]+):\s(.*)$',
        r'^(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4})\s+(\d{1,2}:\d{2})\s+-\s+([^:]+):\s(.*)$'
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


def empaquetar_circulos(radii):
    """Algoritmo geométrico original para empaquetar las burbujas."""
    N = len(radii)
    pos = np.zeros((N, 2))
    if N == 0: return pos
    pos[0] = [0, 0]
    if N == 1: return pos
    pos[1] = [radii[0] + radii[1], 0]

    def calcular_distancia(p1, p2):
        return np.sqrt((p1[0]-p2[0])**2 + (p1[1]-p2[1])**2)

    def evaluar_colision(punto, radio, indices_colocados):
        for j in indices_colocados:
            if calcular_distancia(punto, pos[j]) < (radio + radii[j]) - 1e-3:
                return True
        return False

    for i in range(2, N):
        r_i = radii[i]
        mejor_posicion = None
        distancia_minima_centro = float('inf')

        for j in range(i):
            for k in range(j + 1, i):
                r1 = radii[j] + r_i
                r2 = radii[k] + r_i
                p1 = pos[j]
                p2 = pos[k]
                d = calcular_distancia(p1, p2)

                if d > r1 + r2 or d < abs(r1 - r2):
                    continue

                a = (r1**2 - r2**2 + d**2) / (2 * d)
                h = np.sqrt(max(0, r1**2 - a**2))
                p3 = p1 + a * (p2 - p1) / d

                candidato_1 = [p3[0] + h * (p2[1] - p1[1]) / d, p3[1] - h * (p2[0] - p1[0]) / d]
                candidato_2 = [p3[0] - h * (p2[1] - p1[1]) / d, p3[1] + h * (p2[0] - p1[0]) / d]

                for cand in [candidato_1, candidato_2]:
                    if not evaluar_colision(cand, r_i, range(i)):
                        dist_orig = np.sqrt(cand[0]**2 + cand[1]**2)
                        if dist_orig < distancia_minima_centro:
                            distancia_minima_centro = dist_orig
                            mejor_posicion = cand

        if mejor_posicion is None:
            for j in range(i):
                p_j = pos[j]
                d_j = np.sqrt(p_j[0]**2 + p_j[1]**2)
                vector_direccion = p_j / d_j if d_j > 0 else np.array([1, 0])
                cand = p_j + vector_direccion * (radii[j] + r_i)
                if not evaluar_colision(cand, r_i, range(i)):
                    dist_orig = np.sqrt(cand[0]**2 + cand[1]**2)
                    if dist_orig < distancia_minima_centro:
                        distancia_minima_centro = dist_orig
                        mejor_posicion = cand

        if mejor_posicion is None:
            angulo = i * 0.1
            radio_espiral = np.sqrt(i) * max(radii)
            mejor_posicion = [radio_espiral * np.cos(angulo), radio_espiral * np.sin(angulo)]

        pos[i] = mejor_posicion
    return pos


# =============================================================================
# UTILIDADES PARA EL INFORME PDF (gráficas estáticas + resumen IA + maquetación)
# =============================================================================
# Las gráficas del PDF se generan con matplotlib (no con Plotly/Kaleido): no
# depende de ningún navegador ni subproceso externo, así que no hay popups,
# cuelgues ni arranques en frío. Las gráficas INTERACTIVAS de la web siguen
# siendo las de Plotly de siempre; esto solo afecta a las imágenes del PDF.

_COLOR_FONDO_MPL = '#1E293B'
_COLOR_TEXTO_MPL = '#E2E8F0'
_COLOR_EJES_MPL = '#94A3B8'


def _figura_mpl_base(figsize):
    """Crea una figura de matplotlib con el mismo estilo oscuro que la web."""
    plt.style.use('dark_background')
    fig, ax = plt.subplots(figsize=figsize)
    fig.patch.set_facecolor(_COLOR_FONDO_MPL)
    ax.set_facecolor(_COLOR_FONDO_MPL)
    ax.set_title(ax.get_title(), color='white')
    ax.tick_params(colors=_COLOR_EJES_MPL, labelsize=9)
    for spine in ax.spines.values():
        spine.set_visible(False)
    return fig, ax


def _guardar_mpl_a_bytes(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=130, facecolor=_COLOR_FONDO_MPL, bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


def grafico_barh_mpl(categorias, valores, titulo, color='#14B8A6', fmt='{:,.0f}', figsize=(10, 6), cmap=None):
    fig, ax = _figura_mpl_base(figsize)
    if cmap is not None and len(valores) > 0:
        norm = plt.Normalize(min(valores), max(valores) if max(valores) > 0 else 1)
        colores_barras = [plt.get_cmap(cmap)(norm(v)) for v in valores]
    else:
        colores_barras = color
    barras = ax.barh(categorias, valores, color=colores_barras)
    ax.set_title(titulo, color='white', fontsize=13, fontweight='bold', pad=14)
    ax.set_xticks([])
    maximo = max(valores) if len(valores) and max(valores) > 0 else 1
    for barra, valor in zip(barras, valores):
        ax.text(barra.get_width() + maximo * 0.015, barra.get_y() + barra.get_height() / 2,
                fmt.format(valor), va='center', color='white', fontsize=9)
    plt.tight_layout()
    return _guardar_mpl_a_bytes(fig)


def grafico_barv_mpl(categorias, valores, titulo, color='#128C7E', fmt='{:,.0f}', figsize=(10, 5.5)):
    fig, ax = _figura_mpl_base(figsize)
    barras = ax.bar(categorias, valores, color=color)
    ax.set_title(titulo, color='white', fontsize=13, fontweight='bold', pad=14)
    ax.set_yticks([])
    maximo = max(valores) if len(valores) and max(valores) > 0 else 1
    for barra, valor in zip(barras, valores):
        ax.text(barra.get_x() + barra.get_width() / 2, barra.get_height() + maximo * 0.015,
                fmt.format(valor), ha='center', va='bottom', color='white', fontsize=9)
    plt.tight_layout()
    return _guardar_mpl_a_bytes(fig)


def grafico_linea_mpl(x, y, titulo, color='#128C7E', figsize=(10, 5)):
    fig, ax = _figura_mpl_base(figsize)
    ax.plot(x, y, color=color, marker='o', linewidth=2.2, markersize=4)
    ax.set_title(titulo, color='white', fontsize=13, fontweight='bold', pad=14)
    ax.xaxis.set_major_locator(mticker.MultipleLocator(2))
    ax.grid(axis='y', color='#334155', linewidth=0.5, alpha=0.5)
    plt.tight_layout()
    return _guardar_mpl_a_bytes(fig)


def grafico_heatmap_mpl(datos_2d, x_labels, y_labels, titulo, cmap='YlGnBu', figsize=(10, 4.5), anotar=False, fmt=""):
    plt.style.use('dark_background')
    fig, ax = plt.subplots(figsize=figsize)
    fig.patch.set_facecolor(_COLOR_FONDO_MPL)
    sns.heatmap(
        datos_2d, xticklabels=x_labels, yticklabels=y_labels, cmap=cmap, ax=ax,
        cbar=False, annot=anotar, fmt=fmt, linewidths=0.6, linecolor=_COLOR_FONDO_MPL,
        annot_kws={"size": 7, "color": "#0F172A"} if anotar else None
    )
    ax.set_title(titulo, color='white', fontsize=13, fontweight='bold', pad=14)
    ax.tick_params(colors=_COLOR_EJES_MPL, labelsize=8)
    plt.tight_layout()
    return _guardar_mpl_a_bytes(fig)


def generar_resumen_ia(stats):
    """Genera un resumen del 'carácter' del grupo usando la API de Gemini (Google),
    a partir únicamente de estadísticas agregadas y curiosidades ya calculadas
    en Python (nunca se envían mensajes individuales, salvo la LONGITUD del
    más largo, nunca su contenido)."""
    if CLIENTE_GEMINI is None:
        return ("No se ha generado un resumen con IA porque el servidor no tiene "
                "configurada la clave GEMINI_API_KEY (o GOOGLE_API_KEY).")

    perfiles = stats.get('perfiles_integrantes', [])
    lineas_integrantes = []
    for p in perfiles:
        hora_txt = f"{p['hora_favorita']}h" if p['hora_favorita'] is not None else "sin horario claro"
        lineas_integrantes.append(
            f"- {p['usuario']}: {p['mensajes']} mensajes, más activo sobre las {hora_txt}, "
            f"mensajes de ~{p['longitud_media']:.0f} caracteres de media, emoji favorito {p['emoji_favorito']}"
        )
    listado_integrantes = "\n".join(lineas_integrantes) if lineas_integrantes else "(sin datos individuales)"

    nota_omitidos = ""
    if stats.get('integrantes_omitidos', 0) > 0:
        nota_omitidos = (f"\n(Hay {stats['integrantes_omitidos']} integrantes más, muy poco activos, que no "
                         f"aparecen en este listado individual: puedes referirte a ellos como grupo, de pasada, "
                         f"sin inventarles datos.)")

    # Cuantas más personas haya que mencionar, más margen de tokens/palabras hace falta
    max_tokens = min(4000, 700 + 25 * len(perfiles))

    prompt = f"""Eres el cronista extraoficial y con sentido del humor de un grupo de WhatsApp.
No has visto ni un solo mensaje original: solo estos datos agregados y curiosidades ya calculadas.

DATOS GENERALES
- {stats['total_mensajes']} mensajes entre el {stats['fecha_inicio']} y el {stats['fecha_fin']}
- {stats['num_usuarios']} participantes activos
- Top 5 más activos (usuario: mensajes): {stats['top5_usuarios']}
- Multimedia enviado: {stats['pct_multimedia']:.1f}% de los mensajes · Mensajes borrados por sus autores: {stats['pct_eliminados']:.1f}%

CURIOSIDADES Y "PERSONAJES" DEL GRUPO (la materia prima para las anécdotas destacadas)
- El día más movido de toda su historia fue el {stats['dia_mas_activo']}, con {stats['mensajes_dia_mas_activo']} mensajes ese solo día.
- La racha más larga escribiendo sin fallar un día fue de {stats['racha_maxima']} días consecutivos.
- El emoji estrella del grupo es {stats['emoji_estrella']}, y quien más lo usa es {stats['usuario_emoji_estrella']} ({stats['cantidad_emoji_estrella']} veces).
- El búho nocturno es {stats['usuario_nocturno']}: un {stats['pct_nocturno_valor']:.0f}% de sus mensajes los manda entre medianoche y las 6 de la mañana.
- El madrugador es {stats['usuario_madrugador']}: un {stats['pct_madrugador_valor']:.0f}% de sus mensajes son entre las 6 y las 9 de la mañana.
- El mensaje más largo jamás escrito tiene {stats['longitud_mensaje_largo']} caracteres (una novela) y es obra de {stats['autor_mensaje_largo']} (no conoces el contenido, solo la longitud).
- El rey o reina del "visto": {stats['top_fantasma']}, cuyos mensajes se quedan más tiempo sin respuesta de nadie.
- El más rápido respondiendo cuando alguien le escribe es {stats['respondedor_rapido']}, con una media de {stats['tiempo_respondedor_rapido']:.1f} minutos.
- La palabra clave estrella del grupo es "{stats['palabra_estrella']}", y quien más la repite es {stats['usuario_palabra_estrella']}.
- Emojis más repetidos en general: {stats['top_emojis']}
- Palabras clave más repetidas en general: {stats['top_palabras']}

FICHA INDIVIDUAL DE CADA INTEGRANTE (obligatorio usarla, ver instrucción final)
{listado_integrantes}{nota_omitidos}

Con estos datos, escribe un resumen DIVERTIDO Y ESPECÍFICO en español, en prosa y sin listas ni encabezados,
que suene como si conocieras de verdad al grupo. Usa 4 o 5 de las curiosidades de arriba como titulares o
anécdotas graciosas (el búho nocturno, el rey del visto, la palabra estrella, la racha de días, el mensaje
kilométrico...). Tono cercano y con humor ligero, tipo "resumen anual estilo Spotify Wrapped pero de WhatsApp".

REQUISITO IMPRESCINDIBLE: además de esas anécdotas destacadas, tienes que dedicarle al menos una mención
breve y específica a CADA UNO de los integrantes de la "ficha individual" de arriba (aunque solo sea una
frase corta usando su emoji favorito, su hora más activa o su longitud media de mensaje) — nadie de esa
lista puede quedarse sin nombrar. Si el grupo es grande, ajusta la longitud del texto y agrupa a varias
personas en la misma frase si hace falta, pero no omitas a nadie de la lista. No inventes hechos, cifras
ni nombres que no estén en los datos de arriba. Escribe en prosa corrida, sin emojis ni símbolos decorativos."""

    try:
        respuesta = CLIENTE_GEMINI.models.generate_content(
            model="gemini-3.5-flash",
            contents=prompt,
            config=google_genai_types.GenerateContentConfig(
                max_output_tokens=max_tokens,
                # Sin esto, el modelo gasta parte del presupuesto de tokens en
                # "pensar" internamente antes de escribir, y el texto visible
                # puede cortarse a mitad de frase. Para una tarea de redacción
                # como esta no hace falta razonamiento, así que lo desactivamos.
                thinking_config=google_genai_types.ThinkingConfig(thinking_budget=0),
            ),
        )
        texto = (respuesta.text or "").strip()

        # Aviso en logs si, aun así, la respuesta se quedó corta por límite de tokens
        try:
            motivo_corte = respuesta.candidates[0].finish_reason
            if motivo_corte and "MAX_TOKENS" in str(motivo_corte):
                print(f"[Resumen IA] Aviso: la respuesta se cortó por MAX_TOKENS (max_tokens={max_tokens}).")
        except Exception:
            pass

        return texto
    except Exception as e:
        print(f"[Resumen IA] Error llamando a la API de Gemini: {e}")
        return f"No se pudo generar el resumen con IA en este momento ({type(e).__name__})."


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


PATRON_EMOJI_LIMPIEZA = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U0001F1E6-\U0001F1FF"
    "\U00002B00-\U00002BFF"
    "\U0001F900-\U0001F9FF"
    "\uFE0F"   # variation selector (aparece en emojis como ⏱️ o 🗓️)
    "\u200d"   # zero-width joiner (secuencias de emoji compuestas)
    "]+"
)


def limpiar_texto_pdf(texto):
    """Elimina emojis y símbolos pictográficos de un texto antes de insertarlo
    en el PDF: las fuentes básicas de reportlab (Helvetica) no los soportan y
    su presencia puede hacer que la generación del PDF falle silenciosamente."""
    if not texto:
        return texto
    texto_limpio = PATRON_EMOJI_LIMPIEZA.sub('', texto)
    return re.sub(r'[ \t]{2,}', ' ', texto_limpio).strip()


def generar_informe_pdf(stats, resumen_ia, imagenes):
    """Construye el informe PDF completo (portada + resumen IA + una sección
    por cada gráfica con su explicación) y devuelve los bytes del archivo.
    `imagenes` es un dict {clave: bytes_png}."""

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=2*cm, bottomMargin=2*cm, leftMargin=2*cm, rightMargin=2*cm
    )

    estilos = getSampleStyleSheet()
    estilo_titulo = ParagraphStyle('TituloInforme', parent=estilos['Title'], textColor=colors.HexColor('#0F172A'), fontSize=24)
    estilo_subtitulo = ParagraphStyle('Subtitulo', parent=estilos['Normal'], textColor=colors.HexColor('#475569'), fontSize=11, spaceAfter=6)
    estilo_h2 = ParagraphStyle('H2Informe', parent=estilos['Heading2'], textColor=colors.HexColor('#0F766E'), spaceBefore=14, spaceAfter=6)
    estilo_cuerpo = ParagraphStyle('CuerpoInforme', parent=estilos['Normal'], fontSize=10.5, leading=15, textColor=colors.HexColor('#1E293B'))
    estilo_explicacion = ParagraphStyle('Explicacion', parent=estilos['Normal'], fontSize=9.5, leading=13, textColor=colors.HexColor('#64748B'), spaceAfter=8)

    story = []

    # --- Portada ---
    story.append(Spacer(1, 3*cm))
    story.append(Paragraph("Informe de Analisis de WhatsApp", estilo_titulo))
    story.append(Spacer(1, 0.4*cm))
    story.append(Paragraph(f"Generado el {datetime.datetime.now().strftime('%d/%m/%Y a las %H:%M')}", estilo_subtitulo))
    story.append(Paragraph(f"{stats['total_mensajes']:,} mensajes analizados - {stats['num_usuarios']} participantes - "
                            f"del {stats['fecha_inicio']} al {stats['fecha_fin']}", estilo_subtitulo))
    story.append(Spacer(1, 1*cm))
    story.append(HRFlowable(width="100%", color=colors.HexColor('#14B8A6'), thickness=1.2))
    story.append(Spacer(1, 1*cm))

    # --- Resumen generado por IA ---
    story.append(Paragraph("Resumen del grupo (generado con IA)", estilo_h2))
    resumen_limpio = limpiar_texto_pdf(resumen_ia).replace("\n", "<br/>")
    story.append(Paragraph(resumen_limpio, estilo_cuerpo))
    story.append(PageBreak())

    # --- Una sección por gráfica ---
    titulos = {
        "ranking": "Miembros mas activos",
        "horas": "Actividad por hora del dia",
        "heatmap": "Actividad por dia y hora",
        "matriz": "Matriz de afinidad cruzada",
        "evolucion": "Evolucion anual de mensajes",
        "tiempo": "Tiempo de respuesta medio",
        "fantasma": "Mensajes fantasma",
        "multimedia": "Multimedia enviado",
        "eliminados": "Mensajes eliminados",
        "longitud": "Longitud media de mensaje",
        "emojis": "Emojis mas usados",
        "palabras": "Palabras clave",
        "burbujas": "Mapa de conceptos",
    }

    for clave, imagen_bytes in imagenes.items():
        if not imagen_bytes:
            continue
        story.append(Paragraph(titulos.get(clave, clave.title()), estilo_h2))
        story.append(Paragraph(limpiar_texto_pdf(EXPLICACIONES_GRAFICAS.get(clave, "")), estilo_explicacion))
        try:
            img_buf = io.BytesIO(imagen_bytes)
            # Mantenemos proporción ~16:9 salvo el mapa de burbujas, que es cuadrado
            if clave == "burbujas":
                imagen_rl = RLImage(img_buf, width=12*cm, height=12*cm)
            else:
                imagen_rl = RLImage(img_buf, width=16*cm, height=8.7*cm)
            story.append(imagen_rl)
        except Exception as e:
            print(f"[PDF] No se pudo incrustar la imagen de '{clave}': {e}")
            story.append(Paragraph("(No se pudo incrustar esta grafica en el PDF)", estilo_explicacion))
        story.append(Spacer(1, 0.6*cm))

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()


@app.get("/", response_class=HTMLResponse)
async def inicio(request: Request):
    return templates.TemplateResponse(name="index.html", context={}, request=request)


@app.post("/analizar", response_class=HTMLResponse)
def analizar_chat(request: Request, file: UploadFile = File(...), custom_words: str = Form(None)):
    contenido = file.file.read()
    df = procesar_chat_whatsapp(contenido)

    if df.empty:
        return HTMLResponse("<h2 style='color:white; font-family:sans-serif; text-align:center; margin-top:50px;'>Error: El formato de tu archivo de chat no coincide con los patrones de lectura de WhatsApp.</h2>", status_code=400)

    # --- PROCESAMIENTO CRONOLÓGICO Y CÁLCULOS AVANZADOS ---
    df['Fecha_Completa'] = pd.to_datetime(df['Fecha'] + ' ' + df['Hora'], format='mixed', errors='coerce')
    df = df.dropna(subset=['Fecha_Completa']).sort_values('Fecha_Completa').reset_index(drop=True)
    df['Hora_Int'] = df['Fecha_Completa'].dt.hour
    df['Año'] = df['Fecha_Completa'].dt.year
    df['Dia_Semana_Num'] = df['Fecha_Completa'].dt.dayofweek  # 0 = Lunes
    df['Tiempo_Dif_Min'] = df['Fecha_Completa'].diff().dt.total_seconds() / 60.0
    df['Autor_Anterior'] = df['Autor'].shift(1)

    # Detección de mensajes multimedia / eliminados (se hace antes de limpiar el texto)
    df['Es_Multimedia'] = df['Mensaje'].astype(str).str.lower().apply(
        lambda t: any(frase in t for frase in FRASES_MULTIMEDIA)
    )
    df['Es_Eliminado'] = df['Mensaje'].astype(str).str.lower().apply(
        lambda t: any(frase in t for frase in FRASES_ELIMINADO)
    )

    total_mensajes_usuario = df['Autor'].value_counts()
    usuarios_top_15 = total_mensajes_usuario.head(15).index.tolist()

    # Convivencia y Tiempos de Respuesta
    es_respuesta_valida = (df['Tiempo_Dif_Min'] <= 120) & (df['Autor'] != df['Autor_Anterior'])
    tiempos_respuesta = df[es_respuesta_valida].groupby('Autor')['Tiempo_Dif_Min'].mean()
    df['Tiempo_Hasta_Siguiente_Min'] = df['Tiempo_Dif_Min'].shift(-1)
    es_mensaje_fantasma = (df['Tiempo_Hasta_Siguiente_Min'] > 180) | (df['Tiempo_Hasta_Siguiente_Min'].isna())
    fantasmas_usuario = df[es_mensaje_fantasma]['Autor'].value_counts()
    porcentaje_fantasmas = (fantasmas_usuario / total_mensajes_usuario * 100).fillna(0)

    # 1. Gráfica: Ranking de Miembros
    top_autores = total_mensajes_usuario.head(15).reset_index()
    top_autores.columns = ['Usuario', 'Mensajes']
    fig1 = px.bar(top_autores.sort_values('Mensajes'), x='Mensajes', y='Usuario', orientation='h', text='Mensajes', title='Miembros más activos', color='Mensajes', color_continuous_scale='tealgrn')
    fig1.update_traces(texttemplate='%{text:,}', textposition='outside', cliponaxis=False)
    fig1.update_layout(template='plotly_dark', paper_bgcolor='rgba(30,41,59,1)', plot_bgcolor='rgba(0,0,0,0)', coloraxis_showscale=False, margin=dict(t=50,b=20,l=140,r=80), xaxis=dict(visible=False), yaxis=dict(title=''))
    g1 = pio.to_html(fig1, full_html=False, include_plotlyjs=False, div_id='g-ranking', config={'displayModeBar': False})

    # 2. Gráfica: Actividad por Hora
    m_hora = df['Hora_Int'].value_counts().sort_index().reindex(range(0, 24), fill_value=0).reset_index()
    m_hora.columns = ['Hora', 'Mensajes']
    fig2 = px.line(m_hora, x='Hora', y='Mensajes', title='Actividad por hora del día', markers=True)
    fig2.update_traces(line=dict(color='#128C7E', width=3))
    fig2.update_layout(template='plotly_dark', paper_bgcolor='rgba(30,41,59,1)', plot_bgcolor='rgba(0,0,0,0)', margin=dict(t=50,b=20,l=20,r=20), xaxis=dict(title='', tickmode='linear', tick0=0, dtick=2), yaxis=dict(title=''))
    g2 = pio.to_html(fig2, full_html=False, include_plotlyjs=False, div_id='g-horas', config={'displayModeBar': False})

    # 3. Gráfica: Matriz de Afinidad Cruzada
    df_f_matriz = df[df['Autor'].isin(usuarios_top_15) & df['Autor_Anterior'].isin(usuarios_top_15)]
    df_conv_activa = df_f_matriz[(df_f_matriz['Tiempo_Dif_Min'] <= 15) & (df_f_matriz['Autor'] != df_f_matriz['Autor_Anterior'])]
    matriz_interaccion = pd.crosstab(df_conv_activa['Autor'], df_conv_activa['Autor_Anterior']).reindex(index=usuarios_top_15, columns=usuarios_top_15, fill_value=0)
    matriz_normalizada = matriz_interaccion.div(matriz_interaccion.sum(axis=1), axis=0).fillna(0) * 100
    matriz_valores = matriz_normalizada.values.astype(float)
    etiquetas_texto = np.round(matriz_valores, 1).astype(str)
    texto_celdas = np.where(np.eye(matriz_valores.shape[0], dtype=bool), "-", np.char.add(etiquetas_texto, "%"))

    fig3 = go.Figure(data=go.Heatmap(z=matriz_valores, x=matriz_normalizada.columns, y=matriz_normalizada.index, colorscale='GnBu', text=texto_celdas, texttemplate="%{text}", hoverinfo="text"))
    fig3.update_layout(title='Matriz de Afinidad Cruzada (% de respuestas por fila)', template='plotly_dark', paper_bgcolor='rgba(30,41,59,1)', plot_bgcolor='rgba(0,0,0,0)', height=650, margin=dict(t=60, b=120, l=140, r=20), yaxis=dict(autorange="reversed"))
    fig3.update_xaxes(tickangle=-45)
    g3 = pio.to_html(fig3, full_html=False, include_plotlyjs=False, div_id='g-matriz', config={'displayModeBar': False})

    # 4. Gráfica: Evolución Anual
    m_tiempo = df['Año'].value_counts().sort_index().reset_index()
    m_tiempo.columns = ['Año', 'Mensajes']
    m_tiempo['Año'] = m_tiempo['Año'].astype(str)
    fig4 = px.bar(m_tiempo, x='Año', y='Mensajes', text='Mensajes', title='Mensajes enviados por año')
    fig4.update_traces(marker_color='#128C7E', texttemplate='%{text:,}', textposition='outside', cliponaxis=False)
    fig4.update_layout(template='plotly_dark', paper_bgcolor='rgba(30,41,59,1)', plot_bgcolor='rgba(0,0,0,0)', margin=dict(t=50,b=20,l=20,r=20), xaxis=dict(title=''), yaxis=dict(visible=False))
    g4 = pio.to_html(fig4, full_html=False, include_plotlyjs=False, div_id='g-evolucion', config={'displayModeBar': False})

    # =========================================================================
    # 5. 🌟 CREACIÓN SÓLIDA DEL DATAFRAME DE CONVIVENCIA (PARA EVITAR WARNINGS)
    # =========================================================================
    df_convivencia = pd.DataFrame({
        'Tiempo Respuesta (min)': [tiempos_respuesta.get(u, 0) for u in usuarios_top_15],
        'Mensajes Fantasma (%)': [porcentaje_fantasmas.get(u, 0) for u in usuarios_top_15]
    }, index=usuarios_top_15).reset_index().rename(columns={'index': 'Usuario'})

    def formatear_min_seg(valor_minutos):
        if valor_minutos <= 0:
            return "0s"
        minutos_enteros = int(valor_minutos)
        segundos_restantes = int(round((valor_minutos - minutos_enteros) * 60))
        if segundos_restantes == 60:
            minutos_enteros += 1
            segundos_restantes = 0
        if minutos_enteros > 0:
            return f"{minutos_enteros} min {segundos_restantes}s"
        return f"{segundos_restantes}s"

    # 5A. Tiempos de Respuesta
    df_tiempo = df_convivencia.sort_values(by='Tiempo Respuesta (min)', ascending=False)
    df_tiempo['Texto_Formateado'] = df_tiempo['Tiempo Respuesta (min)'].apply(formatear_min_seg)

    fig5_tiempo = px.bar(df_tiempo, x='Tiempo Respuesta (min)', y='Usuario', orientation='h', title='⏱️ Tiempo de Respuesta Medio por Miembro', color='Tiempo Respuesta (min)', color_continuous_scale='tealgrn', text='Texto_Formateado')
    fig5_tiempo.update_traces(textposition='outside', cliponaxis=False)
    fig5_tiempo.update_layout(template='plotly_dark', paper_bgcolor='rgba(30,41,59,1)', plot_bgcolor='rgba(0,0,0,0)', coloraxis_showscale=False, height=550, margin=dict(t=50, b=40, l=140, r=80), xaxis=dict(visible=False), yaxis=dict(title=''))
    g5_tiempo = pio.to_html(fig5_tiempo, full_html=False, include_plotlyjs=False, div_id='g-tiempo', config={'displayModeBar': False})

    # 5B. Mensajes Fantasma
    df_fantasma = df_convivencia.sort_values(by='Mensajes Fantasma (%)', ascending=False)
    df_fantasma['Texto_Porcentaje'] = df_fantasma['Mensajes Fantasma (%)'].apply(lambda x: f"{x:.1f}%")

    fig5_fantasma = px.bar(df_fantasma, x='Mensajes Fantasma (%)', y='Usuario', orientation='h', text='Texto_Porcentaje', title='👻 Fantasmas del Grupo: Porcentaje de Vistos', color='Mensajes Fantasma (%)', color_continuous_scale='rdpu')
    fig5_fantasma.update_traces(textposition='outside', cliponaxis=False)
    fig5_fantasma.update_layout(template='plotly_dark', paper_bgcolor='rgba(30,41,59,1)', plot_bgcolor='rgba(0,0,0,0)', coloraxis_showscale=False, height=550, margin=dict(t=50, b=40, l=140, r=70), xaxis=dict(visible=False), yaxis=dict(title=''))
    g5_fantasma = pio.to_html(fig5_fantasma, full_html=False, include_plotlyjs=False, div_id='g-fantasma', config={'displayModeBar': False})

    # --- Gráfica de Palabras Clave Personalizadas ---
    if custom_words and custom_words.strip():
        palabras_a_rankear = [w.strip() for w in custom_words.split(',') if w.strip()]
    else:
        palabras_a_rankear = [
            "lol", "literal", "tfg", "examen", "fiesta", "salimos", "kebab",
            "cerveza", "gym", "futbol", "sleep", "tarde", "broma", "madre",
            "tio", "viaje", "netflix", "curro", "estudiar", "dinero"
        ]

    df['Mensaje_Minus'] = df['Mensaje'].astype(str).str.lower()

    registros_conceptos = []
    for palabra in palabras_a_rankear:
        palabra_buscar = palabra.strip().lower()
        patron_palabra = rf'\b{re.escape(palabra_buscar)}\b'
        total_veces = df['Mensaje_Minus'].apply(lambda x: len(re.findall(patron_palabra, x))).sum()

        conteo_por_autor = {}
        for autor, sub_df in df.groupby('Autor'):
            veces_autor = sub_df['Mensaje_Minus'].apply(lambda x: len(re.findall(patron_palabra, x))).sum()
            if veces_autor > 0:
                conteo_por_autor[autor] = veces_autor

        autores_ordenados = sorted(conteo_por_autor.items(), key=lambda x: x[1], reverse=True)[:5]
        info_hover = "<br>".join([f"👤 {autor}: {cant} veces" for autor, cant in autores_ordenados])
        if not info_hover:
            info_hover = "Nadie la ha mencionado"

        registros_conceptos.append({'Concepto': palabra, 'Frecuencia': total_veces, 'Detalle_Autores': info_hover})

    df_conceptos = pd.DataFrame(registros_conceptos).sort_values('Frecuencia', ascending=True)

    fig_palabras = px.bar(df_conceptos, x='Frecuencia', y='Concepto', orientation='h', text='Frecuencia', title='Frecuencia de palabras clave personalizadas', color='Frecuencia', color_continuous_scale='tealgrn', custom_data=['Detalle_Autores'])
    fig_palabras.update_traces(texttemplate='%{text:,}', textposition='outside', cliponaxis=False, hovertemplate="<b>Palabra:</b> %{y}<br><b>Total en grupo:</b> %{x} veces<br><br><b>Desglose de uso:</b><br>%{customdata[0]}<extra></extra>")
    fig_palabras.update_layout(template='plotly_dark', paper_bgcolor='rgba(30,41,59,1)', plot_bgcolor='rgba(0,0,0,0)', coloraxis_showscale=False, margin=dict(t=50,b=20,l=100,r=70), xaxis=dict(visible=False), yaxis=dict(title=''))
    g_palabras = pio.to_html(fig_palabras, full_html=False, include_plotlyjs=False, div_id='g-palabras', config={'displayModeBar': False})

    # 6. Gráfica: Bubble Chart
    # Excluimos mensajes multimedia/eliminados para que no contaminen el mapa de conceptos
    df_solo_texto = df[~(df['Es_Multimedia'] | df['Es_Eliminado'])]
    todo_el_texto = " ".join(df_solo_texto['Mensaje'].astype(str)).lower()
    all_words = re.findall(r'\b[a-záéíóúñ]+\b', todo_el_texto)

    stopwords_refinadas = {
        'que', 'un', 'una', 'unos', 'unas', 'el', 'la', 'los', 'las', 'y', 'o', 'u', 'e',
        'de', 'del', 'al', 'en', 'para', 'por', 'con', 'sin', 'sobre', 'tras', 'a', 'ante',
        'mi', 'tu', 'su', 'mis', 'tus', 'sus', 'me', 'te', 'se', 'nos', 'os', 'lo', 'le',
        'les', 'es', 'son', 'fue', 'era', 'ser', 'está', 'están', 'esto', 'eso', 'dijo',
        'aquello', 'este', 'esta', 'estos', 'estas', 'esos', 'esas', 'un', 'bien', 'si',
        'no', 'sí', 'pero', 'mas', 'más', 'ya', 'como', 'cómo', 'alguien', 'nadie', 'algo',
        'nada', 'todo', 'todos', 'toda', 'todas', 'porque', 'por qué', 'así', 'entonces',
        'multimedia', 'omitido', 'archivo', 'adjunto', 'mensaje', 'eliminado', 'sticker',
        'https', 'http', 'com', 'es', 'www', 'html', 'net', 'org', 'link', 'status', 'x', 'twitter'
    }

    palabras_limpias = [p for p in all_words if p not in stopwords_refinadas and len(p) > 2]
    top_100_palabras = pd.Series(palabras_limpias).value_counts().reset_index().head(100)
    top_100_palabras.columns = ['Palabra', 'Frecuencia']

    g6_base64 = ""
    if not top_100_palabras.empty:
        radii_base = np.sqrt(top_100_palabras['Frecuencia'].values)
        escala_visual = 25.0 / radii_base.max()
        radii_visuales = radii_base * escala_visual
        coordenadas = empaquetar_circulos(radii_visuales)

        plt.style.use('dark_background')
        fig_mpl, ax_mpl = plt.subplots(figsize=(11, 11))
        fig_mpl.patch.set_facecolor('#1E293B')
        ax_mpl.set_facecolor('#1E293B')

        colores = sns.color_palette("YlGnBu_r", n_colors=len(top_100_palabras))
        from matplotlib import patheffects

        for idx in range(len(top_100_palabras)):
            fila = top_100_palabras.iloc[idx]
            x_c, y_c = coordenadas[idx]
            r_v = radii_visuales[idx]
            color_burbuja = colores[idx]

            circulo = plt.Circle((x_c, y_c), r_v, color=color_burbuja, alpha=0.9, ec='#0F172A', lw=1)
            ax_mpl.add_patch(circulo)

            if r_v > 1.4:
                tam_fuente = int(r_v * 1.6)
                tam_fuente = min(11, max(6, tam_fuente))
                texto_nodo = f"{fila['Palabra']}\n{fila['Frecuencia']}"
                brillo = (0.299 * color_burbuja[0] + 0.587 * color_burbuja[1] + 0.114 * color_burbuja[2])
                color_texto = 'black' if brillo > 0.55 else 'white'
                color_halo = 'white' if color_texto == 'black' else '#1E293B'
                halo = [patheffects.withStroke(linewidth=2, foreground=color_halo, alpha=0.8)]
                ax_mpl.text(x_c, y_c, texto_nodo, ha='center', va='center', color=color_texto, fontsize=tam_fuente, weight='bold', path_effects=halo)

        ax_mpl.axis('off')
        lim = coordenadas[:, 0].min() - radii_visuales.max() * 1.2, coordenadas[:, 0].max() + radii_visuales.max() * 1.2
        ax_mpl.set_xlim(lim[0], lim[1])
        ax_mpl.set_ylim(coordenadas[:, 1].min() - radii_visuales.max() * 1.2, coordenadas[:, 1].max() + radii_visuales.max() * 1.2)
        plt.tight_layout()

        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=140, facecolor='#1E293B', edgecolor='none')
        buf.seek(0)
        g6_base64 = base64.b64encode(buf.getvalue()).decode('utf-8')
        plt.close(fig_mpl)

    # =========================================================================
    # 7. 🗓️ NUEVO: Heatmap de actividad Día de la Semana × Hora
    # =========================================================================
    tabla_heatmap = (
        df.groupby(['Dia_Semana_Num', 'Hora_Int']).size()
        .unstack(fill_value=0)
        .reindex(index=range(7), columns=range(24), fill_value=0)
    )
    tabla_heatmap.index = DIAS_SEMANA_ES

    fig7 = go.Figure(data=go.Heatmap(
        z=tabla_heatmap.values,
        x=list(range(24)),
        y=DIAS_SEMANA_ES,
        colorscale='GnBu',
        hovertemplate='<b>%{y}</b><br>Hora: %{x}h<br>Mensajes: %{z}<extra></extra>'
    ))
    fig7.update_layout(
        title='🗓️ Mapa de Calor: Actividad por Día y Hora',
        template='plotly_dark', paper_bgcolor='rgba(30,41,59,1)', plot_bgcolor='rgba(0,0,0,0)',
        height=450, margin=dict(t=50, b=40, l=90, r=20),
        xaxis=dict(title='Hora del día', tickmode='linear', tick0=0, dtick=2),
        yaxis=dict(title='', autorange='reversed')
    )
    g7 = pio.to_html(fig7, full_html=False, include_plotlyjs=False, div_id='g-heatmap-semana', config={'displayModeBar': False})

    # =========================================================================
    # 8. 📎 NUEVO: Mensajes Multimedia / Eliminados por usuario
    # =========================================================================
    total_multimedia = int(df['Es_Multimedia'].sum())
    total_eliminados = int(df['Es_Eliminado'].sum())

    multimedia_por_usuario = df[df['Es_Multimedia']]['Autor'].value_counts().reindex(usuarios_top_15, fill_value=0)
    df_multimedia = multimedia_por_usuario.reset_index()
    df_multimedia.columns = ['Usuario', 'Cantidad']
    df_multimedia = df_multimedia.sort_values('Cantidad', ascending=True)

    fig8 = px.bar(df_multimedia, x='Cantidad', y='Usuario', orientation='h', text='Cantidad', title='📎 Multimedia Enviado por Miembro', color='Cantidad', color_continuous_scale='purpor')
    fig8.update_traces(texttemplate='%{text:,}', textposition='outside', cliponaxis=False)
    fig8.update_layout(template='plotly_dark', paper_bgcolor='rgba(30,41,59,1)', plot_bgcolor='rgba(0,0,0,0)', coloraxis_showscale=False, height=550, margin=dict(t=50,b=20,l=140,r=70), xaxis=dict(visible=False), yaxis=dict(title=''))
    g8 = pio.to_html(fig8, full_html=False, include_plotlyjs=False, div_id='g-multimedia', config={'displayModeBar': False})

    # 8B. Mensajes Eliminados por usuario
    eliminados_por_usuario = df[df['Es_Eliminado']]['Autor'].value_counts().reindex(usuarios_top_15, fill_value=0)
    df_eliminados = eliminados_por_usuario.reset_index()
    df_eliminados.columns = ['Usuario', 'Cantidad']
    df_eliminados = df_eliminados.sort_values('Cantidad', ascending=True)

    fig8b = px.bar(df_eliminados, x='Cantidad', y='Usuario', orientation='h', text='Cantidad', title='🗑️ Mensajes Eliminados por Miembro', color='Cantidad', color_continuous_scale='burg')
    fig8b.update_traces(texttemplate='%{text:,}', textposition='outside', cliponaxis=False)
    fig8b.update_layout(template='plotly_dark', paper_bgcolor='rgba(30,41,59,1)', plot_bgcolor='rgba(0,0,0,0)', coloraxis_showscale=False, height=550, margin=dict(t=50,b=20,l=140,r=70), xaxis=dict(visible=False), yaxis=dict(title=''))
    g8b = pio.to_html(fig8b, full_html=False, include_plotlyjs=False, div_id='g-eliminados', config={'displayModeBar': False})

    # =========================================================================
    # 9. ✍️ NUEVO: Longitud media de mensaje por usuario (solo texto real)
    # =========================================================================
    df_solo_texto = df_solo_texto.copy()
    df_solo_texto['Longitud'] = df_solo_texto['Mensaje'].astype(str).str.len()
    longitud_media_usuario = df_solo_texto.groupby('Autor')['Longitud'].mean().reindex(usuarios_top_15, fill_value=0)
    df_longitud = longitud_media_usuario.round(1).reset_index()
    df_longitud.columns = ['Usuario', 'Caracteres']
    df_longitud = df_longitud.sort_values('Caracteres', ascending=True)

    fig9 = px.bar(df_longitud, x='Caracteres', y='Usuario', orientation='h', text='Caracteres', title='✍️ Longitud Media de Mensaje por Miembro (caracteres)', color='Caracteres', color_continuous_scale='tealgrn')
    fig9.update_traces(textposition='outside', cliponaxis=False)
    fig9.update_layout(template='plotly_dark', paper_bgcolor='rgba(30,41,59,1)', plot_bgcolor='rgba(0,0,0,0)', coloraxis_showscale=False, height=550, margin=dict(t=50,b=20,l=140,r=70), xaxis=dict(visible=False), yaxis=dict(title=''))
    g9 = pio.to_html(fig9, full_html=False, include_plotlyjs=False, div_id='g-longitud', config={'displayModeBar': False})

    # =========================================================================
    # 10. 😂 NUEVO: Ranking de Emojis más usados
    # =========================================================================
    todos_los_emojis = []
    for msg in df_solo_texto['Mensaje'].astype(str):
        todos_los_emojis.extend(PATRON_EMOJI.findall(msg))

    g10 = None
    if todos_los_emojis:
        conteo_emojis = Counter(todos_los_emojis).most_common(15)
        df_emojis = pd.DataFrame(conteo_emojis, columns=['Emoji', 'Frecuencia']).sort_values('Frecuencia', ascending=True)

        fig10 = px.bar(df_emojis, x='Frecuencia', y='Emoji', orientation='h', text='Frecuencia', title='😂 Emojis Más Usados en el Grupo', color='Frecuencia', color_continuous_scale='sunsetdark')
        fig10.update_traces(texttemplate='%{text:,}', textposition='outside', cliponaxis=False)
        fig10.update_layout(template='plotly_dark', paper_bgcolor='rgba(30,41,59,1)', plot_bgcolor='rgba(0,0,0,0)', coloraxis_showscale=False, height=550, margin=dict(t=50,b=20,l=70,r=70), xaxis=dict(visible=False), yaxis=dict(title='', tickfont=dict(size=26)))
        g10 = pio.to_html(fig10, full_html=False, include_plotlyjs=False, div_id='g-emojis', config={'displayModeBar': False})

    ranking_tabla = [{"usuario": u, "cantidad": m} for u, m in total_mensajes_usuario.items()]

    # =========================================================================
    # 11. 🎉 Curiosidades específicas del grupo (para un resumen de IA más rico)
    #     Todo se calcula a partir de agregados; nunca se envía el texto de los
    #     mensajes al modelo, salvo la LONGITUD del más largo (no su contenido).
    # =========================================================================
    # Emoji estrella y quién lo usa más
    emoji_estrella, usuario_emoji_estrella, cantidad_emoji_estrella = None, None, 0
    if todos_los_emojis:
        emoji_estrella = Counter(todos_los_emojis).most_common(1)[0][0]
        conteo_emoji_por_autor = {
            autor: " ".join(sub_df['Mensaje'].astype(str)).count(emoji_estrella)
            for autor, sub_df in df_solo_texto.groupby('Autor')
        }
        if conteo_emoji_por_autor:
            usuario_emoji_estrella, cantidad_emoji_estrella = max(conteo_emoji_por_autor.items(), key=lambda x: x[1])

    # Búho nocturno (00h-5h) y madrugador (6h-9h) entre los miembros más activos
    df_top15_msgs = df[df['Autor'].isin(usuarios_top_15)]
    total_por_autor_top15 = df_top15_msgs.groupby('Autor').size()
    pct_nocturno = (df_top15_msgs[df_top15_msgs['Hora_Int'].between(0, 5)].groupby('Autor').size() / total_por_autor_top15 * 100).dropna()
    usuario_nocturno = pct_nocturno.idxmax() if not pct_nocturno.empty else None
    pct_nocturno_valor = pct_nocturno.max() if not pct_nocturno.empty else 0
    pct_madrugador = (df_top15_msgs[df_top15_msgs['Hora_Int'].between(6, 9)].groupby('Autor').size() / total_por_autor_top15 * 100).dropna()
    usuario_madrugador = pct_madrugador.idxmax() if not pct_madrugador.empty else None
    pct_madrugador_valor = pct_madrugador.max() if not pct_madrugador.empty else 0

    # Mensaje más largo (solo se usa su longitud y autor, nunca su contenido)
    autor_mensaje_largo, longitud_mensaje_largo = None, 0
    if not df_solo_texto.empty:
        longitudes = df_solo_texto['Mensaje'].astype(str).str.len()
        idx_largo = longitudes.idxmax()
        autor_mensaje_largo = df_solo_texto.loc[idx_largo, 'Autor']
        longitud_mensaje_largo = int(longitudes.loc[idx_largo])

    # Día más activo de toda la historia del grupo
    conteo_por_dia = df['Fecha_Completa'].dt.date.value_counts()
    dia_mas_activo = conteo_por_dia.idxmax().strftime('%d/%m/%Y') if not conteo_por_dia.empty else None
    mensajes_dia_mas_activo = int(conteo_por_dia.max()) if not conteo_por_dia.empty else 0

    # Racha más larga de días consecutivos con actividad
    dias_unicos = sorted(df['Fecha_Completa'].dt.date.unique())
    racha_actual = racha_maxima = 1 if dias_unicos else 0
    for i in range(1, len(dias_unicos)):
        if (dias_unicos[i] - dias_unicos[i - 1]).days == 1:
            racha_actual += 1
            racha_maxima = max(racha_maxima, racha_actual)
        else:
            racha_actual = 1

    # Palabra clave estrella (la más repetida) y quién la dice más
    palabra_estrella, usuario_palabra_estrella = None, None
    if not df_conceptos.empty:
        fila_estrella = df_conceptos.sort_values('Frecuencia', ascending=False).iloc[0]
        if fila_estrella['Frecuencia'] > 0:
            palabra_estrella = fila_estrella['Concepto']
            detalle = fila_estrella['Detalle_Autores']
            if detalle and detalle != "Nadie la ha mencionado":
                usuario_palabra_estrella = detalle.split('<br>')[0].replace('👤 ', '').split(':')[0].strip()

    # Miembro más rápido y más lento respondiendo (entre quienes tienen dato)
    respondedor_rapido = tiempos_respuesta.idxmin() if not tiempos_respuesta.empty else None
    tiempo_respondedor_rapido = tiempos_respuesta.min() if not tiempos_respuesta.empty else 0

    # =========================================================================
    # 11B. 👥 Perfil individual de CADA integrante (para que el resumen de IA
    #      pueda nombrar a todo el mundo y no solo a los "personajes" destacados)
    # =========================================================================
    LIMITE_INTEGRANTES_PROMPT = 40  # evita prompts kilométricos en grupos enormes

    hora_favorita_por_usuario = df.groupby('Autor')['Hora_Int'].agg(lambda h: h.value_counts().idxmax())
    longitud_media_por_usuario = df_solo_texto.groupby('Autor')['Mensaje'].apply(lambda s: s.astype(str).str.len().mean())

    emoji_favorito_por_usuario = {}
    for autor, sub_df in df_solo_texto.groupby('Autor'):
        emojis_autor = PATRON_EMOJI.findall(" ".join(sub_df['Mensaje'].astype(str)))
        if emojis_autor:
            emoji_favorito_por_usuario[autor] = Counter(emojis_autor).most_common(1)[0][0]

    todos_los_usuarios_por_actividad = total_mensajes_usuario.index.tolist()  # ya viene ordenado desc
    usuarios_para_prompt = todos_los_usuarios_por_actividad[:LIMITE_INTEGRANTES_PROMPT]
    integrantes_omitidos = max(0, len(todos_los_usuarios_por_actividad) - LIMITE_INTEGRANTES_PROMPT)

    perfiles_integrantes = []
    for autor in usuarios_para_prompt:
        perfiles_integrantes.append({
            "usuario": autor,
            "mensajes": int(total_mensajes_usuario.get(autor, 0)),
            "hora_favorita": int(hora_favorita_por_usuario.get(autor)) if autor in hora_favorita_por_usuario.index else None,
            "longitud_media": round(float(longitud_media_por_usuario.get(autor, 0)), 1) if autor in longitud_media_por_usuario.index and pd.notna(longitud_media_por_usuario.get(autor)) else 0,
            "emoji_favorito": emoji_favorito_por_usuario.get(autor, "ninguno"),
        })

    # =========================================================================
    # 12. 📄 Informe PDF descargable (gráficas + explicaciones + resumen IA)
    # =========================================================================
    stats_para_ia = {
        "total_mensajes": len(df),
        "fecha_inicio": df['Fecha_Completa'].min().strftime('%d/%m/%Y'),
        "fecha_fin": df['Fecha_Completa'].max().strftime('%d/%m/%Y'),
        "num_usuarios": df['Autor'].nunique(),
        "top5_usuarios": total_mensajes_usuario.head(5).to_dict(),
        "hora_pico": int(m_hora.loc[m_hora['Mensajes'].idxmax(), 'Hora']),
        "dia_pico": tabla_heatmap.sum(axis=1).idxmax(),
        "pct_multimedia": (total_multimedia / len(df) * 100) if len(df) else 0,
        "pct_eliminados": (total_eliminados / len(df) * 100) if len(df) else 0,
        "top_fantasma": df_fantasma.iloc[0]['Usuario'] if not df_fantasma.empty else "N/A",
        "top_emojis": [e for e, _ in Counter(todos_los_emojis).most_common(8)] if todos_los_emojis else [],
        "top_palabras": df_conceptos.sort_values('Frecuencia', ascending=False).head(8)['Concepto'].tolist(),
        # --- Curiosidades específicas para un resumen más divertido y concreto ---
        "dia_mas_activo": dia_mas_activo or "sin datos suficientes",
        "mensajes_dia_mas_activo": mensajes_dia_mas_activo,
        "racha_maxima": racha_maxima,
        "emoji_estrella": emoji_estrella or "ninguno destacado",
        "usuario_emoji_estrella": usuario_emoji_estrella or "nadie en particular",
        "cantidad_emoji_estrella": cantidad_emoji_estrella,
        "usuario_nocturno": usuario_nocturno or "nadie destacado",
        "pct_nocturno_valor": pct_nocturno_valor,
        "usuario_madrugador": usuario_madrugador or "nadie destacado",
        "pct_madrugador_valor": pct_madrugador_valor,
        "autor_mensaje_largo": autor_mensaje_largo or "alguien anónimo",
        "longitud_mensaje_largo": longitud_mensaje_largo,
        "palabra_estrella": palabra_estrella or "ninguna en particular",
        "usuario_palabra_estrella": usuario_palabra_estrella or "nadie en concreto",
        "respondedor_rapido": respondedor_rapido or "N/A",
        "tiempo_respondedor_rapido": tiempo_respondedor_rapido,
        # --- Perfil de cada integrante, para que nadie se quede sin mención ---
        "perfiles_integrantes": perfiles_integrantes,
        "integrantes_omitidos": integrantes_omitidos,
    }

    # El PDF (Gemini + imágenes matplotlib + reportlab) es lo más lento de generar,
    # así que no lo construimos aquí: guardamos solo los agregados pequeños que
    # necesita y lo generamos bajo demanda en /generar_pdf/{token} cuando el
    # usuario pulsa el botón de descarga.
    datos_pdf = {
        "stats_para_ia": stats_para_ia,
        "top_autores": top_autores,
        "m_hora": m_hora,
        "tabla_heatmap": tabla_heatmap,
        "matriz_normalizada": matriz_normalizada,
        "m_tiempo": m_tiempo,
        "df_tiempo": df_tiempo,
        "df_fantasma": df_fantasma,
        "df_multimedia": df_multimedia,
        "df_eliminados": df_eliminados,
        "df_longitud": df_longitud,
        "df_conceptos": df_conceptos,
        "df_emojis": df_emojis if todos_los_emojis else None,
        "g6_base64": g6_base64,
    }
    pdf_token = _guardar_datos_pdf_en_cache(datos_pdf)

    return templates.TemplateResponse(
        name="resultados.html",
        context={
            "total_mensajes": len(df),
            "total_multimedia": total_multimedia,
            "total_eliminados": total_eliminados,
            "ranking": ranking_tabla,
            "g1": g1, "g2": g2, "g3": g3, "g4": g4,
            "g5_tiempo": g5_tiempo,
            "g5_fantasma": g5_fantasma,
            "g_palabras": g_palabras,
            "g6": g6_base64,
            "g7": g7,
            "g8": g8,
            "g8b": g8b,
            "g9": g9,
            "g10": g10,
            "pdf_token": pdf_token,
        },
        request=request
    )


@app.get("/generar_pdf/{token}")
def generar_pdf(token: str):
    """Genera el informe PDF bajo demanda a partir de los datos guardados en
    caché durante el /analizar correspondiente. Aquí es donde ocurre lo más
    lento: la llamada a Gemini y el renderizado de las imágenes con matplotlib."""
    datos_pdf = CACHE_DATOS_PDF.get(token)
    if datos_pdf is None:
        return HTMLResponse(
            "<h2 style='color:white; font-family:sans-serif; text-align:center; margin-top:50px;'>"
            "Este informe ya no está disponible (puede haber caducado si el servidor estuvo "
            "inactivo un rato). Vuelve a analizar tu chat para generar un PDF nuevo.</h2>",
            status_code=404,
        )

    stats_para_ia = datos_pdf["stats_para_ia"]
    top_autores = datos_pdf["top_autores"]
    m_hora = datos_pdf["m_hora"]
    tabla_heatmap = datos_pdf["tabla_heatmap"]
    matriz_normalizada = datos_pdf["matriz_normalizada"]
    m_tiempo = datos_pdf["m_tiempo"]
    df_tiempo = datos_pdf["df_tiempo"]
    df_fantasma = datos_pdf["df_fantasma"]
    df_multimedia = datos_pdf["df_multimedia"]
    df_eliminados = datos_pdf["df_eliminados"]
    df_longitud = datos_pdf["df_longitud"]
    df_conceptos = datos_pdf["df_conceptos"]
    df_emojis = datos_pdf["df_emojis"]
    g6_base64 = datos_pdf["g6_base64"]

    resumen_ia = generar_resumen_ia(stats_para_ia)

    # =========================================================================
    # Generamos las imágenes del PDF con matplotlib (sin navegador, sin Kaleido).
    # Reutilizamos los mismos dataframes que ya alimentan las gráficas
    # interactivas de Plotly, así que los números son idénticos en ambos sitios.
    # =========================================================================
    imagenes_pdf = {}

    try:
        top_autores_asc = top_autores.sort_values('Mensajes')
        imagenes_pdf["ranking"] = grafico_barh_mpl(
            top_autores_asc['Usuario'], top_autores_asc['Mensajes'],
            "Miembros mas activos", cmap='YlGn'
        )
    except Exception as e:
        print(f"[PDF] No se pudo generar la gráfica 'ranking': {e}")
        imagenes_pdf["ranking"] = None

    try:
        imagenes_pdf["horas"] = grafico_linea_mpl(
            m_hora['Hora'], m_hora['Mensajes'], "Actividad por hora del dia"
        )
    except Exception as e:
        print(f"[PDF] No se pudo generar la gráfica 'horas': {e}")
        imagenes_pdf["horas"] = None

    try:
        imagenes_pdf["heatmap"] = grafico_heatmap_mpl(
            tabla_heatmap.values, list(range(24)), DIAS_SEMANA_ES,
            "Actividad por dia y hora", cmap='YlGnBu'
        )
    except Exception as e:
        print(f"[PDF] No se pudo generar la gráfica 'heatmap': {e}")
        imagenes_pdf["heatmap"] = None

    try:
        imagenes_pdf["matriz"] = grafico_heatmap_mpl(
            matriz_normalizada.values, matriz_normalizada.columns, matriz_normalizada.index,
            "Matriz de afinidad cruzada (% de respuestas por fila)", cmap='GnBu',
            figsize=(10, 8), anotar=True, fmt=".0f"
        )
    except Exception as e:
        print(f"[PDF] No se pudo generar la gráfica 'matriz': {e}")
        imagenes_pdf["matriz"] = None

    try:
        imagenes_pdf["evolucion"] = grafico_barv_mpl(
            m_tiempo['Año'], m_tiempo['Mensajes'], "Mensajes enviados por año"
        )
    except Exception as e:
        print(f"[PDF] No se pudo generar la gráfica 'evolucion': {e}")
        imagenes_pdf["evolucion"] = None

    try:
        df_tiempo_asc = df_tiempo.sort_values('Tiempo Respuesta (min)')
        imagenes_pdf["tiempo"] = grafico_barh_mpl(
            df_tiempo_asc['Usuario'], df_tiempo_asc['Tiempo Respuesta (min)'],
            "Tiempo de respuesta medio por miembro (min)", cmap='YlGn', fmt='{:,.1f}'
        )
    except Exception as e:
        print(f"[PDF] No se pudo generar la gráfica 'tiempo': {e}")
        imagenes_pdf["tiempo"] = None

    try:
        df_fantasma_asc = df_fantasma.sort_values('Mensajes Fantasma (%)')
        imagenes_pdf["fantasma"] = grafico_barh_mpl(
            df_fantasma_asc['Usuario'], df_fantasma_asc['Mensajes Fantasma (%)'],
            "Mensajes fantasma (%)", cmap='RdPu', fmt='{:,.1f}%'
        )
    except Exception as e:
        print(f"[PDF] No se pudo generar la gráfica 'fantasma': {e}")
        imagenes_pdf["fantasma"] = None

    try:
        imagenes_pdf["multimedia"] = grafico_barh_mpl(
            df_multimedia['Usuario'], df_multimedia['Cantidad'],
            "Multimedia enviado por miembro", cmap='PuRd'
        )
    except Exception as e:
        print(f"[PDF] No se pudo generar la gráfica 'multimedia': {e}")
        imagenes_pdf["multimedia"] = None

    try:
        imagenes_pdf["eliminados"] = grafico_barh_mpl(
            df_eliminados['Usuario'], df_eliminados['Cantidad'],
            "Mensajes eliminados por miembro", cmap='OrRd'
        )
    except Exception as e:
        print(f"[PDF] No se pudo generar la gráfica 'eliminados': {e}")
        imagenes_pdf["eliminados"] = None

    try:
        imagenes_pdf["longitud"] = grafico_barh_mpl(
            df_longitud['Usuario'], df_longitud['Caracteres'],
            "Longitud media de mensaje (caracteres)", cmap='YlGn', fmt='{:,.0f}'
        )
    except Exception as e:
        print(f"[PDF] No se pudo generar la gráfica 'longitud': {e}")
        imagenes_pdf["longitud"] = None

    if df_emojis is not None:
        try:
            # Nota: las fuentes estándar de matplotlib no siempre saben dibujar
            # emoji en color, así que aquí los mostramos numerados; el emoji
            # real siempre se puede ver en el panel interactivo de la web.
            df_emojis_asc = df_emojis.reset_index(drop=True)
            etiquetas_emoji = [f"#{i + 1}" for i in range(len(df_emojis_asc))]
            imagenes_pdf["emojis"] = grafico_barh_mpl(
                etiquetas_emoji, df_emojis_asc['Frecuencia'],
                "Emojis mas usados (ranking, ver la web para verlos)", cmap='RdPu'
            )
        except Exception as e:
            print(f"[PDF] No se pudo generar la gráfica 'emojis': {e}")
            imagenes_pdf["emojis"] = None

    try:
        imagenes_pdf["palabras"] = grafico_barh_mpl(
            df_conceptos['Concepto'], df_conceptos['Frecuencia'],
            "Frecuencia de palabras clave", cmap='YlGn'
        )
    except Exception as e:
        print(f"[PDF] No se pudo generar la gráfica 'palabras': {e}")
        imagenes_pdf["palabras"] = None

    if g6_base64:
        imagenes_pdf["burbujas"] = base64.b64decode(g6_base64)

    try:
        pdf_bytes = generar_informe_pdf(stats_para_ia, resumen_ia, imagenes_pdf)
    except Exception as e:
        print(f"[PDF] Error generando el informe PDF: {e}")
        return HTMLResponse(
            "<h2 style='color:white; font-family:sans-serif; text-align:center; margin-top:50px;'>"
            "Hubo un error generando el informe PDF. Inténtalo de nuevo en unos segundos.</h2>",
            status_code=500,
        )

    # Un solo uso: liberamos la memoria en cuanto se ha generado el PDF
    CACHE_DATOS_PDF.pop(token, None)

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=Informe_Analisis_WhatsApp.pdf"},
    )