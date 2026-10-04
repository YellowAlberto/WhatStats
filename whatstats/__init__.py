"""Paquete con la lógica de análisis de WhatStats, separada del punto de
entrada de FastAPI (`main.py`) para que el proyecto sea más fácil de leer y
mantener.

Submódulos:
- config: constantes y patrones compartidos (frases, regex de emojis, textos
  explicativos de cada gráfica).
- chat_parser: lectura y parseo del .txt exportado de WhatsApp.
- bubble_chart: algoritmo de empaquetado de círculos + generación del mapa de
  conceptos (bubble chart) que se muestra en la web.
- pdf_charts: gráficas estáticas (matplotlib/seaborn) usadas solo en el
  informe PDF descargable.
- pdf_report: maquetación y generación del PDF final con reportlab.
- pdf_cache: caché en memoria de los datos necesarios para generar el PDF
  bajo demanda.
- routes: endpoints de FastAPI ("/", "/analizar", "/generar_pdf/{token}") y
  el manejador de errores global.
"""
