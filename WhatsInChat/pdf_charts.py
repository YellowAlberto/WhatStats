"""Gráficas estáticas (matplotlib/seaborn) usadas solo en el informe PDF
descargable — oculto en la web por ahora, ver resultados.html.

Las gráficas del PDF se generan con matplotlib (no con Plotly/Kaleido): no
depende de ningún navegador ni subproceso externo, así que no hay popups,
cuelgues ni arranques en frío. Las gráficas INTERACTIVAS de la web siguen
siendo las de Plotly de siempre; esto solo afecta a las imágenes del PDF.
"""

import io
import matplotlib
matplotlib.use('Agg')  # Evita bloqueos en servidores web
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import seaborn as sns

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
    ax.tick_params(axis='y', pad=8)  # un poco de aire entre los nombres y las barras
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
