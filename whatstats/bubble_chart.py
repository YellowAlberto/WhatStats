"""Algoritmo de empaquetado de círculos y generación del mapa de conceptos
(bubble chart) que se muestra en la web como una imagen PNG en base64."""

import io
import numpy as np
import matplotlib
matplotlib.use('Agg')  # Evita bloqueos en servidores web
import matplotlib.pyplot as plt
from matplotlib import patheffects
import seaborn as sns


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


def generar_mapa_burbujas(top_100_palabras):
    """Dibuja el mapa de conceptos (bubble chart) a partir de un DataFrame con
    columnas 'Palabra' y 'Frecuencia' (las 100 palabras más repetidas del
    chat) y devuelve la imagen PNG codificada en base64. Si el DataFrame está
    vacío, devuelve una cadena vacía."""
    import base64

    g6_base64 = ""
    if top_100_palabras.empty:
        return g6_base64

    radii_base = np.sqrt(top_100_palabras['Frecuencia'].values)
    escala_visual = 25.0 / radii_base.max()
    radii_visuales = radii_base * escala_visual
    coordenadas = empaquetar_circulos(radii_visuales)

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
    lim = coordenadas[:, 0].min() - radii_visuales.max() * 1.2, coordenadas[:, 0].max() + radii_visuales.max() * 1.2
    ax_mpl.set_xlim(lim[0], lim[1])
    ax_mpl.set_ylim(coordenadas[:, 1].min() - radii_visuales.max() * 1.2, coordenadas[:, 1].max() + radii_visuales.max() * 1.2)
    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=140, facecolor='#1E293B', edgecolor='none')
    buf.seek(0)
    g6_base64 = base64.b64encode(buf.getvalue()).decode('utf-8')
    plt.close(fig_mpl)

    return g6_base64
