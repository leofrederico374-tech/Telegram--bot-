import logging
import json
import os
import asyncio
import threading
import time
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, ContextTypes, PicklePersistence

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# Bot token and owner IDs
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8573621777:AAExY5voLcOKBwB_DHi8RY5QC-PXUIZCR6Y")
OWNER_IDS = [int(x) for x in os.environ.get("OWNER_IDS", "6852704459,8514457680").split(",")]
PORT = int(os.environ.get("PORT", "10000"))
RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL", "https://telegram-bot-y9s3.onrender.com")

# ===== In-memory storage (persists via bot_data) =====
# Messages and state are stored in context.bot_data so they survive within a session
# For cross-deploy persistence, we also keep a global fallback
MESSAGES = []
BOT_ENABLED = True

# ===== Self-ping to keep Render alive =====
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot is alive!")
    def log_message(self, format, *args):
        pass

def start_web_server():
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    server.serve_forever()

def self_ping():
    """Ping self every 4 minutes to prevent Render from sleeping"""
    while True:
        time.sleep(240)
        try:
            urllib.request.urlopen(RENDER_URL, timeout=10)
            logger.info("Self-ping successful")
        except Exception as e:
            logger.warning(f"Self-ping failed: {e}")

# ===== Helper functions =====
def get_messages(context: ContextTypes.DEFAULT_TYPE):
    if "messages" not in context.bot_data:
        context.bot_data["messages"] = []
    return context.bot_data["messages"]

def set_messages(context: ContextTypes.DEFAULT_TYPE, messages):
    context.bot_data["messages"] = messages

def is_bot_enabled(context: ContextTypes.DEFAULT_TYPE):
    return context.bot_data.get("enabled", True)

def set_bot_enabled(context: ContextTypes.DEFAULT_TYPE, enabled):
    context.bot_data["enabled"] = enabled

# ===== Bot command handlers =====
async def add_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in OWNER_IDS:
        return
    if not context.args:
        await update.message.reply_text("Usage: /add <message>")
        return
    message_to_add = " ".join(context.args)
    messages = get_messages(context)
    messages.append(message_to_add)
    set_messages(context, messages)
    await update.message.reply_text(f"✅ Message added: '{message_to_add}'")

async def remove_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in OWNER_IDS:
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /remove <message_number>")
        return
    index_to_remove = int(context.args[0]) - 1
    messages = get_messages(context)
    if 0 <= index_to_remove < len(messages):
        removed_message = messages.pop(index_to_remove)
        set_messages(context, messages)
        await update.message.reply_text(f"✅ Message removed: '{removed_message}'")
    else:
        await update.message.reply_text("❌ Invalid message number.")

async def list_messages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in OWNER_IDS:
        return
    messages = get_messages(context)
    if not messages:
        await update.message.reply_text("📭 No messages saved. Use /add to add some.")
        return
    response = "📋 Saved messages:\n"
    for i, msg in enumerate(messages):
        response += f"{i+1}. {msg}\n"
    await update.message.reply_text(response)

async def disable_bot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in OWNER_IDS:
        return
    set_bot_enabled(context, False)
    await update.message.reply_text("🔴 Bot disabled. Use /on to enable.")

async def enable_bot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in OWNER_IDS:
        return
    set_bot_enabled(context, True)
    await update.message.reply_text("🟢 Bot enabled.")

async def handle_b_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in OWNER_IDS:
        return

    if not is_bot_enabled(context):
        await update.message.reply_text("🔴 Bot is disabled. Use /on to enable.")
        return

    if not update.message.reply_to_message:
        await update.message.reply_text("💡 Reply to someone's message with /b to send pre-written messages.")
        return

    target_user = update.message.reply_to_message.from_user
    if target_user.username:
        mention_string = f"@{target_user.username}"
    else:
        mention_string = target_user.first_name

    messages_to_send = get_messages(context)
    if not messages_to_send:
        await update.message.reply_text("📭 No pre-written messages. Use /add to add some.")
        return

    # Delete the owner's /b command message
    try:
        await update.message.delete()
    except Exception as e:
        logger.warning(f"Could not delete message: {e}")

    # Send messages as standalone messages in the group
    chat_id = update.message.chat_id
    for msg in messages_to_send:
        await context.bot.send_message(chat_id=chat_id, text=f"{mention_string} {msg}")
        await asyncio.sleep(0.5)

async def post_init(application: Application) -> None:
    commands = [
        BotCommand("add", "Add a pre-written message"),
        BotCommand("remove", "Remove a message by number"),
        BotCommand("list", "List all saved messages"),
        BotCommand("b", "Send messages to replied user"),
        BotCommand("on", "Enable bot"),
        BotCommand("d", "Disable bot"),
    ]
    await application.bot.set_my_commands(commands)
    logger.info("Bot commands set.")

def main() -> None:
    # Start web server in background thread (for Render health check)
    web_thread = threading.Thread(target=start_web_server, daemon=True)
    web_thread.start()
    logger.info(f"Web server started on port {PORT}")

    # Start self-ping in background thread
    ping_thread = threading.Thread(target=self_ping, daemon=True)
    ping_thread.start()
    logger.info("Self-ping thread started (every 4 minutes)")

    # Use PicklePersistence to save bot_data to disk
    persistence = PicklePersistence(filepath="bot_persistence.pkl")

    # Start bot
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .persistence(persistence)
        .post_init(post_init)
        .build()
    )
    application.add_handler(CommandHandler("add", add_message))
    application.add_handler(CommandHandler("remove", remove_message))
    application.add_handler(CommandHandler("list", list_messages))
    application.add_handler(CommandHandler("b", handle_b_command))
    application.add_handler(CommandHandler("on", enable_bot))
    application.add_handler(CommandHandler("d", disable_bot))
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
