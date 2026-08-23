import functools
import logging

from telegram import Update
from telegram.ext import ContextTypes

from common import sheets_client
from common import users as users_module

logger = logging.getLogger(__name__)


def restricted(func):
    """Decorator for handlers: silently ignores anyone not listed in
    data/users.json, and points sheets_client at that sender's own sheet for
    the duration of this update — this one call is what makes every Sheets
    call inside the handler (and anything it calls) target the right user
    without threading a sheet id through each of them individually."""

    @functools.wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        user_id = str(user.id) if user else None
        matched = users_module.get_user_by_telegram_id(user_id) if user_id else None
        if matched is None:
            logger.warning(
                "Ignored message from unauthorized user_id=%s username=%s",
                user_id, user.username if user else None,
            )
            return
        sheets_client.set_current_sheet(matched["sheet_id"])
        return await func(update, context, *args, **kwargs)

    return wrapped
