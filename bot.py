import os
import asyncio
import threading
import subprocess
import uuid

from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
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

BASE_DIR = os.getcwd()
VIDEOS_DIR = os.path.join(BASE_DIR, "videos")
CLIPS_DIR = os.path.join(BASE_DIR, "clips")

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
        use_reloader=False
    )


# =========================================================
# MENÚ PRINCIPAL
# =========================================================

def menu_principal():

    botones = [
        [
            InlineKeyboardButton(
                "🎬 Crear 2 clips",
                callback_data="clips"
            )
        ],
        [
            InlineKeyboardButton(
                "📱 Clips verticales 9:16",
                callback_data="vertical"
            )
        ],
        [
            InlineKeyboardButton(
                "🎥 Clips normales 16:9",
                callback_data="horizontal"
            )
        ],
        [
            InlineKeyboardButton(
                "ℹ️ Cómo funciona",
                callback_data="info"
            )
        ]
    ]

    return InlineKeyboardMarkup(botones)


# =========================================================
# START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    context.user_data["formato"] = "vertical"

    await update.message.reply_text(
        "🤖 *MI-CLIPBOT*\n\n"
        "🎬 Una versión gratuita tipo editor de clips.\n\n"
        "Envíame un video y puedo convertirlo "
        "en 2 clips.\n\n"
        "📱 Recomendado: formato vertical 9:16\n"
        "🎥 También puedo conservar 16:9.",
        reply_markup=menu_principal(),
        parse_mode="Markdown"
    )


# =========================================================
# BOTONES
# =========================================================

async def botones(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query

    await query.answer()

    if query.data == "clips":

        await query.message.reply_text(
            "🎬 Perfecto.\n\n"
            "Envíame el video y crearé 2 clips."
        )

    elif query.data == "vertical":

        context.user_data["formato"] = "vertical"

        await query.message.reply_text(
            "📱 Formato vertical seleccionado.\n\n"
            "Los clips serán preparados para "
            "Shorts, Reels y TikTok."
        )

    elif query.data == "horizontal":

        context.user_data["formato"] = "horizontal"

        await query.message.reply_text(
            "🎥 Formato horizontal seleccionado."
        )

    elif query.data == "info":

        await query.message.reply_text(
            "ℹ️ MI-CLIPBOT\n\n"
            "1️⃣ Envías un video.\n"
            "2️⃣ Lo proceso.\n"
            "3️⃣ Creo 2 clips.\n"
            "4️⃣ Los convierto al formato elegido.\n"
            "5️⃣ Te devuelvo los clips.\n\n"
            "🚀 Más adelante añadiremos publicación "
            "directa en YouTube."
        )


# =========================================================
# OBTENER DURACIÓN
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

    import re

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
# CREAR CLIP VERTICAL
# =========================================================

def crear_vertical(
    entrada,
    salida,
    inicio,
    duracion
):

    filtro = (
        "scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920"
    )

    resultado = subprocess.run(
        [
            FFMPEG,
            "-y",
            "-ss",
            str(inicio),
            "-i",
            entrada,
            "-t",
            str(duracion),

            "-vf",
            filtro,

            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "27",

            "-c:a",
            "aac",
            "-b:a",
            "128k",

            "-movflags",
            "+faststart",

            salida
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    if resultado.returncode != 0:

        raise Exception(
            "Error creando video vertical:\n"
            + resultado.stderr[-1500:]
        )


# =========================================================
# CREAR CLIP HORIZONTAL
# =========================================================

def crear_horizontal(
    entrada,
    salida,
    inicio,
    duracion
):

    resultado = subprocess.run(
        [
            FFMPEG,
            "-y",
            "-ss",
            str(inicio),
            "-i",
            entrada,
            "-t",
            str(duracion),

            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "27",

            "-c:a",
            "aac",
            "-b:a",
            "128k",

            "-movflags",
            "+faststart",

            salida
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    if resultado.returncode != 0:

        raise Exception(
            "Error creando video:\n"
            + resultado.stderr[-1500:]
        )


# =========================================================
# CREAR 2 CLIPS
# =========================================================

def crear_clips(video, formato):

    duracion_total = obtener_duracion(video)

    if duracion_total < 8:

        raise Exception(
            "El video debe durar al menos 8 segundos."
        )

    # Dejamos unos segundos de margen
    duracion_util = duracion_total

    mitad = duracion_util / 2

    duracion_clip = mitad

    clip1 = os.path.join(
        CLIPS_DIR,
        "MI_CLIP_1.mp4"
    )

    clip2 = os.path.join(
        CLIPS_DIR,
        "MI_CLIP_2.mp4"
    )

    # Borrar archivos anteriores
    for archivo in [clip1, clip2]:

        if os.path.exists(archivo):

            try:
                os.remove(archivo)
            except Exception:
                pass

    if formato == "vertical":

        crear_vertical(
            video,
            clip1,
            0,
            duracion_clip
        )

        crear_vertical(
            video,
            clip2,
            mitad,
            duracion_clip
        )

    else:

        crear_horizontal(
            video,
            clip1,
            0,
            duracion_clip
        )

        crear_horizontal(
            video,
            clip2,
            mitad,
            duracion_clip
        )

    return clip1, clip2


# =========================================================
# PROCESAR VIDEO
# =========================================================

async def procesar_video(
    update,
    archivo_telegram,
    nombre,
    formato
):

    mensaje = update.message

    video_entrada = os.path.join(
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

        await mensaje.reply_text(
            "⏳ 1/4 — Descargando tu video..."
        )

        await archivo_telegram.download_to_drive(
            video_entrada
        )

        await mensaje.reply_text(
            "🧠 2/4 — Preparando el video..."
        )

        await mensaje.reply_text(
            "✂️ 3/4 — Creando tus 2 clips..."
        )

        loop = asyncio.get_running_loop()

        await loop.run_in_executor(
            None,
            crear_clips,
            video_entrada,
            formato
        )

        await mensaje.reply_text(
            "📤 4/4 — Enviando los clips..."
        )

        # =================================================
        # CLIP 1
        # =================================================

        with open(
            clip1,
            "rb"
        ) as archivo1:

            await mensaje.reply_video(
                video=archivo1,
                caption=(
                    "🔥 MI CLIP 1\n\n"
                    "🎬 Creado con MI-CLIPBOT"
                ),
                read_timeout=600,
                write_timeout=600,
                connect_timeout=60,
                pool_timeout=60
            )

        # =================================================
        # CLIP 2
        # =================================================

        with open(
            clip2,
            "rb"
        ) as archivo2:

            await mensaje.reply_video(
                video=archivo2,
                caption=(
                    "🔥 MI CLIP 2\n\n"
                    "🎬 Creado con MI-CLIPBOT"
                ),
                read_timeout=600,
                write_timeout=600,
                connect_timeout=60,
                pool_timeout=60
            )

        await mensaje.reply_text(
            "✅ ¡Listo!\n\n"
            "Tus 2 clips fueron creados correctamente.",
            reply_markup=menu_principal()
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

        for archivo in [
            video_entrada,
            clip1,
            clip2
        ]:

            try:

                if os.path.exists(archivo):

                    os.remove(archivo)

            except Exception:

                pass


# =========================================================
# RECIBIR VIDEO NORMAL
# =========================================================

async def recibir_video(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return

    if not update.message.video:
        return

    video = update.message.video

    archivo = await video.get_file()

    nombre = (
        str(video.file_unique_id)
        + "_"
        + str(uuid.uuid4())[:8]
    )

    formato = context.user_data.get(
        "formato",
        "vertical"
    )

    await procesar_video(
        update,
        archivo,
        nombre,
        formato
    )


# =========================================================
# RECIBIR VIDEO COMO DOCUMENTO
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

    nombre_archivo = (
        documento.file_name or ""
    )

    extensiones = (
        ".mp4",
        ".mov",
        ".mkv",
        ".avi",
        ".webm"
    )

    if not nombre_archivo.lower().endswith(
        extensiones
    ):

        await update.message.reply_text(
            "⚠️ Envíame un archivo de video."
        )

        return

    archivo = await documento.get_file()

    nombre = (
        str(documento.file_unique_id)
        + "_"
        + str(uuid.uuid4())[:8]
    )

    formato = context.user_data.get(
        "formato",
        "vertical"
    )

    await procesar_video(
        update,
        archivo,
        nombre,
        formato
    )


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
        CallbackQueryHandler(
            botones
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

    hilo_web = threading.Thread(
        target=iniciar_web,
        daemon=True
    )

    hilo_web.start()

    iniciar_bot()
