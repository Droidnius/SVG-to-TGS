"""
Bot de Telegram: convierte archivos SVG a TGS (stickers animados de Telegram).

Uso:
    export TELEGRAM_BOT_TOKEN="tu_token_de_botfather"
    python bot.py

Requisitos: ver requirements.txt
"""

import logging
import os
import subprocess
import tempfile
from pathlib import Path

from telegram import Update, InputFile
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

# Requisitos de Telegram para stickers animados (.tgs)
MAX_TGS_SIZE_BYTES = 64 * 1024  # 64 KB
STICKER_CANVAS = 512  # px, lienzo cuadrado
MAX_DURATION_SECONDS = 3
TARGET_FPS = 60


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "¡Hola! Envíame un archivo .svg y trataré de convertirlo a .tgs "
        "(sticker animado de Telegram).\n\n"
        "Importante: si tu SVG es estático (sin animaciones SMIL/CSS), el "
        "resultado será una animación de un solo fotograma: se verá bien "
        "pero no se moverá. Para animación real, el SVG debe contener "
        "animación, o debes partir de un archivo Lottie ya animado."
    )


async def handle_svg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    document = update.message.document
    if not document:
        return

    filename = document.file_name or ""
    if not filename.lower().endswith(".svg"):
        await update.message.reply_text("Por favor envía un archivo con extensión .svg")
        return

    status_msg = await update.message.reply_text("Recibido. Convirtiendo a TGS, dame un momento...")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        svg_path = tmp_path / "input.svg"
        tgs_path = tmp_path / "output.tgs"

        file = await context.bot.get_file(document.file_id)
        await file.download_to_drive(custom_path=str(svg_path))

        try:
            convert_svg_to_tgs(svg_path, tgs_path)
        except Exception as e:
            logger.exception("Fallo en la conversión")
            await status_msg.edit_text(f"No pude convertir el archivo: {e}")
            return

        if not tgs_path.exists():
            await status_msg.edit_text("La conversión no generó ningún archivo de salida.")
            return

        size = tgs_path.stat().st_size
        if size > MAX_TGS_SIZE_BYTES:
            await status_msg.edit_text(
                f"El .tgs resultante pesa {size / 1024:.1f} KB, por encima del "
                f"límite de Telegram ({MAX_TGS_SIZE_BYTES / 1024:.0f} KB).\n"
                "Sugerencias: simplifica el SVG (menos nodos, menos colores/"
                "gradientes, menos texto convertido a paths) e inténtalo de nuevo."
            )
            return

        await status_msg.edit_text("Conversión lista. Enviando archivo...")
        await update.message.reply_document(
            document=InputFile(str(tgs_path), filename="sticker.tgs"),
            caption=(
                "Aquí está tu archivo .tgs "
                f"({size / 1024:.1f} KB). Recuerda: para usarlo como sticker "
                "real en Telegram debe añadirse a un sticker set animado "
                "mediante @Stickers o la API (createNewStickerSet)."
            ),
        )


def convert_svg_to_tgs(svg_path: Path, tgs_path: Path) -> None:
    """
    Usa la herramienta de línea de comandos `lottie_convert.py`
    (parte de la librería `lottie`) para convertir SVG -> TGS,
    forzando el lienzo a 512x512 (requisito de Telegram).
    """
    cmd = [
        "lottie_convert.py",
        str(svg_path),
        str(tgs_path),
        "--width", str(STICKER_CANVAS),
        "--height", str(STICKER_CANVAS),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "error desconocido en lottie_convert.py")


def main():
    if not BOT_TOKEN:
        raise SystemExit(
            "Define la variable de entorno TELEGRAM_BOT_TOKEN con el token de tu bot "
            "(obtenido de @BotFather)."
        )

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.FileExtension("svg"), handle_svg))

    logger.info("Bot iniciado, esperando mensajes...")
    app.run_polling()


if __name__ == "__main__":
    main()
