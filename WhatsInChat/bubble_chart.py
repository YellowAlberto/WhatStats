"""Algoritmo de empaquetado de círculos y generación del mapa de conceptos
(bubble chart): un SVG interactivo para la web y un PNG para el informe PDF."""

import io
import base64
from html import escape
import numpy as np
import matplotlib
matplotlib.use('Agg')  # Evita bloqueos en servidores web
import matplotlib.pyplot as plt
from matplotlib import patheffects
import seaborn as sns
from matplotlib.colors import to_hex


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


def _disposicion(top_100_palabras):
    """Calcula (una sola vez) radios y coordenadas de las burbujas y el encuadre
    cuadrado que las contiene: devuelve (coordenadas, radios, (cx, cy, mitad))."""
    radii_base = np.sqrt(top_100_palabras['Frecuencia'].values)
    escala_visual = 25.0 / radii_base.max()
    radii_visuales = radii_base * escala_visual
    coordenadas = empaquetar_circulos(radii_visuales)

    x_min = (coordenadas[:, 0] - radii_visuales).min()
    x_max = (coordenadas[:, 0] + radii_visuales).max()
    y_min = (coordenadas[:, 1] - radii_visuales).min()
    y_max = (coordenadas[:, 1] + radii_visuales).max()
    mitad = max(x_max - x_min, y_max - y_min) / 2 * 1.03
    return coordenadas, radii_visuales, ((x_min + x_max) / 2, (y_min + y_max) / 2, mitad)


def _png_base64(top_100_palabras, coordenadas, radii_visuales, encuadre):
    """Imagen PNG (base64) del mapa, usada en el informe PDF."""
    centro_x, centro_y, mitad = encuadre

    plt.style.use('dark_background')
    fig_mpl, ax_mpl = plt.subplots(figsize=(11, 11))
    fig_mpl.patch.set_facecolor('#1E293B')
    ax_mpl.set_facecolor('#1E293B')

    colores = sns.color_palette("YlGnBu_r", n_colors=len(top_100_palabras))

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
    # Encuadre cuadrado y ajustado a las burbujas (sin márgenes sobrantes)
    ax_mpl.set_xlim(centro_x - mitad, centro_x + mitad)
    ax_mpl.set_ylim(centro_y - mitad, centro_y + mitad)
    ax_mpl.set_aspect('equal', adjustable='box')
    fig_mpl.subplots_adjust(left=0, right=1, bottom=0, top=1)

    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=140, facecolor='#1E293B', edgecolor='none')
    buf.seek(0)
    resultado = base64.b64encode(buf.getvalue()).decode('utf-8')
    plt.close(fig_mpl)
    return resultado


def _svg(top_100_palabras, coordenadas, radii_visuales, encuadre):
    """SVG interactivo (se incrusta tal cual en la página). Cada burbuja es un
    <g class="burbuja"> con sus datos en atributos data-*; el JavaScript de
    resultados.html se encarga del resalte, el tooltip y la pantalla completa."""
    centro_x, centro_y, mitad = encuadre
    colores = sns.color_palette("YlGnBu_r", n_colors=len(top_100_palabras))

    partes = [
        f'<svg id="svg-burbujas" xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="{centro_x - mitad:.2f} {centro_y - mitad:.2f} {2 * mitad:.2f} {2 * mitad:.2f}" '
        f'preserveAspectRatio="xMidYMid meet" role="img" '
        f'aria-label="Mapa de las 100 palabras más usadas: cuanto mayor la burbuja, más veces se ha usado">'
    ]
    for idx in range(len(top_100_palabras)):
        palabra = str(top_100_palabras.iloc[idx]['Palabra'])
        frecuencia = int(top_100_palabras.iloc[idx]['Frecuencia'])
        cx, cy = float(coordenadas[idx][0]), float(coordenadas[idx][1])
        r = float(radii_visuales[idx])
        color = colores[idx]
        brillo = 0.299 * color[0] + 0.587 * color[1] + 0.114 * color[2]
        color_texto = '#0f172a' if brillo > 0.55 else '#ffffff'
        fondo = to_hex(color)

        etiqueta = ""
        # Tamaño de letra limitado por el radio y por lo largo de la palabra
        fs = min(r * 0.42, (2 * r * 0.86) / (max(len(palabra), len(str(frecuencia))) * 0.62))
        if fs >= 2.2:
            etiqueta = (
                f'<text x="{cx:.2f}" y="{cy - fs * 0.1:.2f}" text-anchor="middle" fill="{color_texto}" '
                f'font-size="{fs:.2f}" font-weight="700" pointer-events="none">'
                f'{escape(palabra)}<tspan x="{cx:.2f}" dy="{fs * 1.1:.2f}">{frecuencia}</tspan></text>'
            )
        partes.append(
            f'<g class="burbuja" data-palabra="{escape(palabra, quote=True)}" data-cx="{cx:.2f}" '
            f'data-cy="{cy:.2f}" data-r="{r:.2f}" data-fill="{fondo}" data-txt="{color_texto}">'
            f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r:.2f}" fill="{fondo}"/>{etiqueta}</g>'
        )
    # Capa superior (sin eventos) donde el JS dibuja la burbuja resaltada
    partes.append('<g id="burbuja-foco" pointer-events="none"></g></svg>')
    return "".join(partes)


def generar_mapas_burbujas(top_100_palabras):
    """Devuelve (png_base64, svg) del mapa de conceptos a partir de un DataFrame
    con columnas 'Palabra' y 'Frecuencia' (las 100 palabras más repetidas). El
    PNG va al informe PDF y el SVG interactivo a la web. Si no hay palabras,
    devuelve ("", "")."""
    if top_100_palabras.empty:
        return "", ""
    coordenadas, radii_visuales, encuadre = _disposicion(top_100_palabras)
    png = _png_base64(top_100_palabras, coordenadas, radii_visuales, encuadre)
    svg = _svg(top_100_palabras, coordenadas, radii_visuales, encuadre)
    return png, svg


def generar_mapa_burbujas(top_100_palabras):
    """Solo el PNG en base64 (compatibilidad); cadena vacía si no hay palabras."""
    return generar_mapas_burbujas(top_100_palabras)[0]
