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
    raise RuntimeError("BOT_TOKEN no está configurado en Render")

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

VIDEOS_DIR = "videos"
CLIPS_DIR = "clips"
TEMP_DIR = "temp"

os.makedirs(VIDEOS_DIR, exist_ok=True)
os.makedirs(CLIPS_DIR, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)


# =========================================================
# WHISPER
# =========================================================

MODELO_WHISPER = None


def cargar_whisper():

    global MODELO_WHISPER

    if MODELO_WHISPER is None:

        print("Cargando Whisper...")

        MODELO_WHISPER = whisper.load_model(
            "tiny"
        )

        print("Whisper cargado correctamente.")

    return MODELO_WHISPER


# =========================================================
# SERVIDOR WEB
# =========================================================

web = Flask(__name__)


@web.route("/")
def home():

    return "🤖 MI CLIPBOT está funcionando correctamente."


@web.route("/health")
def health():

    return "OK"


def iniciar_web():

    puerto = int(
        os.environ.get(
            "PORT",
            "10000"
        )
    )

    web.run(
        host="0.0.0.0",
        port=puerto,
        debug=False,
        use_reloader=False
    )


# =========================================================
# START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(

        "🤖 ¡Hola! Soy MI CLIPBOT.\n\n"

        "🎬 Envíame un video.\n\n"

        "✂️ Crearé 2 clips.\n"
        "🗣️ Detectaré el habla.\n"
        "📝 Crearé subtítulos en español.\n"
        "📍 Los colocaré abajo del video."
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

    horas = int(
        encontrado.group(1)
    )

    minutos = int(
        encontrado.group(2)
    )

    segundos = float(
        encontrado.group(3)
    )

    return (
        horas * 3600
        + minutos * 60
        + segundos
    )


# =========================================================
# CREAR CLIP
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

        print(
            resultado.stderr[-3000:]
        )

        raise Exception(
            "No pude crear el clip."
        )


# =========================================================
# CREAR LOS 2 CLIPS
# =========================================================

def crear_clips(video):

    duracion = obtener_duracion(
        video
    )

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
# CREAR SRT CON WHISPER
# =========================================================

def segundo_a_srt(segundos):

    horas = int(
        segundos // 3600
    )

    minutos = int(
        (segundos % 3600) // 60
    )

    segundos_enteros = int(
        segundos % 60
    )

    milisegundos = int(
        (segundos - int(segundos)) * 1000
    )

    return (
        f"{horas:02d}:"
        f"{minutos:02d}:"
        f"{segundos_enteros:02d},"
        f"{milisegundos:03d}"
    )


def crear_subtitulos(
    video,
    archivo_srt
):

    modelo = cargar_whisper()

    print(
        "Transcribiendo:",
        video
    )

    resultado = modelo.transcribe(

        video,

        language="es",

        task="transcribe",

        fp16=False,

        verbose=False
    )

    segmentos = resultado.get(
        "segments",
        []
    )

    with open(
        archivo_srt,
        "w",
        encoding="utf-8"
    ) as archivo:

        numero = 1

        for segmento in segmentos:

            texto = segmento.get(
                "text",
                ""
            ).strip()

            if not texto:
                continue

            inicio = segmento[
                "start"
            ]

            fin = segmento[
                "end"
            ]

            archivo.write(

                str(numero)
                + "\n"
            )

            archivo.write(

                segundo_a_srt(inicio)
                + " --> "
                + segundo_a_srt(fin)
                + "\n"
            )

            archivo.write(
                texto
                + "\n\n"
            )

            numero += 1

    return archivo_srt


# =========================================================
# QUEMAR SUBTÍTULOS EN EL VIDEO
# =========================================================

def aplicar_subtitulos(
    video,
    srt,
    salida
):

    srt_absoluto = os.path.abspath(
        srt
    )

    srt_ffmpeg = (
        srt_absoluto
        .replace("\\", "/")
        .replace(":", "\\:")
        .replace("'", "\\'")
    )

    filtro = (
        "subtitles="
        + "'"
        + srt_ffmpeg
        + "':"
        "force_style="
        "'"
        "FontName=Arial,"
        "FontSize=18,"
        "PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H00000000,"
        "BorderStyle=1,"
        "Outline=2,"
        "Shadow=0,"
        "Alignment=2,"
        "MarginV=45"
        "'"
    )

    resultado = subprocess.run(

        [
            FFMPEG,

            "-y",

            "-i",
            video,

            "-vf",
            filtro,

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

        print(
            resultado.stderr[-5000:]
        )

        raise Exception(
            "No pude colocar los subtítulos."
        )

    return salida


# =========================================================
# PROCESAR UN CLIP
# =========================================================

def procesar_clip(
    clip,
    numero
):

    srt = os.path.join(

        TEMP_DIR,

        f"clip_{numero}.srt"
    )

    salida = os.path.join(

        CLIPS_DIR,

        f"MI_CLIP_{numero}_SUB.mp4"
    )

    crear_subtitulos(

        clip,

        srt
    )

    aplicar_subtitulos(

        clip,

        srt,

        salida
    )

    return salida


# =========================================================
# PROCESAR VIDEO COMPLETO
# =========================================================

async def procesar_video(

    update,

    archivo_telegram,

    nombre
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

    final1 = os.path.join(

        CLIPS_DIR,

        "MI_CLIP_1_SUB.mp4"
    )

    final2 = os.path.join(

        CLIPS_DIR,

        "MI_CLIP_2_SUB.mp4"
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

            video_entrada
        )

        await mensaje.reply_text(

            "🧠 Analizando el audio con Whisper...\n\n"
            "Esto puede tardar un poco."
        )

        await loop.run_in_executor(

            None,

            procesar_clip,

            clip1,

            1
        )

        await mensaje.reply_text(

            "📝 Clip 1 subtitulado.\n"
            "🧠 Procesando clip 2..."
        )

        await loop.run_in_executor(

            None,

            procesar_clip,

            clip2,

            2
        )

        await mensaje.reply_text(

            "✅ ¡Los 2 clips están listos!\n\n"
            "📤 Enviándotelos..."
        )

        with open(

            final1,

            "rb"
        ) as archivo1:

            await mensaje.reply_video(

                video=archivo1,

                caption=(
                    "🎬 MI CLIP 1\n"
                    "📝 Subtítulos en español"
                ),

                read_timeout=600,

                write_timeout=600,

                connect_timeout=60,

                pool_timeout=60
            )

        with open(

            final2,

            "rb"
        ) as archivo2:

            await mensaje.reply_video(

                video=archivo2,

                caption=(
                    "🎬 MI CLIP 2\n"
                    "📝 Subtítulos en español"
                ),

                read_timeout=600,

                write_timeout=600,

                connect_timeout=60,

                pool_timeout=60
            )

        await mensaje.reply_text(

            "🚀 ¡Proceso terminado!"
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

        archivos = [

            video_entrada,

            clip1,

            clip2,

            final1,

            final2,

            os.path.join(
                TEMP_DIR,
                "clip_1.srt"
            ),

            os.path.join(
                TEMP_DIR,
                "clip_2.srt"
            )
        ]

        for archivo in archivos:

            try:

                if os.path.exists(
                    archivo
                ):

                    os.remove(
                        archivo
                    )

            except Exception:

                pass


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

    video = update.message.video

    archivo = await video.get_file()

    nombre = str(

        video.file_unique_id
    )

    await procesar_video(

        update,

        archivo,

        nombre
    )


# =========================================================
# RECIBIR DOCUMENTO
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

    nombre = str(

        documento.file_unique_id
    )

    await procesar_video(

        update,

        archivo,

        nombre
    )


# =========================================================
# BOT
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
