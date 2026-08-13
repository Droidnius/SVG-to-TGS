"""
Bot de Telegram: convierte archivos SVG a TGS (stickers animados de Telegram).

Uso:
    export TELEGRAM_BOT_TOKEN="tu_token_de_botfather"
    python bot.py

Requisitos: ver requirements.txt
"""

import gzip
import json
import logging
import os
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from telegram import Update, InputFile
from telegram.error import BadRequest
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

        fix_rounded_rect_radius(tgs_path)
        size = tgs_path.stat().st_size

        if size > MAX_TGS_SIZE_BYTES:
            await status_msg.edit_text(
                f"El .tgs resultante pesa {size / 1024:.1f} KB, por encima del "
                f"límite de Telegram ({MAX_TGS_SIZE_BYTES / 1024:.0f} KB).\n"
                "Sugerencias: simplifica el SVG (menos nodos, menos colores/"
                "gradientes, menos texto convertido a paths) e inténtalo de nuevo."
            )
            return

        layer_count = count_lottie_layers(tgs_path)
        if layer_count == 0:
            await status_msg.edit_text(
                f"La conversión terminó pero el resultado quedó casi vacío "
                f"({size} bytes, sin capas visibles). Esto normalmente pasa "
                "cuando `lottie_convert.py` no logra interpretar ciertos "
                "elementos del SVG (grupos anidados, <use>, clip-paths, "
                "máscaras, gradientes complejos, texto sin convertir a "
                "path). Prueba aplanando el SVG (todos los grupos "
                "convertidos a paths simples, sin <use>/<defs> referenciados) "
                "y vuelve a intentarlo. Si quieres, comparte el SVG y "
                "reviso qué elemento específico está fallando."
            )
            return

        await status_msg.edit_text("Conversión lista. Enviando sticker...")
        try:
            with open(tgs_path, "rb") as tgs_file:
                await update.message.reply_sticker(
                    sticker=InputFile(tgs_file, filename="sticker.tgs"),
                )
        except BadRequest as e:
            logger.warning("Telegram rechazó el .tgs como sticker: %s", e)
            with open(tgs_path, "rb") as tgs_file:
                await update.message.reply_document(
                    document=InputFile(tgs_file, filename="sticker.tgs"),
                    caption=(
                        "Telegram rechazó este archivo como sticker directo "
                        f"({e}). Te lo mando como .tgs ({size / 1024:.1f} KB) "
                        "para que lo revises o lo subas manualmente con "
                        "@Stickers (a veces valida detalles adicionales, como "
                        "duración exacta o frame rate, que este chequeo básico "
                        "no cubre)."
                    ),
                )


def fix_rounded_rect_radius(tgs_path: Path) -> None:
    """
    `lottie_convert.py` tiene un bug conocido y consistente: al convertir
    un <rect rx="N"> de SVG a un shape "rc" (rounded rect) de Lottie,
    guarda la mitad del radio real (rx=256 -> r=128). Esto se comprobó
    de forma reproducible con varios valores de rx. Aquí se recorre el
    Lottie ya generado y se duplica el radio de cada "rc" estático
    (a=0) para compensarlo. Si el radio está animado (a=1, con
    keyframes), se deja tal cual porque no aplica este caso simple.
    """
    try:
        with gzip.open(tgs_path, "rt", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        logger.exception("No se pudo leer el .tgs para corregir el radio de esquina")
        return

    fixed_any = False

    def walk(node):
        nonlocal fixed_any
        if isinstance(node, dict):
            if node.get("ty") == "rc":
                r = node.get("r")
                if isinstance(r, dict) and r.get("a") == 0 and isinstance(r.get("k"), (int, float)):
                    r["k"] = r["k"] * 2
                    fixed_any = True
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data.get("assets", []))
    walk(data.get("layers", []))

    if fixed_any:
        with gzip.open(tgs_path, "wt", encoding="utf-8") as f:
            json.dump(data, f, separators=(",", ":"))
        logger.info("Corregido el radio de esquina de rectángulo(s) redondeado(s) en %s", tgs_path)


def count_lottie_layers(tgs_path: Path) -> int:
    """
    Descomprime el .tgs y cuenta cuántas formas (shapes) con contenido
    real tiene el Lottie resultante. Busca de forma recursiva porque en
    la salida de lottie_convert.py el contenido casi siempre queda
    anidado dentro de "assets" (el layer de nivel superior suele ser solo
    una referencia de tipo precomp), no directamente en "layers".
    """
    try:
        with gzip.open(tgs_path, "rt", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        logger.exception("No se pudo leer el .tgs generado para validarlo")
        return 0

    count = 0

    def walk(node):
        nonlocal count
        if isinstance(node, dict):
            # "ty": "sh" (path), "el" (elipse), "rc" (rect), etc. son
            # formas reales dentro de un grupo "shapes"; los contamos.
            if node.get("ty") in ("sh", "el", "rc", "sr"):
                count += 1
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data.get("assets", []))
    walk(data.get("layers", []))
    return count


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


class _HealthCheckHandler(BaseHTTPRequestHandler):
    """Handler mínimo: responde 200 OK a cualquier request. Solo existe
    para que el healthcheck de Fly.io (u otra plataforma similar) tenga
    algo que verificar; el bot en sí no usa HTTP para nada."""

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        pass  # silenciar el log de cada ping de healthcheck


def start_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), _HealthCheckHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info("Servidor de healthcheck escuchando en el puerto %s", port)


def main():
    if not BOT_TOKEN:
        raise SystemExit(
            "Define la variable de entorno TELEGRAM_BOT_TOKEN con el token de tu bot "
            "(obtenido de @BotFather)."
        )

    start_health_server()

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.FileExtension("svg"), handle_svg))

    logger.info("Bot iniciado, esperando mensajes...")
    app.run_polling()


if __name__ == "__main__":
    main()
