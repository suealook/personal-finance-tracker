import logging

from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from bot import handlers
from common.heartbeat import write_heartbeat
from config import settings

logging.basicConfig(
    format="%(asctime)s %(name)s %(levelname)s %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL_SECONDS = 30


async def _heartbeat_job(context):
    write_heartbeat("bot")


def build_application() -> Application:
    if not settings.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set — check your .env file.")
    if not settings.TELEGRAM_ALLOWED_USER_ID:
        raise RuntimeError("TELEGRAM_ALLOWED_USER_ID is not set — check your .env file.")

    app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", handlers.cmd_start))
    app.add_handler(CommandHandler("help", handlers.cmd_help))
    app.add_handler(CommandHandler("undo", handlers.cmd_undo))
    app.add_handler(CommandHandler("correct", handlers.cmd_correct))
    app.add_handler(CommandHandler("categories", handlers.cmd_categories))
    app.add_handler(CommandHandler("addcategory", handlers.cmd_addcategory))
    app.add_handler(CommandHandler("summary", handlers.cmd_summary))
    app.add_handler(CallbackQueryHandler(handlers.on_category_confirm, pattern=r"^cat_confirm:"))
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
