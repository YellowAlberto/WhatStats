"""Maquetación y generación del informe PDF final (portada + una sección por
cada gráfica con su explicación), usando reportlab."""

import re
import io
import datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image as RLImage, PageBreak, HRFlowable
)

from .config import EXPLICACIONES_GRAFICAS

PATRON_EMOJI_LIMPIEZA = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U0001F1E6-\U0001F1FF"
    "\U00002B00-\U00002BFF"
    "\U0001F900-\U0001F9FF"
    "️"   # variation selector (aparece en emojis como ⏱️ o 🗓️)
    "‍"   # zero-width joiner (secuencias de emoji compuestas)
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


def generar_informe_pdf(stats, imagenes):
    """Construye el informe PDF completo (portada + una sección por cada
    gráfica con su explicación) y devuelve los bytes del archivo.
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
