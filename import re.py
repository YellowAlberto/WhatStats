import re
import os
import io
import base64
import datetime
from collections import Counter
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg') # Evita bloqueos en servidores web
import matplotlib.pyplot as plt
import seaborn as sns

# --- Carga automática del archivo .env ---
from dotenv import load_dotenv
load_dotenv()

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
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

app = FastAPI(title="Analizador de WhatsApp Completo")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

os.makedirs("static", exist_ok=True)

# --- Patrones auxiliares reutilizados en varias partes del análisis ---
FRASES_MULTIMEDIA = [
    'multimedia omitido', 'imagen omitida', 'video omitido', 'audio omitido',
    'sticker omitido', 'gif omitido', 'documento omitido', 'contacto omitido',
    'media omitted', 'image omitted', 'video omitted', 'audio omitted',
    'sticker omitted', 'gif omitted', 'document omitted', 'contact card omitted',
    '<archivo adjunto>', '<attached:', 'this message was deleted',
    'se eliminó este mensaje', 'eliminaste este mensaje', 'you deleted this message'
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

def fig_a_png_bytes(fig, ancho=1200, alto=650, escala=2):
    """Convierte una figura de Plotly a bytes PNG usando el motor kaleido."""
    return pio.to_image(fig, format="png", width=ancho, height=alto, scale=escala)


def generar_resumen_ia(stats):
    """Genera un resumen del 'carácter' del grupo usando la nueva API oficial de Gemini."""
    try:
        from google import genai
        
        # Obtenemos la clave del entorno de forma segura
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        
        if not api_key:
            return ("No se ha generado un resumen con IA porque el servidor no tiene "
                    "configurada la clave GEMINI_API_KEY o GOOGLE_API_KEY en el archivo .env.")
        
        # Inicialización moderna utilizando la nueva SDK de Google
        client = genai.Client(api_key=api_key)
        
    except Exception as e:
        return f"No se pudo inicializar la nueva librería 'google-genai' ({type(e).__name__}). Asegúrate de hacer pip install google-genai"

    prompt = f"""Eres un analista de datos que resume la personalidad de un grupo de WhatsApp
a partir de estadísticas agregadas (nunca has visto los mensajes originales). Con estos datos:

- Mensajes totales: {stats['total_mensajes']}
- Rango de fechas: {stats['fecha_inicio']} a {stats['fecha_fin']}
- Número de participantes activos: {stats['num_usuarios']}
- Top 5 miembros más activos (usuario: mensajes): {stats['top5_usuarios']}
- Hora del día con más actividad: {stats['hora_pico']}h
- Día de la semana con más actividad: {stats['dia_pico']}
- Porcentaje de mensajes multimedia/eliminados: {stats['pct_multimedia']:.1f}%
- Miembro con mayor % de "mensajes fantasma" (sin respuesta en 3h): {stats['top_fantasma']}
- Emojis más usados: {stats['top_emojis']}
- Palabras clave más repetidas: {stats['top_palabras']}

Escribe un resumen ameno y cercano en español (150-200 palabras, sin listas, en prosa) que describa
la personalidad y dinámica de este grupo: quién lo anima, cuándo está más vivo, qué lo caracteriza.
Tono ligero y positivo, como el resumen anual de una app de estadísticas. No inventes datos que no
se te han dado y no menciones nombres reales si no aparecen explícitamente en la lista de arriba."""

    try:
        # Sintaxis moderna: se usa client.models.generate_content con el modelo 'gemini-2.5-flash'
        respuesta = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt
        )
        return respuesta.text.strip()
    except Exception as e:
        return f"No se pudo generar el resumen con la nueva API de Gemini ({type(e).__name__})."


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
    "multimedia": "Cantidad de fotos, vídeos, audios, stickers y mensajes eliminados que ha compartido "
                  "cada miembro (contenido que no se puede analizar como texto).",
    "longitud": "Longitud media, en caracteres, de los mensajes de texto de cada miembro: quién escribe "
                "párrafos y quién prefiere respuestas cortas.",
    "emojis": "Los emojis que más se repiten en las conversaciones de texto del grupo.",
    "palabras": "Frecuencia de aparición de una lista de palabras clave (elegidas por el usuario o por "
                "defecto) a lo largo de todo el historial del chat.",
    "burbujas": "Mapa de las 100 palabras más repetidas en el grupo (excluyendo multimedia y palabras "
                "vacías): cuanto más grande la burbuja, más veces se ha usado esa palabra.",
}


def generar_informe_pdf(stats, resumen_ia, imagenes):
    """Construye el informe PDF completo (portada + resumen IA + una sección
    por cada gráfica con su explicación) y devuelve los bytes del archivo."""

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
    story.append(Paragraph("📊 Informe de Análisis de WhatsApp", estilo_titulo))
    story.append(Spacer(1, 0.4*cm))
    story.append(Paragraph(f"Generado el {datetime.datetime.now().strftime('%d/%m/%Y a las %H:%M')}", estilo_subtitulo))
    story.append(Paragraph(f"{stats['total_mensajes']:,} mensajes analizados · {stats['num_usuarios']} participantes · "
                            f"del {stats['fecha_inicio']} al {stats['fecha_fin']}", estilo_subtitulo))
    story.append(Spacer(1, 1*cm))
    story.append(HRFlowable(width="100%", color=colors.HexColor('#14B8A6'), thickness=1.2))
    story.append(Spacer(1, 1*cm))

    # --- Resumen generado por IA ---
    story.append(Paragraph("🤖 Resumen del grupo (generado con IA)", estilo_h2))
    story.append(Paragraph(resumen_ia.replace("\n", "<br/>"), estilo_cuerpo))
    story.append(PageBreak())

    # --- Una sección por gráfica ---
    titulos = {
        "ranking": "📊 Miembros más activos",
        "horas": "🕒 Actividad por hora del día",
        "heatmap": "🗓️ Actividad por día y hora",
        "matriz": "🧩 Matriz de afinidad cruzada",
        "evolucion": "📅 Evolución anual de mensajes",
        "tiempo": "⏱️ Tiempo de respuesta medio",
        "fantasma": "👻 Mensajes fantasma",
        "multimedia": "📎 Multimedia y mensajes eliminados",
        "longitud": "✍️ Longitud media de mensaje",
        "emojis": "😂 Emojis más usados",
        "palabras": "🏷️ Palabras clave",
        "burbujas": "🔮 Mapa de conceptos",
    }

    for clave, imagen_bytes in imagenes.items():
        if not imagen_bytes:
            continue
        story.append(Paragraph(titulos.get(clave, clave.title()), estilo_h2))
        story.append(Paragraph(EXPLICACIONES_GRAFICAS.get(clave, ""), estilo_explicacion))
        try:
            img_buf = io.BytesIO(imagen_bytes)
            if clave == "burbujas":
                imagen_rl = RLImage(img_buf, width=12*cm, height=12*cm)
            else:
                imagen_rl = RLImage(img_buf, width=16*cm, height=8.7*cm)
            story.append(imagen_rl)
        except Exception:
            story.append(Paragraph("(No se pudo incrustar esta gráfica en el PDF)", estilo_explicacion))
        story.append(Spacer(1, 0.6*cm))

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()


@app.get("/", response_class=HTMLResponse)
async def inicio(request: Request):
    return templates.TemplateResponse(name="index.html", context={}, request=request)


@app.post("/analizar", response_class=HTMLResponse)
async def analizar_chat(request: Request, file: UploadFile = File(...), custom_words: str = Form(None)):
    contenido = await file.read()
    df = procesar_chat_whatsapp(contenido)

    if df.empty:
        return HTMLResponse("<h2 style='color:white; font-family:sans-serif; text-align:center; margin-top:50px;'>Error: El formato de tu archivo de chat no coincide con los patrones de lectura de WhatsApp.</h2>", status_code=400)

    # --- PROCESAMIENTO CRONOLÓGICO Y CÁLCULOS AVANZADOS ---
    df['Fecha_Completa'] = pd.to_datetime(df['Fecha'] + ' ' + df['Hora'], format='mixed', errors='coerce')
    df = df.dropna(subset=['Fecha_Completa']).sort_values('Fecha_Completa').reset_index(drop=True)
    df['Hora_Int'] = df['Fecha_Completa'].dt.hour
    df['Año'] = df['Fecha_Completa'].dt.year
    df['Dia_Semana_Num'] = df['Fecha_Completa'].dt.dayofweek
    df['Tiempo_Dif_Min'] = df['Fecha_Completa'].diff().dt.total_seconds() / 60.0
    df['Autor_Anterior'] = df['Autor'].shift(1)

    df['Es_Multimedia'] = df['Mensaje'].astype(str).str.lower().apply(
        lambda t: any(frase in t for frase in FRASES_MULTIMEDIA)
    )

    total_mensajes_usuario = df['Autor'].value_counts()
    usuarios_top_15 = total_mensajes_usuario.head(15).index.tolist()

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
    g1 = pio.to_html(fig1, full_html=False, div_id='g-ranking', config={'displayModeBar': False})

    # 2. Gráfica: Actividad por Hora
    m_hora = df['Hora_Int'].value_counts().sort_index().reindex(range(0, 24), fill_value=0).reset_index()
    m_hora.columns = ['Hora', 'Mensajes']
    fig2 = px.line(m_hora, x='Hora', y='Mensajes', title='Actividad por Hora', markers=True)
    fig2.update_traces(line=dict(color='#128C7E', width=3))
    fig2.update_layout(template='plotly_dark', paper_bgcolor='rgba(30,41,59,1)', plot_bgcolor='rgba(0,0,0,0)', margin=dict(t=50,b=20,l=20,r=20), xaxis=dict(title='', tickmode='linear', tick0=0, dtick=2), yaxis=dict(title=''))
    g2 = pio.to_html(fig2, full_html=False, div_id='g-horas', config={'displayModeBar': False})

    # 3. Gráfica: Matriz de Afinidad Cruzada
    df_f_matriz = df[df['Autor'].isin(usuarios_top_15) & df['Autor_Anterior'].isin(usuarios_top_15)]
    df_conv_activa = df_f_matriz[(df_f_matriz['Tiempo_Dif_Min'] <= 15) & (df_f_matriz['Autor'] != df_f_matriz['Autor_Anterior'])]
    matriz_interaccion = pd.crosstab(df_conv_activa['Autor'], df_conv_activa['Autor_Anterior']).reindex(index=usuarios_top_15, columns=usuarios_top_15, fill_value=0)
    matriz_normalizada = matriz_interaccion.div(matriz_interaccion.sum(axis=1), axis=0).fillna(0) * 100
    matriz_valores = matriz_normalizada.values.astype(float)
    etiquetas_texto = np.round(matriz_valores, 1).astype(str)
    texto_celdas = np.where(np.eye(matriz_valores.shape[0], dtype=bool), "-", np.char.add(etiquetas_texto, "%"))

    fig3 = go.Figure(data=go.Heatmap(z=matriz_valores, x=matriz_normalizada.columns, y=matriz_normalizada.index, colorscale='GnBu', text=texto_celdas, texttemplate="%{text}", hoverinfo="text"))
    
    # 🛠️ MODIFICADO: Aumentamos la altura (height) y expandimos los márgenes inferiores (b=180) y derecho (r=40)
    fig3.update_layout(
        title='Afinidad entre miembros de grupos', 
        template='plotly_dark', 
        paper_bgcolor='rgba(30,41,59,1)', 
        plot_bgcolor='rgba(0,0,0,0)', 
        height=750,                      # Más alto para que luzca más amplio
        margin=dict(t=60, b=180, l=140, r=40), # b=180 evita que se corten las etiquetas inclinadas y el disclaimer
        yaxis=dict(autorange="reversed")
    )
    
    # 🛠️ MODIFICADO: Ajustamos la posición 'y' del disclaimer para que baje un poco más debido al nuevo margen
    fig3.add_annotation(
        text="*Solo se contabilizan respuestas rápidas ocurridas en una ventana menor a 15 minutos.",
        xref="paper", yref="paper",
        x=1.0, y=-0.28,  # y=-0.28 empuja el texto bien abajo de los nombres de los usuarios
        showarrow=False,
        font=dict(size=10, color="#94a3b8"), 
        align="right"
    )
    
    fig3.update_xaxes(tickangle=-45)
    g3 = pio.to_html(fig3, full_html=False, div_id='g-matriz', config={'displayModeBar': False})

    # 4. Gráfica: Evolución Anual
    m_tiempo = df['Año'].value_counts().sort_index().reset_index()
    m_tiempo.columns = ['Año', 'Mensajes']
    m_tiempo['Año'] = m_tiempo['Año'].astype(str)
    fig4 = px.bar(m_tiempo, x='Año', y='Mensajes', text='Mensajes', title='Mensajes enviados por año')
    fig4.update_traces(marker_color='#128C7E', texttemplate='%{text:,}', textposition='outside', cliponaxis=False)
    fig4.update_layout(template='plotly_dark', paper_bgcolor='rgba(30,41,59,1)', plot_bgcolor='rgba(0,0,0,0)', margin=dict(t=50,b=20,l=20,r=20), xaxis=dict(title=''), yaxis=dict(visible=False))
    g4 = pio.to_html(fig4, full_html=False, div_id='g-evolucion', config={'displayModeBar': False})

    # 5. DataFrame de Convivencia
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
    g5_tiempo = pio.to_html(fig5_tiempo, full_html=False, div_id='g-tiempo', config={'displayModeBar': False})

    # 5B. Mensajes Fantasma
    df_fantasma = df_convivencia.sort_values(by='Mensajes Fantasma (%)', ascending=False)
    df_fantasma['Texto_Porcentaje'] = df_fantasma['Mensajes Fantasma (%)'].apply(lambda x: f"{x:.1f}%")

    fig5_fantasma = px.bar(df_fantasma, x='Mensajes Fantasma (%)', y='Usuario', orientation='h', text='Texto_Porcentaje', title='👻 Fantasmas del Grupo: Porcentaje de Vistos', color='Mensajes Fantasma (%)', color_continuous_scale='rdpu')
    fig5_fantasma.update_traces(textposition='outside', cliponaxis=False)
    fig5_fantasma.update_layout(template='plotly_dark', paper_bgcolor='rgba(30,41,59,1)', plot_bgcolor='rgba(0,0,0,0)', coloraxis_showscale=False, height=550, margin=dict(t=50, b=40, l=140, r=70), xaxis=dict(visible=False), yaxis=dict(title=''))
    g5_fantasma = pio.to_html(fig5_fantasma, full_html=False, div_id='g-fantasma', config={'displayModeBar': False})

    # --- Palabras clave ---
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
    g_palabras = pio.to_html(fig_palabras, full_html=False, div_id='g-palabras', config={'displayModeBar': False})

    # 6. Gráfica: Bubble Chart
    df_solo_texto = df[~df['Es_Multimedia']]
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
        plt.savefig(buf, format='png', dpi=200, facecolor='#1E293B', edgecolor='none')
        buf.seek(0)
        g6_base64 = base64.b64encode(buf.getvalue()).decode('utf-8')
        plt.close(fig_mpl)

    # 7. Heatmap
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
        title='Actividad por día de la semana y hora del día',
        template='plotly_dark', paper_bgcolor='rgba(30,41,59,1)', plot_bgcolor='rgba(0,0,0,0)',
        height=450, margin=dict(t=50, b=40, l=90, r=20),
        xaxis=dict(title='Hora del día', tickmode='linear', tick0=0, dtick=2),
        yaxis=dict(title='', autorange='reversed')
    )
    g7 = pio.to_html(fig7, full_html=False, div_id='g-heatmap-semana', config={'displayModeBar': False})

    # 8. Multimedia
    total_multimedia = int(df['Es_Multimedia'].sum())
    multimedia_por_usuario = df[df['Es_Multimedia']]['Autor'].value_counts().reindex(usuarios_top_15, fill_value=0)
    df_multimedia = multimedia_por_usuario.reset_index()
    df_multimedia.columns = ['Usuario', 'Cantidad']
    df_multimedia = df_multimedia.sort_values('Cantidad', ascending=True)

    fig8 = px.bar(df_multimedia, x='Cantidad', y='Usuario', orientation='h', text='Cantidad', title='📎 Multimedia y Mensajes Eliminados por Miembro', color='Cantidad', color_continuous_scale='purpor')
    fig8.update_traces(texttemplate='%{text:,}', textposition='outside', cliponaxis=False)
    fig8.update_layout(template='plotly_dark', paper_bgcolor='rgba(30,41,59,1)', plot_bgcolor='rgba(0,0,0,0)', coloraxis_showscale=False, height=550, margin=dict(t=50,b=20,l=140,r=70), xaxis=dict(visible=False), yaxis=dict(title=''))
    g8 = pio.to_html(fig8, full_html=False, div_id='g-multimedia', config={'displayModeBar': False})

    # 9. Longitud media
    df_solo_texto = df_solo_texto.copy()
    df_solo_texto['Longitud'] = df_solo_texto['Mensaje'].astype(str).str.len()
    longitud_media_usuario = df_solo_texto.groupby('Autor')['Longitud'].mean().reindex(usuarios_top_15, fill_value=0)
    df_longitud = longitud_media_usuario.round(1).reset_index()
    df_longitud.columns = ['Usuario', 'Caracteres']
    df_longitud = df_longitud.sort_values('Caracteres', ascending=True)

    fig9 = px.bar(df_longitud, x='Caracteres', y='Usuario', orientation='h', text='Caracteres', title='✍️ Longitud Media de Mensaje por Miembro (caracteres)', color='Caracteres', color_continuous_scale='tealgrn')
    fig9.update_traces(textposition='outside', cliponaxis=False)
    fig9.update_layout(template='plotly_dark', paper_bgcolor='rgba(30,41,59,1)', plot_bgcolor='rgba(0,0,0,0)', coloraxis_showscale=False, height=550, margin=dict(t=50,b=20,l=140,r=70), xaxis=dict(visible=False), yaxis=dict(title=''))
    g9 = pio.to_html(fig9, full_html=False, div_id='g-longitud', config={'displayModeBar': False})

    # 10. Emojis
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
        g10 = pio.to_html(fig10, full_html=False, div_id='g-emojis', config={'displayModeBar': False})

    ranking_tabla = [{"usuario": u, "cantidad": m} for u, m in total_mensajes_usuario.items()]

    # 11. PDF e IA
    stats_para_ia = {
        "total_mensajes": len(df),
        "fecha_inicio": df['Fecha_Completa'].min().strftime('%d/%m/%Y'),
        "fecha_fin": df['Fecha_Completa'].max().strftime('%d/%m/%Y'),
        "num_usuarios": df['Autor'].nunique(),
        "top5_usuarios": total_mensajes_usuario.head(5).to_dict(),
        "hora_pico": int(m_hora.loc[m_hora['Mensajes'].idxmax(), 'Hora']),
        "dia_pico": tabla_heatmap.sum(axis=1).idxmax(),
        "pct_multimedia": (total_multimedia / len(df) * 100) if len(df) else 0,
        "top_fantasma": df_fantasma.iloc[0]['Usuario'] if not df_fantasma.empty else "N/A",
        "top_emojis": [e for e, _ in Counter(todos_los_emojis).most_common(8)] if todos_los_emojis else [],
        "top_palabras": df_conceptos.sort_values('Frecuencia', ascending=False).head(8)['Concepto'].tolist(),
    }

    resumen_ia = generar_resumen_ia(stats_para_ia)

    imagenes_pdf = {}
    figuras_plotly = {
        "ranking": fig1, "horas": fig2, "heatmap": fig7, "matriz": fig3,
        "evolucion": fig4, "tiempo": fig5_tiempo, "fantasma": fig5_fantasma,
        "multimedia": fig8, "longitud": fig9, "palabras": fig_palabras,
    }
    if todos_los_emojis:
        figuras_plotly["emojis"] = fig10

    for clave, figura in figuras_plotly.items():
        try:
            imagenes_pdf[clave] = fig_a_png_bytes(figura)
        except Exception:
            imagenes_pdf[clave] = None

    if g6_base64:
        imagenes_pdf["burbujas"] = base64.b64decode(g6_base64)

    try:
        pdf_bytes = generar_informe_pdf(stats_para_ia, resumen_ia, imagenes_pdf)
        pdf_base64 = base64.b64encode(pdf_bytes).decode('utf-8')
    except Exception:
        pdf_base64 = None

    return templates.TemplateResponse(
        name="resultados.html",
        context={
            "total_mensajes": len(df),
            "total_multimedia": total_multimedia,
            "ranking": ranking_tabla,
            "g1": g1, "g2": g2, "g3": g3, "g4": g4,
            "g5_tiempo": g5_tiempo,
            "g5_fantasma": g5_fantasma,
            "g_palabras": g_palabras,
            "g6": g6_base64,
            "g7": g7,
            "g8": g8,
            "g9": g9,
            "g10": g10,
            "pdf_base64": pdf_base64,
        },
        request=request
    )