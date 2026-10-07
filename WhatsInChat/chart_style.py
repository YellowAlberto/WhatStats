"""Estilo visual común de las gráficas interactivas (Plotly) de la web.

Todas las gráficas se construyen con estas funciones para que compartan paleta,
tipografía, márgenes y tooltips:

- Tipos de gráfica elegidos según el dato: reloj radial para las horas, podio
  en el ranking, "piruletas" (punto + palito) para conteos pequeños, mapas de
  calor para cruces.
- Un único color de marca (teal) y un color de acento (ámbar) que solo se usa
  para resaltar el valor máximo de cada gráfica.
- Sin cuadrículas, bordes ni barras de color: etiquetas directas sobre las
  barras y títulos cortos alineados a la izquierda.
- Fondo transparente y colores neutros: el fondo lo pone la tarjeta de la web.
  Los colores de texto y las escalas de los mapas de calor se ajustan al modo
  claro/oscuro con JavaScript (ver `aplicarTemaGraficas` en resultados.html).
"""

import plotly.graph_objects as go
import plotly.io as pio

COLOR_PRINCIPAL = "#14b8a6"   # teal-500
COLOR_ACENTO = "#f59e0b"      # amber-500, solo para resaltar el máximo
COLOR_PODIO = ("#f59e0b", "#94a3b8", "#c2763a")  # oro, plata, bronce
COLOR_TEXTO = "#64748b"       # slate-500: legible en claro y oscuro hasta que JS lo ajusta
FUENTE = ("Inter, ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto, "
          "'Helvetica Neue', Arial, sans-serif")

# Escala de los mapas de calor (opaca: así el texto de las celdas se autocontrasta).
# JS cambia entre estas dos según el tema: mantener sincronizadas con resultados.html.
ESCALA_CALOR_OSCURO = [[0, "#17303c"], [0.5, "#0d9488"], [1, "#5eead4"]]
ESCALA_CALOR_CLARO = [[0, "#f0fdfa"], [0.5, "#5eead4"], [1, "#0f766e"]]

CONFIG_PLOTLY = {"displayModeBar": False, "responsive": True}


def a_html(fig, div_id):
    """Convierte la figura en el fragmento HTML que se incrusta en la plantilla."""
    return pio.to_html(fig, full_html=False, include_plotlyjs=False, div_id=div_id, config=CONFIG_PLOTLY)


def _colores_destacando_maximo(valores):
    maximo = max(valores) if len(valores) else 0
    return [COLOR_ACENTO if (maximo > 0 and v == maximo) else COLOR_PRINCIPAL for v in valores]


def _rango_con_aire(valores, factor=1.18):
    maximo = max(valores) if len(valores) else 0
    return [0, maximo * factor] if maximo > 0 else None


def _aplicar_estilo(fig, titulo, subtitulo=None, altura=None, margen=None):
    titulo_cfg = dict(text=titulo, x=0, xanchor="left", font=dict(size=18, family=FUENTE))
    if subtitulo:
        titulo_cfg["subtitle"] = dict(text=subtitulo, font=dict(size=12, color=COLOR_TEXTO))
    fig.update_layout(
        template="simple_white",
        title=titulo_cfg,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FUENTE, color=COLOR_TEXTO, size=13),
        margin=margen or dict(t=90 if subtitulo else 60, b=24, l=20, r=20),
        hoverlabel=dict(bgcolor="#0f172a", bordercolor=COLOR_PRINCIPAL,
                        font=dict(family=FUENTE, color="#f1f5f9", size=13)),
        showlegend=False,
        bargap=0.35,
    )
    if altura:
        fig.update_layout(height=altura)
    return fig


def barras_horizontales(df, col_valor, col_categoria, titulo, subtitulo=None, texto=None,
                        texto_formato="%{text:,}", hover=None, customdata=None, altura=None,
                        tamano_etiqueta_y=None, margen_der=70, podio=False):
    """Barras horizontales. `df` debe venir ya ordenado de menor a mayor
    (así la barra más larga queda arriba). La barra máxima se resalta en ámbar.

    Con `podio=True` las tres barras más largas se colorean en oro, plata y
    bronce (sin emojis de medalla)."""
    valores = df[col_valor].tolist()
    categorias = df[col_categoria].tolist()
    if texto is None:
        texto = valores
    if hover is None:
        hover = "<b>%{y}</b><br>%{x:,}<extra></extra>"
    colores = _colores_destacando_maximo(valores)

    if podio:
        n = len(categorias)
        for idx, color in {n - 1: COLOR_PODIO[0], n - 2: COLOR_PODIO[1], n - 3: COLOR_PODIO[2]}.items():
            if idx >= 0:
                colores[idx] = color

    fig = go.Figure(go.Bar(
        x=valores, y=categorias, orientation="h",
        text=texto, texttemplate=texto_formato, textposition="outside", cliponaxis=False,
        textfont=dict(size=12),
        customdata=customdata, hovertemplate=hover,
        marker=dict(color=colores, cornerradius=6),
    ))
    _aplicar_estilo(fig, titulo, subtitulo, altura,
                    margen=dict(t=90 if subtitulo else 60, b=24, l=20, r=margen_der))
    fig.update_xaxes(visible=False, range=_rango_con_aire(valores))
    # tickmode lineal con dtick=1 obliga a Plotly a escribir TODAS las etiquetas
    # (si no, con etiquetas grandes como los emojis se salta una de cada dos).
    fig.update_yaxes(type="category", showline=False, showgrid=False, ticks="",
                     ticksuffix="  ", automargin=True, tickmode="linear", tick0=0, dtick=1,
                     tickfont=dict(size=tamano_etiqueta_y) if tamano_etiqueta_y else None)
    return fig


def barras_verticales(df, col_categoria, col_valor, titulo, subtitulo=None, hover=None, altura=None):
    """Barras verticales (p. ej. mensajes por año). La barra máxima en ámbar."""
    valores = df[col_valor].tolist()
    categorias = df[col_categoria].astype(str).tolist()
    if hover is None:
        hover = "<b>%{x}</b><br>%{y:,}<extra></extra>"

    fig = go.Figure(go.Bar(
        x=categorias, y=valores,
        text=valores, texttemplate="%{text:,}", textposition="outside", cliponaxis=False,
        textfont=dict(size=12), hovertemplate=hover,
        marker=dict(color=_colores_destacando_maximo(valores), cornerradius=6),
    ))
    _aplicar_estilo(fig, titulo, subtitulo, altura)
    fig.update_xaxes(type="category", showline=False, showgrid=False, ticks="")
    fig.update_yaxes(visible=False, range=_rango_con_aire(valores, 1.2))
    return fig


def reloj_actividad_horaria(df, titulo, subtitulo=None):
    """Reloj radial de 24 horas (columnas 'Hora' y 'Mensajes'): cada barra es una
    hora, empezando por las 0h arriba y avanzando en el sentido de las agujas
    del reloj. La hora pico se resalta en ámbar."""
    horas = df["Hora"].tolist()
    valores = df["Mensajes"].tolist()
    maximo = max(valores) if valores else 0
    gris = "rgba(100,116,139,0.22)"

    fig = go.Figure(go.Barpolar(
        r=valores, theta=[h * 15 + 7.5 for h in horas], width=[13.5] * len(horas),
        customdata=horas,
        marker=dict(color=_colores_destacando_maximo(valores), line=dict(width=0)),
        hovertemplate="<b>%{customdata}:00 h</b><br>%{r:,} mensajes<extra></extra>",
    ))
    _aplicar_estilo(fig, titulo, subtitulo, margen=dict(t=90 if subtitulo else 60, b=30, l=50, r=50))
    fig.update_layout(polar=dict(
        bgcolor="rgba(0,0,0,0)",
        radialaxis=dict(showticklabels=False, showline=False, ticks="", gridcolor=gris,
                        range=[0, maximo * 1.05] if maximo > 0 else None),
        angularaxis=dict(direction="clockwise", rotation=90, showline=False, ticks="", gridcolor=gris,
                         tickmode="array", tickvals=[h * 15 for h in range(0, 24, 3)],
                         ticktext=[f"{h}h" for h in range(0, 24, 3)]),
    ))
    return fig


def piruletas(df, col_valor, col_categoria, titulo, subtitulo=None, hover=None, altura=None,
              formato="{:,}", margen_der=70):
    """Gráfica "piruleta": un punto al final de un palito fino por categoría.
    Queda más ligera que las barras cuando hay muchos ceros o valores pequeños.
    `df` ordenado de menor a mayor; el máximo va en ámbar."""
    valores = df[col_valor].tolist()
    categorias = df[col_categoria].tolist()
    colores = _colores_destacando_maximo(valores)
    if hover is None:
        hover = "<b>%{y}</b><br>%{x:,}<extra></extra>"

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=valores, y=categorias, orientation="h", width=0.07,
        marker=dict(color=colores), hoverinfo="skip",
    ))
    fig.add_trace(go.Scatter(
        x=valores, y=categorias, mode="markers+text",
        text=[formato.format(v) for v in valores], textposition="middle right",
        textfont=dict(size=12), cliponaxis=False,
        marker=dict(color=colores, size=15, line=dict(width=0)),
        hovertemplate=hover,
    ))
    _aplicar_estilo(fig, titulo, subtitulo, altura,
                    margen=dict(t=90 if subtitulo else 60, b=24, l=20, r=margen_der))
    fig.update_xaxes(visible=False, range=_rango_con_aire(valores, 1.15))
    fig.update_yaxes(type="category", showline=False, showgrid=False, ticks="",
                     ticksuffix="  ", automargin=True, tickmode="linear", tick0=0, dtick=1)
    return fig


def mapa_calor(z, x, y, titulo, hover, subtitulo=None, texto=None, altura=None, margen=None,
               titulo_x=None, dtick_x=None, tickangle_x=None):
    """Mapa de calor sin barra de color, con celdas separadas y filas de arriba
    a abajo en el orden recibido."""
    fig = go.Figure(go.Heatmap(
        z=z, x=x, y=y, colorscale=ESCALA_CALOR_OSCURO, showscale=False,
        xgap=3, ygap=3, hoverongaps=False, hovertemplate=hover,
        text=texto, texttemplate="%{text}" if texto is not None else None,
        textfont=dict(size=11),
    ))
    _aplicar_estilo(fig, titulo, subtitulo, altura, margen)
    xaxis = dict(showline=False, showgrid=False, ticks="", automargin=True)
    if titulo_x:
        xaxis["title"] = dict(text=titulo_x, font=dict(size=12))
    if dtick_x:
        xaxis.update(tickmode="linear", tick0=0, dtick=dtick_x)
    if tickangle_x is not None:
        xaxis["tickangle"] = tickangle_x
    fig.update_xaxes(**xaxis)
    fig.update_yaxes(autorange="reversed", showline=False, showgrid=False, ticks="", automargin=True)
    return fig
