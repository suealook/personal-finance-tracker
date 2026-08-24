import logging
import uuid

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.auth import restricted
from common import categories as categories_module
from common import sheets_client
from common.dateutil_helpers import current_month, month_bounds, now_str
from common.llm_analysis import quick_tip
from common.llm_parse import parse_transaction, parse_transaction_from_image

logger = logging.getLogger(__name__)

HELP_TEXT = (
    "Text me a transaction (\"spent 12.50 on coffee at starbucks\") or send a photo "
    "of a receipt — either logs it.\n\n"
    "Commands:\n"
    "/undo - remove the last transaction I logged\n"
    "/correct <field> <value> - fix the last transaction, e.g. /correct amount 15.00\n"
    "/categories - list active categories\n"
    "/addcategory <name> <type> - add a category (type: Expense/Income/Savings/Debt)\n"
    "/summary - month-to-date income and spending by category\n"
    "/help - show this message"
)

CORRECTABLE_FIELDS = {"amount", "category", "note", "date"}


def _write_transaction(parsed: dict, raw_row_index: int, msg_id: str) -> dict:
    txn_id = str(uuid.uuid4())
    row = {
        "TransactionID": txn_id,
        "Date": parsed["date"],
        "Amount": parsed["amount"],
        "Category": parsed["category"],
        "Note": parsed.get("note", ""),
        "Source": "telegram",
        "LoggedAt": now_str(),
        "TelegramMsgID": msg_id,
        "Status": "active",
    }
    sheets_client.append_transaction(row)
    sheets_client.update_raw_log(raw_row_index, "parsed", txn_id)
    return row


def _confirmation_text(row: dict) -> str:
    note_suffix = f" ({row['Note']})" if row.get("Note") else ""
    return (
        f"Logged: {row['Amount']} - {row['Category']}{note_suffix} on {row['Date']}.\n"
        "Tap Undo below, or /correct <field> <value> to fix."
    )


def _undo_keyboard(transaction_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("Undo", callback_data=f"undo_txn:{transaction_id}")]])


async def _finalize_transaction(parsed: dict, raw_row_index: int, msg_id: str, reply_fn) -> dict:
    """Writes the transaction and sends the confirmation (with an Undo button)
    via whichever mechanism the caller needs — a new message (on_message,
    on_photo) or editing an existing one (on_category_confirm)."""
    row = _write_transaction(parsed, raw_row_index, msg_id)
    await reply_fn(_confirmation_text(row), _undo_keyboard(row["TransactionID"]))
    return row


async def _process_parsed(
    parsed: dict,
    raw_row_index: int,
    msg_id: str,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    active_categories: list[str],
):
    """Shared continuation once a message or photo has been parsed into a
    candidate transaction: confirm a brand-new category before writing
    anything, otherwise finalize immediately."""
    if categories_module.resolve_category(parsed, active_categories):
        context.chat_data["pending"] = {
            "parsed": parsed,
            "raw_row_index": raw_row_index,
            "msg_id": msg_id,
        }
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("Yes, create it", callback_data="cat_confirm:yes"),
                    InlineKeyboardButton("No, cancel", callback_data="cat_confirm:no"),
                ]
            ]
        )
        await update.message.reply_text(
            f"'{parsed['category']}' isn't an existing category "
            f"(type: {parsed.get('category_type', 'Expense')}). Create it?",
            reply_markup=keyboard,
        )
        return

    async def _reply(text, markup):
        await update.message.reply_text(text, reply_markup=markup)

    await _finalize_transaction(parsed, raw_row_index, msg_id, _reply)


@restricted
async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if not text:
        return
    user = update.effective_user

    raw_row = {
        "Timestamp": now_str(),
        "TelegramUserID": str(user.id),
        "TelegramUsername": user.username or "",
        "RawText": text,
        "ParseStatus": "pending",
        "LinkedTransactionID": "",
    }
    raw_row_index = sheets_client.append_raw_log(raw_row)

    try:
        active_categories = categories_module.get_active_categories()
        parsed = parse_transaction(text, active_categories)
    except Exception:
        logger.exception("Failed to parse message: %r", text)
        sheets_client.update_raw_log(raw_row_index, "failed")
        await update.message.reply_text(
            "Couldn't parse that one — saved to the raw log so nothing's lost. "
            "Try rephrasing, e.g. \"12.50 coffee\"."
        )
        return

    await _process_parsed(parsed, raw_row_index, str(update.message.message_id), update, context, active_categories)


@restricted
async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    caption = (update.message.caption or "").strip()

    raw_row = {
        "Timestamp": now_str(),
        "TelegramUserID": str(user.id),
        "TelegramUsername": user.username or "",
        "RawText": "[receipt photo]" + (f": {caption}" if caption else ""),
        "ParseStatus": "pending",
        "LinkedTransactionID": "",
    }
    raw_row_index = sheets_client.append_raw_log(raw_row)

    try:
        photo = update.message.photo[-1]  # largest available size
        photo_file = await context.bot.get_file(photo.file_id)
        image_bytes = bytes(await photo_file.download_as_bytearray())
        active_categories = categories_module.get_active_categories()
        parsed = parse_transaction_from_image(image_bytes, active_categories, caption=caption or None)
    except Exception:
        logger.exception("Failed to parse receipt photo")
        sheets_client.update_raw_log(raw_row_index, "failed")
        await update.message.reply_text(
            "Couldn't read that receipt — saved to the raw log so nothing's lost."
        )
        return

    await _process_parsed(parsed, raw_row_index, str(update.message.message_id), update, context, active_categories)


@restricted
async def on_category_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pending = context.chat_data.pop("pending", None)
    if not pending:
        await query.edit_message_text("Nothing pending to confirm.")
        return

    if query.data == "cat_confirm:yes":
        parsed = pending["parsed"]
        try:
            categories_module.add_category(
                parsed["category"], parsed.get("category_type", "Expense")
            )
        except ValueError:
            pass  # category already exists (race with /addcategory) - fine, just use it

        async def _reply(text, markup):
            await query.edit_message_text(text, reply_markup=markup)

        await _finalize_transaction(parsed, pending["raw_row_index"], pending["msg_id"], _reply)
    else:
        sheets_client.update_raw_log(pending["raw_row_index"], "failed")
        await query.edit_message_text("Cancelled. Nothing logged.")


@restricted
async def on_undo_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    transaction_id = query.data.split(":", 1)[1]
    try:
        txn = sheets_client.get_transaction_by_id(transaction_id)
        if not txn or txn.get("Status") != "active":
            await query.edit_message_text("Already undone (or not found).")
            return
        sheets_client.undo_transaction(txn["_row"])
    except Exception:
        logger.exception("Failed to undo transaction_id=%s", transaction_id)
        await query.edit_message_text("Couldn't undo that one — please try again.")
        return
    await query.edit_message_text(f"Undone: {txn['Amount']} - {txn['Category']} on {txn['Date']}.")


@restricted
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT)


@restricted
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT)


@restricted
async def cmd_undo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    last = sheets_client.get_last_transaction_for_source("telegram")
    if not last:
        await update.message.reply_text("Nothing to undo.")
        return
    sheets_client.undo_transaction(last["_row"])
    await update.message.reply_text(
        f"Undone: {last['Amount']} - {last['Category']} on {last['Date']}."
    )


@restricted
async def cmd_correct(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "Usage: /correct <field> <value>  (fields: amount, category, note, date)"
        )
        return
    field, value = args[0].lower(), " ".join(args[1:])
    if field not in CORRECTABLE_FIELDS:
        await update.message.reply_text(f"Field must be one of: {', '.join(sorted(CORRECTABLE_FIELDS))}")
        return

    last = sheets_client.get_last_transaction_for_source("telegram")
    if not last:
        await update.message.reply_text("No transaction to correct.")
        return

    column = {"amount": "Amount", "category": "Category", "note": "Note", "date": "Date"}[field]
    if field == "amount":
        try:
            value = float(value)
        except ValueError:
            await update.message.reply_text("Amount must be a number.")
            return
    if field == "category":
        # Same validation _resolve_category applies to the auto-parsed path —
        # writing an unrecognized category string here would silently orphan
        # the transaction from every Type-based rollup (dashboard income/
        # spend split, budgets, variance) exactly like the bug that path was
        # just fixed for, just through this manual entry point instead.
        active = categories_module.get_active_categories()
        match = next((c for c in active if c.lower() == value.lower()), None)
        if match is None:
            await update.message.reply_text(
                f"'{value}' isn't an existing category. Use /addcategory {value} <type> first, or check the spelling."
            )
            return
        value = match  # normalize to the category's real casing
    sheets_client.update_transaction_field(last["_row"], column, value)
    await update.message.reply_text(f"Updated {field} to: {value}")


@restricted
async def cmd_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    active = categories_module.get_active_category_records()
    if not active:
        await update.message.reply_text("No active categories yet. Use /addcategory <name> <type>.")
        return

    grouped: dict[str, list[str]] = {}
    group_order: list[str] = []
    for c in active:
        group = c.get("Group") or "Other"
        if group not in grouped:
            grouped[group] = []
            group_order.append(group)
        grouped[group].append(c["Category"])

    lines = ["Active categories (priority order):"]
    for group in group_order:
        lines.append(f"\n{group}:")
        lines.extend(f"- {name}" for name in grouped[group])
    await update.message.reply_text("\n".join(lines))


@restricted
async def cmd_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    month = current_month()
    start, end = month_bounds(month)
    txns = sheets_client.get_actual(start_date=start, end_date=end)
    cat_types = {c["Category"]: c["Type"] for c in categories_module.get_all_categories()}

    income_total = 0.0
    spend_by_cat: dict[str, float] = {}
    for t in txns:
        amt = float(t.get("Amount") or 0)
        cat = t.get("Category", "(uncategorized)")
        if cat_types.get(cat) == "Income":
            income_total += amt
        else:
            spend_by_cat[cat] = spend_by_cat.get(cat, 0.0) + amt
    spend_total = sum(spend_by_cat.values())

    lines = [f"Summary for {month} (month to date)", "", f"Income: {income_total:,.2f}", ""]
    lines.append("Spending by category:")
    if spend_by_cat:
        for cat, amt in sorted(spend_by_cat.items(), key=lambda kv: -kv[1]):
            lines.append(f"- {cat}: {amt:,.2f}")
    else:
        lines.append("(none yet)")
    lines.append("")
    lines.append(f"Total spending: {spend_total:,.2f}")
    lines.append(f"Net: {income_total - spend_total:+,.2f}")

    try:
        tip = quick_tip(month)
    except Exception:
        logger.exception("quick_tip failed for /summary")
        tip = None
    if tip:
        lines.append("")
        lines.append(f"Tip: {tip}")

    await update.message.reply_text("\n".join(lines))


@restricted
async def cmd_addcategory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "Usage: /addcategory <name> <type>  (type: Expense/Income/Savings/Debt)"
        )
        return
    name, type_ = " ".join(args[:-1]), args[-1]
    try:
        categories_module.add_category(name, type_)
    except ValueError as e:
        await update.message.reply_text(str(e))
        return
    await update.message.reply_text(f"Added category '{name}' ({type_.title()}).")
