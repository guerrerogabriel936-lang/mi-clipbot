import os
import re
import asyncio
import threading
import subprocess

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
    raise RuntimeError("Falta BOT_TOKEN en Render")

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

VIDEOS_DIR = "videos"
CLIPS_DIR = "clips"

os.makedirs(VIDEOS_DIR, exist_ok=True)
os.makedirs(CLIPS_DIR, exist_ok=True)


# =========================================================
# SERVIDOR WEB
# =========================================================

web = Flask(__name__)


@web.route("/")
def inicio():
    return "MI CLIPBOT funcionando correctamente."


@web.route("/health")
def health():
    return "OK"


def iniciar_web():
    puerto = int(os.environ.get("PORT", "10000"))

    web.run(
        host="0.0.0.0",
        port=puerto,
        debug=False,
        use_reloader=False
    )


# =========================================================
# TELEGRAM
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "🤖 Hola, soy MI CLIPBOT.\n\n"
        "🎬 Envíame un video y crearé 2 clips."
    )


# =========================================================
# DURACIÓN
# =========================================================

def obtener_duracion(video):

    resultado = subprocess.run(
        [
            FFMPEG,
            "-i",
            video
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    texto = resultado.stderr

    encontrado = re.search(
        r"Duration:\s*(\d+):(\d+):([\d.]+)",
        texto
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

def crear_clip(
    video,
    inicio,
    duracion,
    salida
):

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
            salida
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    if resultado.returncode != 0:

        print(resultado.stderr)

        raise Exception(
            "Error creando el clip."
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
        "MI_CLIP_1.mp4"
    )

    clip2 = os.path.join(
        CLIPS_DIR,
        "MI_CLIP_2.mp4"
    )

    crear_clip(
        video,
        0,
        mitad,
        clip1
    )

    crear_clip(
        video,
        mitad,
        mitad,
        clip2
    )

    return clip1, clip2


# =========================================================
# RECIBIR VIDEO
# =========================================================

async def recibir_video(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return

    if not update.message.video:
        return

    mensaje = update.message

    await mensaje.reply_text(
        "⏳ Recibí tu video. Preparando los clips..."
    )

    video = mensaje.video

    archivo = await video.get_file()

    nombre = str(video.file_unique_id)

    ruta = os.path.join(
        VIDEOS_DIR,
        nombre + ".mp4"
    )

    clip1 = os.path.join(
        CLIPS_DIR,
        "MI_CLIP_1.mp4"
    )

    clip2 = os.path.join(
        CLIPS_DIR,
        "MI_CLIP_2.mp4"
    )

    try:

        await archivo.download_to_drive(ruta)

        await mensaje.reply_text(
            "✂️ Creando los 2 clips..."
        )

        loop = asyncio.get_running_loop()

        await loop.run_in_executor(
            None,
            crear_clips,
            ruta
        )

        await mensaje.reply_text(
            "✅ Clips creados. Enviándotelos..."
        )

        with open(clip1, "rb") as video1:

            await mensaje.reply_video(
                video=video1,
                caption="🎬 MI CLIP 1",
                read_timeout=600,
                write_timeout=600,
                connect_timeout=60,
                pool_timeout=60
            )

        with open(clip2, "rb") as video2:

            await mensaje.reply_video(
                video=video2,
                caption="🎬 MI CLIP 2",
                read_timeout=600,
                write_timeout=600,
                connect_timeout=60,
                pool_timeout=60
            )

        await mensaje.reply_text(
            "🚀 ¡Listo! Ya tienes tus 2 clips."
        )

    except Exception as error:

        print(
            "ERROR:",
            repr(error)
        )

        await mensaje.reply_text(
            "❌ Ocurrió un error:\n\n"
            + str(error)
        )

    finally:

        for archivo_temp in [
            ruta,
            clip1,
            clip2
        ]:

            try:

                if os.path.exists(archivo_temp):
                    os.remove(archivo_temp)

            except Exception:
                pass


# =========================================================
# RECIBIR VIDEO COMO ARCHIVO
# =========================================================

async def recibir_documento(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return

    documento = update.message.document

    if not documento:
        return

    nombre = documento.file_name or ""

    extensiones = (
        ".mp4",
        ".mov",
        ".mkv",
        ".avi",
        ".webm"
    )

    if not nombre.lower().endswith(extensiones):

        await update.message.reply_text(
            "⚠️ Ese archivo no parece ser un video."
        )

        return

    archivo = await documento.get_file()

    video_nombre = str(
        documento.file_unique_id
    )

    ruta = os.path.join(
        VIDEOS_DIR,
        video_nombre + ".mp4"
    )

    await update.message.reply_text(
        "⏳ Recibí tu archivo de video..."
    )

    try:

        await archivo.download_to_drive(ruta)

        loop = asyncio.get_running_loop()

        await update.message.reply_text(
            "✂️ Creando los 2 clips..."
        )

        await loop.run_in_executor(
            None,
            crear_clips,
            ruta
        )

        clip1 = os.path.join(
            CLIPS_DIR,
            "MI_CLIP_1.mp4"
        )

        clip2 = os.path.join(
            CLIPS_DIR,
            "MI_CLIP_2.mp4"
        )

        with open(clip1, "rb") as video1:

            await update.message.reply_video(
                video=video1,
                caption="🎬 MI CLIP 1",
                read_timeout=600,
                write_timeout=600,
                connect_timeout=60,
                pool_timeout=60
            )

        with open(clip2, "rb") as video2:

            await update.message.reply_video(
                video=video2,
                caption="🎬 MI CLIP 2",
                read_timeout=600,
                write_timeout=600,
                connect_timeout=60,
                pool_timeout=60
            )

        await update.message.reply_text(
            "🚀 ¡Proceso terminado!"
        )

    except Exception as error:

        print(
            "ERROR:",
            repr(error)
        )

        await update.message.reply_text(
            "❌ Error:\n\n"
            + str(error)
        )

    finally:

        for archivo_temp in [
            ruta,
            os.path.join(
                CLIPS_DIR,
                "MI_CLIP_1.mp4"
            ),
            os.path.join(
                CLIPS_DIR,
                "MI_CLIP_2.mp4"
            )
        ]:

            try:

                if os.path.exists(archivo_temp):
                    os.remove(archivo_temp)

            except Exception:
                pass


# =========================================================
# INICIAR BOT
# =========================================================

def iniciar_bot():

    request = HTTPXRequest(
        connect_timeout=60,
        read_timeout=600,
        write_timeout=600,
        pool_timeout=60
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
            start
        )
    )

    app.add_handler(
        MessageHandler(
            filters.VIDEO,
            recibir_video
        )
    )

    app.add_handler(
        MessageHandler(
            filters.Document.VIDEO,
            recibir_documento
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
        daemon=True
    )

    hilo.start()

    iniciar_bot()
