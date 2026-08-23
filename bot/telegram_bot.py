import logging

from telegram import BotCommand
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from bot import handlers
from common import users as users_module
from common.heartbeat import write_heartbeat
from config import settings

logging.basicConfig(
    format="%(asctime)s %(name)s %(levelname)s %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL_SECONDS = 30

# Single source of truth for slash commands: both the handler registration
# and Telegram's native "/" command menu read from this table, so the two
# can never drift out of sync with each other.
COMMANDS = [
    ("start", "Show help", handlers.cmd_start),
    ("help", "Show help", handlers.cmd_help),
    ("summary", "Month-to-date income and spending", handlers.cmd_summary),
    ("categories", "List active categories", handlers.cmd_categories),
    ("addcategory", "Add a category: /addcategory <name> <type>", handlers.cmd_addcategory),
    ("undo", "Remove the last transaction", handlers.cmd_undo),
    ("correct", "Fix the last transaction: /correct <field> <value>", handlers.cmd_correct),
]


async def _heartbeat_job(context):
    write_heartbeat("bot")


async def _post_init(app: Application):
    await app.bot.set_my_commands([BotCommand(name, description) for name, description, _ in COMMANDS])


def build_application() -> Application:
    if not settings.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set — check your .env file.")
    if not users_module.any_users_configured():
        raise RuntimeError("No users configured in data/users.json — see SETUP.md.")

    app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).post_init(_post_init).build()

    for name, _description, handler_fn in COMMANDS:
        app.add_handler(CommandHandler(name, handler_fn))

    app.add_handler(CallbackQueryHandler(handlers.on_category_confirm, pattern=r"^cat_confirm:"))
    app.add_handler(CallbackQueryHandler(handlers.on_undo_button, pattern=r"^undo_txn:"))
    app.add_handler(MessageHandler(filters.PHOTO, handlers.on_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.on_message))

    if app.job_queue is not None:
        app.job_queue.run_repeating(_heartbeat_job, interval=HEARTBEAT_INTERVAL_SECONDS, first=0)
    else:
        logger.warning("JobQueue unavailable — bot heartbeat for the /update status page is disabled.")

    return app


def main():
    app = build_application()
    logger.info("Starting Telegram bot (long polling)...")
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
