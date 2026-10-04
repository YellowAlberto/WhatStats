import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

# --- Cargar variables de entorno desde un archivo .env (si existe) ---
# FastAPI/uvicorn NO leen el .env automáticamente: hay que cargarlo explícitamente
# con python-dotenv. Se deja preparado por si en el futuro hace falta alguna
# clave/config por variable de entorno (ya no hay ninguna IA que la necesite).
try:
    from dotenv import load_dotenv
    load_dotenv()  # busca un archivo .env en el directorio de trabajo (o superiores)
except ImportError:
    pass

from whatstats.routes import router, manejador_errores_generico


app = FastAPI(title="Analizador de WhatsApp Completo")

app.mount("/static", StaticFiles(directory="static"), name="static")

os.makedirs("static", exist_ok=True)

app.add_exception_handler(Exception, manejador_errores_generico)
app.include_router(router)
