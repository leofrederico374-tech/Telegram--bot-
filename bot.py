import logging
import json
import os
import asyncio
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.request
from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, ContextTypes

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# Bot token and owner ID
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8573621777:AAExY5voLcOKBwB_DHi8RY5QC-PXUIZCR6Y")
OWNER_ID = int(os.environ.get("OWNER_ID", "6852704459"))
MESSAGES_FILE = "messages.json"
BOT_STATE_FILE = "bot_state.json"
RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL", "https://telegram-bot-8hpa.onrender.com")
PORT = int(os.environ.get("PORT", "10000"))

# ===== Self-ping to keep Render alive =====
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot is alive!")
    def log_message(self, format, *args):
        pass  # Suppress logs

def start_web_server():
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    server.serve_forever()

def self_ping():
    """Ping self every 4 minutes to prevent Render from sleeping"""
    import time
    while True:
        time.sleep(240)  # 4 minutes
        try:
            urllib.request.urlopen(RENDER_URL)
            logger.info("Self-ping successful")
        except Exception as e:
            logger.warning(f"Self-ping failed: {e}")

# ===== Bot functions =====
def load_messages():
    try:
        with open(MESSAGES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def save_messages(messages):
    with open(MESSAGES_FILE, "w", encoding="utf-8") as f:
        json.dump(messages, f, indent=4, ensure_ascii=False)

def load_bot_state():
    try:
        with open(BOT_STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"enabled": True}

def save_bot_state(state):
    with open(BOT_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=4, ensure_ascii=False)

async def add_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != OWNER_ID:
        return
    if not context.args:
        await update.message.reply_text("Usage: /add <message>")
        return
    message_to_add = " ".join(context.args)
    messages = load_messages()
    messages.append(message_to_add)
    save_messages(messages)
    await update.message.reply_text(f"Message added: '{message_to_add}'")

async def remove_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != OWNER_ID:
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /remove <message_number>")
        return
    index_to_remove = int(context.args[0]) - 1
    messages = load_messages()
    if 0 <= index_to_remove < len(messages):
        removed_message = messages.pop(index_to_remove)
        save_messages(messages)
        await update.message.reply_text(f"Message removed: '{removed_message}'")
    else:
        await update.message.reply_text("Invalid message number.")

async def list_messages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != OWNER_ID:
        return
    messages = load_messages()
    if not messages:
        await update.message.reply_text("No messages saved.")
        return
    response = "Saved messages:\n"
    for i, msg in enumerate(messages):
        response += f"{i+1}. {msg}\n"
    await update.message.reply_text(response)

async def disable_bot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != OWNER_ID:
        return
    state = load_bot_state()
    state["enabled"] = False
    save_bot_state(state)
    await update.message.reply_text("Bot disabled.")

async def handle_b_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != OWNER_ID:
        return

    bot_state = load_bot_state()
    if bot_state.get("enabled", True) == False:
        await update.message.reply_text("Bot is disabled.")
        return

    if not update.message.reply_to_message:
        # If not replying, enable the bot
        state = load_bot_state()
        state["enabled"] = True
        save_bot_state(state)
        await update.message.reply_text("Bot enabled.")
        return

    target_user = update.message.reply_to_message.from_user
    if target_user.username:
        mention_string = f"@{target_user.username}"
    else:
        mention_string = target_user.first_name

    messages_to_send = load_messages()
    if not messages_to_send:
        await update.message.reply_text("No pre-written messages. Use /add to add some.")
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
    logger.info("Self-ping thread started")

    # Start bot
    application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    application.add_handler(CommandHandler("add", add_message))
    application.add_handler(CommandHandler("remove", remove_message))
    application.add_handler(CommandHandler("list", list_messages))
    application.add_handler(CommandHandler("b", handle_b_command))
    application.add_handler(CommandHandler("d", disable_bot))
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
