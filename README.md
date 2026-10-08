<div align="center">

<img src="static/favicon.svg" alt="Logo de WhatsInChat" width="96">

# WhatsInChat

**Descubre qué esconde el chat de tu grupo.**
Sube la exportación de un chat de WhatsApp y obtén al instante rankings, horas punta, palabras favoritas y el perfil de cada miembro. Gratis, sin registro y sin guardar tu chat.

[**Probar la web →**](https://whatsinchat.onrender.com) · [Ver un ejemplo](https://whatsinchat.onrender.com/ejemplo)

</div>

---

## ¿Qué hace?

Subes el `.zip` o el `.txt` que exporta WhatsApp y la web te devuelve un panel interactivo con la radiografía del grupo:

| | |
|---|---|
| **Quién habla más** | Ranking de miembros con podio y el porcentaje de cada uno sobre el total. |
| **Cuándo se habla** | Reloj de 24 horas, mapa de calor día × hora y evolución por años. |
| **Cómo se llevan** | Matriz de afinidad (quién responde a quién), tiempos de respuesta y mensajes que se quedan "en visto". |
| **Qué se dice** | Palabras clave a tu elección, mapa de conceptos en burbujas y ranking de emojis. |
| **Cómo escribe cada uno** | Perfiles de estilo: el risueño, el cariñoso, el gruñón, el intenso, el nocturno… con la explicación de por qué se asigna cada uno. |
| **Multimedia y más** | Fotos, vídeos y audios enviados, mensajes eliminados y longitud media de los mensajes. |

### Resumen para compartir

Un botón crea un **carrusel de 6 imágenes** (portada, podio, hora y día, vocabulario, premios del grupo y día récord) listo para descargar o compartir en redes. Se genera en tu navegador y solo lleva números y nombres, nunca mensajes.

### Y además

- Modo claro y oscuro.
- Funciona en móvil.
- Botón **"Ver un ejemplo"** con un chat ficticio, para probar sin subir nada.
- Palabras clave personalizables: escribe una palabra, pulsa Intro y se añade a la lista.

## Privacidad

Tu chat **no se guarda ni se comparte**. Se procesa en memoria en el momento de analizarlo y se descarta al terminar. No se envía a ningún servicio externo ni a ningún modelo de IA: los perfiles de estilo se calculan con reglas sencillas sobre el texto, no con aprendizaje automático. Las imágenes del resumen se dibujan en tu propio navegador.

## Cómo exportar un chat de WhatsApp

**Android:** abre el chat → tres puntos → *Más* → *Exportar chat* → **Sin archivos** → guarda el fichero.
**iPhone:** abre el chat → toca el nombre del grupo → *Exportar chat* → **Sin multimedia**.

Elegir "sin archivos" hace que el chat pese poco y se analice más rápido.

## Tecnologías

- **Backend:** [FastAPI](https://fastapi.tiangolo.com/) y [Jinja2](https://jinja.palletsprojects.com/)
- **Análisis de datos:** [pandas](https://pandas.pydata.org/) y NumPy
- **Gráficas:** [Plotly](https://plotly.com/python/) (interactivas), matplotlib y seaborn
- **Informe PDF:** ReportLab
- **Frontend:** HTML, CSS propio y [Tailwind CSS](https://tailwindcss.com/), JavaScript sin dependencias
- **Iconos:** set de iconos SVG propio (`static/iconos.svg`)
- **Despliegue:** [Render](https://render.com/)

## Ejecutarlo en local

Necesitas Python 3.10 o superior.

```bash
# 1. Clona el repositorio
git clone https://github.com/YellowAlberto/WhatsInChat.git
cd WhatsInChat

# 2. Crea y activa un entorno virtual
python -m venv venv
# Windows (PowerShell):
.\venv\Scripts\Activate.ps1
# macOS / Linux:
source venv/bin/activate

# 3. Instala las dependencias
pip install -r requirements.txt

# 4. Arranca el servidor
python -m uvicorn main:app --reload
```

Abre <http://127.0.0.1:8000> en el navegador. Hay que lanzar el comando desde la carpeta donde está `main.py`.

> El CSS de Tailwind ya está compilado en `static/css/tailwind.css`, así que **no necesitas Node** para ejecutar la web. Solo lo necesitarías si cambias las clases de Tailwind de las plantillas y quieres volver a generarlo (`npm install` y `npm run build:css`).

## Estructura del proyecto

```
main.py                 Punto de entrada de la aplicación
WhatsInChat/            Lógica del análisis
  routes.py             Rutas web y construcción de los resultados
  chat_parser.py        Lectura del .txt exportado por WhatsApp
  chart_style.py        Estilo común de las gráficas
  perfiles.py           Perfiles de estilo de cada miembro
  demo_chat.py          Chat ficticio para el botón "Ver un ejemplo"
  pdf_*.py              Generación del informe PDF
templates/              Portada, resultados y página de error
static/                 CSS, iconos y favicon
```

## Despliegue en Render

1. Crea un *Web Service* en Render conectado a este repositorio.
2. **Build Command:** `pip install -r requirements.txt`
3. **Start Command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`

No hacen falta variables de entorno.

> En el plan gratuito, el servicio se "duerme" tras un rato sin visitas y la primera carga puede tardar unos segundos. Hay un límite de 25 MB por archivo para no quedarse sin memoria.

## Ideas para el futuro

- Soporte para chats exportados en inglés y otros idiomas.
- Filtrar el análisis por fechas.
- Más perfiles y datos curiosos.
- Imagen de previsualización al compartir el enlace.

## Aviso

WhatsInChat es un proyecto independiente y **no está afiliado, patrocinado ni respaldado por WhatsApp ni por Meta**. "WhatsApp" es una marca registrada de sus propietarios y se menciona aquí solo para indicar de qué aplicación proceden los chats que se analizan.

## Licencia

Por definir.
