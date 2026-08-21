import os
import asyncio
import threading
import subprocess
import uuid
import secrets
import re

from flask import Flask, redirect, request
from werkzeug.middleware.proxy_fix import ProxyFix

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

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload


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
TOKENS_DIR = os.path.join(BASE_DIR, "youtube_tokens")

os.makedirs(VIDEOS_DIR, exist_ok=True)
os.makedirs(CLIPS_DIR, exist_ok=True)
os.makedirs(TOKENS_DIR, exist_ok=True)


# =========================================================
# GOOGLE / YOUTUBE
# =========================================================

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")

GOOGLE_REDIRECT_URI = os.getenv(
    "GOOGLE_REDIRECT_URI",
    "https://mi-clipbot.onrender.com/oauth2callback"
)

YOUTUBE_SCOPE = [
    "https://www.googleapis.com/auth/youtube.upload"
]

oauth_states = {}


# =========================================================
# SERVIDOR WEB
# =========================================================

web = Flask(__name__)

# IMPORTANTE:
# Render funciona detrás de un proxy HTTPS.
# Esto hace que Flask reconozca correctamente HTTPS.
web.wsgi_app = ProxyFix(
    web.wsgi_app,
    x_for=1,
    x_proto=1,
    x_host=1,
    x_port=1,
)


@web.route("/")
def home():
    return "🤖 MI-CLIPBOT está funcionando correctamente."


@web.route("/health")
def health():
    return "OK"


# =========================================================
# OAUTH YOUTUBE
# =========================================================

@web.route("/connect-youtube")
def connect_youtube():

    user_id = request.args.get("user")

    if not user_id:
        return "Falta el usuario de Telegram.", 400

    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        return (
            "Faltan GOOGLE_CLIENT_ID o "
            "GOOGLE_CLIENT_SECRET en Render.",
            500
        )

    state = secrets.token_urlsafe(32)

    oauth_states[state] = str(user_id)

    client_config = {
        "web": {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [GOOGLE_REDIRECT_URI],
        }
    }

    flow = Flow.from_client_config(
        client_config,
        scopes=YOUTUBE_SCOPE,
        state=state
    )

    flow.redirect_uri = GOOGLE_REDIRECT_URI

    authorization_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent"
    )
oauth_states[state + "_verifier"] = flow.code_verifier
    return redirect(authorization_url)


@web.route("/oauth2callback")
def oauth2callback():

    state = request.args.get("state")

    if not state:
        return "No se recibió el estado OAuth.", 400

    user_id = oauth_states.get(state)

    if not user_id:
        return (
            "La sesión de conexión expiró. "
            "Vuelve a pulsar Conectar YouTube desde Telegram.",
            400
        )

    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        return "Faltan las credenciales de Google.", 500

    client_config = {
        "web": {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [GOOGLE_REDIRECT_URI],
        }
    }

    flow = Flow.from_client_config(
        client_config,
        scopes=YOUTUBE_SCOPE,
        state=state
    )

    flow.redirect_uri = GOOGLE_REDIRECT_URI

    try:
flow.code_verifier = oauth_states.get(state + "_verifier")
        # Gracias a ProxyFix, request.url será HTTPS
        flow.fetch_token(
            authorization_response=request.url
        )

    except Exception as error:

        print("ERROR OAUTH:", repr(error))

        return (
            "❌ Error conectando YouTube:<br><br>"
            + str(error),
            500
        )

    credentials = flow.credentials

    token_file = os.path.join(
        TOKENS_DIR,
        f"{user_id}.json"
    )

    with open(
        token_file,
        "w",
        encoding="utf-8"
    ) as archivo:

        archivo.write(
            credentials.to_json()
        )

    oauth_states.pop(state, None)

    return """
    <html>
    <head>
        <meta name="viewport" content="width=device-width">
        <title>MI-CLIPBOT</title>
    </head>

    <body style="
        font-family:Arial;
        text-align:center;
        padding:40px;
    ">

        <h1>✅ YouTube conectado</h1>

        <p>
        Tu cuenta de YouTube quedó conectada correctamente.
        </p>

        <p>
        Ya puedes volver a Telegram.
        </p>

    </body>
    </html>
    """


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
# FUNCIONES YOUTUBE
# =========================================================

def token_path(user_id):

    return os.path.join(
        TOKENS_DIR,
        f"{user_id}.json"
    )


def youtube_conectado(user_id):

    return os.path.exists(
        token_path(user_id)
    )


def obtener_youtube(user_id):

    archivo = token_path(user_id)

    if not os.path.exists(archivo):

        raise Exception(
            "Tu cuenta de YouTube no está conectada."
        )

    credentials = Credentials.from_authorized_user_file(
        archivo,
        YOUTUBE_SCOPE
    )

    if (
        credentials.expired
        and credentials.refresh_token
    ):

        from google.auth.transport.requests import Request

        credentials.refresh(Request())

        with open(
            archivo,
            "w",
            encoding="utf-8"
        ) as f:

            f.write(
                credentials.to_json()
            )

    return build(
        "youtube",
        "v3",
        credentials=credentials
    )


def subir_youtube(
    user_id,
    archivo_video,
    titulo,
    descripcion,
    privacidad
):

    youtube = obtener_youtube(user_id)

    cuerpo = {
        "snippet": {
            "title": titulo,
            "description": descripcion,
            "categoryId": "22",
        },
        "status": {
            "privacyStatus": privacidad,
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(
        archivo_video,
        mimetype="video/mp4",
        resumable=True
    )

    solicitud = youtube.videos().insert(
        part="snippet,status",
        body=cuerpo,
        media_body=media
    )

    respuesta = None

    while respuesta is None:

        estado, respuesta = solicitud.next_chunk()

        if estado:

            print(
                "Subiendo:",
                int(estado.progress() * 100),
                "%"
            )

    return respuesta["id"]


# =========================================================
# MENÚ PRINCIPAL
# =========================================================

def menu_principal():

    botones = [

        [
            InlineKeyboardButton(
                "🎬 Crear 5 clips",
                callback_data="clips"
            )
        ],

        [
            InlineKeyboardButton(
                "📱 Vertical 9:16",
                callback_data="vertical"
            ),
            InlineKeyboardButton(
                "🎥 Horizontal 16:9",
                callback_data="horizontal"
            )
        ],

        [
            InlineKeyboardButton(
                "▶️ Conectar YouTube",
                callback_data="youtube"
            )
        ],

        [
            InlineKeyboardButton(
                "📤 Publicar en YouTube",
                callback_data="publicar"
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


def menu_privacidad():

    botones = [

        [
            InlineKeyboardButton(
                "🌎 Público",
                callback_data="yt_public"
            )
        ],

        [
            InlineKeyboardButton(
                "🔗 No listado",
                callback_data="yt_unlisted"
            )
        ],

        [
            InlineKeyboardButton(
                "🔒 Privado",
                callback_data="yt_private"
            )
        ]

    ]

    return InlineKeyboardMarkup(botones)


# =========================================================
# START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    context.user_data["formato"] = "vertical"

    await update.message.reply_text(

        "🤖 *MI-CLIPBOT*\n\n"

        "🎬 Editor gratuito de clips.\n\n"

        "📹 Envíame un video largo y crearé "
        "*5 clips de 30 segundos*.\n\n"

        "📱 Vertical para Shorts/Reels/TikTok\n"
        "🎥 Horizontal para YouTube\n\n"

        "▶️ También puedes conectar YouTube "
        "y publicar tus clips.",

        reply_markup=menu_principal(),

        parse_mode="Markdown"
    )


# =========================================================
# BOTONES
# =========================================================

async def botones(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    user_id = str(
        query.from_user.id
    )

    if query.data == "clips":

        await query.message.reply_text(

            "🎬 Perfecto.\n\n"
            "Envíame tu video.\n\n"
            "Crearé automáticamente "
            "5 clips de aproximadamente "
            "30 segundos."
        )

    elif query.data == "vertical":

        context.user_data["formato"] = "vertical"

        await query.message.reply_text(

            "📱 *Vertical 9:16 seleccionado.*\n\n"
            "Ideal para YouTube Shorts, "
            "TikTok e Instagram Reels.",

            parse_mode="Markdown"
        )

    elif query.data == "horizontal":

        context.user_data["formato"] = "horizontal"

        await query.message.reply_text(

            "🎥 *Horizontal 16:9 seleccionado.*\n\n"
            "Ideal para YouTube normal.",

            parse_mode="Markdown"
        )

    elif query.data == "youtube":

        if youtube_conectado(user_id):

            await query.message.reply_text(
                "✅ Tu YouTube ya está conectado."
            )

            return

        url = (
            "https://mi-clipbot.onrender.com"
            "/connect-youtube"
            "?user="
            + user_id
        )

        teclado = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "▶️ CONECTAR YOUTUBE",
                        url=url
                    )
                ]
            ]
        )

        await query.message.reply_text(

            "▶️ *Conectar YouTube*\n\n"
            "Pulsa el botón de abajo.",

            reply_markup=teclado,

            parse_mode="Markdown"
        )

    elif query.data == "publicar":

        if not youtube_conectado(user_id):

            await query.message.reply_text(

                "⚠️ Primero debes conectar "
                "tu cuenta de YouTube.",

                reply_markup=menu_principal()
            )

            return

        clips = context.user_data.get(
            "clips",
            []
        )

        if not clips:

            await query.message.reply_text(
                "⚠️ Primero envíame un video."
            )

            return

        await query.message.reply_text(

            "📤 ¿Cómo quieres publicar "
            "los 5 clips?",

            reply_markup=menu_privacidad()
        )

    elif query.data in (
        "yt_public",
        "yt_unlisted",
        "yt_private"
    ):

        privacidad = {

            "yt_public": "public",
            "yt_unlisted": "unlisted",
            "yt_private": "private"

        }[query.data]

        context.user_data[
            "youtube_privacidad"
        ] = privacidad

        await publicar_clips(
            query.message,
            context,
            privacidad
        )

    elif query.data == "info":

        await query.message.reply_text(

            "ℹ️ *MI-CLIPBOT*\n\n"
            "1️⃣ Envías un video largo.\n"
            "2️⃣ Calcula su duración.\n"
            "3️⃣ Selecciona 5 partes.\n"
            "4️⃣ Cada parte dura 30 segundos.\n"
            "5️⃣ Convierte al formato elegido.\n"
            "6️⃣ Te devuelve los clips.\n"
            "7️⃣ Puedes conectar YouTube.\n"
            "8️⃣ Puedes publicar los clips.",

            parse_mode="Markdown"
        )


# =========================================================
# PUBLICAR CLIPS
# =========================================================

async def publicar_clips(
    mensaje,
    context,
    privacidad
):

    user_id = str(
        mensaje.chat_id
    )

    clips = context.user_data.get(
        "clips",
        []
    )

    if not clips:

        await mensaje.reply_text(
            "⚠️ No hay clips disponibles."
        )

        return

    await mensaje.reply_text(
        "📤 Iniciando publicación..."
    )

    publicados = []

    loop = asyncio.get_running_loop()

    try:

        for numero, clip in enumerate(
            clips,
            start=1
        ):

            if not os.path.exists(clip):
                continue

            await mensaje.reply_text(
                f"📤 Subiendo clip {numero}/{len(clips)}..."
            )

            titulo = (
                f"MI CLIP {numero} | MI-CLIPBOT"
            )

            descripcion = (
                "Clip creado automáticamente "
                "con MI-CLIPBOT.\n\n"
                "#shorts #video #clip"
            )

            video_id = await loop.run_in_executor(

                None,

                subir_youtube,

                user_id,
                clip,
                titulo,
                descripcion,
                privacidad
            )

            publicados.append(video_id)

            await mensaje.reply_text(

                f"✅ Clip {numero} publicado.\n\n"
                f"https://www.youtube.com/watch?v={video_id}"
            )

        await mensaje.reply_text(

            f"🎉 ¡Listo!\n\n"
            f"Se publicaron {len(publicados)} "
            f"de {len(clips)} clips.",

            reply_markup=menu_principal()
        )

    except Exception as error:

        print(
            "ERROR YOUTUBE:",
            repr(error)
        )

        await mensaje.reply_text(

            "❌ Error publicando en YouTube:\n\n"
            + str(error)
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
# CREAR VERTICAL
# =========================================================

def crear_vertical(
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

            "-vf",
            (
                "scale=720:1280:"
                "force_original_aspect_ratio=decrease,"
                "pad=720:1280:"
                "(ow-iw)/2:(oh-ih)/2"
            ),

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
# CREAR HORIZONTAL
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
# CREAR 5 CLIPS
# =========================================================

def crear_clips(
    video,
    formato,
    user_id
):

    duracion_total = obtener_duracion(
        video
    )

    if duracion_total < 30:

        raise Exception(
            "El video debe durar al menos "
            "30 segundos."
        )

    duracion_clip = 30

    if duracion_total < 150:

        cantidad_real = int(
            duracion_total // 30
        )

        cantidad_real = max(
            1,
            cantidad_real
        )

    else:

        cantidad_real = 5

    clips_usuario_dir = os.path.join(
        CLIPS_DIR,
        str(user_id)
    )

    os.makedirs(
        clips_usuario_dir,
        exist_ok=True
    )

    for archivo in os.listdir(
        clips_usuario_dir
    ):

        ruta = os.path.join(
            clips_usuario_dir,
            archivo
        )

        try:

            if os.path.isfile(ruta):
                os.remove(ruta)

        except Exception:
            pass

    clips = []

    if cantidad_real == 1:

        posiciones = [0]

    else:

        espacio = (
            duracion_total - duracion_clip
        )

        posiciones = [

            (espacio * i)
            / (cantidad_real - 1)

            for i in range(
                cantidad_real
            )
        ]

    for numero, inicio in enumerate(
        posiciones,
        start=1
    ):

        salida = os.path.join(

            clips_usuario_dir,

            f"MI_CLIP_{numero}.mp4"
        )

        if formato == "vertical":

            crear_vertical(
                video,
                salida,
                inicio,
                duracion_clip
            )

        else:

            crear_horizontal(
                video,
                salida,
                inicio,
                duracion_clip
            )

        clips.append(salida)

    return clips


# =========================================================
# PROCESAR VIDEO
# =========================================================

async def procesar_video(
    update,
    context,
    archivo_telegram,
    nombre,
    formato
):

    mensaje = update.message

    user_id = str(
        update.effective_user.id
    )

    video_entrada = os.path.join(
        VIDEOS_DIR,
        nombre + ".mp4"
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
            "✂️ 3/4 — Creando tus 5 clips "
            "de 30 segundos..."
        )

        loop = asyncio.get_running_loop()

        clips = await loop.run_in_executor(

            None,

            crear_clips,

            video_entrada,
            formato,
            user_id
        )

        # IMPORTANTE:
        # Guardar los clips en la sesión del usuario
        # para publicarlos después en YouTube.

        context.user_data["clips"] = clips

        await mensaje.reply_text(
            "📤 4/4 — Enviando los clips..."
        )

        for numero, clip in enumerate(
            clips,
            start=1
        ):

            if not os.path.exists(clip):
                continue

            with open(
                clip,
                "rb"
            ) as archivo:

                await mensaje.reply_video(

                    video=archivo,

                    caption=(
                        f"🔥 MI CLIP {numero}\n\n"
                        "⏱️ Duración: 30 segundos\n"
                        "🎬 MI-CLIPBOT"
                    ),

                    read_timeout=600,
                    write_timeout=600,
                    connect_timeout=60,
                    pool_timeout=60
                )

        await mensaje.reply_text(

            "✅ ¡Listo!\n\n"
            f"Se crearon {len(clips)} clips "
            "de aproximadamente 30 segundos.\n\n"
            "▶️ Si quieres subirlos a YouTube, "
            "pulsa *Publicar en YouTube*.",

            reply_markup=menu_principal(),

            parse_mode="Markdown"
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

        try:

            if os.path.exists(video_entrada):

                os.remove(
                    video_entrada
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
        context,
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
        context,
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
