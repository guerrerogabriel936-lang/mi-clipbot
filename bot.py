import os
import threading
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

TOKEN = os.getenv("BOT_TOKEN")

# Servidor para Render
web = Flask(__name__)

@web.route("/")
def home():
    return "MI CLIPBOT está funcionando. 🤖"

def iniciar_web():
    puerto = int(os.environ.get("PORT", 10000))
    web.run(host="0.0.0.0", port=puerto)

# Comando /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 ¡Hola! Soy MI CLIPBOT. 🎬\n\n"
        "Envíame un video y comenzaré a prepararlo."
    )

# Recibir videos
async def recibir_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    video = update.message.video

    await update.message.reply_text(
        "🎬 ¡Video recibido!\n"
        "Estoy preparando el archivo..."
    )

    archivo = await video.get_file()

    carpeta = "videos"
    os.makedirs(carpeta, exist_ok=True)

    ruta = os.path.join(carpeta, f"{video.file_unique_id}.mp4")

    await archivo.download_to_drive(ruta)

    await update.message.reply_text(
        "✅ Video guardado correctamente.\n"
        "Ahora podremos comenzar a crear los clips."
    )

def iniciar_bot():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    app.add_handler(
        MessageHandler(filters.VIDEO, recibir_video)
    )

    app.run_polling()

if __name__ == "__main__":
    threading.Thread(target=iniciar_web, daemon=True).start()
    iniciar_bot()
