"""Soporte para subir el chat exportado directamente como .zip.

WhatsApp exporta un .zip (en iPhone siempre, y en Android cuando se elige
"Incluir archivos") que contiene el .txt del chat más, a veces, fotos, audios,
etc. Aquí se abre el zip SIN cargarlo entero en memoria y se lee únicamente el
.txt del chat: el resto de archivos del zip ni se descomprimen.
"""

import zipfile

FIRMA_ZIP = b'PK\x03\x04'


class ErrorZip(Exception):
    """Error con un mensaje apto para mostrárselo al usuario."""

    def __init__(self, mensaje, status_code=400):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.status_code = status_code


def es_zip(fileobj):
    """True si el archivo (seekable) empieza con la firma de un .zip. Deja el
    cursor al principio."""
    cabecera = fileobj.read(4)
    fileobj.seek(0)
    return cabecera == FIRMA_ZIP


def extraer_txt_de_zip(fileobj, limite_bytes):
    """Devuelve los bytes del .txt del chat contenido en el zip.

    `limite_bytes` es el tamaño máximo permitido del .txt ya descomprimido;
    se comprueba ANTES de descomprimir y también mientras se lee, para
    protegerse de zips malintencionados (zip bombs)."""
    try:
        zf = zipfile.ZipFile(fileobj)
    except zipfile.BadZipFile:
        raise ErrorZip("No se ha podido abrir el archivo .zip: parece estar dañado o incompleto. "
                       "Vuelve a exportar el chat e inténtalo de nuevo.")

    with zf:
        candidatos = [
            info for info in zf.infolist()
            if not info.is_dir()
            and info.filename.lower().endswith('.txt')
            and not info.filename.startswith('__MACOSX/')
            and not info.filename.rsplit('/', 1)[-1].startswith('._')
        ]
        if not candidatos:
            raise ErrorZip("El .zip no contiene ningún archivo .txt de chat. Asegúrate de subir "
                           "el .zip tal cual lo exportó WhatsApp.")

        # Si hubiera varios .txt, el del chat es el más grande.
        elegido = max(candidatos, key=lambda i: i.file_size)

        if elegido.file_size > limite_bytes:
            raise ErrorZip(
                f"El chat dentro del .zip pesa más de {limite_bytes // (1024 * 1024)}MB y este servidor "
                f"no tiene memoria suficiente para procesarlo de una vez. Prueba a exportar un rango "
                f"de fechas más corto, o a dividir el chat en varias exportaciones.",
                status_code=413,
            )

        try:
            with zf.open(elegido) as f:
                # Se lee con tope por si la cabecera del zip mintiera sobre el tamaño real
                contenido = f.read(limite_bytes + 1)
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError):
            raise ErrorZip("No se ha podido leer el chat dentro del .zip (puede estar dañado o "
                           "protegido con contraseña).")

        if len(contenido) > limite_bytes:
            raise ErrorZip("El chat dentro del .zip es demasiado grande para procesarlo.", status_code=413)

        return contenido
