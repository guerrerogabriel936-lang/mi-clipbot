import os
import re
import asyncio
import threading
import subprocess
from pathlib import Path

from flask import Flask
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.request import HTTPXRequest
import imageio_ffmpeg


# =========================================================
# CONFIGURACIÓN
# =========================================================

TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise RuntimeError("BOT_TOKEN no está configurado en Render")

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

VIDEOS_DIR = "videos"
CLIPS_DIR = "clips"

os.makedirs(VIDEOS_DIR, exist_ok=True)
os.makedirs(CLIPS_DIR, exist_ok=True)


# =========================================================
# SERVIDOR WEB PARA RENDER
# =========================================================

web = Flask(__name__)


@web.route("/")
def home():
    return "🤖 MI CLIPBOT está funcionando correctamente."


@web.route("/health")
def health():
    return "OK"


def iniciar_web():
    puerto = int(os.environ.get("PORT", "10000"))

    web.run(
        host="0.0.0.0",
        port=puerto,
        debug=False,
        use_reloader=False,
    )


# =========================================================
# START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "🤖 ¡Hola! Soy MI CLIPBOT.\n\n"
        "🎬 Envíame un video y crearé 2 clips.\n"
        "📝 Prepararemos subtítulos en español."
    )


# =========================================================
# DURACIÓN
# =========================================================

def obtener_duracion(video):

    resultado = subprocess.run(
        [
            FFMPEG,
            "-i",
            video,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    texto = resultado.stderr

    encontrado = re.search(
        r"Duration:\s*(\d+):(\d+):([\d.]+)",
        texto,
    )

    if not encontrado:
        raise Exception(
            "No pude obtener la duración del video."
        )

    horas = int(encontrado.group(1))
    minutos = int(encontrado.group(2))
    segundos = float(encontrado.group(3))

    return (
        horas * 3600
        + minutos * 60
        + segundos
    )


# =========================================================
# CREAR UN CLIP
# =========================================================

def crear_clip(video, inicio, duracion, salida):

    resultado = subprocess.run(
        [
            FFMPEG,
            "-y",
            "-ss",
            str(inicio),
            "-i",
            video,
            "-t",
            str(duracion),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            salida,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    if resultado.returncode != 0:
        raise Exception(
            "FFmpeg no pudo crear el clip."
        )


# =========================================================
# CREAR LOS 2 CLIPS
# =========================================================

def crear_clips(video):

    duracion = obtener_duracion(video)

    if duracion < 4:
        raise Exception(
            "El video es demasiado corto."
        )

    mitad = duracion / 2

    clip1 = os.path.join(
        CLIPS_DIR,
        "MI_CLIP_1.mp4",
    )

    clip2 = os.path.join(
        CLIPS_DIR,
        "MI_CLIP_2.mp4",
    )

    crear_clip(
        video,
        0,
        mitad,
        clip1,
    )

    crear_clip(
        video,
        mitad,
        mitad,
        clip2,
    )

    return clip1, clip2


# =========================================================
# SUBTÍTULOS
# =========================================================
#
# Esta función deja preparada la estructura.
# La transcripción automática con Whisper se activará
# después de instalar/configurar Whisper en Render.
#

def agregar_subtitulos(clip, salida):

    # Por ahora copiamos el clip.
    # En el siguiente paso añadiremos Whisper + SRT
    # y los subtítulos españoles abajo del video.

    resultado = subprocess.run(
        [
            FFMPEG,
            "-y",
            "-i",
            clip,
            "-c",
            "copy",
            salida,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    if resultado.returncode != 0:
        raise Exception(
            "No pude preparar el video."
        )

    return salida


# =========================================================
# PROCESAR VIDEO
# =========================================================

async def procesar_video(
    update,
    archivo_telegram,
    nombre,
):

    mensaje = update.message

    video_entrada = os.path.join(
        VIDEOS_DIR,
        nombre + ".mp4",
    )

    clip1 = os.path.join(
        CLIPS_DIR,
        "MI_CLIP_1.mp4",
    )

    clip2 = os.path.join(
        CLIPS_DIR,
        "MI_CLIP_2.mp4",
    )

    clip1_final = os.path.join(
        CLIPS_DIR,
        "MI_CLIP_1_FINAL.mp4",
    )

    clip2_final = os.path.join(
        CLIPS_DIR,
        "MI_CLIP_2_FINAL.mp4",
    )

    try:

        await mensaje.reply_text(
            "⏳ Descargando tu video..."
        )

        await archivo_telegram.download_to_drive(
            video_entrada
        )

        await mensaje.reply_text(
            "🎬 Video recibido.\n\n"
            "✂️ Creando los 2 clips..."
        )

        loop = asyncio.get_running_loop()

        await loop.run_in_executor(
            None,
            crear_clips,
            video_entrada,
        )

        await mensaje.reply_text(
            "📝 Preparando los clips para "
            "los subtítulos en español..."
        )

        await loop.run_in_executor(
            None,
            agregar_subtitulos,
            clip1,
            clip1_final,
        )

        await loop.run_in_executor(
            None,
            agregar_subtitulos,
            clip2,
            clip2_final,
        )

        await mensaje.reply_text(
            "✅ ¡Los 2 clips están listos!\n\n"
            "📤 Enviándotelos..."
        )

        with open(
            clip1_final,
            "rb",
        ) as archivo1:

            await mensaje.reply_video(
                video=archivo1,
                caption="🎬 MI CLIP 1",
                read_timeout=600,
                write_timeout=600,
                connect_timeout=60,
                pool_timeout=60,
            )

        with open(
            clip2_final,
            "rb",
        ) as archivo2:

            await mensaje.reply_video(
                video=archivo2,
                caption="🎬 MI CLIP 2",
                read_timeout=600,
                write_timeout=600,
                connect_timeout=60,
                pool_timeout=60,
            )

        await mensaje.reply_text(
            "🚀 ¡Proceso terminado!\n\n"
            "▶️ La conexión con YouTube "
            "la configuraremos después."
        )

    except Exception as error:

        print(
            "ERROR:",
            repr(error),
        )

        await mensaje.reply_text(
            "❌ Ocurrió un error:\n\n"
            + str(error)
        )

    finally:

        archivos = [
            video_entrada,
            clip1,
            clip2,
            clip1_final,
            clip2_final,
        ]

        for archivo in archivos:

            try:

                if os.path.exists(archivo):
                    os.remove(archivo)

            except Exception:
                pass


# =========================================================
# RECIBIR VIDEO
# =========================================================

async def recibir_video(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not update.message:
        return

    if not update.message.video:
        return

    video = update.message.video

    archivo = await video.get_file()

    nombre = str(
        video.file_unique_id
    )

    await procesar_video(
        update,
        archivo,
        nombre,
    )


# =========================================================
# RECIBIR VIDEO COMO DOCUMENTO
# =========================================================

async def recibir_documento(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not update.message:
        return

    documento = update.message.document

    if not documento:
        return

    nombre_archivo = (
        documento.file_name or ""
    )

    extensiones = (
        ".mp4",
        ".mov",
        ".mkv",
        ".avi",
        ".webm",
    )

    if not nombre_archivo.lower().endswith(
        extensiones
    ):

        await update.message.reply_text(
            "⚠️ Envíame un archivo de video."
        )

        return

    archivo = await documento.get_file()

    nombre = str(
        documento.file_unique_id
    )

    await procesar_video(
        update,
        archivo,
        nombre,
    )


# =========================================================
# INICIAR BOT
# =========================================================

def iniciar_bot():

    request = HTTPXRequest(
        connect_timeout=60,
        read_timeout=600,
        write_timeout=600,
        pool_timeout=60,
    )

    app = (
        Application
        .builder()
        .token(TOKEN)
        .request(request)
        .build()
    )

    app.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    app.add_handler(
        MessageHandler(
            filters.VIDEO,
            recibir_video,
        )
    )

    app.add_handler(
        MessageHandler(
            filters.Document.VIDEO,
            recibir_documento,
        )
    )

    print(
        "🤖 MI-CLIPBOT iniciado correctamente."
    )

    app.run_polling(
        drop_pending_updates=True
    )


# =========================================================
# ARRANQUE
# =========================================================

if __name__ == "__main__":

    hilo = threading.Thread(
        target=iniciar_web,
        daemon=True,
    )

    hilo.start()
