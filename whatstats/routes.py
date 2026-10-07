"""Endpoints de FastAPI ("/", "/analizar", "/generar_pdf/{token}") y el
manejador de errores global de la aplicación."""

import re
import gc
import json
import base64
from collections import Counter

import pandas as pd
import numpy as np

from fastapi import APIRouter, File, UploadFile, Request, Form
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from .config import FRASES_MULTIMEDIA, FRASES_ELIMINADO, PATRON_EMOJI, DIAS_SEMANA_ES
from .chat_parser import procesar_chat_whatsapp
from .chart_style import (
    a_html, barras_horizontales, barras_verticales, reloj_actividad_horaria, piruletas, mapa_calor,
)
from .zip_utils import es_zip, extraer_txt_de_zip, ErrorZip
from .chat_name import nombre_chat_desde_archivo
from .bubble_chart import generar_mapas_burbujas
from .perfiles import calcular_perfiles, CATALOGO_PERFILES
from .pdf_charts import grafico_barh_mpl, grafico_barv_mpl, grafico_linea_mpl, grafico_heatmap_mpl
from .pdf_report import generar_informe_pdf
from .pdf_cache import CACHE_DATOS_PDF, _guardar_datos_pdf_en_cache

router = APIRouter()


def _json_seguro(datos):
    """JSON listo para incrustar dentro de un <script>: se escapan los '<' para
    que ningún nombre o palabra del chat pueda cerrar la etiqueta <script>."""
    return json.dumps(datos, ensure_ascii=False).replace("<", "\\u003c")


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
    nombre_interno = None
    if es_zip(file.file):
        try:
            contenido, nombre_interno = extraer_txt_de_zip(file.file, LIMITE_TAMANO_MB * 1024 * 1024)
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

    # El nombre del grupo no está en el texto del chat: se deduce del nombre del archivo
    nombre_grupo = nombre_chat_desde_archivo(file.filename, nombre_interno)

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
    fig1 = barras_horizontales(
        top_autores.sort_values('Mensajes'), 'Mensajes', 'Usuario',
        titulo='Miembros más activos', podio=True,
        hover="<b>%{y}</b><br>%{x:,} mensajes<extra></extra>",
    )
    g1 = a_html(fig1, 'g-ranking')
    del fig1

    # 2. Gráfica: Actividad por Hora
    m_hora = df['Hora_Int'].value_counts().sort_index().reindex(range(0, 24), fill_value=0).reset_index()
    m_hora.columns = ['Hora', 'Mensajes']
    fig2 = reloj_actividad_horaria(
        m_hora, titulo='Actividad por hora del día',
        subtitulo='Cada barra es una hora del día (las 0h arriba, en sentido horario); la más larga es la hora pico',
    )
    g2 = a_html(fig2, 'g-horas')
    del fig2

    # 3. Gráfica: Matriz de Afinidad Cruzada
    df_f_matriz = df[df['Autor'].isin(usuarios_top_15) & df['Autor_Anterior'].isin(usuarios_top_15)]
    df_conv_activa = df_f_matriz[(df_f_matriz['Tiempo_Dif_Min'] <= 15) & (df_f_matriz['Autor'] != df_f_matriz['Autor_Anterior'])]
    matriz_interaccion = pd.crosstab(df_conv_activa['Autor'], df_conv_activa['Autor_Anterior']).reindex(index=usuarios_top_15, columns=usuarios_top_15, fill_value=0)
    matriz_normalizada = matriz_interaccion.div(matriz_interaccion.sum(axis=1), axis=0).fillna(0) * 100
    matriz_valores = matriz_normalizada.values.astype(float)
    diagonal = np.eye(matriz_valores.shape[0], dtype=bool)
    matriz_para_dibujar = np.where(diagonal, np.nan, matriz_valores)  # la diagonal (uno mismo) queda en blanco
    # Solo se escribe el porcentaje en las celdas relevantes (>= 5%) para que no sea ilegible
    texto_celdas = np.where(
        diagonal | (matriz_valores < 5), "",
        np.char.add(np.round(matriz_valores).astype(int).astype(str), "%")
    )

    fig3 = mapa_calor(
        matriz_para_dibujar, list(matriz_normalizada.columns), list(matriz_normalizada.index),
        titulo='Afinidad cruzada',
        subtitulo='Por cada miembro (fila), qué % de sus respuestas rápidas (menos de 15 min) van dirigidas a cada otro miembro (columna)',
        texto=texto_celdas,
        hover="<b>%{y}</b> responde a <b>%{x}</b><br>%{z:.1f}% de sus respuestas rápidas<extra></extra>",
        margen=dict(t=90, b=20, l=20, r=20), tickangle_x=-45,
    )
    g3 = a_html(fig3, 'g-matriz')
    del fig3

    # 4. Gráfica: Evolución Anual
    m_tiempo = df['Año'].value_counts().sort_index().reset_index()
    m_tiempo.columns = ['Año', 'Mensajes']
    m_tiempo['Año'] = m_tiempo['Año'].astype(str)
    fig4 = barras_verticales(
        m_tiempo, 'Año', 'Mensajes', titulo='Mensajes por año',
        hover="<b>%{x}</b><br>%{y:,} mensajes<extra></extra>",
    )
    g4 = a_html(fig4, 'g-evolucion')
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

    df_tiempo_graf = df_tiempo.sort_values('Tiempo Respuesta (min)')
    fig5_tiempo = barras_horizontales(
        df_tiempo_graf, 'Tiempo Respuesta (min)', 'Usuario',
        titulo='Tiempo de respuesta medio',
        subtitulo='Lo que tarda cada miembro, de media, en responder cuando alguien le escribe (solo respuestas en menos de 2 h)',
        texto=df_tiempo_graf['Texto_Formateado'].tolist(), texto_formato='%{text}',
        customdata=df_tiempo_graf['Texto_Formateado'].tolist(),
        hover="<b>%{y}</b><br>Responde de media en %{customdata}<extra></extra>",
    )
    g5_tiempo = a_html(fig5_tiempo, 'g-tiempo')
    del fig5_tiempo

    # 5B. Mensajes Fantasma
    df_fantasma = df_convivencia.sort_values(by='Mensajes Fantasma (%)', ascending=False)
    df_fantasma['Texto_Porcentaje'] = df_fantasma['Mensajes Fantasma (%)'].apply(lambda x: f"{x:.1f}%")

    df_fantasma_graf = df_fantasma.sort_values('Mensajes Fantasma (%)')
    fig5_fantasma = barras_horizontales(
        df_fantasma_graf, 'Mensajes Fantasma (%)', 'Usuario',
        titulo='Mensajes fantasma',
        subtitulo='% de mensajes de cada miembro que se quedan sin respuesta de nadie durante más de 3 horas ("en visto")',
        texto=df_fantasma_graf['Texto_Porcentaje'].tolist(), texto_formato='%{text}',
        hover="<b>%{y}</b><br>%{x:.1f}% de sus mensajes sin respuesta<extra></extra>",
    )
    g5_fantasma = a_html(fig5_fantasma, 'g-fantasma')
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

    fig_palabras = barras_horizontales(
        df_conceptos, 'Frecuencia', 'Concepto',
        titulo='Palabras clave',
        customdata=df_conceptos[['Detalle_Autores']].values,
        hover="<b>%{y}</b> · %{x:,} veces<br><br><b>Quién más la usa:</b><br>%{customdata[0]}<extra></extra>",
        # Con muchas palabras (lista personalizada larga) se fija un alto propio y el recuadro hace scroll
        altura=(26 * len(df_conceptos) + 110) if len(df_conceptos) > 25 else None,
    )
    g_palabras = a_html(fig_palabras, 'g-palabras')
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

    g6_base64, g6_svg = generar_mapas_burbujas(top_100_palabras)

    # Detalle de cada burbuja para el tooltip interactivo (solo agregados: la
    # palabra, cuántas veces se usa, su % y quién más la usa; nunca mensajes).
    detalle_burbujas = {}
    if not top_100_palabras.empty:
        palabras_top = set(top_100_palabras['Palabra'])
        uso_por_autor = {p: Counter() for p in palabras_top}
        for autor, sub_df in df_solo_texto.groupby('Autor'):
            texto_autor = " ".join(sub_df['Mensaje'].astype(str)).lower()
            for p in re.findall(r'\b[a-záéíóúñ]+\b', texto_autor):
                if p in palabras_top:
                    uso_por_autor[p][autor] += 1
        total_palabras = max(len(palabras_limpias), 1)
        for puesto, (palabra, frecuencia) in enumerate(zip(top_100_palabras['Palabra'], top_100_palabras['Frecuencia']), start=1):
            detalle_burbujas[palabra] = {
                "n": int(frecuencia),
                "puesto": puesto,
                "pct": round(int(frecuencia) / total_palabras * 100, 2),
                "autores": [[a, int(c)] for a, c in uso_por_autor[palabra].most_common(3)],
            }

    # =========================================================================
    # 7. 🗓️ NUEVO: Heatmap de actividad Día de la Semana × Hora
    # =========================================================================
    tabla_heatmap = (
        df.groupby(['Dia_Semana_Num', 'Hora_Int']).size()
        .unstack(fill_value=0)
        .reindex(index=range(7), columns=range(24), fill_value=0)
    )
    tabla_heatmap.index = DIAS_SEMANA_ES

    fig7 = mapa_calor(
        tabla_heatmap.values, list(range(24)), DIAS_SEMANA_ES,
        titulo='Actividad por día y hora',
        hover='<b>%{y}</b><br>%{x}:00 h<br>%{z:,} mensajes<extra></extra>',
        margen=dict(t=60, b=20, l=20, r=20),
        titulo_x='Hora del día', dtick_x=2,
    )
    g7 = a_html(fig7, 'g-heatmap-semana')
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

    fig8 = piruletas(
        df_multimedia, 'Cantidad', 'Usuario', titulo='Multimedia enviado',
        hover="<b>%{y}</b><br>%{x:,} archivos multimedia<extra></extra>",
    )
    g8 = a_html(fig8, 'g-multimedia')
    del fig8

    # 8B. Mensajes Eliminados por usuario
    eliminados_por_usuario = df[df['Es_Eliminado']]['Autor'].value_counts().reindex(usuarios_top_15, fill_value=0)
    df_eliminados = eliminados_por_usuario.reset_index()
    df_eliminados.columns = ['Usuario', 'Cantidad']
    df_eliminados = df_eliminados.sort_values('Cantidad', ascending=True)

    fig8b = piruletas(
        df_eliminados, 'Cantidad', 'Usuario', titulo='Mensajes eliminados',
        hover="<b>%{y}</b><br>%{x:,} mensajes eliminados<extra></extra>",
    )
    g8b = a_html(fig8b, 'g-eliminados')
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

    fig9 = barras_horizontales(
        df_longitud, 'Caracteres', 'Usuario', titulo='Longitud media de mensaje',
        subtitulo='Caracteres por mensaje de texto',
        texto_formato='%{text:,.1f}',
        hover="<b>%{y}</b><br>%{x:,.1f} caracteres de media<extra></extra>",
    )
    g9 = a_html(fig9, 'g-longitud')
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

        fig10 = barras_horizontales(
            df_emojis, 'Frecuencia', 'Emoji', titulo='Emojis más usados',
            hover="<b>%{y}</b><br>%{x:,} veces<extra></extra>",
            tamano_etiqueta_y=18,
        )
        g10 = a_html(fig10, 'g-emojis')
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

    # Etiqueta de "estilo/mood" de cada persona (se calcula en el servidor; si
    # algo fallara, el resto de la página funciona igual sin etiquetas)
    try:
        etiquetas_usuario = calcular_perfiles(df_solo_texto, df)
    except Exception:
        etiquetas_usuario = {}

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
            "etiqueta": etiquetas_usuario.get(autor),
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
            "nombre_grupo": nombre_grupo,
            "catalogo_perfiles": CATALOGO_PERFILES,
            "total_mensajes": len(df),
            "total_multimedia": total_multimedia,
            "total_eliminados": total_eliminados,
            "ranking": ranking_tabla,
            "g1": g1, "g2": g2, "g3": g3, "g4": g4,
            "g5_tiempo": g5_tiempo,
            "g5_fantasma": g5_fantasma,
            "g_palabras": g_palabras,
            "g6_svg": g6_svg,
            "burbujas_json": _json_seguro(detalle_burbujas),
            "g7": g7,
            "g8": g8,
            "g8b": g8b,
            "g9": g9,
            "g10": g10,
            "pdf_token": pdf_token,
            # Perfil por usuario (para el panel que se abre al clicar una fila
            # de la tabla de ranking). Se manda ya serializado a JSON: así el
            # HTML no depende de ningún filtro extra de Jinja2.
            "perfiles_usuario_json": _json_seguro(perfiles_usuario),
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
