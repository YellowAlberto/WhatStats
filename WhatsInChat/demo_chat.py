"""Chat de ejemplo (totalmente ficticio) para el botón "Ver un ejemplo" de la portada.

Genera, con una semilla fija, un chat de WhatsApp inventado en el mismo formato
que exporta Android ("13/03/2025, 22:15 - Lucía: texto"). Así quien dude de
subir su chat real puede ver el análisis completo sin subir nada.

Las fechas usan solo los días 13 a 28 de cada mes a propósito: así no hay
ambigüedad entre día/mes al leerlas.
"""

import random
from datetime import datetime, timedelta

SEMILLA = 2025

# (nombre, peso de participación, frases características)
_MIEMBROS = [
    ("Lucía", 1.3, ["jajajaja qué fuerte", "jajaja me muero 😂", "xd no puedo", "🤣🤣🤣", "jajaja el vídeo es genial", "jaja ya ves", "ay jajaja 💀"]),
    ("Marcos", 1.0, ["qué asco de día", "estoy harto de esto", "joder qué pereza", "me aburro un montón", "vaya mierda de lunes", "odio madrugar 🙄", "fatal todo"]),
    ("Irene", 1.1, ["gracias crack ❤️", "te quiero mucho 🥰", "qué guapa la foto 😍", "sois los mejores 💕", "gracias por venir ❤️", "me encantáis 🫶"]),
    ("Dani", 1.2, ["VAMOOOOS!!", "SIIIIII!!!", "NOOOOO qué dices!!", "increíble!!!", "QUÉ BUENO!!", "vamooooos equipo!!"]),
    ("Sergio", 1.0, ["¿a qué hora quedamos?", "¿quién se apunta?", "¿dónde cenamos?", "¿alguien sabe si abre?", "¿y mañana qué hacemos?", "¿llevo algo?"]),
    ("Paula", 0.8, ["Os cuento con calma lo que pasó ayer: llegué tarde porque el autobús se averió y tuve que ir andando casi media hora, y cuando por fin llegué ya habían empezado a cenar, así que me senté como pude y pedí lo mismo que todos.",
                    "Para el viaje propongo que reservemos pronto los billetes porque suben mucho de precio a última hora, y que repartamos los gastos entre todos desde el principio para no liarnos luego con las cuentas."]),
    ("Nacho", 0.7, ["no puedo dormir", "qué hacéis despiertos", "otra noche en vela", "buenas noches a los que duermen", "me voy a la cama ya (mentira)"]),
]

_NEUTRAS = [
    "vale", "ok", "ahora voy", "luego hablamos", "estoy en casa", "ya llego", "perfecto", "de acuerdo",
    "mañana nos vemos", "la peli de anoche estuvo bien", "el finde nos vamos a la playa", "cena en mi casa el viernes",
    "he visto el partido", "qué tal el examen", "hoy hace mucho calor", "nos vemos en el bar de siempre",
    "me paso por la tienda", "alguien tiene el enlace", "ya está reservado", "en media hora salgo",
    "la playa estaba llena", "el café de la esquina", "buen plan para el sábado", "hay que organizar la cena",
]

_MULTIMEDIA = "<Multimedia omitido>"
_ELIMINADO = "Se eliminó este mensaje"

# Peso de cada hora para las conversaciones "normales" (más actividad por la tarde-noche)
_HORAS = list(range(8, 24))
_PESOS_HORA = [1, 1, 2, 2, 3, 3, 2, 2, 3, 4, 5, 6, 7, 7, 5, 3]


def _dias_validos(inicio, fin):
    dias = []
    d = inicio
    while d <= fin:
        if 13 <= d.day <= 28:
            dias.append(d)
        d += timedelta(days=1)
    return dias


def _texto_de(rnd, nombre, frases):
    """Cada miembro usa su estilo característico en buena parte de sus mensajes."""
    if rnd.random() < 0.58:
        return rnd.choice(frases)
    return rnd.choice(_NEUTRAS)


def generar_chat_demo():
    """Devuelve el chat de ejemplo como bytes UTF-8, listo para el parser."""
    rnd = random.Random(SEMILLA)
    nombres = [m[0] for m in _MIEMBROS]
    pesos = [m[1] for m in _MIEMBROS]
    frases = {m[0]: m[2] for m in _MIEMBROS}
    dias = _dias_validos(datetime(2025, 3, 1), datetime(2025, 8, 31))

    mensajes = []  # (datetime, autor, texto)

    # Conversaciones del día a día
    for _ in range(165):
        dia = rnd.choice(dias)
        hora = rnd.choices(_HORAS, _PESOS_HORA)[0]
        momento = dia.replace(hour=hora, minute=rnd.randint(0, 59))
        ultimo = None
        for _ in range(rnd.randint(6, 22)):
            autor = rnd.choices(nombres, pesos)[0]
            if autor == "Nacho" and rnd.random() < 0.6:
                autor = rnd.choices(nombres, pesos)[0]
            texto = _texto_de(rnd, autor, frases[autor])
            r = rnd.random()
            if r < 0.04:
                texto = _MULTIMEDIA
            elif r < 0.055:
                texto = _ELIMINADO
            mensajes.append((momento, autor, texto))
            ultimo = autor
            # Ráfagas (mensajes seguidos) o pausas más largas
            momento += timedelta(minutes=rnd.choice([0.3, 0.5, 0.7, 1, 2, 4, 7, 12]))
            # A veces el mismo autor sigue escribiendo
            if rnd.random() < 0.12 and ultimo:
                mensajes.append((momento, ultimo, _texto_de(rnd, ultimo, frases[ultimo])))
                momento += timedelta(minutes=rnd.choice([0.2, 0.4]))

    # Conversaciones de madrugada (principalmente Nacho)
    for _ in range(26):
        dia = rnd.choice(dias)
        momento = dia.replace(hour=rnd.choice([0, 1, 2, 3, 4]), minute=rnd.randint(0, 59)) + timedelta(days=1)
        for _ in range(rnd.randint(4, 10)):
            autor = "Nacho" if rnd.random() < 0.7 else rnd.choice(["Marcos", "Lucía", "Dani"])
            mensajes.append((momento, autor, _texto_de(rnd, autor, frases[autor])))
            momento += timedelta(minutes=rnd.choice([1, 2, 3, 5]))

    mensajes.sort(key=lambda m: m[0])

    lineas = []
    for momento, autor, texto in mensajes:
        # Mensajes solo en días 13-28 (los de madrugada pueden caer el día 29: se dejan, no hay ambigüedad)
        lineas.append(f"{momento.strftime('%d/%m/%Y, %H:%M')} - {autor}: {texto}")
    return ("\n".join(lineas) + "\n").encode("utf-8")
