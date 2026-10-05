"""Endpoints de FastAPI ("/", "/analizar", "/generar_pdf/{token}") y el
manejador de errores global de la aplicación."""

import re
import gc
import json
import base64
from collections import Counter

import pandas as pd
import numpy as np

import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio

from fastapi import APIRouter, File, UploadFile, Request, Form
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from .config import FRASES_MULTIMEDIA, FRASES_ELIMINADO, PATRON_EMOJI, DIAS_SEMANA_ES
from .chat_parser import procesar_chat_whatsapp
from .zip_utils import es_zip, extraer_txt_de_zip, ErrorZip
from .bubble_chart import generar_mapa_burbujas
from .pdf_charts import grafico_barh_mpl, grafico_barv_mpl, grafico_linea_mpl, grafico_heatmap_mpl
from .pdf_report import generar_informe_pdf
from .pdf_cache import CACHE_DATOS_PDF, _guardar_datos_pdf_en_cache

router = APIRouter()
templates = Jinja2Templates(directory="templates")


async def manejador_errores_generico(request: Request, exc: Exception):
    """Red de seguridad: si algo revienta en cualquier endpoint (un chat con un
    formato inesperado, un fallo al generar una gráfica, etc.), en vez de un
    500 en blanco mostramos una pantalla de error con estilo y un botón para
    volver a intentarlo."""
    print(f"[ERROR] Excepción no controlada en {request.url.path}: {exc}")
    return templates.TemplateResponse(
        name="error.html",
        context={"mensaje": "Ha ocurrido un error inesperado al procesar tu solicitud. Vuelve a intentarlo o prueba con otro archivo."},
        request=request,
        status_code=500,
    )


@router.get("/", response_class=HTMLResponse)
async def inicio(request: Request):
    return templates.TemplateResponse(name="index.html", context={}, request=request)


@router.post("/analizar", response_class=HTMLResponse)
def analizar_chat(request: Request, file: UploadFile = File(...), custom_words: str = Form(None)):
    LIMITE_TAMANO_MB = 25

    # Si es un .zip (exportación de WhatsApp), se extrae solo el .txt del chat.
    # Se lee directamente del archivo temporal, sin cargar el zip entero en
    # memoria (puede traer fotos y audios).
    if es_zip(file.file):
        try:
            contenido = extraer_txt_de_zip(file.file, LIMITE_TAMANO_MB * 1024 * 1024)
        except ErrorZip as e:
            return templates.TemplateResponse(
                name="error.html",
                context={"mensaje": e.mensaje},
                request=request,
                status_code=e.status_code,
            )
    else:
        contenido = file.file.read()

    # El plan Free de Render tiene solo 512MB de RAM. Un .txt de WhatsApp muy
    # grande se convierte en un DataFrame bastante más pesado que el propio
    # archivo (cada mensaje es un objeto de texto en Python), y encima genera
    # 13 gráficas interactivas a la vez: por encima de este tamaño es fácil
    # quedarse sin memoria. Lo rechazamos con un aviso claro en vez de que el
    # servicio se caiga a medias.
    if len(contenido) > LIMITE_TAMANO_MB * 1024 * 1024:
        return templates.TemplateResponse(
            name="error.html",
            context={"mensaje": f"Tu archivo pesa más de {LIMITE_TAMANO_MB}MB y este servidor no tiene memoria suficiente "
                                 f"para procesarlo de una vez. Prueba a exportar un rango de fechas más corto, o a "
                                 f"dividir el chat en varias exportaciones."},
            request=request,
            status_code=413,
        )

    df = procesar_chat_whatsapp(contenido)
    del contenido  # ya no hace falta el texto en crudo, liberamos su memoria cuanto antes

    if df.empty:
        return templates.TemplateResponse(
            name="error.html",
            context={"mensaje": "El formato de tu archivo no coincide con los patrones de lectura de WhatsApp. "
                                 "Asegúrate de haber exportado el chat sin archivos adjuntos y de subir el .txt tal cual lo recibiste."},
            request=request,
            status_code=400,
        )

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
    fig1.update_layout(template='plotly_dark', paper_bgcolor='rgba(30,41,59,1)', plot_bgcolor='rgba(0,0,0,0)', coloraxis_showscale=False, margin=dict(t=50,b=20,l=140,r=80), xaxis=dict(visible=False), yaxis=dict(title='', ticksuffix='  '))
    g1 = pio.to_html(fig1, full_html=False, include_plotlyjs=False, div_id='g-ranking', config={'displayModeBar': False})
    del fig1

    # 2. Gráfica: Actividad por Hora
    m_hora = df['Hora_Int'].value_counts().sort_index().reindex(range(0, 24), fill_value=0).reset_index()
    m_hora.columns = ['Hora', 'Mensajes']
    fig2 = px.line(m_hora, x='Hora', y='Mensajes', title='Actividad por hora del día', markers=True)
    fig2.update_traces(line=dict(color='#128C7E', width=3))
    fig2.update_layout(template='plotly_dark', paper_bgcolor='rgba(30,41,59,1)', plot_bgcolor='rgba(0,0,0,0)', margin=dict(t=50,b=20,l=20,r=20), xaxis=dict(title='', tickmode='linear', tick0=0, dtick=2), yaxis=dict(title=''))
    g2 = pio.to_html(fig2, full_html=False, include_plotlyjs=False, div_id='g-horas', config={'displayModeBar': False})
    del fig2

    # 3. Gráfica: Matriz de Afinidad Cruzada
    df_f_matriz = df[df['Autor'].isin(usuarios_top_15) & df['Autor_Anterior'].isin(usuarios_top_15)]
    df_conv_activa = df_f_matriz[(df_f_matriz['Tiempo_Dif_Min'] <= 15) & (df_f_matriz['Autor'] != df_f_matriz['Autor_Anterior'])]
    matriz_interaccion = pd.crosstab(df_conv_activa['Autor'], df_conv_activa['Autor_Anterior']).reindex(index=usuarios_top_15, columns=usuarios_top_15, fill_value=0)
    matriz_normalizada = matriz_interaccion.div(matriz_interaccion.sum(axis=1), axis=0).fillna(0) * 100
    matriz_valores = matriz_normalizada.values.astype(float)
    etiquetas_texto = np.round(matriz_valores, 1).astype(str)
    texto_celdas = np.where(np.eye(matriz_valores.shape[0], dtype=bool), "-", np.char.add(etiquetas_texto, "%"))

    fig3 = go.Figure(data=go.Heatmap(z=matriz_valores, x=matriz_normalizada.columns, y=matriz_normalizada.index, colorscale='GnBu', text=texto_celdas, texttemplate="%{text}", hoverinfo="text"))
    fig3.update_layout(
        title='Matriz de Afinidad Cruzada (% de respuestas por fila)<br>'
              '<span style="font-size:0.6em;color:#94a3b8">Por cada miembro (fila), qué % de sus respuestas rápidas (menos de 15 min) van dirigidas a cada otro miembro (columna)</span>',
        template='plotly_dark', paper_bgcolor='rgba(30,41,59,1)', plot_bgcolor='rgba(0,0,0,0)', height=650, margin=dict(t=90, b=120, l=140, r=20), yaxis=dict(autorange="reversed"))
    fig3.update_xaxes(tickangle=-45)
    g3 = pio.to_html(fig3, full_html=False, include_plotlyjs=False, div_id='g-matriz', config={'displayModeBar': False})
    del fig3

    # 4. Gráfica: Evolución Anual
    m_tiempo = df['Año'].value_counts().sort_index().reset_index()
    m_tiempo.columns = ['Año', 'Mensajes']
    m_tiempo['Año'] = m_tiempo['Año'].astype(str)
    fig4 = px.bar(m_tiempo, x='Año', y='Mensajes', text='Mensajes', title='Mensajes enviados por año')
    fig4.update_traces(marker_color='#128C7E', texttemplate='%{text:,}', textposition='outside', cliponaxis=False)
    fig4.update_layout(template='plotly_dark', paper_bgcolor='rgba(30,41,59,1)', plot_bgcolor='rgba(0,0,0,0)', margin=dict(t=50,b=20,l=20,r=20), xaxis=dict(title=''), yaxis=dict(visible=False))
    g4 = pio.to_html(fig4, full_html=False, include_plotlyjs=False, div_id='g-evolucion', config={'displayModeBar': False})
    del fig4

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

    fig5_tiempo = px.bar(df_tiempo, x='Tiempo Respuesta (min)', y='Usuario', orientation='h',
                          title='⏱️ Tiempo de Respuesta Medio por Miembro<br>'
                                '<span style="font-size:0.6em;color:#94a3b8">Minutos que tarda cada miembro, de media, en responder cuando alguien le escribe (solo se cuentan respuestas en menos de 2h)</span>',
                          color='Tiempo Respuesta (min)', color_continuous_scale='tealgrn', text='Texto_Formateado')
    fig5_tiempo.update_traces(textposition='outside', cliponaxis=False)
    fig5_tiempo.update_layout(template='plotly_dark', paper_bgcolor='rgba(30,41,59,1)', plot_bgcolor='rgba(0,0,0,0)', coloraxis_showscale=False, height=550, margin=dict(t=80, b=40, l=140, r=80), xaxis=dict(visible=False), yaxis=dict(title='', ticksuffix='  '))
    g5_tiempo = pio.to_html(fig5_tiempo, full_html=False, include_plotlyjs=False, div_id='g-tiempo', config={'displayModeBar': False})
    del fig5_tiempo

    # 5B. Mensajes Fantasma
    df_fantasma = df_convivencia.sort_values(by='Mensajes Fantasma (%)', ascending=False)
    df_fantasma['Texto_Porcentaje'] = df_fantasma['Mensajes Fantasma (%)'].apply(lambda x: f"{x:.1f}%")

    fig5_fantasma = px.bar(df_fantasma, x='Mensajes Fantasma (%)', y='Usuario', orientation='h', text='Texto_Porcentaje',
                            title='👻 Fantasmas del Grupo: Porcentaje de Vistos<br>'
                                  '<span style="font-size:0.6em;color:#94a3b8">% de mensajes de cada miembro que se quedan sin respuesta de nadie durante más de 3 horas ("en visto")</span>',
                            color='Mensajes Fantasma (%)', color_continuous_scale='rdpu')
    fig5_fantasma.update_traces(textposition='outside', cliponaxis=False)
    fig5_fantasma.update_layout(template='plotly_dark', paper_bgcolor='rgba(30,41,59,1)', plot_bgcolor='rgba(0,0,0,0)', coloraxis_showscale=False, height=550, margin=dict(t=80, b=40, l=140, r=70), xaxis=dict(visible=False), yaxis=dict(title='', ticksuffix='  '))
    g5_fantasma = pio.to_html(fig5_fantasma, full_html=False, include_plotlyjs=False, div_id='g-fantasma', config={'displayModeBar': False})
    del fig5_fantasma

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

    df.drop(columns=['Mensaje_Minus'], inplace=True)  # era una copia completa del texto: liberamos esa memoria ya

    fig_palabras = px.bar(df_conceptos, x='Frecuencia', y='Concepto', orientation='h', text='Frecuencia', title='Frecuencia de palabras clave personalizadas', color='Frecuencia', color_continuous_scale='tealgrn', custom_data=['Detalle_Autores'])
    fig_palabras.update_traces(texttemplate='%{text:,}', textposition='outside', cliponaxis=False, hovertemplate="<b>Palabra:</b> %{y}<br><b>Total en grupo:</b> %{x} veces<br><br><b>Desglose de uso:</b><br>%{customdata[0]}<extra></extra>")
    fig_palabras.update_layout(template='plotly_dark', paper_bgcolor='rgba(30,41,59,1)', plot_bgcolor='rgba(0,0,0,0)', coloraxis_showscale=False, margin=dict(t=50,b=20,l=100,r=70), xaxis=dict(visible=False), yaxis=dict(title='', ticksuffix='  '))
    g_palabras = pio.to_html(fig_palabras, full_html=False, include_plotlyjs=False, div_id='g-palabras', config={'displayModeBar': False})
    del fig_palabras

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

    g6_base64 = generar_mapa_burbujas(top_100_palabras)

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
    del fig7

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
    fig8.update_layout(template='plotly_dark', paper_bgcolor='rgba(30,41,59,1)', plot_bgcolor='rgba(0,0,0,0)', coloraxis_showscale=False, height=550, margin=dict(t=50,b=20,l=140,r=70), xaxis=dict(visible=False), yaxis=dict(title='', ticksuffix='  '))
    g8 = pio.to_html(fig8, full_html=False, include_plotlyjs=False, div_id='g-multimedia', config={'displayModeBar': False})
    del fig8

    # 8B. Mensajes Eliminados por usuario
    eliminados_por_usuario = df[df['Es_Eliminado']]['Autor'].value_counts().reindex(usuarios_top_15, fill_value=0)
    df_eliminados = eliminados_por_usuario.reset_index()
    df_eliminados.columns = ['Usuario', 'Cantidad']
    df_eliminados = df_eliminados.sort_values('Cantidad', ascending=True)

    fig8b = px.bar(df_eliminados, x='Cantidad', y='Usuario', orientation='h', text='Cantidad', title='🗑️ Mensajes Eliminados por Miembro', color='Cantidad', color_continuous_scale='burg')
    fig8b.update_traces(texttemplate='%{text:,}', textposition='outside', cliponaxis=False)
    fig8b.update_layout(template='plotly_dark', paper_bgcolor='rgba(30,41,59,1)', plot_bgcolor='rgba(0,0,0,0)', coloraxis_showscale=False, height=550, margin=dict(t=50,b=20,l=140,r=70), xaxis=dict(visible=False), yaxis=dict(title='', ticksuffix='  '))
    g8b = pio.to_html(fig8b, full_html=False, include_plotlyjs=False, div_id='g-eliminados', config={'displayModeBar': False})
    del fig8b

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
    fig9.update_layout(template='plotly_dark', paper_bgcolor='rgba(30,41,59,1)', plot_bgcolor='rgba(0,0,0,0)', coloraxis_showscale=False, height=550, margin=dict(t=50,b=20,l=140,r=70), xaxis=dict(visible=False), yaxis=dict(title='', ticksuffix='  '))
    g9 = pio.to_html(fig9, full_html=False, include_plotlyjs=False, div_id='g-longitud', config={'displayModeBar': False})
    del fig9

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
        fig10.update_layout(template='plotly_dark', paper_bgcolor='rgba(30,41,59,1)', plot_bgcolor='rgba(0,0,0,0)', coloraxis_showscale=False, height=550, margin=dict(t=50,b=20,l=70,r=70), xaxis=dict(visible=False), yaxis=dict(title='', tickfont=dict(size=26), ticksuffix='  '))
        g10 = pio.to_html(fig10, full_html=False, include_plotlyjs=False, div_id='g-emojis', config={'displayModeBar': False})
        del fig10

    ranking_tabla = [{"usuario": u, "cantidad": m} for u, m in total_mensajes_usuario.items()]

    # =========================================================================
    # 11B. 👥 Perfil individual de CADA integrante, para la vista de estadísticas
    #      por usuario (al clicar su fila en la tabla de ranking de la web).
    # =========================================================================
    hora_favorita_por_usuario = df.groupby('Autor')['Hora_Int'].agg(lambda h: h.value_counts().idxmax())
    longitud_media_por_usuario = df_solo_texto.groupby('Autor')['Mensaje'].apply(lambda s: s.astype(str).str.len().mean())

    emoji_favorito_por_usuario = {}
    for autor, sub_df in df_solo_texto.groupby('Autor'):
        emojis_autor = PATRON_EMOJI.findall(" ".join(sub_df['Mensaje'].astype(str)))
        if emojis_autor:
            emoji_favorito_por_usuario[autor] = Counter(emojis_autor).most_common(1)[0][0]

    multimedia_todos_usuarios = df[df['Es_Multimedia']]['Autor'].value_counts()
    eliminados_todos_usuarios = df[df['Es_Eliminado']]['Autor'].value_counts()

    perfiles_usuario = {}
    for autor in total_mensajes_usuario.index:
        mensajes_autor = int(total_mensajes_usuario.get(autor, 0))
        perfiles_usuario[autor] = {
            "mensajes": mensajes_autor,
            "pct_mensajes": round(mensajes_autor / len(df) * 100, 1) if len(df) else 0,
            "multimedia": int(multimedia_todos_usuarios.get(autor, 0)),
            "eliminados": int(eliminados_todos_usuarios.get(autor, 0)),
            "hora_favorita": int(hora_favorita_por_usuario.get(autor)) if autor in hora_favorita_por_usuario.index and pd.notna(hora_favorita_por_usuario.get(autor)) else None,
            "longitud_media": round(float(longitud_media_por_usuario.get(autor, 0)), 1) if autor in longitud_media_por_usuario.index and pd.notna(longitud_media_por_usuario.get(autor)) else 0,
            "emoji_favorito": emoji_favorito_por_usuario.get(autor, "—"),
            "tiempo_respuesta_medio": round(float(tiempos_respuesta.get(autor)), 1) if autor in tiempos_respuesta.index and pd.notna(tiempos_respuesta.get(autor)) else None,
            "pct_fantasma": round(float(porcentaje_fantasmas.get(autor, 0)), 1),
        }

    # =========================================================================
    # 12. 📄 Informe PDF descargable (gráficas + explicaciones). Oculto en la
    #     web por ahora (ver resultados.html), pero se deja listo por si se
    #     reactiva más adelante. Solo necesita estos 4 datos para la portada.
    # =========================================================================
    stats_pdf_portada = {
        "total_mensajes": len(df),
        "fecha_inicio": df['Fecha_Completa'].min().strftime('%d/%m/%Y'),
        "fecha_fin": df['Fecha_Completa'].max().strftime('%d/%m/%Y'),
        "num_usuarios": df['Autor'].nunique(),
    }

    # El PDF (imágenes matplotlib + reportlab) es lo más lento de generar, así
    # que no lo construimos aquí: guardamos solo los agregados pequeños que
    # necesita y lo generamos bajo demanda en /generar_pdf/{token} cuando el
    # usuario pulsa el botón de descarga.
    datos_pdf = {
        "stats_pdf_portada": stats_pdf_portada,
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
    gc.collect()

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
            # Perfil por usuario (para el panel que se abre al clicar una fila
            # de la tabla de ranking). Se manda ya serializado a JSON: así el
            # HTML no depende de ningún filtro extra de Jinja2.
            "perfiles_usuario_json": json.dumps(perfiles_usuario, ensure_ascii=False),
        },
        request=request
    )


@router.get("/generar_pdf/{token}")
def generar_pdf(token: str):
    """Genera el informe PDF bajo demanda a partir de los datos guardados en
    caché durante el /analizar correspondiente. Aquí es donde ocurre lo más
    lento: el renderizado de todas las imágenes con matplotlib."""
    datos_pdf = CACHE_DATOS_PDF.get(token)
    if datos_pdf is None:
        return HTMLResponse(
            "<h2 style='color:white; font-family:sans-serif; text-align:center; margin-top:50px;'>"
            "Este informe ya no está disponible (puede haber caducado si el servidor estuvo "
            "inactivo un rato). Vuelve a analizar tu chat para generar un PDF nuevo.</h2>",
            status_code=404,
        )

    stats_pdf_portada = datos_pdf["stats_pdf_portada"]
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
        pdf_bytes = generar_informe_pdf(stats_pdf_portada, imagenes_pdf)
    except Exception as e:
        print(f"[PDF] Error generando el informe PDF: {e}")
        return HTMLResponse(
            "<h2 style='color:white; font-family:sans-serif; text-align:center; margin-top:50px;'>"
            "Hubo un error generando el informe PDF. Inténtalo de nuevo en unos segundos.</h2>",
            status_code=500,
        )

    # Un solo uso: liberamos la memoria en cuanto se ha generado el PDF
    CACHE_DATOS_PDF.pop(token, None)
    del imagenes_pdf
    gc.collect()

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=Informe_Analisis_WhatsApp.pdf"},
    )
