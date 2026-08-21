import functools
import logging

from telegram import Update
from telegram.ext import ContextTypes

from config import settings

logger = logging.getLogger(__name__)


def restricted(func):
    """Decorator for handlers: silently ignores anyone but TELEGRAM_ALLOWED_USER_ID."""

    @functools.wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        user_id = str(user.id) if user else None
        if not settings.TELEGRAM_ALLOWED_USER_ID or user_id != settings.TELEGRAM_ALLOWED_USER_ID:
            logger.warning(
                "Ignored message from unauthorized user_id=%s username=%s",
                user_id, user.username if user else None,
            )
            return
        return await func(update, context, *args, **kwargs)

    return wrapped
