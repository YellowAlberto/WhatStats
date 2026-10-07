"""Perfiles de "estilo/mood" de cada integrante del grupo.

No es un análisis de sentimiento con IA: se miden señales sencillas de CÓMO
escribe cada persona (risas, cariño, quejas, intensidad, preguntas, longitud,
ráfagas de mensajes y horario) y se COMPARAN con la media del grupo. Cada
persona recibe la etiqueta del rasgo en el que más destaca respecto a los demás.

Todo se calcula en el servidor con expresiones regulares: el texto de los
mensajes nunca sale de él (a la página solo llegan la etiqueta y su explicación).
"""

import re

# Mínimo de mensajes de texto para describir a alguien (con menos, saldría ruido)
MIN_MENSAJES = 50
# A partir de cuántas veces la media del grupo se considera que "destaca"
UMBRAL_DESTACA = 1.3

# --- Patrones (se aplican sobre el mensaje en minúsculas, salvo MAYUSCULAS) ---
_RISAS = re.compile(
    r"(?:ja|je|ji|jo){2,}|\bha(?:ha)+|\bx+d+\b|\bjs(?:js)+|\bkek|\blol\b|\blmao\b|[😂🤣💀😹😆]"
)
_CARINO = re.compile(
    r"te quiero|te amo|gracias|\bcrack\b|\bmaquin[ae]\b|\bcampe[oó]n|cari[ñn]o|\bamor\b|\bguap[oa]|"
    r"\bbonit[oa]|\bpreciosa?\b|\btq+\b|\bgenial\b|[❤♥💕💖💗💓💞💘😍🥰😘🫶💜💙💚🧡💛🤍🤗]"
)
_QUEJA = re.compile(
    r"\bodio\b|\bharto\b|\bharta\b|\basco\b|\bputo\b|\bputa\b|\bmierda\b|\bjoder\b|\bco[ñn]o\b|\brabia\b|"
    r"\bpaso de\b|\bno puedo m[aá]s\b|\bpesad[oa]s?\b|\baburrid[oa]\b|\bfatal\b|\bhorrible\b|\bcabr[oó]n|"
    r"\bgilipollas\b|\bidiota\b|\bimb[eé]cil\b|\bqu[eé] pereza\b|[😡🤬😤🙄😒😠👎]"
)
_ELONGADO = re.compile(r"([a-záéíóúñ])\1{3,}")
_MAYUSCULAS = re.compile(r"\b[A-ZÁÉÍÓÚÑ]{4,}\b")

# Suelo de la media del grupo por señal: evita que una media casi nula dispare
# el ratio (p. ej. un grupo muy educado donde 4% de quejas parecería "20 veces más").
_SUELO = {
    "risas": 0.05, "cariño": 0.03, "queja": 0.02, "intensidad": 0.05,
    "preguntas": 0.08, "rafaga": 0.10, "nocturno": 0.05,
}
# Un valor absoluto mínimo para que una señal pueda "ganar" (aunque supere la media)
_MINIMO_ABS = {
    "risas": 0.04, "cariño": 0.03, "queja": 0.02, "intensidad": 0.05,
    "preguntas": 0.10, "rafaga": 0.12, "nocturno": 0.15,
}

# (emoji, título, plantilla de la explicación)
_PERFILES = {
    "risas":      ("😂", "El risueño",         "{pct} de sus mensajes llevan risas; la media del grupo es {media}."),
    "cariño":     ("🥰", "El cariñoso",        "{pct} de sus mensajes tienen cariño (corazones, gracias, piropos); la media del grupo es {media}."),
    "queja":      ("😤", "El gruñón",          "{pct} de sus mensajes son quejas o protestas; la media del grupo es {media}."),
    "intensidad": ("🔥", "El intenso",         "{pct} de sus mensajes llevan exclamaciones, MAYÚSCULAS o letras alargadas; la media del grupo es {media}."),
    "preguntas":  ("🤔", "El preguntón",       "{pct} de sus mensajes son preguntas; la media del grupo es {media}."),
    "longitud":   ("📜", "El ensayista",       "Sus mensajes miden {valor} caracteres de media; la media del grupo es {media}."),
    "rafaga":     ("⚡", "El ametrallador",    "{pct} de sus mensajes son ráfagas (seguidos de otro suyo en menos de un minuto); la media del grupo es {media}."),
    "nocturno":   ("🌙", "El nocturno",        "{pct} de sus mensajes son de madrugada (de 0h a 5h); la media del grupo es {media}."),
}


def _min(clave):
    return f"{_MINIMO_ABS[clave] * 100:.0f}%"


_FACTOR = f"{UMBRAL_DESTACA:.1f}".replace(".", ",")

# Catálogo que se enseña en la web (botón de información del modal). Se genera
# a partir de las mismas constantes que usa el cálculo, para que no se desincronice.
CATALOGO_PERFILES = [
    {"emoji": _PERFILES["risas"][0], "titulo": _PERFILES["risas"][1],
     "criterio": f"Cuenta los mensajes con risas (jaja, jeje, xd, lol, 😂, 🤣, 💀…). Se lo lleva quien ríe al menos {_FACTOR} veces más que la media del grupo y en al menos el {_min('risas')} de sus mensajes."},
    {"emoji": _PERFILES["cariño"][0], "titulo": _PERFILES["cariño"][1],
     "criterio": f"Cuenta los mensajes con corazones y caras de cariño, \"te quiero\", \"gracias\", \"crack\", piropos… Requiere superar {_FACTOR} veces la media del grupo y al menos el {_min('cariño')} de sus mensajes."},
    {"emoji": _PERFILES["queja"][0], "titulo": _PERFILES["queja"][1],
     "criterio": f"Cuenta los mensajes con quejas, enfado o palabrotas (\"harto\", \"qué asco\", 😡, 🙄…). Requiere superar {_FACTOR} veces la media del grupo y al menos el {_min('queja')} de sus mensajes."},
    {"emoji": _PERFILES["intensidad"][0], "titulo": _PERFILES["intensidad"][1],
     "criterio": f"Cuenta los mensajes con varias exclamaciones (!!), palabras en MAYÚSCULAS de 4 o más letras o letras alargadas (\"nooooo\"). Requiere superar {_FACTOR} veces la media del grupo y al menos el {_min('intensidad')} de sus mensajes."},
    {"emoji": _PERFILES["preguntas"][0], "titulo": _PERFILES["preguntas"][1],
     "criterio": f"Cuenta los mensajes que llevan un signo de interrogación. Requiere superar {_FACTOR} veces la media del grupo y al menos el {_min('preguntas')} de sus mensajes."},
    {"emoji": _PERFILES["longitud"][0], "titulo": _PERFILES["longitud"][1],
     "criterio": f"Mira cuántos caracteres tienen sus mensajes de media. Requiere superar {_FACTOR} veces la media del grupo y escribir al menos 40 caracteres por mensaje."},
    {"emoji": _PERFILES["rafaga"][0], "titulo": _PERFILES["rafaga"][1],
     "criterio": f"Cuenta los mensajes que llegan menos de un minuto después de otro suyo (escribe en ráfagas). Requiere superar {_FACTOR} veces la media del grupo y al menos el {_min('rafaga')} de sus mensajes."},
    {"emoji": _PERFILES["nocturno"][0], "titulo": _PERFILES["nocturno"][1],
     "criterio": f"Cuenta los mensajes escritos entre las 0:00 y las 5:59. Requiere superar {_FACTOR} veces la media del grupo y al menos el {_min('nocturno')} de sus mensajes."},
    {"emoji": "😌", "titulo": "El equilibrado",
     "criterio": f"Lo recibe quien no supera {_FACTOR} veces la media del grupo en ningún rasgo: escribe de forma muy parecida al resto."},
    {"emoji": "🫥", "titulo": "Sin perfil todavía",
     "criterio": f"Lo recibe quien tiene menos de {MIN_MENSAJES} mensajes de texto (no hay datos suficientes) o, si en el grupo no hay al menos dos personas con suficientes mensajes, porque no hay con quién compararlas."},
]


def _pct(x):
    """0.1234 -> '12,3%' (formato español)."""
    return f"{x * 100:.1f}".replace(".", ",") + "%"


def _num(x):
    return f"{x:.0f}"


def _señales_por_autor(df_texto, df_total):
    """Devuelve {autor: {señal: valor, 'n': mensajes}} para quienes llegan al mínimo."""
    # Ráfaga: mensaje cuyo anterior es del mismo autor y llegó hace <= 1 minuto
    es_rafaga = (df_total["Autor"] == df_total["Autor_Anterior"]) & (df_total["Tiempo_Dif_Min"] <= 1)
    rafaga_por_indice = es_rafaga.reindex(df_texto.index, fill_value=False)

    originales = df_texto["Mensaje"].astype(str)
    minusculas = originales.str.lower()

    marcas = {
        "risas": minusculas.map(lambda t: bool(_RISAS.search(t))),
        "cariño": minusculas.map(lambda t: bool(_CARINO.search(t))),
        "queja": minusculas.map(lambda t: bool(_QUEJA.search(t))),
        "intensidad": originales.map(
            lambda t: ("!!" in t) or bool(_ELONGADO.search(t.lower())) or bool(_MAYUSCULAS.search(t))
        ),
        "preguntas": originales.str.contains("?", regex=False),
        "rafaga": rafaga_por_indice,
        "nocturno": df_texto["Hora_Int"].between(0, 5),
    }

    base = df_texto[["Autor"]].copy()
    for nombre, serie in marcas.items():
        base[nombre] = serie.astype(float)
    base["longitud"] = originales.str.len().astype(float)

    agrupado = base.groupby("Autor")
    medias = agrupado.mean(numeric_only=True)
    conteo = agrupado.size()

    resultado = {}
    for autor in medias.index:
        fila = {k: float(medias.at[autor, k]) for k in medias.columns}
        fila["n"] = int(conteo[autor])
        resultado[autor] = fila
    return resultado


def calcular_perfiles(df_texto, df_total):
    """Calcula el perfil de cada autor.

    `df_texto`: mensajes de texto real (sin multimedia ni eliminados), con las
    columnas Autor, Mensaje y Hora_Int. `df_total`: todos los mensajes, con
    Autor, Autor_Anterior y Tiempo_Dif_Min (el mismo índice que `df_texto`).

    Devuelve {autor: {"emoji", "titulo", "explicacion", "secundario"}}.
    """
    señales = _señales_por_autor(df_texto, df_total)
    elegibles = {a: s for a, s in señales.items() if s["n"] >= MIN_MENSAJES}

    perfiles = {}
    sin_datos = {
        "emoji": "🫥", "titulo": "Sin perfil todavía",
        "explicacion": f"Con menos de {MIN_MENSAJES} mensajes de texto no hay datos suficientes para describir su estilo.",
        "secundario": None,
    }
    for autor in señales:
        if autor not in elegibles:
            perfiles[autor] = dict(sin_datos)

    if len(elegibles) < 2:
        # Sin con quién compararse, un perfil relativo no tiene sentido
        for autor in elegibles:
            perfiles[autor] = {
                "emoji": "🫥", "titulo": "Sin perfil todavía",
                "explicacion": "Hacen falta al menos dos personas con suficientes mensajes para poder compararlas.",
                "secundario": None,
            }
        return perfiles

    # Media del grupo (media de las medias individuales: quien más escribe no pesa más)
    nombres_senal = list(_PERFILES.keys())
    media_grupo = {k: sum(s[k] for s in elegibles.values()) / len(elegibles) for k in nombres_senal}

    for autor, s in elegibles.items():
        puntuaciones = []
        for k in nombres_senal:
            if k == "longitud":
                ratio = s[k] / media_grupo[k] if media_grupo[k] > 0 else 0
                valido = s[k] >= 40  # un mensaje "largo" de verdad
            else:
                ratio = s[k] / max(media_grupo[k], _SUELO[k])
                valido = s[k] >= _MINIMO_ABS[k]
            if valido and ratio >= UMBRAL_DESTACA:
                puntuaciones.append((ratio, k))
        puntuaciones.sort(reverse=True)

        if not puntuaciones:
            perfiles[autor] = {
                "emoji": "😌", "titulo": "El equilibrado",
                "explicacion": "No destaca especialmente en ningún rasgo: escribe de forma muy parecida a la media del grupo.",
                "secundario": None,
            }
            continue

        ratio, clave = puntuaciones[0]
        emoji, titulo, plantilla = _PERFILES[clave]
        if clave == "longitud":
            explicacion = plantilla.format(valor=_num(s[clave]), media=_num(media_grupo[clave]))
        else:
            explicacion = plantilla.format(pct=_pct(s[clave]), media=_pct(media_grupo[clave]))

        secundario = None
        if len(puntuaciones) > 1:
            _, clave2 = puntuaciones[1]
            secundario = {"emoji": _PERFILES[clave2][0], "titulo": _PERFILES[clave2][1]}

        perfiles[autor] = {"emoji": emoji, "titulo": titulo, "explicacion": explicacion, "secundario": secundario}

    return perfiles
